"""Observed failures never grant retries or change execution policy."""

import copy
import json
import hashlib
import stat
from pathlib import Path
import re
import subprocess

from stage2_common import Stage2Error


def _primary_failure(error):
    response = getattr(error, "response", None)
    codes = (
        getattr(error, "status_code", None),
        getattr(response, "status_code", None),
        getattr(error, "code", None),
    )
    for code in codes:
        if type(code) is int and code in (401, 429):
            return "authentication" if code == 401 else "rate-limit"
    match = re.search(r"\bHTTP(?:\s+status)?[: =]+(401|429)\b", str(error), re.I)
    if match:
        return "authentication" if match.group(1) == "401" else "rate-limit"
    if isinstance(error, (TimeoutError, subprocess.TimeoutExpired)):
        return "timeout"
    if isinstance(error, json.JSONDecodeError):
        return "format"
    if str(error).startswith(("native-cleanup-", "controller-cleanup-")):
        return "cleanup"
    return "unknown"


def _cleanup_status(report):
    if not isinstance(report, dict):
        return "not-reported"
    if (
        report.get("errors")
        or report.get("reap_status") in {"timeout", "error"}
        or report.get("tree_kill_status")
        in {"timeout", "error", "not-attempted-unconfirmed-ownership"}
    ):
        return "failed"
    return "complete" if report.get("reap_status") == "complete" else "unknown"


def describe_controller_failure(error):
    """Retain primary failure and cleanup independently; unknown stays unknown."""
    if isinstance(error, ControllerNativeFailure):
        return copy.deepcopy(error.observation)
    primary = _primary_failure(error)
    cleanup = _cleanup_status(getattr(error, "cleanup_report", None))
    return {
        "failure_class": "cleanup" if cleanup == "failed" else primary,
        "primary_failure_class": primary,
        "cleanup_status": cleanup,
        "error_type": type(error).__name__,
        "retry_authorized": False,
    }


def classify_controller_failure(error):
    return describe_controller_failure(error)["failure_class"]


def _native_provider_observation(capture, capture_dir):
    """Read only receipt-bound native error events, never agent/tool text."""
    observed = {"state": "unavailable", "codes": [], "events": []}
    if capture_dir is None or capture.get("status") == "complete":
        return observed
    try:
        root = Path(capture_dir)

        def retained(name, digest, maximum):
            path = root / name
            status = path.lstat()
            if (
                path.is_symlink()
                or getattr(status, "st_file_attributes", 0) & 0x400
                or not stat.S_ISREG(status.st_mode)
                or status.st_size > maximum
            ):
                raise ValueError("native-failure-evidence-not-regular-or-bounded")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("native-failure-evidence-hash-mismatch")
            return raw

        record = json.loads(
            retained("run.json", capture.get("record_sha256_receipt"), 4 << 20)
        )
        returned = {
            key: value
            for key, value in capture.items()
            if key != "record_sha256_receipt"
        }
        if record != returned or record.get("kind") != "Stage2NativeCapture":
            raise ValueError("native-failure-record-mismatch")
        files = record["archived_files"]
        stdout = retained("stdout.jsonl", files["stdout.jsonl"], 64 << 20)
        stderr = retained("stderr.txt", files["stderr.txt"], 4 << 20)
        observed["state"] = "verified"
        for number, line in enumerate(stdout.decode("utf-8").splitlines(), 1):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict) or event.get("type") not in {
                "error",
                "turn.failed",
            }:
                continue
            error = event.get("error") if event["type"] == "turn.failed" else event
            if not isinstance(error, dict):
                continue
            code = error.get("status_code", error.get("http_status_code"))
            message = error.get("message")
            match = re.search(
                r"\bHTTP(?:\s+status)?[: =]+(401|429)\b", message or "", re.I
            )
            if type(code) is not int or code not in {401, 429}:
                code = int(match.group(1)) if match else None
            if code is not None:
                observed["codes"].append(code)
                observed["events"].append(
                    {"source": "stdout.jsonl", "line": number, "code": code}
                )
        if type(record.get("exit_code")) is int and record["exit_code"] != 0:
            for number, line in enumerate(stderr.decode("utf-8").splitlines(), 1):
                match = re.match(
                    r"\s*(?:ERROR:|Error:|error:)\s+.*?\bHTTP(?:\s+status)?[: =]+(401|429)\b",
                    line,
                )
                if match:
                    code = int(match.group(1))
                    observed["codes"].append(code)
                    observed["events"].append(
                        {"source": "stderr.txt", "line": number, "code": code}
                    )
        observed["codes"] = sorted(set(observed["codes"]))
        observed["events"] = observed["events"][:16]
    except (OSError, ValueError, KeyError, TypeError) as error:
        observed = {
            "state": "unavailable",
            "codes": [],
            "events": [],
            "error_type": type(error).__name__,
        }
    return observed


class ControllerNativeFailure(Stage2Error):
    """Preserve the returned capture's failure observations, not an execution proof."""

    def __init__(self, capture, capture_dir=None):
        exception = capture.get("exception") or {}
        error_type = exception.get("type")
        primary = (
            "timeout"
            if error_type in {"TimeoutExpired", "TimeoutError"}
            else "format"
            if error_type == "JSONDecodeError"
            or capture.get("event_summary", {}).get("parse_error")
            else _primary_failure(RuntimeError(str(exception.get("message", ""))))
        )
        provider = _native_provider_observation(capture, capture_dir)
        if primary == "unknown" and len(provider["codes"]) == 1:
            primary = "authentication" if provider["codes"][0] == 401 else "rate-limit"
        cleanup = _cleanup_status(exception.get("cleanup_report"))
        self.observation = {
            "failure_class": "cleanup" if cleanup == "failed" else primary,
            "primary_failure_class": primary,
            "cleanup_status": cleanup,
            "error_type": error_type,
            "capture_status": capture.get("status"),
            "provider_observation": provider,
            "capture_record_sha256": capture.get("record_sha256_receipt"),
            "retry_authorized": False,
        }
        super().__init__(
            "controller-native-capture-incomplete: "
            + str(capture.get("status", "unknown"))
        )

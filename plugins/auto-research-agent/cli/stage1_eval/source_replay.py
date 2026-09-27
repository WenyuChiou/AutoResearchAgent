"""Offline source replay through the pinned, documented research-hub CLI."""

import json
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .common import EvaluationError, canonical, sha

EVENT_KIND = "Stage1SourceReplayEvent.v1"
REPORT_SCHEMA = "source-fetch-validation/v1"


def replay_source_bytes(result_path, prefix, journal_path):
    """Re-extract saved bytes; this performs no source acquisition or judging."""
    result_path, journal_path = Path(result_path), Path(journal_path)
    if (
        not isinstance(prefix, list)
        or not prefix
        or any(not isinstance(arg, str) or not arg for arg in prefix)
    ):
        raise EvaluationError("source replay requires a bound command prefix")
    result_bytes = result_path.read_bytes()
    command = prefix + ["source", "validate", str(result_path), "--json"]
    result_sha256 = sha(result_bytes)
    previous = []
    if journal_path.exists():
        try:
            previous = [
                json.loads(line) for line in journal_path.read_bytes().splitlines()
            ]
        except (ValueError, UnicodeError) as exc:
            raise EvaluationError("source replay journal is invalid") from exc
        if (
            not previous
            or len(previous) % 2
            or any(
                not isinstance(event, dict) or event.get("kind") != EVENT_KIND
                for event in previous
            )
        ):
            raise EvaluationError("unfinished or invalid source replay is preserved")
        for request, outcome in zip(previous[::2], previous[1::2], strict=True):
            if (
                request.get("event") != "registered"
                or outcome.get("event") != "finished"
                or not request.get("attempt_id")
                or request["attempt_id"] != outcome.get("attempt_id")
                or outcome.get("validation_passed") is not True
            ):
                raise EvaluationError(
                    "failed source replay is preserved; use a new archive after diagnosis"
                )
            try:
                if (
                    request.get("command") != command
                    or request.get("result_sha256") != result_sha256
                    or any(
                        outcome.get(key) != value
                        for key, value in request.items()
                        if key not in {"event", "observed_at"}
                    )
                    or outcome.get("status") != "completed"
                    or outcome.get("returncode") != 0
                    or any(
                        sha(bytes.fromhex(outcome[field + "_hex"]))
                        != outcome[field + "_sha256"]
                        for field in ("stdout", "stderr")
                    )
                ):
                    raise ValueError("changed journal binding")
            except (KeyError, TypeError, ValueError) as exc:
                raise EvaluationError("source replay journal binding changed") from exc
    request = {
        "kind": EVENT_KIND,
        "attempt_id": uuid.uuid4().hex,
        "command": command,
        "result_sha256": result_sha256,
        "timeout_seconds": 120,
        "counts_as_source_acquisition": False,
    }
    journal_path.parent.mkdir(parents=True, exist_ok=True)

    def append(event):
        with journal_path.open("ab") as stream:
            stream.write(canonical({**request, **event}) + b"\n")

    append(
        {"event": "registered", "observed_at": datetime.now(timezone.utc).isoformat()}
    )
    try:
        completed = subprocess.run(
            request["command"],
            capture_output=True,
            timeout=120,
            check=False,
            shell=False,
        )
        stdout, stderr, code, status = (
            completed.stdout,
            completed.stderr,
            completed.returncode,
            "completed",
        )
    except subprocess.TimeoutExpired as exc:
        stdout, stderr, code, status = (
            exc.stdout or b"",
            exc.stderr or b"",
            None,
            "timeout",
        )
    except OSError as exc:
        stdout, stderr, code, status = (
            b"",
            str(exc).encode("utf-8"),
            None,
            "spawn-error",
        )
    error, report = None, None
    if status != "completed" or code != 0:
        error = f"source replay CLI did not complete: {status}, exit={code}"
    else:
        try:
            report = json.loads(stdout)
        except (ValueError, UnicodeError):
            error = "source replay CLI returned invalid JSON"
        if error is None:
            try:
                source = json.loads(result_bytes)
                unchanged = result_path.read_bytes() == result_bytes
            except (ValueError, UnicodeError, OSError):
                source, unchanged = None, False
            if (
                not isinstance(report, dict)
                or report.get("schema_version") != REPORT_SCHEMA
                or report.get("valid") is not True
                or report.get("errors") != []
                or not isinstance(source, dict)
                or not unchanged
                or not isinstance(source.get("receipt_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", source["receipt_sha256"]) is None
                or not isinstance(source.get("source_version"), str)
                or any(
                    report.get(key) != source.get(key)
                    for key in ("receipt_sha256", "source_version")
                )
                or report.get("result_path") != str(result_path.resolve())
            ):
                error = "public source bytes fail pinned CLI replay or report binding"
    append(
        {
            "event": "finished",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "returncode": code,
            "stdout_hex": stdout.hex(),
            "stderr_hex": stderr.hex(),
            "stdout_sha256": sha(stdout),
            "stderr_sha256": sha(stderr),
            "validation_passed": error is None,
            "error": error,
        }
    )
    if error:
        raise EvaluationError(error)
    return report

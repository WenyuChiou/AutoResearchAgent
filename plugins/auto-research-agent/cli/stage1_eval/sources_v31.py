"""Public-source CLI adapter with per-work immutable acquisition receipts."""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .collector import _doi, _title, collect_subject_sources, rebuild_subject_sources
from .common import EvaluationError, canonical, read_json, sha, write_json
from .extraction_v31 import work_id_for
from .runtime import executable_sha256, installed_package_sha256


FETCH_RECEIPT_VERSION = "Stage1PublicSourceFetchReceipt.v1"
VALIDATION_RECEIPT_VERSION = "Stage1PublicSourceValidationReceipt.v1"
SOURCE_STATUSES = {
    "available",
    "inaccessible",
    "rate-limited",
    "parse-error",
    "identity-mismatch",
}


def _replay_source_bytes(result_path):
    # Pure offline replay is mandatory even if every saved checksum was updated.
    # It does not repeat acquisition or invoke another model.
    from research_hub.source_fetch import validate_source_fetch

    report = validate_source_fetch(result_path)
    if not isinstance(report, dict) or report.get("valid") is not True:
        raise EvaluationError("public source bytes fail offline extraction replay")
    return report


def _persist(path, value):
    if path.exists():
        if canonical(read_json(path)) != canonical(value):
            raise EvaluationError(f"source archive changed: {path.name}")
    else:
        write_json(path, value)


def _metadata(work, spec, directory, command, replay_only):
    path = directory / "result.json"
    single = {"works": [work]}
    if not path.exists():
        if replay_only:
            raise EvaluationError(f"missing metadata unit: {work['work_id']}")
        result = collect_subject_sources(single, spec, directory, command)
        _persist(path, result)
    result = read_json(path)
    raw = directory / "raw"
    for receipt in result["receipts"]:
        for field in ("stdout", "stderr"):
            name = receipt[field + "_path"]
            if (
                Path(name).name != name
                or sha((raw / name).read_bytes()) != receipt[field + "_sha256"]
            ):
                raise EvaluationError(f"metadata receipt mismatch: {work['work_id']}")
    expected = rebuild_subject_sources(single, spec, result["receipts"], raw)
    if canonical(expected) != canonical(result["sources"]):
        raise EvaluationError(
            f"metadata source reconstruction failed: {work['work_id']}"
        )
    return result


def _runtime_binding(command):
    return {
        "command": command,
        "executable_sha256": executable_sha256(command[0]),
        "research_hub_package_sha256": installed_package_sha256("research_hub"),
    }


def _verify_capture(directory, receipt, names):
    for name, key in names:
        path = directory / name
        if not path.is_file() or sha(path.read_bytes()) != receipt.get(key):
            raise EvaluationError("source-fetch raw capture changed")


def _validate_fetch(prefix, directory, result_path, replay_only):
    validation_dir = directory / "validation"
    request_path = validation_dir / "request.json"
    receipt_path = validation_dir / "receipt.json"
    stdout_path = validation_dir / "stdout.json"
    stderr_path = validation_dir / "stderr.txt"
    command = prefix + ["source", "validate", str(result_path), "--json"]
    binding = {
        "kind": VALIDATION_RECEIPT_VERSION,
        **_runtime_binding(command),
        "result_path": str(result_path),
        "result_sha256": sha(result_path.read_bytes()),
    }
    had_receipt = receipt_path.exists()
    if not had_receipt:
        if request_path.exists() or validation_dir.exists():
            raise EvaluationError(
                "partial source validation is preserved and cannot be repeated"
            )
        if replay_only:
            raise EvaluationError("missing source validation receipt")
        validation_dir.mkdir(parents=True, exist_ok=False)
        _persist(request_path, binding)
        started = datetime.now(timezone.utc).isoformat()
        try:
            completed = subprocess.run(
                command, capture_output=True, timeout=120, check=False
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
                str(exc).encode(),
                None,
                "spawn-error",
            )
        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        _persist(
            receipt_path,
            {
                **binding,
                "started_at": started,
                "ended_at": datetime.now(timezone.utc).isoformat(),
                "status": status,
                "returncode": code,
                "stdout_sha256": sha(stdout),
                "stderr_sha256": sha(stderr),
            },
        )
    receipt = read_json(receipt_path)
    if read_json(request_path) != binding or any(
        receipt.get(key) != value for key, value in binding.items()
    ):
        raise EvaluationError("source validation request/runtime changed")
    _verify_capture(
        validation_dir,
        receipt,
        (("stdout.json", "stdout_sha256"), ("stderr.txt", "stderr_sha256")),
    )
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise EvaluationError("source raw-byte replay did not complete")
    try:
        report = json.loads(stdout_path.read_bytes())
    except (UnicodeError, ValueError) as exc:
        raise EvaluationError("source validator returned invalid JSON") from exc
    if not isinstance(report, dict) or report.get("valid") is not True:
        raise EvaluationError(
            "source raw-byte replay failed: "
            + str(report.get("errors") if isinstance(report, dict) else None)
        )
    saved_result = validation_dir / "result.json"
    if had_receipt and not saved_result.is_file():
        raise EvaluationError("completed source validation lost its saved result")
    _persist(saved_result, report)
    if canonical(read_json(saved_result)) != canonical(report):
        raise EvaluationError("saved source validation differs from captured stdout")
    replay = _replay_source_bytes(result_path)
    if canonical({k: v for k, v in replay.items() if k != "checked_at"}) != canonical(
        {k: v for k, v in report.items() if k != "checked_at"}
    ):
        raise EvaluationError(
            "saved source validation differs from actual offline replay"
        )
    return receipt, report


def _fetch(command, args, directory, request, replay_only):
    prefix = [sys.executable if p == "@python" else p for p in command]
    binding = {
        "kind": FETCH_RECEIPT_VERSION,
        **_runtime_binding(prefix + args),
        "request": request,
    }
    receipt_path = directory / "fetch-receipt.json"
    if not receipt_path.exists():
        if (directory / "request.json").exists() or directory.exists():
            raise EvaluationError(
                "partial source fetch is preserved and cannot be repeated"
            )
        if replay_only:
            raise EvaluationError("missing source-fetch receipt")
        directory.mkdir(parents=True, exist_ok=False)
        # Save intent before invoking the CLI. A partial attempt is never repeated.
        _persist(directory / "request.json", binding)
        started = datetime.now(timezone.utc).isoformat()
        try:
            result = subprocess.run(
                prefix + args, capture_output=True, timeout=600, check=False
            )
            stdout, stderr, code = result.stdout, result.stderr, result.returncode
            status = "completed"
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, code, status = (
                exc.stdout or b"",
                exc.stderr or b"",
                None,
                "timeout",
            )
        except OSError as exc:
            stdout, stderr, code, status = b"", str(exc).encode(), None, "spawn-error"
        (directory / "stdout.json").write_bytes(stdout)
        (directory / "stderr.txt").write_bytes(stderr)
        _persist(
            receipt_path,
            {
                **binding,
                "started_at": started,
                "ended_at": datetime.now(timezone.utc).isoformat(),
                "returncode": code,
                "status": status,
                "stdout_sha256": sha(stdout),
                "stderr_sha256": sha(stderr),
            },
        )
    receipt = read_json(receipt_path)
    if read_json(directory / "request.json") != binding or any(
        receipt.get(k) != v for k, v in binding.items()
    ):
        raise EvaluationError("source-fetch request/runtime changed")
    _verify_capture(
        directory,
        receipt,
        (("stdout.json", "stdout_sha256"), ("stderr.txt", "stderr_sha256")),
    )
    result_path = directory / "source/source-fetch-result.json"
    completed = receipt.get("status") == "completed"
    structured_exit = completed and receipt.get("returncode") in {0, 1}
    if structured_exit and not result_path.is_file():
        raise EvaluationError("completed source fetch lost its structured result")
    if not structured_exit:
        if result_path.exists():
            raise EvaluationError(
                "failed source fetch has an unexpected result artifact"
            )
        return None, receipt
    result = read_json(result_path)
    if not isinstance(result, dict) or result.get("request") != request:
        raise EvaluationError("source CLI result request differs from executed request")
    try:
        emitted = json.loads((directory / "stdout.json").read_bytes())
    except ValueError as exc:
        raise EvaluationError("source CLI did not emit its saved result") from exc
    if canonical(emitted) != canonical(result):
        raise EvaluationError("source CLI result differs from captured stdout")
    if result.get("status") not in SOURCE_STATUSES:
        raise EvaluationError("source CLI returned an unknown result status")
    expected_returncode = 0 if result.get("status") == "available" else 1
    if receipt.get("returncode") != expected_returncode:
        raise EvaluationError("source CLI exit code disagrees with result status")
    _validate_fetch(prefix, directory, result_path, replay_only)
    return result, receipt


def collect_sources_v31(extraction, spec, output, command, *, replay_only=False):
    root = Path(output)
    sources, receipts, fetched = [], [], []
    for work in extraction["works"]:
        # work IDs are deterministic extractor hashes, never caller-authored paths.
        work_id = work["work_id"]
        expected_work_id = work_id_for(work)
        if not re.fullmatch(r"work-[0-9a-f]{16}", str(work_id)) or (
            work_id != expected_work_id
        ):
            raise EvaluationError("unsafe extracted work ID")
        base = root / work_id
        metadata = _metadata(work, spec, base / "metadata", command, replay_only)
        sources.extend(metadata["sources"])
        receipts.extend(metadata["receipts"])
        candidates = metadata["sources"]
        doi = next((s["doi"] for s in candidates if s["doi"]), None) or _doi(
            work["identifier"]
        )
        url = next((s["url"] for s in candidates if s.get("url")), None)
        if not url and work["identifier"].startswith(("https://", "http://")):
            url = work["identifier"]
        if not doi and not url:
            fetched.append({"work_id": work_id, "status": "no-source-identifier"})
            continue
        directory = (base / "public-fetch").resolve()
        args = [
            "source",
            "fetch",
            "--title",
            work["title"],
            "--output-dir",
            str(directory / "source"),
            "--json",
        ]
        if doi:
            args += ["--doi", doi]
        if url:
            args += ["--url", url]
        request = {
            "operation": "source fetch",
            "doi": doi or "",
            "url": url or "",
            "title": work["title"],
            "output_dir": str(directory / "source"),
            "public_only": True,
        }
        result, receipt = _fetch(command, args, directory, request, replay_only)
        fetched.append({"work_id": work_id, "receipt": receipt, "result": result})
    return {"sources": sources, "receipts": receipts, "public_fetches": fetched}


def attach_public_sources(packet, source_result):
    """Add located source text; failed/uncertain identities remain unknown."""
    for entry in source_result["public_fetches"]:
        result = entry.get("result")
        if not result or result["status"] != "available":
            continue
        work_id = entry["work_id"]
        work = next(
            (row for row in packet["extraction"]["works"] if row["work_id"] == work_id),
            None,
        )
        if work is None:
            raise EvaluationError("public source references an unknown subject work")
        expected, observed = result["expected_identity"], result["observed_identity"]
        work_doi = _doi(work["identifier"])
        if expected.get("title") != work["title"] or (
            work_doi and _doi(expected.get("doi")) != work_doi
        ):
            raise EvaluationError("public source request differs from extracted work")
        identity_ok = result["identity_status"] == "verified" or (
            result["identity_status"] == "consistent"
            and _title(expected["title"]) == _title(observed["title"])
        )
        if not identity_ok:
            continue
        matching_metadata = [
            source
            for source in source_result["sources"]
            if source.get("subject_work_id") == work_id
            and source.get("date_status") != "after-cutoff"
            and (
                (
                    _doi(observed.get("doi"))
                    and _doi(source.get("doi")) == _doi(observed.get("doi"))
                )
                or _title(source.get("title")) == _title(observed.get("title"))
            )
        ]
        if not matching_metadata:
            continue
        metadata = matching_metadata[0]
        output_dir = Path(result["output_dir"]).resolve()
        text_path = Path(result["extracted_text_path"])
        if not text_path.is_absolute():
            text_path = output_dir / text_path
        text_path = text_path.resolve()
        try:
            text_path.relative_to(output_dir)
        except ValueError as exc:
            raise EvaluationError("public extracted text escapes fetch output") from exc
        text_bytes = text_path.read_bytes()
        if sha(text_bytes) != result["extracted_text_sha256"]:
            raise EvaluationError(f"public extracted text changed: {work_id}")
        text = text_bytes.decode("utf-8")
        if result["source_version"] != "sha256:" + result["raw_sha256"]:
            raise EvaluationError("public source version is not bound to raw bytes")
        locators = result.get("locators")
        if not isinstance(locators, list) or not locators:
            raise EvaluationError("public source has no replayed passage locators")
        for locator in locators:
            if (
                not isinstance(locator, dict)
                or not isinstance(locator.get("start"), int)
                or isinstance(locator.get("start"), bool)
                or not isinstance(locator.get("end"), int)
                or isinstance(locator.get("end"), bool)
                or locator["start"] < 0
                or locator["end"] <= locator["start"]
                or locator["end"] > len(text)
            ):
                raise EvaluationError("public source has an invalid passage locator")
        key = "src-public-" + sha(canonical([work_id, result["source_version"]]))[:16]
        packet["sources"][key] = {
            "source_id": key,
            "subject_work_id": work_id,
            "source_level": result["evidence_level"],
            "title": observed["title"],
            "doi": observed["doi"] or None,
            "url": result["final_url"],
            "work_key": "doi:" + observed["doi"]
            if observed["doi"]
            else "title:" + _title(observed["title"]),
            "version_id": result["source_version"],
            "authors": metadata.get("authors", []),
            "year": metadata.get("year"),
            "date_status": metadata["date_status"],
            "raw_sha256": result["raw_sha256"],
            "identity_status": result["identity_status"],
            "counts_as_subject_search": False,
        }
        packet["source_origins"][key] = ["evaluator-reference-check"]
        packet["content_evidence"][key] = {
            "text": text,
            "sha256": result["extracted_text_sha256"],
            "origin": "evaluator-reference-check",
            "subject_work_id": work_id,
            "source_version": result["source_version"],
            "artifact_path": str(text_path),
            "locator": locators,
        }
    packet["public_source_receipts"] = source_result["public_fetches"]
    return packet

"""Bounded independent research-hub source acquisition and challenge receipts."""

import json
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from .common import EvaluationError, canonical, check_spec, sha, write_json
from .runtime import executable_sha256, installed_package_sha256


def _run_hub(args, output_dir, label, hub_command, timeout=90):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / f"{label}.stdout.json"
    err_path = output_dir / f"{label}.stderr.txt"
    if raw_path.exists() or err_path.exists():
        raise EvaluationError(
            f"{label} already attempted; do not repeat a search silently"
        )
    command = [sys.executable if part == "@python" else part for part in hub_command]
    command.extend(args)
    try:
        executable_hash = executable_sha256(command[0])
    except EvaluationError:
        executable_hash = None
    try:
        package_hash = installed_package_sha256("research_hub")
    except EvaluationError:
        package_hash = None
    started = datetime.now(timezone.utc).isoformat()
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=timeout, check=False
        )
        status = "results" if result.returncode == 0 else "backend-failure"
        stdout, stderr = result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        stdout, stderr = exc.stdout or b"", exc.stderr or b""
    raw_path.write_bytes(stdout)
    err_path.write_bytes(stderr)
    receipt = {
        "command": command,
        "executable_sha256": executable_hash,
        "research_hub_package_sha256": package_hash,
        "started_at": started,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "stdout_sha256": sha(stdout),
        "stderr_sha256": sha(stderr),
        "stdout_path": raw_path.name,
        "stderr_path": err_path.name,
    }
    if status != "results":
        return [], receipt
    try:
        works = json.loads(stdout)
    except (ValueError, UnicodeError):
        receipt["status"] = "invalid-response"
        return [], receipt
    if not isinstance(works, list):
        receipt["status"] = "invalid-response"
        return [], receipt
    if not works:
        receipt["status"] = "zero-results"
    return works, receipt


def _source(row, receipt_id, as_of):
    if not isinstance(row, dict) or not row.get("title"):
        return None
    doi = (row.get("doi") or "").strip().lower().removeprefix("https://doi.org/")
    work_key = "doi:" + doi if doi else "title:" + row["title"].casefold().strip()
    raw_hash = sha(canonical(row))
    year = row.get("year")
    cutoff_year = int(as_of[:4])
    if isinstance(year, int) and year > cutoff_year:
        date_status = "after-cutoff"
    elif isinstance(year, int) and year == cutoff_year and as_of[5:] != "12-31":
        date_status = "same-year-date-unverified"
    elif isinstance(year, int):
        date_status = "within-year-cutoff"
    else:
        date_status = "publication-date-unverified"
    return {
        "source_id": "src-" + raw_hash[:16],
        "work_key": work_key,
        "version_id": "version-" + raw_hash[:16],
        "title": row["title"],
        "doi": doi or None,
        "authors": row.get("authors", []),
        "year": year,
        "url": row.get("url"),
        "abstract": row.get("abstract") or "",
        "source_level": "abstract" if row.get("abstract") else "metadata",
        "date_status": date_status,
        "receipt_id": receipt_id,
        "raw_sha256": raw_hash,
    }


def _dedupe(sources):
    # Keep distinct source versions; do not count repeated backend hits as works.
    return list({row["source_id"]: row for row in sources}.values())


def _doi(value):
    match = re.search(r"10\.\d{4,9}/[^\s?#]+", str(value or "").casefold())
    return match.group(0).rstrip(".,;:)") if match else None


def _title(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def _matches_subject_work(row, work):
    """Reject search hits that do not identify the work actually cited."""
    if _title(row.get("title")) != _title(work["title"]):
        return False
    identifier = work["identifier"]
    if not identifier:
        return True
    cited_doi = _doi(identifier)
    if cited_doi:
        return _doi(row.get("doi")) == cited_doi
    return (
        str(row.get("url") or "").rstrip("/").casefold()
        == identifier.rstrip("/").casefold()
    )


def _saved_rows(stdout, status):
    if status not in {"results", "zero-results"}:
        return []
    try:
        rows = json.loads(stdout)
    except (UnicodeError, ValueError) as exc:
        raise EvaluationError("successful receipt contains invalid JSON") from exc
    if not isinstance(rows, list) or (status == "results") != bool(rows):
        raise EvaluationError("receipt status disagrees with saved result list")
    return rows


def rebuild_background_sources(spec, receipts, raw_dir):
    policy = spec["draft"]["search_policy"]
    queries = policy["challenge_queries"]
    if len(receipts) != len(queries):
        raise EvaluationError("background query receipt count changed")
    sources = []
    for query, receipt in zip(queries, receipts):
        expected_year = (
            f"{int(spec['as_of'][:4]) - policy['recent_years'] + 1}-{spec['as_of'][:4]}"
            if query["purpose"] == "frontier"
            else "-" + spec["as_of"][:4]
        )
        expected_args = [
            "search",
            query["query"],
            "--limit",
            str(policy["max_results_per_query"]),
            "--backend",
            policy["backend"],
            "--year",
            expected_year,
            "--json",
        ]
        if (
            receipt.get("query_id") != query["query_id"]
            or receipt.get("purpose") != query["purpose"]
            or receipt.get("need_ids") != query["need_ids"]
            or receipt.get("command", [])[-len(expected_args) :] != expected_args
        ):
            raise EvaluationError("background receipt differs from frozen query")
        stdout = (Path(raw_dir) / receipt["stdout_path"]).read_bytes()
        sources.extend(
            filter(
                None,
                (
                    _source(row, query["query_id"], spec["as_of"])
                    for row in _saved_rows(stdout, receipt["status"])
                ),
            )
        )
    return _dedupe(sources)


def rebuild_subject_sources(extraction, spec, receipts, raw_dir):
    works = extraction["works"]
    if len(receipts) != len(works):
        raise EvaluationError("subject source receipt count changed")
    sources = []
    for work, receipt in zip(works, receipts):
        query = work["identifier"] or work["title"]
        expected_args = ["enrich", query, "--backend", "openalex", "--json"]
        if (
            receipt.get("work_id") != work["work_id"]
            or receipt.get("command", [])[-len(expected_args) :] != expected_args
        ):
            raise EvaluationError("source receipt differs from extracted work")
        stdout = (Path(raw_dir) / receipt["stdout_path"]).read_bytes()
        for row in _saved_rows(stdout, receipt["status"]):
            if not isinstance(row, dict) or not _matches_subject_work(row, work):
                continue
            source = _source(row, work["work_id"], spec["as_of"])
            if source is None or source["date_status"] == "after-cutoff":
                continue
            source["subject_work_id"] = work["work_id"]
            source["source_id"] = (
                "src-"
                + sha(
                    canonical(
                        {"work_id": work["work_id"], "raw_sha256": source["raw_sha256"]}
                    )
                )[:16]
            )
            sources.append(source)
    return _dedupe(sources)


def collect_background(spec, output_dir, hub_command):
    draft = check_spec(spec)
    output_dir = Path(output_dir)
    policy = draft["search_policy"]
    receipts = []
    for query in policy["challenge_queries"]:
        year = (
            f"{int(spec['as_of'][:4]) - policy['recent_years'] + 1}-{spec['as_of'][:4]}"
            if query["purpose"] == "frontier"
            else "-" + spec["as_of"][:4]
        )
        args = [
            "search",
            query["query"],
            "--limit",
            str(policy["max_results_per_query"]),
            "--backend",
            policy["backend"],
            "--year",
            year,
            "--json",
        ]
        _, receipt = _run_hub(args, output_dir / "raw", query["query_id"], hub_command)
        receipt.update(
            query_id=query["query_id"],
            purpose=query["purpose"],
            need_ids=query["need_ids"],
        )
        receipts.append(receipt)
    result = {
        "kind": "Stage1BackgroundEvidence",
        "schema_version": "3.0.0",
        "spec_sha256": sha(canonical(spec)),
        "mode": "evidence-audited",
        "sources": rebuild_background_sources(spec, receipts, output_dir / "raw"),
        "receipts": receipts,
        "scope_note": "Bounded search observations, not a gold/silver answer list or exhaustive recall denominator.",
    }
    write_json(output_dir / "background.json", result)
    return result


def collect_subject_sources(extraction, spec, output_dir, hub_command):
    check_spec(spec)
    output_dir = Path(output_dir)
    receipts = []
    for work in extraction["works"]:
        query = work["identifier"] or work["title"]
        args = ["enrich", query, "--backend", "openalex", "--json"]
        _, receipt = _run_hub(args, output_dir / "raw", work["work_id"], hub_command)
        receipt["work_id"] = work["work_id"]
        receipts.append(receipt)
    return {
        "sources": rebuild_subject_sources(
            extraction, spec, receipts, output_dir / "raw"
        ),
        "receipts": receipts,
    }

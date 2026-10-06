"""Saved-byte extraction attempts and version-bound read-only projections.

This module never fetches a URL, judges a claim, or changes the original input.
The parser is supplied by an explicitly pinned local source file.
"""

from copy import deepcopy
from dataclasses import asdict
from importlib import metadata, util
from pathlib import Path
import platform
import re
import sys
from research_hub.utils.doi import normalize_doi

from stage1_deliverable.common import (
    DeliverableError,
    canonical,
    private_output,
    safe_path,
    sha,
)
from stage1_deliverable.sources import artifact_map
from .json_bytes import decode_json


def require(value, message):
    if not value:
        raise DeliverableError(message)


def _parser(path, expected):
    path = Path(path).resolve(strict=True)
    require(sha(path.read_bytes()) == expected, "rerun parser hash differs")
    name = "research_hub.stage1_saved_rerun_parser"
    spec = util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "rerun parser unavailable")
    module = util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    require(sha(path.read_bytes()) == expected, "rerun parser changed while loading")
    return module


def _metadata(paper, extracted, identity_status=None):
    """Separate verbatim recorded venue parsing from source-observed fields."""
    venue = paper.get("venue") or ""
    fields = {
        "journal": venue or None,
        "volume": None,
        "issue": None,
        "pages": None,
        "doi": paper.get("doi"),
    }
    provenance = {"journal": {"status": "original-verbatim", "value": venue}}
    match = re.fullmatch(r"(.+?)\s+(\d+)\(([^()]+)\):\s*(\d+[–-]\d+|\d+)", venue)
    if match:
        for key, value in zip(("journal", "volume", "issue", "pages"), match.groups()):
            fields[key] = value
            provenance[key] = {
                "status": "parsed-from-original-venue",
                "value": value,
                "venue_verbatim": venue,
            }
    table = extracted.get("bibliographic_metadata", {})
    if table:
        # The table title must name this work before any table field is used.
        def normalize(text):
            return " ".join(text.casefold().split()).rstrip(".")

        if (
            identity_status != "mismatch"
            and normalize(table.get("title", "")) == normalize(paper["title"])
            and (
                not paper.get("doi")
                or normalize_doi(table.get("doi", "")) == normalize_doi(paper["doi"])
            )
        ):
            for key in ("doi", "volume", "issue", "pages", "journal"):
                if table.get(key):
                    fields[key] = table[key]
                    provenance[key] = {
                        "status": "observed-in-identity-matched-saved-source",
                        "value": table[key],
                        "locators": extracted["locators"],
                    }
    return fields, provenance


def build_rerun(index, package_root, output, parser_path, expected_parser_sha256):
    """Re-extract each saved final response, retaining all historical attempts."""
    from .projection import validate_index

    validate_index(index)
    require(index["schema_version"] in {"1.0.0", "2.0.0"}, "rerun needs original index")
    destination = private_output(output)
    require(not destination.exists(), "rerun output must be a new directory")
    package_root = private_output(package_root)
    parser = _parser(parser_path, expected_parser_sha256)
    rows, files = [], {}
    papers = {(p["work_id"], p["version_id"]): p for p in index["papers"]}
    for source in index["sources"]:
        paper = papers[(source["work_id"], source["version_id"])]
        receipt = source["receipt"]
        prefix = "deliverable/sources/" + source["source_id"] + "/"
        mapping = artifact_map(receipt)
        original = safe_path(package_root, prefix + "original.json").read_bytes()
        require(
            sha(original) == source["result_sha256"], "rerun original receipt differs"
        )
        require(decode_json(original) == receipt, "rerun receipt identity differs")
        selected = next(
            (
                a
                for a in reversed(receipt["attempts"])
                if a.get("raw_path") and a.get("outcome") != "redirect"
            ),
            None,
        )
        row = {key: source[key] for key in ("work_id", "version_id", "source_id")}
        row.update(
            original_result_sha256=source["result_sha256"],
            previous_status=receipt["status"],
            previous_evidence_level=receipt["evidence_level"],
            original_attempts=deepcopy(receipt["attempts"]),
        )
        extracted = {}
        reading = {
            "status": "not-attempted-no-saved-response",
            "evidence_level": "metadata",
            "identity_status": "unverified",
            "characters": 0,
            "text_sha256": None,
            "locators": [],
            "diagnostics": {},
            "error": None,
        }
        if selected:
            raw = safe_path(
                package_root, prefix + mapping[selected["raw_path"]]
            ).read_bytes()
            require(sha(raw) == selected["raw_sha256"], "rerun raw source hash differs")
            suffix = ".pdf" if raw.startswith(b"%PDF-") else ".html"
            raw_name = "sources/" + source["source_id"] + "/raw" + suffix
            files[raw_name] = raw
            row.update(
                raw_path=raw_name,
                raw_sha256=sha(raw),
                source_version="sha256:" + sha(raw),
                final_url=selected["final_url"],
                selected_sequence=selected["sequence"],
            )
            try:
                if selected.get("response_truncated"):
                    raise ValueError(
                        "saved response is truncated; extraction not admitted"
                    )
                if selected.get("http_status") != 200:
                    raise PermissionError(
                        "saved HTTP response was not successful; no new access attempted"
                    )
                item = (
                    parser._extract_pdf(raw)
                    if suffix == ".pdf"
                    else parser._extract_html(raw, selected["final_url"])
                )
                extracted = asdict(item)
                identity = parser._identity(
                    paper.get("doi") or "",
                    paper["title"],
                    item.observed_doi,
                    item.observed_title,
                )
                reading.update(
                    status="identity-mismatch"
                    if identity == "mismatch"
                    else "extracted",
                    evidence_level=item.evidence_level,
                    identity_status=identity,
                    characters=len(item.text),
                    text_sha256=sha(item.text.encode("utf-8")),
                    locators=item.locators,
                    diagnostics=extracted.get("diagnostics", {}),
                    observed_identity={
                        "title": item.observed_title,
                        "doi": item.observed_doi,
                    },
                )
                text_name = "sources/" + source["source_id"] + "/extracted.txt"
                files[text_name] = item.text.encode("utf-8")
                row["extracted_path"] = text_name
            except (PermissionError, ValueError, RuntimeError) as error:
                reading.update(
                    status="inaccessible"
                    if isinstance(error, PermissionError)
                    else "failed-engineering",
                    error={"type": type(error).__name__, "message": str(error)},
                )
        row["reading"] = reading
        row["source_metadata"] = extracted.get("bibliographic_metadata", {})
        row["metadata"], row["metadata_provenance"] = _metadata(
            paper, extracted, reading["identity_status"]
        )
        row["attempt_id"] = sha(
            canonical(
                {
                    "base": sha(canonical(index)),
                    "parser": expected_parser_sha256,
                    "work": paper["work_id"],
                    "version": paper["version_id"],
                    "raw": row.get("raw_sha256"),
                }
            )
        )
        rows.append(row)
    runtime = {
        "python": platform.python_version(),
        "python_executable_sha256": sha(Path(sys.executable).read_bytes()),
        "parser_sha256": expected_parser_sha256,
        "adapter_sha256": sha(Path(__file__).read_bytes()),
        "dependencies": {
            name: metadata.version(name)
            for name in ("pdfplumber", "pdfminer.six", "research-hub-pipeline")
        },
    }
    data = {
        "kind": "Stage1SavedSourceRerun",
        "schema_version": "1.0.0",
        "base_index_sha256": sha(canonical(index)),
        "parser_runtime": runtime,
        "rows": rows,
        "research_execution": False,
        "scientific_judgments_changed": False,
        "official_stage2_import_eligible": False,
        "new_searches": 0,
        "new_downloads": 0,
        "quality_score": None,
    }
    manifest = {
        "data": data,
        "files": {
            name: {"sha256": sha(raw), "bytes": len(raw)}
            for name, raw in sorted(files.items())
        },
    }
    destination.mkdir(parents=True)
    for name, raw in files.items():
        path = safe_path(destination, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    safe_path(destination, "source-rerun-manifest.json").write_bytes(
        canonical(manifest)
    )
    return sha(canonical(manifest))

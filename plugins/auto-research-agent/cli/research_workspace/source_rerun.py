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
from urllib.parse import quote
from research_hub.utils.doi import normalize_doi

from stage1_deliverable.common import (
    DeliverableError,
    canonical,
    inventory,
    private_output,
    safe_path,
    sha,
)
from stage1_deliverable.sources import artifact_map
from stage1_deliverable.views import bibtex
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


def _bibliography(index, rows):
    current = deepcopy(index["papers"])
    original_ids = {
        (s["work_id"], s["version_id"], s["source_id"]) for s in index["sources"]
    }
    row_ids = [(r["work_id"], r["version_id"], r["source_id"]) for r in rows]
    require(
        len(set(row_ids)) == len(row_ids) and set(row_ids) == original_ids,
        "rerun work/source/version differs",
    )
    by_id = {}
    for row in rows:
        by_id.setdefault((row["work_id"], row["version_id"]), row)
    entries = []
    for paper in current:
        row = by_id[(paper["work_id"], paper["version_id"])]
        base = bibtex({"papers": [paper]}).decode("utf-8")
        # Preserve legacy producer values and add separately labelled metadata.
        values = row["metadata"]
        additions = []
        for key in ("volume", "issue", "pages", "doi"):
            if values.get(key) and (key != "doi" or not paper.get("doi")):
                replacements = {
                    "\\": r"{\textbackslash}",
                    "{": r"\{",
                    "}": r"\}",
                    "%": r"\%",
                    "&": r"\&",
                    "_": r"\_",
                    "#": r"\#",
                    "$": r"\$",
                    "\n": " ",
                    "\r": " ",
                    "\t": " ",
                }
                value = (
                    quote(str(values[key]), safe=":/?#[]@!$&'()*+,;=%-._~")
                    if key == "doi"
                    else "".join(replacements.get(c, c) for c in str(values[key]))
                )
                additions.append(
                    f"  {'number' if key == 'issue' else key} = {{{value}}}"
                )
        if additions:
            additions.append(
                "  annotation = {Additional metadata bound to the saved-source rerun; original judgments retained}"
            )
            base = (
                base.rstrip().removesuffix("}").rstrip()
                + "\n"
                + ",\n".join(additions)
                + ",\n}\n"
            )
        entries.append(
            {
                "work_id": paper["work_id"],
                "version_id": paper["version_id"],
                "bibtex": base,
            }
        )
    return {
        "all_bibtex": "\n".join(r["bibtex"].rstrip() for r in entries) + "\n",
        "entries": entries,
    }


def attach_rerun(index, rerun_root, expected_manifest_sha256):
    """Accept an externally bound rerun without altering frozen claims or scores."""
    from .projection import validate_index

    validate_index(index)
    require(
        index["schema_version"] in {"1.0.0", "2.0.0"},
        "rerun cannot replace a rerun silently",
    )
    root = private_output(rerun_root)
    raw = safe_path(root, "source-rerun-manifest.json").read_bytes()
    require(
        sha(raw) == expected_manifest_sha256, "external rerun manifest hash differs"
    )
    manifest = decode_json(raw)
    files = manifest["files"]
    actual = inventory(root)
    actual.pop("source-rerun-manifest.json", None)
    require(
        actual == {name: row["sha256"] for name, row in files.items()},
        "rerun inventory differs",
    )
    evidence = {}
    for name, row in files.items():
        content = safe_path(root, name).read_bytes()
        require(
            sha(content) == row["sha256"] and len(content) == row["bytes"],
            "rerun artifact differs",
        )
        evidence[name] = content
    result = deepcopy(index)
    result["schema_version"] = "3.0.0"
    result["source_rerun"] = {
        "manifest_sha256": expected_manifest_sha256,
        "data": manifest["data"],
        "artifact_hashes": files,
        "bibliography": _bibliography(index, manifest["data"]["rows"]),
    }
    validate_rerun_index(result)
    for row in result["source_rerun"]["data"]["rows"]:
        if row.get("raw_path"):
            require(
                sha(evidence[row["raw_path"]]) == row["raw_sha256"],
                "rerun selected raw differs",
            )
        if row.get("extracted_path"):
            text = evidence[row["extracted_path"]].decode("utf-8")
            require(
                sha(text.encode("utf-8")) == row["reading"]["text_sha256"],
                "rerun extracted text differs",
            )
            require(
                len(text) == row["reading"]["characters"], "rerun text count differs"
            )
            for locator in row["reading"]["locators"]:
                if locator["type"] == "html-publication-table":
                    raw_source = evidence[row["raw_path"]]
                    require(
                        locator["source_sha256"] == sha(raw_source),
                        "rerun table source differs",
                    )
                    for field in locator["fields"]:
                        start, end = field["raw_utf8_bytes"]
                        require(
                            type(start) is int
                            and type(end) is int
                            and 0 <= start < end <= len(raw_source),
                            "rerun raw table locator invalid",
                        )
                        require(
                            sha(raw_source[start:end]) == field["raw_element_sha256"],
                            "rerun table quotation bytes differ",
                        )
                        require(
                            sha(row["source_metadata"][field["field"]].encode("utf-8"))
                            == field["clean_value_sha256"],
                            "rerun table field value differs",
                        )
    return result


def validate_rerun_index(index):
    base = deepcopy(index)
    extension = base.pop("source_rerun")
    base["schema_version"] = (
        "2.0.0" if base["supplement"]["status"] != "not-provided" else "1.0.0"
    )
    from .projection import validate_index

    validate_index(base)
    data = extension["data"]
    require(
        sha(canonical({"data": data, "files": extension["artifact_hashes"]}))
        == extension["manifest_sha256"],
        "rerun manifest/data binding differs",
    )
    require(
        data["kind"] == "Stage1SavedSourceRerun" and data["schema_version"] == "1.0.0",
        "unsupported source rerun",
    )
    require(
        data["base_index_sha256"] == sha(canonical(base)), "rerun base/version differs"
    )
    for key in (
        "research_execution",
        "scientific_judgments_changed",
        "official_stage2_import_eligible",
    ):
        require(
            data.get(key) is False, "rerun cannot promote research, judgment or import"
        )
    require(
        data.get("quality_score") is None
        and data.get("new_searches") == 0
        and data.get("new_downloads") == 0,
        "rerun cannot create a score or source acquisition",
    )
    original = {
        (s["work_id"], s["version_id"], s["source_id"]): s for s in base["sources"]
    }
    rows = data["rows"]
    require(len(rows) == len(original), "rerun must preserve every source")
    identities = [(r["work_id"], r["version_id"], r["source_id"]) for r in rows]
    require(
        len(set(identities)) == len(rows) and set(identities) == set(original),
        "rerun work/source/version differs",
    )
    require(identities == list(original), "rerun canonical source order differs")
    for key, row in zip(identities, rows):
        source = original[key]
        require(
            row["original_result_sha256"] == source["result_sha256"],
            "rerun original result differs",
        )
        require(
            row["previous_status"] == source["receipt"]["status"]
            and row["previous_evidence_level"] == source["receipt"]["evidence_level"]
            and row["original_attempts"] == source["receipt"]["attempts"],
            "rerun historical failure/attempts differ",
        )
        selected = next(
            (
                a
                for a in reversed(source["receipt"]["attempts"])
                if a.get("raw_path") and a.get("outcome") != "redirect"
            ),
            None,
        )
        if row.get("raw_sha256"):
            require(
                selected is not None and row["raw_sha256"] == selected["raw_sha256"],
                "rerun raw is not from this source",
            )
            require(
                row["source_version"] == "sha256:" + row["raw_sha256"],
                "rerun raw version differs",
            )
            require(
                row["selected_sequence"] == selected["sequence"]
                and row["final_url"] == selected["final_url"],
                "rerun selected attempt differs",
            )
        require(
            bool(row.get("raw_path")) == bool(selected), "rerun saved response omitted"
        )
        require(
            row["attempt_id"]
            == sha(
                canonical(
                    {
                        "base": data["base_index_sha256"],
                        "parser": data["parser_runtime"]["parser_sha256"],
                        "work": row["work_id"],
                        "version": row["version_id"],
                        "raw": row.get("raw_sha256"),
                    }
                )
            ),
            "rerun attempt binding differs",
        )
        reading = row["reading"]
        require(
            reading["status"]
            in {
                "extracted",
                "identity-mismatch",
                "inaccessible",
                "failed-engineering",
                "not-attempted-no-saved-response",
            },
            "rerun reading status invalid",
        )
        require(
            type(reading["characters"]) is int and reading["characters"] >= 0,
            "rerun text count invalid",
        )
        require(
            reading["identity_status"]
            in {"verified", "consistent", "unverified", "mismatch"},
            "rerun identity status invalid",
        )
        if reading["status"] in {"extracted", "identity-mismatch"}:
            require(
                bool(row.get("extracted_path"))
                and reading["characters"] > 0
                and reading["error"] is None,
                "rerun successful text missing",
            )
            require(
                (reading["identity_status"] == "mismatch")
                == (reading["status"] == "identity-mismatch"),
                "rerun identity mismatch hidden",
            )
        else:
            require(
                not row.get("extracted_path")
                and reading["characters"] == 0
                and reading["text_sha256"] is None,
                "rerun failed read cannot contain admitted text",
            )
        require(
            reading["evidence_level"] in {"metadata", "abstract", "full-text"},
            "rerun evidence level invalid",
        )
        for locator in reading["locators"]:
            require(
                type(locator["start"]) is int
                and type(locator["end"]) is int
                and 0 <= locator["start"] < locator["end"] <= reading["characters"],
                "rerun locator invalid",
            )
            if locator["type"] == "html-publication-table" or (
                len(reading["locators"]) == 1
                and locator["start"] == 0
                and locator["end"] == reading["characters"]
                and str(locator["value"]).casefold() == "abstract"
            ):
                require(
                    reading["evidence_level"] == "abstract",
                    "rerun abstract cannot become full-text",
                )
        paper = next(
            p for p in base["papers"] if (p["work_id"], p["version_id"]) == key[:2]
        )
        require(
            (row["metadata"], row["metadata_provenance"])
            == _metadata(
                paper,
                {
                    "bibliographic_metadata": row.get("source_metadata", {}),
                    "locators": reading["locators"],
                },
                reading["identity_status"],
            ),
            "rerun metadata provenance differs",
        )
        for name in (row.get("raw_path"), row.get("extracted_path")):
            if name:
                require(
                    name in extension["artifact_hashes"],
                    "rerun missing source artifact",
                )
        if row.get("extracted_path"):
            require(
                extension["artifact_hashes"][row["extracted_path"]]["sha256"]
                == reading["text_sha256"],
                "rerun text/artifact binding differs",
            )
    require(
        extension["bibliography"] == _bibliography(base, rows),
        "rerun bibliography differs",
    )
    return index

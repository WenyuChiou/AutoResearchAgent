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
from stage1_deliverable.views import bibtex, csv_bytes, workbook_bytes
from .json_bytes import decode_json


def require(value, message):
    if not value:
        raise DeliverableError(message)


def _saved_response_selection(attempts):
    """Return the latest nonredirect event and its matching offline acquisition."""
    position, selected = next(
        (
            (position, attempt)
            for position, attempt in reversed(list(enumerate(attempts)))
            if attempt.get("outcome") != "redirect"
        ),
        (0, None),
    )
    acquisition = None
    if (
        selected
        and selected.get("purpose") == "offline-parser-replay"
        and selected.get("http_status") is None
    ):
        acquisition = next(
            (
                attempt
                for attempt in reversed(attempts[:position])
                if attempt.get("purpose") != "offline-parser-replay"
                and attempt.get("outcome") != "redirect"
                and attempt.get("http_status") == 200
                and attempt.get("raw_path")
                and attempt.get("response_truncated") is False
                and all(
                    attempt.get(key) == selected.get(key)
                    for key in ("raw_sha256", "response_bytes", "final_url")
                )
            ),
            None,
        )
    return selected, acquisition


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
        selected, acquisition = _saved_response_selection(receipt["attempts"])
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
        if selected and selected.get("raw_path"):
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
                if (
                    selected.get("purpose") == "offline-parser-replay"
                    and selected.get("http_status") is None
                ):
                    if (
                        type(selected.get("response_bytes")) is not int
                        or len(raw) != selected["response_bytes"]
                    ):
                        raise ValueError("offline replay byte count differs")
                    if acquisition is None:
                        raise ValueError(
                            "offline parser replay has no matching successful saved acquisition"
                        )
                    try:
                        acquisition_raw = safe_path(
                            package_root, prefix + mapping[acquisition["raw_path"]]
                        ).read_bytes()
                    except OSError as error:
                        raise ValueError(
                            "offline replay acquisition archive could not be read"
                        ) from error
                    require(
                        sha(acquisition_raw) == acquisition["raw_sha256"]
                        and len(acquisition_raw) == acquisition["response_bytes"],
                        "offline replay acquisition bytes differ",
                    )
                    raw = acquisition_raw
                    row["acquisition_sequence"] = acquisition["sequence"]
                elif selected.get("http_status") != 200:
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
        elif selected:
            offline = selected.get("purpose") == "offline-parser-replay"
            reading.update(
                status="failed-engineering" if offline else "inaccessible",
                error={
                    "type": "ValueError" if offline else "PermissionError",
                    "message": "latest attempt has no saved body; earlier responses were not substituted",
                },
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


def _bibliography(index, rows, *, citation_key_policy=None):
    require(
        citation_key_policy in (None, "work-version-sha256"),
        "unknown rerun citation key policy",
    )
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
        if citation_key_policy == "work-version-sha256":
            key = "work_" + sha(canonical((paper["work_id"], paper["version_id"])))
            base, count = re.subn(
                r"(@[A-Za-z]+\{)[^,\r\n]+,",
                lambda match: match[1] + key + ",",
                base,
                count=1,
            )
            require(count == 1, "rerun bibliography entry heading missing")
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


def attach_rerun(
    index,
    rerun_root,
    expected_manifest_sha256,
    *,
    expected_body_review_acceptance_hashes=None,
    expected_whole_source_review_acceptance_hashes=None,
):
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
        "bibliography": _bibliography(
            index,
            manifest["data"]["rows"],
            citation_key_policy=manifest["data"].get("citation_key_policy"),
        ),
    }
    from .body_review_attachment import attach_body_reviews

    reviews = attach_body_reviews(
        manifest["data"]["rows"],
        evidence,
        files,
        expected_body_review_acceptance_hashes,
    )
    if reviews:
        result["source_rerun"]["body_reviews"] = reviews
    from .whole_source_review import attach_whole_source_reviews

    source_reviews = attach_whole_source_reviews(
        manifest["data"]["rows"],
        evidence,
        files,
        expected_whole_source_review_acceptance_hashes,
    )
    if source_reviews:
        result["source_rerun"]["whole_source_reviews"] = source_reviews
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
        selected, acquisition = _saved_response_selection(source["receipt"]["attempts"])
        acquisition_bound = (
            acquisition is not None
            and row.get("acquisition_sequence") == acquisition["sequence"]
        )
        require(
            "acquisition_sequence" not in row or acquisition_bound,
            "rerun acquisition attempt differs",
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
            bool(row.get("raw_path")) == bool(selected and selected.get("raw_path")),
            "rerun saved response omitted",
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
                selected is not None
                and bool(selected.get("raw_path"))
                and not selected.get("response_truncated")
                and (selected.get("http_status") == 200 or acquisition_bound),
                "rerun successful reading lacks saved acquisition",
            )
            if acquisition_bound:
                require(
                    type(selected.get("response_bytes")) is int
                    and extension["artifact_hashes"]
                    .get(row["raw_path"], {})
                    .get("bytes")
                    == selected["response_bytes"],
                    "rerun offline acquisition byte count differs",
                )
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
        extension["bibliography"]
        == _bibliography(
            base, rows, citation_key_policy=data.get("citation_key_policy")
        ),
        "rerun bibliography differs",
    )
    from .body_review_attachment import validate_body_reviews

    validate_body_reviews(extension)
    from .whole_source_review import validate_whole_source_reviews

    validate_whole_source_reviews(extension)
    return index


def rerun_files(index, rerun_root):
    validate_rerun_index(index)
    import json

    from .source_availability import derive_source_availability

    extension = index["source_rerun"]
    rows = extension["data"]["rows"]
    availability = derive_source_availability(index)

    def tabular(values):
        return [
            {
                key: (
                    json.dumps(value, ensure_ascii=False, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else value
                )
                for key, value in row.items()
            }
            for row in values
        ]

    flattened = [
        {
            "work_id": r["work_id"],
            "version_id": r["version_id"],
            "source_id": r["source_id"],
            "attempt_id": r["attempt_id"],
            "previous_status": r["previous_status"],
            **r["metadata"],
            **r["reading"],
            "metadata_provenance": r["metadata_provenance"],
        }
        for r in rows
    ]
    columns = sorted({key for row in flattened for key in row})
    flattened = [{key: row.get(key) for key in columns} for row in flattened]
    from .closeout import closeout_tables, fence

    tables = (
        closeout_tables(index)
        if index["supplement"]["status"] != "not-provided"
        else {"Papers": index["papers"]}
    )
    tables["SourceRerun"] = flattened
    tables["SourceAvailability"] = tabular(availability["source_rows"])
    tables["ClaimAvailability"] = tabular(availability["claim_rows"])
    availability_markdown = (
        "# Saved-source availability\n\n"
        "Availability records whether a readable saved body is present. It does not change or explain the historical claim assessment.\n\n"
        + fence(availability)
    )
    files = {
        "source-rerun/catalog.xlsx": workbook_bytes(tables),
        "source-rerun/catalog.csv": csv_bytes("SourceRerun", flattened),
        "source-rerun/source-availability.json": canonical(availability),
        "source-rerun/source-availability.csv": csv_bytes(
            "SourceAvailability", tabular(availability["source_rows"])
        ),
        "source-rerun/source-availability.md": availability_markdown.encode("utf-8"),
        "source-rerun/manifest.json": canonical(extension),
        "source-rerun/references.bib": extension["bibliography"]["all_bibtex"].encode(
            "utf-8"
        ),
        "source-rerun/report.md": (
            "# Saved-source Stage 1 rerun\n\n"
            "Original claims, failures, compound counts and coverage remain historical and unchanged. "
            "New read attempts and bibliography fields are separate; extraction is not claim support.\n\n"
            + "## Source availability\n\n"
            + fence(availability["counts"])
            + fence(extension["data"])
        ).encode("utf-8"),
    }
    for row in availability["source_rows"]:
        identity = [row["work_id"], row["version_id"]]
        claims = [
            claim
            for claim in availability["claim_rows"]
            if (claim["work_id"], claim["version_id"])
            == (row["work_id"], row["version_id"])
        ]
        files["source-rerun/notes/" + sha(canonical(identity)) + ".md"] = (
            "# Source availability note\n\n"
            "Readable-source status and historical claim assessment are separate.\n\n"
            + fence({"source_availability": row, "claims": claims})
        ).encode("utf-8")
    root = private_output(rerun_root)
    for name, row in extension["artifact_hashes"].items():
        raw = safe_path(root, name).read_bytes()
        require(sha(raw) == row["sha256"], "rerun bytes changed while exporting")
        files["source-rerun/" + name] = raw
    return files

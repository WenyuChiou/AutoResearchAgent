"""Project a bound private delivery package without granting research readiness."""

from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from stage1_deliverable import sources, views
from stage1_deliverable.common import (
    DeliverableError,
    canonical,
    identifier,
    inventory,
    private_output,
    read_json,
    safe_path,
    sha,
)
from stage1_deliverable.records import validate_records

from .stages import stage_registry


def _require(condition, message):
    if not condition:
        raise DeliverableError(message)


def validate_index(index):
    """Validate the presentation contract, never scientific correctness."""
    schema = read_json(Path(__file__).with_name("WorkspaceIndex.v1.schema.json"))
    try:
        Draft202012Validator(schema).validate(index)
    except ValidationError as error:
        raise DeliverableError("workspace index schema: " + error.message) from error
    identities = [(paper["work_id"], paper["version_id"]) for paper in index["papers"]]
    _require(len(set(identities)) == len(identities), "duplicate work/version")
    _require(
        {stage["stage"] for stage in index["stages"]} == set(range(1, 7)),
        "workspace stages must contain each stage exactly once",
    )
    bibliography = index["bibliography"]
    entries = bibliography["entries"]
    entry_ids = [(entry["work_id"], entry["version_id"]) for entry in entries]
    _require(
        len(entries) == len(identities) and set(entry_ids) == set(identities),
        "bibliography must contain each work/version exactly once",
    )
    _require(
        bibliography["records_sha256"] == index["provenance"]["records_sha256"],
        "bibliography records hash differs",
    )
    papers = dict(zip(identities, index["papers"]))
    for identity, entry in zip(entry_ids, entries):
        _require(
            entry["bibtex"].encode("utf-8")
            == views.bibtex({"papers": [papers[identity]]}),
            "bibliography entry differs from canonical producer",
        )
    _require(
        bibliography["all_bibtex"].encode("utf-8") == views.bibtex(index),
        "bibliography all_bibtex differs from canonical producer",
    )
    return index


def _jsonl(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            _require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    return [
        json.loads(line, object_pairs_hook=unique)
        for line in path.read_bytes().splitlines()
    ]


def _package(root, expected):
    manifest_path = safe_path(root, "package_manifest.json")
    _require(
        sha(manifest_path.read_bytes()) == expected, "external package hash mismatch"
    )
    outer = read_json(manifest_path)
    _require(
        outer.get("kind") == "Stage1PrivateDeliveryPackageManifest"
        and outer.get("schema_version") == "1.0.0",
        "unsupported delivery package",
    )
    actual = inventory(root)
    actual.pop("package_manifest.json", None)
    extra_manifest = safe_path(root, "provenance_manifest.json")
    if extra_manifest.is_file():
        actual["provenance_manifest.json"] = sha(extra_manifest.read_bytes())
    files = outer["files"]
    _require(
        actual == {name: row["sha256"] for name, row in files.items()},
        "package inventory mismatch",
    )
    for name, row in files.items():
        _require(
            safe_path(root, name).stat().st_size == row["bytes"],
            "package byte count mismatch",
        )
    delivery = safe_path(root, "deliverable")
    manifest = read_json(safe_path(delivery, "provenance_manifest.json"))
    _require(
        manifest.get("kind") == "Stage1ResearchDeliverable"
        and manifest.get("schema_version") == "1.0.0",
        "unsupported canonical package",
    )
    _require(inventory(delivery) == manifest["files"], "deliverable inventory mismatch")
    records = validate_records(manifest["canonical_records"])
    original = safe_path(delivery, "records.original.json")
    _require(
        sha(original.read_bytes()) == manifest["original_input_sha256"],
        "original records hash mismatch",
    )
    _require(read_json(original) == records, "canonical records mismatch")
    _require(
        _jsonl(safe_path(delivery, "papers.jsonl")) == records["papers"],
        "paper view mismatch",
    )
    return outer, manifest, records


def _source_records(delivery, records):
    attempts = _jsonl(safe_path(delivery, "paper_manifest.jsonl"))
    _require(
        len({(row["source_id"], row["attempt"]) for row in attempts}) == len(attempts),
        "duplicate source attempt",
    )
    output, texts = [], {}
    papers = {paper["work_id"]: paper for paper in records["papers"]}
    for source in records["sources"]:
        archive = safe_path(delivery, "sources/" + source["source_id"])
        original = safe_path(archive, "original.json")
        _require(
            sha(original.read_bytes()) == source["result_sha256"],
            "source receipt hash mismatch",
        )
        receipt = read_json(original)
        sources.validate_receipt_shape(receipt)
        _require(
            sources.receipt_digest(receipt) == receipt["receipt_sha256"],
            "source receipt digest mismatch",
        )
        mapping = sources.artifact_map(receipt)
        for item in [receipt, *receipt["attempts"]]:
            for path_key, hash_key in (
                ("raw_path", "raw_sha256"),
                ("extracted_text_path", "extracted_text_sha256"),
            ):
                if item.get(path_key):
                    raw = safe_path(archive, mapping[item[path_key]]).read_bytes()
                    _require(
                        sha(raw) == item[hash_key], "source artifact hash mismatch"
                    )
        paper = papers[source["work_id"]]

        def normalize(value):
            return " ".join(value.casefold().split()).rstrip(".")

        _require(
            normalize(receipt["expected_identity"]["title"])
            == normalize(paper["title"]),
            "source title binding mismatch",
        )
        _require(
            receipt["expected_identity"]["doi"] == (paper["doi"] or ""),
            "source DOI binding mismatch",
        )
        rows = [row for row in attempts if row["source_id"] == source["source_id"]]
        _require(
            {row["attempt"] for row in rows}
            == {row["sequence"] for row in receipt["attempts"]},
            "source attempt inventory mismatch",
        )
        for row in rows:
            _require(
                (row["work_id"], row["version_id"])
                == (source["work_id"], source["version_id"]),
                "source attempt version mismatch",
            )
            for key in ("archive_path", "paper_path"):
                if row[key]:
                    _require(
                        sha(safe_path(delivery, row[key]).read_bytes())
                        == row["sha256"],
                        "source manifest bytes mismatch",
                    )
        if receipt.get("extracted_text_path"):
            texts[source["source_id"]] = (
                safe_path(archive, mapping[receipt["extracted_text_path"]])
                .read_bytes()
                .decode("utf-8")
            )
        output.append({**deepcopy(source), "receipt": receipt, "attempts": rows})
    _require(
        {row["source_id"] for row in attempts} == {row["source_id"] for row in output},
        "orphan source attempt",
    )
    levels = {"metadata": 0, "abstract": 1, "full-text": 2}
    by_id = {row["source_id"]: row["receipt"] for row in output}
    for paper in records["papers"]:
        maximum = max(
            (
                levels[by_id[key]["evidence_level"]]
                for key in paper["source_ids"]
                if by_id[key]["status"] == "available"
            ),
            default=0,
        )
        _require(
            levels[paper["evidence_level"]] <= maximum,
            "paper evidence level exceeds source",
        )
    for claim in records["claims"]:
        receipt = by_id[claim["source_id"]]
        _require(
            receipt["status"] == "available" and claim["source_id"] in texts,
            "claim source text unavailable",
        )
        _require(
            levels[claim["evidence_level"]] <= levels[receipt["evidence_level"]],
            "claim evidence level exceeds source",
        )
        text = texts[claim["source_id"]]
        _require(
            claim["end"] <= len(text)
            and text[claim["start"] : claim["end"]] == claim["quote"],
            "claim quote binding mismatch",
        )
    return output


def _missing(value, pointer=""):
    if value is None or value == "" or value == []:
        return [{"pointer": pointer, "status": "not-recorded"}]
    if isinstance(value, str) and value.casefold().startswith(
        ("unknown", "unverified", "not independently assessed")
    ):
        return [{"pointer": pointer, "status": "stated-unknown"}]
    if isinstance(value, (dict, list)):
        pairs = value.items() if isinstance(value, dict) else enumerate(value)
        return [
            row for key, item in pairs for row in _missing(item, f"{pointer}/{key}")
        ]
    return []


def project_package(
    package_root,
    project_id,
    expected_manifest_sha256,
    *,
    validation_mode="byte-inventory",
):
    """Return deterministic records; byte checks are not exporter semantic replay."""
    identifier(project_id)
    _require(
        validation_mode == "byte-inventory",
        "unknown validation mode",
    )
    root = private_output(package_root)
    outer, manifest, records = _package(root, expected_manifest_sha256)
    delivery = safe_path(root, "deliverable")
    source_rows = _source_records(delivery, records)
    manifest_sha = outer["files"]["deliverable/provenance_manifest.json"]["sha256"]
    record_sha = manifest["original_input_sha256"]

    def provenance(pointer):
        return {
            "path": "deliverable/records.original.json",
            "sha256": record_sha,
            "pointer": pointer,
        }

    edges = []
    for index, claim in enumerate(records["claims"]):
        edges.append(
            {
                "type": "claim-source",
                **{
                    key: claim[key]
                    for key in (
                        "work_id",
                        "version_id",
                        "claim_id",
                        "source_id",
                        "relation",
                    )
                },
                "provenance": provenance(f"/claims/{index}"),
            }
        )
    for index, paper in enumerate(records["papers"]):
        for role_index, role in enumerate(paper["roles"]):
            for claim_id in role["claim_ids"]:
                edges.append(
                    {
                        "type": "role-claim",
                        "work_id": paper["work_id"],
                        "version_id": paper["version_id"],
                        "role": role["role"],
                        "reason": role["reason"],
                        "claim_id": claim_id,
                        "provenance": provenance(f"/papers/{index}/roles/{role_index}"),
                    }
                )

    def documents(suffix):
        return [
            {
                "path": name,
                "sha256": info["sha256"],
                "text": safe_path(root, name).read_bytes().decode("utf-8"),
            }
            for name, info in sorted(outer["files"].items())
            if name.endswith(suffix)
        ]

    readiness = read_json(safe_path(root, "stage2_readiness.json"))
    _require(
        outer["stage2_readiness_sha256"]
        == sha(safe_path(root, "stage2_readiness.json").read_bytes()),
        "readiness binding mismatch",
    )
    result = {
        "kind": "WorkspaceIndex",
        "schema_version": "1.0.0",
        "project_id": project_id,
        "status": "partial-review-only",
        "topic": records["topic"],
        "as_of": records["as_of"],
        **{
            key: deepcopy(records[key])
            for key in ("papers", "claims", "screening", "coverage")
        },
        "sources": source_rows,
        "edges": edges,
        "missing_fields": _missing(records),
        "search": documents("search_and_screening.csv"),
        "coverage_documents": documents("coverage_and_stop.md"),
        "audit_documents": [
            document
            for document in documents(
                (
                    "claim_audit.csv",
                    "assertion_labels.json",
                    "cited_source_spans.json",
                    "preserved_failures.json",
                )
            )
            if document["path"]
            in {
                "audit/claim_audit.csv",
                "audit/assertion_labels.json",
                "audit/cited_source_spans.json",
                "audit/preserved_failures.json",
            }
        ],
        "readiness": readiness,
        "supplement": {"status": "not-provided", "top3_status": "pending"},
        "stages": stage_registry(),
        "native_session": {"status": "not-connected", "thread_id": None},
        "evaluations": {"status": "not-provided", "items": []},
        "bibliography": {
            "producer": "stage1_deliverable.views.bibtex",
            "records_sha256": record_sha,
            "all_bibtex": views.bibtex(records).decode("utf-8"),
            "entries": [
                {
                    "work_id": paper["work_id"],
                    "version_id": paper["version_id"],
                    "bibtex": views.bibtex({"papers": [paper]}).decode("utf-8"),
                }
                for paper in records["papers"]
            ],
        },
        "provenance": {
            "package_manifest_sha256": expected_manifest_sha256,
            "deliverable_manifest_sha256": manifest_sha,
            "records_sha256": record_sha,
            "files": deepcopy(outer["files"]),
            "validation": {
                "mode": validation_mode,
                "byte_inventory": "passed",
                "canonical_bindings": "passed",
                "semantic_replay": "not-performed",
                "scientific_quality_scored": False,
            },
        },
    }
    _require(
        _package(root, expected_manifest_sha256) == (outer, manifest, records),
        "package changed during projection",
    )
    canonical(result)  # Reject unserializable output before the caller writes it.
    return validate_index(result)

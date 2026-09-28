"""Build immutable private packages and replay all generated views."""

from pathlib import Path

from . import sources, views
from .common import (
    DeliverableError,
    canonical,
    inventory,
    private_output,
    read_json,
    reject_links,
    safe_path,
    sha,
    write_json,
)
from .records import _keys, validate_records

DOCX = {"status": "available", "reason": "python-docx present in declared runtime"}


def _jsonl(rows):
    return b"".join(canonical(row) + b"\n" for row in rows)


def derive(records, root, runtime):
    """Reconstruct sources and claims from canonical records plus raw archives."""
    paper_by_id = {p["work_id"]: p for p in records["papers"]}
    source_by_id, manifests, paper_files = {}, [], {}
    levels = {"metadata": 0, "abstract": 1, "full-text": 2}
    for source in records["sources"]:
        archive = safe_path(root, "sources/" + source["source_id"])
        if sha((archive / "original.json").read_bytes()) != source["result_sha256"]:
            raise DeliverableError(
                "source archive differs from canonical input binding"
            )
        rows, result, mapping = sources.source_records(
            source, paper_by_id[source["work_id"]], archive, runtime
        )
        source_by_id[source["source_id"]] = (source, result, archive, mapping)
        manifests.extend(rows)
        for row in rows:
            if row["paper_path"]:
                if row["paper_path"] in paper_files:
                    raise DeliverableError("duplicate full source path")
                paper_files[row["paper_path"]] = safe_path(
                    root, row["archive_path"]
                ).read_bytes()
    for paper in records["papers"]:
        available = [
            source_by_id[x][1]
            for x in paper["source_ids"]
            if source_by_id[x][1]["status"] == "available"
        ]
        maximum = max([levels[s["evidence_level"]] for s in available], default=0)
        if levels[paper["evidence_level"]] > maximum:
            raise DeliverableError("abstract or metadata cannot become full text")
    for claim in records["claims"]:
        _, result, archive, mapping = source_by_id[claim["source_id"]]
        if result["status"] != "available" or not result.get("extracted_text_path"):
            raise DeliverableError("claim requires accessible same-work source text")
        if levels[claim["evidence_level"]] > levels[result["evidence_level"]]:
            raise DeliverableError("claim evidence level exceeds actual source")
        raw = safe_path(archive, mapping[result["extracted_text_path"]]).read_bytes()
        if sha(raw) != result["extracted_text_sha256"]:
            raise DeliverableError("claim text bytes changed")
        text = raw.decode("utf-8")
        if (
            claim["end"] > len(text)
            or text[claim["start"] : claim["end"]] != claim["quote"]
        ):
            raise DeliverableError(
                "claim quote differs from exact version-bound source span"
            )
    return manifests, paper_files


def _counts(records, manifests):
    states = {
        state: sum(row["state"] == state for row in manifests)
        for state in sources.STATES
    }
    full = [row for row in manifests if row["paper_path"]]
    return {
        "papers": len(records["papers"]),
        "claims": len(records["claims"]),
        "screening": len(records["screening"]),
        "coverage": len(records["coverage"]),
        "source_attempts": len(manifests),
        "access_state_counts": states,
        "acquired_full_text": {
            kind: sum(row["paper_path"].endswith("." + suffix) for row in full)
            for kind, suffix in (("pdf", "pdf"), ("html", "html"), ("text", "txt"))
        },
        "source_bindings": {"total": len(full), "complete": len(full)},
        "full_text_acquisition_fraction": {
            "numerator": len({row["work_id"] for row in full}),
            "denominator": len(records["papers"]),
        },
        "not_exercised": [key for key, value in states.items() if not value],
    }


def build(records_path, output, expected_records_sha256):
    records_path = Path(records_path).resolve()
    original = records_path.read_bytes()
    if sha(original) != expected_records_sha256:
        raise DeliverableError("canonical input SHA-256 differs from supplied binding")
    records = validate_records(read_json(records_path))
    sources.reject_secrets(original)
    runtime = sources.runtime_binding()
    output = private_output(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "papers").mkdir()
    (output / "records.original.json").write_bytes(original)
    # Partial exports remain visible and cannot be silently overwritten.
    for source in records["sources"]:
        sources.stage_source(
            source,
            records_path.parent,
            safe_path(output, "sources/" + source["source_id"]),
        )
    manifests, paper_files = derive(records, output, runtime)
    generated = views.render(records, manifests)
    generated.update(paper_files)
    generated["papers.jsonl"] = _jsonl(records["papers"])
    generated["paper_manifest.jsonl"] = _jsonl(manifests)
    for name, data in generated.items():
        target = safe_path(output, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
    manifest = {
        "kind": "Stage1ResearchDeliverable",
        "schema_version": "1.0.0",
        "experimental": True,
        "improvement": "not yet demonstrated",
        "canonical_records": records,
        "original_input_sha256": expected_records_sha256,
        "runtime": runtime,
        "docx": DOCX,
        "counts": _counts(records, manifests),
        "files": inventory(output),
    }
    write_json(output / "provenance_manifest.json", manifest)
    digest = sha((output / "provenance_manifest.json").read_bytes())
    report = validate(output, digest)
    return {
        **report,
        "manifest_sha256": digest,
        "records_sha256": expected_records_sha256,
    }


def validate(root, expected_sha256):
    reject_links(root)
    root = Path(root).resolve()
    manifest_path = root / "provenance_manifest.json"
    if sha(manifest_path.read_bytes()) != expected_sha256:
        raise DeliverableError("package manifest differs from trusted external SHA-256")
    manifest = read_json(manifest_path)
    _keys(
        manifest,
        (
            "kind",
            "schema_version",
            "experimental",
            "improvement",
            "canonical_records",
            "original_input_sha256",
            "runtime",
            "docx",
            "counts",
            "files",
        ),
        "package manifest",
    )
    if (
        manifest.get("kind") != "Stage1ResearchDeliverable"
        or manifest.get("schema_version") != "1.0.0"
        or manifest["experimental"] is not True
        or manifest["improvement"] != "not yet demonstrated"
        or manifest["docx"] != DOCX
    ):
        raise DeliverableError("unsupported package contract")
    records = validate_records(manifest["canonical_records"])
    original = (root / "records.original.json").read_bytes()
    if (
        sha(original) != manifest["original_input_sha256"]
        or read_json(root / "records.original.json") != records
    ):
        raise DeliverableError("canonical records differ from original input artifact")
    runtime = sources.runtime_binding()
    if manifest["runtime"] != runtime:
        raise DeliverableError("exporter or dependency runtime bytes changed")
    if inventory(root) != manifest["files"]:
        raise DeliverableError("package file inventory or bytes differ")
    manifests, paper_files = derive(records, root, runtime)
    generated = views.render(records, manifests)
    generated.update(paper_files)
    generated["papers.jsonl"] = _jsonl(records["papers"])
    generated["paper_manifest.jsonl"] = _jsonl(manifests)
    for name, data in generated.items():
        if safe_path(root, name).read_bytes() != data:
            raise DeliverableError("canonical-to-view semantic replay differs: " + name)
    allowed = {*generated, "records.original.json"}
    for source in records["sources"]:
        archive = safe_path(root, "sources/" + source["source_id"])
        original = read_json(archive / "original.json")
        allowed.update(
            "sources/" + source["source_id"] + "/" + name
            for name in (
                *set(sources.artifact_map(original).values()),
                "original.json",
                "validation.json",
            )
        )
    if set(manifest["files"]) != allowed:
        raise DeliverableError("unrecognized files cannot enter a research package")
    counts = _counts(records, manifests)
    if manifest["counts"] != counts:
        raise DeliverableError("rehashed package counts differ from canonical records")
    return {
        "kind": "Stage1DeliverableValidation",
        "status": "passed",
        "cross_format_reconciled": True,
        "source_semantic_replay": True,
        "manifest_sha256": expected_sha256,
        "counts": counts,
        "scientific_quality_scored": False,
    }

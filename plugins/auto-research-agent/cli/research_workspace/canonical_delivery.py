"""Read an already saved canonical delivery without rebuilding its package.

The legacy Index uses virtual ``deliverable/`` paths. Each inventory row below
explicitly maps that path to a physical relative path in the bare delivery.
Its required package_manifest_sha256 field aliases the actual canonical
manifest hash; no private-package envelope or readiness artifact is invented.
"""

import re
from collections.abc import Mapping
from types import MappingProxyType

from stage1_deliverable.common import (
    DeliverableError,
    canonical,
    identifier,
    inventory,
    private_output,
    safe_path,
    sha,
)
from stage1_deliverable.records import validate_records

from .json_bytes import decode_json
from .projection import _jsonl, _project_records, _source_records


def _require(condition, message):
    if not condition:
        raise DeliverableError(message)


def _read(root, files, virtual_path, artifact_bytes=None):
    _require(virtual_path in files, "unlisted canonical delivery artifact")
    row = files[virtual_path]
    raw = (
        safe_path(root, row["physical_relative_path"]).read_bytes()
        if artifact_bytes is None
        else artifact_bytes[row["physical_relative_path"]]
    )
    _require(
        sha(raw) == row["sha256"] and len(raw) == row["bytes"],
        "canonical delivery artifact bytes differ",
    )
    return raw


def _read_bound(root, files, virtual_path, artifact_bytes):
    if artifact_bytes is None:
        return _read(root, files, virtual_path)
    return _read(root, files, virtual_path, artifact_bytes)


def _delivery(root, expected, artifact_bytes=None):
    _require(
        isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected),
        "external canonical manifest hash required",
    )
    path = safe_path(root, "provenance_manifest.json")
    raw = path.read_bytes() if artifact_bytes is None else artifact_bytes[path.name]
    _require(sha(raw) == expected, "external canonical manifest hash differs")
    manifest = decode_json(raw)
    _require(
        isinstance(manifest, dict)
        and manifest.get("kind") == "Stage1ResearchDeliverable"
        and manifest.get("schema_version") in {"1.0.0", "1.1.0"},
        "unsupported saved canonical delivery",
    )
    declared = manifest.get("files")
    _require(isinstance(declared, dict), "canonical inventory required")
    files = {}
    for physical_path, digest in declared.items():
        _require(
            isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest),
            "canonical inventory hash invalid",
        )
        artifact = safe_path(root, physical_path)
        _require(
            physical_path != "provenance_manifest.json"
            and (
                artifact.is_file()
                if artifact_bytes is None
                else physical_path in artifact_bytes
            ),
            "canonical inventory artifact unavailable",
        )
        files["deliverable/" + physical_path] = {
            "sha256": digest,
            "bytes": (
                artifact.stat().st_size
                if artifact_bytes is None
                else len(artifact_bytes[physical_path])
            ),
            "physical_relative_path": physical_path,
        }
    actual = (
        inventory(root)
        if artifact_bytes is None
        else {
            name: sha(raw)
            for name, raw in artifact_bytes.items()
            if name != "provenance_manifest.json"
        }
    )
    _require(actual == declared, "canonical delivery inventory differs")
    files["deliverable/provenance_manifest.json"] = {
        "sha256": expected,
        "bytes": len(raw),
        "physical_relative_path": "provenance_manifest.json",
    }
    records = validate_records(manifest["canonical_records"])
    _require(
        records["schema_version"] == manifest["schema_version"],
        "canonical records version differs",
    )
    original = _read_bound(
        root, files, "deliverable/records.original.json", artifact_bytes
    )
    _require(
        sha(original) == manifest["original_input_sha256"]
        and decode_json(original) == records,
        "original canonical records binding differs",
    )
    _require(
        _jsonl(_read_bound(root, files, "deliverable/papers.jsonl", artifact_bytes))
        == records["papers"],
        "canonical paper view differs",
    )
    return manifest, records, files


def _snapshot(root, artifact_bytes):
    if artifact_bytes is None:
        return None
    _require(
        isinstance(artifact_bytes, Mapping) and len(artifact_bytes) <= 2049,
        "bounded canonical artifact snapshot required",
    )
    result, size = {}, 0
    for path, raw in artifact_bytes.items():
        safe_path(root, path)
        _require(
            type(raw) is bytes and len(raw) <= 16 * 1024 * 1024,
            "snapshot artifact bound",
        )
        size += len(raw)
        _require(size <= 64 * 1024 * 1024, "snapshot package bound")
        result[path] = raw
    _require(
        "provenance_manifest.json" in result, "snapshot canonical manifest required"
    )
    return MappingProxyType(result)


def project_canonical_delivery(
    delivery_root, project_id, expected_manifest_sha256, *, artifact_bytes=None
):
    """Return a byte/source-bound Index; never run a semantic runtime replay.

    Only the supplied bare delivery is read. Source receipt identity must match
    its canonical work directly: a mismatch requiring an external extractor is
    refused. Missing readiness stays missing, and canonical 1.1's Stage 2
    consumer remains unconnected. This projection grants no execution permit.
    Optional immutable artifact bytes avoid reopening content during projection;
    callers remain responsible for current physical/source binding validation.
    """
    identifier(project_id)
    root = private_output(delivery_root)
    artifact_bytes = _snapshot(root, artifact_bytes)
    manifest, records, files = _delivery(root, expected_manifest_sha256, artifact_bytes)

    def bound_read(path):
        return _read_bound(root, files, path, artifact_bytes)

    source_rows = _source_records(root, bound_read, records, semantic_replay=False)
    result = _project_records(
        project_id,
        expected_manifest_sha256,
        files,
        bound_read,
        manifest,
        records,
        source_rows,
        expected_manifest_sha256,
        {
            "status": "not-provided",
            "stage2_execution_authorized": False,
            "reason": "bare-canonical-delivery-has-no-readiness-artifact",
        },
    )
    _require(
        _delivery(root, expected_manifest_sha256, artifact_bytes)
        == (manifest, records, files),
        "canonical delivery changed during projection",
    )
    return result


def project_canonical_atlas(
    delivery_root, project_id, expected_manifest_sha256, *, artifact_bytes=None
):
    """Return (Index, relative-path bytes) for the existing v6 Atlas and Wiki.

    These presentation bytes are derived in memory; the original package is
    never copied, rebuilt or written, and no host or API is created.
    """
    from .atlas import atlas_files
    from .literature_selection import derive_literature_selection, selection_files
    from .wiki import wiki_files

    index = project_canonical_delivery(
        delivery_root,
        project_id,
        expected_manifest_sha256,
        artifact_bytes=artifact_bytes,
    )
    notes = wiki_files(index)
    payload = {
        "index": index,
        "index_sha256": sha(canonical(index)),
        "note_paths": [
            {
                "work_id": paper["work_id"],
                "version_id": paper["version_id"],
                "path": "wiki/"
                + sha(canonical([paper["work_id"], paper["version_id"]]))
                + ".md",
            }
            for paper in index["papers"]
        ],
        "literature_selection": derive_literature_selection(index),
    }
    files = {
        **notes,
        **atlas_files(payload),
        **selection_files(index),
        "workspace-index.json": canonical(index),
        "references.bib": index["bibliography"]["all_bibtex"].encode("utf-8"),
    }
    return index, files

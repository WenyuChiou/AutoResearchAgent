"""Read an already saved canonical delivery without rebuilding its package.

The legacy Index uses virtual ``deliverable/`` paths. Each inventory row below
explicitly maps that path to a physical relative path in the bare delivery.
Its required package_manifest_sha256 field aliases the actual canonical
manifest hash; no private-package envelope or readiness artifact is invented.
"""

import re

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


def _read(root, files, virtual_path):
    _require(virtual_path in files, "unlisted canonical delivery artifact")
    row = files[virtual_path]
    raw = safe_path(root, row["physical_relative_path"]).read_bytes()
    _require(
        sha(raw) == row["sha256"] and len(raw) == row["bytes"],
        "canonical delivery artifact bytes differ",
    )
    return raw


def _delivery(root, expected):
    _require(
        isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected),
        "external canonical manifest hash required",
    )
    path = safe_path(root, "provenance_manifest.json")
    raw = path.read_bytes()
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
            physical_path != "provenance_manifest.json" and artifact.is_file(),
            "canonical inventory artifact unavailable",
        )
        files["deliverable/" + physical_path] = {
            "sha256": digest,
            "bytes": artifact.stat().st_size,
            "physical_relative_path": physical_path,
        }
    _require(inventory(root) == declared, "canonical delivery inventory differs")
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
    original = _read(root, files, "deliverable/records.original.json")
    _require(
        sha(original) == manifest["original_input_sha256"]
        and decode_json(original) == records,
        "original canonical records binding differs",
    )
    _require(
        _jsonl(_read(root, files, "deliverable/papers.jsonl")) == records["papers"],
        "canonical paper view differs",
    )
    return manifest, records, files


def project_canonical_delivery(delivery_root, project_id, expected_manifest_sha256):
    """Return a byte/source-bound Index; never run a semantic runtime replay.

    Only the supplied bare delivery is read. Source receipt identity must match
    its canonical work directly: a mismatch requiring an external extractor is
    refused. Missing readiness stays missing, and canonical 1.1's Stage 2
    consumer remains unconnected. This projection grants no execution permit.
    """
    identifier(project_id)
    root = private_output(delivery_root)
    manifest, records, files = _delivery(root, expected_manifest_sha256)

    def bound_read(path):
        return _read(root, files, path)

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
        _delivery(root, expected_manifest_sha256) == (manifest, records, files),
        "canonical delivery changed during projection",
    )
    return result


def project_canonical_atlas(delivery_root, project_id, expected_manifest_sha256):
    """Return (Index, relative-path bytes) for the existing v6 Atlas and Wiki.

    These presentation bytes are derived in memory; the original package is
    never copied, rebuilt or written, and no host or API is created.
    """
    from .atlas import atlas_files
    from .literature_selection import derive_literature_selection, selection_files
    from .wiki import wiki_files

    index = project_canonical_delivery(
        delivery_root, project_id, expected_manifest_sha256
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

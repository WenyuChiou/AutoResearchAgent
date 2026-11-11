"""Retain original Core history and nullable observations without source promotion."""

import copy
import json
from pathlib import Path

from stage1_deliverable import core_records, screening_records
from stage1_deliverable.common import private_output, reject_links, safe_path, sha
from stage1_deliverable.records import validate_records

VERSION = "2.7.0"
PREFIX = "stage1_core"


def project_claim(row):
    """Project the current observation; the complete event remains in original records."""
    return {
        "origin": "stage1",
        "evidence_id": row["claim_id"],
        "source_id": row["source_id"],
        "work_id": row["work_id"],
        "version_id": row["version_id"],
        "claim_text": row["text"],
        "core_event_sha256": row["core_event"]["event_sha256"],
        "core_artifact": {
            "path": PREFIX
            + "/"
            + core_records.artifact_path(row["core_event"]["payload"]["source_ref"]),
            "sha256": row["core_event"]["payload"]["source_ref"]["sha256"],
        },
        **{
            key: copy.deepcopy(row[key])
            for key in (
                "relation",
                "evidence_level",
                "locator",
                "start",
                "end",
                "quote",
            )
        },
    }


def _artifact_names(records):
    names = [row["artifact_path"] for row in records["core_artifacts"]]
    if records["schema_version"] == "1.2.0":
        names.extend(row["artifact_path"] for row in records["screening_artifacts"])
        names.append(records["screening_journal"]["path"])
    return sorted(set(names))


def _core_io(root, name):
    from stage2_workflow.store import _io

    # Check the original root before safe_path resolves Windows aliases.
    _io(Path(root))
    path = safe_path(root, name)
    target = _io(path)
    if target != path:
        # Ordinary lstat can report a deep existing entry as missing.
        reject_links(target)
    return target


def _private_core_output(root):
    from stage2_workflow.store import _io

    ordinary = private_output(root)
    target = _io(ordinary)
    if target != ordinary:
        # Inspect the same private-root markers when ordinary lstat cannot
        # observe a deep Windows ancestor. Keep the ordinary logical root.
        private_output(target)
    return ordinary


def _read_file(root, name):
    return _core_io(root, name).read_bytes()


def _write_file(root, name, raw):
    path = _core_io(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def retain_core_source(deliverable_root, handoff_path, output, records):
    """Copy direct reproducibility artifacts only; this is not source admission."""
    output = _private_core_output(output)
    descriptor = {
        "kind": "Stage1CoreSource",
        "schema_version": "1.0.0",
        "records_version": records["schema_version"],
        "files": [],
        "scientific_quality_verified": False,
        "execution_authorized": False,
    }
    entries = [
        (name, safe_path(deliverable_root, name))
        for name in (
            "records.original.json",
            "provenance_manifest.json",
            *_artifact_names(records),
        )
    ]
    entries.append(("handoff.json", Path(handoff_path)))
    for name, original in entries:
        reject_links(original)
        # The trusted Stage1 package already owns its source I/O paths.
        raw = original.read_bytes()
        relative = PREFIX + "/" + name
        _write_file(output, relative, raw)
        descriptor["files"].append({"path": relative, "sha256": sha(raw)})
    return descriptor


def file_refs(packet):
    """Return fixed-namespace provenance refs, empty for historical packet formats."""
    if packet.get("schema_version") != VERSION:
        return []
    return packet["core_source"]["files"]


def copy_files(packet, source_root, output_root):
    """Relocate the retained closure unchanged; packet paths remain stable."""
    refs = file_refs(packet)
    if not refs:
        return
    output_root = _private_core_output(output_root)
    for ref in refs:
        raw = _read_file(source_root, ref["path"])
        if sha(raw) != ref["sha256"]:
            from .contract import Stage2Error

            raise Stage2Error("stage1-core-artifact-hash-mismatch")
        _write_file(output_root, ref["path"], raw)


def validate_core_source(packet, root):
    """Replay original Core/screening semantics and immutable selected projections."""
    from .contract import Stage2Error

    def require(condition, message):
        if not condition:
            raise Stage2Error("stage1-core-" + message)

    try:
        descriptor = packet["core_source"]
        require(packet["schema_version"] == VERSION, "packet-version")
        require(
            type(descriptor) is dict
            and set(descriptor)
            == {
                "kind",
                "schema_version",
                "records_version",
                "files",
                "scientific_quality_verified",
                "execution_authorized",
            },
            "descriptor-shape",
        )
        require(
            descriptor["kind"] == "Stage1CoreSource"
            and descriptor["schema_version"] == "1.0.0"
            and descriptor["scientific_quality_verified"] is False
            and descriptor["execution_authorized"] is False,
            "descriptor-boundary",
        )
        refs = descriptor["files"]
        paths = [ref["path"] for ref in refs]
        require(
            len(paths) == len(set(path.casefold() for path in paths)), "duplicate-path"
        )
        for ref in refs:
            require(ref["path"].startswith(PREFIX + "/"), "path-namespace")
            require(
                sha(_read_file(root, ref["path"])) == ref["sha256"],
                "artifact-hash-mismatch",
            )
        base = Path(root) / PREFIX
        raw_records = _read_file(base, "records.original.json")
        raw_manifest = _read_file(base, "provenance_manifest.json")
        raw_handoff = _read_file(base, "handoff.json")
        records = json.loads(raw_records)
        manifest = json.loads(raw_manifest)
        handoff = json.loads(raw_handoff)
        validate_records(records)
        require(records["schema_version"] in {"1.1.0", "1.2.0"}, "records-version")
        require(
            records["schema_version"] == descriptor["records_version"],
            "descriptor-version",
        )
        expected = {
            PREFIX + "/" + name
            for name in (
                "records.original.json",
                "provenance_manifest.json",
                "handoff.json",
                *_artifact_names(records),
            )
        }
        require(set(paths) == expected, "artifact-closure-mismatch")

        def read_artifact(name):
            return _read_file(base, name)

        core_records.validate_artifacts(records, read_artifact)
        if records["schema_version"] == "1.2.0":
            screening_records.validate_artifacts(records, read_artifact)
        upstream = packet["upstream"]
        require(
            sha(raw_records) == upstream["stage1_records_sha256"], "records-binding"
        )
        require(
            sha(raw_manifest) == upstream["stage1_deliverable_manifest_sha256"],
            "manifest-binding",
        )
        require(
            sha(raw_handoff) == upstream["stage1_handoff_sha256"], "handoff-binding"
        )
        require(manifest["canonical_records"] == records, "manifest-records-mismatch")
        require(
            manifest["original_input_sha256"] == sha(raw_records),
            "original-input-mismatch",
        )
        from stage2_workflow.import_stage1 import verify_stage1_handoff

        verify_stage1_handoff(
            handoff, sha(raw_manifest), upstream["research_brief_sha256"]
        )
        require(handoff["schema_version"] == "1.0.0", "native-handoff-required")
        require(
            handoff["source_run_id"] == upstream["source_run_id"]
            and handoff["source_state_sha256"] == upstream["source_state_sha256"],
            "run-state-mismatch",
        )
        require(handoff["eligible_for_stage2"] is True, "handoff-ineligible")
        included = set(upstream["included_work_ids"])
        selected = handoff["papers"]
        papers = {row["work_id"]: row for row in records["papers"]}
        require(
            selected and len({row["work_id"] for row in selected}) == len(selected),
            "handoff-paper-set-invalid",
        )
        for row in selected:
            paper = papers.get(row["work_id"])
            require(
                paper is not None
                and paper["version_id"]
                == (row["reviewed_version_id"] or row["listed_version_id"])
                and paper["title"] == row["title"],
                "handoff-paper-binding-mismatch",
            )
        require(
            included == {row["work_id"] for row in handoff["papers"]},
            "included-set-mismatch",
        )
        fields = ("source_id", "work_id", "version_id")
        require(
            {
                tuple(row[k] for k in fields)
                for row in packet["sources"]
                if row["origin"] == "stage1"
            }
            == {
                tuple(row[k] for k in fields)
                for row in records["sources"]
                if row["work_id"] in included
            },
            "source-identity-projection-mismatch",
        )
        require(
            not any(row["path"].startswith(PREFIX + "/") for row in packet["sources"]),
            "source-path-collides-with-provenance",
        )
        literature = [
            {"origin": "stage1", **copy.deepcopy(row)}
            for row in sorted(records["papers"], key=lambda row: row["work_id"])
            if row["work_id"] in included
        ]
        require(
            [row for row in packet["literature"] if row["origin"] == "stage1"]
            == literature,
            "literature-projection-mismatch",
        )
        evidence = [
            project_claim(row)
            for row in records["claims"]
            if row["work_id"] in included
        ]
        require(
            [row for row in packet["evidence"] if row["origin"] == "stage1"]
            == evidence,
            "claim-projection-mismatch",
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        if isinstance(error, Stage2Error):
            raise
        raise Stage2Error("stage1-core-provenance-invalid: " + str(error)) from error

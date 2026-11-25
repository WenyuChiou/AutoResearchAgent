"""Freeze saved evidence for the existing admission consumer; never grant approval.

The request and its external SHA are operator-supplied evidence, not authenticated
identity. A native project-state export and replayable journal bind the checkpoint.
Missing material yields a diagnostic, never a renamed CandidateSnapshot.
"""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import tempfile

from stage1_deliverable.common import canonical, private_output, safe_path, sha
from stage1_ledger.journal import Journal
from stage1_ledger.sources import replay as replay_sources
from stage1_ledger.validation import validate_run
from .final_delivery import _view
from .saved_admission import check_snapshot, inspect_saved_admission, require
from .saved_admission_evidence import read_bound, read_bound_json, valid_input_version


BINDINGS = (
    "original_request",
    "brief",
    "resources",
    "deliverable",
    "view",
    "companion",
)
MATERIALS = ("raw_source", "extracted_text", "full_note", "acquisition_provenance")


def _same_version(left, right):
    return type(left) is type(right) and left == right and valid_input_version(left)


def _inventory(root):
    return {
        p.relative_to(root).as_posix(): sha(
            safe_path(root, p.relative_to(root).as_posix()).read_bytes()
        )
        for p in root.rglob("*")
        if p.is_file()
    }


def export_snapshot(evidence_root, request_ref, output):
    """Validate native bindings and freeze a self-contained private evidence bundle.

    Return missing prerequisites without publishing output. Successful generation
    still has a blocked Stage1Handoff until separate external acceptance exists.
    Repeating an identical export validates again and leaves the old bytes intact.
    """
    root, output = private_output(evidence_root), private_output(output)
    require(
        root.is_dir() and output.parent.is_dir(),
        "existing input/output parent required",
    )
    require(
        not output.is_relative_to(root) and not root.is_relative_to(output),
        "output overlaps evidence",
    )
    request = read_bound_json(root, request_ref)
    require(
        type(request) is dict
        and set(request)
        == {
            "project_id",
            "input_version",
            "admission_id",
            "recorded_at",
            "project_state",
            "checkpoint_event_id",
            "ledger_path",
            "bindings",
            "materials",
        },
        "export request fields invalid",
    )
    require(
        valid_input_version(request["input_version"]), "typed input version required"
    )
    require(
        all(
            type(request[k]) is str and request[k].strip()
            for k in (
                "project_id",
                "admission_id",
                "recorded_at",
                "checkpoint_event_id",
                "ledger_path",
            )
        ),
        "export identity required",
    )
    at = datetime.fromisoformat(request["recorded_at"].replace("Z", "+00:00"))
    require(at.utcoffset() is not None, "export timestamp needs timezone")
    bindings, materials = request["bindings"], request["materials"]
    require(
        type(bindings) is dict and set(bindings) == set(BINDINGS),
        "binding fields invalid",
    )
    require(
        type(materials) is list and 0 < len(materials) <= 1024, "material list required"
    )
    missing, files = [], {}

    def bound(ref, label):
        if ref is None:
            missing.append({"field": label, "reason": "not supplied"})
            return None
        raw = read_bound(root, ref)
        files[ref["path"]] = raw
        return raw

    for name in BINDINGS:
        bound(bindings[name], "bindings." + name)
    for name in ("brief", "resources"):
        if bindings[name] is not None:
            value = read_bound_json(root, bindings[name])
            require(
                value.get("project_id") == request["project_id"]
                and _same_version(value.get("input_version"), request["input_version"]),
                name + " typed identity mismatch",
            )
    project = read_bound_json(root, request["project_state"])
    bound(request["project_state"], "project_state")
    require(
        project.get("project_ref") == request["project_id"]
        and _same_version(project.get("input_version"), request["input_version"]),
        "project identity mismatch",
    )
    run = project.get("stage1_runs", {}).get(project.get("stage1_active"))
    require(
        type(run) is dict
        and run.get("last_checkpoint") == request["checkpoint_event_id"],
        "project checkpoint mismatch",
    )
    binding = run["binding"]
    require(
        binding.get("project_id") == request["project_id"]
        and _same_version(binding.get("input_version"), request["input_version"]),
        "run identity mismatch",
    )
    if bindings["brief"] is not None:
        require(
            binding.get("brief_sha256") == bindings["brief"]["sha256"],
            "project brief mismatch",
        )
    ledger_root = safe_path(root, request["ledger_path"])
    journal = Journal(ledger_root)
    require(
        sha((ledger_root / "run_manifest.json").read_bytes()) == run["manifest_sha256"],
        "ledger manifest mismatch",
    )
    report = validate_run(ledger_root)
    checkpoint, candidates = None, []
    if not report["valid"]:
        missing.append({"field": "ledger", "reason": report["errors"]})
    else:
        events = journal.events()
        checkpoints = [
            e["payload"] for e in events if e["payload"]["kind"] == "Checkpoint"
        ]
        require(
            bool(checkpoints)
            and checkpoints[-1]["event_id"] == request["checkpoint_event_id"],
            "latest checkpoint required",
        )
        checkpoint = checkpoints[-1]
        require(
            checkpoint["state_sha256"] == report["state_sha256"], "checkpoint is stale"
        )
        require(
            at
            >= datetime.fromisoformat(checkpoint["created_at"].replace("Z", "+00:00")),
            "export predates checkpoint",
        )
        for ref in checkpoint["stage_result"]["outputs"]:
            value = json.loads(journal.read_ref(ref))
            if value["kind"] == "CandidateSnapshot":
                candidates = value["rows"]
    source_ids = []
    for n, material in enumerate(materials):
        require(
            type(material) is dict and set(material) == {"source_id", *MATERIALS},
            "material fields invalid",
        )
        require(
            type(material["source_id"]) is str and material["source_id"],
            "source identity required",
        )
        source_ids.append(material["source_id"])
        for name in MATERIALS:
            bound(material[name], f"materials[{n}].{name}")
    require(len(source_ids) == len(set(source_ids)), "duplicate material source")
    # Readiness diagnostics are not a successful snapshot. Preserve independent
    # coverage blockers even when a schema/version failure stops journal replay.
    result = {
        "kind": "SavedSourceSnapshotExport",
        "project_id": request["project_id"],
        "input_version": request["input_version"],
        "checkpoint_event_id": request["checkpoint_event_id"],
        "request_ref": request_ref,
        "ledger_validation": report,
        "checkpoint_gate": checkpoint["stage_result"]["gate"] if checkpoint else None,
        "missing": missing,
        "snapshot_ref": None,
        "eligible_for_stage2": False,
        "execution_authorized": False,
        "status": "missing-prerequisites",
    }
    if missing:
        return result
    _, index, _ = _view(
        (root / bindings["view"]["path"]).parent, bindings["view"]["sha256"]
    )
    require(index.get("project_id") == request["project_id"], "view project mismatch")
    paper_by_work = {p["work_id"]: p for p in index["papers"]}
    source_by_id = {s["source_id"]: s for s in index["sources"]}
    rows = []
    saved_sources = replay_sources(journal)
    for material in materials:
        source = source_by_id.get(material["source_id"])
        require(source is not None, "material absent from validated view")
        work, version = source["work_id"], source["version_id"]
        require(
            work in paper_by_work and paper_by_work[work]["version_id"] == version,
            "view source version mismatch",
        )
        require(
            _same_version(
                paper_by_work[work].get("input_version"), request["input_version"]
            ),
            "view paper typed input version mismatch",
        )
        require(
            any(
                c["work_id"] == work and version in c["version_ids"] for c in candidates
            ),
            "material absent from checkpoint",
        )
        require(
            any(
                saved_sources.starts[key]["work_id"] == work
                and saved_sources.starts[key]["version_id"] == version
                and finish["outcome"] == "available"
                and (finish.get("raw_ref") or {}).get("sha256")
                == material["raw_source"]["sha256"]
                and (finish.get("text_ref") or {}).get("sha256")
                == material["extracted_text"]["sha256"]
                for key, finish in saved_sources.finishes.items()
            ),
            "material bytes absent from checkpoint source history",
        )
        provenance = read_bound_json(root, material["acquisition_provenance"])
        rows.append(
            {
                "work_id": work,
                "version_id": version,
                "source_id": material["source_id"],
                **{name: material[name] for name in MATERIALS},
                "original_acquired_at": provenance.get("original_acquired_at"),
            }
        )
    snapshot = {
        "kind": "SavedSourceCandidateSnapshot",
        "schema_version": "1.0.0",
        **{
            k: request[k]
            for k in ("project_id", "input_version", "admission_id", "recorded_at")
        },
        "source_mode": "saved-source-current-admission",
        "historical_discovery_events": None,
        "historical_trace_status": "missing",
        "bindings": bindings,
        "rows": rows,
    }
    check_snapshot(snapshot)
    # Copy the validator-owned package/view closure, not arbitrary sibling data.
    for directory in (
        (root / bindings[n]["path"]).parent for n in ("deliverable", "view")
    ):
        require(directory != root, "package/view require dedicated directories")
        for path in directory.rglob("*"):
            if path.is_file():
                name = path.relative_to(root).as_posix()
                files[name] = safe_path(root, name).read_bytes()
    for path in ledger_root.rglob("*"):
        if path.is_file():
            name = path.relative_to(root).as_posix()
            files[name] = safe_path(root, name).read_bytes()
    files[request_ref["path"]] = read_bound(root, request_ref)
    names = [name.casefold() for name in files]
    require(len(names) == len(set(names)), "case-insensitive evidence path collision")
    require(
        not {name.split("/", 1)[0] for name in names}.intersection(
            {"snapshot.json", "snapshot-ref.json", "export-receipt.json"}
        ),
        "reserved export filename",
    )
    raw = canonical(snapshot) + b"\n"
    ref = {"path": "snapshot.json", "sha256": sha(raw), "bytes": len(raw)}
    files["snapshot.json"] = raw
    files["snapshot-ref.json"] = canonical(ref) + b"\n"
    with tempfile.TemporaryDirectory(prefix=".snapshot-", dir=output.parent) as temp:
        stage = Path(temp) / "bundle"
        stage.mkdir()
        for name, data in files.items():
            path = safe_path(stage, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        # This is the existing, unmodified consumer: source/view/package/note and
        # qualification checks all run. External acceptance is never supplied.
        handoff = inspect_saved_admission(stage, ref)
        require(not handoff["eligible_for_stage2"], "export cannot grant acceptance")
        require(
            validate_run(stage / request["ledger_path"]) == report,
            "ledger changed during export",
        )
        require(
            all(
                safe_path(root, n).read_bytes() == b
                for n, b in files.items()
                if n not in {"snapshot.json", "snapshot-ref.json"}
            ),
            "evidence changed during export",
        )
        result.update(
            status="snapshot-exported",
            snapshot_ref=ref,
            handoff=handoff,
            checkpoint_sha256=sha(canonical(checkpoint)),
            evidence_sha256={n: sha(b) for n, b in files.items()},
        )
        (stage / "export-receipt.json").write_bytes(canonical(result) + b"\n")
        if output.exists():
            require(
                output.is_dir() and _inventory(output) == _inventory(stage),
                "existing export differs; preserve original",
            )
        else:
            os.rename(stage, output)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_root")
    parser.add_argument(
        "--request-ref",
        required=True,
        help="JSON containing a separately pinned request path/SHA/bytes",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="private directory outside the evidence root and Git",
    )
    args = parser.parse_args(argv)
    try:
        ref = json.loads(Path(args.request_ref).read_text(encoding="utf-8"))
        result = export_snapshot(args.evidence_root, ref, args.output)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0 if result["status"] == "snapshot-exported" else 2
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

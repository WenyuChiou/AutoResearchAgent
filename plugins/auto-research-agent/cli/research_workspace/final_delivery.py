"""Inspect saved Stage 1 delivery prerequisites without granting completion."""

import argparse
import json
from pathlib import Path
import platform
import sys

from stage1_brief.brief import validate_brief
from stage1_brief.formal_target import formal_selection_progress, formal_target_state
from stage1_deliverable.common import (
    DeliverableError,
    canonical,
    private_output,
    safe_path,
    sha,
)
from stage1_ledger.journal import LedgerError

from .json_bytes import decode_json
from .literature_selection import derive_literature_selection, selection_files
from .wiki import wiki_files


def _require(condition, message):
    if not condition:
        raise DeliverableError("final-delivery: " + message)


def _bound_json(path, expected):
    raw = private_output(path).read_bytes()
    _require(sha(raw) == expected, "external artifact hash differs")
    value = decode_json(raw)
    _require(type(value) is dict, "artifact JSON must be an object")
    return value


def _view(root, expected):
    root = private_output(root)
    manifest = _bound_json(safe_path(root, "view-manifest.json"), expected)
    _require(manifest.get("kind") == "WorkspaceReadOnlyView", "wrong view kind")
    files = manifest.get("files")
    _require(type(files) is dict and bool(files), "missing file inventory")

    def inventory():
        actual = {}
        for path in root.rglob("*"):
            name = path.relative_to(root).as_posix()
            checked = safe_path(root, name)
            if checked.is_file() and name != "view-manifest.json":
                actual[name] = sha(checked.read_bytes())
        return actual

    _require(inventory() == files, "view inventory or bytes differ")
    index = _bound_json(
        safe_path(root, "workspace-index.json"), manifest.get("index_sha256")
    )
    selection = derive_literature_selection(index)
    # Source availability labels are not a substitute for the exact saved bytes.
    for name, record in (
        index.get("source_rerun", {}).get("artifact_hashes", {}).items()
    ):
        _require(
            sha(safe_path(root, "source-rerun/" + name).read_bytes())
            == record["sha256"],
            "source rerun artifact differs",
        )
    for name, data in selection_files(index).items():
        _require(
            safe_path(root, name).read_bytes() == data,
            "selection export differs: " + name,
        )
    for name, data in wiki_files(index).items():
        # A Stage 2 attachment can append links to README, not rewrite paper notes.
        if name != "wiki/README.md":
            _require(
                safe_path(root, name).read_bytes() == data,
                "paper note differs: " + name,
            )
    data = safe_path(root, "workspace-data.js").read_text(encoding="utf-8")
    prefix, suffix = "window.WORKSPACE_VIEW = ", ";\n"
    _require(
        data.startswith(prefix) and data.endswith(suffix), "unknown payload wrapper"
    )
    payload = decode_json(data[len(prefix) : -len(suffix)].encode("utf-8"))
    _require(type(payload) is dict, "HTML payload must be an object")
    _require(
        payload.get("index") == index
        and payload.get("index_sha256") == manifest["index_sha256"]
        and payload.get("literature_selection") == selection,
        "HTML payload differs from canonical index or selection",
    )
    for name in ("index.html", "references.bib", "wiki/README.md"):
        _require(name in files, "required workspace file missing: " + name)
    bibliography = index.get("source_rerun", {}).get(
        "bibliography", index["bibliography"]
    )
    _require(
        safe_path(root, "references.bib").read_bytes()
        == bibliography["all_bibtex"].encode("utf-8"),
        "complete screening bibliography differs",
    )
    _require(
        inventory() == files
        and sha(safe_path(root, "view-manifest.json").read_bytes()) == expected,
        "view changed during inspection",
    )
    return manifest, index, selection


def inspect_final_delivery(
    root,
    expected_view_sha256,
    brief_path,
    expected_brief_sha256,
    *,
    timing_path=None,
    expected_timing_sha256=None,
):
    """Check saved prerequisites; final handoff/browser acceptance stays separate.

    External hashes bind the operator-selected artifacts. They do not authenticate
    a researcher, attest brief/index lineage, execute HTML, or approve an import.
    """
    manifest, index, selection = _view(root, expected_view_sha256)
    brief = _bound_json(brief_path, expected_brief_sha256)
    intake = validate_brief(brief)
    target = formal_target_state(brief)
    _require(brief["project_id"] == index["project_id"], "wrong brief project")
    distinct = {
        row["work_id"] for row in selection["rows"] if row["status"] == "included"
    }
    progress = (
        formal_selection_progress(
            brief,
            {
                "project_id": brief["project_id"],
                "input_version": brief["input_version"],
                "rows": selection["rows"],
            },
        )
        if target["status"] == "confirmed"
        else {
            **target,
            "formally_usable_distinct_works": len(distinct),
            "formal_target_met": False,
            "target_shortfall": None,
        }
    )
    ready = intake["necessary_clarification_complete"] and progress["formal_target_met"]
    timing = None
    if timing_path is not None or expected_timing_sha256 is not None:
        _require(
            timing_path is not None and expected_timing_sha256 is not None,
            "both timing arguments required",
        )
        from .run_timing import summarize_timing

        timing = summarize_timing(
            _bound_json(timing_path, expected_timing_sha256),
            project_id=brief["project_id"],
            input_version=brief["input_version"],
            index_sha256=sha(canonical(index)),
        )
    remaining = [
        "confirmed-brief-to-input-lineage",
        "research-deliverable-semantic-validation",
        "coverage-and-claim-review",
        "accepted-stage1-to-stage2-handoff",
        "actual-html-operation-acceptance",
    ]
    if not ready:
        remaining.insert(0, "confirmed-intake-and-formal-work-target")
    return {
        "kind": "Stage1FinalDeliveryPrerequisites",
        "schema_version": "1.0.0",
        "status": "ready-for-final-checks" if ready else "partial",
        "project_id": brief["project_id"],
        "input_version": brief["input_version"],
        "view_manifest_sha256": expected_view_sha256,
        "brief_sha256": expected_brief_sha256,
        "index_canonical_sha256": sha(canonical(index)),
        "selection_sha256": sha(canonical(selection)),
        "source_selection_counts": selection["counts"],
        "formal_progress": progress,
        "intake": intake,
        "saved_projection_reconciled": True,
        "final_checks_required": remaining,
        "stage1_completed": False,
        "official_stage2_import_eligible": False,
        "scientific_quality_scored": False,
        "claim_assessments_changed": False,
        "coverage_complete": False,
        "research_execution": False,
        "html_execution": "not-performed",
        "timing": timing,
        "checker_runtime": {
            "python": platform.python_version(),
            "sources": {
                name: sha(Path(__file__).with_name(name).read_bytes())
                for name in (
                    "final_delivery.py",
                    "run_timing.py",
                    "literature_selection.py",
                    "body_completeness.py",
                    "body_review.py",
                    "body_review_attachment.py",
                    "wiki.py",
                )
            },
        },
        "limits": "Saved-byte/selection checks are prerequisites. Final semantic, lineage, coverage, handoff and actual browser acceptance must be independently evidenced. Operator-supplied hashes are not authentication. No final-completion receipt is minted by this command.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("view_root")
    parser.add_argument("--expected-view-manifest-sha256", required=True)
    parser.add_argument("--brief", required=True)
    parser.add_argument("--expected-brief-sha256", required=True)
    parser.add_argument("--timing")
    parser.add_argument("--expected-timing-sha256")
    args = parser.parse_args(argv)
    try:
        report = inspect_final_delivery(
            args.view_root,
            args.expected_view_manifest_sha256,
            args.brief,
            args.expected_brief_sha256,
            timing_path=args.timing,
            expected_timing_sha256=args.expected_timing_sha256,
        )
    except (
        DeliverableError,
        LedgerError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

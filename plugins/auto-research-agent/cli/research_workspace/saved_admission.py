"""Replay a distinct current saved-source admission; legacy discoveries stay absent."""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator, FormatChecker
from stage1_brief.brief import validate_brief
from stage1_deliverable import package as deliverable_package
from stage1_ledger.handoff import DIMENSIONS
from .final_delivery import _view
from .formal_readiness import derive_formal_readiness
from .saved_admission_evidence import read_bound, read_bound_json


SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "schemas/stage1-saved-admission.v1.schema.json"
)
HTML_ACTIONS = (
    "first-load",
    "paper-detail",
    "graph-selection",
    "full-note",
    "bibtex-download",
    "refresh",
    "keyboard",
)
CORE_CHECKS = (
    "brief-lineage",
    "deliverable-semantics",
    "coverage-and-claim-review",
    "handoff-contract",
)
PRODUCER_FILES = (
    "cli/research_workspace/saved_admission.py",
    "cli/research_workspace/saved_admission_evidence.py",
    "cli/research_workspace/final_delivery.py",
    "cli/research_workspace/formal_readiness.py",
    "cli/stage2_workflow/import_stage1.py",
    "cli/stage2_workflow/__main__.py",
    "schemas/stage1-saved-admission.v1.schema.json",
    "schemas/stage1-handoff.v2.schema.json",
)
REQUIRED_CI_JOBS = {
    "pr-contract",
    "contracts (ubuntu-latest)",
    "contracts (windows-latest)",
    "contracts (macos-latest)",
}


def require(condition, reason):
    if not condition:
        raise ValueError("saved-source-admission: " + reason)


def check_snapshot(snapshot):
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            snapshot
        )
    )
    require(not errors, "snapshot contract invalid")


def check_handoff(handoff):
    schema = json.loads(
        SCHEMA.with_name("stage1-handoff.v2.schema.json").read_text(encoding="utf-8")
    )
    errors = list(Draft202012Validator(schema).iter_errors(handoff))
    require(not errors, "handoff v2 contract invalid")


def reconcile_rows(rows, papers, target):
    require(type(target) is int and target > 0, "target invalid")
    works = [row["work_id"] for row in rows]
    sources = [row["source_id"] for row in rows]
    require(len(works) == len(set(works)), "duplicate work")
    require(len(sources) == len(set(sources)), "duplicate source")
    require(len(works) >= target, "formal work shortfall")
    paper_by_id = {paper["work_id"]: paper for paper in papers}
    for row in rows:
        paper = paper_by_id.get(row["work_id"])
        require(
            paper is not None
            and paper["version_id"] == row["version_id"]
            and row["source_id"] in paper["source_ids"],
            "work/version/source mismatch",
        )
    return set(works)


def resource_totals(control):
    require(control.get("no_resource_reset") is True, "resource reset")
    resources = {}
    for field, name in (
        ("queries", "queries"),
        ("full_source_acquisition_attempts", "acquisitions"),
    ):
        values = [
            control.get(key, {}).get(field)
            for key in (
                "current_round_used",
                "previous_cumulative_used",
                "total_authorized_limits",
            )
        ]
        require(
            all(type(value) is int and value >= 0 for value in values),
            "resource values unknown or invalid",
        )
        used = values[0] + values[1]
        require(used <= values[2], "resource limit exceeded")
        resources[name] = {"used": used, "limit": values[2]}
    return resources


def check_note_binding(row, paper, companion_digest):
    """Reuse the validated companion mapping, independent of a note's prose format."""
    binding = paper.get("fresh_note", {}).get("companion_binding", {})
    require(
        paper.get("work_id") == row["work_id"]
        and paper.get("version_id") == row["version_id"]
        and binding.get("companion_manifest_sha256") == companion_digest
        and binding.get("sha256") == row["full_note"]["sha256"]
        and binding.get("bytes") == row["full_note"]["bytes"],
        "full note companion binding mismatch",
    )


def check_acquisition_binding(row, source, provenance, admission_at):
    """Retain the saved original time; current admission does not recreate acquisition."""
    require(
        provenance.get("raw_sha256") == row["raw_source"]["sha256"]
        and provenance.get("original_acquired_at") == row["original_acquired_at"],
        "original acquisition binding mismatch",
    )
    require(
        any(
            attempt.get("sha256") == row["acquisition_provenance"]["sha256"]
            for attempt in source.get("attempts", [])
        ),
        "acquisition provenance absent from validated source",
    )
    if row["original_acquired_at"] is not None:
        acquired = datetime.fromisoformat(
            row["original_acquired_at"].replace("Z", "+00:00")
        )
        admitted = datetime.fromisoformat(admission_at.replace("Z", "+00:00"))
        require(
            acquired.utcoffset() is not None and acquired <= admitted,
            "original acquisition time invalid",
        )


def _check_acceptance(
    root, ref, trusted_digest, snapshot_digest, snapshot, view_manifest
):
    require(
        trusted_digest == ref["sha256"],
        "Core acceptance needs independent external hash",
    )
    acceptance = read_bound_json(root, ref)
    required = {
        "kind",
        "schema_version",
        "snapshot_sha256",
        "project_id",
        "input_version",
        "contract_sha256",
        "producer",
        "checks",
        "html",
    }
    require(
        set(acceptance) == required
        and acceptance["kind"] == "SavedSourceAdmissionAcceptance"
        and acceptance["schema_version"] == "1.0.0",
        "Core acceptance contract invalid",
    )
    for field, expected in (
        ("snapshot_sha256", snapshot_digest),
        ("project_id", snapshot["project_id"]),
        ("input_version", snapshot["input_version"]),
        ("contract_sha256", hashlib.sha256(SCHEMA.read_bytes()).hexdigest()),
    ):
        require(
            acceptance[field] == expected, "Core acceptance binding mismatch: " + field
        )
    producer = acceptance["producer"]
    require(
        set(producer)
        == {
            "delivered_commit",
            "reviewed_head",
            "merge_parents",
            "merge_tree",
            "sources",
            "ci",
        },
        "producer contract invalid",
    )
    commit = producer["delivered_commit"]
    reviewed = producer["reviewed_head"]
    parents = producer["merge_parents"]
    require(
        all(
            type(value) is str
            and len(value) == 40
            and all(c in "0123456789abcdef" for c in value)
            for value in (commit, reviewed, producer["merge_tree"])
        )
        and type(parents) is list
        and len(parents) == 2
        and len(set(parents)) == 2
        and all(
            type(value) is str
            and len(value) == 40
            and all(c in "0123456789abcdef" for c in value)
            for value in parents
        )
        and reviewed in parents
        and commit not in parents,
        "producer not delivered",
    )
    require(
        set(producer["sources"]) == set(PRODUCER_FILES),
        "producer runtime inventory incomplete",
    )
    for name, digest in producer["sources"].items():
        require(
            hashlib.sha256((SCHEMA.parent.parent / name).read_bytes()).hexdigest()
            == digest,
            "producer runtime changed",
        )
    ci = producer["ci"]
    require(
        type(ci) is list
        and {
            (phase, name)
            for phase, names in (
                ("pr", REQUIRED_CI_JOBS),
                ("post-main", REQUIRED_CI_JOBS - {"pr-contract"}),
            )
            for name in names
        }.issubset({(job.get("phase"), job.get("name")) for job in ci})
        and len({(job.get("phase"), job.get("name")) for job in ci}) == len(ci),
        "CI evidence missing",
    )
    for job in ci:
        require(
            set(job) == {"phase", "name", "head_sha", "run_id", "job_id", "conclusion"}
            and job["phase"] in {"pr", "post-main"}
            and job["head_sha"] == (reviewed if job["phase"] == "pr" else commit)
            and job["conclusion"] == "success"
            and all(
                type(job[key]) is int and job[key] > 0 for key in ("run_id", "job_id")
            ),
            "CI not successful on delivered producer",
        )
    require(
        set(acceptance["checks"]) == set(CORE_CHECKS),
        "Core acceptance categories incomplete",
    )
    for category in CORE_CHECKS:
        check = read_bound_json(root, acceptance["checks"][category])
        require(
            set(check)
            == {
                "kind",
                "category",
                "snapshot_sha256",
                "project_id",
                "input_version",
                "scope",
                "validator",
                "rubric",
                "results",
                "outcome",
                "observations",
                "evidence",
            }
            and check.get("kind") == "SavedSourceAdmissionReview"
            and check.get("category") == category
            and check.get("snapshot_sha256") == snapshot_digest
            and check.get("project_id") == snapshot["project_id"]
            and check.get("input_version") == snapshot["input_version"]
            and check.get("scope") == "saved-source-current-admission"
            and check.get("outcome") == "accepted"
            and type(check.get("observations")) is str
            and bool(check["observations"].strip())
            and type(check.get("evidence")) is list
            and bool(check["evidence"]),
            "Core review missing: " + category,
        )
        read_bound(root, check["validator"])
        read_bound(root, check["rubric"])
        require(
            type(check["results"]) is list and bool(check["results"]),
            "Core checks absent",
        )
        for result in check["results"]:
            require(
                set(result) == {"check_id", "status", "locator", "reason"}
                and result["status"] == "passed"
                and all(
                    type(result[key]) is str and bool(result[key].strip())
                    for key in ("check_id", "locator", "reason")
                ),
                "Core check result invalid",
            )
        for evidence in check["evidence"]:
            read_bound(root, evidence)
    html = read_bound_json(root, acceptance["html"])
    require(
        html.get("kind") == "ActualHtmlOperationReceipt"
        and html.get("schema_version") == "1.0.0"
        and html.get("snapshot_sha256") == snapshot_digest,
        "HTML receipt invalid or stale",
    )
    files = view_manifest["files"]
    expected_html = files.get("index.html")
    require(
        expected_html is not None and html.get("html_sha256") == expected_html,
        "HTML version mismatch",
    )
    operations = html.get("operations")
    require(
        type(operations) is list
        and len(operations) == len(HTML_ACTIONS)
        and {row.get("action") for row in operations} == set(HTML_ACTIONS),
        "HTML operations incomplete",
    )
    for operation in operations:
        require(
            operation.get("status") == "passed"
            and type(operation.get("tool_action_ref")) is str
            and bool(operation["tool_action_ref"].strip())
            and operation.get("evidence"),
            "HTML action unobserved",
        )
        start = datetime.fromisoformat(operation["started_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(operation["ended_at"].replace("Z", "+00:00"))
        require(
            start.utcoffset() is not None
            and end.utcoffset() is not None
            and end >= start,
            "HTML operation time invalid",
        )
        for evidence in operation["evidence"]:
            require(bool(read_bound(root, evidence)), "HTML evidence empty")
    downloaded = read_bound(root, html["bibtex_download"])
    expected_bib = html["expected_bibtex"]
    # The expected bibliography must be a member of the already validated view.
    view_root = (Path(root) / snapshot["bindings"]["view"]["path"]).parent
    relative = (
        Path(expected_bib["path"])
        .relative_to(view_root.relative_to(Path(root)))
        .as_posix()
    )
    require(
        relative == "literature/included-references.bib"
        and relative in files
        and expected_bib["sha256"] == files[relative],
        "HTML bibliography not in validated view",
    )
    require(downloaded == read_bound(root, expected_bib), "BibTeX download differs")
    return acceptance


def inspect_saved_admission(
    root, snapshot_ref, *, acceptance_ref=None, trusted_acceptance_sha256=None
):
    """Recompute prerequisites and bound external acceptance without minting approval.

    The external Core digest is an explicit trust boundary. Hashes cannot authenticate
    reviewers, browser actions, GitHub or scientific truth by themselves.
    """
    snapshot = read_bound_json(root, snapshot_ref)
    check_snapshot(snapshot)
    bindings = snapshot["bindings"]
    for ref in bindings.values():
        read_bound(root, ref)
    brief = read_bound_json(root, bindings["brief"])
    validate_brief(brief, require_confirmed=True)
    require(
        (brief["project_id"], brief["input_version"])
        == (snapshot["project_id"], snapshot["input_version"]),
        "brief identity mismatch",
    )
    control = read_bound_json(root, bindings["resources"])
    require(
        (control.get("project_id"), control.get("input_version"))
        == (snapshot["project_id"], snapshot["input_version"]),
        "resource identity mismatch",
    )
    resources = resource_totals(control)
    view_root = (Path(root) / bindings["view"]["path"]).parent
    view_manifest, index, selection = _view(view_root, bindings["view"]["sha256"])
    progress = derive_formal_readiness(index, brief, resources=resources)
    require(
        progress["decision"] == "stop-count-target-and-covered",
        "qualification or need coverage incomplete",
    )
    require(progress["note_pending_versions"] == 0, "notes incomplete")
    deliverable_root = (Path(root) / bindings["deliverable"]["path"]).parent
    deliverable_package.validate(deliverable_root, bindings["deliverable"]["sha256"])
    manifest = read_bound_json(root, bindings["deliverable"])
    papers = manifest["canonical_records"]["papers"]
    included = reconcile_rows(snapshot["rows"], papers, progress["target"])
    require(
        included == set(progress["formally_usable_work_ids"]),
        "formal selection differs",
    )
    source_by_id = {source["source_id"]: source for source in index["sources"]}
    for row in snapshot["rows"]:
        raw = read_bound(root, row["raw_source"])
        text = read_bound(root, row["extracted_text"])
        note = read_bound_json(root, row["full_note"])
        require(
            raw and text and type(note) is dict and bool(note),
            "source or full note absent",
        )
        source = source_by_id.get(row["source_id"])
        require(
            source is not None
            and source["work_id"] == row["work_id"]
            and source["version_id"] == row["version_id"],
            "view source identity mismatch",
        )
        check_acquisition_binding(
            row,
            source,
            read_bound_json(root, row["acquisition_provenance"]),
            snapshot["recorded_at"],
        )
        # Source-rerun bytes were independently replayed by _view; qualification
        # references are then compared to the exact raw/text admitted here.
        paper = next(p for p in index["papers"] if p["work_id"] == row["work_id"])
        check_note_binding(row, paper, bindings["companion"]["sha256"])
        qualification = paper["fresh_note"]["source_qualification"]
        require(
            qualification.get("source_id") == row["source_id"]
            and qualification.get("raw_sha256") == row["raw_source"]["sha256"]
            and qualification.get("text_sha256") == row["extracted_text"]["sha256"],
            "qualification source hashes mismatch",
        )
    require(
        (acceptance_ref is None) == (trusted_acceptance_sha256 is None),
        "both acceptance inputs required",
    )
    acceptance = None
    if acceptance_ref is not None:
        acceptance = _check_acceptance(
            root,
            acceptance_ref,
            trusted_acceptance_sha256,
            snapshot_ref["sha256"],
            snapshot,
            view_manifest,
        )
    result = {
        "kind": "Stage1Handoff",
        "schema_version": "2.0.0",
        "source_mode": "saved-source-current-admission",
        "source_run_id": snapshot["admission_id"],
        "source_state_sha256": snapshot_ref["sha256"],
        "snapshot_ref": snapshot_ref,
        "acceptance_ref": acceptance_ref,
        "project_id": snapshot["project_id"],
        "input_version": snapshot["input_version"],
        "deliverable_manifest_sha256": bindings["deliverable"]["sha256"],
        "brief_sha256": bindings["brief"]["sha256"],
        "papers": [
            {
                "work_id": paper["work_id"],
                "title": paper["title"],
                "listed_version_id": paper["version_id"],
                "reviewed_version_id": paper["version_id"],
            }
            for paper in papers
            if paper["work_id"] in included
        ],
        "comparison_dimensions": DIMENSIONS,
        "resources_preserved": resources,
        "limitations": [
            "Saved-source current admission; historical discovery trace is missing.",
            "Claim relations and Unknowns remain unchanged; no scientific sufficiency asserted.",
        ],
        "stage1_gate": {
            "status": "ready-for-import" if acceptance else "blocked",
            "quantity_decision": progress["decision"],
            "remaining": []
            if acceptance
            else [*CORE_CHECKS, "actual-html-operation-acceptance"],
        },
        "eligible_for_stage2": acceptance is not None,
        "stage1_completed": False,
        "stage2": {"status": "not-started", "execution_authorized": False},
    }
    check_handoff(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_root")
    parser.add_argument(
        "--snapshot-ref",
        required=True,
        help="JSON file containing the externally bound snapshot ref",
    )
    parser.add_argument("--acceptance-ref")
    parser.add_argument("--trusted-acceptance-sha256")
    args = parser.parse_args(argv)
    try:
        snapshot_ref = json.loads(Path(args.snapshot_ref).read_text(encoding="utf-8"))
        acceptance_ref = (
            json.loads(Path(args.acceptance_ref).read_text(encoding="utf-8"))
            if args.acceptance_ref
            else None
        )
        result = inspect_saved_admission(
            args.evidence_root,
            snapshot_ref,
            acceptance_ref=acceptance_ref,
            trusted_acceptance_sha256=args.trusted_acceptance_sha256,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

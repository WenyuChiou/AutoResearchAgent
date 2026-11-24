"""Receive a project's own published Stage 1 input without starting Stage 2."""

from contextlib import nullcontext
import sqlite3

from stage1_deliverable.common import private_output, reject_links, safe_path, sha
from stage1_ledger.journal import LedgerError, canonical, decode, write_new
from stage2_common import canonical_hash, validate_packet
from stage2_workflow import build_stage2_seed
from stage2_workflow.store import _write_new as publish_new

from .project_stage1_coverage import unresolved
from .project_stage2_profile import read_initial_seed
from .session_api import SessionApiError, _check


RECEIVER = "stage2-current-project-receiver"


def _blocked(view, reason):
    return {**view, "status": "blocked", "reason": reason}


def _reference(view, bound, binding, brief, native_run_id):
    source = {
        key: bound[key]
        for key in (
            "artifact_ref",
            "run_ref",
            "checkpoint_event_id",
            "ledger_state_sha256",
            "manifest_sha256",
            "handoff_sha256",
            "records_sha256",
        )
    }
    return {
        **source,
        "project_ref": view["project_ref"],
        "input_version": view["input_version"],
        "brief_sha256": view["brief_sha256"],
        "canonical_brief_sha256": canonical_hash(brief),
        "resources_sha256": canonical_hash(
            binding["settings"]["resource_envelope"].strip()
        ),
        "native_run_id": native_run_id,
        "plan_manifest_sha256": binding["plan_manifest_sha256"],
        "settings_sha256": bound["binding"]["settings_sha256"],
    }


def _packet(root, pin, source):
    seed = safe_path(root, "seed")
    packet = read_initial_seed(seed, pin)
    validate_packet(packet, seed)
    upstream = packet["upstream"]
    _check(
        all(
            upstream[field] == source[key]
            for field, key in (
                ("stage1_deliverable_manifest_sha256", "manifest_sha256"),
                ("stage1_handoff_sha256", "handoff_sha256"),
                ("stage1_records_sha256", "records_sha256"),
                ("source_state_sha256", "ledger_state_sha256"),
                ("research_brief_sha256", "canonical_brief_sha256"),
                ("resources_sha256", "resources_sha256"),
                ("source_run_id", "native_run_id"),
            )
        )
        and upstream["eligible_for_stage2"] is True
        and upstream["stage2"]
        == {"status": "not-started", "execution_authorized": False}
        and packet["candidates"] == [],
        "stage2-current-input-binding-differs",
    )
    return packet


def _receive(intake, view, binding, bound, source, check_deadline, check_owner):
    digest = canonical_hash(source)
    root = private_output(intake._path(view["project_ref"], "s2r-" + digest[:32]))
    check_deadline()
    receipt_path = safe_path(root, "receipt.json")
    identity = {
        "kind": "Stage2CurrentProjectInputReceipt",
        "schema_version": "1.0.0",
        "recorded_by": RECEIVER,
        "source": source,
        "source_descriptor_sha256": digest,
    }
    try:
        root.mkdir()
    except FileExistsError:
        reject_links(root)
        if not receipt_path.is_file():
            return _blocked(view, "stage2-current-input-publication-unobserved")
        with receipt_path.open("rb") as stream:
            raw = stream.read(8193)
        _check(len(raw) <= 8192, "stage2-current-input-receipt-invalid")
        receipt = decode(raw, "Stage2 current project input receipt")
        _check(
            raw == canonical({**identity, "packet_sha256": receipt["packet_sha256"]}),
            "stage2-current-input-receipt-binding-differs",
        )
        packet = _packet(root, receipt["packet_sha256"], source)
    else:
        resources = safe_path(root, "resources.txt")
        write_new(resources, binding["settings"]["resource_envelope"].encode("utf-8"))
        imported = build_stage2_seed(
            bound["deliverable_dir"],
            bound["manifest_sha256"],
            bound["handoff_path"],
            bound["handoff_sha256"],
            binding["brief_path"],
            resources,
            safe_path(root, "seed"),
            allow_current_core=True,
        )
        packet = _packet(root, imported["packet_sha256"], source)
        receipt = {**identity, "packet_sha256": imported["packet_sha256"]}
        raw = canonical(receipt)
        check_owner()
        check_deadline()
        publish_new(receipt_path, raw)
    check_owner()
    check_deadline()
    return {
        **view,
        "status": "received",
        "recorded_by": RECEIVER,
        "source_descriptor_sha256": digest,
        "source": source,
        "receipt_sha256": sha(raw),
        "stage1_atlas_url": (
            f"/api/projects/{source['project_ref']}/stage1/atlas/{source['input_version']}/"
            f"{view['revision']}/{source['artifact_ref']}/{source['manifest_sha256']}"
        ),
        "packet_id": packet["packet_id"],
        "packet_schema_version": packet["schema_version"],
        "packet_sha256": receipt["packet_sha256"],
        "source_work_ids": packet["upstream"]["included_work_ids"],
        "source_count": len(packet["sources"]),
        "candidate_count": len(packet["candidates"]),
    }


def current_evidence(delivery, credential, stage1, project, *, check_deadline=None):
    """Return the current project's verified Stage 2 input or its actual blockers."""
    ref = project["project_ref"]
    ledger_view = stage1.get("ledger") or {}
    checkpoint = stage1.get("checkpoint")
    view = {
        "project_ref": ref,
        "revision": project["revision"],
        "input_version": project["input_version"],
        "brief_sha256": project["brief_sha256"],
        "checkpoint_event_id": checkpoint["event_id"] if checkpoint else None,
        "gate_blockers": list(
            (ledger_view.get("gate") or {}).get("blocking_items", [])
        ),
        "next_allowed_action": ledger_view.get("next_allowed_action"),
        "execution_authorized": False,
    }
    if stage1.get("stage1_status") in {
        "query-runtime-unconnected",
        "owner-reopen-required",
    }:
        return _blocked(view, "stage2-current-evidence-owner-unavailable")
    if not checkpoint or not checkpoint["current"]:
        return _blocked(view, "stage1-current-checkpoint-unavailable")
    if view["next_allowed_action"] != "stop-sufficient":
        return _blocked(view, "stage1-not-eligible-for-stage2")
    check_deadline = check_deadline or (lambda: None)
    intake = delivery.intake
    try:
        with intake._lock:
            # All normal intake writers use an IMMEDIATE transaction. Hold the
            # same boundary through publication and keep SQLite data untouched.
            check_deadline()
            intake.db.execute("BEGIN IMMEDIATE")
            try:
                principal = intake._principal(credential)
                state = intake._load(principal, ref)
                _check(state["revision"] == project["revision"], "stale-revision")
                _check(
                    not unresolved(
                        delivery.stage1, ref, principal, view["input_version"]
                    ),
                    "stage1-coverage-write-outcome-unobserved",
                )
                _, _, binding, run, ledger, report = delivery._saved_context(ref)
                guard = nullcontext(lambda: None)
                if run.get("query_owned"):
                    owner = getattr(delivery.stage1, "query_service", None)
                    factory = getattr(owner, "saved_records_guard", None)
                    _check(
                        callable(factory), "stage2-current-evidence-owner-unavailable"
                    )
                    guard = factory(run, ledger, report)
                # Direct Core writes share the journal's writer lock. Use its
                # non-repairing mode and the query owner's established lock order.
                with guard as check_owner, ledger.writing(repair=False):
                    bound = delivery.binding(ref)
                    bound_version = bound["binding"]["input_version"]
                    _check(
                        bound["project_ref"] == bound["binding"]["project_id"] == ref
                        and type(bound_version) is type(view["input_version"])
                        and bound_version == view["input_version"]
                        and bound["binding"]["brief_sha256"] == view["brief_sha256"]
                        and bound["checkpoint_event_id"] == checkpoint["event_id"]
                        and bound["ledger_state_sha256"] == ledger_view["state_sha256"]
                        and bound["eligible_for_stage2"] is True,
                        "stage2-current-evidence-binding-differs",
                    )
                    source = _reference(
                        view,
                        bound,
                        binding,
                        project["brief"],
                        ledger.manifest["research_run"]["run_id"],
                    )
                    return _receive(
                        intake,
                        view,
                        binding,
                        bound,
                        source,
                        check_deadline,
                        check_owner,
                    )
            finally:
                intake.db.rollback()
    except SessionApiError as error:
        return _blocked(view, error.code)
    except (LedgerError, sqlite3.OperationalError):
        return _blocked(view, "stage2-current-evidence-owner-unavailable")
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return _blocked(view, "stage2-current-evidence-validation-failed")

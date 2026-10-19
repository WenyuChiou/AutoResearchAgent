"""Explicit offline transitions over existing immutable Stage2/Stage3 evidence."""

import copy

from .contracts import Stage3Error, digest
from .decision import revision_impact
from .intake import admit_intake
from .preparation import closed, file_binding, prepare_ab, sha256, text
from .review import plan_status
from .storage import inspect_package, private_output, safe_path, write_new

KINDS = {"source", "plan", "review", "ab_definition"}
MAX_CHECKPOINT_REVISIONS = 64
ACTIONS = {"start", "attach-plan", "attach-review", "prepare-ab", "revise-source"}


def source_binding(package, delivery, expected_manifest_sha256):
    sha256(expected_manifest_sha256)
    return {
        "package": str(safe_path(package)),
        "delivery": str(safe_path(delivery)),
        "manifest_sha256": expected_manifest_sha256,
    }


def _evaluate(bindings):
    closed(bindings, KINDS, "workflow bindings")
    source = bindings["source"]
    closed(source, {"package", "delivery", "manifest_sha256"}, "source")
    for name in ("package", "delivery"):
        text(source[name], "source " + name)
    sha256(source["manifest_sha256"])
    intake = admit_intake(
        source["package"],
        source["delivery"],
        expected_manifest_sha256=source["manifest_sha256"],
    )
    plan = None
    state = (
        "needs-information"
        if intake["legacy_candidates"] or not intake["questions"]
        else "awaiting-plan"
    )
    next_action = (
        "resolve-stage2-scientific-mapping"
        if state == "needs-information"
        else "supply-saved-plan"
    )
    if bindings["plan"] is not None:
        ref = bindings["plan"]
        closed(ref, {"package", "manifest_sha256"}, "plan binding")
        text(ref["package"], "saved plan package")
        sha256(ref["manifest_sha256"])
        saved = inspect_package(ref["package"], ref["manifest_sha256"])
        request = saved["artifacts"]["request.json"]
        if (
            request.get("admission_scope") != "strict-selected"
            or request.get("intake") != intake
        ):
            raise Stage3Error("saved plan must bind this strict selected intake")
        plan = saved["artifacts"].get("plan.json")
        if plan is None:
            state, next_action = "failed", "inspect-original-planning-failure"
        else:
            state = plan_status(plan, intake, admission_scope="strict-selected")
            next_action = (
                "supply-semantic-review"
                if state == "draft"
                else "resolve-plan-blockers"
            )
    if bindings["review"] is not None:
        if plan is None:
            raise Stage3Error("semantic review requires a saved plan")
        ref = bindings["review"]
        closed(ref, {"path", "sha256"}, "review binding")
        review = file_binding(ref["path"], ref["sha256"])
        state = plan_status(plan, intake, review, admission_scope="strict-selected")
        next_action = (
            "record-version-bound-plan-decision"
            if state == "ready-for-plan-review"
            else "resolve-plan-blockers"
        )
    preparation = None
    if bindings["ab_definition"] is not None:
        ref = bindings["ab_definition"]
        closed(ref, {"path", "sha256"}, "A/B definition binding")
        preparation = prepare_ab(file_binding(ref["path"], ref["sha256"]), intake)
    return (
        intake,
        plan,
        {
            "planning_status": state,
            "next_action": next_action,
            "selected_candidates": intake["selected_candidates"],
            "question_refs": [q["question_ref"] for q in intake["questions"]],
            "evaluation_status": "preparation-only" if preparation else "not-prepared",
            "ab_preparation": preparation,
            "readiness": "implementation-only",
            "human_origin_verification": "native-host-responsibility-unverified",
            "execution_authorized": False,
        },
    )


def _save(
    path, workflow_id, revision, parent, bindings, *, action="start", impact=None
):
    text(workflow_id, "workflow ID")
    if revision > MAX_CHECKPOINT_REVISIONS:
        raise Stage3Error(
            "workflow history limit reached; explicit archival/migration required"
        )
    intake, _, status = _evaluate(bindings)
    checkpoint = {
        "kind": "Stage3WorkflowCheckpoint",
        "schema_version": "1.0.0",
        "workflow_id": workflow_id,
        "revision": revision,
        "action": action,
        "parent": parent,
        "bindings": bindings,
        "intake_sha256": digest(intake),
        "status": status,
        "revision_impact": impact,
        "execution_authorized": False,
    }
    output = private_output(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_new(output, checkpoint)
    return {"checkpoint": checkpoint, "checkpoint_sha256": digest(checkpoint)}


def start_workflow(
    package, delivery, *, expected_source_manifest_sha256, output, workflow_id
):
    """Start only from a strict selected handoff; never synthesize a choice."""
    return _save(
        output,
        workflow_id,
        1,
        None,
        {
            "source": source_binding(
                package, delivery, expected_source_manifest_sha256
            ),
            "plan": None,
            "review": None,
            "ab_definition": None,
        },
    )


def _read_checkpoint(path, expected_checkpoint_sha256):
    checkpoint = file_binding(path, expected_checkpoint_sha256)
    closed(
        checkpoint,
        {
            "kind",
            "schema_version",
            "workflow_id",
            "revision",
            "action",
            "parent",
            "bindings",
            "intake_sha256",
            "status",
            "revision_impact",
            "execution_authorized",
        },
        "workflow checkpoint",
    )
    if (
        checkpoint["kind"] != "Stage3WorkflowCheckpoint"
        or checkpoint["schema_version"] != "1.0.0"
        or checkpoint["execution_authorized"] is not False
        or type(checkpoint["revision"]) is not int
        or checkpoint["revision"] < 1
        or checkpoint["revision"] > MAX_CHECKPOINT_REVISIONS
        or not isinstance(checkpoint["action"], str)
        or checkpoint["action"] not in ACTIONS
    ):
        raise Stage3Error("invalid workflow identity/version/authority")
    text(checkpoint["workflow_id"], "workflow ID")
    closed(checkpoint["bindings"], KINDS, "workflow bindings")
    return checkpoint


def _impact(previous_bindings, current_bindings, evaluate=_evaluate):
    old_intake, old_plan, _ = evaluate(previous_bindings)
    new_intake, _, _ = evaluate(current_bindings)
    if old_plan is not None:
        return revision_impact(old_plan, old_intake, new_intake)
    return {
        "confirmation_invalidated": old_intake != new_intake,
        "execution_authorized": False,
    }


def _transition(checkpoint, previous, evaluate=_evaluate):
    action, bindings = checkpoint["action"], checkpoint["bindings"]
    expected_impact = None
    if previous is None:
        if (
            checkpoint["revision"] != 1
            or action != "start"
            or any(bindings[k] is not None for k in KINDS - {"source"})
        ):
            raise Stage3Error("invalid initial workflow transition")
    else:
        if (
            checkpoint["workflow_id"] != previous["workflow_id"]
            or checkpoint["revision"] != previous["revision"] + 1
        ):
            raise Stage3Error("previous checkpoint identity/version mismatch")
        expected = copy.deepcopy(previous["bindings"])
        if action == "attach-plan":
            expected.update(plan=bindings["plan"], review=None)
            required = "plan"
        elif action == "attach-review":
            expected["review"] = bindings["review"]
            required = "review"
        elif action == "prepare-ab":
            expected["ab_definition"] = bindings["ab_definition"]
            required = "ab_definition"
        elif action == "revise-source":
            expected = {
                "source": bindings["source"],
                "plan": None,
                "review": None,
                "ab_definition": None,
            }
            required = "source"
            expected_impact = _impact(previous["bindings"], bindings, evaluate)
        else:
            raise Stage3Error("invalid noninitial workflow action")
        if bindings != expected or bindings[required] is None:
            raise Stage3Error("workflow action changed unrelated bindings")
    if checkpoint["revision_impact"] != expected_impact:
        raise Stage3Error("workflow revision impact differs from verified transition")


def inspect_workflow(path, *, expected_checkpoint_sha256):
    """Verify bounded complete ancestry and current dependencies, without calls."""
    history, seen = [], set()
    cursor = {"path": str(safe_path(path)), "sha256": expected_checkpoint_sha256}
    while cursor is not None:
        closed(cursor, {"path", "sha256"}, "previous checkpoint binding")
        text(cursor["path"], "previous checkpoint path")
        identity = str(safe_path(cursor["path"]))
        if identity in seen or len(history) >= MAX_CHECKPOINT_REVISIONS:
            raise Stage3Error("workflow history cycle or bounded history limit")
        seen.add(identity)
        row = _read_checkpoint(cursor["path"], cursor["sha256"])
        history.append(row)
        cursor = row["parent"]
    evaluated = {}

    def evaluate(bindings):
        key = digest(bindings)
        if key not in evaluated:
            evaluated[key] = _evaluate(bindings)
        return evaluated[key]

    for index, row in enumerate(history):
        _transition(
            row, history[index + 1] if index + 1 < len(history) else None, evaluate
        )
        intake, _, status = evaluate(row["bindings"])
        if row["intake_sha256"] != digest(intake) or row["status"] != status:
            raise Stage3Error(
                "workflow projection/status differs from admitted dependencies"
            )
    checkpoint = history[0]
    return {
        "checkpoint": checkpoint,
        "checkpoint_sha256": expected_checkpoint_sha256,
        "resume_action": "verified-replay-no-calls",
    }


def advance_workflow(path, *, expected_checkpoint_sha256, action, output, binding):
    """One explicit evidence attachment; previous versions remain immutable."""
    saved = inspect_workflow(
        path, expected_checkpoint_sha256=expected_checkpoint_sha256
    )
    old = saved["checkpoint"]
    bindings = copy.deepcopy(old["bindings"])
    binding = copy.deepcopy(binding)
    impact = None
    if action == "attach-plan":
        bindings["plan"] = binding
        bindings["review"] = None
    elif action == "attach-review":
        bindings["review"] = binding
    elif action == "prepare-ab":
        bindings["ab_definition"] = binding
    elif action == "revise-source":
        new_bindings = {
            "source": binding,
            "plan": None,
            "review": None,
            "ab_definition": None,
        }
        impact = _impact(bindings, new_bindings)
        bindings = new_bindings
    else:
        raise Stage3Error("unsupported offline workflow action")
    # Bound references use absolute paths so resume does not depend on the cwd.
    for key in KINDS - {"source"}:
        ref = bindings[key]
        if ref is not None:
            field = "package" if key == "plan" else "path"
            if not isinstance(ref, dict) or field not in ref:
                raise Stage3Error("invalid workflow artifact binding")
            ref[field] = str(safe_path(ref[field]))
    if action == "revise-source":
        closed(binding, {"package", "delivery", "manifest_sha256"}, "source binding")
        bindings["source"] = source_binding(
            binding["package"], binding["delivery"], binding["manifest_sha256"]
        )
    parent = {"path": str(safe_path(path)), "sha256": expected_checkpoint_sha256}
    return _save(
        output,
        old["workflow_id"],
        old["revision"] + 1,
        parent,
        bindings,
        action=action,
        impact=impact,
    )

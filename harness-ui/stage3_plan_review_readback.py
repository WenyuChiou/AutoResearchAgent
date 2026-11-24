"""Read saved strict-selection planning records for an already authorized view."""

from collections import Counter
from hashlib import sha256 as hash_bytes
from pathlib import Path

from stage2_workflow.interaction import _user_text
from stage3_plan.contracts import Stage3Error, digest
from stage3_plan.preparation import closed, file_binding, sha256, text
from stage3_plan.review import validate_review
from stage3_plan.storage import inspect_package, read_bytes
from stage3_plan.workflow import inspect_workflow


def plan_review_identity(view):
    """Identify the strict saved plan in the Host's authenticated projection."""
    plan, job = view.get("plan"), view.get("job")
    if (
        plan is None
        or view.get("selection_status") != "recorded"
        or job is None
        or job["outcome"] != "saved"
    ):
        return None
    if job["project_ref"] != view["project_ref"]:
        raise Stage3Error("readback job belongs to another project")
    identity = {
        "project_ref": view["project_ref"],
        "input_version": view["input_version"],
        "revision": view["revision"],
        "brief_sha256": view["brief_sha256"],
        "selection_request_sha256": view["selection_request_sha256"],
        "job_request_sha256": job["request_sha256"],
        "source_manifest_sha256": plan["source_manifest_sha256"],
        "plan_manifest_sha256": job["plan_manifest_sha256"],
        "plan_id": plan["plan_id"],
        "plan_version": plan["version"],
        "plan_sha256": digest(plan),
    }
    for name, value in identity.items():
        if name.endswith("_sha256"):
            sha256(value)
    text(identity["project_ref"], "project reference")
    text(identity["plan_id"], "plan ID")
    return identity


def _bound_decision(ref, identity, review_ref, status):
    closed(ref, {"path", "sha256"}, "plan decision reference")
    decision = file_binding(ref["path"], ref["sha256"])
    fields = {
        "kind",
        "schema_version",
        "plan_manifest_sha256",
        "plan_sha256",
        "plan_id",
        "version",
        "review_sha256",
        "native_user_message_sha256",
        "message_index",
        "user_text",
        "decision",
        "plan_status",
        "decision_status",
        "host_verification",
        "identity_authenticated",
        "semantic_authorization_verified",
        "authority_note",
        "execution_authorized",
    }
    closed(decision, fields, "plan decision")
    binding = {
        key: identity[key]
        for key in (
            "plan_manifest_sha256",
            "plan_sha256",
            "plan_id",
            "source_manifest_sha256",
        )
    }
    binding["version"] = identity["plan_version"]
    if (
        decision["kind"] != "Stage3PlanDecision"
        or decision["schema_version"] != "1.0.0"
        or decision["execution_authorized"] is not False
        or decision["review_sha256"] != review_ref["sha256"]
        or any(
            digest(decision[key]) != digest(value)
            for key, value in binding.items()
            if key != "source_manifest_sha256"
        )
    ):
        raise Stage3Error("decision differs from the displayed plan or review")
    choice = decision["decision"]
    if choice not in ("confirm", "revise", "defer") or (
        choice == "confirm" and status != "ready-for-plan-review"
    ):
        raise Stage3Error("decision is inadmissible for this plan")

    archived = Path(ref["path"]).parent
    review_bytes = read_bytes(archived / "semantic-review.json")
    native = read_bytes(archived / "native-user-message.jsonl")
    if (
        hash_bytes(review_bytes).hexdigest() != review_ref["sha256"]
        or hash_bytes(native).hexdigest() != decision["native_user_message_sha256"]
        or _user_text(native, decision["message_index"]) != decision["user_text"]
    ):
        raise Stage3Error("archived decision evidence differs")
    binding.update(
        native_user_message_sha256=decision["native_user_message_sha256"],
        message_index=decision["message_index"],
        user_text=decision["user_text"],
        decision=choice,
    )
    verification = decision["host_verification"]
    verified = False
    decision_status = "decision-recorded-pending-host-verification"
    plan_status = status
    if verification is not None:
        closed(
            verification,
            {"kind", "binding_sha256", "verified", "evidence_ref"},
            "host decision verification",
        )
        if (
            verification["kind"] != "Stage3HostDecisionVerification"
            or type(verification["verified"]) is not bool
            or verification["binding_sha256"] != digest(binding)
        ):
            raise Stage3Error(
                "host decision verification differs from the saved record"
            )
        text(verification["evidence_ref"], "host evidence reference")
        verified = verification["verified"]
        decision_status = "host-verified" if verified else "host-rejected"
        if verified:
            plan_status = {
                "confirm": "plan-confirmed",
                "revise": "needs-revision",
                "defer": "draft",
            }[choice]
    if (
        decision["decision_status"] != decision_status
        or decision["plan_status"] != plan_status
        or decision["identity_authenticated"] is not verified
        or decision["semantic_authorization_verified"] is not verified
    ):
        raise Stage3Error("saved decision status differs from its evidence")
    return {
        "sha256": ref["sha256"],
        "decision": choice,
        "status": decision_status,
        "plan_status": plan_status,
        "identity_authenticated": verified,
    }


def read_plan_review(view, *, trusted_binding=None):
    """Project only pinned records. Paths and pins come from a Host-owned index.

    This function is for use after authorization, under the normal project's
    read lock. Never derive a binding from browser parameters or from a scan of
    private directories. A historical binding must accompany the verified view
    of that historical plan, never stand in for the current view.
    """
    identity = plan_review_identity(view)
    result = {
        "identity": identity,
        "planning_status": (view.get("job") or {}).get("planning_status"),
        "readback_status": "unlinked" if identity else "outside-saved-strict-plan",
        "checkpoint_sha256": None,
        "next_action": None,
        "review": None,
        "decision": None,
        "execution_authorized": False,
    }
    if trusted_binding is None:
        return result
    closed(trusted_binding, {"identity", "checkpoint", "decision"}, "readback binding")
    if identity is None or digest(trusted_binding["identity"]) != digest(identity):
        raise Stage3Error("readback binding differs from the displayed project or plan")
    checkpoint_ref = trusted_binding["checkpoint"]
    closed(checkpoint_ref, {"path", "sha256"}, "readback checkpoint reference")
    checkpoint = inspect_workflow(
        checkpoint_ref["path"], expected_checkpoint_sha256=checkpoint_ref["sha256"]
    )["checkpoint"]
    refs = checkpoint["bindings"]
    if (
        refs["plan"] is None
        or refs["plan"]["manifest_sha256"] != identity["plan_manifest_sha256"]
        or refs["source"]["manifest_sha256"] != identity["source_manifest_sha256"]
    ):
        raise Stage3Error("workflow checkpoint does not bind the displayed plan")
    artifacts = inspect_package(
        refs["plan"]["package"], identity["plan_manifest_sha256"]
    )["artifacts"]
    saved_plan = artifacts.get("plan.json")
    if saved_plan is None or digest(saved_plan) != identity["plan_sha256"]:
        raise Stage3Error("displayed plan bytes differ from the sealed plan")
    status = checkpoint["status"]["planning_status"]
    result.update(
        planning_status=status,
        readback_status="bound",
        checkpoint_sha256=checkpoint_ref["sha256"],
        next_action=checkpoint["status"]["next_action"],
    )
    review_ref = refs["review"]
    decision_ref = trusted_binding["decision"]
    if review_ref is None:
        if decision_ref is not None:
            raise Stage3Error("a decision read requires a bound semantic review")
        return result
    review = validate_review(
        saved_plan,
        artifacts["request.json"]["intake"],
        file_binding(review_ref["path"], review_ref["sha256"]),
    )
    result["review"] = {
        "sha256": review_ref["sha256"],
        "reviewer_kind": review["reviewer"]["kind"],
        "identity_authenticated": review["reviewer"]["identity_authenticated"],
        "finding_counts": dict(Counter(f["status"] for f in review["findings"])),
    }
    if decision_ref is not None:
        decision = _bound_decision(decision_ref, identity, review_ref, status)
        result.update(
            decision=decision,
            planning_status=decision["plan_status"],
            next_action=None,
        )
    return result

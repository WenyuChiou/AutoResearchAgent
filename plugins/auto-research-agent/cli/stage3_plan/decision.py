"""Version-bound plan decisions retain the actual user text, never permission."""

import hashlib

from stage2_workflow.interaction import _user_text

from .contracts import Stage3Error, digest
from .review import plan_status, validate_review
from .storage import inspect_package, private_output, read_bytes, read_json, write_new


def record_plan_decision(
    package_dir,
    *,
    expected_manifest_sha256,
    review_path,
    expected_review_sha256,
    native_message,
    message_index,
    user_text,
    decision,
    output_dir,
    planning_package,
    delivery_dir,
    expected_source_manifest_sha256,
    verify_decision=None,
    scientific_mapping=None,
    expected_mapping_manifest_sha256=None,
    verify_mapping_choice=None,
):
    saved = inspect_package(package_dir, expected_manifest_sha256)
    plan = saved["artifacts"].get("plan.json")
    if plan is None:
        raise Stage3Error("failed/incomplete generation has no confirmable plan")
    intake = saved["artifacts"]["request.json"]["intake"]
    from .intake import admit_intake

    current_intake = admit_intake(
        planning_package,
        delivery_dir,
        expected_manifest_sha256=expected_source_manifest_sha256,
        scientific_mapping=scientific_mapping,
        expected_mapping_manifest_sha256=expected_mapping_manifest_sha256,
        verify_mapping_choice=verify_mapping_choice,
    )
    if current_intake != intake:
        raise Stage3Error(
            "selection/source conditions changed; current plan must be revised"
        )
    review_bytes = read_bytes(review_path)
    if hashlib.sha256(review_bytes).hexdigest() != expected_review_sha256:
        raise Stage3Error("review external hash mismatch")
    review = read_json(review_path)
    validate_review(plan, intake, review)
    if decision not in {"confirm", "revise", "defer"}:
        raise Stage3Error("unsupported plan decision")
    scope = saved["artifacts"]["request.json"]["admission_scope"]
    current_status = plan_status(plan, intake, review, admission_scope=scope)
    if decision == "confirm" and current_status != "ready-for-plan-review":
        raise Stage3Error("unresolved semantic/core blockers prevent plan confirmation")
    raw = read_bytes(native_message)
    if (
        not isinstance(user_text, str)
        or not user_text.strip()
        or _user_text(raw, message_index) != user_text
    ):
        raise Stage3Error("decision must retain exact actual native user message")
    binding = {
        "plan_manifest_sha256": expected_manifest_sha256,
        "plan_sha256": digest(plan),
        "plan_id": plan["plan_id"],
        "version": plan["version"],
        "source_manifest_sha256": expected_source_manifest_sha256,
        "native_user_message_sha256": hashlib.sha256(raw).hexdigest(),
        "user_text": user_text,
        "decision": decision,
        "message_index": message_index,
    }
    verification = None
    if verify_decision is not None:
        if scope != "strict-selected" or not callable(verify_decision):
            raise Stage3Error(
                "only a strict admitted plan can use a trusted host verifier"
            )
        verification = verify_decision(dict(binding))
        if (
            not isinstance(verification, dict)
            or set(verification)
            != {"kind", "binding_sha256", "verified", "evidence_ref"}
            or verification["kind"] != "Stage3HostDecisionVerification"
            or verification["binding_sha256"] != digest(binding)
            or type(verification["verified"]) is not bool
            or not isinstance(verification["evidence_ref"], str)
            or not verification["evidence_ref"].strip()
        ):
            raise Stage3Error(
                "host verification must bind exact identity, intent and displayed version"
            )
    verified = verification is not None and verification["verified"]
    record = {
        "kind": "Stage3PlanDecision",
        "schema_version": "1.0.0",
        "plan_manifest_sha256": expected_manifest_sha256,
        "plan_sha256": digest(plan),
        "plan_id": plan["plan_id"],
        "version": plan["version"],
        "review_sha256": expected_review_sha256,
        "native_user_message_sha256": hashlib.sha256(raw).hexdigest(),
        "message_index": message_index,
        "user_text": user_text,
        "decision": decision,
        "plan_status": current_status
        if not verified
        else "plan-confirmed"
        if decision == "confirm"
        else "needs-revision"
        if decision == "revise"
        else "draft",
        "decision_status": "host-verified"
        if verified
        else "host-rejected"
        if verification is not None
        else "decision-recorded-pending-host-verification",
        "host_verification": verification,
        "identity_authenticated": bool(verified),
        "semantic_authorization_verified": bool(verified),
        "authority_note": "Only the trusted native-host callback can attest actual human origin, intended decision and displayed version. CLI text records remain pending; no research permission is granted.",
        "execution_authorized": False,
    }
    output = private_output(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "decision.json", record)
    write_new(output / "native-user-message.jsonl", raw, raw=True)
    write_new(output / "semantic-review.json", review_bytes, raw=True)
    return record


def revision_impact(plan, old_intake, new_intake):
    """Return affected scopes without generating, rewriting or clearing history."""
    old = {q["question_ref"]: q for q in old_intake["questions"]}
    new = {q["question_ref"]: q for q in new_intake["questions"]}
    changed = {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}
    old_resources = {row["resource_id"]: row for row in old_intake["resources"]}
    new_resources = {row["resource_id"]: row for row in new_intake["resources"]}
    resources = {
        key
        for key in old_resources.keys() | new_resources.keys()
        if old_resources.get(key) != new_resources.get(key)
    }
    old_arguments = {
        (row["candidate_id"], row["candidate_version"]): row["argument"]
        for row in old_intake["scientific_arguments"]
    }
    new_arguments = {
        (row["candidate_id"], row["candidate_version"]): row["argument"]
        for row in new_intake["scientific_arguments"]
    }
    changed_arguments = {
        key
        for key in old_arguments.keys() | new_arguments.keys()
        if old_arguments.get(key) != new_arguments.get(key)
    }
    for question in plan["questions"]:
        if (
            question["candidate_id"],
            question["candidate_version"],
        ) in changed_arguments:
            changed.add(question["question_ref"])
    if (
        old_intake.get("evidence") != new_intake.get("evidence")
        or old_intake.get("sources") != new_intake.get("sources")
        or old_intake.get("prior_work_reviews") != new_intake.get("prior_work_reviews")
    ):
        # Source/gap semantics cannot be re-established by a hash comparison.
        changed.update(old.keys() | new.keys())
    if any(
        old_intake.get(field) != new_intake.get(field)
        for field in (
            "selection_conditions",
            "brief",
            "resource_constraints",
            "comparison",
            "unresolved",
        )
    ):
        changed.update(old.keys() | new.keys())
    for question in plan["question_plans"]:
        if any(row["resource_id"] in resources for row in question["resource_uses"]):
            changed.add(question["question_ref"])
    affected_designs = set()
    previous = None
    while previous != len(changed):
        previous = len(changed)
        for row in plan["designs"]:
            if changed.intersection(row["question_refs"]):
                affected_designs.add(row["design_id"])
                changed.update(row["question_refs"])
    return {
        "affected_questions": sorted(changed),
        "affected_designs": sorted(affected_designs),
        "changed_resources": sorted(resources),
        "affected_analyses": sorted(
            row["analysis_id"]
            for row in plan["analyses"]
            if changed.intersection(row["question_refs"])
        ),
        "affected_results": sorted(
            row["result_id"]
            for row in plan["results"]
            if changed.intersection(row["question_refs"])
        ),
        "return_to_stage2": old_intake["selected_candidates"]
        != new_intake["selected_candidates"]
        or old != new
        or bool(changed_arguments),
        "confirmation_invalidated": digest(old_intake) != digest(new_intake),
        "unaffected_evidence_retained": True,
        "execution_authorized": False,
    }

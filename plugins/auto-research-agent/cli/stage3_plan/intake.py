"""Admit only the existing, externally pinned selected planning handoff."""

import copy

from stage2_workflow.planning_handoff import inspect_planning_handoff

from .contracts import Stage3Error, digest


def project_intake(handoff, manifest_sha256):
    """Project verified input; callers must not treat this pure helper as admission."""
    if handoff.get("execution_authorized") is not False:
        raise Stage3Error("planning input must retain execution_authorized=false")
    selected = handoff["decision"]
    if selected["kind"] != "select" or not selected["selected"]:
        raise Stage3Error("a current human selection is required")
    candidates = {
        (row["candidate"]["candidate_id"], row["candidate"]["version"]): row[
            "candidate"
        ]
        for row in handoff["selected_options"]
    }
    questions, arguments, legacy = [], [], []
    for ref in selected["selected"]:
        key = (ref["candidate_id"], ref["candidate_version"])
        if key not in candidates:
            raise Stage3Error("selected candidate version absent from verified options")
        argument = candidates[key].get("scientific_argument")
        identity = dict(candidate_id=key[0], candidate_version=key[1])
        if argument is None:
            legacy.append(
                {
                    **identity,
                    "reason": "legacy-unstructured; a versioned Stage2 mapping and human confirmation are required",
                }
            )
            continue
        arguments.append({**identity, "argument": copy.deepcopy(argument)})
        for question in argument["questions"]:
            questions.append(
                {
                    **identity,
                    "question_ref": f"{key[0]}@{key[1]}/{question['question_id']}",
                    **{
                        field: copy.deepcopy(question[field])
                        for field in (
                            "question_id",
                            "text",
                            "priority",
                            "gap_ids",
                            "intended_claim",
                        )
                    },
                }
            )
    packet = handoff["evaluation_packet"]
    evidence_ids = set()

    def collect_evidence(value):
        if isinstance(value, dict):
            evidence_ids.update(value.get("evidence_ids", []))
            for item in value.values():
                collect_evidence(item)
        elif isinstance(value, list):
            for item in value:
                collect_evidence(item)

    collect_evidence(arguments)
    collect_evidence(handoff["selected_options"])
    collect_evidence(handoff["selected_direction_resources"])
    collect_evidence(handoff["selected_prior_work_reviews"])
    evidence = [row for row in packet["evidence"] if row["evidence_id"] in evidence_ids]
    source_ids = {row["source_id"] for row in evidence}
    intake = {
        "source_manifest_sha256": manifest_sha256,
        "selected_candidates": copy.deepcopy(selected["selected"]),
        "questions": questions,
        "scientific_arguments": arguments,
        "resources": copy.deepcopy(handoff["selected_direction_resources"]["rows"]),
        "legacy_candidates": legacy,
        "brief": copy.deepcopy(packet["brief"]),
        "resource_constraints": copy.deepcopy(packet["resources"]),
        "comparison": packet["comparison"],
        "evidence": copy.deepcopy(evidence),
        "sources": copy.deepcopy(
            [row for row in packet["sources"] if row["source_id"] in source_ids]
        ),
        "prior_work_reviews": copy.deepcopy(handoff["selected_prior_work_reviews"]),
        "selection_conditions": copy.deepcopy(selected.get("conditions", [])),
        "unresolved": copy.deepcopy(selected.get("unresolved", [])),
        "execution_authorized": False,
    }
    if "input_origin" in handoff:
        intake["input_origin"] = copy.deepcopy(handoff["input_origin"])
    if "reviewer_planning_context" in handoff:
        context = handoff["reviewer_planning_context"]
        if (
            not isinstance(context, dict)
            or context.get("kind") != "Stage2ReviewerPlanningContext"
            or context.get("schema_version") != "1.0.0"
            or context.get("source_kind") != "stage2-independent-review"
            or context.get("review_view_version") != "1.3.0"
        ):
            raise Stage3Error("unsupported reviewer planning context")
        intake["reviewer_planning_context"] = copy.deepcopy(context)
    return intake


def admit_intake(
    package_dir,
    delivery_dir,
    *,
    expected_manifest_sha256,
    scientific_mapping=None,
    expected_mapping_manifest_sha256=None,
    verify_mapping_choice=None,
):
    """No manual ZIP, recommendation, UI draft or self-computed trust substitute."""
    verified = inspect_planning_handoff(
        package_dir, delivery_dir, expected_manifest_sha256=expected_manifest_sha256
    )
    intake = project_intake(verified["handoff"], expected_manifest_sha256)
    if scientific_mapping is None:
        if (
            expected_mapping_manifest_sha256 is not None
            or verify_mapping_choice is not None
        ):
            raise Stage3Error("mapping configuration requires its explicit package")
        return intake
    from .legacy_mapping import inspect_legacy_mapping

    mapped = inspect_legacy_mapping(
        scientific_mapping, expected_manifest_sha256=expected_mapping_manifest_sha256
    )

    # Both inspectors validate physical source bytes. Only their storage paths
    # may differ; every scientific field and source identity/hash must match.
    def logical_packet(packet):
        value = copy.deepcopy(packet)
        for row in value["sources"]:
            del row["path"]
        return value

    if logical_packet(mapped["packet"]) != logical_packet(
        verified["handoff"]["evaluation_packet"]
    ):
        raise Stage3Error("legacy mapping is not the current strict delivery packet")
    selected = {
        (r["candidate_id"], r["candidate_version"])
        for r in intake["selected_candidates"]
    }
    entries = {
        (r["candidate_id"], r["candidate_version"]): r
        for r in mapped["mapping"]["candidates"]
    }
    if not selected or not selected.issubset(entries):
        raise Stage3Error(
            "mapping does not contain current selected candidate versions"
        )
    binding = dict(
        planning_manifest_sha256=expected_manifest_sha256,
        mapping_manifest_sha256=expected_mapping_manifest_sha256,
        selected_candidates=intake["selected_candidates"],
        decision=verified["handoff"]["decision"],
    )
    if not callable(verify_mapping_choice):
        raise Stage3Error(
            "trusted host must verify human saw and selected this mapping/version"
        )
    result = verify_mapping_choice(copy.deepcopy(binding))
    if (
        not isinstance(result, dict)
        or set(result) != {"kind", "binding_sha256", "verified", "evidence_ref"}
        or result["kind"] != "Stage2MappedSelectionVerification"
        or result["binding_sha256"] != digest(binding)
        or result["verified"] is not True
        or not isinstance(result["evidence_ref"], str)
        or not result["evidence_ref"].strip()
    ):
        raise Stage3Error("mapped selection host verification rejected or mismatched")
    if not intake["legacy_candidates"]:
        raise Stage3Error("an already structured packet must not use a legacy mapping")
    intake["scientific_arguments"] = []
    intake["questions"] = []
    intake["resources"] = []
    for key in sorted(selected):
        row = entries[key]
        intake["scientific_arguments"].append(
            dict(
                candidate_id=key[0],
                candidate_version=key[1],
                argument=copy.deepcopy(row["scientific_argument"]),
                original_approach=row["original_approach"],
                limitations=copy.deepcopy(row["limitations"]),
            )
        )
        for question in row["scientific_argument"]["questions"]:
            intake["questions"].append(
                dict(
                    candidate_id=key[0],
                    candidate_version=key[1],
                    question_ref=f"{key[0]}@{key[1]}/{question['question_id']}",
                    **{
                        field: copy.deepcopy(question[field])
                        for field in (
                            "question_id",
                            "text",
                            "priority",
                            "gap_ids",
                            "intended_claim",
                        )
                    },
                )
            )
        intake["resources"].extend(copy.deepcopy(row["resources"]))
    intake["legacy_candidates"] = []
    intake["legacy_mapping"] = dict(
        origin="legacy-manual-v1",
        mapping_version=mapped["mapping"]["mapping_version"],
        manifest_sha256=expected_mapping_manifest_sha256,
        host_selection_verification=result,
        packet_unresolved=copy.deepcopy(mapped["mapping"]["unresolved"]),
    )
    return intake

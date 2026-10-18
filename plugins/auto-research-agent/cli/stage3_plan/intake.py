"""Admit only the existing, externally pinned selected planning handoff."""

import copy

from stage2_workflow.planning_handoff import inspect_planning_handoff

from .contracts import Stage3Error


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
    return {
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


def admit_intake(package_dir, delivery_dir, *, expected_manifest_sha256):
    """No manual ZIP, recommendation, UI draft or self-computed trust substitute."""
    verified = inspect_planning_handoff(
        package_dir, delivery_dir, expected_manifest_sha256=expected_manifest_sha256
    )
    return project_intake(verified["handoff"], expected_manifest_sha256)

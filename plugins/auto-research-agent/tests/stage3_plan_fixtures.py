"""Synthetic, domain-generic fixtures for Stage 3 contract tests."""

import copy


TOPICS = {
    "numeric": {
        "question": "How does the measured response vary across recorded conditions?",
        "design": "Collect repeated numeric measurements under documented conditions.",
        "analysis": "Estimate the response pattern with uncertainty intervals.",
    },
    "observational": {
        "question": "Which observed contexts co-occur with the recorded outcome?",
        "design": "Define an observational sample and record relevant contexts.",
        "analysis": "Describe adjusted associations and residual uncertainty.",
    },
    "qualitative": {
        "question": "How do participants explain variation in the focal process?",
        "design": "Collect purposive interviews and preserve a reflexive audit trail.",
        "analysis": "Develop and challenge themes using contrasting accounts.",
    },
    "theory": {
        "question": "Which propositions follow from the stated assumptions?",
        "design": "Enumerate assumptions and derive propositions by explicit argument.",
        "analysis": "Check derivations for consistency and counterexamples.",
    },
}


def make_plan(topic="numeric", question_count=1, *, shared_path=False):
    details = TOPICS[topic]
    candidate_id = f"candidate-{topic}"
    questions = []
    question_plans = []
    for index in range(1, question_count + 1):
        question_id = f"q{index}"
        question_ref = f"{candidate_id}@1/{question_id}"
        questions.append(
            {
                "question_ref": question_ref,
                "candidate_id": candidate_id,
                "candidate_version": 1,
                "question_id": question_id,
                "text": f"{details['question']} Part {index}",
                "priority": "core" if index == 1 else "secondary",
                "gap_ids": [f"gap-{index}"],
                "intended_claim": f"A bounded answer to question {index}.",
            }
        )

    all_refs = [row["question_ref"] for row in questions]
    designs = []
    analyses = []
    results = []
    for index, question in enumerate(questions, start=1):
        suffix = "shared" if shared_path else str(index)
        design_id = f"design-{suffix}"
        analysis_id = f"analysis-{suffix}"
        result_id = f"result-{suffix}"
        question_plans.append(
            {
                "question_ref": question["question_ref"],
                "evidence_needed": "A traceable body of relevant evidence.",
                "measurement": "Use a method suited to the stated question.",
                "claim_boundary": "Claims remain within the observed or derived evidence.",
                "resource_uses": [
                    {
                        "resource_id": "resource-1",
                        "purpose": "Provide the primary material.",
                        "fit_rationale": "The source is explicitly bound to this question.",
                        "status": "available",
                    }
                ],
                "design_ids": [design_id],
                "analysis_ids": [analysis_id],
                "result_ids": [result_id],
                "blockers": [],
                "minimum_deliverable": "A bounded answer with uncertainty stated.",
            }
        )
        if shared_path and index > 1:
            continue
        path_refs = all_refs if shared_path else [question["question_ref"]]
        designs.append(
            {
                "design_id": design_id,
                "question_refs": path_refs,
                "family": f"{topic} inquiry",
                "procedure": details["design"],
                "comparisons": {
                    "status": "not-applicable" if topic == "theory" else "applicable",
                    "description": "Contrast relevant cases or propositions.",
                    "reason": "Formal comparison is not required for this derivation."
                    if topic == "theory"
                    else "",
                },
                "credibility_checks": ["Inspect evidence coverage."],
                "failure_conditions": ["Required evidence remains unavailable."],
                "stop_conditions": ["The bounded evidence set is exhausted."],
            }
        )
        analyses.append(
            {
                "analysis_id": analysis_id,
                "question_refs": path_refs,
                "design_ids": [design_id],
                "method": details["analysis"],
                "criteria": ["Apply the stated method consistently."],
                "uncertainty": "Record unresolved assumptions and evidence limits.",
                "limitations": "The bounded materials limit generalization.",
            }
        )
        results.append(
            {
                "result_id": result_id,
                "question_refs": path_refs,
                "analysis_ids": [analysis_id],
                "artifact": "A future result artifact.",
                "status": "not-run",
                "observed_value": None,
                "interpretation": {
                    "supports": "Evidence would support the bounded claim.",
                    "contradicts": "Evidence would contradict the bounded claim.",
                    "inconclusive": "Evidence would leave the claim unresolved.",
                },
            }
        )

    return {
        "kind": "Stage3ResearchPlan",
        "schema_version": "1.0.0",
        "plan_id": f"plan-{topic}",
        "version": 1,
        "source_manifest_sha256": "a" * 64,
        "selected_candidates": [{"candidate_id": candidate_id, "candidate_version": 1}],
        "questions": questions,
        "question_plans": question_plans,
        "designs": designs,
        "analyses": analyses,
        "results": results,
        "resources": [
            {
                "resource_id": "resource-1",
                "origin": "stage2",
                "availability": "available",
                "access_conditions": "Available for the bounded planning task.",
                "fitness": "Directly relevant to the selected questions.",
                "scale_basis": "Scale follows the evidence-producing method.",
                "minimum": "Enough material to attempt the minimum deliverable.",
                "standard": "Enough material for the full bounded design.",
                "uncertainties": [],
            }
        ],
        "milestones": [
            {
                "milestone_id": "m1",
                "description": "Prepare the evidence and design.",
                "depends_on": [],
                "design_ids": sorted({row["design_id"] for row in designs}),
                "duration_basis": "Duration depends on evidence access and method scope.",
                "deliverable": "A reviewable design package.",
            },
            {
                "milestone_id": "m2",
                "description": "Produce the bounded analysis artifacts.",
                "depends_on": ["m1"],
                "design_ids": [],
                "duration_basis": "Duration depends on the selected analysis method.",
                "deliverable": "A reviewable result package.",
            },
        ],
        "unknowns": [],
        "execution_authorized": False,
    }


def make_intake(plan):
    argument_resource_refs = []
    for question in plan["questions"]:
        argument_resource_refs.append(
            {
                "resource_id": "resource-1",
                "question_ids": [question["question_id"]],
                "purpose": "Provide the primary material.",
                "fit_status": "supported",
                "evidence_ids": [],
            }
        )
    candidate = plan["selected_candidates"][0]
    return {
        "source_manifest_sha256": plan["source_manifest_sha256"],
        "selected_candidates": copy.deepcopy(plan["selected_candidates"]),
        "questions": copy.deepcopy(plan["questions"]),
        "scientific_arguments": [
            {
                **candidate,
                "argument": {"resource_refs": argument_resource_refs},
            }
        ],
        "resources": [
            {
                **candidate,
                "resource_id": "resource-1",
                "name": "Synthetic planning material",
                "status": "available",
            }
        ],
        "legacy_candidates": [],
    }

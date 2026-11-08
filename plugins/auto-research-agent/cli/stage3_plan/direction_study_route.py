"""Derive the public plan method from a complete typed prospective study route."""

from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from .contracts import Stage3Error, canonical_bytes
from .storage import decode_json, read_bytes

PROFILE = "source-study-v1"
SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "schemas/stage3-structured-direction-plan.v1.schema.json"
)
PHASES = (
    ("baseline", "Step 1: Establish the reference"),
    ("prototype", "Step 2: Build the proposed method"),
    ("holdout", "Step 3: Test on independent evidence"),
    ("continuation", "Step 4: Decide the qualified continuation"),
)
PHASE_FIELDS = (
    ("inputs", "Inputs"),
    ("procedure", "Procedure"),
    ("output", "Output"),
    ("decision", "Decision"),
    ("if_blocked", "If blocked"),
    ("timebox", "Timebox"),
)
RESPONSE_FIELDS = (
    ("acquire", "Acquire the evidence"),
    ("pair", "Pair observations"),
    ("identify", "Define the supported contrast"),
    ("train_and_lock", "Develop and freeze"),
    ("predict_before_reveal", "Predict before revealing targets"),
    ("reveal_and_verify", "Reveal and independently verify"),
    ("qualified_scope", "Limit the qualified scope"),
    ("if_blocked", "Stop or narrow the claim"),
)

GUIDANCE = (
    "Return the supplied structured-study schema. Keep the user's original question "
    "as the main study, with a feasible first comparison and a conditional extension. "
    "For each question write four ordered study_route phases: baseline, prototype, "
    "holdout and continuation. Give every phase its concrete inputs, procedure, "
    "output, decision, blocked branch and timebox. Name each preceding output used "
    "by the next phase. The public method will be derived from these fields; there "
    "is no additional method field or unspecified external protocol to refer to. "
    "Use visible Step 1-4 labels when referring to another phase. "
    "First inspect the bound material inventory and its exact scope, units, versions "
    "and limits. Distinguish present values from a source listing or an unverified "
    "URL. Existing development pilots are already observed, never new holdouts. "
    "Do not assume an unprovided collaborator, specialist or commercial license. "
    "Make the minimum study use supported available inputs; where indispensable "
    "access is unknown, give the specific acquisition check and explain which "
    "original claim cannot yet be answered. A paperwork checklist alone is not a "
    "research result. Make the same outcomes and units comparable across the "
    "transparent reference and proposed method. State the actual fit, calculation "
    "or comparison rule, allowed input and checked output. "
    "Reserve independent groups, periods or other suitable verification evidence "
    "before tuning; lock preprocessing, methods, prompts, scores and decision rules "
    "before targets are revealed. Specify a reproducible small first trial, retain "
    "invalid outputs and failures, and allow the proposed method to lose. "
    "For any price, policy, dose or intervention response claim, use matched-response "
    "in response_validation. Name a plausible lawful source or measurement route; "
    "state exposure/outcome keys, units, windows, source-specific contrast, estimand, "
    "confounds and robustness check. Show how both frozen methods predict the same "
    "held-out keys from permitted predictors without labels or aggregates containing "
    "them. An independent verifier reveals targets only after predictions are saved. "
    "State how unseen groups and revised methods obtain independent evidence. "
    "Matching, arithmetic, simulated shocks or correlation alone do not identify "
    "causal responses. Continue to a feedback or dynamic mechanism only within "
    "independently qualified units, exposures, states and horizons; otherwise retain "
    "the useful limited comparison and hold the unanswered response claim. For "
    "non-response questions use not-applicable and explain the appropriate check. "
    "Keep overview concise, then give operational details once in the route. "
    "All procedures, thresholds, resources and results remain proposed unless "
    "explicitly supported by admitted evidence.\n"
)


def project_study_route(value):
    """Validate raw structured fields and preserve the existing public plan shape."""
    schema = decode_json(read_bytes(SCHEMA))
    if not Draft202012Validator(schema).is_valid(value):
        raise Stage3Error("structured direction planning response schema differs")
    result = deepcopy(value)
    result["kind"] = "Stage3DirectionPlanningResult"
    for row in result["question_plans"]:
        route = row.pop("study_route")
        response = row.pop("response_validation")
        sections = []
        for phase, heading in PHASES:
            item = route[phase]
            sections.append(
                f"{heading} — {item['title']}\n"
                + "\n".join(f"{label}: {item[key]}" for key, label in PHASE_FIELDS)
            )
            if phase == "holdout":
                checks = [f"Why this check applies: {response['reason']}"]
                if response["kind"] == "matched-response":
                    checks += [
                        f"{i}. {label}: {response[key]}"
                        for i, (key, label) in enumerate(RESPONSE_FIELDS, 1)
                    ]
                sections.append("Response validation\n" + "\n".join(checks))
        row["method"] = "\n\n".join(sections)
    # Stable key order keeps shared-context prompts identical after disk replay.
    return decode_json(canonical_bytes(result))

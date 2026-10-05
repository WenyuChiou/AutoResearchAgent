"""Opt-in evaluator framing; never changes the frozen scientific rubric."""

import hashlib
from pathlib import Path

from stage2_common import Stage2Error

VERSION = "3.1.0"
TARGET_PREFIX = (
    "Assessment target: the submitted Stage 2 package text for the specified criterion. "
    "External facts are verification evidence, not missing work supplied by the subject. "
    "Score what the submitted content actually delivers; recognizing a missing comparison, "
    "boundary or next step does not itself supply it. Do not score the quality of your own "
    "critique. Apply only this criterion's anchors, not a requirement from another criterion. "
    "Evaluate the version identified in the submitted text; later checks cannot approve an earlier version. "
    "Correctly supported infeasibility or zero recommendations can score well, with the criterion's required explanation.\n"
)


def target_policy_binding(*, version=VERSION):
    """Return actual policy bytes for a caller's pre-call configuration freeze."""
    if version != VERSION:
        raise Stage2Error("assessment-target-policy-version")
    return {
        "kind": "Stage2AssessmentTargetPolicy",
        "schema_version": VERSION,
        "prompt_sha256": hashlib.sha256(TARGET_PREFIX.encode("utf-8")).hexdigest(),
        "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def validate_target_policy_binding(binding):
    """Reject stale or rehashed caller claims; no model or tool is dispatched."""
    if not isinstance(binding, dict) or binding != target_policy_binding():
        raise Stage2Error("assessment-target-policy-binding")
    return binding


def apply_target_policy(prompt, *, version=VERSION):
    """Frame a supplied prompt explicitly without adding evidence or scores."""
    target_policy_binding(version=version)
    if not isinstance(prompt, str) or not prompt.strip():
        raise Stage2Error("assessment-target-policy-prompt")
    return TARGET_PREFIX + prompt


def prepare_targeted_quality_batch(role, cases, rubric, *, version=VERSION):
    """Prepare an opt-in blinded unit; legacy producers and replay stay intact."""
    binding = target_policy_binding(version=version)
    if role not in ("R1", "R2"):
        raise Stage2Error("assessment-target-policy-quality-role")
    from .rubric_quality_v3 import prepare_quality_batch

    prepared = prepare_quality_batch(role, cases, rubric)
    return {
        **prepared,
        "prompt": apply_target_policy(prepared["prompt"], version=version),
        "assessment_target_policy": binding,
    }

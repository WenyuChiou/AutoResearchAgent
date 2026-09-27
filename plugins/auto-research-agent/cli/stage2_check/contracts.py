"""Local Stage 2 check schema and semantic validation."""

from functools import lru_cache
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from stage2_common import Stage2Error, validate_evidence_refs


AXES = ("opportunity", "value", "answerability", "materials", "execution")


def decode_json(data, label):
    """Decode strict JSON, rejecting duplicate keys and non-finite numbers."""

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise Stage2Error(f"duplicate-json-key: {label}: {key}")
            value[key] = item
        return value

    def invalid(value):
        raise Stage2Error(f"nonfinite-json: {label}: {value}")

    try:
        return json.loads(data, object_pairs_hook=unique, parse_constant=invalid)
    except (ValueError, UnicodeError) as error:
        if isinstance(error, Stage2Error):
            raise
        raise Stage2Error(f"invalid-json: {label}: {error}") from error


@lru_cache(maxsize=1)
def _validator():
    schema_path = (
        Path(__file__).resolve().parents[2] / "schemas/stage2-check.v1.schema.json"
    )
    schema = decode_json(schema_path.read_bytes(), str(schema_path))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_assessment(assessment, packet, latest_versions):
    """Validate shape, packet binding, evidence, and deterministic gates.

    The external assessor supplies scientific judgments. These checks establish
    only that the record is source-bound and internally eligible for its stated
    disposition.
    """

    errors = list(_validator().iter_errors(assessment))
    if errors:
        error = errors[0]
        path = "/".join(str(part) for part in error.absolute_path)
        raise Stage2Error(f"schema:Stage2Check/{path}: {error.message}")

    candidate_id = assessment["candidate_id"]
    current = latest_versions.get(candidate_id)
    if current is None:
        raise Stage2Error(f"unknown-candidate: {candidate_id}")
    if assessment["candidate_version"] != current["version"]:
        raise Stage2Error(
            "stale-candidate-version: "
            f"{candidate_id} expected {current['version']}, "
            f"got {assessment['candidate_version']}"
        )

    for axis in AXES:
        finding = assessment["checks"][axis]
        validate_evidence_refs(finding["evidence_ids"], packet)
        if finding["status"] == "assessed" and not finding["evidence_ids"]:
            raise Stage2Error(f"assessed-evidence-required: {axis}")
        if finding["status"] == "unknown" and not finding["next_check"]:
            raise Stage2Error(f"unknown-next-check-required: {axis}")

    if assessment["scope_change_requested"] and not assessment["next_step"]:
        raise Stage2Error("scope-change-next-step-required")

    disposition = assessment["disposition"]
    checks = assessment["checks"].values()
    if disposition == "recommend":
        if assessment["scope_change_requested"]:
            raise Stage2Error("recommendation-blocked: scope-change-requested")
        if any(finding["blocking"] for finding in checks):
            raise Stage2Error("recommendation-blocked: blocking-finding")
        if any(finding["status"] == "unknown" for finding in checks):
            raise Stage2Error("recommendation-blocked: unknown-finding")
        applicable = [
            finding for finding in checks if finding["status"] != "not-applicable"
        ]
        if not applicable or any(
            finding["status"] != "assessed" or finding["score"] != 2
            for finding in applicable
        ):
            raise Stage2Error("recommendation-not-sufficient-for-design")
    elif disposition in {"revise", "park"} and not assessment["next_step"]:
        raise Stage2Error(f"{disposition}-next-step-required")
    elif disposition == "reject" and not any(
        finding["status"] == "assessed"
        and finding["score"] == 0
        and finding["evidence_ids"]
        for finding in checks
    ):
        raise Stage2Error("reject-assessed-negative-evidence-required")

    revised = assessment.get("revised_candidate")
    if revised is not None:
        if disposition != "revise":
            raise Stage2Error("revision-requires-revise-disposition")
        if revised["candidate_id"] != candidate_id:
            raise Stage2Error("revision-candidate-mismatch")
        if revised["version"] != current["version"] + 1:
            raise Stage2Error("revision-version-not-contiguous")
        if revised["parent_version"] != current["version"]:
            raise Stage2Error("revision-parent-mismatch")
        validate_evidence_refs(revised["evidence_ids"], packet)


def latest_candidates(packet, events):
    """Reconstruct all candidate versions and the latest version per ID."""

    histories = {}
    for candidate in packet["candidates"]:
        histories.setdefault(candidate["candidate_id"], []).append(candidate)
    for event in events:
        revised = event["assessment"].get("revised_candidate")
        if revised is not None:
            history = histories.get(revised["candidate_id"])
            if not history:
                raise Stage2Error("history-revision-unknown-candidate")
            current = max(history, key=lambda item: item["version"])
            if (
                revised["version"] != current["version"] + 1
                or revised["parent_version"] != current["version"]
            ):
                raise Stage2Error("history-revision-chain-invalid")
            history.append(revised)
    for history in histories.values():
        history.sort(key=lambda item: item["version"])
    return histories, {
        candidate_id: history[-1] for candidate_id, history in histories.items()
    }

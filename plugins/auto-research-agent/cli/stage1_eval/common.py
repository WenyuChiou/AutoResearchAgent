"""Shared byte bindings and contract loading for the independent evaluator."""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

EVAL_ROOT = Path(__file__).resolve().parents[2] / "evals"
RUBRIC_PATH = EVAL_ROOT / "rubrics/stage1-general.v3.json"


class EvaluationError(ValueError):
    """An evaluation input or recorded output failed closed."""


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise EvaluationError(f"refusing to overwrite {path}")
    path.write_bytes(canonical(value) + b"\n")


def validate_schema(value, name):
    schema = read_json(EVAL_ROOT / "schemas" / name)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=str,
    )
    if errors:
        first = errors[0]
        raise EvaluationError(
            f"{name}:{'/'.join(map(str, first.absolute_path))}:{first.message}"
        )


def load_rubric():
    rubric = read_json(RUBRIC_PATH)
    if (
        rubric.get("rubric_id") != "stage1-general-v3"
        or len(rubric.get("criteria", [])) != 10
    ):
        raise EvaluationError("unknown general Stage 1 rubric")
    return rubric, sha(RUBRIC_PATH.read_bytes())


def check_spec(spec):
    rubric, digest = load_rubric()
    if (
        spec.get("kind") != "TopicEvaluationSpec"
        or spec.get("schema_version") != "3.0.0"
    ):
        raise EvaluationError("expected TopicEvaluationSpec v3")
    if (
        spec.get("rubric_sha256") != digest
        or spec.get("rubric_id") != rubric["rubric_id"]
    ):
        raise EvaluationError("topic spec rubric binding changed")
    if len(spec.get("task_sha256", "")) != 64 or not spec.get("frozen_at"):
        raise EvaluationError("topic spec lacks task binding or freeze time")
    draft = spec.get("draft")
    validate_schema(draft, "topic-spec-draft.v3.schema.json")
    need_ids = [row["need_id"] for row in draft["needs"]]
    roles = [row["role"] for row in draft["roles"]]
    queries = draft["search_policy"]["challenge_queries"]
    if len(set(need_ids)) != len(need_ids) or len(set(roles)) != len(roles):
        raise EvaluationError("duplicate needs or roles")
    if len({row["query_id"] for row in queries}) != len(queries):
        raise EvaluationError("duplicate challenge query IDs")
    if len({row["query"].casefold().strip() for row in queries}) < 2:
        raise EvaluationError("challenge requires distinct search paths")
    if not {"closest", "foundation"}.issubset({row["purpose"] for row in queries}):
        raise EvaluationError("challenge requires closest and foundation paths")
    for row in queries:
        if not set(row["need_ids"]).issubset(need_ids):
            raise EvaluationError("challenge references unknown need")
    if not {"foundation", "closest-work"}.issubset(set(roles)):
        raise EvaluationError(
            "foundation and closest-work applicability must be decided"
        )
    for criterion_id, decision in spec.get("criterion_applicability", {}).items():
        if (
            criterion_id != "P2V3.BOUNDARIES"
            or decision.get("applicability")
            not in {"applicable", "not-applicable", "unresolved"}
            or not decision.get("reason", "").strip()
        ):
            raise EvaluationError("invalid criterion applicability rationale")
    if any(
        key in spec or key in draft
        for key in (
            "gold_set",
            "holdout_sha256",
            "expected_titles",
            "core_hit",
            "core_total",
        )
    ):
        raise EvaluationError("v3 cannot contain answer-key fields")
    return draft

"""Canonical serialization and structural validation for Stage 3 plans."""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator


SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "schemas/stage3-research-plan.v1.schema.json"
)


class Stage3Error(ValueError):
    """A Stage 3 research plan is invalid."""


def canonical_bytes(value):
    """Return deterministic UTF-8 JSON bytes for a contract value."""

    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise Stage3Error(f"value is not canonical JSON: {error}") from error


def digest(value):
    """Return the SHA-256 digest of a canonical contract value."""

    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _schema_validator():
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError) as error:
        raise Stage3Error(f"cannot load Stage 3 plan schema: {error}") from error
    return Draft202012Validator(schema)


def validate_plan(plan):
    """Raise ``Stage3Error`` when a plan violates the v1 closed shape."""

    errors = sorted(_schema_validator().iter_errors(plan), key=str)
    if errors:
        first = errors[0]
        where = "/".join(map(str, first.absolute_path)) or "$"
        raise Stage3Error(f"stage3 plan schema {where}: {first.message}")

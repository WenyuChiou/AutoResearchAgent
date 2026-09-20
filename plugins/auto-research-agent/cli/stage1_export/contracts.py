"""Resolve export schemas only from the production schema directory."""

from functools import lru_cache
from pathlib import Path
from jsonschema import Draft202012Validator
from stage1_ledger.journal import LedgerError, decode


@lru_cache(maxsize=None)
def validator(kind):
    path = Path(__file__).resolve().parents[2] / "schemas/stage1-export.v1.schema.json"
    schema = decode(path.read_bytes(), str(path))
    return Draft202012Validator(dict(schema, **{"$ref": "#/$defs/" + kind}))


def check(value):
    kind = value.get("kind") if isinstance(value, dict) else None
    if kind not in {
        "Stage1ExportManifest",
        "Stage1MetricInputs",
        "Stage1EfficiencyInputs",
        "Stage1NativeCaptureSpec",
        "Stage1NativeUsage",
    }:
        raise LedgerError("unknown-export-kind")
    error = next(validator(kind).iter_errors(value), None)
    if error:
        raise LedgerError("export-schema: " + error.message)

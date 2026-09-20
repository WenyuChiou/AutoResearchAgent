"""Local-only schema resolution; never download schemas from identifiers."""

from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from .journal import LedgerError, decode


@lru_cache(maxsize=None)
def validator(name):
    directory = Path(__file__).resolve().parents[2] / "schemas"
    shared = decode(
        (directory / "stage-contracts.v1.schema.json").read_bytes(), "shared schema"
    )
    schema = decode(
        (directory / "stage1-ledger.v1.schema.json").read_bytes(), "ledger schema"
    )
    registry = Registry().with_resources(
        [
            (shared["$id"], Resource.from_contents(shared)),
            (schema["$id"], Resource.from_contents(schema)),
        ]
    )
    return Draft202012Validator(
        {"$ref": schema["$id"] + "#/$defs/" + name},
        registry=registry,
        format_checker=FormatChecker(),
    )


def check(value, name):
    errors = list(validator(name).iter_errors(value))
    if errors:
        error = errors[0]
        path = "/".join(str(part) for part in error.absolute_path)
        raise LedgerError(f"schema:{name}/{path}: {error.message}")


def check_manifest(value):
    check(value, "Stage1Manifest")
    if value["research_run"]["current_stage"] != 1:
        raise LedgerError("manifest-stage: expected Stage 1")


def check_payload(value):
    kinds = {
        "ActionStarted",
        "ArtifactStored",
        "ActionFinished",
        "QueryEvent",
        "CandidateRevision",
        "DecisionEvent",
        "ClaimEvidence",
        "Checkpoint",
        "ExtractionFailure",
        "IdentityComparison",
    }
    if not isinstance(value, dict) or value.get("kind") not in kinds:
        raise LedgerError("unknown-event-kind")
    check(value, value["kind"])


def check_record(value):
    check(value, "Record")

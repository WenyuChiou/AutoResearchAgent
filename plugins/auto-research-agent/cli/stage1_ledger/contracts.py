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
    coverage = decode(
        (directory / "stage1-coverage-run.v1.schema.json").read_bytes(),
        "coverage schema",
    )
    handoff = decode(
        (directory / "stage1-handoff.v1.schema.json").read_bytes(), "handoff schema"
    )
    sources = decode(
        (directory / "stage1-source-evidence.v1.schema.json").read_bytes(),
        "source evidence schema",
    )
    registry = Registry().with_resources(
        [
            (shared["$id"], Resource.from_contents(shared)),
            (schema["$id"], Resource.from_contents(schema)),
            (coverage["$id"], Resource.from_contents(coverage)),
            (handoff["$id"], Resource.from_contents(handoff)),
            (sources["$id"], Resource.from_contents(sources)),
        ]
    )
    return Draft202012Validator(
        {
            "$ref": (
                sources
                if name in sources["$defs"]
                else handoff
                if name in handoff["$defs"]
                else coverage
                if name in coverage["$defs"]
                else schema
            )["$id"]
            + "#/$defs/"
            + name
        },
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
    if value["mode"] == "research-hub-cli":
        from stage1_retrieval.receipt import check_pin

        check_pin(value["research_hub_pin"])
    elif value["research_hub_pin"] is not None:
        raise LedgerError("offline-manifest-has-runtime")


def check_payload(value):
    kinds = {
        "ActionStarted",
        "SourceImportStarted",
        "ArtifactStored",
        "ActionFinished",
        "QueryEvent",
        "CandidateRevision",
        "DecisionEvent",
        "ClaimEvidence",
        "Checkpoint",
        "ExtractionFailure",
        "IdentityComparison",
        "CoveragePlanBound",
        "CoverageRoundOpened",
        "CoverageReceipt",
        "CoverageRoundClosed",
        "CoverageWorkReview",
        "CoverageHumanAction",
        "SourceReadStarted",
        "SourceReadFinished",
    }
    if not isinstance(value, dict) or value.get("kind") not in kinds:
        raise LedgerError("unknown-event-kind")
    check(value, value["kind"])


def check_record(value):
    check(value, "Record")

"""Local-only schema resolution; never download schemas from identifiers."""

from collections import OrderedDict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import threading

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from .journal import LedgerError, decode
from .source_arguments import check_source_arguments


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


# Schema validity is a pure function of (schema name, exact JSON value): the
# schemas are fixed local files and the validator is already process-cached. A
# ledger is re-read and re-checked on every request, and one request checks the
# same few thousand immutable events many times, so remember only *successful*
# results keyed by a digest of the exact value. Every call still reads, parses
# and hashes its input; an edited value has a different digest and is validated
# again; a failure is never remembered.
_VALID_LIMIT = 250_000
_valid = OrderedDict()
_valid_lock = threading.Lock()


def _value_key(value, name):
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        return None
    return name, hashlib.sha256(raw).digest()


def check(value, name):
    key = _value_key(value, name)
    if key is not None:
        with _valid_lock:
            if key in _valid:
                _valid.move_to_end(key)
                return
    errors = list(validator(name).iter_errors(value))
    if errors:
        error = errors[0]
        path = "/".join(str(part) for part in error.absolute_path)
        raise LedgerError(f"schema:{name}/{path}: {error.message}")
    if key is not None:
        with _valid_lock:
            _valid[key] = True
            while len(_valid) > _VALID_LIMIT:
                _valid.popitem(last=False)


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
    check_source_arguments(value)
    check(value, value["kind"])
    if value["kind"] == "ClaimEvidence":
        from .semantics import assessment_check

        assessment_check(value)


def check_record(value):
    check(value, "Record")

"""Check saved execution evidence without executing a command or contacting a provider."""

from datetime import datetime
from functools import lru_cache
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from stage1_ledger.journal import LedgerError, canonical, decode, digest
from .audit import require
from .projection import project


@lru_cache(maxsize=None)
def validator(kind):
    directory = Path(__file__).resolve().parents[2] / "schemas"
    schema = decode(
        (directory / "stage1-execution.v1.schema.json").read_bytes(), "execution schema"
    )
    shared = decode(
        (directory / "stage-contracts.v1.schema.json").read_bytes(), "shared schema"
    )
    registry = Registry().with_resources(
        [(v["$id"], Resource.from_contents(v)) for v in (schema, shared)]
    )
    return Draft202012Validator(
        {"$ref": schema["$id"] + "#/$defs/" + kind},
        registry=registry,
        format_checker=FormatChecker(),
    )


def check(value, kind):
    errors = list(validator(kind).iter_errors(value))
    if errors:
        raise LedgerError("execution-schema:" + errors[0].message)


def check_pin(pin):
    check(pin, "Pin")
    path = (
        Path(__file__).resolve().parents[2]
        / "schemas/research-hub-audit.v1.schema.json"
    )
    require(
        pin["audit_schema_sha256"] == digest(path.read_bytes()), "runtime-schema-pin"
    )


def check_saved_relative_path(relative):
    """Check receipt names without consulting the replay caller's filesystem."""
    require(
        isinstance(relative, str)
        and relative
        and not any(ord(character) < 32 for character in relative),
        "unsafe-audit-path",
    )
    pieces = relative.split("/")
    require(
        "\\" not in relative
        and ":" not in relative
        and not PurePosixPath(relative).is_absolute()
        and all(piece not in {"", ".", ".."} for piece in pieces),
        "unsafe-audit-path",
    )


def command(pin, operation, arguments, backend, audit_directory, identifier=None):
    require(
        operation in {"search", "references", "cited-by", "enrich", "verify"},
        "unsupported-command",
    )
    flags = [
        "--limit",
        str(arguments["limit"]),
        "--json",
        "--audit-output",
        audit_directory,
    ]
    if operation == "search":
        require(
            backend in {"openalex", "crossref", "semantic-scholar", "arxiv", "pubmed"},
            "unsupported-backend",
        )
        flags += [
            "--backend",
            backend,
            "--rank-by",
            arguments.get("rank_by") or "smart",
        ]
        if arguments.get("year"):
            flags += ["--year", arguments["year"]]
        target = arguments["query"]
    elif operation in {"references", "cited-by"}:
        require(
            backend == "semantic-scholar" and identifier,
            "citation-backend-or-identifier",
        )
        target = identifier
    elif operation == "enrich":
        require(
            backend in {"openalex", "arxiv", "semantic-scholar"} and identifier,
            "lookup-backend-or-identifier",
        )
        flags = ["--backend", backend, "--json", "--audit-output", audit_directory]
        target = identifier.split(":", 1)[1]
    else:
        require(
            identifier
            and (
                (backend == "doi.org" and identifier.startswith("DOI:"))
                or (backend == "arxiv.org" and identifier.startswith("ARXIV:"))
            ),
            "resolver-backend-or-identifier",
        )
        flags = [
            "--audit-output",
            audit_directory,
            "--doi" if backend == "doi.org" else "--arxiv",
            identifier.split(":", 1)[1],
        ]
    argv = (
        pin["argv_prefix"]
        + [operation, *flags]
        + ([] if operation == "verify" else ["--", target])
    )
    require(
        all(isinstance(value, str) and value for value in argv),
        "invalid-command-argument",
    )
    return argv


def validate_execution(manifest, attempt, completion, read_ref):
    require(manifest["mode"] == "research-hub-cli", "execution-in-offline-run")
    pin = manifest["research_hub_pin"]
    check_pin(pin)
    require("execution_ref" in completion, "missing-execution-receipt")
    receipt = decode(read_ref(completion["execution_ref"]), "execution receipt")
    check(receipt, "Receipt")
    args = attempt["arguments"]
    require(receipt["attempt_id"] == attempt["event_id"], "receipt-attempt")
    require(
        receipt["runtime_sha256"] == args["runtime_sha256"] == digest(canonical(pin)),
        "receipt-runtime",
    )
    require(
        args["argv"]
        == command(
            pin,
            args["operation"],
            args["input"],
            attempt["backend"],
            args["audit_directory"],
            args["identifier"],
        ),
        "receipt-command",
    )
    process = receipt["process"]
    require(process["exit_code"] == completion["exit_code"], "receipt-exit-code")
    times = [
        datetime.fromisoformat(t.replace("Z", "+00:00"))
        for t in (attempt["created_at"], process["started_at"], process["ended_at"])
    ]
    require(
        all(t.utcoffset() is not None for t in times) and times == sorted(times),
        "process-time-order",
    )
    if "created_at" in completion:
        require(
            times[-1]
            <= datetime.fromisoformat(completion["created_at"].replace("Z", "+00:00")),
            "process-end-after-completion",
        )
    for key in ("stdout", "stderr"):
        require(
            digest(read_ref(completion[key])) == process[key + "_sha256"],
            "process-" + key,
        )
    files = {}
    for name, ref in receipt["audit_files"].items():
        require(
            ref["producer"] == attempt["event_id"], "audit-artifact-producer-mismatch"
        )
        check_saved_relative_path(name)
        files[name] = read_ref(ref)
    require(
        {name: digest(raw) for name, raw in files.items()} == process["audit_files"],
        "capture-audit-files",
    )
    projected = project(
        files,
        backend=attempt["backend"],
        process=process,
        operation=args["operation"],
        argv=args["argv"][len(pin["argv_prefix"]) :],
    )
    require(
        receipt["projection"] == {k: v for k, v in projected.items() if k != "records"},
        "receipt-projection",
    )
    for key in ("outcome", "http_status"):
        require(completion[key] == projected[key], "receipt-" + key)
    records = (
        decode(read_ref(completion["records"]), "normalized records")
        if completion["records"]
        else None
    )
    require(records == projected["records"], "receipt-records")
    return receipt

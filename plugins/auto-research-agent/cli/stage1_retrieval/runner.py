"""Run one public CLI attempt, then import its sealed local capture exactly once."""

import os
from pathlib import Path
import subprocess
import uuid

from stage1_ledger.journal import (
    LedgerError,
    canonical,
    contained,
    decode,
    digest,
    utc_now,
    write_new,
)
from stage1_ledger.store import Ledger
from .audit import require
from .projection import project
from .receipt import check, check_pin, command


def audit_files(directory, limit):
    result = {}
    if directory.exists():
        for path in sorted(directory.rglob("*")):
            name = path.relative_to(directory).as_posix()
            safe = contained(directory, name)
            if safe.is_file():
                require(safe.stat().st_size <= limit, "capture-file-size:" + name)
                result[name] = safe.read_bytes()
                require(
                    len(result) <= 4096
                    and sum(map(len, result.values())) <= 128 * 1024 * 1024,
                    "capture-total-limit",
                )
    return result


def identifier_for(ledger, query):
    if query["arguments"].get("operation", "search") == "search":
        return None
    seed = query["arguments"]["coverage"]
    work = ledger.candidates().get(seed["seed_work_id"])
    require(work is not None, "unknown-citation-seed")
    # Only use identifiers from the specified naturally discovered version.
    for discovery in work["discoveries"]:
        if discovery["version_id"] == seed["seed_version_id"]:
            row = discovery["record"]
            if row.get("doi"):
                return "DOI:" + row["doi"]
            if row.get("arxiv"):
                return "ARXIV:" + row["arxiv"]
    raise LedgerError("citation-seed-has-no-supported-identifier")


def execute(root, query_id, backend):
    ledger = Ledger(root)
    require(ledger.manifest["mode"] == "research-hub-cli", "live-runtime-required")
    pin = ledger.manifest["research_hub_pin"]
    check_pin(pin)
    require(
        digest(Path(pin["argv_prefix"][0]).read_bytes()) == pin["executable_sha256"],
        "changed-executable",
    )
    require(
        digest(Path(pin["config"]["path"]).read_bytes()) == pin["config"]["sha256"],
        "changed-config",
    )
    query = ledger.event(query_id, "ActionStarted")
    require(
        query["operation"] == "search" and query_id in ledger.pending(),
        "query-not-open",
    )
    require(
        not any(
            p["kind"] == "ActionStarted"
            and p["parent_id"] == query_id
            and p["backend"] == backend
            for p in (r["payload"] for r in ledger.events())
        ),
        "attempt-already-recorded: resume saved capture or explicitly create a new query",
    )
    capture = contained(ledger.root, "captures/" + uuid.uuid4().hex)
    audit = capture / "audit"
    operation = query["arguments"].get("operation", "search")
    identifier = identifier_for(ledger, query)
    argv = command(pin, operation, query["arguments"], backend, str(audit), identifier)
    arguments = dict(
        driver="research-hub-cli-v1",
        operation=operation,
        input=query["arguments"],
        identifier=identifier,
        argv=argv,
        audit_directory=str(audit),
        capture_directory=capture.relative_to(ledger.root).as_posix(),
        runtime_sha256=digest(canonical(pin)),
    )
    attempt = ledger.start("backend", arguments, backend=backend, parent_id=query_id)
    capture.mkdir(parents=True, exist_ok=False)
    started, failure, exit_code = utc_now(), None, 127
    environment = dict(
        os.environ,
        RESEARCH_HUB_CONFIG=pin["config"]["path"],
        RESEARCH_HUB_NO_ZOTERO="1",
    )
    # No shell, model CLI, vault ingest, or automatic retry is involved.
    with (
        (capture / "stdout.bin").open("xb") as out,
        (capture / "stderr.bin").open("xb") as err,
    ):
        try:
            child = subprocess.Popen(
                argv,
                cwd=pin["cwd"],
                env=environment,
                stdout=out,
                stderr=err,
                stdin=subprocess.DEVNULL,
                shell=False,
            )
            try:
                exit_code = child.wait(timeout=pin["timeout_seconds"])
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                failure = (
                    "timeout"
                    if isinstance(error, subprocess.TimeoutExpired)
                    else "interrupted"
                )
                child.kill()
                exit_code = child.wait()
        except OSError as error:
            failure = "unknown_error"
            err.write(str(error).encode("utf-8"))
        for stream in (out, err):
            stream.flush()
            os.fsync(stream.fileno())
    files = audit_files(audit, ledger.manifest["max_artifact_bytes"])
    process = dict(
        started_at=started,
        ended_at=utc_now(),
        exit_code=exit_code,
        failure=failure,
        stdout_sha256=digest((capture / "stdout.bin").read_bytes()),
        stderr_sha256=digest((capture / "stderr.bin").read_bytes()),
        audit_files={name: digest(raw) for name, raw in files.items()},
    )
    write_new(capture / "process.json", canonical(process))
    return resume(root, attempt)


def resume(root, attempt_id):
    """Read an existing completed process capture. This function never starts a process."""
    ledger = Ledger(root)
    attempt = ledger.event(attempt_id, "ActionStarted")
    require(attempt_id in ledger.pending(), "attempt-not-open")
    args = attempt["arguments"]
    require(args.get("driver") == "research-hub-cli-v1", "unknown-execution-driver")
    capture = contained(ledger.root, args["capture_directory"])
    process = decode(contained(capture, "process.json").read_bytes(), "process capture")
    check(process, "Process")
    streams = {
        key: contained(capture, key + ".bin").read_bytes()
        for key in ("stdout", "stderr")
    }
    for key, raw in streams.items():
        require(digest(raw) == process[key + "_sha256"], "changed-capture:" + key)
    files = audit_files(
        contained(capture, "audit"), ledger.manifest["max_artifact_bytes"]
    )
    require(
        {name: digest(raw) for name, raw in files.items()} == process["audit_files"],
        "changed-capture:audit",
    )
    projected = project(
        files,
        backend=attempt["backend"],
        process=process,
        operation=args["operation"],
        argv=args["argv"][len(ledger.manifest["research_hub_pin"]["argv_prefix"]) :],
    )
    refs = {
        key: ledger.save_bytes(raw, producer=attempt_id) for key, raw in streams.items()
    }
    records = (
        None
        if projected["records"] is None
        else ledger.save_bytes(canonical(projected["records"]), producer=attempt_id)
    )
    saved = {
        name: ledger.save_bytes(raw, producer=attempt_id) for name, raw in files.items()
    }
    receipt = dict(
        kind="Stage1ExecutionReceipt",
        schema_version="1.0.0",
        attempt_id=attempt_id,
        runtime_sha256=args["runtime_sha256"],
        process=process,
        audit_files=saved,
        projection={k: v for k, v in projected.items() if k != "records"},
    )
    check(receipt, "Receipt")
    execution_ref = ledger.save_bytes(canonical(receipt), producer=attempt_id)
    return ledger.finish(
        attempt_id,
        outcome=projected["outcome"],
        http_status=projected["http_status"],
        exit_code=process["exit_code"],
        records=records,
        execution_ref=execution_ref,
        **refs,
    )

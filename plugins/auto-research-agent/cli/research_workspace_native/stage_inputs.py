"""Bounded saved-input bytes and real offline stage producers.

Stage1 checkpoint runs on an action-owned ledger copy. Stage2 completion replays
saved delivery/evaluation evidence. Nothing authorizes native/model execution.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

from stage1_deliverable.common import (
    canonical,
    private_output,
    reject_links,
    safe_path,
    sha,
)
from stage1_ledger.store import Ledger
from stage1_ledger.validation import validate_run
from stage2_workflow.completion import inspect_completion
from research_workspace_native.session_api import SessionApiError

HASH = re.compile(r"[0-9a-f]{64}")
MAX_BYTES, MAX_FILES = 64 * 1024 * 1024, 512


def _check(condition, code, status=409):
    if not condition:
        raise SessionApiError(code, status)


def _hash(value):
    return isinstance(value, str) and bool(HASH.fullmatch(value))


def _walk_error(error):
    raise error


def snapshot_inputs(inputs):
    """Trusted registration helper; read bounded regular files, never producers."""
    _check(
        isinstance(inputs, dict) and set(inputs) in ({1, 2}, {"1", "2"}),
        "stage-input-shape",
        400,
    )
    files, total, entries = {}, 0, 0
    for stage_key, item in inputs.items():
        stage = int(stage_key)
        if item is None:
            continue
        expected = (
            {"ledger_root"}
            if stage == 1
            else {
                "delivery_root",
                "delivery_manifest_sha256",
                "evaluation_root",
                "evaluation_manifest_sha256",
            }
        )
        _check(
            isinstance(item, dict) and set(item) == expected, "stage-input-shape", 400
        )
        if stage == 2:
            _check(
                _hash(item["delivery_manifest_sha256"]), "manifest-hash-required", 400
            )
            _check(
                (item["evaluation_root"] is None)
                == (item["evaluation_manifest_sha256"] is None),
                "assessment-binding-required",
                400,
            )
            _check(
                item["evaluation_root"] is None
                or _hash(item["evaluation_manifest_sha256"]),
                "manifest-hash-required",
                400,
            )
        for name in (
            ("ledger_root",) if stage == 1 else ("delivery_root", "evaluation_root")
        ):
            if item[name] is None:
                continue
            source = Path(item[name])
            _check(source.is_absolute(), "absolute-input-root-required", 400)
            source = private_output(source).resolve()
            _check(source.is_dir(), "input-directory-required", 400)
            for base, directories, names in os.walk(
                source, followlinks=False, onerror=_walk_error
            ):
                entries += len(directories) + len(names)
                _check(entries <= MAX_FILES * 4, "input-entry-bound")
                directories.sort()
                for directory in directories:
                    reject_links(Path(base) / directory)  # Before os.walk descends.
                for filename in sorted(names):
                    path = Path(base) / filename
                    reject_links(path)
                    info = os.lstat(path)
                    _check(
                        stat.S_ISREG(info.st_mode)
                        and info.st_size <= MAX_BYTES - total,
                        "input-file-bound",
                    )
                    key = f"stage{stage}/{name}/{path.relative_to(source).as_posix()}"
                    chunks, remaining = [], MAX_BYTES - total + 1
                    with path.open("rb") as stream:
                        while remaining > 0:
                            chunk = stream.read(min(64 * 1024, remaining))
                            if not chunk:
                                break
                            chunks.append(chunk)
                            remaining -= len(chunk)
                    raw = b"".join(chunks)
                    total += len(raw)
                    _check(
                        total <= MAX_BYTES and len(files) < MAX_FILES,
                        "input-snapshot-bound",
                    )
                    files[key] = raw
    return files


def source_digest(files):
    return sha(
        canonical(
            {
                name: {"sha256": sha(raw), "size": len(raw)}
                for name, raw in files.items()
            }
        )
    )


def preflight_storage(prepared, store_path):
    """Reject source overlap and all old binding drift before opening a writer."""
    inputs = [
        Path(value).resolve()
        for _, _, _, binding in prepared
        for stage_input in binding["inputs"].values()
        for name, value in (stage_input or {}).items()
        if name.endswith("_root") and value is not None
    ]
    database = private_output(Path(store_path)).resolve()
    for _, _, output, _ in prepared:
        _check(
            all(
                not output.is_relative_to(source) and not source.is_relative_to(output)
                for source in inputs
            ),
            "cross-project-input-output-overlap",
        )
    _check(
        all(not database.is_relative_to(source) for source in inputs),
        "database-input-overlap",
    )
    for suffix in ("", "-wal", "-shm", "-journal"):
        safe_path(database.parent, database.name + suffix)
    if database.exists():
        _check(database.is_file(), "journal-regular-file-required")
        connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        try:
            for ref, item, _, binding in prepared:
                row = connection.execute(
                    "SELECT state FROM projects WHERE id=?",
                    ("stage-actions-" + sha(ref.encode())[:32],),
                ).fetchone()
                if row:
                    state = json.loads(row[0])
                    _check(
                        state["index_sha256"] == item["index_sha256"]
                        and state.get("stage_actions_binding", binding) == binding,
                        "saved-registration-differs",
                    )
        finally:
            connection.close()
    return database


def produce_stage_result(binding, row, root, state):
    stage = row["stage"]
    _check(
        type(stage) is int
        and stage in (1, 2)
        and row["action"]
        in (
            {"checkpoint-stage1", "review-stage"}
            if stage == 1
            else {"inspect-stage2", "review-stage"}
        ),
        "stage-action-unavailable",
        400,
    )
    request = row["request"]
    if row["action"] == "review-stage":
        checks = [
            r
            for r in state["intents"].values()
            if r["stage"] == stage and r["action"] != "review-stage"
        ]
        latest = max(checks, key=lambda r: r["intent_revision"]) if checks else None
        readiness = (
            deepcopy(latest["result"]["readiness"])
            if latest
            and latest.get("outcome") == "succeeded"
            and latest["status"] == "completed"
            else dict(
                status="missing" if latest is None else "unavailable",
                blockers=[
                    "stage-check-not-run"
                    if latest is None
                    else "latest-stage-check-unavailable"
                ],
            )
        )
        next_request = (
            "not-requested"
            if request["decision"] != "request-next"
            else "blocked"
            if readiness["status"] not in {"ready", "pass"}
            else "recorded-awaiting-execution-authority"
        )
        return dict(
            kind="WorkspaceStageReviewRecord",
            schema_version="1.0.0",
            stage=stage,
            principal=row["principal"],
            decision=request["decision"],
            note=request["note"],
            source_sha256=binding["source_sha256"],
            index_sha256=binding["index_sha256"],
            input_version=binding["input_version"],
            check_action_ref=latest["key"] if latest else None,
            readiness=readiness,
            next_stage_request=next_request,
            native_user_message_attested=False,
            execution_authorized=False,
        )
    item = binding["inputs"][str(stage)]
    if item is None:
        return dict(
            kind="WorkspaceStageActionResult",
            stage=stage,
            readiness=dict(status="missing", blockers=["saved-stage-input-missing"]),
            execution_authorized=False,
        )
    files = snapshot_inputs(binding["inputs"])
    _check(source_digest(files) == binding["source_sha256"], "saved-input-changed")
    for name, raw in files.items():
        if name.startswith(f"stage{stage}/"):
            path = safe_path(root, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
    if stage == 1:
        ledger = Ledger(root / "stage1/ledger_root")
        event = ledger.checkpoint()
        report = validate_run(ledger.root)
        _check(report["valid"], "checkpoint-validation-failed")
        result = event["stage_result"]
        handoff = json.loads(ledger.read_ref(result["outputs"][-1]))
        readiness = dict(
            status="pass" if result["gate"]["outcome"] == "pass" else "blocked",
            blockers=result["gate"].get("blocking_items", []),
            next_allowed_action=result["next_allowed_action"],
        )
        return dict(
            kind="WorkspaceStageActionResult",
            stage=stage,
            readiness=readiness,
            checkpoint=event,
            handoff=handoff,
            ledger_valid=report["valid"],
            source_state_sha256=report["state_sha256"],
            execution_authorized=False,
        )
    options = (
        {}
        if item["evaluation_root"] is None
        else dict(
            evaluation_dir=root / "stage2/evaluation_root",
            expected_evaluation_manifest_sha256=item["evaluation_manifest_sha256"],
        )
    )
    completion = inspect_completion(
        root / "stage2/delivery_root", item["delivery_manifest_sha256"], **options
    )
    return dict(
        kind="WorkspaceStageActionResult",
        stage=stage,
        readiness=dict(
            status="ready" if completion["stage2_complete"] else "incomplete",
            blockers=completion["blockers"],
        ),
        completion=completion,
        execution_authorized=False,
    )

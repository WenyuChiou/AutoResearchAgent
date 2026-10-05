"""Join a native judge archive to its originally sealed inference traces.

Run inside the retained role namespace with its original runtime and home paths.
This read-only check authenticates execution and usage, not scientific scores or
namespace isolation. The seal digest must come from the caller's retained log.
"""

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from stage1_eval.common import canonical
from stage2_common import Stage2Error

from .judge_worker import verify_worker_output
from .replay import _require_sha
from .trace_observation import inspect_native_trace


def _path(value, *, directory=False):
    path = Path(os.path.abspath(os.fspath(value)))
    for index, item in enumerate((path, *path.parents)):
        info = os.lstat(item)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(info.st_mode) or (
            reparse and getattr(info, "st_file_attributes", 0) & reparse
        ):
            raise Stage2Error("judge-trace-replay-link-path")
        wants_directory = directory or index > 0
        if not (
            stat.S_ISDIR(info.st_mode)
            if wants_directory
            else stat.S_ISREG(info.st_mode)
        ):
            raise Stage2Error("judge-trace-replay-path-type")
    return path


def _json(path):
    value = json.loads(_path(path).read_bytes())
    if not isinstance(value, dict):
        raise Stage2Error("judge-trace-replay-object-required")
    return value


def _attempt_roots(output, label, count):
    archive = _path(output / (label + ".model-call"), directory=True)
    files = sorted(archive.glob("attempt-*.stdout.jsonl"))
    expected = [f"attempt-{number:02d}.stdout.jsonl" for number in range(1, count + 1)]
    if [path.name for path in files] != expected:
        raise Stage2Error("judge-trace-replay-attempt-files")
    roots = set()
    for path in files:
        rows = [
            json.loads(line)
            for line in _path(path).read_bytes().splitlines()
            if line.strip()
        ]
        found = [
            row.get("thread_id")
            for row in rows
            if isinstance(row, dict) and row.get("type") == "thread.started"
        ]
        if (
            len(found) != 1
            or not isinstance(found[0], str)
            or not found[0]
            or found[0] in roots
        ):
            raise Stage2Error("judge-trace-replay-attempt-root")
        roots.add(found[0])
    return roots


def verify_judge_trace_unit(
    output_dir,
    worker_result_sha256,
    *,
    request_file,
    request_sha256,
    codex,
    evaluator_home,
    trace_root,
    seal_file,
    externally_retained_seal_sha256,
    envelope_root,
):
    """Recompute a sealed unit without a model call, write, or saved PASS.

    Every attempted generation needs a distinct joined trace. Incomplete usage,
    tool activity, child threads, or a missing original seal fail closed. The
    generation envelope's hashes are checked but do not attest its mount policy.
    """
    _require_sha(externally_retained_seal_sha256, "judge-trace-original-seal")
    seal_path = _path(seal_file)
    if (
        hashlib.sha256(seal_path.read_bytes()).hexdigest()
        != externally_retained_seal_sha256
    ):
        raise Stage2Error("judge-trace-replay-original-seal-mismatch")
    seal = _json(seal_path)
    if set(seal) != {
        "label",
        "role",
        "request_sha256",
        "worker_result_sha256",
        "traces",
        "native_stdout_sha256",
        "native_stderr_sha256",
        "native_result_sha256",
    }:
        raise Stage2Error("judge-trace-replay-seal-shape")
    request_path = _path(request_file)
    request = _json(request_path)
    if any(
        seal[key] != expected
        for key, expected in (
            ("label", request.get("label")),
            ("role", request.get("role")),
            ("request_sha256", request_sha256),
            ("worker_result_sha256", worker_result_sha256),
        )
    ):
        raise Stage2Error("judge-trace-replay-seal-binding")
    envelope = _path(envelope_root, directory=True)
    for name, key in (
        ("native.stdout", "native_stdout_sha256"),
        ("native.stderr", "native_stderr_sha256"),
        ("native-result.json", "native_result_sha256"),
    ):
        _require_sha(seal[key], key)
        if hashlib.sha256(_path(envelope / name).read_bytes()).hexdigest() != seal[key]:
            raise Stage2Error("judge-trace-replay-envelope-mismatch")
    home = _path(evaluator_home, directory=True)
    if (home / "auth.json").exists() or (home / "auth.json").is_symlink():
        raise Stage2Error("judge-trace-replay-credentials-present")
    output = _path(output_dir, directory=True)
    result = verify_worker_output(
        output,
        worker_result_sha256,
        request_file=request_path,
        request_sha256=request_sha256,
        codex=codex,
        evaluator_home=home,
    )
    count = result["actual_root_attempts"]
    if type(count) is not int or count < 1:
        raise Stage2Error("judge-trace-replay-attempt-count")
    roots = _attempt_roots(output, result["label"], count)
    traces = seal["traces"]
    if not isinstance(traces, dict) or len(traces) != count:
        raise Stage2Error("judge-trace-replay-attempt-trace-count")
    trace_path = _path(trace_root, directory=True)
    if {path.name for path in trace_path.iterdir()} != set(traces):
        raise Stage2Error("judge-trace-replay-trace-set")
    observations, joined, totals = [], set(), {}
    for name, inventory in sorted(traces.items()):
        if not isinstance(name, str) or not re.fullmatch(
            r"trace-[A-Za-z0-9_.-]+", name
        ):
            raise Stage2Error("judge-trace-replay-trace-name")
        trace = _path(trace_path / name, directory=True)
        observation = inspect_native_trace(
            trace, inventory, hashlib.sha256(canonical(inventory)).hexdigest()
        )
        root = observation["root_thread_id"]
        if root not in roots or root in joined:
            raise Stage2Error("judge-trace-replay-foreign-or-duplicate-root")
        joined.add(root)
        if observation["blockers"]:
            raise Stage2Error(
                "judge-trace-replay-incomplete: " + ", ".join(observation["blockers"])
            )
        if (
            observation["counts"]["tool_calls"] != 0
            or observation["counts"]["threads"] != 1
        ):
            raise Stage2Error("judge-trace-replay-tool-or-child-activity")
        usage = observation["token_usage_totals"]
        if (
            not isinstance(usage, dict)
            or not usage
            or any(type(value) is not int or value < 0 for value in usage.values())
        ):
            raise Stage2Error("judge-trace-replay-usage-incomplete")
        if totals and set(usage) != set(totals):
            raise Stage2Error("judge-trace-replay-usage-shape")
        for key, value in usage.items():
            totals[key] = totals.get(key, 0) + value
        observations.append(observation)
    if joined != roots:
        raise Stage2Error("judge-trace-replay-unmatched-attempt")
    return {
        "kind": "Stage2NativeJudgeTraceReplay",
        "schema_version": "1.0.0",
        "authenticated": True,
        "request_sha256": request_sha256,
        "worker_result_sha256": worker_result_sha256,
        "original_seal_sha256": externally_retained_seal_sha256,
        "role": result["role"],
        "label": result["label"],
        "result": result,
        "observations": observations,
        "actual_root_attempts": count,
        "call_accounting_complete": True,
        "token_usage_complete": True,
        "token_usage_totals": totals,
        "new_model_calls": 0,
        "offered_tools_claim": "exact-observed-inventory; absence-not-assumed",
        "namespace_isolation": "not-attested-by-this-replay",
        "semantic_validation": "host-required",
        "cost": "unknown",
        "formal_ready": False,
    }

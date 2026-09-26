"""Append-only evaluator model-call capture and verified replay for v3.1."""

import copy
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from .common import EvaluationError, canonical, read_json, sha
from .runtime import executable_sha256

MODEL_CALL_ARCHIVE_VERSION = "3.1.0"


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _write_new(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise EvaluationError(f"refusing to overwrite model-call evidence: {path}")
    path.write_bytes(raw)


def _json_new(path, value):
    _write_new(path, canonical(value) + b"\n")


def _normalize_policy(execution_policy, timeout):
    if not isinstance(execution_policy, dict):
        raise EvaluationError("v3.1 execution policy must be a frozen object")
    try:
        policy = json.loads(json.dumps(execution_policy))
    except (TypeError, ValueError) as exc:
        raise EvaluationError("v3.1 execution policy is not JSON serializable") from exc
    policy.setdefault("kind", "EvaluatorModelExecutionPolicy")
    policy.setdefault("schema_version", MODEL_CALL_ARCHIVE_VERSION)
    policy.setdefault("timeout_seconds", 600 if timeout is None else timeout)
    policy.setdefault("max_transient_transport_retries", 1)
    if policy["schema_version"] != MODEL_CALL_ARCHIVE_VERSION:
        raise EvaluationError("unknown evaluator model-call policy version")
    if (
        not isinstance(policy["timeout_seconds"], (int, float))
        or isinstance(policy["timeout_seconds"], bool)
        or policy["timeout_seconds"] <= 0
    ):
        raise EvaluationError("model-call timeout must be positive")
    if timeout is not None and timeout != policy["timeout_seconds"]:
        raise EvaluationError("timeout argument differs from frozen execution policy")
    retries = policy["max_transient_transport_retries"]
    if (
        not isinstance(retries, int)
        or isinstance(retries, bool)
        or retries not in (0, 1)
    ):
        raise EvaluationError("v3.1 permits at most one transient transport retry")
    if any(policy.get(key) is True for key in ("retry_timeouts", "retry_timeout")):
        raise EvaluationError("v3.1 does not retry evaluator timeouts")
    bundle = policy.get("evaluator_bundle_sha256")
    if (
        not isinstance(bundle, str)
        or len(bundle) != 64
        or any(character not in "0123456789abcdef" for character in bundle)
    ):
        raise EvaluationError("v3.1 policy lacks a frozen evaluator bundle SHA-256")
    return policy


def _completed_agent_json(raw):
    try:
        events = [json.loads(line) for line in raw.splitlines()]
    except (UnicodeDecodeError, ValueError) as exc:
        raise EvaluationError("evaluator transcript is unreadable") from exc
    if not any(event.get("type") == "turn.completed" for event in events):
        raise EvaluationError("evaluator transcript lacks a completed turn")
    benign = (
        "Code Mode is unavailable because code-mode host is disabled.",
        "Skill descriptions were shortened to fit the skills context budget.",
    )
    messages = []
    for event in events:
        if not event.get("type", "").startswith("item."):
            continue
        item = event.get("item", {})
        if item.get("type") == "agent_message":
            if event.get("type") == "item.completed":
                messages.append(item.get("text"))
            continue
        if item.get("type") == "reasoning":
            continue
        if item.get("type") == "error" and any(
            item.get("message", "").startswith(prefix) for prefix in benign
        ):
            continue
        raise EvaluationError("evaluator transcript contains a tool or error event")
    if len(messages) != 1 or not isinstance(messages[0], str):
        raise EvaluationError("evaluator transcript lacks a unique final JSON message")
    try:
        return json.loads(messages[0])
    except ValueError as exc:
        raise EvaluationError("evaluator final message is not JSON") from exc


def _evaluator_code_sha():
    root = Path(__file__).resolve().parent
    rows = []
    for name in ("model.py", "model_calls.py"):
        raw = (root / name).read_bytes()
        rows.append({"path": name, "sha256": sha(raw)})
    return sha(canonical(rows))


def _command(codex, model, reasoning, generation_schema, attempt_output):
    command = [
        str(codex),
        "exec",
        "--json",
        "--ignore-user-config",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{reasoning}"',
        "--output-schema",
        str(generation_schema),
        "-o",
        str(attempt_output),
        "-",
    ]
    from .model import DISABLED

    for name in DISABLED:
        command[3:3] = ["--disable", name]
    return command


def _request_config(codex, evaluator_home, model, reasoning):
    home = Path(evaluator_home).resolve()
    if not home.is_dir():
        raise EvaluationError("evaluator CODEX_HOME does not exist")
    return {
        "codex": str(Path(codex).resolve()),
        "codex_executable_sha256": executable_sha256(codex),
        "evaluator_home": str(home),
        "model": model,
        "reasoning": reasoning,
    }


def _request_record(prompt, schema_raw, generation_raw, config, policy, label):
    binding = {
        "archive_version": MODEL_CALL_ARCHIVE_VERSION,
        "label": label,
        "prompt_sha256": sha(prompt.encode("utf-8")),
        "schema_sha256": sha(schema_raw),
        "generation_schema_sha256": sha(generation_raw),
        "config": config,
        "execution_policy": policy,
        "evaluator_code_sha256": _evaluator_code_sha(),
    }
    return {**binding, "request_fingerprint_sha256": sha(canonical(binding))}


def _transport_diagnostics(stdout, stderr):
    diagnostics = [stderr.decode("utf-8", errors="replace")]
    try:
        events = [json.loads(line) for line in stdout.splitlines()]
    except (UnicodeDecodeError, ValueError):
        return diagnostics, False, False
    completed = any(event.get("type") == "turn.completed" for event in events)
    tool_event = False
    for event in events:
        item = event.get("item", {})
        if event.get("type", "").startswith("item.") and item.get("type") not in {
            "agent_message",
            "reasoning",
            "error",
        }:
            tool_event = True
        if item.get("type") == "error":
            diagnostics.append(str(item.get("message", "")))
        if event.get("type") == "error":
            diagnostics.append(str(event.get("message", event.get("error", ""))))
    return diagnostics, completed, tool_event


def _transient_transport_failure(stdout, stderr, returncode):
    if not returncode:
        return False
    diagnostics, completed, tool_event = _transport_diagnostics(stdout, stderr)
    if completed or tool_event:
        return False
    text = "\n".join(diagnostics).casefold()
    if any(
        token in text
        for token in ("401", "unauthorized", "invalid api key", "authentication")
    ):
        return False
    return any(
        token in text
        for token in (
            "429",
            "rate limit",
            "connection reset",
            "connection aborted",
            "connection refused",
            "network transport",
            "transport error",
            "network error",
        )
    )


def _attempt_files(archive, number):
    stem = archive / f"attempt-{number:02d}"
    return {
        "stdout": stem.with_suffix(".stdout.jsonl"),
        "stderr": stem.with_suffix(".stderr.txt"),
        "output": stem.with_suffix(".output.json"),
        "record": stem.with_suffix(".record.json"),
    }


def _save_attempt(files, stdout, stderr, output, record):
    _write_new(files["stdout"], stdout)
    _write_new(files["stderr"], stderr)
    _write_new(files["output"], output)
    record["files"] = {
        key: {"path": path.name, "sha256": sha(path.read_bytes())}
        for key, path in files.items()
        if key != "record"
    }
    _json_new(files["record"], record)


def _validate_semantics(result, semantic_validator):
    if semantic_validator is None:
        return
    try:
        verdict = semantic_validator(copy.deepcopy(result))
    except Exception as exc:
        raise EvaluationError(
            f"model output failed caller semantic validation: {exc}"
        ) from exc
    if verdict is False:
        raise EvaluationError("model output failed caller semantic validation")


def _validate_local_schema(result, schema):
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            result
        ),
        key=str,
    )
    if errors:
        first = errors[0]
        location = "/".join(map(str, first.absolute_path))
        raise EvaluationError(
            f"model output failed local schema validation at {location}: {first.message}"
        )


def replay_native_model_call_archive(
    archive,
    *,
    expected_prompt,
    expected_schema,
    expected_config,
    expected_policy,
):
    """Replay a native-complete generation, including semantic rejections."""
    archive = Path(archive)
    request_path = archive / "request.json"
    if not request_path.is_file():
        raise EvaluationError("model-call archive lacks request binding")
    request = read_json(request_path)
    schema_raw = (
        Path(expected_schema).read_bytes()
        if isinstance(expected_schema, (str, os.PathLike))
        else canonical(expected_schema)
    )
    prompt_raw = expected_prompt.encode("utf-8")
    policy = _normalize_policy(expected_policy, None)
    from .model import _api_schema

    generation_raw = canonical(_api_schema(json.loads(schema_raw)))
    expected = _request_record(
        expected_prompt,
        schema_raw,
        generation_raw,
        expected_config,
        policy,
        request.get("label"),
    )
    if request != expected:
        raise EvaluationError(
            "model-call request fingerprint or current evaluator changed"
        )
    if (archive / "prompt.txt").read_bytes() != prompt_raw:
        raise EvaluationError("archived model prompt changed")
    if (archive / "schema.json").read_bytes() != schema_raw:
        raise EvaluationError("archived model schema changed")
    if (archive / "generation-schema.json").read_bytes() != generation_raw:
        raise EvaluationError("archived generation schema changed")
    records = sorted(archive.glob("attempt-*.record.json"))
    if not records or len(records) > 1 + policy["max_transient_transport_retries"]:
        raise EvaluationError("model-call archive violates frozen attempt limit")
    raw = None
    record = None
    for number, record_path in enumerate(records, 1):
        attempt = read_json(record_path)
        if (
            attempt.get("archive_version") != MODEL_CALL_ARCHIVE_VERSION
            or attempt.get("attempt") != number
            or attempt.get("request_fingerprint_sha256")
            != request["request_fingerprint_sha256"]
            or attempt.get("config") != expected_config
            or attempt.get("execution_policy") != policy
            or attempt.get("timeout_seconds") != policy["timeout_seconds"]
        ):
            raise EvaluationError("saved model-call attempt binding changed")
        expected_files = _attempt_files(archive, number)
        if record_path != expected_files["record"]:
            raise EvaluationError("model-call attempt sequence changed")
        expected_command = _command(
            expected_config["codex"],
            expected_config["model"],
            expected_config["reasoning"],
            archive / "generation-schema.json",
            expected_files["output"],
        )
        if attempt.get("command") != expected_command:
            raise EvaluationError("saved model-call command changed")
        attempt_raw = {}
        for key in ("stdout", "stderr", "output"):
            item = attempt.get("files", {}).get(key, {})
            relative = item.get("path", "")
            if not isinstance(relative, str) or Path(relative).name != relative:
                raise EvaluationError("saved model-call file reference is unsafe")
            path = archive / relative
            if (
                path != expected_files[key]
                or not path.is_file()
                or sha(path.read_bytes()) != item.get("sha256")
            ):
                raise EvaluationError(f"saved model-call {key} bytes changed")
            attempt_raw[key] = path.read_bytes()
        if number < len(records) and (
            attempt.get("failure_class") != "transient-transport"
            or attempt.get("timed_out") is not False
            or not _transient_transport_failure(
                attempt_raw["stdout"],
                attempt_raw["stderr"],
                attempt.get("returncode"),
            )
        ):
            raise EvaluationError("saved model-call contains an unauthorized retry")
        record = attempt
        raw = attempt_raw
    assert record is not None and raw is not None
    if record.get("generation_status") != "completed":
        raise EvaluationError("saved model generation is incomplete or failed")
    files = record.get("files", {})
    native = _completed_agent_json(raw["stdout"])
    try:
        output = json.loads(raw["output"])
    except ValueError as exc:
        raise EvaluationError("saved model output is not JSON") from exc
    if canonical(native) != canonical(output):
        raise EvaluationError("saved output differs from native completed agent JSON")
    _validate_local_schema(output, json.loads(schema_raw))
    return output, {
        "execution_status": "native-replayed",
        "reused_completed_generation": False,
        "call_archive": str(archive.resolve()),
        "request_fingerprint_sha256": request["request_fingerprint_sha256"],
        "attempt": record["attempt"],
        "attempt_record_sha256": sha(records[-1].read_bytes()),
        "model": expected_config["model"],
        "reasoning": expected_config["reasoning"],
        "codex_executable_sha256": expected_config["codex_executable_sha256"],
        "schema_sha256": request["schema_sha256"],
        "generation_schema_sha256": request["generation_schema_sha256"],
        "prompt_sha256": request["prompt_sha256"],
        "output_sha256": files["output"]["sha256"],
        "stdout_sha256": files["stdout"]["sha256"],
        "stderr_sha256": files["stderr"]["sha256"],
        "execution_policy": policy,
        "config": expected_config,
        "semantic_status": record.get("semantic_status"),
    }


def verify_model_call_archive(
    archive,
    *,
    expected_prompt,
    expected_schema,
    expected_config,
    expected_policy,
    semantic_validator=None,
):
    """Verify that a native-complete generation is semantically reusable."""
    if semantic_validator is None:
        raise EvaluationError("verified model-call reuse requires a semantic validator")
    output, provenance = replay_native_model_call_archive(
        archive,
        expected_prompt=expected_prompt,
        expected_schema=expected_schema,
        expected_config=expected_config,
        expected_policy=expected_policy,
    )
    _validate_semantics(output, semantic_validator)
    provenance.update(
        {"execution_status": "reused", "reused_completed_generation": True}
    )
    return output, provenance


def call_model_v31(
    prompt,
    schema_path,
    output_dir,
    label,
    *,
    codex,
    evaluator_home,
    model,
    reasoning,
    timeout,
    execution_policy,
    resume_verified,
    semantic_validator,
    api_schema,
):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{label}.model-call"
    policy = _normalize_policy(execution_policy, timeout)
    config = _request_config(codex, evaluator_home, model, reasoning)
    schema_raw = Path(schema_path).read_bytes()
    generation_raw = canonical(api_schema(json.loads(schema_raw)))
    request = _request_record(prompt, schema_raw, generation_raw, config, policy, label)
    if archive.exists() or any(
        (output_dir / name).exists()
        for name in (f"{label}.json", f"{label}.jsonl", f"{label}.stderr.txt")
    ):
        if not resume_verified:
            raise EvaluationError(f"{label} already attempted; inspect saved evidence")
        return verify_model_call_archive(
            archive,
            expected_prompt=prompt,
            expected_schema=schema_path,
            expected_config=config,
            expected_policy=policy,
            semantic_validator=semantic_validator,
        )
    archive.mkdir(parents=True)
    _write_new(archive / "prompt.txt", prompt.encode("utf-8"))
    _write_new(archive / "schema.json", schema_raw)
    _write_new(archive / "generation-schema.json", generation_raw)
    _json_new(archive / "request.json", request)
    attempts = policy["max_transient_transport_retries"] + 1
    for number in range(1, attempts + 1):
        files = _attempt_files(archive, number)
        command = _command(
            config["codex"],
            model,
            reasoning,
            archive / "generation-schema.json",
            files["output"],
        )
        started_at = _utc_now()
        started = time.monotonic()
        stdout = b""
        stderr = b""
        returncode = None
        timed_out = False
        spawn_error = None
        with tempfile.TemporaryDirectory(prefix="stage1-evaluator-") as scratch:
            try:
                completed = subprocess.run(
                    command,
                    input=prompt.encode("utf-8"),
                    capture_output=True,
                    cwd=scratch,
                    env=dict(os.environ, CODEX_HOME=config["evaluator_home"]),
                    timeout=policy["timeout_seconds"],
                    check=False,
                )
                stdout = completed.stdout or b""
                stderr = completed.stderr or b""
                returncode = completed.returncode
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout or b""
                stderr = exc.stderr or b""
                timed_out = True
            except OSError as exc:
                stderr = str(exc).encode("utf-8", errors="replace")
                spawn_error = exc
        output = files["output"].read_bytes() if files["output"].is_file() else b""
        if files["output"].is_file():
            files["output"].unlink()
        status = "failed"
        generation_status = "failed"
        semantic_status = "not-run"
        error = None
        failure_detail = None
        if timed_out:
            error = "timeout"
            failure_detail = "subprocess timeout"
        elif spawn_error is not None:
            error = "spawn"
            failure_detail = str(spawn_error)
        elif returncode:
            error = (
                "transient-transport"
                if _transient_transport_failure(stdout, stderr, returncode)
                else "process"
            )
            failure_detail = stderr.decode("utf-8", errors="replace")[:2000]
        else:
            try:
                native = _completed_agent_json(stdout)
                result = json.loads(output)
                if canonical(native) != canonical(result):
                    raise EvaluationError(
                        "model output differs from native completed agent JSON"
                    )
                _validate_local_schema(result, json.loads(schema_raw))
                generation_status = "completed"
                if semantic_validator is None:
                    semantic_status = "not-requested"
                    status = "completed"
                else:
                    _validate_semantics(result, semantic_validator)
                    semantic_status = "accepted"
                    status = "completed"
            except (EvaluationError, ValueError) as exc:
                error = "invalid-output"
                if "semantic validation" in str(exc):
                    error = "semantic-mismatch"
                    semantic_status = "rejected"
                    status = "native-completed"
                    generation_status = "completed"
                elif "local schema validation" in str(exc):
                    error = "schema-mismatch"
                failure_detail = str(exc)
        record = {
            "archive_version": MODEL_CALL_ARCHIVE_VERSION,
            "attempt": number,
            "request_fingerprint_sha256": request["request_fingerprint_sha256"],
            "command": command,
            "config": config,
            "execution_policy": policy,
            "started_at": started_at,
            "ended_at": _utc_now(),
            "runtime_seconds": round(time.monotonic() - started, 6),
            "timeout_seconds": policy["timeout_seconds"],
            "returncode": returncode,
            "timed_out": timed_out,
            "status": status,
            "generation_status": generation_status,
            "semantic_status": semantic_status,
            "failure_class": error,
            "failure_detail": failure_detail,
        }
        _save_attempt(files, stdout, stderr, output, record)
        if status == "completed":
            _write_new(output_dir / f"{label}.json", output)
            _write_new(output_dir / f"{label}.jsonl", stdout)
            _write_new(output_dir / f"{label}.stderr.txt", stderr)
            if semantic_validator is None:
                verified, provenance = replay_native_model_call_archive(
                    archive,
                    expected_prompt=prompt,
                    expected_schema=schema_path,
                    expected_config=config,
                    expected_policy=policy,
                )
            else:
                verified, provenance = verify_model_call_archive(
                    archive,
                    expected_prompt=prompt,
                    expected_schema=schema_path,
                    expected_config=config,
                    expected_policy=policy,
                    semantic_validator=semantic_validator,
                )
            provenance.update(
                {
                    "execution_status": "executed",
                    "reused_completed_generation": False,
                }
            )
            return verified, provenance
        if error != "transient-transport" or number == attempts:
            if timed_out:
                raise EvaluationError(f"{label} timed out; raw attempt retained")
            raise EvaluationError(
                f"{label} model invocation failed ({error}); raw attempt retained"
            )
    raise AssertionError("unreachable")

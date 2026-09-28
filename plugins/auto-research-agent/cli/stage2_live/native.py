"""Generic, fail-closed capture for native Codex Stage 2 subject runs.

The subject keeps Codex's native tools.  This module records host-observable
process evidence; it does not claim to attest provider-side execution.
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import subprocess


SUBJECT_EXECUTION_POLICY = {"sandbox": "workspace-write", "network_access": True}
SUBJECT_SANDBOX_ARGS = [
    "--sandbox",
    "workspace-write",
    "-c",
    "sandbox_workspace_write.network_access=true",
]


class CaptureError(ValueError):
    """A frozen binding or capture invariant was not satisfied."""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _normal_path(path):
    return Path(path).resolve()


def _assert_separate(*paths):
    resolved = [_normal_path(path) for path in paths]
    for index, left in enumerate(resolved):
        for right in resolved[index + 1 :]:
            if (
                left == right
                or left.is_relative_to(right)
                or right.is_relative_to(left)
            ):
                raise CaptureError("CODEX_HOME, workspace, and output must be separate")


def _tree_inventory(root):
    root = _normal_path(root)
    if not root.is_dir():
        raise CaptureError(f"bound directory is missing: {root}")
    inventory = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise CaptureError(f"bound tree contains a symlink: {path}")
        if path.is_file():
            inventory[path.relative_to(root).as_posix()] = sha256(path.read_bytes())
    return inventory


def _inventory_sha(inventory):
    rows = [f"{name}\0{digest}".encode() for name, digest in sorted(inventory.items())]
    return sha256(b"\n".join(rows))


def _path_binding(path):
    path = _normal_path(path)
    if path.is_symlink():
        raise CaptureError(f"bound path is a symlink: {path}")
    if path.is_file():
        return {
            "path": str(path),
            "kind": "file",
            "sha256": sha256(path.read_bytes()),
        }
    if path.is_dir():
        inventory = _tree_inventory(path)
        return {
            "path": str(path),
            "kind": "directory",
            "sha256": _inventory_sha(inventory),
            "files": inventory,
        }
    raise CaptureError(f"bound path is missing: {path}")


def _safe_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise CaptureError(f"invalid binding name: {name!r}")
    return name


def _bindings(values):
    if not isinstance(values, dict):
        raise CaptureError("input/config bindings must be dictionaries")
    return {
        _safe_name(name): _path_binding(path) for name, path in sorted(values.items())
    }


def _copy_binding(source, destination):
    source = _normal_path(source)
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return
    destination.mkdir(parents=True, exist_ok=True)
    for relative in _tree_inventory(source):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)


def _runtime_tree_sha(root):
    return _inventory_sha(_tree_inventory(root))


def codex_runtime_sha(codex):
    """Bind the standalone native executable; reject indirect script launchers."""
    launcher = _normal_path(codex)
    if not launcher.is_file():
        raise CaptureError("Codex launcher is missing")
    raw = launcher.read_bytes()
    if launcher.suffix.lower() in {
        ".ps1",
        ".cmd",
        ".bat",
        ".js",
        ".sh",
    } or raw.startswith(b"#!"):
        raise CaptureError(
            "use the standalone Codex binary; indirect script launchers are unsupported"
        )
    return sha256(raw)


def _prompt_bytes(prompt):
    if isinstance(prompt, bytes):
        return prompt
    if isinstance(prompt, str):
        return prompt.encode("utf-8")
    raise CaptureError("prompt must be exact str or bytes")


def _events(raw):
    parsed = []
    try:
        for line in raw.splitlines():
            if line.strip():
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise CaptureError("Codex JSONL event must be an object")
                if "item" in event and not isinstance(event["item"], dict):
                    raise CaptureError("Codex JSONL item must be an object")
                parsed.append(event)
    except (UnicodeDecodeError, ValueError) as error:
        raise CaptureError("Codex stdout is not valid JSONL") from error
    return parsed


def _event_summary(raw):
    try:
        events = _events(raw)
    except CaptureError:
        return {
            "status": "failed",
            "thread_id": None,
            "usage": None,
            "tool_events": [],
            "final_output": None,
            "parse_error": "invalid-jsonl",
        }
    started = [event for event in events if event.get("type") == "thread.started"]
    completed = [event for event in events if event.get("type") == "turn.completed"]
    failures = [
        event for event in events if event.get("type") in {"turn.failed", "error"}
    ]
    rerouted = any(
        event.get("type") in {"model.rerouted", "model_rerouted", "modelRerouted"}
        for event in events
    )
    usage = completed[0].get("usage") if len(completed) == 1 else None
    messages = [
        event.get("item", {}).get("text")
        for event in events
        if event.get("type") == "item.completed"
        and event.get("item", {}).get("type") == "agent_message"
        and isinstance(event.get("item", {}).get("text"), str)
    ]
    tools = []
    for event in events:
        item = event.get("item", {})
        item_type = item.get("type")
        if event.get("type") == "item.completed" and item_type not in {
            None,
            "agent_message",
            "reasoning",
        }:
            tools.append(
                {
                    key: item.get(key)
                    for key in (
                        "id",
                        "type",
                        "status",
                        "name",
                        "server",
                        "tool",
                        "query",
                        "queries",
                        "arguments",
                    )
                    if key in item
                }
            )
    structurally_complete = (
        len(started) == 1
        and len(completed) == 1
        and not failures
        and not rerouted
        and isinstance(usage, dict)
        and bool(messages)
    )
    return {
        "status": "complete"
        if structurally_complete
        else "failed"
        if failures
        else "incomplete",
        "thread_id": started[0].get("thread_id") if len(started) == 1 else None,
        "usage": usage,
        "tool_events": tools,
        "final_output": messages[-1] if messages else None,
        "parse_error": None,
    }


def _output_inventory(output):
    output = _normal_path(output)
    return {
        path.relative_to(output).as_posix(): sha256(path.read_bytes())
        for path in sorted(output.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file() and path.name not in {"run.json", "run.json.tmp"}
    }


def _record_receipt(record_path):
    return sha256(Path(record_path).read_bytes())


def _validate_receipt(receipt):
    if not isinstance(receipt, str) or not re.fullmatch(r"[0-9a-f]{64}", receipt):
        raise CaptureError(
            "an externally retained run-record SHA-256 receipt is required"
        )


def _same_binding_bytes(actual, expected):
    keys = {"kind", "sha256"}
    if expected["kind"] == "directory":
        keys.add("files")
    return all(actual.get(key) == expected.get(key) for key in keys)


def _request_binding(
    codex,
    codex_home,
    workspace,
    prompt_bytes,
    model,
    reasoning,
    input_bindings,
    config_bindings,
    policy_bindings,
):
    profile_config = _normal_path(codex_home) / "config.toml"
    profile_binding = (
        _path_binding(profile_config) if profile_config.is_file() else None
    )
    return {
        "codex": str(_normal_path(codex)),
        "codex_runtime_sha256": codex_runtime_sha(codex),
        "codex_home": str(_normal_path(codex_home)),
        "codex_profile_config": profile_binding,
        "workspace": str(_normal_path(workspace)),
        "workspace_start": _path_binding(workspace),
        "prompt_sha256": sha256(prompt_bytes),
        "model": model,
        "reasoning": reasoning,
        "input_bindings": _bindings(input_bindings),
        "config_bindings": _bindings(config_bindings),
        "policy_bindings": policy_bindings,
    }


def _stable_request(binding):
    value = dict(binding)
    value.pop("workspace_start")
    return value


def _archive_start(output, binding, prompt_bytes):
    archive = output / "archive"
    (archive / "prompt.bin").parent.mkdir(parents=True, exist_ok=True)
    (archive / "prompt.bin").write_bytes(prompt_bytes)
    _copy_binding(binding["workspace"], archive / "workspace-start")
    profile = binding.get("codex_profile_config")
    if profile:
        _copy_binding(profile["path"], archive / "profile-config.toml")
    for category in ("input_bindings", "config_bindings"):
        for name, item in binding[category].items():
            _copy_binding(item["path"], archive / category / name)


def _expected_command(record, output):
    stable = record["stable_request_binding"]
    return [
        stable["codex"],
        "exec",
        *SUBJECT_SANDBOX_ARGS,
        "--json",
        "-m",
        stable["model"],
        "-c",
        f"model_reasoning_effort={json.dumps(stable['reasoning'])}",
        "-C",
        stable["workspace"],
        "--skip-git-repo-check",
        "-o",
        str(output / "final.txt"),
        "-",
    ]


def _verify_archives(output, record):
    actual = _output_inventory(output)
    if actual != record.get("archived_files"):
        raise CaptureError("capture archive inventory or byte hash differs")
    archive = output / "archive"
    stable = record["stable_request_binding"]
    if sha256((archive / "prompt.bin").read_bytes()) != stable["prompt_sha256"]:
        raise CaptureError("archived prompt differs from frozen binding")
    if not _same_binding_bytes(
        _path_binding(archive / "workspace-start"), record["workspace_start"]
    ):
        raise CaptureError("archived starting workspace differs from frozen binding")
    profile = stable.get("codex_profile_config")
    if profile and not _same_binding_bytes(
        _path_binding(archive / "profile-config.toml"), profile
    ):
        raise CaptureError("archived profile config differs from frozen binding")
    for category in ("input_bindings", "config_bindings"):
        for name, expected in stable[category].items():
            if not _same_binding_bytes(
                _path_binding(archive / category / name), expected
            ):
                raise CaptureError(f"archived {category} bytes differ: {name}")
    if not _same_binding_bytes(
        _path_binding(archive / "workspace-end"), record["workspace_end"]
    ):
        raise CaptureError("archived final workspace differs from frozen end binding")
    summary = _event_summary((output / "stdout.jsonl").read_bytes())
    recorded = record.get("event_summary")
    if summary != recorded:
        raise CaptureError("native transcript differs from recorded event summary")
    if summary["status"] != "complete" or not isinstance(summary["usage"], dict):
        raise CaptureError("native transcript is not one completed turn with usage")
    if record.get("actual_completed_turn_usage") != summary["usage"]:
        raise CaptureError("duplicated completed-turn usage differs from transcript")
    final_bytes = (output / "final.txt").read_bytes()
    try:
        saved_final = final_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CaptureError("saved final output is not UTF-8") from error
    if saved_final.rstrip("\r\n") != summary["final_output"]:
        raise CaptureError("saved final output differs from native transcript")
    return summary["final_output"]


def verify_capture(
    output_dir, record_sha256_receipt, *, allow_injected_test_capture=False
):
    """Verify archived bytes and reconstruct the final output from JSONL."""
    output = _normal_path(output_dir)
    _validate_receipt(record_sha256_receipt)
    record_path = output / "run.json"
    if _record_receipt(record_path) != record_sha256_receipt:
        raise CaptureError("run-record SHA-256 receipt differs")
    record = _read_json(record_path)
    if (
        record.get("status") != "complete"
        or record.get("exit_code") != 0
        or record.get("exception") is not None
    ):
        raise CaptureError("only a completed native capture is resumable")
    if record.get("capture_mode") not in {
        "authentic-subprocess",
        "injected-test-adapter",
    }:
        raise CaptureError("capture mode is invalid")
    if (
        record["capture_mode"] == "injected-test-adapter"
        and not allow_injected_test_capture
    ):
        raise CaptureError("injected test capture cannot be verified as authentic")
    if record.get("command") != _expected_command(record, output):
        raise CaptureError("recorded command differs from immutable inputs")
    try:
        started = datetime.fromisoformat(record["started_at"])
        ended = datetime.fromisoformat(record["ended_at"])
    except (KeyError, TypeError, ValueError) as error:
        raise CaptureError("capture UTC times are invalid") from error
    if (
        started.tzinfo is None
        or ended.tzinfo is None
        or started.utcoffset() != timezone.utc.utcoffset(started)
        or ended.utcoffset() != timezone.utc.utcoffset(ended)
        or ended < started
    ):
        raise CaptureError("capture UTC times are invalid")
    reconstructed = _verify_archives(output, record)
    return record, reconstructed


def capture_native(
    *,
    codex,
    codex_home,
    workspace,
    prompt,
    model,
    reasoning,
    input_bindings,
    config_bindings,
    policy_bindings,
    output_dir,
    resume=False,
    process_runner=None,
    record_sha256_receipt=None,
):
    """Run once, or verify and replay a completed capture without re-execution.

    ``process_runner`` is solely an injected test seam. Its use is recorded and
    can never be represented as an authentic native subprocess capture.
    """
    codex_home, workspace, output = map(
        _normal_path, (codex_home, workspace, output_dir)
    )
    _assert_separate(codex_home, workspace, output)
    if not codex_home.is_dir() or not workspace.is_dir():
        raise CaptureError("isolated CODEX_HOME and workspace must already exist")
    if policy_bindings != SUBJECT_EXECUTION_POLICY:
        raise CaptureError(
            "Stage 2 subject policy must preserve workspace-write/network access"
        )
    if (
        not isinstance(model, str)
        or not model
        or not isinstance(reasoning, str)
        or not reasoning
    ):
        raise CaptureError("exact model and reasoning are required")
    prompt_bytes = _prompt_bytes(prompt)
    current = _request_binding(
        codex,
        codex_home,
        workspace,
        prompt_bytes,
        model,
        reasoning,
        input_bindings,
        config_bindings,
        policy_bindings,
    )
    if output.exists():
        if not resume:
            raise CaptureError("capture output already exists")
        record, reconstructed = verify_capture(
            output,
            record_sha256_receipt,
            allow_injected_test_capture=process_runner is not None,
        )
        if _stable_request(current) != record.get("stable_request_binding"):
            raise CaptureError("capture binding changed before verified resume")
        if _path_binding(workspace) != record.get("workspace_end"):
            raise CaptureError("workspace changed after completed capture")
        replay = dict(record)
        replay["reconstructed_final_output"] = reconstructed
        replay["resume_action"] = "verified-replay-no-execution"
        replay["record_sha256_receipt"] = record_sha256_receipt
        return replay
    if resume:
        raise CaptureError("resume requires an existing completed capture")

    output.mkdir(parents=True)
    _archive_start(output, current, prompt_bytes)
    final_path = output / "final.txt"
    command = _expected_command(
        {"stable_request_binding": _stable_request(current)}, output
    )
    injected = process_runner is not None
    started = _utc_now()
    exception = None
    try:
        if injected:
            result = process_runner(
                command,
                input=prompt_bytes,
                env=dict(os.environ, CODEX_HOME=str(codex_home)),
                cwd=workspace,
                capture_output=True,
            )
            stdout = (
                result.stdout
                if isinstance(result.stdout, bytes)
                else result.stdout.encode()
            )
            stderr = (
                result.stderr
                if isinstance(result.stderr, bytes)
                else result.stderr.encode()
            )
            with (output / "stdout.jsonl").open("xb") as handle:
                handle.write(stdout)
            with (output / "stderr.txt").open("xb") as handle:
                handle.write(stderr)
            exit_code = result.returncode
        else:
            with (
                (output / "stdout.jsonl").open("xb") as stdout_handle,
                (output / "stderr.txt").open("xb") as stderr_handle,
            ):
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    env=dict(os.environ, CODEX_HOME=str(codex_home)),
                    cwd=workspace,
                )
                process.communicate(input=prompt_bytes)
                exit_code = process.returncode
            stdout = (output / "stdout.jsonl").read_bytes()
            stderr = (output / "stderr.txt").read_bytes()
    except (
        BaseException
    ) as error:  # preserve evidence from an interrupted single attempt
        stdout = getattr(error, "stdout", None) or b""
        stderr = getattr(error, "stderr", None) or str(error).encode("utf-8", "replace")
        exit_code = None
        exception = {"type": type(error).__name__, "message": str(error)}
        for path, data in (
            (output / "stdout.jsonl", stdout),
            (output / "stderr.txt", stderr),
        ):
            if not path.exists():
                with path.open("xb") as handle:
                    handle.write(data)
    ended = _utc_now()
    stdout = (output / "stdout.jsonl").read_bytes()
    stderr = (output / "stderr.txt").read_bytes()
    summary = _event_summary(stdout)
    status = summary["status"]
    if exit_code != 0 or exception is not None:
        status = "failed"
    if status == "complete" and not final_path.is_file():
        status = "incomplete"
    if status == "complete":
        try:
            if (
                final_path.read_text(encoding="utf-8").rstrip("\r\n")
                != summary["final_output"]
            ):
                status = "incomplete"
        except UnicodeDecodeError:
            status = "incomplete"
    try:
        workspace_end = _path_binding(workspace)
        _copy_binding(workspace, output / "archive/workspace-end")
    except (CaptureError, OSError) as error:
        status = "failed"
        workspace_end = None
        if exception is None:
            exception = {
                "type": type(error).__name__,
                "message": f"final workspace archive failed: {error}",
            }
    sessions = codex_home / "sessions"
    session_state = "missing"
    if sessions.is_dir():
        try:
            _copy_binding(sessions, output / "archive/native-sessions")
            session_state = "saved"
        except (CaptureError, OSError) as error:
            status = "failed"
            session_state = "archive-failed"
            if exception is None:
                exception = {"type": type(error).__name__, "message": str(error)}
    record = {
        "kind": "Stage2NativeCapture",
        "schema_version": "1.0.0",
        "status": status,
        "command": command,
        "started_at": started,
        "ended_at": ended,
        "exit_code": exit_code,
        "exception": exception,
        "stable_request_binding": _stable_request(current),
        "workspace_start": current["workspace_start"],
        "workspace_end": workspace_end,
        "native_session_records": session_state,
        "event_summary": summary,
        "actual_completed_turn_usage": summary["usage"],
        "cost": {
            "amount": None,
            "currency": None,
            "state": "unknown-not-reported-by-codex-cli",
        },
        "capture_mode": "injected-test-adapter" if injected else "authentic-subprocess",
        "evidence_class": "synthetic-test-only" if injected else "host-native-capture",
        "host_observation": {
            "observed": [
                "launcher/runtime bytes",
                "command",
                "process exit",
                "stdout JSONL",
                "stderr",
                "final output",
                "workspace bytes",
                "UTC host times",
            ],
            "not_attested": [
                "provider-side execution",
                "network packet completeness",
                "remote identity",
                "billing beyond CLI-reported usage",
            ],
        },
    }
    record["archived_files"] = _output_inventory(output)
    _write_json(output / "run.json", record)
    receipt = _record_receipt(output / "run.json")
    if status == "complete":
        verify_capture(output, receipt, allow_injected_test_capture=injected)
    result = dict(record)
    result["record_sha256_receipt"] = receipt
    return result

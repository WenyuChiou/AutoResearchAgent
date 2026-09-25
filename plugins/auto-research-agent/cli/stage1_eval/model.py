"""Tool-free Codex invocation with raw logs retained for evaluator provenance."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from .common import EvaluationError, read_json, sha
from .runtime import executable_sha256

DISABLED = (
    "shell_tool",
    "unified_exec",
    "code_mode_host",
    "computer_use",
    "browser_use",
    "apps",
    "plugins",
    "view_image",
    "multi_agent",
    "skill_search",
    "hooks",
)


def require_tool_free_events(raw):
    """Reject evaluator tool actions without importing the legacy holdout path."""
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
    for event in events:
        if not event.get("type", "").startswith("item."):
            continue
        item = event.get("item", {})
        if item.get("type") in {"agent_message", "reasoning"}:
            continue
        if item.get("type") == "error" and any(
            item.get("message", "").startswith(prefix) for prefix in benign
        ):
            continue
        raise EvaluationError("evaluator transcript contains a tool or error event")


def _api_schema(value):
    """Keep a strict generation shape; enforce richer local constraints afterward."""
    unsupported = {
        "$schema",
        "$id",
        "title",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minLength",
        "maxLength",
        "pattern",
        "minimum",
        "maximum",
        "format",
    }
    if isinstance(value, list):
        return [_api_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    cleaned = {}
    for key, item in value.items():
        if key in unsupported:
            continue
        if key in {"properties", "$defs", "definitions"} and isinstance(item, dict):
            # Keys here are user-defined field/definition names, not schema
            # keywords; `title` is a valid property in a citation record.
            cleaned[key] = {name: _api_schema(child) for name, child in item.items()}
        else:
            cleaned[key] = _api_schema(item)
    if "const" in cleaned:
        cleaned["enum"] = [cleaned.pop("const")]
    return cleaned


def call_model(
    prompt,
    schema_path,
    output_dir,
    label,
    *,
    codex,
    evaluator_home,
    model,
    reasoning,
    timeout=300,
):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / f"{label}.json"
    stdout_path = output_dir / f"{label}.jsonl"
    stderr_path = output_dir / f"{label}.stderr.txt"
    if any(path.exists() for path in (result_path, stdout_path, stderr_path)):
        raise EvaluationError(f"{label} already attempted; inspect saved evidence")
    home = Path(evaluator_home).resolve()
    if not home.is_dir():
        raise EvaluationError("evaluator CODEX_HOME does not exist")
    codex_sha = executable_sha256(codex)
    generation_schema = output_dir / f"{label}.generation-schema.json"
    generation_schema.write_text(
        json.dumps(_api_schema(read_json(schema_path)), sort_keys=True),
        encoding="utf-8",
    )
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
        str(result_path),
        "-",
    ]
    for name in DISABLED:
        command[3:3] = ["--disable", name]
    env = dict(os.environ, CODEX_HOME=str(home))
    with tempfile.TemporaryDirectory(prefix="stage1-evaluator-") as scratch:
        try:
            completed = subprocess.run(
                command,
                input=prompt.encode("utf-8"),
                capture_output=True,
                cwd=scratch,
                env=env,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout_path.write_bytes(exc.stdout or b"")
            stderr_path.write_bytes(exc.stderr or b"")
            raise EvaluationError(f"{label} timed out; raw logs retained") from exc
    stdout_path.write_bytes(completed.stdout)
    stderr_path.write_bytes(completed.stderr)
    try:
        require_tool_free_events(completed.stdout)
    except Exception as exc:
        raise EvaluationError(f"{label} used a tool or did not complete") from exc
    if completed.returncode or not result_path.is_file():
        raise EvaluationError(f"{label} model invocation failed; raw logs retained")
    result = read_json(result_path)
    return result, {
        "model": model,
        "reasoning": reasoning,
        "codex_executable_sha256": codex_sha,
        "schema_sha256": sha(Path(schema_path).read_bytes()),
        "generation_schema_sha256": sha(generation_schema.read_bytes()),
        "prompt_sha256": sha(prompt.encode("utf-8")),
        "output_sha256": sha(result_path.read_bytes()),
        "stdout_sha256": sha(stdout_path.read_bytes()),
        "stderr_sha256": sha(stderr_path.read_bytes()),
    }

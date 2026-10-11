"""Local evidence driver: raw source inventory, actual child exit and logs."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

root = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=False)
plugin = root / "plugins/auto-research-agent"
tests = [
    "project_stage1_query_cases",
    "project_query_history_cases",
    "project_stage1_query_http_cases",
    "test_capability_metric_map",
    "test_workspace_project_host",
    "test_research_workspace_native_binding.WorkspaceNativeBindingTests.test_runtime_bytes_bound_including_added_cached_bytecode",
    "test_research_workspace_native_binding.WorkspaceNativeBindingTests.test_dependency_sha_bound_and_changed_checkout_rejected",
    "test_research_workspace_native_transport.NativeTransportTests.test_resume_no_reexecution_after_disconnect_timeout_or_partial_write",
]
if len(sys.argv) > 3:
    tests = sys.argv[3:]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def inventory():
    result = {}
    for directory, suffixes in (
        ("cli", {".py", ".html", ".js", ".css"}),
        ("tests", {".py", ".cjs"}),
        ("schemas", {".json"}),
    ):
        for path in (plugin / directory).rglob("*"):
            if path.is_file() and path.suffix in suffixes:
                result[path.relative_to(root).as_posix()] = digest(path)
    metric = plugin / "evals/capability-metric-map.v3.json"
    result[metric.relative_to(root).as_posix()] = digest(metric)
    return dict(sorted(result.items()))

command = [sys.executable, "-I", "-B", "-X", "utf8", str(plugin / "tests/planned_query_raw_runner.py")]
for selector in tests:
    command.extend(["--test", selector])
temp = Path("D:/Codex_Learning/harness_building/_temp/fq10")
temp.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp), PYTHONDONTWRITEBYTECODE="1")
before = inventory()
started = datetime.now(timezone.utc).isoformat()
clock = time.monotonic()
timeout = False
with (out / "stdout.log").open("wb") as stdout, (out / "stderr.log").open("wb") as stderr:
    try:
        result = subprocess.run(command, cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, timeout=480, check=False)
        code = result.returncode
    except subprocess.TimeoutExpired:
        timeout, code = True, 124
elapsed = time.monotonic() - clock
after = inventory()
log = (out / "stderr.log").read_text(encoding="utf-8", errors="replace")
summaries = re.findall(r"Ran (\d+) tests? in ([\d.]+)s", log)
receipt = {
    "schema_version": "1.0.0", "kind": "OfflineFocusedTestReceipt",
    "started_at": started, "ended_at": datetime.now(timezone.utc).isoformat(),
    "command": command, "cwd": str(root), "modules": tests,
    "exit_code": code, "timed_out": timeout, "elapsed_seconds": elapsed,
    "test_summaries": summaries, "source_before": before, "source_after": after,
    "source_inventory_equal": before == after,
    "environment": {key: env[key] for key in ("TEMP", "TMP", "TMPDIR", "PYTHONDONTWRITEBYTECODE")},
    "logs": {name: digest(out / name) for name in ("stdout.log", "stderr.log")},
    "scope": "Real temporary HTTP/SQLite/Core/runner; external probe/backend and model replaced by fixtures. No actual new search/source/native/model/research/scoring.",
}
(out / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({key: receipt[key] for key in ("exit_code", "timed_out", "elapsed_seconds", "test_summaries", "source_inventory_equal", "logs")}, indent=2))
if before != after:
    sys.exit(125)
sys.exit(code)

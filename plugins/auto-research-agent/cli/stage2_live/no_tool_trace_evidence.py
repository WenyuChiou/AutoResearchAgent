from hashlib import sha256
import json

from stage2_common import Stage2Error, canonical_hash

from .judge_trace_replay import _path
from .trace_files import _load_inventory, _ref
from .trace_observation import inspect_native_trace
from .trace_parsing import _tools


_USAGE = "input_tokens cached_input_tokens cache_write_input_tokens output_tokens reasoning_output_tokens total_tokens".split()
_CONFIG = {"model", "reasoning", "sandbox_mode", "approval_policy"}


def _fail(reason):
    raise Stage2Error("no-tool-trace-evidence-" + reason)


def _object(path, reason):
    try:
        value = json.loads(_path(path).read_bytes())
    except (UnicodeDecodeError, ValueError) as error:
        raise Stage2Error(f"no-tool-trace-evidence-{reason}") from error
    if not isinstance(value, dict):
        _fail(reason)
    return value


def _attempts(provenance, expected):
    if not isinstance(provenance, dict):
        _fail("archive-provenance-invalid")
    archive = _path(provenance.get("call_archive"), directory=True)
    request = _object(archive / "request.json", "archive-request-invalid")
    config, fingerprint = (
        request.get("config"),
        request.get("request_fingerprint_sha256"),
    )
    if (
        provenance.get("request_fingerprint_sha256") != fingerprint
        or provenance.get("config") != config
        or provenance.get("execution_status")
        not in {"executed", "native-replayed", "reused"}
        or not isinstance(config, dict)
        or config.get("model") != expected["model"]
        or config.get("reasoning") != expected["reasoning"]
    ):
        _fail("archive-binding-mismatch")
    records = sorted(archive.glob("attempt-*.record.json"))
    stdout_files = sorted(archive.glob("attempt-*.stdout.jsonl"))
    if not records or len(records) != len(stdout_files):
        _fail("attempt-inventory-invalid")
    attempts = []
    for number, (record_path, stdout_path) in enumerate(zip(records, stdout_files), 1):
        stem = f"attempt-{number:02d}"
        if (
            record_path.name != stem + ".record.json"
            or stdout_path.name != stem + ".stdout.jsonl"
        ):
            _fail("attempt-inventory-invalid")
        record = _object(record_path, "attempt-record-invalid")
        stdout = stdout_path.read_bytes()
        if (
            record.get("attempt") != number
            or record.get("request_fingerprint_sha256") != fingerprint
            or record.get("config") != config
            or record.get("files", {}).get("stdout")
            != {"path": stdout_path.name, "sha256": sha256(stdout).hexdigest()}
        ):
            _fail("attempt-binding-mismatch")
        try:
            events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        except (UnicodeDecodeError, ValueError) as error:
            raise Stage2Error(
                "no-tool-trace-evidence-attempt-stdout-invalid"
            ) from error
        roots = [
            row.get("thread_id")
            for row in events
            if isinstance(row, dict) and row.get("type") == "thread.started"
        ]
        if len(roots) != 1 or not isinstance(roots[0], str) or not roots[0]:
            _fail("attempt-root-invalid")
        attempts.append((record, roots[0]))
    if len({root for _, root in attempts}) != len(attempts):
        _fail("attempt-root-duplicate")
    if (
        provenance.get("attempt") != len(attempts)
        or provenance.get("attempt_record_sha256")
        != sha256(records[-1].read_bytes()).hexdigest()
        or provenance.get("stdout_sha256")
        != sha256(stdout_files[-1].read_bytes()).hexdigest()
    ):
        _fail("authenticated-final-attempt-mismatch")
    return fingerprint, attempts


def _effective(raw, root):
    configs, models = [], []
    for line in raw["trace.jsonl"].splitlines():
        row = json.loads(line)
        payload = row.get("payload", {}) if isinstance(row, dict) else {}
        if (
            payload.get("type") == "protocol_event_observed"
            and payload.get("event_type") == "session_configured"
        ):
            _, value, _ = _ref(payload, "event_payload", raw)
            if isinstance(value, dict) and value.get("thread_id") == root:
                configs.append(value)
        if payload.get("type") == "inference_started" and row.get("thread_id") == root:
            _, request, _ = _ref(payload, "request_payload", raw)
            if not isinstance(request, dict) or not isinstance(
                request.get("model"), str
            ):
                _fail("inference-model-invalid")
            models.append(request["model"])
    if len(configs) != 1:
        _fail("effective-config-missing-or-duplicate")
    value, sandbox = configs[0], configs[0].get("sandbox_policy")
    return {
        "model": value.get("model"),
        "reasoning": value.get("reasoning_effort"),
        "sandbox_mode": sandbox.get("type") if isinstance(sandbox, dict) else sandbox,
        "approval_policy": value.get("approval_policy"),
    }, models


def _usage(observation):
    calls, total = observation.get("inferences"), {key: 0 for key in _USAGE}
    if not isinstance(calls, list):
        _fail("call-inventory-invalid")
    # The public observation exposes compaction totals without all six usage
    # fields. Keep the aggregate unknown rather than undercounting those calls.
    complete = (
        bool(calls)
        and not observation.get("counts", {}).get("compactions", 0)
        and not any(
            item in {"compaction-usage-missing", "compaction-accounting-unverified"}
            for item in observation.get("blockers", [])
        )
    )
    for call in calls:
        usage = call.get("token_usage") if isinstance(call, dict) else None
        if usage is None:
            complete = False
            continue
        if not isinstance(usage, dict) or any(
            type(usage.get(key)) is not int or usage[key] < 0 for key in _USAGE
        ):
            _fail("usage-invalid")
        for key in _USAGE:
            total[key] += usage[key]
    return total if complete else {key: None for key in _USAGE}


def _no_offered_tools(observation, raw):
    calls = observation.get("inferences")
    if not isinstance(calls, list):
        _fail("call-inventory-invalid")
    for call in calls:
        reference = call.get("request_ref") if isinstance(call, dict) else None
        if not isinstance(reference, str) or reference not in raw:
            _fail("offered-tools-unresolved")
        definitions = _tools(json.loads(raw[reference]))
        if definitions is None:
            offered = observation["threads"][0].get("offered_tools")
            if (
                call.get("tools_inherited") is not True
                or not isinstance(offered, dict)
                or offered.get("definitions") != []
            ):
                _fail("offered-tools-unresolved")
        elif definitions != []:
            _fail("offered-tools-nonempty")


def _attempt_terminal(observation, attempt, root):
    thread = observation["threads"][0]
    if thread.get("thread_id") != root or not isinstance(
        thread.get("terminal_status"), str
    ):
        _fail("attempt-terminal-unresolved")
    failed = attempt.get("generation_status") != "completed"
    terminal_failed = thread["terminal_status"] != "completed"
    lifecycle_failed = any(
        item == "rollout-not-completed"
        or item.startswith(("thread-not-completed:", "turn-not-completed:"))
        for item in observation["blockers"]
    )
    if failed != terminal_failed or (not failed and lifecycle_failed):
        _fail("attempt-trace-status-mismatch")
    return failed


def _verify_trace_evidence(
    archive_provenance,
    trace_root,
    seal_file,
    externally_retained_seal_sha256,
    *,
    expected_config,
    offered_tool_mode,
):
    """Verify raw traces only after canonical native archive authentication.

    This does not authenticate arbitrary provenance objects, dispatch calls,
    or attest formal role isolation. The caller retains the original seal.
    """
    if offered_tool_mode not in {"empty", "record"}:
        _fail("offered-tool-mode-invalid")
    if (
        not isinstance(expected_config, dict)
        or set(expected_config) != _CONFIG
        or expected_config.get("sandbox_mode") != "read-only"
        or expected_config.get("approval_policy") != "never"
    ):
        _fail("expected-config-invalid")
    fingerprint, attempts = _attempts(archive_provenance, expected_config)
    seal_path = _path(seal_file)
    if sha256(seal_path.read_bytes()).hexdigest() != externally_retained_seal_sha256:
        _fail("original-seal-mismatch")
    seal = _object(seal_path, "seal-invalid")
    if (
        set(seal)
        != {
            "kind",
            "schema_version",
            "request_fingerprint_sha256",
            "attempt_record_sha256",
            "stdout_sha256",
            "traces",
        }
        or seal.get("kind") != "Stage2NoToolTraceSeal"
        or seal.get("schema_version") != "1.0.0"
    ):
        _fail("seal-invalid")
    if (
        any(
            seal.get(key) != archive_provenance.get(key)
            for key in (
                "request_fingerprint_sha256",
                "attempt_record_sha256",
                "stdout_sha256",
            )
        )
        or seal["request_fingerprint_sha256"] != fingerprint
    ):
        _fail("seal-archive-binding-mismatch")
    traces, root_path = seal["traces"], _path(trace_root, directory=True)
    if (
        not isinstance(traces, dict)
        or len(traces) != len(attempts)
        or {path.name for path in root_path.iterdir()} != set(traces)
    ):
        _fail("trace-inventory-mismatch")
    reports, joined, aggregate = [], set(), {key: 0 for key in _USAGE}
    aggregate_complete = True
    attempts_by_root = {root: attempt for attempt, root in attempts}
    for name, inventory in sorted(traces.items()):
        if not isinstance(name, str) or not name.startswith("trace-"):
            _fail("trace-name-invalid")
        trace_dir = _path(root_path / name, directory=True)
        digest = canonical_hash(inventory)
        observation = inspect_native_trace(trace_dir, inventory, digest)
        actual_root = observation.get("root_thread_id")
        if actual_root not in attempts_by_root or actual_root in joined:
            _fail("foreign-or-duplicate-root")
        attempt = attempts_by_root[actual_root]
        joined.add(actual_root)
        raw = _load_inventory(trace_dir, inventory, digest)
        actual_config, models = _effective(raw, actual_root)
        if actual_config != expected_config or any(
            model != expected_config["model"] for model in models
        ):
            _fail("effective-config-mismatch")
        threads, counts, blockers = (
            observation.get("threads"),
            observation.get("counts"),
            observation.get("blockers"),
        )
        if not isinstance(threads, list) or len(threads) != 1:
            _fail("child-activity")
        if not isinstance(counts, dict) or counts.get("tool_calls") != 0:
            _fail("tool-activity")
        if not isinstance(blockers, list) or any(
            ("missing" in item or "incomplete" in item)
            and item != "compaction-usage-missing"
            for item in blockers
        ):
            _fail("trace-incomplete")
        if any(item.startswith("offered-tools-") for item in blockers):
            _fail("offered-tools-unresolved")
        if offered_tool_mode == "empty":
            _no_offered_tools(observation, raw)
            offered = None
        else:
            from .no_execution_trace_evidence import _offered_inventory

            offered = _offered_inventory(observation, raw)
        failed = _attempt_terminal(observation, attempt, actual_root)
        usage = _usage(observation)
        if any(value is None for value in usage.values()):
            aggregate_complete = False
        else:
            for key, value in usage.items():
                aggregate[key] += value
        report = {
            "attempt": attempt["attempt"],
            "thread_id": actual_root,
            "status": "failure" if failed else "completed",
            "error": attempt.get("failure_class") if failed else None,
            "calls": observation.get("inferences"),
            "usage": usage,
            "effective_config": actual_config,
        }
        if offered_tool_mode == "record":
            report["offered_tool_inventory"] = offered
        reports.append(report)
    result = {
        "kind": "Stage2NoToolTraceEvidence",
        "schema_version": "1.0.0",
        "verification_status": "verified",
        "matched_roots": sorted(joined),
        "attempts": reports,
        "token_usage_totals": aggregate
        if aggregate_complete
        else {key: None for key in _USAGE},
        "new_model_calls": 0,
        "new_tool_calls": 0,
        "resume_action": "verified-replay-no-execution",
        "original_seal_sha256": externally_retained_seal_sha256,
    }
    if offered_tool_mode == "record":
        result.update(
            kind="Stage2NoExecutionTraceEvidence",
            schema_version="1.0.0",
            execution_policy="no-executed-tools-v1",
            tool_calls_observed=0,
            child_threads_observed=0,
            tools_unavailable_attested=False,
            formal_isolation_attested=False,
        )
    return result


def verify_no_tool_trace_evidence(
    archive_provenance,
    trace_root,
    seal_file,
    externally_retained_seal_sha256,
    *,
    expected_config,
):
    """Retain the strict contract: every offered tool inventory must be empty."""
    return _verify_trace_evidence(
        archive_provenance,
        trace_root,
        seal_file,
        externally_retained_seal_sha256,
        expected_config=expected_config,
        offered_tool_mode="empty",
    )

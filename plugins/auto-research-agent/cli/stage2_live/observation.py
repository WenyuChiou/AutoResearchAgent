"""Observe supported app-server APIs without starting a model turn.

An app-server snapshot is not the offered tools of a later model request.
Keep that distinction explicit, including when every RPC succeeds.
"""

import json
import math
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time

from stage1_deliverable.common import DeliverableError, private_output
from .native import CaptureError, codex_runtime_sha, sha256, _utc_now
from .native_namespace import NativeNamespaceError, bind_namespace, wrap_namespace
from .trace_seal_io import SealDirectory


MAX_RPC_FRAME_BYTES = 64 * 1024 * 1024
MAX_RPC_STREAM_BYTES = 128 * 1024 * 1024
MAX_RPC_EVENTS = 2048


def _valid_rpc_timeout(value):
    return type(value) in {int, float} and 0 < value <= 600 and math.isfinite(value)


def _response_observed(item, reply):
    result = reply.get("result")
    if not isinstance(result, dict) or "error" in reply or "host_error" in reply:
        return False
    if any(
        result.get(k)
        for k in ("nextCursor", "next_cursor", "errors", "marketplaceLoadErrors")
    ):
        return False
    method = item["method"]
    if method == "config/read":
        return isinstance(result.get("config"), dict)
    if method == "skills/list":
        data = result.get("data")
        return isinstance(data, list) and all(
            isinstance(row, dict)
            and isinstance(row.get("skills"), list)
            and isinstance(row.get("errors"), list)
            and not row["errors"]
            for row in data
        )
    if method == "plugin/list":
        return isinstance(result.get("marketplaces"), list) and isinstance(
            result.get("marketplaceLoadErrors"), list
        )
    if method == "mcpServerStatus/list":
        return isinstance(result.get("data"), list)
    if method == "thread/read":
        return isinstance(result.get("thread"), dict) and (
            result["thread"].get("id") == item["params"]["threadId"]
        )
    return False


def _verify_transport(rows, events, raw_responses=None):
    if not isinstance(rows, list) or not isinstance(events, list):
        raise CaptureError("observation transport containers are malformed")
    expected = [row["request"] for row in rows]
    requests, responses = [], {}
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("payload"), dict):
            raise CaptureError("observation transport event is malformed")
        payload = event["payload"]
        if event.get("direction") == "request":
            requests.append(payload)
        elif event.get("direction") == "response":
            if "id" in payload:
                if payload["id"] in responses:
                    raise CaptureError("observation transport reply is duplicated")
                responses[payload["id"]] = payload
            elif not isinstance(payload.get("method"), str):
                raise CaptureError("observation transport notification is malformed")
        else:
            raise CaptureError("observation transport direction is malformed")
    if (
        len(requests) != len(expected) + 2
        or requests[0].get("method") != "initialize"
        or requests[0].get("id") != 0
        or requests[1] != {"method": "initialized"}
        or requests[2:] != expected
        or any(row["request"]["id"] != index for index, row in enumerate(rows, 1))
        or set(responses) - {0, *(row["request"]["id"] for row in rows)}
    ):
        raise CaptureError("observation transport contains unexpected requests")
    hello = responses.get(0)
    if not isinstance(hello, dict) or "error" in hello or "result" not in hello:
        raise CaptureError("observation transport initialization differs")
    for row in rows:
        reply = row["response"]
        if reply.get("host_error") == "rpc-timeout":
            if row["request"]["id"] in responses:
                raise CaptureError("observation timeout has a conflicting reply")
        elif responses.get(row["request"]["id"]) != reply:
            raise CaptureError("observation response differs from native transport")
    if raw_responses is not None and raw_responses != [r["response"] for r in rows]:
        raise CaptureError("observation raw responses differ from RPC rows")


def _rpc_exchange(command, home, workspace, requests, timeout):
    replies = queue.Queue(maxsize=256)
    events = []
    terminal_reader_failure = []
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            command,
            env=dict(os.environ, CODEX_HOME=str(home)),
            cwd=workspace,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            creationflags=flags,
        )

        def publish(value):
            replies.put(value, timeout=1)

        def reader_error(
            kind, limit=None, observed=None, error_type=None, byte_offset=None
        ):
            detail = {"kind": kind}
            if limit is not None:
                detail["limit_bytes"] = limit
            if observed is not None:
                detail["observed_prefix_bytes"] = observed
            if error_type is not None:
                detail["error_type"] = error_type
            if byte_offset is not None:
                detail["byte_offset"] = byte_offset
            if not terminal_reader_failure:
                terminal_reader_failure.append(detail)
            publish({"reader_error": detail})

        def reader_capture_error(detail):
            kind = detail.get("kind")
            observed = detail.get("observed_prefix_bytes")
            limit = detail.get("limit_bytes")
            if kind == "frame-limit":
                return CaptureError(
                    f"app-server response frame exceeded {limit} bytes "
                    f"after reading {observed}-byte prefix"
                )
            if kind == "stream-limit":
                return CaptureError(
                    f"app-server response stream exceeded {limit} bytes "
                    f"after reading {observed}-byte prefix"
                )
            if kind == "invalid-utf8":
                return CaptureError(
                    "app-server response contained invalid UTF-8 "
                    f"in {observed}-byte prefix"
                )
            if kind == "malformed-json":
                return CaptureError(
                    f"app-server emitted malformed JSON in {observed}-byte frame"
                )
            if kind == "reader-exception":
                return CaptureError(
                    f"app-server response reader failed: {detail.get('error_type')}"
                )
            if kind == "event-limit":
                return CaptureError("app-server observation event bound exceeded")
            return CaptureError("app-server response reader failed")

        def read():
            total = 0
            try:
                for number in range(1, MAX_RPC_EVENTS + 2):
                    line = process.stdout.readline(
                        min(MAX_RPC_FRAME_BYTES + 2, MAX_RPC_STREAM_BYTES - total + 1)
                    )
                    if not line:
                        break
                    total += len(line)
                    if total > MAX_RPC_STREAM_BYTES:
                        reader_error("stream-limit", MAX_RPC_STREAM_BYTES, total)
                        break
                    if number > MAX_RPC_EVENTS:
                        reader_error("event-limit")
                        break
                    payload = line[:-1] if line.endswith(b"\n") else line
                    if payload.endswith(b"\r"):
                        payload = payload[:-1]
                    if len(payload) > MAX_RPC_FRAME_BYTES:
                        reader_error("frame-limit", MAX_RPC_FRAME_BYTES, len(line))
                        break
                    try:
                        text = payload.decode("utf-8")
                    except UnicodeDecodeError as error:
                        reader_error(
                            "invalid-utf8",
                            observed=len(line),
                            byte_offset=error.start,
                        )
                        break
                    try:
                        publish(json.loads(text))
                    except json.JSONDecodeError:
                        reader_error("malformed-json", observed=len(line))
                        break
            except queue.Full:
                pass  # The finite request deadline terminates a stalled producer.
            except BaseException as error:
                try:
                    reader_error("reader-exception", error_type=type(error).__name__)
                except queue.Full:
                    pass
            finally:
                try:
                    replies.put(None, timeout=1)
                except queue.Full:
                    pass

        reader = threading.Thread(target=read, daemon=True)
        reader.start()

        def request(item):
            events.append({"direction": "request", "payload": item})
            process.stdin.write((json.dumps(item) + "\n").encode())
            process.stdin.flush()
            deadline = time.monotonic() + timeout
            while True:
                if time.monotonic() >= deadline:
                    return {"id": item["id"], "host_error": "rpc-timeout"}
                try:
                    value = replies.get(timeout=max(0, deadline - time.monotonic()))
                except queue.Empty:
                    return {"id": item["id"], "host_error": "rpc-timeout"}
                events.append({"direction": "response", "payload": value})
                if len(events) > MAX_RPC_EVENTS:
                    raise CaptureError("app-server observation event bound exceeded")
                if value is None:
                    raise CaptureError("app-server closed its output before replying")
                if not isinstance(value, dict):
                    raise CaptureError("app-server emitted a non-object JSON response")
                detail = value.get("reader_error")
                if isinstance(detail, dict):
                    raise reader_capture_error(detail)
                if value.get("id") == item["id"]:
                    return value

        responses = []
        failure = None
        try:
            hello = request(
                {
                    "id": 0,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {
                            "name": "stage2-runtime-observer",
                            "version": "1",
                        },
                        "capabilities": {"experimentalApi": True},
                    },
                }
            )
            if "error" in hello or "host_error" in hello:
                raise CaptureError("app-server initialization failed")
            notification = {"method": "initialized"}
            events.append({"direction": "request", "payload": notification})
            process.stdin.write((json.dumps(notification) + "\n").encode())
            process.stdin.flush()
            for item in requests:
                responses.append(request(item))
        except BaseException as error:
            failure = error
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass  # A closed executor pipe must not hide the original failure.
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            reader.join(timeout=5)
            process.stdout.close()
        if terminal_reader_failure:
            marker = {"reader_error": terminal_reader_failure[0]}
            if not any(
                event.get("direction") == "response" and event.get("payload") == marker
                for event in events
            ):
                events.append({"direction": "response", "payload": marker})
            if failure is None:
                failure = reader_capture_error(terminal_reader_failure[0])
        stderr.seek(0)
        stderr_bytes = stderr.read()
        if failure is not None:
            failure.observation_events = events
            failure.observation_stderr = stderr_bytes
            raise failure
        return responses, events, stderr_bytes


def _write_observation(output, name, raw, handle):
    if handle is None:
        (output / name).write_bytes(raw)
    else:
        handle.write(name, raw)


def collect_runtime_observation(
    *,
    codex,
    codex_home,
    workspace,
    output_dir,
    thread_id=None,
    rpc_transport=None,
    rpc_timeout_seconds=120,
    trace_root=None,
    _output_handle=None,
):
    """Collect private metadata; never dispatch turn/start or change settings."""
    if not _valid_rpc_timeout(rpc_timeout_seconds):
        raise CaptureError("rpc_timeout_seconds must be finite and within (0, 600]")
    try:
        output = private_output(output_dir)
    except DeliverableError as error:
        raise CaptureError(str(error)) from error
    if _output_handle is not None and (
        not isinstance(_output_handle, SealDirectory)
        or not _output_handle.active
        or _output_handle.path.absolute() != output
    ):
        raise CaptureError("observation output handle differs from declared directory")
    home, work = Path(codex_home).resolve(), Path(workspace).resolve()
    if not home.is_dir() or not work.is_dir() or home == work:
        raise CaptureError("existing distinct profile and workspace are required")
    if home.is_relative_to(work) or work.is_relative_to(home):
        raise CaptureError("profile and workspace must not contain each other")
    if any(
        output == p or output.is_relative_to(p) or p.is_relative_to(output)
        for p in (home, work)
    ):
        raise CaptureError("observation output must be separate from profile/workspace")
    if thread_id is not None and (
        not isinstance(thread_id, str) or not thread_id.strip()
    ):
        raise CaptureError("thread_id must be nonempty when supplied")
    runtime = codex_runtime_sha(codex)
    try:
        namespace = bind_namespace(codex, home, work, trace_root=trace_root)
    except NativeNamespaceError as error:
        raise CaptureError(str(error)) from error
    config = home / "config.toml"
    config_sha = sha256(config.read_bytes()) if config.is_file() else None
    requests = [
        {
            "id": 1,
            "method": "config/read",
            "params": {"includeLayers": True, "cwd": str(work)},
        },
        {"id": 2, "method": "skills/list", "params": {"cwds": [str(work)]}},
        {"id": 3, "method": "plugin/list", "params": {"cwds": [str(work)]}},
        {"id": 4, "method": "mcpServerStatus/list", "params": {"limit": 100}},
    ]
    if thread_id is not None:
        requests.append(
            {
                "id": 5,
                "method": "thread/read",
                "params": {
                    "threadId": thread_id,
                    "includeTurns": False,
                },
            }
        )
    if _output_handle is None:
        output.mkdir(parents=True, exist_ok=False)
    native_command = [str(Path(codex).resolve()), "app-server", "--stdio"]
    try:
        command = wrap_namespace(native_command, namespace)
    except NativeNamespaceError as error:
        raise CaptureError(str(error)) from error
    if namespace:
        namespace_raw = Path(namespace["path"]).read_bytes()
        if sha256(namespace_raw) != namespace["sha256"]:
            raise CaptureError("native namespace changed before archival")
        _write_observation(
            output,
            "native-namespace.json",
            namespace_raw,
            _output_handle,
        )
    started = _utc_now()
    transport = rpc_transport or _rpc_exchange
    try:
        responses, events, stderr = transport(
            command, home, work, requests, rpc_timeout_seconds
        )
    except Exception as error:
        _write_observation(
            output,
            "failed-transport.json",
            (json.dumps(getattr(error, "observation_events", [])) + "\n").encode(),
            _output_handle,
        )
        _write_observation(
            output,
            "stderr.txt",
            getattr(error, "observation_stderr", b""),
            _output_handle,
        )
        _write_observation(
            output,
            "failure.json",
            (
                json.dumps(
                    {
                        "status": "failed",
                        "error_type": type(error).__name__,
                        "started_at": started,
                        "formal_ready": False,
                    }
                )
                + "\n"
            ).encode(),
            _output_handle,
        )
        raise
    # Preserve completed transport bytes before any semantic validation fails.
    _write_observation(
        output,
        "transport.json",
        (json.dumps(events, ensure_ascii=False, sort_keys=True) + "\n").encode(),
        _output_handle,
    )
    _write_observation(
        output,
        "rpc-responses.json",
        (json.dumps(responses, ensure_ascii=False, sort_keys=True) + "\n").encode(),
        _output_handle,
    )
    _write_observation(output, "stderr.txt", stderr, _output_handle)
    if len(responses) != len(requests):
        raise CaptureError("RPC response count differs from dispatched requests")
    rows = []
    for item, reply in zip(requests, responses):
        if not isinstance(reply, dict) or reply.get("id") != item["id"]:
            raise CaptureError("RPC response identity differs")
        complete = _response_observed(item, reply)
        rows.append(
            {
                "method": item["method"],
                "request": item,
                "response": reply,
                "status": "observed" if complete else "incomplete",
            }
        )
    _verify_transport(rows, events, responses)
    try:
        namespace_changed = (
            namespace is not None
            and bind_namespace(codex, home, work, trace_root=trace_root) != namespace
        )
    except NativeNamespaceError as error:
        raise CaptureError(str(error)) from error
    if (
        runtime != codex_runtime_sha(codex)
        or config_sha != (sha256(config.read_bytes()) if config.is_file() else None)
        or namespace_changed
    ):
        raise CaptureError("runtime, profile, or namespace changed during observation")
    payloads = {
        "rpc.json": rows,
        "transport.json": events,
        "rpc-responses.json": responses,
    }
    artifacts = {}
    for name, value in payloads.items():
        raw = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()
        if name == "rpc.json":
            _write_observation(output, name, raw, _output_handle)
        artifacts[name] = sha256(raw)
    artifacts["stderr.txt"] = sha256(stderr)
    if namespace:
        artifacts["native-namespace.json"] = namespace["sha256"]
    record = {
        "kind": "Stage2RuntimeObservation",
        "schema_version": "2.0.0",
        "rpc_timeout_seconds": rpc_timeout_seconds,
        "status": "observed"
        if all(r["status"] == "observed" for r in rows)
        else "partial",
        "started_at": started,
        "ended_at": _utc_now(),
        "command": command,
        "binding": {
            "runtime_sha256": runtime,
            "profile_config_sha256": config_sha,
            "workspace": str(work),
            "codex_home": str(home),
            "thread_id": thread_id,
        },
        "artifacts": artifacts,
        "model_turns_dispatched": 0,
        "evidence_class": "synthetic-test-only"
        if rpc_transport
        else "host-app-server-observation",
        "offered_tool_inventory": "unknown",
        "instruction_source_chain": "unknown",
        "filesystem_read_isolation": "not-assessed",
        "formal_ready": False,
    }
    if namespace:
        record["binding"]["native_namespace"] = namespace
    raw = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode()
    _write_observation(output, "observation.json", raw, _output_handle)
    return {**record, "record_sha256_receipt": sha256(raw)}


def verify_runtime_observation(output_dir, receipt, *, allow_synthetic=False):
    """Read-only verification against an externally retained receipt."""
    try:
        root = private_output(output_dir)
        raw = (root / "observation.json").read_bytes()
        if sha256(raw) != receipt:
            raise CaptureError("observation receipt differs")
        record = json.loads(raw)
        schema = record.get("schema_version") if isinstance(record, dict) else None
        timeout_contract = (
            schema == "1.0.0" and "rpc_timeout_seconds" not in record
        ) or (
            schema == "2.0.0"
            and "rpc_timeout_seconds" in record
            and _valid_rpc_timeout(record["rpc_timeout_seconds"])
        )
        if not isinstance(record, dict) or (
            record.get("kind") != "Stage2RuntimeObservation"
            or not timeout_contract
            or record.get("formal_ready") is not False
            or record.get("model_turns_dispatched") != 0
            or record.get("offered_tool_inventory") != "unknown"
            or record.get("instruction_source_chain") != "unknown"
        ):
            raise CaptureError("observation contract differs")
        if (
            record["evidence_class"] != "host-app-server-observation"
            and not allow_synthetic
        ):
            raise CaptureError("synthetic observation is not native evidence")
        namespace = record.get("binding", {}).get("native_namespace")
        namespace_file = root / "native-namespace.json"
        if (namespace is not None) != namespace_file.is_file() or (
            namespace is not None
        ) != ("native-namespace.json" in record.get("artifacts", {})):
            raise CaptureError("observation namespace artifact binding differs")
        try:
            if namespace is not None:
                current = bind_namespace(
                    namespace["scope"]["codex"],
                    namespace["scope"]["home"],
                    namespace["scope"]["workspace"],
                    trace_root=namespace.get("trace_root"),
                )
                if current != namespace:
                    raise CaptureError("observation namespace binding changed")
                expected_command = wrap_namespace(
                    [namespace["scope"]["codex"], "app-server", "--stdio"],
                    namespace,
                )
                if record.get("command") != expected_command:
                    raise CaptureError("observation namespace command differs")
            elif record.get("command") != [
                record["binding"].get("codex", record["command"][0]),
                "app-server",
                "--stdio",
            ]:
                # Legacy records did not retain the executable path separately;
                # their first command element remains the binding.
                raise CaptureError("observation command differs")
        except NativeNamespaceError as error:
            raise CaptureError(str(error)) from error
        expected_artifacts = set(record["artifacts"])
        if expected_artifacts not in (
            {"rpc.json", "transport.json", "stderr.txt"},
            {"rpc.json", "transport.json", "stderr.txt", "rpc-responses.json"},
            {
                "rpc.json",
                "transport.json",
                "stderr.txt",
                "rpc-responses.json",
                "native-namespace.json",
            },
        ):
            raise CaptureError("observation artifact set differs")
        for name, digest in record["artifacts"].items():
            if sha256((root / name).read_bytes()) != digest:
                raise CaptureError("observation artifact bytes differ")
        rows = json.loads((root / "rpc.json").read_bytes())
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise CaptureError("observation RPC rows are malformed")
        methods = ["config/read", "skills/list", "plugin/list", "mcpServerStatus/list"]
        if record["binding"]["thread_id"] is not None:
            methods.append("thread/read")
        if [r["method"] for r in rows] != methods or any(
            r["request"]["method"] != r["method"]
            or r["response"]["id"] != r["request"]["id"]
            for r in rows
        ):
            raise CaptureError("observation methods or response bindings differ")
        events = json.loads((root / "transport.json").read_bytes())
        raw_responses = (
            json.loads((root / "rpc-responses.json").read_bytes())
            if "rpc-responses.json" in record["artifacts"]
            else None
        )
        _verify_transport(rows, events, raw_responses)
        statuses = [
            "observed"
            if _response_observed(row["request"], row["response"])
            else "incomplete"
            for row in rows
        ]
        if [row["status"] for row in rows] != statuses or record["status"] != (
            "observed" if all(s == "observed" for s in statuses) else "partial"
        ):
            raise CaptureError("observation status does not match RPC evidence")
        return record
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        if isinstance(error, CaptureError):
            raise
        raise CaptureError("observation archive is malformed") from error

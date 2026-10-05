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
from .trace_seal_io import SealDirectory


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
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            command,
            env=dict(os.environ, CODEX_HOME=str(home)),
            cwd=workspace,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
            creationflags=flags,
        )

        def read():
            try:
                for number, line in enumerate(process.stdout, 1):
                    if number > 2048 or len(line) > 4 * 1024 * 1024:
                        replies.put(
                            {"invalid_json": "bounded output exceeded"}, timeout=1
                        )
                        break
                    try:
                        replies.put(json.loads(line), timeout=1)
                    except json.JSONDecodeError:
                        replies.put({"invalid_json": line}, timeout=1)
            except queue.Full:
                pass  # The finite request deadline terminates a stalled producer.
            finally:
                try:
                    replies.put(None, timeout=1)
                except queue.Full:
                    pass

        reader = threading.Thread(target=read, daemon=True)
        reader.start()

        def request(item):
            events.append({"direction": "request", "payload": item})
            process.stdin.write(json.dumps(item) + "\n")
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
                if len(events) > 2048:
                    raise CaptureError("app-server observation event bound exceeded")
                if value is None:
                    raise CaptureError("app-server closed its output before replying")
                if not isinstance(value, dict) or "invalid_json" in value:
                    raise CaptureError("app-server emitted malformed JSON")
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
            process.stdin.write(json.dumps(notification) + "\n")
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
    command = [str(Path(codex).resolve()), "app-server", "--stdio"]
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
    if runtime != codex_runtime_sha(codex) or config_sha != (
        sha256(config.read_bytes()) if config.is_file() else None
    ):
        raise CaptureError("runtime or profile changed during observation")
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
        if set(record["artifacts"]) not in (
            {"rpc.json", "transport.json", "stderr.txt"},
            {"rpc.json", "transport.json", "stderr.txt", "rpc-responses.json"},
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

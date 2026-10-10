"""Fresh, content-only native units with durable no-resend evidence.

The trusted broker supplies aggregate authority/budget. This producer is a
separate pilot lane, not Engine/native-namespace or scientific acceptance.
"""

from copy import deepcopy
from contextlib import closing
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import tomllib

from stage1_deliverable.common import canonical, private_output, sha
from .bootstrap import _account
from .frame_journal import _validated
from .process_deadline import SessionLeaseExpired
from .runtime_factory import compose_runtime
from .runtime_spec import _hash, _require, _thread_config
from .stage_inputs import snapshot_inputs, source_digest


def _save(path, value):
    raw = canonical(value) + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return sha(raw)


def _database(path, project):
    path = private_output(path)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        state = db.execute(
            "SELECT state FROM projects WHERE id=?", (project,)
        ).fetchone()
        _require(state is not None, "unit project missing")
        rows = db.execute(
            "SELECT revision,kind,payload,state_sha256 FROM events WHERE project=? ORDER BY revision",
            (project,),
        ).fetchall()
    return dict(state=json.loads(state[0]), events=[list(row) for row in rows])


class StageModel:
    """Use checked own-account inputs; every semantic unit owns one new thread.

    ``deadline`` is an absolute time.monotonic() deadline, not Unix time.
    ``admit`` must durably reserve the unit at phase=reserve and return literal
    True at every later phase without reserving another model call.
    ``runtime_factory`` is an explicit injected seam for synthetic tests only.
    """

    def __init__(
        self,
        checked,
        *,
        model,
        permit_sha256,
        source_sha256,
        executable_sha256,
        user_config_sha256,
        config_sha256,
        authenticate,
        credential,
        admit,
        output_root,
        project_ref="repo-content-pilot",
        runtime_factory=compose_runtime,
    ):
        _require(
            all(callable(v) for v in (authenticate, admit, runtime_factory)),
            "trusted callbacks required",
        )
        _require(
            isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", model),
            "model required",
        )
        _require(
            isinstance(project_ref, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", project_ref),
            "project ref required",
        )
        _require(
            all(
                _hash(v)
                for v in (
                    permit_sha256,
                    source_sha256,
                    executable_sha256,
                    user_config_sha256,
                    config_sha256,
                )
            ),
            "unit pins required",
        )
        self.checked, self.model, self.ref = checked, model, project_ref
        self.source_sha256, self.permit_sha256 = source_sha256, permit_sha256
        self.authenticate, self.credential, self.admit = authenticate, credential, admit
        self.factory, self.root = runtime_factory, private_output(output_root)
        roots = [Path(checked[n]) for n in ("source_root", "repo")]
        roots += [
            Path(v)
            for stage in checked["stage_inputs"].values()
            for k, v in (stage or {}).items()
            if k.endswith("_root") and v is not None
        ]
        _require(
            all(
                not self.root.is_relative_to(r) and not r.is_relative_to(self.root)
                for r in roots
            ),
            "unit output overlaps input",
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self.pins = {
            "executable": executable_sha256,
            "user_path": user_config_sha256,
            "config_path": config_sha256,
            "index_path": checked["index_sha256"],
            "input_path": checked["input_version"],
        }
        self.context = dict(
            model=model,
            permit_sha256=permit_sha256,
            source_sha256=source_sha256,
            manifest=deepcopy(checked["manifest"]),
            pins=self.pins,
            thread_config=_thread_config(checked["thread_config"]),
            project_ref=project_ref,
            stage_source_sha256=checked["stage_source_sha256"],
            stage_inputs=deepcopy(checked["stage_inputs"]),
        )
        self.context_sha256 = sha(canonical(self.context))
        self._lock, self._run_lock = threading.RLock(), threading.Lock()
        self._active, self._current, self._accepted = None, None, {}
        self._check_source()

    def _check_source(self):
        source, checked = self.checked["source"], self.checked
        for name, expected in self.pins.items():
            source.pinned(
                checked[name],
                expected,
                512 * 1024 * 1024 if name == "executable" else 32 * 1024 * 1024,
            )
        manifest = self.context["manifest"]
        _require(
            source.inventory(Path(checked["repo"]) / "plugins/auto-research-agent")
            == manifest["plugin_files"]
            and source.inventory(Path(checked["source_root"]))
            == manifest["source_files"],
            "unit source inventory changed",
        )
        home = source.unlinked(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        _require(
            source.unlinked(home / "config.toml").resolve()
            == Path(checked["user_path"]),
            "inherited user config changed",
        )
        for ancestor in (
            Path(checked["source_root"]),
            *Path(checked["source_root"]).parents,
        ):
            layer = ancestor / ".codex/config.toml"
            _require(
                not layer.exists()
                or source.unlinked(layer).resolve() == Path(checked["user_path"]),
                "new configuration layer refused",
            )
        names = tomllib.loads(source.read(checked["user_path"]).decode("utf8")).get(
            "mcp_servers", {}
        )
        expected = {k: False for k in (f"mcp_servers.{n}.enabled" for n in names)}
        _require(
            {
                k: v
                for k, v in self.context["thread_config"].items()
                if k.startswith("mcp_servers.")
            }
            == expected,
            "user MCP denials changed",
        )
        _require(
            source_digest(snapshot_inputs(self.context["stage_inputs"]))
            == self.context["stage_source_sha256"],
            "stage source binding changed",
        )
        return True

    def _gate(self, request, deadline, phase, event):
        self._verify_source(deadline)
        action = event.get("action", {})
        if phase == "action":
            method, payload = action.get("method"), action.get("payload", {})
            if method == "turn/start":
                _require(
                    payload.get("model") == self.model
                    and payload.get("cwd")
                    == Path(self.checked["source_root"]).as_posix()
                    and payload.get("input")
                    == [
                        {"type": "text", "text": request["prompt"], "text_elements": []}
                    ],
                    "unit prompt binding differs",
                )
            elif method not in {
                "turn/interrupt",
                "item/tool/requestUserInput",
                "item/commandExecution/requestApproval",
                "item/fileChange/requestApproval",
            }:
                return False
            elif method != "turn/interrupt" and method != "item/tool/requestUserInput":
                if payload.get("decision") not in {"decline", "cancel"}:
                    return False
        return (
            self.admit(
                dict(
                    phase=phase,
                    unit_key=request["unit_key"],
                    prompt_sha256=request["prompt_sha256"],
                    source_sha256=self.source_sha256,
                    permit_sha256=self.permit_sha256,
                    event=deepcopy(event),
                )
            )
            is True
        )

    def _verify_source(self, deadline):
        if time.monotonic() >= deadline:
            raise SessionLeaseExpired("unit deadline expired")
        return self._check_source()

    def _spec(self, folder, deadline):
        remaining = math.floor(min(600, deadline - time.monotonic()))
        _require(remaining >= 1, "unit deadline expired")
        checked = self.checked
        return dict(
            kind="NativeAtlasRuntimeSpec",
            schema_version="1.0.0",
            project_ref=self.ref,
            project_id=checked["project_id"],
            principals=["local-viewer"],
            source_root=Path(checked["source_root"]).as_posix(),
            index_path=Path(checked["index_path"]).as_posix(),
            index_sha256=checked["index_sha256"],
            input_path=Path(checked["input_path"]).as_posix(),
            input_version=checked["input_version"],
            store_path=(folder / "native.sqlite3").as_posix(),
            executable=Path(checked["executable"]).as_posix(),
            executable_sha256=self.pins["executable"],
            model=self.model,
            approval_policy="on-request",
            permit_sha256=self.permit_sha256,
            thread_config=self.context["thread_config"],
            handshake_timeout_seconds=min(120, remaining),
            limits=dict(
                lifetime_seconds=remaining,
                max_stream_bytes=1048576,
                max_text_bytes=16384,
                max_starts=1,
                timeout_seconds=min(30, remaining),
            ),
        )

    def run(self, unit_key, prompt, deadline):
        _require(
            isinstance(unit_key, str)
            and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", unit_key),
            "unit key required",
        )
        _require(
            isinstance(prompt, str) and 0 < len(prompt.encode("utf8")) <= 16384,
            "unit prompt bound exceeded",
        )
        _require(
            type(deadline) in (int, float) and math.isfinite(deadline),
            "monotonic deadline required",
        )
        folder = self.root / sha(unit_key.encode("utf8"))
        request = dict(
            unit_key=unit_key,
            prompt=prompt,
            prompt_sha256=sha(prompt.encode("utf8")),
            source_sha256=self.source_sha256,
            context_sha256=self.context_sha256,
            model=self.model,
        )
        request_path, result_path = folder / "request.json", folder / "result.json"
        with self._run_lock:
            if folder.exists():
                _require(
                    self.checked["source"].decode(
                        self.checked["source"].read(request_path, 65536)
                    )
                    == request,
                    "unit key payload differs",
                )
                if result_path.exists():
                    saved = self.checked["source"].decode(
                        self.checked["source"].read(result_path, 65536)
                    )
                    self._accepted[unit_key] = sha(canonical(saved))
                    return dict(saved, replayed=True)
                return dict(
                    status="execution-unknown",
                    unit_key=unit_key,
                    request_path=str(request_path),
                    replayed=True,
                )
            folder.mkdir()
            request_sha = _save(request_path, request)
            runtime, receipt = (
                None,
                dict(
                    status="execution-unknown",
                    unit_key=unit_key,
                    request_path=str(request_path),
                    request_sha256=request_sha,
                    source_sha256=self.source_sha256,
                    prompt_sha256=request["prompt_sha256"],
                ),
            )
            with self._lock:
                self._current = dict(request, status="reserved")
            try:
                _require(
                    self._gate(request, deadline, "reserve", {}) is True,
                    "unit reservation refused",
                )
                spec = self._spec(folder, deadline)
                spec_path = folder / "runtime-spec.json"
                spec_sha = _save(spec_path, spec)
                receipt.update(
                    spec_path=str(spec_path),
                    spec_sha256=spec_sha,
                    native_store_path=spec["store_path"],
                )
                gates = {"verify_source": lambda _: self._verify_source(deadline)}
                for name, phase in (
                    ("admit_spawn", "spawn"),
                    ("admit_lifecycle", "lifecycle"),
                    ("admit_attach", "attach"),
                    ("admit_action", "action"),
                ):
                    gates[name] = lambda event, phase=phase: self._gate(
                        request, deadline, phase, event
                    )
                runtime = self.factory(
                    [(spec_path, spec_sha)],
                    authenticate=self.authenticate,
                    gates={self.ref: gates},
                    enabled=True,
                )
                _require(runtime is not None, "unit composition unavailable")
                with self._lock:
                    self._active, self._current["status"] = runtime, "running"
                runtime.start()
                with runtime._entries[0]["store"]._lock:
                    offer = runtime.api.offer(self.credential, self.ref)
                    runtime.api.message(
                        self.credential,
                        self.ref,
                        dict(
                            key=unit_key,
                            revision=offer["revision"],
                            offer_ref=offer["offer_ref"],
                            offer_sha256=offer["offer_sha256"],
                            text=prompt,
                        ),
                    )
                while time.monotonic() < deadline:
                    entry = runtime._entries[0]
                    with entry["store"]._lock:
                        data = _database(Path(spec["store_path"]), spec["project_id"])
                    try:
                        self._reconstruct(data, request, spec)
                        receipt["status"] = "completed"
                        break
                    except ValueError as error:
                        if any(
                            row.get("status")
                            in {"failed", "interrupted", "execution-unknown"}
                            for row in data["state"]["intents"].values()
                            if row.get("method") == "turn/start"
                        ) or any(
                            row["status"] in {"failed", "interrupted"}
                            for row in data["state"]["turns"].values()
                        ):
                            receipt["failure"] = "native-evidence: " + str(error)[:256]
                            break
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            except Exception as error:
                receipt["failure"] = type(error).__name__ + ": " + str(error)[:512]
            finally:
                if runtime is not None:
                    try:
                        receipt["cleanup"] = runtime.shutdown(timeout=10)
                        clean = receipt["cleanup"].get(self.ref, {})
                        _require(
                            clean.get("leader_reaped") is True
                            and clean.get("errors") == []
                            and clean.get("journal_cleanup_observed") is True,
                            "unit cleanup unobserved",
                        )
                    except Exception as error:
                        receipt.update(
                            status="execution-unknown",
                            cleanup_failure=type(error).__name__,
                        )
                with self._lock:
                    self._active = None
                    self._current = dict(request, status=receipt["status"])
            store_path = folder / "native.sqlite3"
            if store_path.exists():
                try:
                    data = _database(store_path, self.checked["project_id"])
                    artifact = folder / "raw-protocol.json"
                    receipt["raw_artifact"] = dict(
                        path=artifact.as_posix(), sha256=_save(artifact, data)
                    )
                    receipt["native_store_sha256"] = sha(
                        self.checked["source"].read(store_path, 32 * 1024 * 1024)
                    )
                except Exception as error:
                    receipt.update(
                        status="execution-unknown",
                        evidence_failure=type(error).__name__,
                    )
            _save(result_path, receipt)
            self._accepted[unit_key] = sha(canonical(receipt))
            return deepcopy(receipt)

    def _reconstruct(self, data, request, spec):
        state, rows = data["state"], data["events"]
        _require(state["index_sha256"] == spec["index_sha256"], "saved project differs")
        starts = [
            (key, row)
            for key, row in state.get("session_api_actions", {}).items()
            if row.get("kind") == "message"
        ]
        _require(len(starts) == 1, "single native unit required")
        key, action = starts[0]
        _require(
            action["request"]["text"] == request["prompt"]
            and action["request"]["key"] == request["unit_key"],
            "saved prompt differs",
        )
        intent = state["intents"][key]
        thread, turn = state["thread_id"], intent.get("native_turn_id")
        _require(
            intent["method"] == "turn/start"
            and intent["status"] == "completed"
            and isinstance(turn, str),
            "completed bound native turn required",
        )
        _require(
            intent["payload"]
            == dict(
                threadId=thread,
                cwd=spec["source_root"],
                model=spec["model"],
                input=[dict(type="text", text=request["prompt"], text_elements=[])],
            ),
            "saved native payload differs",
        )
        document = action["start_offer"]["document"]
        _require(
            all(
                document.get(n) == spec[n]
                for n in (
                    "project_id",
                    "source_root",
                    "index_sha256",
                    "input_version",
                    "model",
                    "permit_sha256",
                )
            ),
            "saved offer differs",
        )
        correlations = [
            c["binding"]
            for c in state["protocol"]["correlations"].values()
            if c["binding"]["intent_key"] == key
        ]
        _require(len(correlations) == 1, "native correlation ambiguous")
        binding = correlations[0]
        _require(
            binding["thread_id"] == thread
            and binding["connection_id"] == action["connection_id"]
            and binding["intent_sha256"] == intent["record_sha256"],
            "native correlation differs",
        )
        finals, terminal, outgoing, reply = {}, set(), 0, 0
        for _, kind, raw_payload, _ in rows:
            if kind != "protocol-frame":
                continue
            payload = json.loads(raw_payload)
            frame, conflict = _validated(payload["frame"])
            _require(
                conflict is None
                and payload.get("quarantine") is None
                and sha(frame["raw_utf8"].encode("utf8")) == payload["raw_sha256"],
                "raw native frame invalid",
            )
            if frame["connection_id"] != binding["connection_id"]:
                continue
            message = frame["message"]
            rpc_id = binding["request"]["id"]
            same_id = (
                type(message.get("id")) is type(rpc_id) and message.get("id") == rpc_id
            )
            if (
                frame["direction"] == "outgoing"
                and message.get("method") == "turn/start"
            ):
                _require(
                    same_id and message.get("params") == intent["payload"],
                    "raw start differs",
                )
                outgoing += 1
            if frame["direction"] != "incoming":
                continue
            if frame["kind"] == "response" and same_id:
                _require(
                    message.get("result", {}).get("turn", {}).get("id") == turn,
                    "native reply differs",
                )
                reply += 1
            params = message.get("params", {})
            observed_turn = params.get("turnId", params.get("turn", {}).get("id"))
            if params.get("threadId") != thread or observed_turn != turn:
                continue
            item = params.get("item", {})
            _require(message.get("method") != "error", "native error observed")
            if message.get("method") in {"item/started", "item/completed"}:
                _require(
                    item.get("type") in {"agentMessage", "reasoning"},
                    "native tool item observed",
                )
            if (
                message.get("method") == "item/completed"
                and item.get("type") == "agentMessage"
            ):
                _require(
                    isinstance(item.get("id"), str)
                    and isinstance(item.get("text"), str),
                    "native final invalid",
                )
                value = (item["text"], item.get("phase"))
                _require(
                    value[1] in (None, "commentary", "final_answer"),
                    "native message phase invalid",
                )
                _require(
                    item["id"] not in finals or finals[item["id"]] == value,
                    "conflicting native final",
                )
                finals[item["id"]] = value
            if message.get("method") == "turn/completed":
                terminal.add(params["turn"].get("status"))
        _require(
            outgoing == 1
            and reply == 1
            and terminal == {"completed"}
            and len(finals) > 0,
            "complete native final and terminal required",
        )
        answers = [text for text, phase in finals.values() if phase == "final_answer"]
        if not answers:
            answers = [text for text, phase in finals.values() if phase is None]
        _require(len(answers) == 1, "native final answer ambiguous")
        text = answers[0]
        _require(
            0 < len(text.encode("utf8")) <= 1048576,
            "native final empty or exceeds bound",
        )
        boot = state.get("bootstrap", {})
        _require(boot.get("phase") == "adopted", "native bootstrap missing")
        accounts = [
            f["message"]["result"]
            for f in boot["frames"]
            if f["kind"] == "response"
            and type(f["message"].get("id")) is str
            and f["message"]["id"] == "1"
        ]
        _require(
            len(accounts) == 1
            and _account(accounts[0].get("account"))
            and (
                accounts[0].get("requiresOpenaiAuth") is False
                or accounts[0].get("account") is not None
            ),
            "account observation missing",
        )
        return dict(
            status="completed",
            final_text=text,
            model=spec["model"],
            thread_id=thread,
            turn_id=turn,
            prompt_sha256=request["prompt_sha256"],
            source_sha256=request["source_sha256"],
            observed_tool_items=[],
            account_observation="accepted-account-schema",
            authenticated_process=False,
            process_tree_containment_verified=False,
            usage=None,
            cost=None,
        )

    def verify_receipt(
        self, receipt, *, expected_prompt_sha256, expected_source_sha256
    ):
        saved = {k: v for k, v in receipt.items() if k != "replayed"}
        key = saved.get("unit_key")
        _require(
            key in self._accepted and self._accepted[key] == sha(canonical(saved)),
            "unbound unit receipt",
        )
        _require(saved.get("status") == "completed", "unit incomplete")
        folder = self.root / sha(key.encode("utf8"))
        source = self.checked["source"]
        request = source.decode(
            source.pinned(folder / "request.json", saved["request_sha256"], 65536)
        )
        _require(
            request["context_sha256"] == self.context_sha256
            and request["prompt_sha256"] == expected_prompt_sha256
            and request["source_sha256"]
            == expected_source_sha256
            == self.source_sha256,
            "unit input hash differs",
        )
        spec = source.decode(
            source.pinned(folder / "runtime-spec.json", saved["spec_sha256"], 65536)
        )
        _require(
            saved["raw_artifact"]["path"] == (folder / "raw-protocol.json").as_posix()
            and saved["native_store_path"] == (folder / "native.sqlite3").as_posix(),
            "unit artifact path differs",
        )
        data = source.decode(
            source.pinned(
                saved["raw_artifact"]["path"],
                saved["raw_artifact"]["sha256"],
                32 * 1024 * 1024,
            )
        )
        source.pinned(
            saved["native_store_path"], saved["native_store_sha256"], 32 * 1024 * 1024
        )
        _require(
            data
            == _database(Path(saved["native_store_path"]), self.checked["project_id"]),
            "raw protocol/database differs",
        )
        result = self._reconstruct(data, request, spec)
        return dict(
            result,
            raw_artifact=deepcopy(saved["raw_artifact"]),
            native_store_path=saved["native_store_path"],
        )

    def active_api(self):
        with self._lock:
            return None if self._active is None else self._active.api

    def status(self):
        with self._lock:
            current = (
                None
                if self._current is None
                else {k: v for k, v in self._current.items() if k != "prompt"}
            )
            result = dict(
                current=current,
                project_ref=self.ref,
                active=self._active is not None,
                native_view=None,
            )
            if self._active is not None:
                try:
                    result["native_view"] = self._active.api.view(
                        self.credential, self.ref
                    )
                except Exception as error:
                    result["view_failure"] = (
                        type(error).__name__ + ": " + str(error)[:256]
                    )
            return result

    def answer(self, body, pre_admission=None):
        _require(
            not isinstance(body.get("result"), dict)
            or body["result"].get("decision") in (None, "decline", "cancel"),
            "pilot approvals are deny-only",
        )
        with self._lock:
            _require(self._active is not None, "unit session unavailable")
            with self._active.api.admission_guard(pre_admission or (lambda: 10)):
                return self._active.api.answer(self.credential, self.ref, body)

    def interrupt(self, body, pre_admission=None):
        with self._lock:
            _require(self._active is not None, "unit session unavailable")
            with self._active.api.admission_guard(pre_admission or (lambda: 10)):
                return self._active.api.interrupt(self.credential, self.ref, body)

    def close(self):
        """Stop the active physical session; its worker retains the final receipt."""
        with self._lock:
            runtime = self._active
        if runtime is not None:
            return runtime.shutdown(timeout=10)
        return None

"""Content-only producer with real SQLite/bootstrap and explicit injected I/O."""

import atlas_test_paths  # noqa: F401 -- standalone discovery needs local CLI.

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from native_session_fixtures import Channel
from research_workspace_native import atlas_local_source as source
from research_workspace_native.bootstrap import BootstrapSession
from research_workspace_native.controller import InjectedSessionController
from research_workspace_native.frame_journal import FrameJournal
from research_workspace_native.runtime_spec import DENIED_THREAD_CONFIG
from research_workspace_native.session_api import SessionApi
from research_workspace_native.stage_inputs import source_digest
from stage1_deliverable.common import canonical, sha


class FakeChannel(Channel):
    """No processes/models/search: only deterministic protocol messages."""

    def __init__(self, mode):
        super().__init__()
        self.mode = mode

    def write(self, data, timeout):
        count = super().write(data, timeout)
        message = json.loads(data)
        method = message.get("method")
        if method == "initialize":
            self.queue(dict(id=message["id"], result=dict(userAgent="synthetic")))
        elif method == "account/read":
            self.queue(
                dict(
                    id=message["id"],
                    result=dict(requiresOpenaiAuth=True, account=dict(type="apiKey")),
                )
            )
        elif method == "thread/start":
            p = message["params"]
            self.queue(
                dict(
                    id=message["id"],
                    result=dict(
                        thread=dict(id="fake-thread"),
                        cwd=p["cwd"],
                        model=p["model"],
                        approvalPolicy=p["approvalPolicy"],
                        sandbox=dict(type="readOnly", networkAccess=False),
                    ),
                )
            )
        elif method == "turn/start":
            self.queue(dict(id=message["id"], result=dict(turn=dict(id="fake-turn"))))
            if self.mode == "question":
                self.queue(
                    dict(
                        id=8,
                        method="item/tool/requestUserInput",
                        params=dict(
                            threadId="fake-thread",
                            turnId="fake-turn",
                            itemId="q",
                            questions=[dict(id="q", question="Choose?")],
                        ),
                    )
                )
            elif self.mode != "timeout":
                self.finish()
        elif method == "turn/interrupt":
            self.queue(dict(id=message["id"], result={}))
            self.queue(
                dict(
                    method="turn/completed",
                    params=dict(
                        threadId="fake-thread",
                        turn=dict(id="fake-turn", status="interrupted"),
                    ),
                )
            )
        elif "result" in message:
            self.queue(
                dict(
                    method="serverRequest/resolved",
                    params=dict(threadId="fake-thread", requestId=8),
                )
            )
            self.finish()
        return count

    def finish(self):
        params = dict(
            threadId="fake-thread",
            turnId="fake-turn",
            item=dict(
                id="final",
                type="agentMessage",
                text="Synthetic controlled source interpretation.",
            ),
        )
        if self.mode == "wrong-turn":
            params["turnId"] = "other-turn"
        if self.mode == "tool":
            params["item"]["type"] = "webSearch"
        if self.mode == "commentary":
            commentary = deepcopy(params)
            commentary["item"].update(
                id="progress", phase="commentary", text="Reading source content"
            )
            self.queue(dict(method="item/completed", params=commentary))
            params["item"]["phase"] = "final_answer"
        self.queue(dict(method="item/completed", params=params))
        if self.mode == "conflict":
            changed = deepcopy(params)
            changed["item"]["text"] = "Conflicting saved final"
            self.queue(dict(method="item/completed", params=changed))
        if self.mode != "no-terminal":
            self.queue(
                dict(
                    method="turn/completed",
                    params=dict(
                        threadId="fake-thread",
                        turn=dict(id="fake-turn", status="completed"),
                    ),
                )
            )


class FakeRuntime:
    def __init__(self, registration, authenticate, gates, mode):
        path, pin = registration
        spec = source.decode(source.pinned(path, pin))
        self.spec, self.gate = spec, gates[spec["project_ref"]]
        self.mode = mode
        if (
            self.gate["verify_source"]({}) is not True
            or self.gate["admit_spawn"](dict(action={})) is not True
        ):
            raise ValueError("fake spawn refused")
        self.store = FrameJournal(spec["store_path"])
        self.store.bind_project(spec["project_id"], spec["index_sha256"])
        owner = self.store.acquire_owner(spec["project_id"], "synthetic")
        params = dict(
            cwd=spec["source_root"],
            model=spec["model"],
            approvalPolicy="on-request",
            sandbox="read-only",
            config=spec["thread_config"],
        )
        self.store.record_intent(
            spec["project_id"],
            owner,
            "new-thread",
            "thread/start",
            params,
            self.store.snapshot(spec["project_id"])["revision"],
        )
        self.channel = FakeChannel(mode)
        boot = BootstrapSession(
            store=self.store,
            project_id=spec["project_id"],
            owner=owner,
            connection_id="fake-epoch",
            index_sha256=spec["index_sha256"],
            input_version=spec["input_version"],
            intent_key="new-thread",
            channel=self.channel,
            verify_binding=lambda: self.gate["verify_source"]({}),
            admit_lifecycle=lambda a: self.gate["admit_lifecycle"](dict(action=a)),
        )
        boot.open_thread(dict(name="synthetic", version="1"))
        self.controller = InjectedSessionController.adopt_ready(
            boot, admit_action=lambda a: self.gate["admit_action"](dict(action=a))
        )
        self.api = SessionApi(authenticate=authenticate)
        self.api.register(
            spec["project_ref"],
            trusted_stage_unit=spec["kind"] == "NativeStageUnitRuntimeSpec",
            controller=self.controller,
            principals={"local-viewer"},
            source_root=spec["source_root"],
            index_sha256=spec["index_sha256"],
            input_version=spec["input_version"],
            verify_source=lambda _: self.gate["verify_source"]({}),
            start_offer=lambda _: dict(
                project_id=spec["project_id"],
                index_sha256=spec["index_sha256"],
                input_version=spec["input_version"],
                source_root=spec["source_root"],
                model=spec["model"],
                permit_sha256=spec["permit_sha256"],
                limits={
                    k: spec["limits"][k]
                    for k in ("max_text_bytes", "max_starts", "timeout_seconds")
                },
            ),
        )
        self._entries, self.stop = [dict(store=self.store)], threading.Event()
        self.thread = None
        self.closed = False

    def start(self):
        def pump():
            while not self.stop.is_set():
                if self.channel.reads:
                    try:
                        self.controller.pump()
                    except Exception:
                        break
                else:
                    self.stop.wait(0.002)

        self.thread = threading.Thread(target=pump)
        self.thread.start()

    def shutdown(self, timeout=10):
        if not self.closed:
            self.stop.set()
            if self.thread is not None:
                self.thread.join(timeout)
            self.controller.close()
            self.store.close()
            self.closed = True
        return {
            self.spec["project_ref"]: dict(
                leader_reaped=True,
                errors=[],
                synthetic=True,
                journal_cleanup_observed=self.mode != "cleanup-fail",
            )
        }


class StageModelFixture(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.repo = self.root / "repo"
        (self.repo / "plugins/auto-research-agent").mkdir(parents=True)
        self.input_root = self.root / "input"
        self.input_root.mkdir()
        self.index, self.brief = (
            self.input_root / "index.json",
            self.input_root / "brief.json",
        )
        self.index.write_bytes(canonical(dict(project_id="pilot")))
        self.brief.write_bytes(b"synthetic source-bound input")
        self.executable, self.config, self.user = (
            self.root / n for n in ("never-executed.exe", "host.json", "config.toml")
        )
        for path in (self.executable, self.config, self.user):
            path.write_bytes(b"synthetic pinned bytes")
        self.user.write_bytes(b'model="synthetic"\n')
        environment = patch.dict(os.environ, CODEX_HOME=str(self.root))
        environment.start()
        self.addCleanup(environment.stop)
        self.checked = dict(
            source=source,
            repo=self.repo,
            source_root=self.input_root,
            project_id="pilot",
            index_path=self.index,
            index_sha256=sha(self.index.read_bytes()),
            input_path=self.brief,
            input_version=sha(self.brief.read_bytes()),
            thread_config=DENIED_THREAD_CONFIG,
            executable=self.executable,
            user_path=self.user,
            config_path=self.config,
            manifest=dict(
                plugin_files=source.inventory(
                    self.repo / "plugins/auto-research-agent"
                ),
                source_files=source.inventory(self.input_root),
            ),
            stage_inputs={"1": None, "2": None},
            stage_source_sha256=source_digest({}),
        )
        self.allowed, self.mode, self.calls, self.events = True, "complete", [], []

    def model(self, **options):
        from research_workspace_native.stage_model import StageModel

        def admit(event):
            self.events.append(event)
            return self.allowed

        def factory(registrations, **kwargs):
            self.calls.append(registrations)
            runtime = FakeRuntime(
                registrations[0], kwargs["authenticate"], kwargs["gates"], self.mode
            )
            self.runtime = runtime
            self.addCleanup(runtime.shutdown)
            return runtime

        self.instance = StageModel(
            self.checked,
            model="synthetic-model",
            permit_sha256=sha(b"new pilot permit"),
            source_sha256=sha(b"two controlled sources"),
            executable_sha256=sha(self.executable.read_bytes()),
            user_config_sha256=sha(self.user.read_bytes()),
            config_sha256=sha(self.config.read_bytes()),
            authenticate=lambda c: "local-viewer" if c == "token" else None,
            credential="token",
            admit=admit,
            output_root=self.root / "outputs",
            runtime_factory=factory,
            **options,
        )
        return self.instance

    def verify(self, model, receipt, prompt="interpret the controlled sources"):
        return model.verify_receipt(
            receipt,
            expected_prompt_sha256=sha(prompt.encode()),
            expected_source_sha256=sha(b"two controlled sources"),
        )

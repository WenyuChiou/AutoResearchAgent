"""Shared synthetic fixtures for the Codex chat backend tests.

Nothing here starts Codex, opens a network connection or spends anything. The chat
service runs against a scripted ``FakeRpc`` (a protocol transcript, not a model).
"""

# ruff: noqa: E402 -- the plugin and Wiki use repository-local imports.
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(REPO / "plugins/auto-research-agent/cli"),
    str(REPO / "plugins/auto-research-agent/tests"),
]

from harness_chat import ChatService
from harness_chat_tools import HarnessChatTools
from manual_materials import Materials

TOKEN = "wiki-chat-fixture-token-000000000001"
PRINCIPAL = "local-viewer"
BRIEF = "a" * 64
OTHER_BRIEF = "b" * 64


class FakeRpc:
    """Scripted Codex app-server transcript. ``logged_in=False`` and ``silent`` model the two failure shapes."""

    config = {}

    def __init__(
        self,
        record,
        action=None,
        wrong_binding=False,
        question=False,
        duplicate=False,
        logged_in=True,
        silent=False,
    ):
        self.record, self.action, self.wrong, self.question, self.duplicate = (
            record,
            action,
            wrong_binding,
            question,
            duplicate,
        )
        self.logged_in, self.silent = logged_in, silent
        self.sent, self.methods, self.events = [], [], []
        self.resumed = None

    def request(self, method, params, timeout=10):
        self.methods.append(method)
        if method == "initialize":
            return {}
        if method == "account/read":
            return {"account": {"type": "chatgpt"} if self.logged_in else None}
        if method == "account/rateLimits/read":
            return {"rateLimits": {"primary": {"usedPercent": 20}}}
        if method == "model/list":
            return {
                "data": [
                    {
                        "id": "fixture-model",
                        "supportedReasoningEfforts": [{"reasoningEffort": "high"}],
                    }
                ]
            }
        if method in ("thread/start", "thread/resume"):
            self.resumed = params.get("threadId")
            return {
                "thread": {"id": self.resumed or "native-thread-test"},
                "model": "fixture-model",
                "reasoningEffort": "high",
                "approvalPolicy": "on-request",
                "sandbox": {"type": "readOnly"},
            }
        if method == "turn/start":
            base = {
                "threadId": "wrong-thread" if self.wrong else "native-thread-test",
                "turnId": "native-turn-test",
            }
            if self.silent:
                pass
            elif self.action:
                frame = {
                    "id": "request-1",
                    "method": "item/tool/call",
                    "params": dict(
                        base,
                        tool="harness",
                        namespace=None,
                        callId="call-1",
                        arguments=self.action,
                    ),
                }
                self.events.append(frame)
                if self.duplicate:
                    self.events.append(frame)
            elif self.question:
                self.events.append(
                    {
                        "id": "question-1",
                        "method": "item/tool/requestUserInput",
                        "params": dict(
                            base,
                            questions=[
                                dict(id="scope", question="Which scope?", options=[])
                            ],
                        ),
                    }
                )
            else:
                self.events += self.terminal()
            return {"turn": {"id": "native-turn-test"}}
        if method == "turn/interrupt":
            self.events = self.terminal("interrupted")
            return {}
        if method == "thread/read":
            return {
                "thread": {
                    "id": "native-thread-test",
                    "turns": [
                        dict(
                            id="native-turn-test",
                            status="completed",
                            items=[dict(type="agentMessage", text="Recovered final")],
                        )
                    ],
                }
            }
        raise AssertionError(method)

    def terminal(self, status="completed"):
        return [
            dict(
                method="item/completed",
                params=dict(
                    threadId="native-thread-test",
                    turnId="native-turn-test",
                    item=dict(type="agentMessage", text="Harness response saved."),
                ),
            ),
            dict(
                method="turn/completed",
                params=dict(
                    threadId="native-thread-test",
                    turn=dict(id="native-turn-test", status=status),
                ),
            ),
        ]

    def send(self, frame):
        self.sent.append(frame)
        if "result" in frame and not any(
            x.get("method") == "turn/completed" for x in self.events
        ):
            self.events += self.terminal()

    def next(self):
        if self.events:
            return self.events.pop(0)
        time.sleep(0.01)
        raise TimeoutError()

    def close(self):
        return {"leader_stopped": True}


class FakeProjects:
    """The ``host.projects.read`` shape of the real intake store, with a mutable input version."""

    def __init__(self):
        self.records = {}

    def add(
        self,
        ref,
        project_id,
        input_version=1,
        brief=BRIEF,
        topic="Aircraft fault diagnosis with sensor drift",
    ):
        self.records[ref] = dict(
            project_ref=ref,
            project_id=project_id,
            input_version=input_version,
            revision=1,
            brief_sha256=brief,
            brief={"original_description": topic},
        )

    def read(self, credential, ref):
        if credential != TOKEN or ref not in self.records:
            raise ValueError("project-unavailable")
        return json.loads(json.dumps(self.records[ref]))

    def binding(self, ref):
        value = self.records[ref]
        return {
            k: value[k]
            for k in ("project_ref", "project_id", "input_version", "brief_sha256")
        }


class ChatFixture:
    """A project store, a material store with one readable Stage 1 text file, and grant/service builders."""

    def __init__(self, case, ref="project-alpha", project_id="pid-alpha"):
        self.case = case
        self.root = Path(
            case.enterContext(tempfile.TemporaryDirectory(prefix="chat-"))
        ).resolve()
        incoming = self.root / "incoming"
        incoming.mkdir()
        self.ref, self.project_id = ref, project_id
        self.projects = FakeProjects()
        self.projects.add(ref, project_id)
        self.host = SimpleNamespace(credential=TOKEN, projects=self.projects)
        self.store = Materials(self.root / "materials", incoming, [])
        self.text = self.register_text(
            ref, 1, "notes.md", "Saved reading note for the chat fixture.\n".encode()
        )
        self.tools = HarnessChatTools(self.host, self.store)
        self.rpcs = []

    def register_text(self, ref, stage, name, data):
        pin = hashlib.sha256(data).hexdigest()
        item = self.store.begin_upload(
            dict(project_ref=ref, name=name, stage=stage, bytes=len(data), sha256=pin)
        )
        if data:
            self.store.upload_chunk(
                dict(id=item["id"], offset=0, base64=base64.b64encode(data).decode())
            )
        return self.store.finish_upload(dict(id=item["id"]))

    def binding(self, ref=None):
        return self.projects.binding(ref or self.ref)

    def grant(self, **override):
        """A legacy-shape chat grant dict (what ``load_config`` returns), bound to this project and version."""
        spec = dict(
            expires_at=time.time() + 600,
            max_turns=3,
            turn_seconds=10,
            previous_calls=0,
            previous_seconds=0,
            max_calls=3,
            max_seconds=100,
            pins={},
            model="fixture-model",
            effort="high",
            budget_path=str(self.root / "quota.sqlite3"),
            principal=PRINCIPAL,
            stages=[1, 2, 3, 4, 5, 6],
            bindings=[self.binding()],
            money_cap_usd=None,
        )
        spec.update(override)
        return spec

    def service(self, spec=None, **rpc):
        def factory(record):
            fake = FakeRpc(record, **rpc)
            self.rpcs.append(fake)
            return fake

        service = ChatService(
            self.root / "chat", self.tools, spec or self.grant(), rpc_factory=factory
        )
        self.case.addCleanup(service.close)
        return service

    def body(
        self,
        text="Read my notes",
        key="unique-request-0001",
        stage=1,
        session=None,
        ref=None,
        **extra,
    ):
        binding = self.binding(ref)
        return dict(
            project_ref=binding["project_ref"],
            stage=stage,
            text=text,
            key=key,
            session_id=session,
            input_version=binding["input_version"],
            brief_sha256=binding["brief_sha256"],
            **extra,
        )

    def send(self, service, **kwargs):
        return service.start(self.body(**kwargs), PRINCIPAL)

    def wait(self, service, turn, status):
        deadline = time.monotonic() + 8
        row = None
        while time.monotonic() < deadline:
            row = service.get("turns", turn["id"])
            if row["status"] in status:
                return row
            time.sleep(0.02)
        self.case.fail(str(row))

    def finished(self, service, turn):
        row = self.wait(
            service, turn, {"completed", "failed", "interrupted", "unknown"}
        )
        worker = service.running.get(turn["id"], {}).get("thread")
        if worker:
            worker.join(2)
        return row

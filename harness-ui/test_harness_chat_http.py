"""The chat routes on the real loopback ProjectHost with the real project store; scripted Codex only."""

# ruff: noqa: E402 -- the plugin and Wiki use repository-local imports.
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(REPO / "plugins/auto-research-agent/cli"),
    str(REPO / "plugins/auto-research-agent/tests"),
]

from research_workspace_native.http import token_authenticator
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_intake import ProjectIntakeService
from test_workspace_project_intake import compile_body, submit_body

from chat_test_fixtures import TOKEN, FakeRpc
from current_chat_host import install_wiki_chat
from harness_chat_http import install_chat
from manual_materials import Materials
import chat_test_fixtures as fixtures


class HostFixture:
    """A real ProjectHost over a real intake project with one registered Stage 1 note."""

    def __init__(self, case, *, spec_factory=None, rpc_factory=None, options=None):
        self.case = case
        self.root = Path(
            case.enterContext(tempfile.TemporaryDirectory(prefix="chat-http-"))
        ).resolve()
        self.intake = ProjectIntakeService(
            self.root / "p",
            authenticate=token_authenticator({TOKEN: fixtures.PRINCIPAL}),
        )
        case.addCleanup(self.intake.close)
        self.host = ProjectHost(
            projects=self.intake, credential=TOKEN, files={}, views=[], port=0
        )
        case.addCleanup(self.host.server_close)
        self.ref = self.intake.create(
            TOKEN,
            {"key": "chat-http", "topic": "Aircraft fault diagnosis with sensor drift"},
        )["project_ref"]
        view = self.intake.read(TOKEN, self.ref)
        self.intake.submit(TOKEN, self.ref, submit_body(view))
        self.intake.compile(
            TOKEN, self.ref, compile_body(self.intake.read(TOKEN, self.ref))
        )
        incoming = self.root / "incoming"
        incoming.mkdir()
        self.store = Materials(self.root / "materials", incoming, [])
        helper = fixtures.ChatFixture.register_text
        self.note = helper(
            self, self.ref, 1, "notes.md", b"Real-project note for the HTTP test.\n"
        )
        self.chat_root = self.root / "chat"
        self.service = None
        if options is not None:
            self.service = install_wiki_chat(self.host, self.store, options)
        else:
            spec = spec_factory(self) if spec_factory else None
            self.service = install_chat(
                self.host, self.store, self.chat_root, spec, rpc_factory=rpc_factory
            )
        thread = threading.Thread(target=self.host.serve_forever, daemon=True)
        thread.start()
        case.addCleanup(
            lambda: (self.service.close(), self.host.shutdown(), thread.join(2))
        )
        self.url = "http://127.0.0.1:" + str(self.host.server_address[1])

    def binding(self):
        view = self.intake.read(TOKEN, self.ref)
        return {
            k: view[k]
            for k in ("project_ref", "project_id", "input_version", "brief_sha256")
        }

    def grant(self, **override):
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
            principal=fixtures.PRINCIPAL,
            stages=[1, 2, 3],
            bindings=[self.binding()],
            money_cap_usd=None,
        )
        spec.update(override)
        return spec

    def call(self, path, body=None, auth=True, origin=None):
        headers = {"Origin": origin or self.url}
        if auth:
            headers["Authorization"] = "Bearer " + TOKEN
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            self.url + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
        )
        try:
            with urlopen(request, timeout=5) as result:
                return result.status, json.load(result)
        except HTTPError as error:
            return error.code, json.load(error)

    def send_body(self, **extra):
        binding = self.binding()
        return dict(
            project_ref=self.ref,
            stage=1,
            text="Read my note",
            key="http-unique-request-0001",
            session_id=None,
            input_version=binding["input_version"],
            brief_sha256=binding["brief_sha256"],
            **extra,
        )

    def wait(self, turn_id, status):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            row = self.service.get("turns", turn_id)
            if row["status"] in status:
                return row
            time.sleep(0.02)
        self.case.fail(str(row))


class ChatHttp(unittest.TestCase):
    def state_path(self, fx, stage=1, project=None):
        return (
            "/api/v9/chat/state?project=" + (project or fx.ref) + "&stage=" + str(stage)
        )

    def test_real_host_auth_state_send_replay_and_stale_version(self):
        holder = {}
        fx = HostFixture(
            self,
            spec_factory=lambda f: f.grant(),
            rpc_factory=lambda r: FakeRpc(
                r, action=dict(action="read_material", id=holder["note"], note="")
            ),
        )
        holder["note"] = fx.note["id"]
        self.assertEqual(fx.call(self.state_path(fx), auth=False)[0], 401)
        self.assertEqual(
            fx.call(self.state_path(fx), origin="https://untrusted.example")[0], 403
        )
        code, missing = fx.call(self.state_path(fx, project="project-missing"))
        self.assertEqual((code, missing["error"]), (404, "project-unavailable"))
        code, view = fx.call(self.state_path(fx))
        self.assertEqual(code, 200, view)
        self.assertEqual(
            (view["panel_state"], view["can_send"], view["enabled"]),
            ("ready", True, True),
        )
        self.assertTrue(view["connect_check"]["ok"] and view["spend_check"]["ok"])
        self.assertEqual(view["binding"], fx.binding())
        self.assertEqual(
            [m["readable"]["ok"] for m in view["context"]["materials"]], [True]
        )
        self.assertEqual(
            (
                view["read_only"],
                view["execution_authorized"],
                view["research_execution"],
            ),
            (True, False, False),
        )
        body = fx.send_body()
        stale = dict(body, input_version=body["input_version"] + 1)
        code, refused = fx.call(
            "/api/v9/chat/send", dict(stale, key="http-unique-request-0002")
        )
        self.assertEqual(
            (code, refused["error"], refused["reason"]["group"]),
            (409, "chat-input-version-differs", "stale-version"),
        )
        self.assertEqual(
            fx.call("/api/v9/chat/send", {"project_ref": fx.ref})[1]["error"],
            "chat-start-fields-invalid",
        )
        code, turn = fx.call("/api/v9/chat/send", body)
        self.assertEqual(code, 200, turn)
        done = fx.wait(turn["id"], {"completed", "failed", "unknown"})
        self.assertEqual(done["status"], "completed", done)
        self.assertEqual(fx.call("/api/v9/chat/send", body)[1]["id"], turn["id"])
        state = fx.call(self.state_path(fx))[1]
        self.assertEqual((state["reserved_turns"], len(state["turns"])), (1, 1))
        self.assertEqual(
            state["turns"][0]["outputs"][0]["value"]["material_id"], fx.note["id"]
        )
        self.assertEqual(fx.call(self.state_path(fx, stage=2))[1]["turns"], [])

    def test_non_string_ids_are_answered_400_and_never_break_the_connection(self):
        fx = HostFixture(
            self, spec_factory=lambda f: f.grant(), rpc_factory=lambda r: FakeRpc(r)
        )
        for route, body in (
            ("stop", {"turn_id": {}}),
            ("reconcile", {"turn_id": ["x"]}),
            ("stop", {"turn_id": 7}),
            ("send", dict(fx.send_body(), session_id={"a": 1})),
            (
                "answer",
                {"turn_id": "t", "request_id": {}, "request_sha256": "h", "value": {}},
            ),
        ):
            code, value = fx.call("/api/v9/chat/" + route, body)
            self.assertEqual(
                (code, value["error"]), (400, "invalid-id-type"), (route, body)
            )
        self.assertEqual(fx.call(self.state_path(fx))[0], 200, "server still answers")
        self.assertEqual(
            fx.service.status(fx.ref, 1, fixtures.PRINCIPAL)["reserved_turns"], 0
        )

    def test_unknown_routes_and_bad_queries(self):
        fx = HostFixture(
            self, spec_factory=lambda f: f.grant(), rpc_factory=lambda r: FakeRpc(r)
        )
        self.assertEqual(fx.call("/api/v9/chat/other?project=x&stage=1")[0], 404)
        self.assertEqual(
            fx.call("/api/v9/chat/state?project=x&stage=1&extra=1")[0], 404
        )
        self.assertEqual(
            fx.call(self.state_path(fx, stage=9))[1]["error"],
            "chat-stage-not-supported",
        )
        self.assertEqual(fx.call("/api/v9/chat/delete", {})[0], 404)
        self.assertEqual(
            fx.call("/api/v9/chat/stop", {"turn_id": "x", "extra": 1})[0], 404
        )

    def test_default_install_reports_not_configured_and_creates_nothing(self):
        fx = HostFixture(self)
        self.assertFalse(fx.chat_root.exists())
        code, view = fx.call(self.state_path(fx))
        self.assertEqual(code, 200, view)
        self.assertEqual(
            (
                view["panel_state"],
                view["enabled"],
                view["can_send"],
                view["content_hidden"],
            ),
            ("not-configured", False, False, True),
        )
        self.assertEqual(view["panel_reason"]["text"], "本机还没有配置对话")
        for route, body in (
            ("send", fx.send_body()),
            (
                "answer",
                {
                    "turn_id": "t",
                    "request_id": "r",
                    "request_sha256": "s",
                    "value": True,
                },
            ),
            ("stop", {"turn_id": "t"}),
            ("reconcile", {"turn_id": "t"}),
        ):
            code, refused = fx.call("/api/v9/chat/" + route, body)
            self.assertEqual(
                (code, refused["error"]), (409, "operator-chat-config-required"), route
            )
        self.assertFalse(fx.chat_root.exists())
        stores = {p.name for p in fx.root.rglob("*.sqlite3")}
        self.assertFalse(stores & {"conversations.sqlite3", "quota.sqlite3"}, stores)

    def test_startup_options_are_all_or_nothing_and_bad_grant_stays_inert(self):
        from argparse import Namespace

        fx_options = Namespace(
            chat_config=None,
            chat_config_sha256=None,
            chat_root=None,
            chat_permit_receipt=None,
            chat_permit_receipt_sha256=None,
            chat_permit_key=None,
        )
        none = HostFixture(self, options=fx_options)
        self.assertEqual(
            none.call(self.state_path(none))[1]["panel_state"], "not-configured"
        )
        with self.assertRaisesRegex(ValueError, "chat-config together with"):
            install_wiki_chat(
                none.host,
                none.store,
                Namespace(**dict(vars(fx_options), chat_root=Path("x"))),
            )
        bad = Path(tempfile.mkdtemp(prefix="chat-grant-")) / "grant.json"
        bad.write_text("{}", encoding="utf-8")
        broken = Namespace(
            **dict(
                vars(fx_options),
                chat_config=bad,
                chat_config_sha256="0" * 64,
                chat_root=Path(tempfile.gettempdir()) / "ara-never-created",
            )
        )
        fx = HostFixture(self, options=broken)
        view = fx.call(self.state_path(fx))[1]
        self.assertEqual(
            (view["panel_state"], view["disabled_reason"], view["can_send"]),
            ("not-configured", "chat-config-pin-differs", False),
        )
        self.assertFalse((Path(tempfile.gettempdir()) / "ara-never-created").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)

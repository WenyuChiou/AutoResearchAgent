"""The four rules of the Wiki V1 Codex chat contract, each with a passing and a refused case.

Contract: topics/project-coordination/briefs/WIKI-V1-CODEX-CHAT-CONTRACT.md. Scripted Codex only;
the Codex process channel (the only place a process is launched) is patched to fail, and
the zero-allowance tests also patch ``subprocess.Popen`` itself.
"""

# ruff: noqa: E402 -- the plugin and Wiki use repository-local imports.
import hashlib
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from chat_test_fixtures import PRINCIPAL, ChatFixture, FakeRpc
from harness_chat import ChatService, load_config
from harness_chat_tools import encoded

CODES = lambda view: [
    r["code"] for r in view["connect_check"]["reasons"] + view["spend_check"]["reasons"]
]  # noqa: E731


class Base(unittest.TestCase):
    def setUp(self):
        self.fx = ChatFixture(self)
        self.channel = patch(
            "native_stage1._ProcessChannel",
            side_effect=AssertionError("native-process-forbidden"),
        ).start()
        self.popen = None
        self.addCleanup(patch.stopall)

    def forbid_popen(self):
        self.popen = patch(
            "subprocess.Popen", side_effect=AssertionError("native-process-forbidden")
        ).start()

    def tearDown(self):
        self.assertEqual(self.channel.call_count, 0)
        if self.popen is not None:
            self.assertEqual(self.popen.call_count, 0)

    def ledger(self, service):
        with service.db() as db:
            return (
                db.execute(
                    "SELECT turns,seconds FROM quota.budget WHERE id=1"
                ).fetchone(),
                db.execute("SELECT COUNT(*) FROM turns").fetchone()[0],
            )

    def grant_file(self, **override):
        fx = self.fx
        exe, config = fx.root / "codex.exe", fx.root / "config.toml"
        exe.write_bytes(b"fixture, never executed")
        config.write_text("", encoding="utf-8")
        spec = dict(
            executable=str(exe),
            config_path=str(config),
            model="fixture-model",
            effort="high",
            expires_at=time.time() + 600,
            max_turns=3,
            turn_seconds=10,
            previous_calls=0,
            previous_seconds=0,
            max_calls=3,
            max_seconds=100,
            pins={},
            authorization="fixture-test-grant",
            budget_path=str(fx.root / "quota.sqlite3"),
            principal=PRINCIPAL,
            bindings=[fx.binding()],
            stages=[1, 2],
            money_cap_usd=None,
        )
        spec.update(override)
        path = fx.root / "grant.json"
        path.write_bytes(encoded(spec))
        return path, hashlib.sha256(path.read_bytes()).hexdigest()


class Rule1Login(Base):
    """No login: only the login explanation, and no model call."""

    def test_logged_in_codex_completes_and_panel_is_ready(self):
        fx = self.fx
        service = fx.service()
        self.assertEqual(fx.finished(service, fx.send(service))["status"], "completed")
        self.assertEqual(service.status(fx.ref, 1, PRINCIPAL)["panel_state"], "ready")

    def test_codex_not_logged_in_shows_login_text_hides_content_and_calls_no_model(
        self,
    ):
        fx = self.fx
        service = fx.service(logged_in=False)
        before = service.status(fx.ref, 1, PRINCIPAL)
        self.assertEqual(
            (before["panel_state"], before["can_send"], before["codex_login"]),
            ("ready", True, "unknown-until-send"),
        )
        turn = fx.finished(service, fx.send(service))
        self.assertEqual(turn["status"], "failed")
        self.assertIn("codex-login-required", turn["error"])
        self.assertTrue({"initialize", "account/read"} <= set(fx.rpcs[0].methods))
        self.assertFalse(
            {"thread/start", "turn/start", "model/list"} & set(fx.rpcs[0].methods)
        )
        view = service.status(fx.ref, 1, PRINCIPAL)
        self.assertEqual(
            (view["panel_state"], view["codex_login"], view["content_hidden"]),
            ("login-required", "logged-out", True),
        )
        self.assertEqual(
            (view["sessions"], view["turns"], view["context"]["materials"]),
            ([], [], []),
        )
        self.assertEqual(view["panel_reason"]["text"], "还没登录 Codex")


class Rule2Permit(Base):
    """Sending needs a conversation permit for this exact project and input version."""

    def test_matching_permit_sends(self):
        fx = self.fx
        service = fx.service()
        view = service.status(fx.ref, 1, PRINCIPAL)
        self.assertEqual((view["panel_state"], view["can_send"]), ("ready", True))
        self.assertEqual(fx.finished(service, fx.send(service))["status"], "completed")

    def test_permit_for_another_project_refuses_but_materials_stay_readable(self):
        fx = self.fx
        fx.projects.add("project-beta", "pid-beta")
        service = fx.service(fx.grant(bindings=[fx.binding("project-beta")]))
        view = service.status(fx.ref, 1, PRINCIPAL)
        self.assertEqual(
            (view["panel_state"], view["can_send"], view["content_hidden"]),
            ("no-permit", False, False),
        )
        self.assertIn("Stage 1 整轮运行的同意书不能代用", view["panel_reason"]["text"])
        self.assertEqual(
            [m["name"] for m in view["context"]["materials"]], ["notes.md"]
        )
        with self.assertRaisesRegex(ValueError, "project-stage-not-authorized"):
            fx.send(service)
        self.assertEqual(self.ledger(service), (None, 0))
        self.assertEqual(fx.rpcs, [])

    def test_new_input_version_invalidates_the_old_permit(self):
        fx = self.fx
        service = fx.service()
        old_body = fx.body()
        fx.projects.records[fx.ref]["input_version"] = 2
        view = service.status(fx.ref, 1, PRINCIPAL)
        self.assertEqual((view["panel_state"], view["can_send"]), ("blocked", False))
        self.assertIn("chat-grant-binding-differs-from-current-project", CODES(view))
        with self.assertRaisesRegex(ValueError, "binding-differs"):
            fx.send(service)
        with self.assertRaisesRegex(ValueError, "binding-differs"):
            service.start(dict(old_body, key="unique-request-0002"), PRINCIPAL)
        self.assertEqual(self.ledger(service), (None, 0))

    def test_changed_brief_or_stale_page_version_is_refused_and_exact_version_passes(
        self,
    ):
        fx = self.fx
        service = fx.service()
        stale = dict(fx.body(), input_version=2)
        with self.assertRaisesRegex(ValueError, "chat-input-version-differs"):
            service.start(stale, PRINCIPAL)
        for wrong in (True, "1", 1.0):
            with self.assertRaisesRegex(ValueError, "chat-input-version-differs"):
                service.start(dict(fx.body(), input_version=wrong), PRINCIPAL)
        with self.assertRaisesRegex(ValueError, "chat-input-version-differs"):
            service.start(dict(fx.body(), brief_sha256="f" * 64), PRINCIPAL)
        self.assertEqual(self.ledger(service), (None, 0))
        self.assertEqual(fx.finished(service, fx.send(service))["status"], "completed")

    def test_stage_not_covered_or_wrong_person_is_refused(self):
        fx = self.fx
        service = fx.service(fx.grant(stages=[1]))
        with self.assertRaisesRegex(ValueError, "project-stage-not-authorized"):
            fx.send(service, stage=2)
        with self.assertRaisesRegex(ValueError, "chat-principal-differs"):
            service.start(fx.body(), "someone-else")
        with self.assertRaisesRegex(ValueError, "chat-principal-differs"):
            service.start(fx.body(), None)
        self.assertEqual(self.ledger(service), (None, 0))

    def test_stage_one_progression_consent_cannot_stand_in_for_a_chat_permit(self):
        fx = self.fx
        binding = fx.binding()
        consent = dict(
            kind="ProjectStageProgressionConsent",
            schema_version="1.0.0",
            confirmed=True,
            expires_at="2099-01-01T00:00:00+00:00",
            settings_sha256="d" * 64,
            stages={"stage1": dict(profile_sha256="e" * 64, max_dispatches=1)},
            **binding,
        )
        path = fx.root / "consent.json"
        path.write_bytes(encoded(consent))
        with self.assertRaisesRegex(ValueError, "chat-config-fields-differ"):
            load_config(path, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_expired_revoked_and_unenforceable_money_cap_refuse(self):
        fx = self.fx
        path, pin = self.grant_file()
        spec = load_config(path, pin)
        service = ChatService(
            fx.root / "chat", fx.tools, spec, rpc_factory=lambda r: self.fail("no rpc")
        )
        self.addCleanup(service.close)
        self.assertEqual(service.status(fx.ref, 1, PRINCIPAL)["panel_state"], "ready")
        Path(str(path) + ".revoked").write_text("operator", encoding="utf-8")
        view = service.status(fx.ref, 1, PRINCIPAL)
        self.assertEqual(
            (view["panel_state"], view["enabled"], view["can_send"]),
            ("blocked", False, False),
        )
        self.assertIn("已被操作者撤销", view["panel_reason"]["text"])
        with self.assertRaisesRegex(ValueError, "chat-permit-revoked"):
            fx.send(service)
        Path(str(path) + ".revoked").unlink()
        expired = fx.service(fx.grant(expires_at=time.time() - 1))
        view = expired.status(fx.ref, 1, PRINCIPAL)
        self.assertEqual((view["panel_state"], view["can_send"]), ("blocked", False))
        self.assertIn("对话许可已到期", view["panel_reason"]["text"])
        capped_path, capped_pin = self.grant_file(money_cap_usd=5)
        with self.assertRaisesRegex(ValueError, "chat-money-cap-not-enforceable"):
            load_config(capped_path, capped_pin)
        capped = fx.service(fx.grant(money_cap_usd=5))
        view = capped.status(fx.ref, 1, PRINCIPAL)
        self.assertEqual(
            view["panel_reason"]["text"], "服务无法执行金额上限，所以不发送"
        )
        with self.assertRaisesRegex(ValueError, "money-cap-not-enforceable"):
            fx.send(capped)

    def test_both_gates_report_separately(self):
        fx = self.fx
        service = fx.service(fx.grant(max_turns=0))
        view = service.status(fx.ref, 1, PRINCIPAL)
        self.assertTrue(view["connect_check"]["ok"])
        self.assertFalse(view["spend_check"]["ok"])
        self.assertEqual(
            view["spend_check"]["reasons"][0]["text"], "调用次数已用完，不会自动追加"
        )
        self.assertEqual(
            (view["spend_check"]["remaining_turns"], view["can_send"]), (0, False)
        )


class Rule3NoDoubleCharge(Base):
    """A repeat or a timeout never charges twice and never resends by itself."""

    def test_repeated_request_replays_the_saved_turn(self):
        fx = self.fx
        service = fx.service()
        first = fx.finished(service, fx.send(service))
        self.assertEqual(self.ledger(service), ((1, 10), 1))
        again = fx.send(service)
        self.assertEqual(again["id"], first["id"])
        self.assertEqual((self.ledger(service), len(fx.rpcs)), (((1, 10), 1), 1))
        with self.assertRaisesRegex(ValueError, "chat-idempotency-conflict"):
            fx.send(service, text="A different message under the same key")
        self.assertEqual((self.ledger(service), len(fx.rpcs)), (((1, 10), 1), 1))

    def test_repeat_after_the_permit_lapsed_is_still_a_read(self):
        fx = self.fx
        spec = fx.grant()
        service = fx.service(spec)
        first = fx.finished(service, fx.send(service))
        spec["expires_at"] = time.time() - 1
        self.assertEqual(fx.send(service)["id"], first["id"])
        with self.assertRaisesRegex(ValueError, "lease-expired"):
            fx.send(service, key="unique-request-0002")
        self.assertEqual(self.ledger(service), ((1, 10), 1))

    def test_timeout_keeps_the_reservation_and_never_resends(self):
        fx = self.fx
        service = fx.service(fx.grant(turn_seconds=1), silent=True)
        turn = fx.send(service)
        row = fx.finished(service, turn)
        self.assertEqual(
            (row["status"], row["error"]),
            ("unknown", "chat-deadline-native-terminal-unconfirmed"),
        )
        self.assertEqual(fx.rpcs[0].methods.count("turn/start"), 1)
        view = service.status(fx.ref, 1, PRINCIPAL)
        self.assertEqual(
            (view["panel_state"], view["can_send"], view["reserved_turns"]),
            ("unknown-result", False, 1),
        )
        self.assertEqual(
            view["turns"][0]["error_reason"]["text"], "这一轮的结果还没确认"
        )
        with self.assertRaisesRegex(ValueError, "unresolved"):
            fx.send(service, key="unique-request-0002")
        self.assertEqual(fx.send(service)["id"], turn["id"])
        self.assertEqual((self.ledger(service), len(fx.rpcs)), (((1, 1), 1), 1))
        recovered = service.reconcile(turn["id"])
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(sum(r.methods.count("turn/start") for r in fx.rpcs), 1)
        self.assertEqual(self.ledger(service), ((1, 1), 1))

    def test_started_elsewhere_blocks_every_project_until_reconciled(self):
        fx = self.fx
        fx.projects.add("project-beta", "pid-beta")
        spec = fx.grant(
            bindings=[fx.binding(), fx.binding("project-beta")],
            max_turns=5,
            max_calls=5,
            max_seconds=200,
        )
        service = fx.service(
            spec, wrong_binding=True, action=dict(action="state", id="", note="")
        )
        held = fx.finished(service, fx.send(service))
        self.assertEqual(held["status"], "unknown")
        view = service.status("project-beta", 1, PRINCIPAL)
        self.assertEqual((view["panel_state"], view["can_send"]), ("other-turn", False))
        self.assertEqual(
            (view["other_turn"]["project_ref"], view["other_turn"]["stage"]),
            (fx.ref, 1),
        )


class Rule4NoDecisionsByChat(Base):
    """Asking questions can never pick a direction, approve a plan or start research."""

    def test_read_only_question_is_answered(self):
        fx = self.fx
        service = fx.service(action=dict(action="materials", id="", note=""))
        turn = fx.finished(service, fx.send(service))
        self.assertEqual(turn["status"], "completed")
        self.assertEqual(
            turn["outputs"][0]["value"]["materials"][0]["name"], "notes.md"
        )

    def test_offered_tool_has_read_actions_only(self):
        fx = self.fx
        spec = fx.tools.specs()[0]["inputSchema"]["properties"]["action"]["enum"]
        self.assertEqual(spec, ["state", "materials", "read_material"])
        self.assertFalse(fx.tools.writes(dict(action="read_material", id="", note="")))
        for stage in range(1, 7):
            context = fx.tools.context(fx.ref, stage)
            self.assertEqual(context["supported_actions"][:1], ["state"])
            self.assertTrue(
                set(context["supported_actions"])
                <= {"state", "materials", "read_material"}
            )
            self.assertFalse(
                context["capabilities"]["formal_selection"]
                or context["capabilities"]["research_execution"]
            )
            self.assertFalse(
                context["capabilities"]["material_registration"]
                or context["capabilities"]["local_review_notes"]
            )

    def test_model_asking_for_a_decision_or_write_is_refused_and_nothing_changes(self):
        fx = self.fx
        project_before = json.dumps(fx.projects.records, sort_keys=True)
        catalog_before = json.dumps(fx.store.catalog(), sort_keys=True)
        service = fx.service(fx.grant(max_turns=20, max_calls=20, max_seconds=400))
        for index, action in enumerate(
            (
                "select_candidate",
                "register_delivery",
                "save_review",
                "prepare_workflow",
                "prepare_advice",
                "approve_plan",
                "start_research",
            )
        ):
            fake = []

            def factory(record, action=action, fake=fake):
                fake.append(
                    FakeRpc(
                        record,
                        action=dict(
                            action=action, id=fx.text["id"], note="Choose direction A"
                        ),
                    )
                )
                return fake[0]

            service.rpc_factory = factory
            row = fx.finished(
                service, fx.send(service, key="unique-decision-key-%04d" % index)
            )
            self.assertEqual((row["status"], row["outputs"]), ("completed", []), action)
            result = fake[0].sent[-1]["result"]
            self.assertFalse(result["success"], action)
            self.assertIn("Harness rejected", result["contentItems"][0]["text"])
        self.assertEqual(
            json.dumps(fx.projects.records, sort_keys=True), project_before
        )
        self.assertEqual(json.dumps(fx.store.catalog(), sort_keys=True), catalog_before)

    def test_status_never_claims_a_decision_or_execution(self):
        fx = self.fx
        service = fx.service()
        fx.finished(service, fx.send(service))
        view = service.status(fx.ref, 1, PRINCIPAL)
        self.assertEqual(
            (
                view["formal_selection"],
                view["execution_authorized"],
                view["research_execution"],
                view["read_only"],
            ),
            (False, False, False, True),
        )


class ZeroAllowanceNeverStartsCodex(Base):
    """With no allowance, no path may launch Codex: no grant, exhausted, expired or zero-turn grants."""

    def assert_nothing_started(self, service, fx):
        for call in (
            lambda: fx.send(service),
            lambda: service.answer(
                dict(turn_id="t", request_id="r", request_sha256="s", value=True)
            ),
            lambda: service.stop("turn-none"),
            lambda: service.reconcile("turn-none"),
        ):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(fx.rpcs, [])
        self.assertEqual(self.channel.call_count, 0)

    def test_no_grant_at_all(self):
        from harness_chat_http import UnconfiguredChat

        fx = self.fx
        self.forbid_popen()
        service = UnconfiguredChat()
        self.assert_nothing_started(service, fx)
        self.assertFalse(service.status(fx.ref, 1, PRINCIPAL)["can_send"])

    def test_zero_turn_grant_exhausted_expired_each_refuse_without_rpc_or_reservation(
        self,
    ):
        fx = self.fx
        self.forbid_popen()
        cases = dict(
            zero=fx.grant(max_turns=0),
            exhausted=fx.grant(previous_calls=3, previous_seconds=0),
            seconds=fx.grant(previous_seconds=95),
            expired=fx.grant(expires_at=time.time() - 1),
        )
        for name, spec in cases.items():
            with self.subTest(name):
                fx.rpcs.clear()
                service = ChatService(
                    fx.root / ("chat-" + name),
                    fx.tools,
                    dict(spec, budget_path=str(fx.root / (name + ".sqlite3"))),
                    rpc_factory=None,
                )
                self.addCleanup(service.close)
                view = service.status(fx.ref, 1, PRINCIPAL)
                self.assertFalse(view["can_send"])
                self.assertEqual(view["reserved_turns"], 0)
                self.assert_nothing_started(service, fx)
                self.assertEqual(self.ledger(service), (None, 0))
                if name != "expired":
                    self.assertEqual(view["remaining_turns"], 0)

    def test_zero_allowance_over_real_http_never_starts_anything(self):
        from test_harness_chat_http import HostFixture

        host = HostFixture(
            self, spec_factory=lambda f: f.grant(max_turns=0), rpc_factory=None
        )
        self.forbid_popen()
        code, refused = host.call("/api/v9/chat/send", host.send_body())
        self.assertEqual(
            (code, refused["error"], refused["reason"]["text"]),
            (409, "chat-cumulative-budget-exhausted", "调用次数已用完，不会自动追加"),
        )
        for route, body in (
            (
                "answer",
                dict(turn_id="t", request_id="r", request_sha256="s", value=True),
            ),
            ("stop", dict(turn_id="t")),
            ("reconcile", dict(turn_id="t")),
        ):
            self.assertEqual(host.call("/api/v9/chat/" + route, body)[0], 409, route)
        state = host.call("/api/v9/chat/state?project=" + host.ref + "&stage=1")[1]
        self.assertEqual(
            (state["can_send"], state["reserved_turns"], state["turns"]), (False, 0, [])
        )
        self.assertEqual(self.ledger(host.service), (None, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)

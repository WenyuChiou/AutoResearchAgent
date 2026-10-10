"""SQLite + fake content providers; no native, actual model, source or search I/O."""

from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import http.client
import json
from pathlib import Path, PureWindowsPath
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_model import ProjectModelService, budget_digest
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.session_api import SessionApiError
from stage1_brief.brief import validate_bound_plan
from stage1_deliverable.common import canonical, sha
from test_stage1_coverage import proposal


def authenticate(token):
    return {"alice-token": "alice", "bob-token": "bob"}.get(token)


class FakeProvider:
    """A synthetic provider whose I/O counter follows real broker admission."""

    def __init__(self, harness, context, admit, output):
        self.harness, self.context, self.admit, self.output = (
            harness,
            context,
            admit,
            output,
        )

    def run(self, key, prompt, deadline):
        self.harness.assertFalse(self.harness.intake.db.in_transaction)
        with closing(
            sqlite3.connect(self.harness.root / "project-intake.sqlite")
        ) as db:
            state = json.loads(
                db.execute(
                    "SELECT state FROM intake_projects WHERE ref=?",
                    (self.context["project_ref"],),
                ).fetchone()[0]
            )
        self.harness.assertEqual(
            state["model_operations"]["calls_reserved"], self.harness.factories
        )
        self.harness.assertEqual(
            state["model_operations"]["jobs"][self.harness.key]["status"], "running"
        )
        event = dict(
            phase="reserve",
            unit_key=key,
            prompt_sha256=sha(prompt.encode()),
            source_sha256=self.context["source_sha256"],
            permit_sha256=self.context["permit_sha256"],
            event={},
        )
        self.admit(event)
        self.admit({**event, "phase": "spawn"})
        self.harness.io += 1
        if self.harness.release is not None:
            self.harness.release.wait(20)
        if self.harness.failure is not None:
            raise self.harness.failure
        return dict(
            status="completed",
            prompt_sha256=sha(prompt.encode()),
            source_sha256=self.context["source_sha256"],
            final_text=self.output,
            usage=None,
            cost=None,
            synthetic=True,
        )

    def verify_receipt(self, receipt, **expected):
        self.harness.assertEqual(
            receipt["prompt_sha256"], expected["expected_prompt_sha256"]
        )
        self.harness.assertEqual(
            receipt["source_sha256"], expected["expected_source_sha256"]
        )
        return receipt

    def status(self):
        self.harness.status_reads += 1
        if self.harness.native_status_failure is not None:
            raise self.harness.native_status_failure
        return {
            "native_view": {
                "project_ref": self.context["project_ref"],
                "project_id": self.context["project_id"],
                "index_sha256": "a" * 64,
                "input_version": "b" * 64,
                "revision": 3,
                "requests": [
                    {
                        "request_ref": "opaque-question",
                        "request_sha256": "c" * 64,
                        "method": "item/tool/requestUserInput",
                        "status": "pending",
                        "payload": {"questions": [{"id": "scope"}]},
                    },
                    *[
                        {
                            "request_ref": "opaque-" + decision,
                            "request_sha256": "c" * 64,
                            "method": "item/commandExecution/requestApproval",
                            "status": "pending",
                            "payload": {},
                        }
                        for decision in ("decline", "cancel")
                    ],
                ],
                "operations": [
                    {
                        "action_ref": "opaque-turn",
                        "action_sha256": "d" * 64,
                        "can_interrupt": True,
                        "status": "dispatched",
                    }
                ],
                "actions": [],
            }
        }

    def answer(self, body, *, pre_admission):
        pre_admission()
        self.harness.native_actions.append(("answer", body))
        if self.harness.native_failure is not None:
            raise self.harness.native_failure
        return {"status": "sent", "synthetic": True}

    def interrupt(self, body, *, pre_admission):
        pre_admission()
        self.harness.native_actions.append(("interrupt", body))
        if self.harness.native_failure is not None:
            raise self.harness.native_failure
        return {"status": "sent", "synthetic": True}


class ProjectModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="project-model-")
        self.root = Path(self.tmp.name)
        self.intake = ProjectIntakeService(self.root, authenticate=authenticate)
        self.model = ProjectModelService(self.intake, provider_factory=self.factory)
        self.io, self.factories = 0, 0
        self.output, self.failure, self.release = (
            "Possible directions; source basis Unknown.",
            None,
            None,
        )
        self.key = "one"
        self.native_actions, self.status_reads = [], 0
        self.native_failure, self.native_status_failure = None, None
        self.provider_roots = []
        self.project_counter = 0

    def tearDown(self):
        if self.release is not None:
            self.release.set()
        self.model.close()
        self.intake.close()
        self.tmp.cleanup()

    def factory(self, *, context, admit, output_root):
        self.assertFalse(self.intake.db.in_transaction)
        self.assertTrue(context["deny_only"])
        self.assertTrue(context["trusted_stage_unit"])
        self.assertTrue(output_root.is_relative_to(self.root))
        self.provider_roots.append(output_root)
        self.factories += 1
        return FakeProvider(self, context, admit, self.output)

    def project(self, *, confirmed=True, calls=2, seconds=60):
        self.project_counter += 1
        receipt = self.intake.create(
            "alice-token",
            {
                "key": "new-" + str(self.project_counter),
                "topic": "Research sparse musical timing representations",
            },
        )
        ref = receipt["project_ref"]
        view = self.intake.read("alice-token", ref)
        body = {
            "key": "resources",
            **{k: view[k] for k in ("revision", "input_version", "brief_sha256")},
            "resource_envelope": "Synthetic engineering case; no research tools.",
            "budgets": dict(
                model_calls=calls,
                seconds=seconds,
                search_calls=0,
                source_reads=0,
                rounds=0,
            ),
            "consent": dict(
                external_search=False, public_source_read=False, browser_fallback=False
            ),
            "user_input": "I confirm this test resource request.",
            "confirmed": True,
        }
        if confirmed:
            body.update(
                key="confirm",
                choices=[
                    dict(
                        field="geography",
                        status="not-applicable",
                        value=None,
                        reason="Method study has no geographic boundary.",
                        user_input="No geographic scope.",
                    )
                ],
                formal_target=30,
                priority_reading_target=20,
            )
            self.intake.submit("alice-token", ref, body)
        else:
            self.intake.configure("alice-token", ref, body)
        return ref

    def register(self, ref, operation="suggest-topic", **change):
        binding = self.intake.brief_binding(ref)
        permit = dict(
            kind="ProjectModelOperationPermit",
            schema_version="1.0.0",
            permission_id="test-only-explicit-grant",
            principal="alice",
            project_id=binding["project_id"],
            input_version=binding["input_version"],
            brief_sha256=binding["brief_sha256"],
            budget_sha256=budget_digest(binding),
            operation=operation,
            model="synthetic-content-model",
            max_calls=2,
            max_seconds=60,
            expires_at=datetime.fromtimestamp(
                time.time() + 600, timezone.utc
            ).isoformat(),
            allow_model_calls=True,
            execution_scope="project-content-planning-only",
            external_search=False,
            frozen_subjects=False,
        )
        permit.update(change)
        path = self.root / (
            "permit-" + str(len(list(self.root.glob("permit-*")))) + ".json"
        )
        raw = canonical(permit) + b"\n"
        path.write_bytes(raw)
        return self.model.register(
            ref, operation=operation, permit_path=path, permit_sha256=sha(raw)
        ), path

    def body(self, ref, offer, key=None):
        view = self.intake.read("alice-token", ref)
        return {
            "key": key or self.key,
            **{k: view[k] for k in ("revision", "input_version", "brief_sha256")},
            "offer_ref": offer["offer_ref"],
            "offer_sha256": offer["offer_sha256"],
            "confirmed": True,
        }

    def finish(self, ref):
        stop = time.monotonic() + 3
        while time.monotonic() < stop:
            jobs = self.model.history("alice-token", ref)["actions"]
            if jobs and jobs[-1]["status"] in {
                "content-review-pending",
                "plan-validated-not-executed",
                "validation-failed",
                "failed-or-unknown",
                "execution-unknown",
            }:
                return jobs[-1]
            time.sleep(0.005)
        self.fail("synthetic worker did not settle within bounded wait")

    def http_request(self, host, token, path, body=None):
        headers = {"Authorization": "Bearer " + token}
        if body is not None:
            headers.update(
                {"Content-Type": "application/json", "Origin": host.expected_origin}
            )
        client = http.client.HTTPConnection("127.0.0.1", host.server_port, timeout=5)
        try:
            client.request(
                "GET" if body is None else "POST",
                path,
                body=None if body is None else json.dumps(body).encode("utf8"),
                headers=headers,
            )
            response = client.getresponse()
            raw = response.read(1048577)
            self.assertLessEqual(len(raw), 1048576)
            return response.status, json.loads(raw)
        finally:
            client.close()

    def actual_ui_reconcile(self, record, rows):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required for the actual UI reconciliation function")
        script = (
            Path(__file__).parents[1] / "cli/research_workspace_native/web/projects.js"
        ).read_text(encoding="utf8")
        actual = script[
            script.index("function reconcile(rowsToCheck)") : script.index(
                "async function history(",
                script.index("function reconcile(rowsToCheck)"),
            )
        ]
        checked = subprocess.run(
            [
                node,
                "-e",
                'const fs=require("node:fs");'
                'const input=JSON.parse(fs.readFileSync(0,"utf8"));'
                "let pending=input.pending;"
                "function forget(key){pending=pending.filter(row=>row.key!==key);}"
                + actual
                + "reconcile(input.rows);process.stdout.write(JSON.stringify(pending));",
            ],
            input=json.dumps({"pending": [record], "rows": rows}),
            text=True,
            encoding="utf8",
            capture_output=True,
            timeout=5,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        return json.loads(checked.stdout)

    def actual_ui_native_reconcile(self, record, rows):
        node = shutil.which("node")
        if node is None:
            self.skipTest(
                "Node is required for the actual native reconciliation helper"
            )
        script = (
            Path(__file__).parents[1] / "cli/research_workspace_native/web/projects.js"
        ).read_text(encoding="utf8")
        actual = script[
            script.index("function nativeObservationMatches(") : script.index(
                "async function native(",
                script.index("function nativeObservationMatches("),
            )
        ]
        checked = subprocess.run(
            [
                node,
                "-e",
                'const fs=require("node:fs");const input=JSON.parse(fs.readFileSync(0,"utf8"));let nativePending=input.pending;const nativeStorage="test";const sessionStorage={setItem(){}};'
                + actual
                + "reconcileNative(input.rows);process.stdout.write(JSON.stringify(nativePending));",
            ],
            input=json.dumps({"pending": [record], "rows": rows}),
            text=True,
            encoding="utf8",
            capture_output=True,
            timeout=5,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        return json.loads(checked.stdout)

    def actual_ui_native_digest(self, operation, body):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required for the actual native hash helper")
        script = (
            Path(__file__).parents[1] / "cli/research_workspace_native/web/projects.js"
        ).read_text(encoding="utf8")
        actual = script[
            script.index("function canonical(") : script.index(
                "function availableStage2("
            )
        ]
        checked = subprocess.run(
            [
                node,
                "-e",
                'const crypto=require("node:crypto").webcrypto;const fs=require("node:fs");const input=JSON.parse(fs.readFileSync(0,"utf8"));'
                + actual
                + "nativeRequestHash(input.operation,input.body).then(value=>process.stdout.write(value));",
            ],
            input=json.dumps({"operation": operation, "body": body}),
            text=True,
            encoding="utf8",
            capture_output=True,
            timeout=5,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        return checked.stdout

    def active_native(self):
        ref = self.project()
        offer, _ = self.register(ref)
        self.release = threading.Event()
        self.model.execute("alice-token", ref, self.body(ref, offer))
        stop = time.monotonic() + 2
        while self.io == 0 and time.monotonic() < stop:
            time.sleep(0.005)
        self.assertEqual(self.io, 1)
        return ref, {
            "key": "answer",
            "revision": 3,
            "index_sha256": "a" * 64,
            "input_version": "b" * 64,
            "request_ref": "opaque-question",
            "request_sha256": "c" * 64,
            "result": {"answers": {"scope": {"answers": ["Retain original topic"]}}},
        }

    def test_draft_topic_prose_preserves_brief_and_durable_intent_then_history_only(
        self,
    ):
        ref = self.project(confirmed=False)
        before = self.intake.brief_binding(ref)
        offer, _ = self.register(ref)
        body = self.body(ref, offer)
        receipt = self.model.execute("alice-token", ref, body)
        job = self.finish(ref)
        self.assertEqual(job["status"], "content-review-pending")
        self.assertEqual(job["kind"], "model-operation")
        self.assertEqual(job["project_ref"], ref)
        self.assertEqual(job["request_sha256"], receipt["request_sha256"])
        self.assertEqual(job["output_preview"], self.output)
        after = self.intake.brief_binding(ref)
        self.assertEqual(before["brief_sha256"], after["brief_sha256"])
        self.assertEqual(after["brief"]["suggestions"], [])
        self.assertFalse(
            self.intake.read("alice-token", ref)["intake_report"][
                "necessary_clarification_complete"
            ]
        )
        for _ in range(3):
            observed = self.model.read("alice-token", ref)
            self.assertEqual(observed["brief_sha256"], after["brief_sha256"])
            self.assertEqual(observed["input_version"], after["input_version"])
            self.model.offers("alice-token", ref)
            self.model.history("alice-token", ref)
        replay = self.model.execute("alice-token", ref, {**body, "revision": 999})
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["job"]["status"], "content-review-pending")
        self.assertEqual(replay["job"]["request_sha256"], receipt["request_sha256"])
        self.assertEqual((self.factories, self.io), (1, 1))
        with self.assertRaises(SessionApiError):
            self.model.execute("alice-token", ref, {**body, "confirmed": False})

    def test_real_confirmed_compiler_saves_unexecuted_plan_and_invalid_output_is_retained(
        self,
    ):
        ref = self.project()
        authored = proposal()
        authored["topic"] = self.intake.brief_binding(ref)["brief"][
            "original_description"
        ]
        request = dict(
            proposal=authored,
            query_bindings=[
                dict(
                    family_id=f"family-{i}",
                    need_ids=["main"],
                    purpose="study-evidence",
                    scope_filters={},
                )
                for i in range(1, 5)
            ],
        )
        self.output = canonical(request).decode()
        offer, _ = self.register(ref, "plan-search")
        self.model.execute("alice-token", ref, self.body(ref, offer))
        job = self.finish(ref)
        self.assertEqual(job["status"], "plan-validated-not-executed")
        binding = self.intake.binding(ref)
        self.assertTrue(
            validate_bound_plan(binding["plan_root"], binding["brief_path"])["valid"]
        )
        self.assertEqual(
            self.intake.read("alice-token", ref)["stage1_status"], "not-started"
        )
        self.key, self.output = "two", "{not valid JSON; keep this failed proposal}"
        self.model.execute("alice-token", ref, self.body(ref, offer))
        invalid = self.finish(ref)
        self.assertEqual(invalid["status"], "validation-failed")
        self.assertEqual(invalid["output_preview"], self.output)
        raw = (
            self.model._runtime_folder(
                "alice", ref, self.model._job("alice", ref, self.key)
            )
            / "output.txt"
        ).read_bytes()
        self.assertEqual(sha(raw), invalid["raw_output"]["sha256"])
        self.assertEqual(self.model.read("alice-token", ref)["calls_reserved"], 2)

    def test_unconnected_reads_zero_budget_expiry_and_forged_fields_are_zero_io(self):
        ref = self.project()
        offer, path = self.register(ref)
        body = self.body(ref, offer)
        self.model.factory = None
        self.assertFalse(self.model.read("alice-token", ref)["connected"])
        self.assertFalse(
            self.model.offers("alice-token", ref)["offers"][0]["available"]
        )
        with self.assertRaises(SessionApiError):
            self.model.execute("alice-token", ref, body)
        self.model.factory = self.factory
        for change in (
            {"rpc": "turn/start"},
            {"permit_path": str(path)},
            {"model": "caller-chosen"},
            {"confirmed": False},
            {"revision": body["revision"] - 1},
            {"offer_ref": []},
        ):
            with self.subTest(change=change), self.assertRaises(SessionApiError):
                self.model.execute("alice-token", ref, {**body, **change})
        with self.assertRaises(SessionApiError):
            self.model.read("bob-token", ref)
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(SessionApiError):
            self.model.execute("alice-token", ref, body)
        with self.assertRaises(SessionApiError):
            self.register(ref, expires_at="2020-01-01T00:00:00Z")
        zero = self.project(confirmed=False, calls=0, seconds=0)
        with self.assertRaises(SessionApiError):
            self.register(zero)
        self.assertEqual((self.factories, self.io), (0, 0))
        self.assertEqual(self.model.read("alice-token", ref)["calls_reserved"], 0)

    def test_same_key_different_offer_refused_and_new_permit_does_not_reset_budget(
        self,
    ):
        ref = self.project(calls=1)
        offer, _ = self.register(ref, max_calls=1)
        body = self.body(ref, offer)
        self.model.execute("alice-token", ref, body)
        self.finish(ref)
        replacement, _ = self.register(
            ref, max_calls=1, permission_id="different-permit-same-budget"
        )
        with self.assertRaises(SessionApiError):
            self.model.execute("alice-token", ref, self.body(ref, replacement))
        with self.assertRaises(SessionApiError):
            self.model.execute(
                "alice-token", ref, self.body(ref, replacement, "new-key")
            )
        self.assertEqual((self.factories, self.io), (1, 1))
        self.assertEqual(self.model.read("alice-token", ref)["calls_reserved"], 1)

    def test_true_sqlite_reopen_marks_queued_unknown_and_same_key_never_dispatches(
        self,
    ):
        ref = self.project()
        offer, path = self.register(ref)
        body = self.body(ref, offer)
        with patch(
            "research_workspace_native.project_model.threading.Thread"
        ) as thread:
            thread.return_value.is_alive.return_value = False
            self.model.execute("alice-token", ref, body)
            thread.return_value.start.assert_called_once()
        self.assertEqual(
            self.model.history("alice-token", ref)["actions"][0]["status"], "queued"
        )
        self.model.close()
        self.intake.close()
        self.intake = ProjectIntakeService(self.root, authenticate=authenticate)
        self.model = ProjectModelService(self.intake, provider_factory=self.factory)
        self.model.register(
            ref,
            operation="suggest-topic",
            permit_path=path,
            permit_sha256=sha(path.read_bytes()),
        )
        unknown = self.model.history("alice-token", ref)["actions"][0]
        self.assertEqual(unknown["status"], "execution-unknown")
        self.assertEqual(unknown["calls_reserved"], 1)
        replay = self.model.execute("alice-token", ref, {**body, "revision": 999})
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["job"]["status"], "execution-unknown")
        with self.assertRaises(SessionApiError):
            self.model.execute("alice-token", ref, self.body(ref, offer, "new-key"))
        self.assertEqual((self.factories, self.io), (0, 0))

    def test_after_provider_failure_unknown_is_retained_and_second_owner_cannot_attach(
        self,
    ):
        ref = self.project()
        offer, path = self.register(ref)
        other = ProjectModelService(self.intake, provider_factory=self.factory)
        with self.assertRaises(sqlite3.OperationalError):
            other.register(
                ref,
                operation="suggest-topic",
                permit_path=path,
                permit_sha256=sha(path.read_bytes()),
            )
        other.close()
        self.failure = RuntimeError("synthetic response lost after dispatch")
        body = self.body(ref, offer)
        self.model.execute("alice-token", ref, body)
        job = self.finish(ref)
        self.assertEqual(job["status"], "failed-or-unknown")
        self.assertIn("response lost", job["failure"])
        self.assertTrue(
            self.model.execute("alice-token", ref, {**body, "revision": 999})[
                "replayed"
            ]
        )
        self.assertEqual((self.factories, self.io), (1, 1))

    def test_locked_pre_admission_timeout_and_changed_brief_preserve_zero_io(self):
        ref = self.project()
        offer, _ = self.register(ref)
        body = self.body(ref, offer)

        def expired():
            raise TimeoutError("synthetic HTTP lock deadline expired")

        with self.assertRaises(TimeoutError):
            self.model.execute("alice-token", ref, body, check_deadline=expired)
        view = self.intake.read("alice-token", ref)
        self.intake.revise(
            "alice-token",
            ref,
            {
                "key": "new-version",
                "topic": "A different researcher topic",
                **{k: view[k] for k in ("revision", "input_version", "brief_sha256")},
            },
        )
        with self.assertRaises(SessionApiError):
            self.model.execute(
                "alice-token",
                ref,
                {**body, "revision": self.intake.read("alice-token", ref)["revision"]},
            )
        self.assertEqual((self.factories, self.io), (0, 0))

    def test_active_native_view_answer_decline_cancel_and_interrupt_stay_server_bound(
        self,
    ):
        ref = self.project()
        offer, _ = self.register(ref)
        self.release = threading.Event()
        self.model.execute("alice-token", ref, self.body(ref, offer))
        stop = time.monotonic() + 2
        while self.io == 0 and time.monotonic() < stop:
            time.sleep(0.005)
        self.assertEqual(self.io, 1)
        view = self.model.native_view("alice-token", ref)
        self.assertTrue(view["connected"])
        self.assertEqual(
            view["native_view"]["requests"][0]["request_ref"], "opaque-question"
        )
        answer = {
            "key": "answer",
            "revision": 3,
            "index_sha256": "a" * 64,
            "input_version": "b" * 64,
            "request_ref": "opaque-question",
            "request_sha256": "c" * 64,
            "result": {
                "answers": {"scope": {"answers": ["Retain the original topic"]}}
            },
        }
        self.model.answer("alice-token", ref, answer)
        for decision in ("decline", "cancel"):
            self.model.answer(
                "alice-token",
                ref,
                {
                    **answer,
                    "key": decision,
                    "request_ref": "opaque-" + decision,
                    "result": {"decision": decision},
                },
            )
        interrupt = {
            "key": "interrupt",
            "revision": 3,
            "index_sha256": "a" * 64,
            "input_version": "b" * 64,
            "action_ref": "opaque-turn",
            "action_sha256": "d" * 64,
        }
        self.model.interrupt("alice-token", ref, interrupt)
        for invalid in (
            {**answer, "result": {"decision": "accept"}},
            {**answer, "rpc": "turn/start"},
        ):
            with self.assertRaises(SessionApiError):
                self.model.answer("alice-token", ref, invalid)

        def expired():
            raise TimeoutError("expired queued HTTP request")

        with self.assertRaises(TimeoutError):
            self.model.interrupt(
                "alice-token",
                ref,
                {**interrupt, "key": "expired"},
                check_deadline=expired,
            )
        # The same key above is history-only, including when a new deadline fails.
        self.assertEqual(
            self.model.interrupt("alice-token", ref, interrupt)["status"],
            "result-observed",
        )
        self.assertEqual(len(self.native_actions), 4)
        self.assertEqual((self.factories, self.io), (1, 1))
        self.release.set()
        self.finish(ref)

    def test_native_stale_invalid_schema_and_full_identity_reconcile_are_known_unsent(
        self,
    ):
        ref, answer = self.active_native()
        cases = [
            {**answer, "key": "stale", "revision": 2},
            {
                **answer,
                "key": "invalid",
                "result": {"answers": {"wrong": {"answers": ["x"]}}},
            },
            {**answer, "key": "bad-source", "index_sha256": "f" * 64},
            {
                **answer,
                "key": "accept",
                "request_ref": "opaque-decline",
                "result": {"decision": "accept"},
            },
            {
                "key": "bad-interrupt",
                "revision": 3,
                "index_sha256": "a" * 64,
                "input_version": "b" * 64,
                "action_ref": "opaque-turn",
                "action_sha256": "e" * 64,
            },
        ]
        for body in cases:
            operation = "interrupt" if "action_ref" in body else "answer"
            with self.assertRaises((SessionApiError, ValueError)):
                getattr(self.model, operation)("alice-token", ref, body)
            observation = next(
                row
                for row in self.model.native_view("alice-token", ref)["native_actions"]
                if row["key"] == body["key"]
            )
            self.assertEqual(observation["status"], "known-unsent")
            self.assertFalse(observation["provider_invoked"])
            digest = sha(canonical({"kind": operation, "body": body}))
            self.assertEqual(observation["request_sha256"], digest)
            record = {
                "key": body["key"],
                "project_ref": ref,
                "target": body.get("request_ref", body.get("action_ref")),
                "operation": operation,
                "request_sha256": digest,
            }
            self.assertEqual(self.actual_ui_native_reconcile(record, [observation]), [])
            for name, replacement in (
                ("kind", "other"),
                ("key", "wrong"),
                ("project_ref", "wrong"),
                ("target_ref", "wrong"),
                ("operation", "wrong"),
                ("request_sha256", "0" * 64),
                ("status", "execution-unknown"),
            ):
                self.assertEqual(
                    self.actual_ui_native_reconcile(
                        record, [{**observation, name: replacement}]
                    ),
                    [record],
                )
            before = (self.status_reads, len(self.native_actions))
            replay = getattr(self.model, operation)("alice-token", ref, body)
            self.assertEqual(replay, observation)
            self.assertEqual((self.status_reads, len(self.native_actions)), before)
            with self.assertRaises(SessionApiError):
                getattr(self.model, operation)(
                    "alice-token", ref, {**body, "revision": 999}
                )
        self.assertEqual(self.native_actions, [])
        self.release.set()
        self.finish(ref)

    def test_native_response_loss_replay_and_closed_session_get_preserve_observations(
        self,
    ):
        ref, body = self.active_native()
        result = self.model.answer("alice-token", ref, body)
        self.assertEqual(result["status"], "result-observed")
        self.assertTrue(result["provider_invoked"])
        before = (self.status_reads, len(self.native_actions))
        self.assertEqual(self.model.answer("alice-token", ref, body), result)
        self.assertEqual((self.status_reads, len(self.native_actions)), before)
        with self.assertRaises(SessionApiError):
            self.model.answer(
                "alice-token",
                ref,
                {**body, "result": {"answers": {"scope": {"answers": ["changed"]}}}},
            )
        with self.assertRaises(SessionApiError):
            self.model.answer("alice-token", ref, {**body, "key": "other-tab"})
        self.assertEqual(len(self.native_actions), 1)
        self.release.set()
        self.finish(ref)
        self.model.close()
        self.intake.close()
        self.intake = ProjectIntakeService(self.root, authenticate=authenticate)
        self.model = ProjectModelService(self.intake, provider_factory=self.factory)
        before = (self.factories, self.io, self.status_reads, len(self.native_actions))
        view = self.model.native_view("alice-token", ref)
        self.assertIsNone(view["native_view"])
        self.assertFalse(view["connected"])
        self.assertEqual(view["native_actions"][0], result)
        self.assertEqual(self.model.answer("alice-token", ref, body), result)
        self.assertEqual(
            (self.factories, self.io, self.status_reads, len(self.native_actions)),
            before,
        )
        with self.assertRaises(SessionApiError):
            self.model.native_view("bob-token", ref)

    def test_native_after_provider_failure_is_unknown_not_resend_or_ui_unlock(self):
        ref, body = self.active_native()
        self.native_failure = ConnectionError("synthetic response lost after mutation")
        with self.assertRaises(ConnectionError):
            self.model.answer("alice-token", ref, body)
        view = self.model.native_view("alice-token", ref)
        observation = view["native_actions"][0]
        self.assertEqual(observation["status"], "execution-unknown")
        self.assertTrue(observation["provider_invoked"])
        record = {
            "key": body["key"],
            "project_ref": ref,
            "target": body["request_ref"],
            "operation": "answer",
            "request_sha256": sha(canonical({"kind": "answer", "body": body})),
        }
        self.assertEqual(
            self.actual_ui_native_reconcile(record, [observation]), [record]
        )
        before = (self.status_reads, len(self.native_actions))
        self.assertEqual(self.model.answer("alice-token", ref, body), observation)
        self.assertEqual((self.status_reads, len(self.native_actions)), before)
        self.native_status_failure = ValueError("synthetic source drift")
        drift = self.model.native_view("alice-token", ref)
        self.assertIsNone(drift["native_view"])
        self.assertEqual(drift["native_actions"][0], observation)
        self.assertEqual(len(self.native_actions), 1)
        self.release.set()
        self.finish(ref)

    def test_native_intent_persistence_failure_reopens_unknown_and_full_ui_hash_is_exact(
        self,
    ):
        ref, body = self.active_native()
        body["result"]["answers"]["scope"]["answers"] = ['保留原文\n"引号"与\\路径']
        digest = sha(canonical({"kind": "answer", "body": body}))
        self.assertEqual(self.actual_ui_native_digest("answer", body), digest)
        unicode_body = deepcopy(body)
        unicode_body["result"]["answers"] = {
            "\ue000": {"answers": ['私用区\n"原文"']},
            "\U0001f600": {"answers": ["emoji 问题 ID"]},
            "id": {"answers": ["前缀"]},
            "id\U0001f600": {"answers": ["带补充平面后缀"]},
            "idA": {"answers": ["ASCII 后缀"]},
            "中文": {"answers": ['quoted "内容"\n下一行\\保留']},
        }
        self.assertEqual(
            self.actual_ui_native_digest("answer", unicode_body),
            sha(canonical({"kind": "answer", "body": unicode_body})),
        )
        self.assertNotEqual(
            self.actual_ui_native_digest("answer", {**body, "revision": 4}), digest
        )
        transaction = self.model._transaction

        def failure(principal, project_ref, kind, change):
            if kind == "model-native-observation":
                raise OSError("synthetic observation-write failure")
            return transaction(principal, project_ref, kind, change)

        with patch.object(self.model, "_transaction", failure):
            with self.assertRaises(OSError):
                self.model.answer("alice-token", ref, body)
        observation = self.model.native_view("alice-token", ref)["native_actions"][0]
        self.assertEqual(observation["status"], "intent-recorded")
        self.assertFalse(observation["provider_invoked"])
        self.assertEqual(self.native_actions, [])
        self.release.set()
        self.finish(ref)
        self.model.close()
        self.intake.close()
        self.intake = ProjectIntakeService(self.root, authenticate=authenticate)
        self.model = ProjectModelService(self.intake, provider_factory=self.factory)
        self.register(ref)
        observed = self.model.native_view("alice-token", ref)["native_actions"][0]
        self.assertEqual(observed["status"], "execution-unknown")
        self.assertEqual(observed["failure"], "owner-recovery-no-resend")
        before = (self.factories, self.io, self.status_reads, len(self.native_actions))
        self.assertEqual(self.model.answer("alice-token", ref, body), observed)
        self.assertEqual(
            (self.factories, self.io, self.status_reads, len(self.native_actions)),
            before,
        )

    def test_real_http_native_refusal_then_get_recovers_without_provider_mutation(self):
        token = "project-content-http-test-credential-at-least-32"
        self.intake.authenticate = lambda credential: (
            "local-viewer" if credential in {token, "alice-token"} else None
        )
        ref = self.project()
        offer, _ = self.register(ref, principal="local-viewer")
        self.release = threading.Event()
        self.model.execute("alice-token", ref, self.body(ref, offer))
        stop = time.monotonic() + 2
        while self.io == 0 and time.monotonic() < stop:
            time.sleep(0.005)
        self.assertEqual(self.io, 1)
        host = ProjectHost(
            projects=self.intake,
            models=self.model,
            credential=token,
            files={},
            views=[],
            port=0,
        )
        server = threading.Thread(target=host.serve_forever, daemon=True)
        server.start()
        route = "/api/projects/" + ref + "/models/native"
        body = {
            "key": "stale-http",
            "revision": 2,
            "index_sha256": "a" * 64,
            "input_version": "b" * 64,
            "request_ref": "opaque-question",
            "request_sha256": "c" * 64,
            "result": {"answers": {"scope": {"answers": ["retain"]}}},
        }
        try:
            code, rejected = self.http_request(host, token, route + "/answer", body)
            self.assertEqual(code, 409, rejected)
            code, view = self.http_request(host, token, route)
            self.assertEqual(code, 200, view)
            action = view["native_actions"][0]
            record = {
                "key": body["key"],
                "project_ref": ref,
                "target": body["request_ref"],
                "operation": "answer",
                "request_sha256": self.actual_ui_native_digest("answer", body),
            }
            self.assertEqual(action["status"], "known-unsent")
            self.assertEqual(self.actual_ui_native_reconcile(record, [action]), [])
            before = (
                self.factories,
                self.io,
                self.status_reads,
                len(self.native_actions),
            )
            code, replay = self.http_request(host, token, route + "/answer", body)
            self.assertEqual(code, 200, replay)
            self.assertEqual(replay, action)
            self.assertEqual(
                (self.factories, self.io, self.status_reads, len(self.native_actions)),
                before,
            )
            self.assertEqual(self.native_actions, [])
            self.release.set()
            self.finish(ref)
            before = (
                self.factories,
                self.io,
                self.status_reads,
                len(self.native_actions),
            )
            code, closed = self.http_request(host, token, route)
            self.assertEqual(code, 200, closed)
            self.assertIsNone(closed["native_view"])
            self.assertEqual(closed["native_actions"][0], action)
            self.assertEqual(
                (self.factories, self.io, self.status_reads, len(self.native_actions)),
                before,
            )
        finally:
            self.release.set()
            host.shutdown()
            host.server_close()
            server.join(3)
            self.assertFalse(server.is_alive())

    def authorization(self, ref, operation="suggest-topic", key="authorize"):
        view = self.intake.read("alice-token", ref)
        return {
            "key": key,
            **{k: view[k] for k in ("revision", "input_version", "brief_sha256")},
            "operation": operation,
            "confirmed": True,
            "user_input": "I allow exactly this one content-planning call, not search or research.",
        }

    def test_authorization_mints_one_immutable_offer_without_provider_then_lost_response_replays(
        self,
    ):
        ref = self.project(confirmed=False)
        self.model.model = "trusted-server-model"
        body = self.authorization(ref)
        self.assertTrue(self.model.read("alice-token", ref)["authorization_available"])
        self.assertEqual(list((self.root / ref).glob("content-permit-*.json")), [])
        result = self.model.authorize("alice-token", ref, body)
        self.assertTrue(result["connected"])
        self.assertEqual(result["max_calls"], 1)
        self.assertEqual(result["max_seconds"], 60)
        paths = list((self.root / ref).glob("content-permit-*.json"))
        self.assertEqual(len(paths), 1)
        raw = paths[0].read_bytes()
        self.assertEqual(sha(raw), result["permit_sha256"])
        permit = json.loads(raw)
        self.assertEqual(permit["model"], "trusted-server-model")
        self.assertFalse(permit["external_search"])
        replay = self.model.authorize("alice-token", ref, {**body, "revision": 999})
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["permit_sha256"], result["permit_sha256"])
        self.assertEqual(replay["offer"], result["offer"])
        self.assertEqual(
            self.model.history("alice-token", ref)["authorizations"]["authorize"][
                "user_input_preview"
            ],
            body["user_input"],
        )
        with self.assertRaises(SessionApiError):
            self.model.authorize(
                "alice-token", ref, {**body, "user_input": "A changed grant."}
            )
        self.assertEqual(paths[0].read_bytes(), raw)
        self.assertEqual((self.factories, self.io), (0, 0))

    def test_authorization_expiry_and_server_cap_are_checked_before_dispatch(self):
        ref = self.project(confirmed=False)
        epoch = time.time()
        self.model.clock = lambda: epoch
        self.model.model, self.model.local_cap_seconds = "trusted-server-model", 10
        result = self.model.authorize("alice-token", ref, self.authorization(ref))
        self.assertEqual(result["max_seconds"], 10)
        body = self.body(ref, result["offer"])
        self.model.clock = lambda: epoch + 11
        with self.assertRaises(SessionApiError):
            self.model.execute("alice-token", ref, body)
        self.assertFalse(
            self.model.offers("alice-token", ref)["offers"][0]["available"]
        )
        self.assertEqual((self.factories, self.io), (0, 0))

    def test_post_permit_timeout_retains_unknown_and_same_key_does_not_remint(self):
        ref = self.project(confirmed=False)
        self.model.model = "trusted-server-model"
        body = self.authorization(ref)
        checks = 0

        def expires_after_write():
            nonlocal checks
            checks += 1
            if checks == 3:
                raise TimeoutError("synthetic deadline after immutable permit write")

        with self.assertRaises(SessionApiError) as raised:
            self.model.authorize(
                "alice-token", ref, body, check_deadline=expires_after_write
            )
        self.assertEqual(raised.exception.receipt["status"], "execution-unknown")
        self.assertEqual(
            raised.exception.receipt["failure_phase"], "post-work-before-commit"
        )
        paths = list((self.root / ref).glob("content-permit-*.json"))
        self.assertEqual(len(paths), 1)
        raw = paths[0].read_bytes()
        recovered = self.model.authorize("alice-token", ref, {**body, "revision": 999})
        self.assertTrue(recovered["replayed"])
        self.assertEqual(recovered["status"], "execution-unknown")
        self.assertEqual(paths[0].read_bytes(), raw)
        self.assertEqual(self.model.offers("alice-token", ref)["offers"], [])
        self.assertEqual((self.factories, self.io), (0, 0))

    def test_budget_declaration_unconnected_or_spoofed_authorization_never_grants(self):
        ref = self.project(confirmed=False)
        body = self.authorization(ref)
        self.model.read("alice-token", ref)
        self.model.offers("alice-token", ref)
        self.assertEqual(list((self.root / ref).glob("content-permit-*.json")), [])
        for change in (
            {"model": "caller-model"},
            {"permit": "caller"},
            {"confirmed": False},
        ):
            with self.assertRaises(SessionApiError):
                self.model.authorize("alice-token", ref, {**body, **change})
        with self.assertRaises(SessionApiError):
            self.model.authorize("alice-token", ref, body)
        self.assertEqual(list((self.root / ref).glob("content-permit-*.json")), [])
        self.assertEqual((self.factories, self.io), (0, 0))

    def test_output_chunks_are_bound_to_historical_bytes_without_provider_io(self):
        ref = self.project()
        self.output = "論文來源與方法。" * 4000
        offer, _ = self.register(ref)
        self.model.execute("alice-token", ref, self.body(ref, offer))
        job = self.finish(ref)
        self.assertTrue(job["output_truncated"])
        self.assertLessEqual(len(job["output_preview"].encode("utf8")), 512)
        observed = []
        offset = 0
        while True:
            page = self.model.outputs("alice-token", ref, job["output_ref"], offset)
            self.assertEqual(page["project_ref"], ref)
            self.assertLessEqual(len(page["text"].encode("utf8")), 16384)
            self.assertEqual(page["output_sha256"], sha(self.output.encode("utf8")))
            observed.append(page["text"])
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]
        self.assertEqual("".join(observed), self.output)
        self.assertTrue(page["chunk_is_partial"])
        with self.assertRaises(SessionApiError):
            self.model.outputs("alice-token", ref, job["output_ref"], 1)
        with self.assertRaises(SessionApiError):
            self.model.outputs("bob-token", ref, job["output_ref"])
        other = self.project(confirmed=False)
        with self.assertRaises(SessionApiError):
            self.model.outputs("alice-token", other, job["output_ref"])
        view = self.intake.read("alice-token", ref)
        self.intake.revise(
            "alice-token",
            ref,
            {
                "key": "revise",
                "topic": "A new topic",
                **{k: view[k] for k in ("revision", "input_version", "brief_sha256")},
            },
        )
        history = self.model.outputs("alice-token", ref, job["output_ref"])
        self.assertEqual(history["input_version"], 1)
        self.assertEqual(history["brief_sha256"], job["brief_sha256"])
        saved_job = self.model._job("alice", ref, self.key)
        path = self.model._runtime_folder("alice", ref, saved_job) / "output.txt"
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaises(SessionApiError):
            self.model.outputs("alice-token", ref, job["output_ref"])
        self.assertEqual((self.factories, self.io), (1, 1))

    def test_short_runtime_preserves_full_source_owner_and_rejects_marker_tamper(self):
        ref = self.project()
        offer, _ = self.register(ref)
        self.model.execute("alice-token", ref, self.body(ref, offer))
        public = self.finish(ref)
        job = self.model._job("alice", ref, self.key)
        self.assertRegex(job["runtime_dir"], r"^m/[0-9a-f]{24}$")
        folder = self.root / job["runtime_dir"]
        marker = folder / "binding.json"
        original = marker.read_bytes()
        binding = json.loads(original)
        self.assertEqual(binding, job["runtime_binding"])
        self.assertEqual(binding["principal"], "alice")
        self.assertEqual(binding["project_ref"], ref)
        self.assertEqual(binding["key"], self.key)
        self.assertEqual(binding["owner"], job["owner"])
        self.assertEqual(binding["unit_key"], "project-unit-" + sha(self.key.encode()))
        for name in ("source_sha256", "prompt_sha256", "request_sha256"):
            self.assertRegex(binding[name], r"^[0-9a-f]{64}$")
        self.assertEqual(self.provider_roots, [folder / "n"])
        longest = (
            PureWindowsPath("D:/rp/projects")
            / job["runtime_dir"]
            / "n"
            / ("0" * 64)
            / ("native.sqlite3.owner-" + "0" * 64 + ".sqlite3-journal")
        )
        self.assertLess(len(str(longest).encode("utf-16-le")) // 2, 240)
        with self.assertRaisesRegex(SessionApiError, "already-observed"):
            self.model._runtime_folder("alice", ref, job, create=True)
        marker.write_bytes(canonical({**binding, "principal": "bob"}) + b"\n")
        with self.assertRaisesRegex(SessionApiError, "binding-collision"):
            self.model.outputs("alice-token", ref, public["output_ref"])
        marker.write_bytes(original)
        self.assertEqual(
            self.model.outputs("alice-token", ref, public["output_ref"])["text"],
            self.output,
        )
        self.assertEqual((self.factories, self.io), (1, 1))

    def test_short_digest_collision_retains_failure_without_dispatch_or_adoption(self):
        ref = self.project()
        offer, _ = self.register(ref)
        with patch.object(
            self.model, "_runtime_relative", return_value="m/" + "a" * 24
        ):
            self.model.execute("alice-token", ref, self.body(ref, offer))
            self.finish(ref)
            marker = self.root / "m" / ("a" * 24) / "binding.json"
            original = marker.read_bytes()
            self.key = "two"
            body = self.body(ref, offer)
            self.model.execute("alice-token", ref, body)
            failed = self.finish(ref)
            self.assertEqual(failed["status"], "failed-or-unknown")
            self.assertIn("model-runtime-binding-collision", failed["failure"])
            self.assertEqual(marker.read_bytes(), original)
            self.assertEqual(self.model.read("alice-token", ref)["calls_reserved"], 2)
            self.assertTrue(self.model.execute("alice-token", ref, body)["replayed"])
        self.assertEqual((self.factories, self.io), (1, 1))

    def test_saved_legacy_output_location_is_read_only_and_keeps_original_hash(self):
        ref = self.project()
        offer, _ = self.register(ref)
        self.model.execute("alice-token", ref, self.body(ref, offer))
        public = self.finish(ref)
        legacy = self.intake._path(
            ref, "model-" + sha(self.key.encode()) + "/output.txt"
        )
        legacy.parent.mkdir()
        legacy.write_bytes(self.output.encode("utf8"))
        with self.intake._lock:
            state = self.intake._load("alice", ref)
            job = state["model_operations"]["jobs"][self.key]
            job.pop("runtime_dir")
            job.pop("runtime_binding")
            self.intake.db.execute("BEGIN IMMEDIATE")
            self.intake._save(state, "synthetic-legacy-layout", {"synthetic": True})
            self.intake.db.commit()
        observed = self.model.outputs("alice-token", ref, public["output_ref"])
        self.assertEqual(observed["project_ref"], ref)
        self.assertEqual(observed["output_sha256"], public["output_sha256"])
        self.assertEqual(observed["text"], self.output)
        self.assertEqual((self.factories, self.io), (1, 1))

    def test_real_http_terminal_identity_and_full_output_get_never_redispatch(self):
        token = "project-content-http-test-credential-at-least-32"
        self.intake.authenticate = lambda credential: (
            "local-viewer" if credential in {token, "alice-token"} else None
        )
        ref = self.project()
        self.output = "保存內容來源與未知條件。" * 3000
        offer, _ = self.register(ref, principal="local-viewer")
        body = self.body(ref, offer)
        host = ProjectHost(
            projects=self.intake,
            models=self.model,
            credential=token,
            files={},
            views=[],
            port=0,
        )
        server = threading.Thread(target=host.serve_forever, daemon=True)
        server.start()
        route = "/api/projects/" + ref
        try:
            code, receipt = self.http_request(
                host, token, route + "/models/actions", body
            )
            self.assertEqual(code, 200, receipt)
            self.assertEqual(receipt["status"], "saved")
            self.assertEqual(receipt["model_status"], "queued")
            record = {
                "key": body["key"],
                "kind": "model-operation",
                "project_ref": ref,
                "request_sha256": receipt["request_sha256"],
            }
            self.assertEqual(self.actual_ui_reconcile(record, [receipt]), [record])
            self.finish(ref)
            code, shared = self.http_request(host, token, route + "/history")
            self.assertEqual(code, 200, shared)
            admission = next(
                row for row in shared["actions"] if row["key"] == body["key"]
            )
            self.assertEqual(admission["model_status"], "queued")
            self.assertEqual(self.actual_ui_reconcile(record, [admission]), [record])
            code, page = self.http_request(host, token, route + "/models/actions/0")
            self.assertEqual(code, 200, page)
            job = page["actions"][0]
            self.assertEqual(job["request_sha256"], receipt["request_sha256"])
            self.assertEqual(self.actual_ui_reconcile(record, [job]), [])
            for altered in (
                {**job, "project_ref": "other-project"},
                {**job, "request_sha256": "0" * 64},
                {**job, "status": "execution-unknown"},
                {**job, "status": "failed-or-unknown"},
            ):
                self.assertEqual(self.actual_ui_reconcile(record, [altered]), [record])
            wrong = {**body, "offer_sha256": "0" * 64}
            code, denied = self.http_request(
                host, token, route + "/models/actions", wrong
            )
            self.assertEqual(code, 409, denied)
            self.assertEqual(
                denied["receipt"]["request_sha256"], receipt["request_sha256"]
            )
            forged_record = {
                **record,
                "request_sha256": sha(
                    canonical(
                        {
                            "kind": "model-operation",
                            "body": {k: v for k, v in wrong.items() if k != "revision"},
                        }
                    )
                ),
            }
            self.assertEqual(
                self.actual_ui_reconcile(forged_record, [job]), [forged_record]
            )
            original = []
            offset = 0
            while True:
                code, output = self.http_request(
                    host,
                    token,
                    route + "/models/outputs/" + job["output_ref"] + "/" + str(offset),
                )
                self.assertEqual(code, 200, output)
                self.assertEqual(output["project_ref"], ref)
                self.assertEqual(output["output_sha256"], job["output_sha256"])
                self.assertLessEqual(len(output["text"].encode("utf8")), 16384)
                original.append(output["text"])
                if output["next_offset"] is None:
                    break
                offset = output["next_offset"]
            self.assertEqual("".join(original), self.output)
            code, _ = self.http_request(
                host,
                token,
                "/api/projects/other-project/models/outputs/"
                + job["output_ref"]
                + "/0",
            )
            self.assertEqual(code, 404)
            code, replay = self.http_request(
                host, token, route + "/models/actions", body
            )
            self.assertEqual(code, 200, replay)
            self.assertTrue(replay["replayed"])
            self.assertEqual((self.factories, self.io), (1, 1))
        finally:
            host.shutdown()
            host.server_close()
            server.join(3)
            self.assertFalse(server.is_alive())

    def test_real_http_history_page32_and_pre_admission_refusal_are_bound_and_zero_io(
        self,
    ):
        token = "project-content-http-test-credential-at-least-32"
        self.intake.authenticate = lambda credential: (
            "local-viewer" if credential in {token, "alice-token"} else None
        )
        ref = self.project()
        offer, _ = self.register(ref, principal="local-viewer")
        body = self.body(ref, offer)
        host = ProjectHost(
            projects=self.intake,
            models=self.model,
            credential=token,
            files={},
            views=[],
            port=0,
        )
        server = threading.Thread(target=host.serve_forever, daemon=True)
        server.start()
        route = "/api/projects/" + ref
        try:
            expired = {**body, "key": "rejected", "revision": body["revision"] + 500}
            code, rejected = self.http_request(
                host, token, route + "/models/actions", expired
            )
            self.assertEqual(code, 409, rejected)
            self.assertEqual(rejected["receipt"]["status"], "known-unsent")
            self.assertEqual(
                rejected["receipt"]["request_sha256"],
                sha(
                    canonical(
                        {
                            "kind": "model-operation",
                            "body": {
                                k: v for k, v in expired.items() if k != "revision"
                            },
                        }
                    )
                ),
            )
            self.assertEqual((self.factories, self.io), (0, 0))
            code, _ = self.http_request(host, token, route + "/models/actions", body)
            self.assertEqual(code, 200)
            self.finish(ref)
            with self.intake._lock:
                state = self.intake._load("local-viewer", ref)
                job = deepcopy(state["model_operations"]["jobs"][self.key])
                state["model_operations"]["jobs"] = {
                    "fixture-" + str(i): {**deepcopy(job), "key": "fixture-" + str(i)}
                    for i in range(40)
                }
                state["model_operations"]["jobs"]["fixture-0"]["status"] = (
                    "execution-unknown"
                )
                self.intake.db.execute("BEGIN IMMEDIATE")
                self.intake._save(
                    state, "synthetic-http-pagination-fixture", {"synthetic": True}
                )
                self.intake.db.commit()
            code, first = self.http_request(host, token, route + "/models/actions/0")
            self.assertEqual(code, 200, first)
            self.assertEqual(len(first["actions"]), 32)
            self.assertEqual(first["next_offset"], 32)
            code, second = self.http_request(host, token, route + "/models/actions/32")
            self.assertEqual(code, 200, second)
            self.assertEqual(len(second["actions"]), 8)
            self.assertIsNone(second["next_offset"])
            code, overview = self.http_request(host, token, route + "/overview")
            self.assertEqual(code, 200, overview)
            self.assertEqual(overview["models"]["unknown_count"], 1)
            self.assertEqual(
                overview["models"]["brief_sha256"], overview["project"]["brief_sha256"]
            )
            for path in (
                "/history/offers",
                "/contract/actions",
                "/models/native/answer",
            ):
                code, _ = self.http_request(host, token, route + path)
                self.assertIn(code, (400, 404))
            code, _ = self.http_request(
                host, "incorrect-credential", route + "/models/actions/32"
            )
            self.assertEqual(code, 401)
            self.assertEqual((self.factories, self.io), (1, 1))
        finally:
            host.shutdown()
            host.server_close()
            server.join(3)
            self.assertFalse(server.is_alive())

    def test_hundreds_of_chinese_history_records_remain_bounded_without_losing_raw(
        self,
    ):
        ref = self.project()
        self.output = "論文概要；不將設計檢查當作科學結論。" * 1000
        offer, _ = self.register(ref)
        self.model.execute("alice-token", ref, self.body(ref, offer))
        self.finish(ref)
        with self.intake._lock:
            state = self.intake._load("alice", ref)
            exemplar = deepcopy(state["model_operations"]["jobs"][self.key])
            state["model_operations"]["jobs"] = {
                "historical-" + str(i): dict(
                    deepcopy(exemplar), key="historical-" + str(i)
                )
                for i in range(256)
            }
            state["model_operations"]["authorizations"] = {
                "grant-" + str(i): dict(
                    artifact={"path": "permit.json", "sha256": "a" * 64, "bytes": 1000},
                    offer_ref=offer["offer_ref"],
                    user_input="只授權此內容任務" * 900,
                )
                for i in range(128)
            }
            state["model_operations"]["jobs"]["historical-0"]["status"] = (
                "execution-unknown"
            )
            state["model_operations"]["jobs"]["historical-1"]["status"] = "queued"
            self.intake.db.execute("BEGIN IMMEDIATE")
            self.intake._save(
                state, "synthetic-history-size-fixture", {"synthetic": True}
            )
            self.intake.db.commit()
        for value in (
            self.model.read("alice-token", ref),
            self.model.history("alice-token", ref),
        ):
            encoded = json.dumps(value, ensure_ascii=True).encode("utf8")
            self.assertLessEqual(len(encoded), 1048576)
            jobs = value.get("jobs", value.get("actions"))
            self.assertTrue(
                all(len(j["output_preview"].encode("utf8")) <= 512 for j in jobs)
            )
        view = self.model.read("alice-token", ref)
        self.assertEqual(view["job_count"], 256)
        self.assertTrue(view["history_has_more"])
        self.assertEqual(view["unknown_count"], 1)
        self.assertEqual(view["active_jobs"][0]["key"], "historical-1")
        recovered, grants, offset = [], {}, 0
        while True:
            page = self.model.history("alice-token", ref, offset)
            self.assertEqual(page["order"], "oldest-first")
            self.assertLessEqual(len(page["actions"]), 32)
            self.assertLessEqual(
                len(json.dumps(page, ensure_ascii=True).encode("utf8")), 1048576
            )
            recovered.extend(page["actions"])
            grants.update(page["authorizations"])
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]
        self.assertEqual(len(recovered), 256)
        self.assertEqual(len(grants), 128)
        self.assertEqual(recovered[0]["status"], "execution-unknown")
        with self.intake._lock:
            saved = self.intake._load("alice", ref)
        self.assertEqual(len(saved["model_operations"]["jobs"]), 256)
        self.assertEqual(len(saved["model_operations"]["authorizations"]), 128)
        self.assertEqual(
            saved["model_operations"]["jobs"]["historical-0"]["output"], self.output
        )
        self.assertEqual((self.factories, self.io), (1, 1))


if __name__ == "__main__":
    unittest.main()

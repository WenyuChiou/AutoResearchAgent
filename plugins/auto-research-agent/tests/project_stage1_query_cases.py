"""Real project/compiler/Core/query receipts; SDK probe/backend are mocked."""

from copy import deepcopy
import json
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

from planned_query_fixture import QueryCase, get_source_proof
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1 import ProjectStage1Service
from research_workspace_native.project_stage1_queries import ProjectStage1QueryService
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
from stage1_ledger.validation import validate_run
from stage1_retrieval.runtime_identity import verify_identity
from research_workspace_native.project_contract import project_view
from test_workspace_project_intake import (
    authenticate,
    bound_body,
    compile_body,
    submit_body,
)


class ProjectQueryCases(QueryCase):
    def setUp(self):
        super().setUp()
        self.intake = ProjectIntakeService(self.root / "p", authenticate=authenticate)
        self.addCleanup(self.intake.close)
        self.stage1 = ProjectStage1Service(self.intake, limit=3)
        self.queries = self.bridge()
        view = self.intake.create(
            "alice-token",
            dict(key="create", topic="RL traffic control with robust validation"),
        )
        self.ref = view["project_ref"]
        current = self.intake.read("alice-token", self.ref)
        body = submit_body(current)
        body["budgets"].update(seconds=100, search_calls=2, rounds=1)
        body["consent"]["external_search"] = True
        self.intake.submit("alice-token", self.ref, body)
        self.intake.compile(
            "alice-token",
            self.ref,
            compile_body(self.intake.read("alice-token", self.ref)),
        )

    def bridge(self, *, admit=lambda event: True):
        proof = get_source_proof()
        service = ProjectStage1QueryService(
            self.stage1,
            runtime_pin=self.pin,
            execution_source_root=proof["repo"],
            execution_source_sha256=sha(canonical(proof["files"])),
            verify_source=lambda _: get_source_proof(),
            admit=admit,
            caps=dict(
                max_attempts=2,
                max_reserved_seconds=100,
                max_results=3,
                validity_seconds=600,
            ),
            backends=["openalex"],
        )
        self.addCleanup(service.close)
        return service

    def body(self, field, key, *, authorize=False):
        offer = self.queries.read("alice-token", self.ref)[field]
        result = dict(
            bound_body(self.intake.read("alice-token", self.ref), key),
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            confirmed=True,
        )
        if authorize:
            result["user_input"] = (
                "Authorize two OpenAlex attempts, no source or model calls."
            )
        return result

    def authorize(self):
        body = self.body("authorization_offer", "authorization", authorize=True)
        receipt = self.queries.authorize("alice-token", self.ref, body)
        return body, receipt

    def bootstrap(self):
        body = self.body("bootstrap_offer", "bootstrap")
        with patch(
            "stage1_retrieval.runtime_identity.verify_identity",
            side_effect=lambda pin, **kw: verify_identity(pin),
        ) as probe:
            receipt = self.queries.bootstrap("alice-token", self.ref, body)
            self.queries.workers[self.ref].join(30)
            self.assertFalse(self.queries.workers[self.ref].is_alive())
        view = self.queries.read("alice-token", self.ref)
        self.assertEqual(view["jobs"][0]["status"], "completed", view)
        self.assertTrue(
            any(call.kwargs.get("probe") is True for call in probe.call_args_list)
        )
        return body, receipt, view

    def test_authorization_and_all_gets_never_probe_create_or_search(self):
        with (
            patch(
                "stage1_retrieval.runtime_identity.capture_identity",
                side_effect=AssertionError("probe"),
            ),
            patch.object(
                type(self.stage1),
                "initialize",
                side_effect=AssertionError("initialize"),
            ),
            patch(
                "stage1_retrieval.runner.execute", side_effect=AssertionError("execute")
            ),
        ):
            view = self.queries.read("alice-token", self.ref)
            self.assertEqual(view["status"], "permission-required")
            body, receipt = self.authorize()
            repeated = self.queries.authorize("alice-token", self.ref, body)
            self.assertEqual(repeated["permit_sha256"], receipt["permit_sha256"])
            self.assertTrue(repeated["replayed"])
            self.assertEqual(
                self.queries.read("alice-token", self.ref)["budget"],
                dict(attempts=0, probes=0, seconds=0),
            )
            self.assertFalse(view["source_acquisition"])
            self.assertFalse(view["model_execution"])

    def test_live_bootstrap_preserves_offline_and_uses_original_integer_brief(self):
        offer = self.stage1.read("alice-token", self.ref)["initialization_offer"]
        body = dict(
            bound_body(self.intake.read("alice-token", self.ref), "offline"),
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            confirmed=True,
        )
        old = self.stage1.initialize("alice-token", self.ref, body)
        self.authorize()
        bootstrap_body, _, view = self.bootstrap()
        state = self.intake._load("alice", self.ref)
        self.assertIn(old["run_ref"], state["stage1_runs"])
        self.assertNotIn("registration", view["jobs"][0])
        job = next(iter(state["stage1_query_jobs"].values()))
        self.assertEqual(
            job["registration"]["input_version"],
            self.intake.binding(self.ref)["brief_sha256"],
        )
        self.assertEqual(job["registration"]["project_input_version"], 1)
        run = state["stage1_runs"][state["stage1_active"]]
        self.assertTrue(validate_run(self.intake._path(self.ref, run["path"]))["valid"])
        self.assertEqual(
            self.stage1.read("alice-token", self.ref)["stage1_status"],
            "query-ledger-active",
        )
        with patch(
            "stage1_retrieval.runtime_identity.capture_identity",
            side_effect=AssertionError("reprobe"),
        ):
            replay = self.queries.bootstrap("alice-token", self.ref, bootstrap_body)
            self.assertTrue(replay["replayed"])
        self.assertEqual(view["budget"], dict(probes=1, attempts=0, seconds=30))

    def test_real_runner_capture_import_extract_then_owned_checkpoint_and_reopen(self):
        self.authorize()
        self.bootstrap()
        request = self.body("query_offer", "query")
        with self.fake_runner(), self.no_probe():
            queued = self.queries.execute("alice-token", self.ref, request)
            self.queries.services[self.ref]._workers[self.ref].join(30)
        service = self.queries.services[self.ref]
        action = service.get_action("alice-token", self.ref, queued["query_action_key"])
        self.assertEqual(action["status"], "completed", action)
        self.assertTrue(action["result"]["execution_ref"])
        self.assertEqual(len(self.children), 1)
        stage_view = self.stage1.read("alice-token", self.ref)
        self.assertGreater(stage_view["ledger"]["counts"]["works"], 0)
        checkpoint_body = dict(
            bound_body(self.intake.read("alice-token", self.ref), "checkpoint"),
            ledger_state_sha256=stage_view["ledger"]["state_sha256"],
            confirmed=True,
        )
        self.stage1.checkpoint("alice-token", self.ref, checkpoint_body)
        self.assertIsNotNone(self.queries.read("alice-token", self.ref)["query_offer"])
        self.queries.close()
        self.stage1.query_service = None
        self.intake.close()
        self.intake = ProjectIntakeService(self.root / "p", authenticate=authenticate)
        self.addCleanup(self.intake.close)
        self.stage1 = ProjectStage1Service(self.intake, limit=3)
        self.queries = self.bridge()
        with (
            patch(
                "stage1_retrieval.runtime_identity.capture_identity",
                side_effect=AssertionError("reprobe"),
            ),
            patch(
                "stage1_retrieval.runner.execute", side_effect=AssertionError("rerun")
            ),
        ):
            self.assertEqual(
                self.queries.read("alice-token", self.ref)["status"],
                "owner-reopen-required",
            )
            self.queries.restore_owner(
                "alice-token", self.ref, self.body("owner_offer", "restore")
            )
            replay = self.queries.execute("alice-token", self.ref, request)
            self.assertTrue(replay["replayed"])
            self.assertEqual(
                self.queries.read("alice-token", self.ref)["budget"],
                dict(probes=1, attempts=1, seconds=62),
            )
        self.assertEqual(len(self.children), 1)

    def test_fractional_runtime_timeout_keeps_exact_reservation_history(self):
        self.pin["timeout_seconds"] = 2.5
        self.queries.config["pin"]["timeout_seconds"] = 2.5
        self.authorize()
        self.bootstrap()
        state = self.intake._load("alice", self.ref)
        registration = next(iter(state["stage1_query_jobs"].values()))["registration"]
        derived = json.loads(Path(registration["permit_path"]).read_bytes())
        self.assertEqual(derived["timeout_seconds"], 3)
        self.assertEqual(self.queries.config["pin"]["timeout_seconds"], 2.5)
        request = self.body("query_offer", "fractional-timeout")
        with self.fake_runner(), self.no_probe():
            queued = self.queries.execute("alice-token", self.ref, request)
            self.queries.services[self.ref]._workers[self.ref].join(30)
        action = self.queries.services[self.ref].get_action(
            "alice-token", self.ref, queued["query_action_key"]
        )
        self.assertEqual(action["status"], "completed", action)
        self.assertEqual(
            self.queries.read("alice-token", self.ref)["budget"],
            dict(probes=1, attempts=1, seconds=62.5),
        )
        with self.no_probe():
            self.assertTrue(
                self.queries.execute("alice-token", self.ref, request)["replayed"]
            )
        self.assertEqual(len(self.children), 1)

    def test_unknown_bootstrap_retains_budget_and_same_key_no_second_probe(self):
        self.authorize()
        body = self.body("bootstrap_offer", "bootstrap")
        with patch(
            "stage1_retrieval.runtime_identity.verify_identity",
            side_effect=RuntimeError("probe result unobserved"),
        ) as probe:
            self.queries.bootstrap("alice-token", self.ref, body)
            self.queries.workers[self.ref].join(30)
        view = self.queries.read("alice-token", self.ref)
        self.assertEqual(view["jobs"][0]["status"], "execution-unknown", view)
        self.assertEqual(probe.call_count, 1)
        with patch(
            "stage1_retrieval.runtime_identity.verify_identity",
            side_effect=AssertionError("repeat"),
        ):
            self.assertTrue(
                self.queries.bootstrap("alice-token", self.ref, body)["replayed"]
            )
        self.assertEqual(view["budget"]["seconds"], 30)
        self.assertIsNone(view["bootstrap_offer"])

    def test_admission_settings_drift_prevents_probe_and_retains_reserved_attempt(self):
        self.authorize()
        body = self.body("bootstrap_offer", "bootstrap")

        def drift(event):
            with self.intake._lock:
                state = self.intake._load("alice", self.ref)
                state["settings"]["resource_envelope"] += " changed"
                self.intake._save(state, "test-settings-drift", event)
            return True

        self.queries.admit = drift
        with patch(
            "stage1_retrieval.runtime_identity.capture_identity",
            side_effect=AssertionError("probe"),
        ):
            self.queries.bootstrap("alice-token", self.ref, body)
            self.queries.workers[self.ref].join(30)
        view = self.queries.read("alice-token", self.ref)
        self.assertEqual(view["jobs"][0]["status"], "refused-known-unsent", view)
        self.assertEqual(view["budget"]["seconds"], 30)

    def test_caller_paths_changed_payload_and_other_project_are_rejected(self):
        body = self.body("authorization_offer", "authorization", authorize=True)
        with self.assertRaises(SessionApiError):
            self.queries.authorize(
                "alice-token", self.ref, dict(body, permit_path="C:/fake")
            )
        self.queries.authorize("alice-token", self.ref, body)
        changed = deepcopy(body)
        changed["user_input"] += " changed"
        with self.assertRaisesRegex(SessionApiError, "idempotency"):
            self.queries.authorize("alice-token", self.ref, changed)
        with self.assertRaises(SessionApiError):
            self.queries.read("bob-token", self.ref)

    def test_expired_seal_restores_history_owner_but_refuses_new_search(self):
        self.authorize()
        self.bootstrap()
        expires = self.intake._load("alice", self.ref)["stage1_query_authorization"][
            "permit"
        ]["expires_at_unix"]
        self.queries.close()
        self.stage1.query_service = None
        self.intake.close()
        self.intake = ProjectIntakeService(self.root / "p", authenticate=authenticate)
        self.addCleanup(self.intake.close)
        self.stage1 = ProjectStage1Service(self.intake, limit=3)
        self.queries = self.bridge()
        with (
            patch(
                "research_workspace_native.project_query_permit.time.time",
                return_value=expires + 1,
            ),
            self.no_probe(),
        ):
            view = self.queries.read("alice-token", self.ref)
            self.assertFalse(view["execution_authorized"])
            self.assertIsNotNone(view["owner_offer"])
            self.queries.restore_owner(
                "alice-token", self.ref, self.body("owner_offer", "restore-expired")
            )
            view = self.queries.read("alice-token", self.ref)
            self.assertIsNone(view["query_offer"])
            stage = self.stage1.read("alice-token", self.ref)
            self.stage1.checkpoint(
                "alice-token",
                self.ref,
                dict(
                    bound_body(
                        self.intake.read("alice-token", self.ref), "expired-checkpoint"
                    ),
                    ledger_state_sha256=stage["ledger"]["state_sha256"],
                    confirmed=True,
                ),
            )
        self.assertEqual(
            self.queries.read("alice-token", self.ref)["budget"]["attempts"], 0
        )

    def test_runtime_config_drift_in_admission_is_refused_before_probe(self):
        self.authorize()
        body = self.body("bootstrap_offer", "config-drift")

        def drift(event):
            config = Path(self.pin["config"]["path"])
            config.write_bytes(config.read_bytes() + b" ")
            return True

        self.queries.admit = drift
        with patch(
            "stage1_retrieval.runtime_identity.capture_identity",
            side_effect=AssertionError("probe"),
        ):
            self.queries.bootstrap("alice-token", self.ref, body)
            self.queries.workers[self.ref].join(30)
        self.assertEqual(
            self.queries.read("alice-token", self.ref)["jobs"][0]["status"],
            "refused-known-unsent",
        )

    def test_unobserved_bootstrap_after_true_store_reopen_remains_unknown(self):
        self.authorize()
        body = self.body("bootstrap_offer", "lost-dispatch")

        class DormantThread:
            def __init__(self, **kwargs):
                pass

            def start(self):
                pass

            def is_alive(self):
                return False

            def join(self, timeout):
                pass

        with patch(
            "research_workspace_native.project_stage1_queries.threading",
            SimpleNamespace(Thread=DormantThread),
        ):
            self.queries.bootstrap("alice-token", self.ref, body)
        self.queries.workers.clear()
        self.queries.close()
        self.stage1.query_service = None
        self.intake.close()
        self.intake = ProjectIntakeService(self.root / "p", authenticate=authenticate)
        self.addCleanup(self.intake.close)
        self.stage1 = ProjectStage1Service(self.intake, limit=3)
        self.queries = self.bridge()
        with self.no_probe():
            view = self.queries.read("alice-token", self.ref)
            self.assertEqual(view["jobs"][0]["saved_status"], "dispatch-unobserved")
            self.assertEqual(view["jobs"][0]["status"], "execution-unknown")
            self.assertIsNone(view["bootstrap_offer"])
            self.assertTrue(
                self.queries.bootstrap("alice-token", self.ref, body)["replayed"]
            )
            projection = project_view(
                self.intake, "alice-token", self.ref, stage1=self.stage1
            )
            self.assertFalse(projection["stages"]["1"]["accepted"])
            self.assertIsNone(
                projection["stages"]["1"]["metrics"]["actual_search_calls"]["value"]
            )
            self.assertEqual(
                projection["stages"]["1"]["metrics"]["search_seconds_reserved"][
                    "value"
                ],
                30,
            )

    def test_last_source_callback_cannot_widen_caps_before_probe(self):
        self.authorize()
        body = self.body("bootstrap_offer", "source-caps-drift")
        calls = []

        def drift(event):
            calls.append(event)
            if len(calls) == 2:
                self.queries.config["caps"]["max_attempts"] += 1
            return get_source_proof()

        self.queries.verify_source = drift
        with patch(
            "stage1_retrieval.runtime_identity.capture_identity",
            side_effect=AssertionError("probe"),
        ):
            self.queries.bootstrap("alice-token", self.ref, body)
            self.queries.workers[self.ref].join(30)
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            self.queries.read("alice-token", self.ref)["jobs"][0]["status"],
            "refused-known-unsent",
        )

    def test_saved_package_production_keeps_ledger_frontier_without_inner_mutation(
        self,
    ):
        self.authorize()
        self.bootstrap()
        state = self.intake._load("alice", self.ref)
        run, ledger, _ = self.stage1._ledger(state, self.intake.binding(self.ref))
        before = self.queries.saved_frontier(self.ref)
        output = self.root / "saved-only-package-marker.txt"
        with self.no_probe():
            result = self.queries.produce_saved(
                self.ref,
                state,
                run,
                ledger,
                lambda owned: (
                    output.write_text(owned.root.as_posix(), encoding="utf8"),
                    {"saved": True},
                )[1],
            )
        self.assertEqual(result, {"saved": True})
        self.assertEqual(self.queries.saved_frontier(self.ref), before)
        self.assertEqual(
            self.queries.services[self.ref].view("alice-token", self.ref)["history"], []
        )

    def test_bootstrap_last_callback_deadline_is_unknown_and_does_not_activate(self):
        self._late_bootstrap("callback")

    def test_bootstrap_late_sqlite_write_rolls_back_activation(self):
        self._late_bootstrap("sqlite")

    def _late_bootstrap(self, phase):
        from time import time as wall_time

        self.authorize()
        body = self.body("bootstrap_offer", "late-bootstrap-commit")
        clock = SimpleNamespace(now=wall_time())

        def late_commit(event):
            if phase == "callback" and event["phase"] == "before-bootstrap-commit":
                state = self.intake._load("alice", self.ref)
                job = next(iter(state["stage1_query_jobs"].values()))
                clock.now = job["deadline_unix"] + 1
            return True

        original_save = self.intake._save

        def late_save(state, kind, payload):
            if (
                phase == "sqlite"
                and kind == "stage1-query-bootstrap-observation"
                and payload.get("status") == "completed"
            ):
                job = next(iter(state["stage1_query_jobs"].values()))
                clock.now = job["deadline_unix"] + 1
            return original_save(state, kind, payload)

        self.queries.admit = late_commit
        with (
            patch(
                "research_workspace_native.project_stage1_queries.time",
                SimpleNamespace(time=lambda: clock.now),
            ),
            patch(
                "stage1_retrieval.runtime_identity.verify_identity",
                side_effect=lambda pin, **kw: verify_identity(pin),
            ) as probe,
            patch.object(self.intake, "_save", side_effect=late_save),
        ):
            self.queries.bootstrap("alice-token", self.ref, body)
            self.queries.workers[self.ref].join(30)
            self.assertFalse(self.queries.workers[self.ref].is_alive())
            view = self.queries.read("alice-token", self.ref)
            self.assertEqual(view["jobs"][0]["status"], "execution-unknown")
            self.assertEqual(
                view["jobs"][0]["error"]["code"], "project-query-bootstrap-expired"
            )
            self.assertIsNone(view["query_offer"])
            state = self.intake._load("alice", self.ref)
            self.assertIsNone(state.get("stage1_active"))
            self.assertEqual(state.get("stage1_runs", {}), {})
            self.assertNotIn(self.ref, self.queries.services)
            calls_before_replay = probe.call_count
            self.assertTrue(
                self.queries.bootstrap("alice-token", self.ref, body)["replayed"]
            )
            self.assertEqual(probe.call_count, calls_before_replay)
            self.assertEqual(
                sum(call.kwargs.get("probe") is True for call in probe.call_args_list),
                1,
            )
            self.assertEqual(view["budget"], dict(probes=1, attempts=0, seconds=30))

    def test_delivery_context_refuses_unknown_owned_writer_before_records_read(self):
        from research_workspace_native.project_stage1_delivery import (
            ProjectStage1DeliveryService,
        )

        self.authorize()
        self.bootstrap()
        service = self.queries.services[self.ref]
        pid = service._projects[self.ref]["pid"]
        with service.store._edit(
            pid,
            service._projects[self.ref]["owner"],
            service.store.snapshot(pid)["revision"],
            "test-retained-unknown",
            {"key": "unknown"},
        ) as saved:
            saved["intents"]["unknown"] = {
                "status": "execution-unknown",
                "principal": "alice",
            }
        self.assertEqual(
            self.stage1.read("alice-token", self.ref)["stage1_status"],
            "query-action-execution-unknown",
        )
        with self.assertRaisesRegex(SessionApiError, "query-unreconciled-action"):
            ProjectStage1DeliveryService(self.stage1).register_records(
                self.ref,
                records_path=self.root / "must-not-be-read",
                expected_records_sha256="0" * 64,
                expected_ledger_state_sha256="0" * 64,
            )

"""Real brief/coverage/ledger/export tests with no network, source or model calls."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1 import ProjectStage1Service
from research_workspace_native.session_api import SessionApiError
from stage1_coverage.run import CoverageLedger
from stage1_export.bundle import validate_export
from stage1_ledger.validation import validate_run
from test_workspace_project_intake import (
    authenticate,
    bound_body,
    compile_body,
    submit_body,
)


class ProjectStage1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="project-stage1-")
        self.root = Path(self.tmp.name).resolve()
        self.intake = ProjectIntakeService(self.root, authenticate=authenticate)
        self.runner = Mock(side_effect=AssertionError("external query dispatched"))
        self.service = ProjectStage1Service(self.intake, query_runner=self.runner)

    def tearDown(self):
        self.intake.close()
        self.tmp.cleanup()

    def new(self, topic="Aircraft diagnosis with sensor drift", key="create"):
        receipt = self.intake.create("alice-token", {"key": key, "topic": topic})
        ref = receipt["project_ref"]
        view = self.intake.read("alice-token", ref)
        self.intake.submit("alice-token", ref, submit_body(view))
        view = self.intake.read("alice-token", ref)
        self.intake.compile("alice-token", ref, compile_body(view))
        return ref

    def initialize_body(self, ref, key="initialize"):
        view = self.intake.read("alice-token", ref)
        offer = self.service.offers("alice-token", ref)["initialization_offer"]
        return dict(
            bound_body(view, key),
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            confirmed=True,
        )

    def initialize(self, ref):
        receipt = self.service.initialize("alice-token", ref, self.initialize_body(ref))
        return receipt, self.service.read("alice-token", ref)

    def action_body(self, ref, key):
        view = self.intake.read("alice-token", ref)
        ledger = self.service.read("alice-token", ref)["ledger"]
        return dict(
            bound_body(view, key),
            ledger_state_sha256=ledger["state_sha256"],
            confirmed=True,
        )

    def query_body(self, ref, key="query"):
        query = self.service.read("alice-token", ref)["queries"][0]
        return dict(
            self.action_body(ref, key),
            query_ref=query["query_ref"],
            query_sha256=query["query_sha256"],
        )

    def private_ledger(self, ref):
        state = self.intake._load("alice", ref)
        run = state["stage1_runs"][state["stage1_active"]]
        return CoverageLedger(self.intake._path(ref, run["path"]))

    def test_two_unrelated_topics_initialize_actual_core_bound_ledgers(self):
        for key, topic in (
            ("aircraft", "Aircraft diagnosis with sensor drift"),
            ("music", "Polyphonic music transcription from sparse annotations"),
        ):
            with self.subTest(topic=topic):
                ref = self.new(topic, key)
                receipt, view = self.initialize(ref)
                ledger = self.private_ledger(ref)
                self.assertEqual(ledger.manifest["research_run"]["objective"], topic)
                self.assertEqual(ledger.manifest["mode"], "offline-import")
                coverage = ledger.coverage_state()
                self.assertEqual(coverage.active, 1)
                self.assertEqual(len(coverage.queries), 12)
                self.assertTrue(validate_run(ledger.root)["valid"])
                self.assertEqual(receipt["stage1_status"], "offline-ledger-active")
                self.assertEqual(view["ledger"]["counts"]["works"], 0)
                self.assertEqual(view["ledger"]["gate"]["outcome"], "review-required")
                self.assertFalse(view["query_execution_connected"])
                self.assertFalse(view["stage1_complete"])
                self.assertIsNone(view["canonical_package"])
                self.assertIsNone(view["monetary_cost"])
                self.assertEqual(view["evaluation_status"], "not-scored")
                self.assertEqual(
                    view["later_stages"]["3"], {"status": "planned", "connected": False}
                )
        self.runner.assert_not_called()

    def test_init_requires_confirmed_core_intake_and_rejects_client_runtime_fields(
        self,
    ):
        raw = self.intake.create(
            "alice-token", {"key": "pending", "topic": "Coral reef surveillance"}
        )
        ref = raw["project_ref"]
        self.assertEqual(
            self.service.read("alice-token", ref)["stage1_status"], "intake-not-ready"
        )
        self.assertIsNone(
            self.service.offers("alice-token", ref)["initialization_offer"]
        )
        with self.assertRaises(SessionApiError):
            self.service.initialize(
                "alice-token",
                ref,
                dict(
                    bound_body(self.intake.read("alice-token", ref), "init"),
                    offer_ref="caller-offer",
                    offer_sha256="0" * 64,
                    confirmed=True,
                ),
            )
        self.assertEqual(list(self.root.rglob("run_manifest.json")), [])
        ready = self.new(key="ready")
        body = self.initialize_body(ready)
        for field in ("root", "owner", "epoch", "rpc", "permit", "principal"):
            with self.subTest(field=field), self.assertRaises(SessionApiError):
                self.service.initialize("alice-token", ready, {**body, field: "caller"})

    def test_reopen_same_key_does_not_create_or_replay_core_mutations(self):
        ref = self.new()
        body = self.initialize_body(ref)
        first = self.service.initialize("alice-token", ref, body)
        query = self.query_body(ref)
        query_receipt = self.service.plan_query("alice-token", ref, query)
        self.intake.close()
        self.intake = ProjectIntakeService(self.root, authenticate=authenticate)
        self.service = ProjectStage1Service(self.intake, query_runner=self.runner)
        with (
            patch.object(
                CoverageLedger, "create", side_effect=AssertionError("second ledger")
            ),
            patch.object(
                CoverageLedger,
                "start_planned",
                side_effect=AssertionError("second query"),
            ),
        ):
            replay = self.service.initialize(
                "alice-token", ref, {**body, "revision": 999}
            )
            self.assertTrue(replay["replayed"])
            self.assertEqual(replay["run_ref"], first["run_ref"])
            repeated = self.service.plan_query(
                "alice-token", ref, {**query, "revision": 999}
            )
            self.assertTrue(repeated["replayed"])
            self.assertEqual(
                repeated["query_event_id"], query_receipt["query_event_id"]
            )
        view = self.service.read("alice-token", ref)
        self.assertEqual(len(view["ledger"]["pending_actions"]), 1)
        self.assertEqual(view["queries"][0]["status"], "intent-recorded-not-executed")
        self.runner.assert_not_called()

    def test_real_checkpoint_and_export_preserve_gate_unknowns_and_unscored_evidence(
        self,
    ):
        ref = self.new()
        self.initialize(ref)
        checkpoint = self.service.checkpoint(
            "alice-token", ref, self.action_body(ref, "checkpoint")
        )
        self.assertEqual(checkpoint["next_allowed_action"], "continue")
        self.assertEqual(len(checkpoint["stage_result"]["outputs"]), 4)
        self.assertFalse(checkpoint["stage1_complete"])
        view = self.service.read("alice-token", ref)
        self.assertTrue(view["checkpoint"]["current"])
        self.assertEqual(view["checkpoint"]["stage_result"]["status"], "running")
        output = self.service.export(
            "alice-token", ref, self.action_body(ref, "export")
        )
        state = self.intake._load("alice", ref)
        artifact = state["stage1_exports"][output["artifact_ref"]]
        report = validate_export(self.intake._path(ref, artifact["path"]))
        self.assertTrue(report["valid"])
        self.assertEqual(output["artifact_kind"], "Stage1ExportManifest")
        self.assertEqual(output["evaluation_status"], "not-scored")
        self.assertFalse(output["stage1_complete"])
        self.assertIsNone(output["canonical_package"])
        self.runner.assert_not_called()

    def test_get_offers_history_do_not_mutate_ledger_or_execute_any_query(self):
        ref = self.new()
        self.initialize(ref)
        ledger = self.private_ledger(ref)
        before = {
            p.relative_to(ledger.root).as_posix(): p.read_bytes()
            for p in ledger.root.rglob("*")
            if p.is_file()
        }
        with (
            patch.object(
                CoverageLedger,
                "start_planned",
                side_effect=AssertionError("GET wrote intent"),
            ),
            patch.object(
                CoverageLedger,
                "checkpoint",
                side_effect=AssertionError("GET checkpointed"),
            ),
            patch.object(
                CoverageLedger,
                "open_round",
                side_effect=AssertionError("GET opened round"),
            ),
        ):
            for _ in range(2):
                self.service.read("alice-token", ref)
                self.service.offers("alice-token", ref)
                self.service.history("alice-token", ref)
        after = {
            p.relative_to(ledger.root).as_posix(): p.read_bytes()
            for p in ledger.root.rglob("*")
            if p.is_file()
        }
        self.assertEqual(before, after)
        self.runner.assert_not_called()

    def test_cross_project_query_and_changed_payload_reject_without_dispatch(self):
        first, second = (
            self.new(key="one"),
            self.new("Coral reef surveillance", key="two"),
        )
        self.initialize(first)
        self.initialize(second)
        old = self.query_body(first)
        foreign = dict(
            self.action_body(second, "foreign"),
            query_ref=old["query_ref"],
            query_sha256=old["query_sha256"],
        )
        with self.assertRaises(SessionApiError):
            self.service.plan_query("alice-token", second, foreign)
        self.assertEqual(
            self.service.read("alice-token", second)["ledger"]["pending_actions"], []
        )
        saved = self.service.plan_query("alice-token", first, old)
        with self.assertRaisesRegex(SessionApiError, "idempotency-payload-differs"):
            self.service.plan_query(
                "alice-token", first, {**old, "query_sha256": "0" * 64}
            )
        self.assertEqual(
            self.service.action("alice-token", first, old["key"])["query_event_id"],
            saved["query_event_id"],
        )
        for credential in ("bob-token", "wrong"):
            with self.assertRaises(SessionApiError):
                self.service.read(credential, first)
        self.runner.assert_not_called()

    def test_budget_and_consent_without_permit_do_not_authorize_runner(self):
        ref = self.new()
        view = self.intake.read("alice-token", ref)
        body = submit_body(view)
        body = {
            name: value
            for name, value in body.items()
            if name not in {"choices", "formal_target", "priority_reading_target"}
        }
        body["key"] = "resource-update"
        body["budgets"].update(search_calls=10, source_reads=20, seconds=120, rounds=2)
        body["consent"].update(external_search=True, public_source_read=True)
        self.intake.configure("alice-token", ref, body)
        self.initialize(ref)
        query = self.query_body(ref)
        with self.assertRaises(SessionApiError) as failure:
            self.service.execute_query("alice-token", ref, query)
        self.assertIn(
            "stage1-query-execution-unconnected", failure.exception.receipt["error"]
        )
        self.assertEqual(failure.exception.receipt["status"], "failed")
        self.assertEqual(
            self.service.read("alice-token", ref)["ledger"]["pending_actions"], []
        )
        self.intake.close()
        self.intake = ProjectIntakeService(self.root, authenticate=authenticate)
        self.service = ProjectStage1Service(self.intake, query_runner=self.runner)
        replay = self.service.execute_query(
            "alice-token", ref, {**query, "revision": 999}
        )
        self.assertEqual(replay["status"], "failed")
        self.assertTrue(replay["replayed"])
        self.runner.assert_not_called()

    def test_source_revision_and_ledger_tampering_fail_closed(self):
        ref = self.new()
        self.initialize(ref)
        old = self.query_body(ref)
        self.service.plan_query("alice-token", ref, old)
        stale = {**old, **bound_body(self.intake.read("alice-token", ref), "stale")}
        with self.assertRaises(SessionApiError) as failure:
            self.service.checkpoint(
                "alice-token",
                ref,
                {
                    name: value
                    for name, value in stale.items()
                    if name not in {"query_ref", "query_sha256"}
                },
            )
        self.assertIn("stage1-ledger-state-stale", failure.exception.receipt["error"])
        ledger = self.private_ledger(ref)
        (ledger.root / "run_manifest.json").write_bytes(b"{}\n")
        with self.assertRaisesRegex(SessionApiError, "stage1-ledger-manifest-differs"):
            self.service.read("alice-token", ref)

    def test_new_input_invalidates_old_ledger_but_preserves_its_records(self):
        ref = self.new()
        receipt, _ = self.initialize(ref)
        ledger = self.private_ledger(ref)
        previous = (ledger.root / "stage_events.jsonl").read_bytes()
        old_body = self.query_body(ref)
        self.intake.revise(
            "alice-token",
            ref,
            dict(
                bound_body(self.intake.read("alice-token", ref), "revise"),
                topic="Coral reef surveillance",
            ),
        )
        self.assertEqual(
            self.service.read("alice-token", ref)["stage1_status"], "stale-input"
        )
        with self.assertRaises(SessionApiError):
            self.service.plan_query(
                "alice-token", ref, {**old_body, "key": "old-source"}
            )
        self.assertEqual((ledger.root / "stage_events.jsonl").read_bytes(), previous)
        self.assertEqual(
            self.service.action("alice-token", ref, "initialize")["run_ref"],
            receipt["run_ref"],
        )


if __name__ == "__main__":
    unittest.main()

"""Actual Core operations; fixed authored bytes, never search/model execution."""

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_project_stage1 as fixture
from research_workspace_native.project_stage1_fixed_replay import (
    FixedReplayInputs,
    FixedReplayStage1Service,
)
from stage1_deliverable.common import sha


class FixedReplayTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.ProjectStage1Tests()
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.ref = self.case.new()
        self.case.initialize(self.ref)
        self.inputs = self.case.root.parent / (self.case.root.name + "-fixed")
        self.inputs.mkdir()
        import shutil

        self.addCleanup(shutil.rmtree, self.inputs)
        self.raw = b'[{"title":"Authored engineering record","authors":["Synthetic"],"year":2024,"version":"v1"}]'
        (self.inputs / "response.json").write_bytes(self.raw)
        binding = self.case.intake.binding(self.ref)
        queries = self.case.service.read("alice-token", self.ref)["queries"]
        rows = {(q["query"], q["purpose"], q["year"]) for q in queries}
        self.config = dict(
            kind="Stage1FixedOfflineReplay",
            schema_version="1.0.0",
            scope="authored-engineering-only",
            project_ref=self.ref,
            input_version=1,
            brief_sha256=binding["brief_sha256"],
            plan_manifest_sha256=binding["plan_manifest_sha256"],
            responses=[
                dict(
                    query=q,
                    purpose=p,
                    year=y,
                    backend="openalex",
                    records_path="response.json",
                    records_sha256=sha(self.raw),
                    http_status=200,
                )
                for q, p, y in sorted(rows, key=str)
            ],
        )
        self.path = self.inputs / "config.json"
        self.connect()

    def connect(self):
        self.path.write_bytes(json.dumps(self.config, sort_keys=True).encode())
        self.pin = sha(self.path.read_bytes())
        self.case.service = FixedReplayStage1Service(
            self.case.intake, fixed_inputs=FixedReplayInputs(self.path, self.pin)
        )

    def snapshot(self):
        ledger = self.case.private_ledger(self.ref)
        return (
            ledger.state_hash(),
            len(ledger.events()),
            self.case.intake.db.execute(
                "SELECT count(*) FROM intake_actions"
            ).fetchone()[0],
            self.case.intake.db.execute(
                "SELECT count(*) FROM intake_events"
            ).fetchone()[0],
        )

    def body(self, index=0, key="replay"):
        view = self.case.service.read("alice-token", self.ref)
        q = view["queries"][index]
        return dict(
            self.case.action_body(self.ref, key),
            query_ref=q["query_ref"],
            query_sha256=q["query_sha256"],
        )

    def test_all_twelve_same_plan_queries_and_same_key_cold_reopen(self):
        first = None
        import subprocess

        original_popen = subprocess.Popen

        def local_git_only(argv, *args, **kwargs):
            if Path(argv[0]).stem != "git":
                raise AssertionError("external process forbidden")
            return original_popen(argv, *args, **kwargs)

        with (
            patch(
                "socket.create_connection",
                side_effect=AssertionError("network forbidden"),
            ),
            patch("subprocess.Popen", side_effect=local_git_only),
        ):
            for i in range(12):
                body = self.body(i, "query-" + str(i))
                receipt = self.case.service.execute_query("alice-token", self.ref, body)
                self.assertEqual(receipt["mode"], "fixed-offline-engineering")
                if i == 0:
                    first = body
        view = self.case.service.read("alice-token", self.ref)
        self.assertEqual(view["ledger"]["counts"]["queries"], 12)
        self.assertEqual(view["ledger"]["counts"]["works"], 1)
        self.assertEqual(view["ledger"]["counts"]["decisions"], 0)
        self.assertIsNone(view["canonical_package"])
        before = self.snapshot()
        self.case.service = FixedReplayStage1Service(
            self.case.intake, fixed_inputs=FixedReplayInputs(self.path, self.pin)
        )
        self.assertTrue(
            self.case.service.execute_query("alice-token", self.ref, first)["replayed"]
        )
        self.assertEqual(before, self.snapshot())
        for q in view["queries"]:
            self.assertFalse(q["execution_available"])
            self.assertEqual(q["status"], "fixed-replay-recorded")
        self.assertEqual(view["fixed_replay"]["completed_queries"], 12)

    def empty_config(self):
        (self.inputs / "empty.json").write_bytes(b"[]")
        for row in self.config["responses"]:
            row.update(records_path="empty.json", records_sha256=sha(b"[]"))
        self.connect()

    def test_completed_a_is_not_completed_b_and_same_key_cannot_cross_config(self):
        first = self.body()
        for i in range(12):
            self.case.service.execute_query(
                "alice-token", self.ref, first if i == 0 else self.body(i, str(i))
            )
        old_pin = self.pin
        before = self.snapshot()
        self.empty_config()
        view = self.case.service.read("alice-token", self.ref)
        self.assertEqual(view["fixed_replay"]["completed_queries"], 0)
        self.assertEqual(
            view["fixed_replay"]["reason"], "fixed-replay-history-config-differs"
        )
        self.assertTrue(
            all(q["historical_config_sha256"] == [old_pin] for q in view["queries"])
        )
        with self.assertRaisesRegex(Exception, "fixed-replay-history-config-differs"):
            self.case.service.execute_query("alice-token", self.ref, first)
        self.assertEqual(before, self.snapshot())

    def test_partial_a_cannot_append_b_or_replay_a_under_b(self):
        first = self.body()
        self.case.service.execute_query("alice-token", self.ref, first)
        before = self.snapshot()
        self.empty_config()
        view = self.case.service.read("alice-token", self.ref)
        self.assertEqual(view["fixed_replay"]["completed_queries"], 0)
        self.assertFalse(any(q["execution_available"] for q in view["queries"]))
        for body in (first, self.body(1, "new-config")):
            with self.assertRaisesRegex(
                Exception, "fixed-replay-history-config-differs"
            ):
                self.case.service.execute_query("alice-token", self.ref, body)
        self.assertEqual(before, self.snapshot())

    def test_same_key_rechecks_project_plan_and_current_material_bytes(self):
        body = self.body()
        self.case.service.execute_query("alice-token", self.ref, body)
        before = self.snapshot()
        original = copy.deepcopy(self.config)
        for field, value in (
            ("project_ref", "another"),
            ("input_version", 2),
            ("brief_sha256", "0" * 64),
            ("plan_manifest_sha256", "0" * 64),
        ):
            with self.subTest(field=field):
                self.config = dict(original, **{field: value})
                self.connect()
                self.assertEqual(
                    self.case.service.read("alice-token", self.ref)["fixed_replay"][
                        "completed_queries"
                    ],
                    0,
                )
                with self.assertRaises(Exception):
                    self.case.service.execute_query("alice-token", self.ref, body)
        self.config = original
        self.connect()
        (self.inputs / "response.json").write_bytes(b"[]")
        with self.assertRaises(Exception):
            self.case.service.execute_query("alice-token", self.ref, body)
        (self.inputs / "response.json").write_bytes(self.raw)
        self.assertTrue(
            self.case.service.execute_query("alice-token", self.ref, body)["replayed"]
        )
        self.assertEqual(before, self.snapshot())

    def test_unattributed_legacy_attempt_remains_unknown_without_mutation(self):
        # An ordinary pre-fixed-input Core record is valid, but has no pin.
        ledger = self.case.private_ledger(self.ref)
        query = self.case.service.read("alice-token", self.ref)["queries"][0]
        started = ledger.start_planned(query["planned_query_id"])
        attempt = ledger.start(
            "backend", {"query": query["query"]}, backend="openalex", parent_id=started
        )
        raw = ledger.save_bytes(self.raw, producer=attempt)
        ledger.finish(
            attempt,
            outcome="success_nonempty",
            http_status=200,
            exit_code=0,
            stdout=raw,
            stderr=raw,
            records=raw,
        )
        ledger.complete_query(started)
        ledger.extract()
        before = self.snapshot()
        view = self.case.service.read("alice-token", self.ref)
        self.assertEqual(view["fixed_replay"]["completed_queries"], 0)
        self.assertEqual(
            view["fixed_replay"]["reason"], "fixed-replay-history-unattributed"
        )
        self.assertEqual(view["queries"][0]["historical_config_sha256"], [])
        with self.assertRaisesRegex(Exception, "fixed-replay-history-unattributed"):
            self.case.service.execute_query(
                "alice-token", self.ref, self.body(1, "next")
            )
        self.assertEqual(before, self.snapshot())

    def test_wrong_binding_confirmation_and_stale_refuse_without_actions(self):
        good = self.body()
        for change in [
            dict(input_version="1"),
            dict(input_version=2),
            dict(confirmed=False),
            dict(query_sha256="0" * 64),
            dict(ledger_state_sha256="0" * 64),
            dict(revision=0),
        ]:
            before = self.snapshot()
            with self.subTest(change=change), self.assertRaises(Exception):
                self.case.service.execute_query(
                    "alice-token", self.ref, {**good, **change}
                )
            self.assertEqual(before, self.snapshot())
        before = self.snapshot()
        with self.assertRaises(Exception):
            self.case.service.execute_query("mallory-token", self.ref, good)
        self.assertEqual(before, self.snapshot())

    def test_missing_template_and_foreign_project_pin_refuse_without_write(self):
        for change in [
            dict(project_ref="project-other"),
            dict(input_version=2),
            dict(brief_sha256="0" * 64),
            dict(plan_manifest_sha256="0" * 64),
        ]:
            original = copy.deepcopy(self.config)
            self.config.update(change)
            self.connect()
            before = self.snapshot()
            with self.assertRaises(Exception):
                self.case.service.execute_query("alice-token", self.ref, self.body())
            self.assertEqual(before, self.snapshot())
            self.config = original
        self.config["responses"] = [
            {**self.config["responses"][0], "query": "different query"}
        ]
        self.connect()
        before = self.snapshot()
        with self.assertRaises(Exception):
            self.case.service.execute_query("alice-token", self.ref, self.body())
        self.assertEqual(before, self.snapshot())

    def test_tampered_config_and_bytes_refuse_without_write(self):
        body = self.body()
        before = self.snapshot()
        for path in [self.path, self.inputs / "response.json"]:
            raw = path.read_bytes()
            path.write_bytes(raw + b" ")
            with self.assertRaises(Exception):
                self.case.service.execute_query("alice-token", self.ref, body)
            self.assertEqual(before, self.snapshot())
            path.write_bytes(raw)

    def test_second_key_and_existing_intent_do_not_repeat(self):
        self.case.service.execute_query("alice-token", self.ref, self.body())
        before = self.snapshot()
        with self.assertRaises(Exception):
            self.case.service.execute_query(
                "alice-token", self.ref, self.body(key="second")
            )
        self.assertEqual(before, self.snapshot())
        self.case.service.plan_query("alice-token", self.ref, self.body(1, "intent"))
        before = self.snapshot()
        with self.assertRaises(Exception):
            self.case.service.execute_query(
                "alice-token", self.ref, self.body(1, "pending")
            )
        self.assertEqual(before, self.snapshot())

    def test_invalid_inputs_and_unconfigured_original_stay_closed(self):
        original = copy.deepcopy(self.config)
        for path in ["../escape.json", "C:escape.json"]:
            self.config = copy.deepcopy(original)
            self.config["responses"][0]["records_path"] = path
            with self.assertRaises(Exception):
                self.connect()
        self.config = copy.deepcopy(original)
        self.config["responses"].append(self.config["responses"][0])
        with self.assertRaises(Exception):
            self.connect()
        self.case.service = fixture.ProjectStage1Service(self.case.intake)
        with self.assertRaises(Exception):
            self.case.service.execute_query("alice-token", self.ref, self.body())
        self.assertEqual(
            self.case.service.read("alice-token", self.ref)["ledger"]["counts"][
                "queries"
            ],
            0,
        )

    def test_write_then_error_preserves_unknown_and_blocks_other_keys_on_reopen(self):
        body = self.body()
        with patch.object(
            fixture.CoverageLedger,
            "extract",
            side_effect=OSError("after recorded query"),
        ):
            with self.assertRaises(Exception):
                self.case.service.execute_query("alice-token", self.ref, body)
        receipt = self.case.intake.action(
            "alice-token", body["key"], project_ref=self.ref
        )
        self.assertEqual(receipt["status"], "execution-unknown")
        self.case.service = FixedReplayStage1Service(
            self.case.intake, fixed_inputs=FixedReplayInputs(self.path, self.pin)
        )
        before = self.snapshot()
        replay = self.case.service.execute_query("alice-token", self.ref, body)
        self.assertEqual(replay["status"], "execution-unknown")
        self.assertTrue(replay["replayed"])
        view = self.case.service.read("alice-token", self.ref)
        self.assertTrue(view["coverage_actions"]["held"])
        self.assertFalse(any(q["execution_available"] for q in view["queries"]))
        with self.assertRaises(Exception):
            self.case.service.execute_query(
                "alice-token", self.ref, self.body(1, "other")
            )
        with self.assertRaises(Exception):
            self.case.service.checkpoint(
                "alice-token", self.ref, self.case.action_body(self.ref, "checkpoint")
            )
        self.assertEqual(before, self.snapshot())


class FixedReplayLauncherTests(unittest.TestCase):
    def test_explicit_pair_pin_and_live_runtime_exclusion(self):
        import test_project_query_launcher as launcher

        case = launcher.ProjectQueryLauncherTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        args = case.args
        args.stage1_fixed_replay = case.config_path
        args.stage1_fixed_replay_sha256 = launcher.sha(case.config_path.read_bytes())
        with self.assertRaisesRegex(ValueError, "cannot compose"):
            case.inspect()
        args.stage1_query_runtime = None
        args.stage1_query_runtime_sha256 = None
        checked = case.inspect()
        self.assertEqual(checked["fixed_replay"]["path"], case.config_path)
        self.assertIsNone(checked["query_runtime"])
        for field in (
            "enable_public_sources",
            "enable_content_model",
            "enable_stage1_run",
            "existing_stage23_store",
        ):
            with self.subTest(field=field):
                setattr(args, field, True)
                with self.assertRaises(ValueError):
                    case.inspect()
                setattr(args, field, False)
        args.stage1_fixed_replay_sha256 = "0" * 64
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            case.inspect()
        args.stage1_fixed_replay_sha256 = None
        with self.assertRaises(ValueError):
            case.inspect()
        self.assertFalse((case.root / "projects").exists())

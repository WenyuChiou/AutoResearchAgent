"""Trusted launcher transport and durable unknown-write barrier, no source jobs."""

import hashlib
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_project_query_launcher as launcher
import test_project_stage1 as fixture
from research_workspace_native.project_stage1_coverage import unresolved


class OfflineSourceLauncherTests(unittest.TestCase):
    def setUp(self):
        self.case = launcher.ProjectQueryLauncherTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        args = self.case.args
        args.stage1_query_runtime = args.stage1_query_runtime_sha256 = None
        args.stage1_fixed_replay = self.case.config_path
        args.stage1_fixed_replay_sha256 = launcher.sha(
            self.case.config_path.read_bytes()
        )
        self.source = self.case.root / "sources.json"
        # This test checks raw pinned transport only; the real owner's strict
        # SDK/config validation runs in prepare and again at Host boundaries.
        self.source.write_bytes(b'{"transport-test":"not-a-valid-source-config"}')
        args.stage1_offline_sources_config = self.source
        args.stage1_offline_sources_sha256 = launcher.sha(self.source.read_bytes())

    def test_paired_pinned_transport_and_no_live_fallback(self):
        checked = self.case.inspect()
        self.assertEqual(checked["offline_sources"]["path"], self.source)
        self.assertIsNone(checked["query_runtime"])
        args = self.case.args
        for field in (
            "enable_content_model",
            "enable_public_sources",
            "enable_stage1_run",
            "existing_stage23_store",
        ):
            with self.subTest(field=field):
                setattr(args, field, True)
                with self.assertRaises(ValueError):
                    self.case.inspect()
                setattr(args, field, False)
        args.stage1_fixed_replay = args.stage1_fixed_replay_sha256 = None
        with self.assertRaisesRegex(ValueError, "require explicit fixed"):
            self.case.inspect()
        self.assertFalse((self.case.root / "projects").exists())

    def test_missing_pin_and_changed_bytes_refuse_before_store(self):
        self.case.args.stage1_offline_sources_sha256 = None
        with self.assertRaisesRegex(ValueError, "required together"):
            self.case.inspect()
        self.case.args.stage1_offline_sources_sha256 = "0" * 64
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            self.case.inspect()
        self.assertFalse((self.case.root / "projects").exists())

    def test_v9_forwards_only_explicit_trusted_options_and_restores_allowlist(self):
        ui = Path(__file__).resolve().parents[3] / "harness-ui"
        with patch.object(sys, "path", [str(ui), *sys.path]):
            v9 = runpy.run_path(str(ui / "run_v9.py"))
        v7 = v9["run_v7"]
        original = v7.HOST_KEYS
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "incoming").mkdir()
            argv = [
                "--ui-state-root",
                str(root / "state"),
                "--incoming-root",
                str(root / "incoming"),
            ]

            def capture(rest):
                self.assertIn("stage1_offline_sources_config", v7.HOST_KEYS)
                self.assertIn("stage1_offline_sources_sha256", v7.HOST_KEYS)
                self.assertIn("--stage1-offline-sources-config", rest)
                return 17

            with patch.object(v7, "main", side_effect=capture):
                self.assertEqual(
                    v9["main"](
                        [
                            *argv,
                            "--stage1-offline-sources-config",
                            str(self.source),
                            "--stage1-offline-sources-sha256",
                            hashlib.sha256(self.source.read_bytes()).hexdigest(),
                        ]
                    ),
                    17,
                )
            self.assertEqual(v7.HOST_KEYS, original)
            with patch.object(
                v7,
                "main",
                side_effect=lambda rest: self.assertEqual(v7.HOST_KEYS, original),
            ):
                v9["main"](argv)
        self.assertEqual(v7.HOST_KEYS, original)


class OfflineSourceUnknownTests(unittest.TestCase):
    def test_uncertain_source_producer_survives_reopen_and_holds_new_keys(self):
        self.check_unknown(OSError("source producer outcome unavailable"))

    def test_source_failure_cannot_borrow_query_only_unsent_exception(self):
        self.check_unknown(fixture.SessionApiError("stage1-query-execution-unconnected"))

    def check_unknown(self, error):
        case = fixture.ProjectStage1Tests()
        case.setUp()
        self.addCleanup(case.tearDown)
        ref = case.new()
        case.initialize(ref)
        body = case.action_body(ref, "offline-source")
        ledger = case.private_ledger(ref)
        before = len(ledger.events())

        def partial(state, request_hash, actor):
            # The launcher slice owns the journal barrier, not the SDK writer.
            # An unobserved source failure cannot be treated as safely unsent.
            raise error

        with self.assertRaises(Exception):
            case.intake._perform("alice", ref, "stage1-offline-source", body, partial)
        receipt = case.intake.action("alice-token", body["key"], project_ref=ref)
        self.assertEqual(receipt["error"], str(error))
        self.assertEqual(len(ledger.events()), before)
        self.assertEqual(receipt["status"], "execution-unknown")
        self.assertEqual(receipt["failure_phase"], "core-write-outcome-unobserved")
        case.intake.close()
        case.intake = fixture.ProjectIntakeService(
            case.root, authenticate=fixture.authenticate
        )
        case.service = fixture.ProjectStage1Service(case.intake)
        snapshot = (
            ledger.state_hash(),
            len(ledger.events()),
            case.intake.db.total_changes,
        )
        replay = case.intake._perform(
            "alice",
            ref,
            "stage1-offline-source",
            body,
            lambda *args: self.fail("repeated source write"),
        )
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["status"], "execution-unknown")
        self.assertEqual(len(unresolved(case.service, ref, "alice", 1)), 1)
        self.assertTrue(
            case.service.read("alice-token", ref)["coverage_actions"]["held"]
        )
        with self.assertRaisesRegex(
            Exception, "stage1-coverage-write-outcome-unobserved"
        ):
            case.service.checkpoint(
                "alice-token", ref, case.action_body(ref, "checkpoint")
            )
        self.assertEqual(
            snapshot,
            (ledger.state_hash(), len(ledger.events()), case.intake.db.total_changes),
        )

"""Real run-authorized saved checkpoint/records/delivery; no external research."""

import unittest
import json
from unittest.mock import patch
import test_project_stage1_run_grant as grant_fixture
from research_workspace_native.project_stage1 import ProjectStage1Service
from research_workspace_native.project_run_authority import action_identity
from research_workspace_native.session_api import SessionApiError
from test_workspace_project_intake import bound_body


class SavedRunCheckpointTests(unittest.TestCase):
    setUp = grant_fixture.RunGrantTests.setUp
    body = grant_fixture.RunGrantTests.body
    authorize = grant_fixture.RunGrantTests.authorize

    def prepare(self):
        self.stage1 = ProjectStage1Service(self.intake)
        offer = self.stage1.read("alice-token", self.ref)["initialization_offer"]
        self.stage1.initialize(
            "alice-token",
            self.ref,
            dict(
                bound_body(self.intake.read("alice-token", self.ref), "initialize"),
                confirmed=True,
                offer_ref=offer["offer_ref"],
                offer_sha256=offer["offer_sha256"],
            ),
        )
        grant = self.authorize()
        body = dict(
            bound_body(self.intake.read("alice-token", self.ref), "preview"),
            confirmed=False,
            ledger_state_sha256=self.stage1.read("alice-token", self.ref)["ledger"][
                "state_sha256"
            ],
        )
        token = self.service.derive(
            "alice-token",
            self.ref,
            grant_ref=grant["grant_ref"],
            grant_sha256=grant["grant_sha256"],
            operation="records",
            identity=action_identity("stage1-checkpoint", body),
        )
        body.update(
            key=token.key + "-work",
            revision=self.intake.read("alice-token", self.ref)["revision"],
        )
        return grant, body, token

    def test_checkpoint_persists_real_run_proof_and_legacy_human_default(self):
        grant, body, token = self.prepare()
        result = self.stage1.checkpoint(
            "alice-token", self.ref, body, run_authorization=token
        )
        self.assertEqual(result["status"], "saved")
        saved = json.loads(
            self.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                ("alice", self.ref, body["key"]),
            ).fetchone()[0]
        )
        self.assertFalse(saved["request"]["confirmed"])
        self.assertEqual(saved["request"]["run_authority"]["action_key"], token.key)
        self.assertFalse(
            saved["request"]["run_authority"]["human_per_action_confirmation"]
        )
        state = self.intake._load("alice", self.ref)
        run = state["stage1_runs"][state["stage1_active"]]
        from stage1_coverage.run import CoverageLedger

        ledger = CoverageLedger(self.intake._path(self.ref, run["path"]))
        events = ledger.events()
        repeated = self.stage1.checkpoint(
            "alice-token", self.ref, dict(body, revision=999), run_authorization=token
        )
        self.assertTrue(repeated["replayed"])
        self.assertEqual(ledger.events(), events)
        human = dict(
            bound_body(self.intake.read("alice-token", self.ref), "human-checkpoint"),
            confirmed=True,
            ledger_state_sha256=ledger.state_hash(),
        )
        human_result = self.stage1.checkpoint("alice-token", self.ref, human)
        saved_human = json.loads(
            self.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                ("alice", self.ref, human["key"]),
            ).fetchone()[0]
        )
        self.assertTrue(saved_human["request"]["confirmed"])
        self.assertNotIn("run_authority", saved_human["request"])
        self.assertFalse(human_result["stage1_complete"])

    def test_json_forgery_and_wrong_operation_refuse_before_core_write(self):
        grant, body, token = self.prepare()
        before = self.intake.history("alice-token", self.ref)
        for changed in [
            dict(body, confirmed=True),
            dict(body, run_authority={}),
            dict(body, ledger_state_sha256="e" * 64),
        ]:
            with self.subTest(changed=changed), self.assertRaises(SessionApiError):
                self.stage1.checkpoint(
                    "alice-token", self.ref, changed, run_authorization=token
                )
        for authority in [{}, False, None]:
            with self.subTest(authority=authority), self.assertRaises(SessionApiError):
                self.stage1.checkpoint(
                    "alice-token", self.ref, body, run_authorization=authority
                )
        with self.assertRaises(SessionApiError):
            self.stage1._mutate(
                "alice-token",
                self.ref,
                body,
                "stage1-screen",
                lambda *a: {},
                run_authorization=token,
            )
        self.assertEqual(self.intake.history("alice-token", self.ref), before)
        self.now = grant["expires_at"]
        with self.assertRaises(SessionApiError):
            self.stage1.checkpoint(
                "alice-token", self.ref, body, run_authorization=token
            )
        self.assertEqual(self.intake.history("alice-token", self.ref), before)

    def test_expiry_after_actual_checkpoint_keeps_unknown_and_written_prefix(self):
        grant, body, token = self.prepare()
        from stage1_coverage.run import CoverageLedger

        state = self.intake._load("alice", self.ref)
        run = state["stage1_runs"][state["stage1_active"]]
        ledger = CoverageLedger(self.intake._path(self.ref, run["path"]))
        before = ledger.events()
        original = CoverageLedger.checkpoint
        written = []

        def expire(core):
            event = original(core)
            written.append(core.events())
            self.now = grant["expires_at"]
            return event

        with patch.object(CoverageLedger, "checkpoint", new=expire):
            with self.assertRaises(SessionApiError) as failed:
                self.stage1.checkpoint(
                    "alice-token", self.ref, body, run_authorization=token
                )
        self.assertEqual(failed.exception.receipt["status"], "execution-unknown")
        after = ledger.events()
        self.assertEqual(after, written[0])
        self.assertEqual(after[: len(before)], before)
        self.assertEqual(
            sum(row["payload"]["kind"] == "Checkpoint" for row in after[len(before) :]),
            1,
        )
        prior = self.intake.history("alice-token", self.ref)
        with self.assertRaises(SessionApiError):
            self.stage1.checkpoint(
                "alice-token", self.ref, body, run_authorization=token
            )
        self.assertEqual(self.intake.history("alice-token", self.ref), prior)
        self.assertEqual(ledger.events(), after)

    def test_post_append_view_failure_remains_unknown_after_reopen_and_new_key(self):
        from pathlib import Path
        from research_workspace_native.project_intake import ProjectIntakeService
        from research_workspace_native.project_stage1_run_grant import (
            ProjectStage1RunGrantService,
        )
        from stage1_coverage.run import CoverageLedger
        from test_workspace_project_intake import authenticate

        grant, body, token = self.prepare()
        state = self.intake._load("alice", self.ref)
        run = state["stage1_runs"][state["stage1_active"]]
        ledger = CoverageLedger(self.intake._path(self.ref, run["path"]))
        before = ledger.events()
        original = Path.write_text

        def fail(path, *args, **kwargs):
            if path.name == "coverage_and_stop.md":
                raise OSError("synthetic post-append view write failed")
            return original(path, *args, **kwargs)

        with patch.object(Path, "write_text", new=fail):
            with self.assertRaises(SessionApiError) as failed:
                self.stage1.checkpoint(
                    "alice-token", self.ref, body, run_authorization=token
                )
        self.assertEqual(failed.exception.receipt["status"], "execution-unknown")
        self.assertEqual(
            failed.exception.receipt["failure_phase"], "core-write-outcome-unobserved"
        )
        after = ledger.events()
        self.assertEqual(after[: len(before)], before)
        self.assertEqual(
            sum(x["payload"]["kind"] == "Checkpoint" for x in after[len(before) :]), 1
        )
        self.intake.close()
        self.intake = ProjectIntakeService(self.root, authenticate=authenticate)
        self.service = ProjectStage1RunGrantService(
            self.intake, runtime_sha256="a" * 64, clock=lambda: self.now
        )
        self.stage1 = ProjectStage1Service(self.intake)
        token = self.service.derive(
            "alice-token",
            self.ref,
            grant_ref=grant["grant_ref"],
            grant_sha256=grant["grant_sha256"],
            operation="records",
            identity=action_identity("stage1-checkpoint", body),
        )
        repeated = self.stage1.checkpoint(
            "alice-token", self.ref, dict(body, revision=999), run_authorization=token
        )
        self.assertEqual(repeated["status"], "execution-unknown")
        self.assertTrue(repeated["replayed"])
        # Checkpoints and their derived artifacts do not alter the semantic hash.
        # A new run-derived identity would correctly replay the same receipt.
        self.assertEqual(ledger.state_hash(), body["ledger_state_sha256"])
        fresh = dict(
            bound_body(self.intake.read("alice-token", self.ref), "fresh-checkpoint"),
            confirmed=True,
            ledger_state_sha256=ledger.state_hash(),
        )
        self.assertNotEqual(fresh["key"], body["key"])
        history = self.intake.history("alice-token", self.ref)
        with self.assertRaisesRegex(SessionApiError, "write-outcome-unobserved"):
            self.stage1.checkpoint("alice-token", self.ref, fresh)
        self.assertEqual(self.intake.history("alice-token", self.ref), history)
        self.assertEqual(ledger.events(), after)


if __name__ == "__main__":
    unittest.main()

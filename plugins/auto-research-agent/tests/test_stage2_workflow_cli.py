"""Focused CLI coverage for the offline Stage 2 workflow records."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stage2_fixture_helpers import write_stage2_fixture  # noqa: E402
from stage2_workflow.__main__ import main  # noqa: E402


class Stage2WorkflowCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sources = self.root / "sources"
        self.packet = write_stage2_fixture(self.sources, candidate_count=1)
        self.packet_path = self.root / "packet.json"
        self.packet_path.write_text(json.dumps(self.packet), encoding="utf-8")
        self.run = self.root / "run"
        self.settings_path = self.root / "settings.json"
        self.settings_path.write_text(
            json.dumps({"model": "test-model"}), encoding="utf-8"
        )
        self.policy_path = self.root / "policy.json"
        self.policy_path.write_text(
            json.dumps({"path": "policy.json", "sha256": "a" * 64}), encoding="utf-8"
        )
        self.empty_artifacts_path = self.root / "artifacts.json"
        self.empty_artifacts_path.write_text("{}", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def init_workflow(self):
        code, output, error = self.invoke(
            "init",
            "--packet",
            str(self.packet_path),
            "--source-root",
            str(self.sources),
            "--output",
            str(self.run),
            "--settings",
            str(self.settings_path),
            "--policy-ref",
            str(self.policy_path),
        )
        self.assertEqual((code, error), (0, ""))
        return json.loads(output)

    def test_stage3_inspection_rejects_git_output_before_reading(self):
        (self.root / ".git").mkdir()
        output = self.root / "private-handoff.json"
        command = "inspect-stage3-input --package not-read --delivery not-read"
        with patch("stage2_workflow.planning_handoff.inspect_planning_handoff") as read:
            code, text, error = self.invoke(
                *command.split(),
                "--expected-manifest-sha256",
                "a" * 64,
                "--output",
                str(output),
            )
        self.assertEqual((code, text), (2, ""))
        self.assertIn("planning-output-must-be-private", error)
        read.assert_not_called()
        self.assertFalse(output.exists())

    def test_init_and_inspect_report_hash_snapshot_and_pending_candidates(self):
        self.init_workflow()
        code, output, error = self.invoke("inspect", "--run", str(self.run))
        self.assertEqual((code, error), (0, ""))
        inspected = json.loads(output)
        self.assertEqual(len(inspected["head_sha256"]), 64)
        self.assertEqual(inspected["snapshot_count"], 1)
        self.assertEqual(inspected["pending_candidate_ids"], ["candidate-1"])

    def test_missing_source_returns_two_without_success_output(self):
        missing = self.root / "missing-sources"
        code, output, error = self.invoke(
            "init",
            "--packet",
            str(self.packet_path),
            "--source-root",
            str(missing),
            "--output",
            str(self.run),
            "--settings",
            str(self.settings_path),
            "--policy-ref",
            str(self.policy_path),
        )
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertIn("stage2-workflow:", error)

    def test_empty_finish_preserves_null_cost_and_does_not_reuse(self):
        self.init_workflow()
        code, output, _ = self.invoke("inspect", "--run", str(self.run))
        head = json.loads(output)["head_sha256"]
        code, output, _ = self.invoke(
            "start",
            "--run",
            str(self.run),
            "--action-id",
            "empty-1",
            "--kind",
            "search",
            "--inputs",
            str(self.settings_path),
            "--settings",
            str(self.settings_path),
            "--expected-head",
            head,
        )
        started = json.loads(output)
        code, output, error = self.invoke(
            "finish",
            "--run",
            str(self.run),
            "--action-id",
            "empty-1",
            "--status",
            "empty",
            "--artifacts",
            str(self.empty_artifacts_path),
            "--expected-head",
            started["event"]["event_sha256"],
        )
        self.assertEqual((code, error), (0, ""))
        finished = json.loads(output)
        self.assertEqual(finished["payload"]["result"]["artifacts"], {})
        self.assertIsNone(finished["payload"]["result"]["cost"])
        code, output, error = self.invoke(
            "start",
            "--run",
            str(self.run),
            "--action-id",
            "empty-1",
            "--kind",
            "search",
            "--inputs",
            str(self.settings_path),
            "--settings",
            str(self.settings_path),
            "--expected-head",
            finished["event_sha256"],
        )
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertIn("replay-not-authorized", error)

    def test_stale_expected_head_is_rejected(self):
        self.init_workflow()
        code, output, error = self.invoke(
            "inspect", "--run", str(self.run), "--expected-head", "0" * 64
        )
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertIn("workflow-head-receipt-mismatch", error)

    def test_review_plan_pending_reconciliation_and_exclusive_output(self):
        self.init_workflow()
        _, text, _ = self.invoke("inspect", "--run", str(self.run))
        head = json.loads(text)["head_sha256"]
        screening = self.root / "screening.json"
        screening.write_text(
            json.dumps(
                [
                    {
                        "candidate_id": "candidate-1",
                        "candidate_version": 1,
                        "included": True,
                        "distance": 0,
                        "reason": "Needs independent review",
                    }
                ]
            ),
            encoding="utf-8",
        )
        batch = self.root / "batch.json"
        plan_args = (
            "review-plan",
            "--run",
            str(self.run),
            "--expected-head",
            head,
            "--screening",
            str(screening),
            "--seed",
            "fixed",
            "--output",
            str(batch),
        )
        code, text, error = self.invoke(*plan_args)
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(
            json.loads(batch.read_text(encoding="utf-8")), json.loads(text)
        )
        original = batch.read_bytes()
        self.assertEqual(self.invoke(*plan_args)[0], 2)
        self.assertEqual(batch.read_bytes(), original)
        reviews = self.root / "reviews.json"
        reviews.write_text("[]", encoding="utf-8")
        resolutions = self.root / "resolutions.json"
        resolutions.write_text(
            json.dumps(
                {
                    "candidate_resolutions": [],
                    "next_step": "Wait for independent reviewers",
                }
            ),
            encoding="utf-8",
        )
        result = self.root / "reconciled.json"
        reconcile_args = (
            "reconcile",
            "--run",
            str(self.run),
            "--expected-head",
            head,
            "--batch",
            str(batch),
            "--reviews",
            str(reviews),
            "--resolutions",
            str(resolutions),
            "--output",
            str(result),
        )
        code, text, error = self.invoke(*reconcile_args)
        self.assertEqual((code, error), (0, ""))
        reconciled = json.loads(text)
        self.assertFalse(reconciled["local_reconciliation_ready"])
        self.assertEqual(reconciled["review_counts"]["missing"], 2)
        self.assertEqual(reconciled["recommendations"], [])
        malformed = {
            "candidate_id": "candidate-1",
            "candidate_version": 1,
            "role": "challenger",
            "status": "failed",
            "review": None,
            "error": "Failed",
        }
        for field in ("status", "candidate_id", "role", "candidate_version"):
            with self.subTest(field=field):
                reviews.write_text(
                    json.dumps([{**malformed, field: []}]), encoding="utf-8"
                )
                # Use a new output path: the failure must occur before publication.
                bad_output = self.root / (field + "-invalid.json")
                code, text, error = self.invoke(*reconcile_args[:-1], str(bad_output))
                self.assertEqual(code, 2)
                self.assertEqual(text, "")
                self.assertIn("stage2-workflow:", error)
                self.assertFalse(bad_output.exists())
        malformed.update(status="complete", error=None, review={"assessment": []})
        reviews.write_text(json.dumps([malformed]), encoding="utf-8")
        bad_output = self.root / "nested-invalid.json"
        self.assertEqual(self.invoke(*reconcile_args[:-1], str(bad_output))[0], 2)
        self.assertFalse(bad_output.exists())

    def test_review_plan_rejects_stale_snapshot_before_writing(self):
        self.init_workflow()
        _, text, _ = self.invoke("inspect", "--run", str(self.run))
        head = json.loads(text)["head_sha256"]
        batch = self.root / "foreign-batch.json"
        batch.write_text(json.dumps({"snapshot_sha256": "0" * 64}), encoding="utf-8")
        output = self.root / "should-not-exist.json"
        code, _, error = self.invoke(
            "reconcile",
            "--run",
            str(self.run),
            "--expected-head",
            head,
            "--batch",
            str(batch),
            "--reviews",
            "not-read.json",
            "--resolutions",
            "not-read.json",
            "--output",
            str(output),
        )
        self.assertEqual(code, 2)
        self.assertIn("review-batch-current-snapshot-mismatch", error)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

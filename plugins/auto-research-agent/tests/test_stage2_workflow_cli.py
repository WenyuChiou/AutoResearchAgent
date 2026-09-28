"""Focused CLI coverage for the offline Stage 2 workflow records."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest


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


if __name__ == "__main__":
    unittest.main()

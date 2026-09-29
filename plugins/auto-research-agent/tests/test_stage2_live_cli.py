"""CLI boundary tests for Stage 2 live adapters; all execution is synthetic."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
sys.path.insert(0, str(PLUGIN / "cli"))
sys.path.insert(0, str(HERE))

from stage2_common import canonical_hash  # noqa: E402
from stage2_fixture_helpers import write_stage2_fixture  # noqa: E402
from stage2_ideation import build_research_task  # noqa: E402
from stage2_live import __main__ as live_cli  # noqa: E402
from stage2_workflow.reviews import prepare_review  # noqa: E402
from test_stage2_checker import assessment  # noqa: E402


SNAPSHOT = "a" * 64
POLICY = {
    "schema_version": "3.1.0",
    "evaluator_bundle_sha256": "b" * 64,
    "timeout_seconds": 600,
    "max_transient_transport_retries": 1,
    "max_semantic_corrections_per_unit": 1,
    "retry_timeouts": False,
}


class Stage2LiveCliTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.sources = self.root / "sources"
        self.packet = write_stage2_fixture(self.sources, candidate_count=1)
        self.packet_path = self.write("packet.json", self.packet)
        self.policy_path = self.write("policy.json", POLICY)
        self.codex = self.root / "codex"
        self.codex.write_bytes(b"synthetic executable identity")
        self.evaluator_home = self.root / "evaluator-home"
        self.evaluator_home.mkdir()

    def write(self, name, value):
        path = self.root / name
        path.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        return path

    def invoke(self, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = live_cli.main([str(value) for value in argv])
        return code, stdout.getvalue(), stderr.getvalue()

    def common_task_args(self, command, output):
        return [
            command,
            "--packet",
            self.packet_path,
            "--source-root",
            self.sources,
            "--snapshot-sha256",
            SNAPSHOT,
            "--output",
            output,
        ]

    def test_controller_recovery_is_nonzero(self):
        spec = self.write("controller.json", {})
        args = [
            "controller",
            "--workflow",
            self.root / "workflow",
            "--controller-root",
            self.root / "controller",
            "--delivery",
            self.root / "delivery",
            "--spec",
            spec,
            "--expected-head",
            "a" * 64,
            "--output",
            self.root / "controller-result.json",
        ]
        with patch(
            "stage2_live.controller.run_controller",
            return_value={"status": "needs-recovery"},
        ):
            code, _, _ = self.invoke(args)
        self.assertEqual(code, 2)

    def test_research_task_is_native_capable_and_source_bound(self):
        output = self.root / "research-task.json"
        code, stdout, stderr = self.invoke(
            self.common_task_args("research-task", output)
        )

        self.assertEqual((code, stderr), (0, ""))
        result = json.loads(stdout)
        saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result, saved)
        self.assertEqual(result, build_research_task(self.packet, SNAPSHOT))
        self.assertEqual(result["tools_policy"], "native")
        self.assertEqual(result["snapshot_sha256"], SNAPSHOT)
        for source in self.packet["sources"]:
            self.assertIn(source["source_id"], result["prompt"])
            self.assertIn(source["sha256"], result["prompt"])

    def test_review_task_is_blind_to_peer_scores_and_conclusions(self):
        output = self.root / "review-task.json"
        code, stdout, stderr = self.invoke(
            self.common_task_args("review-task", output)
            + ["--candidate", "candidate-1", "--role", "challenger"]
        )

        self.assertEqual((code, stderr), (0, ""))
        result = json.loads(stdout)
        self.assertEqual(
            result,
            prepare_review(self.packet, "candidate-1", SNAPSHOT, "challenger"),
        )
        self.assertNotIn("scores", result)
        self.assertNotIn("assessments", result)
        self.assertNotIn("review_sha256s", result)
        self.assertNotIn("other reviewer output", json.dumps(result).lower())
        self.assertEqual(result["role"], "challenger")

    def review(self, role):
        view = prepare_review(self.packet, "candidate-1", SNAPSHOT, role)
        return {
            "role": role,
            "view_sha256": canonical_hash(view),
            "snapshot_sha256": SNAPSHOT,
            "candidate_id": "candidate-1",
            "candidate_version": 1,
            "assessment": assessment(self.packet),
            "session_id": f"synthetic-session-{role}",
            "native_artifact": {
                "path": f"synthetic/{role}.jsonl",
                "sha256": ("b" if role == "challenger" else "c") * 64,
            },
            "initial": True,
            "assumptions": ["A synthetic assumption."],
            "strongest_alternative": "A synthetic alternative.",
            "change_conditions": ["A synthetic change condition."],
        }

    def test_reconciliation_rejects_missing_role_without_output(self):
        reviews = self.write("one-review.json", [self.review("challenger")])
        output = self.root / "reconciliation-task.json"
        code, stdout, stderr = self.invoke(
            self.common_task_args("reconciliation-task", output)
            + ["--candidate", "candidate-1", "--reviews", reviews]
        )

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("failed", stderr)
        self.assertIn("review", stderr.lower())
        self.assertFalse(output.exists())

    def test_invalid_source_bytes_return_two_without_creating_output(self):
        source = self.sources / self.packet["sources"][0]["path"]
        source.write_text("tampered source bytes", encoding="utf-8")
        output = self.root / "invalid-source-output.json"
        code, stdout, stderr = self.invoke(
            self.common_task_args("research-task", output)
        )

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("hash mismatch", stderr)
        self.assertFalse(output.exists())

    def test_capture_rejects_injectable_process_runner_before_call(self):
        request = self.write(
            "capture-request.json",
            {
                "codex": str(self.codex),
                "codex_home": str(self.root / "subject-home"),
                "workspace": str(self.root / "workspace"),
                "prompt": "Synthetic prompt",
                "model": "test-model",
                "reasoning": "high",
                "input_bindings": {},
                "config_bindings": {},
                "policy_bindings": {},
                "output_dir": str(self.root / "capture"),
                "resume": False,
                "record_sha256_receipt": None,
                "process_runner": "forbidden-json-seam",
            },
        )
        receipt_output = self.root / "receipt.json"
        with patch.object(live_cli, "capture_native") as capture:
            code, stdout, stderr = self.invoke(
                [
                    "capture",
                    "--request",
                    request,
                    "--receipt-output",
                    receipt_output,
                ]
            )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("unsupported fields", stderr)
        self.assertFalse(receipt_output.exists())
        capture.assert_not_called()

    def test_extract_transports_exact_inputs_and_options_to_adapter(self):
        raw = "Exact UTF-8 proposal: café.\n"
        raw_path = self.root / "proposal.txt"
        raw_path.write_bytes(raw.encode("utf-8"))
        output = self.root / "extract-output"
        returned = {
            "kind": "SyntheticCliExtraction",
            "status": "passed",
            "native_execution_verified": None,
        }
        with patch.object(
            live_cli, "run_live_extraction", return_value=returned
        ) as adapter:
            code, stdout, stderr = self.invoke(
                [
                    "extract",
                    "--packet",
                    self.packet_path,
                    "--source-root",
                    self.sources,
                    "--snapshot-sha256",
                    SNAPSHOT,
                    "--raw-proposal",
                    raw_path,
                    "--codex",
                    self.codex,
                    "--evaluator-home",
                    self.evaluator_home,
                    "--model",
                    "test-model",
                    "--reasoning",
                    "high",
                    "--policy",
                    self.policy_path,
                    "--output",
                    output,
                ]
            )

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout), returned)
        adapter.assert_called_once_with(
            raw,
            self.packet,
            str(self.sources),
            SNAPSHOT,
            codex=str(self.codex),
            model="test-model",
            reasoning="high",
            execution_policy=POLICY,
            output_dir=str(output),
            resume=False,
            resume_receipt=None,
            evaluator_home=str(self.evaluator_home),
        )

    def test_duplicate_task_output_is_never_overwritten(self):
        output = self.root / "immutable-task.json"
        first = self.invoke(self.common_task_args("research-task", output))
        before = output.read_bytes()
        second = self.invoke(self.common_task_args("research-task", output))

        self.assertEqual(first[0], 0)
        self.assertEqual(second[0], 2)
        self.assertEqual(second[1], "")
        self.assertIn("exists", second[2].lower())
        self.assertEqual(output.read_bytes(), before)

    def test_verify_capture_rejects_wrong_receipt(self):
        capture = self.root / "capture"
        capture.mkdir()
        (capture / "run.json").write_text("{}\n", encoding="utf-8")
        code, stdout, stderr = self.invoke(
            [
                "verify-capture",
                "--capture",
                capture,
                "--receipt",
                "0" * 64,
            ]
        )

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("receipt differs", stderr)

    def test_judge_transports_distinct_homes_and_exact_options(self):
        actions = self.write("actions.json", {"synthetic": True})
        homes = [self.root / name for name in ("r1", "r2", "adj")]
        for home in homes:
            home.mkdir()
        output = self.root / "judge-output"
        returned = {
            "kind": "SyntheticCliJudge",
            "status": "complete",
            "formal_claim_ready": False,
        }
        with patch.object(
            live_cli, "run_stage2_judges", return_value=returned
        ) as adapter:
            code, stdout, stderr = self.invoke(
                [
                    "judge",
                    "--packet",
                    self.packet_path,
                    "--source-root",
                    self.sources,
                    "--subject-id",
                    "opaque-subject",
                    "--input-sha256",
                    "1" * 64,
                    "--config-sha256",
                    "2" * 64,
                    "--actions",
                    actions,
                    "--r1-home",
                    homes[0],
                    "--r2-home",
                    homes[1],
                    "--adj-home",
                    homes[2],
                    "--codex",
                    self.codex,
                    "--model",
                    "test-model",
                    "--reasoning",
                    "high",
                    "--policy",
                    self.policy_path,
                    "--output",
                    output,
                ]
            )

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout), returned)
        adapter.assert_called_once_with(
            self.packet,
            str(self.sources),
            "opaque-subject",
            "1" * 64,
            "2" * 64,
            {"synthetic": True},
            r1_home=str(homes[0]),
            r2_home=str(homes[1]),
            adj_home=str(homes[2]),
            codex=str(self.codex),
            model="test-model",
            reasoning="high",
            execution_policy=POLICY,
            output_dir=str(output),
            resume=False,
            resume_receipt=None,
        )

    def test_evaluator_failure_returns_nonzero_without_scoring_subject(self):
        actions = self.write("failed-actions.json", {"synthetic": True})
        args = [
            "judge",
            "--packet",
            self.packet_path,
            "--source-root",
            self.sources,
            "--subject-id",
            "opaque",
            "--input-sha256",
            "1" * 64,
            "--config-sha256",
            "2" * 64,
            "--actions",
            actions,
            "--r1-home",
            self.root / "r1",
            "--r2-home",
            self.root / "r2",
            "--adj-home",
            self.root / "adj",
            "--codex",
            self.codex,
            "--model",
            "test-model",
            "--reasoning",
            "high",
            "--policy",
            self.policy_path,
            "--output",
            self.root / "failed-judge",
        ]
        result = {
            "status": "evaluator-failure",
            "bundle": {"usable": False, "criteria": []},
        }
        with patch.object(live_cli, "run_stage2_judges", return_value=result):
            code, stdout, stderr = self.invoke(args)
        self.assertEqual((code, stderr), (2, ""))
        self.assertEqual(json.loads(stdout), result)


if __name__ == "__main__":
    unittest.main()

"""Orchestration replay, immutable failures, and formal v3.1 binding checks."""

import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage1_eval import pipeline_v31 as pipeline  # noqa: E402
from stage1_eval.common import EvaluationError, canonical, read_json, sha  # noqa: E402
from stage1_eval.__main__ import evaluate  # noqa: E402
from test_stage1_general_eval import judgment, spec  # noqa: E402


class PipelineV31Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = self.root / "task.txt"
        self.task.write_text(
            "Explore aging and household consumption.", encoding="utf-8"
        )
        self.spec = spec()
        self.spec["task_sha256"] = sha(self.task.read_bytes())
        (self.root / "spec.json").write_bytes(canonical(self.spec))
        self.capture = self.root / "capture"
        self.capture.mkdir()
        (self.capture / "run.json").write_bytes(b"{}")
        self.codex = self.root / "codex"
        self.codex.write_bytes(b"test codex bytes")
        self.home = self.root / "home"
        self.home.mkdir()
        self.args = SimpleNamespace(
            output=str(self.root / "eval"),
            resume_verified=False,
            task=str(self.task),
            spec=str(self.root / "spec.json"),
            hub=None,
            hub_command_json=json.dumps(["@python", "-m", "research_hub"]),
            artifact=[],
            saved_extraction=None,
            resume_pilot=False,
            execution_class="repair-diagnostic",
            portable_diagnostic=True,
            capture=str(self.capture),
            lock=None,
            codex=str(self.codex),
            evaluator_home=str(self.home),
            model="test-model",
            reasoning="high",
            mode="packet-only",
            background=None,
            background_sha256=None,
        )
        self.subject = {
            "status": "complete",
            "answer_sha256": "a" * 64,
            "evidence": {
                "answer": {
                    "text": "A method for household consumption.",
                    "sha256": "a" * 64,
                    "origin": "subject-answer",
                }
            },
        }
        self.extraction = {
            "works": [],
            "central_claims": [],
            "extraction_complete": True,
            "unextracted_reason": None,
        }
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(
            patch(
                "stage1_eval.formal.observe_capture_v31",
                return_value=(self.subject, {}),
            )
        )
        self.stack.enter_context(
            patch(
                "stage1_eval.formal.verify_binding_v31",
                return_value={"diagnostic": True},
            )
        )
        self.stack.enter_context(
            patch.object(pipeline, "installed_package_sha256", return_value="b" * 64)
        )
        self.extract = self.stack.enter_context(
            patch.object(
                pipeline,
                "extract_subject_v31",
                return_value=(self.extraction, {"replay_only": False}),
            )
        )
        self.stack.enter_context(
            patch.object(
                pipeline,
                "collect_sources_v31",
                return_value={"sources": [], "receipts": [], "public_fetches": []},
            )
        )
        self.judge = self.stack.enter_context(
            patch.object(
                pipeline,
                "judge_packet_v31",
                return_value={
                    "selected": {
                        phase: judgment(phase) for phase in ("content", "process")
                    },
                    "provenance": {},
                    "adjudicated_phases": [],
                },
            )
        )

    def test_full_orchestration_saves_replayable_inputs_and_rejects_rehashed_score(
        self,
    ):
        result = pipeline.evaluate_v31(self.args)
        self.assertEqual(result["schema_version"], "3.1.0")
        self.assertNotIn("formal_capture", result)
        root = Path(self.args.output)
        before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        self.args.resume_verified = True
        self.assertEqual(pipeline.evaluate_v31(self.args, replay_only=True), result)
        self.assertEqual(
            before, {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        )
        changed = read_json(root / "result.json")
        changed["dimensions"]["P1"]["observed_score_100"] = 100
        (root / "result.json").write_bytes(canonical(changed))
        with self.assertRaisesRegex(EvaluationError, "artifact changed: result.json"):
            pipeline.evaluate_v31(self.args, replay_only=True)

    def test_inventory_counts_all_attempt_origins_without_legacy_id_prefix(self):
        for attempt in (1, 2):
            self.subject["evidence"][f"attempt-{attempt}-trace-1"] = {
                "text": "native action",
                "sha256": "a" * 64,
                "origin": "subject-native-trace",
            }
        pipeline.evaluate_v31(self.args)
        packet = read_json(Path(self.args.output) / "evidence-packet.json")
        self.assertIn(
            "native trace events: 2",
            packet["process_evidence"]["capture-integrity"]["text"],
        )

    def test_failures_keep_distinct_attempts_and_do_not_create_scores(self):
        self.extract.side_effect = EvaluationError("unit subject-works-001 failed")
        for number in (1, 2):
            with self.assertRaisesRegex(EvaluationError, "subject-works-001"):
                pipeline.evaluate_v31(self.args)
            self.args.resume_verified = True
            failure = read_json(
                Path(self.args.output) / f"evaluation-attempt-{number:03d}.json"
            )
            self.assertEqual(failure["status"], "evaluator-error")
        self.assertFalse((Path(self.args.output) / "result.json").exists())
        self.judge.assert_not_called()

    def test_resume_rejects_changed_input_before_model_work(self):
        pipeline.evaluate_v31(self.args)
        self.extract.reset_mock()
        self.args.resume_verified = True
        self.args.model = "different-model"
        with self.assertRaisesRegex(EvaluationError, "evaluation-input.json"):
            pipeline.evaluate_v31(self.args)
        self.extract.assert_not_called()

    def test_legacy_cli_rejects_new_replay_flags(self):
        for flag in ("resume_verified", "replay_only", "portable_diagnostic"):
            with (
                self.subTest(flag=flag),
                self.assertRaisesRegex(EvaluationError, "v3.1-only"),
            ):
                evaluate(
                    SimpleNamespace(execution_class="exploratory-pilot", **{flag: True})
                )

    def test_usage_counts_native_attempts_once_and_keeps_absent_usage_unknown(self):
        archive = self.root / "unit.model-call"
        archive.mkdir()
        events = [
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 7,
                    "cached_input_tokens": 2,
                    "output_tokens": 3,
                },
            }
        ]
        (archive / "attempt-01.stdout.jsonl").write_bytes(
            b"\n".join(canonical(v) for v in events)
        )
        (archive / "attempt-01.record.json").write_bytes(
            canonical({"files": {"stdout": {"path": "attempt-01.stdout.jsonl"}}})
        )
        (self.root / "compatibility.jsonl").write_bytes(
            (archive / "attempt-01.stdout.jsonl").read_bytes()
        )
        value = pipeline.model_costs(self.root)
        self.assertEqual(value["attempts"], 1)
        self.assertEqual(value["tokens"]["input_tokens"], 7)
        self.assertIsNone(value["tokens"]["reasoning_output_tokens"])


if __name__ == "__main__":
    unittest.main()

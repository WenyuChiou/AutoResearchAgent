"""Complete native-unit submissions and replay, without scientific model claims."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import test_criterion_execution as process_fixture
import test_source_pipeline as source_fixture
from test_judging_v31 import _packet, _evidence, _core
from stage1_eval import complete_judging as complete
from stage1_eval.common import EvaluationError, canonical, read_json


class CompleteJudgingTests(unittest.TestCase):
    def setUp(self):
        self.process = process_fixture.CriterionExecutionTests()
        self.process.setUp()
        self.addCleanup(self.process.doCleanups)
        self.root, self.options = self.process.root, self.process.options
        self.packet = _packet()
        self.packet["spec"]["draft"]["needs"] = [
            {"need_id": "need-1"},
            {"need_id": "need-2"},
        ]
        self.audits = {role: {"summaries": [], "leaves": []} for role in ("r1", "r2")}
        self.prompts = []
        self.different_code = False
        self.false_major = False

    def respond(self, command, **kwargs):
        prompt = kwargs["input"].decode()
        if prompt.startswith("Evaluate the assigned Stage 1 criterion"):
            return self.process.respond(command, **kwargs)
        data, _ = json.JSONDecoder().raw_decode(prompt[prompt.index('{"unit_kind"') :])
        self.prompts.append(data)
        packet = data["packet"]
        rows = {
            "criteria": [],
            "core_assessments": [],
            "omission_assessments": [],
            "major_issues": [],
        }
        if self.false_major:
            rows["major_issues"] = [
                {
                    "issue_id": "synthetic",
                    "violation_type": "false-completion-or-failure-state",
                    "status": "confirmed",
                    "dimension": "P3",
                    "passages": [{"span_id": next(iter(packet["spans"]))}],
                    "reason": "Synthetic allegation with no contrary process evidence.",
                }
            ]
        if data["unit_kind"] == "core":
            for work in packet["assigned_work_ids"]:
                row = _core(work, "candidate")
                row["passages"] = []
                rows["core_assessments"].append(row)
        if "assigned_criterion_id" in packet:
            key = packet["assigned_criterion_id"]
            missing = (
                "identity-ambiguous"
                if self.different_code and "r2" in str(command)
                else "source-unavailable"
            )
            rows["criteria"] = [
                {
                    "criterion_id": key,
                    "status": "unverifiable",
                    "score": None,
                    "passages": [],
                    "reason": "Synthetic inaccessible source condition.",
                    "missing_evidence": ["Source unavailable"],
                    "conclusion_code": "unverifiable",
                    "missing_evidence_codes": [missing],
                }
            ]
            if key.startswith("P2"):
                rows["addressed_need_ids"] = [
                    n["need_id"] for n in packet["spec"]["draft"]["needs"]
                ]
        return self.process.fixture.completed(command, rows)

    def invoke(self, **kwargs):
        return complete.judge_packet_complete(
            self.packet,
            self.root / "complete",
            self.options,
            source_audits=self.audits,
            **kwargs,
        )

    def test_all_ten_criteria_native_archives_and_zero_call_replay(self):
        with patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=self.respond
        ) as calls:
            result = self.invoke()
            self.assertGreater(calls.call_count, 20)
        self.assertEqual(
            sum(len(row["criteria"]) for row in result["selected"].values()), 10
        )
        self.assertEqual(result["adjudicated_phases"], [])
        self.assertEqual(
            len([p for p in self.prompts if "assigned_criterion_id" in p["packet"]]), 14
        )
        for prompt in self.prompts:
            self.assertFalse(prompt["packet"]["judge_view_manifest"]["truncated"])
            self.assertNotIn("prior_judgments", prompt["packet"])
        for path in (self.root / "complete").rglob("*.view.json"):
            view = read_json(path)
            self.assertEqual(view["expected_span_ids"], view["planned_span_ids"])
            self.assertNotIn("submitted_span_ids", view)
        with patch("stage1_eval.model_calls.subprocess.run") as replay:
            self.assertEqual(self.invoke(replay_only=True), result)
        replay.assert_not_called()
        target = self.root / "complete/result.json"
        modified = read_json(target)
        modified["selected"]["content"]["criteria"][0]["score"] = 0
        target.write_bytes(canonical(modified))
        with patch("stage1_eval.model_calls.subprocess.run") as replay:
            with self.assertRaisesRegex(EvaluationError, "artifact changed"):
                self.invoke(replay_only=True)
        replay.assert_not_called()

    def test_content_over_old_view_limit_has_all_text_and_every_need(self):
        text = "Ordinary text. " * 4500 + "TAIL CONTRARY FINDING"
        self.packet["content_evidence"] = {"answer": _evidence(text)}
        with patch("stage1_eval.model_calls.subprocess.run", side_effect=self.respond):
            complete._content(
                self.packet, self.root / "content", self.options, self.audits, False
            )
        for prompt in self.prompts:
            self.assertEqual(
                "".join(r["text"] for r in prompt["packet"]["spans"].values()), text
            )
            self.assertIn("TAIL CONTRARY FINDING", str(prompt))
            self.assertEqual(
                [n["need_id"] for n in prompt["packet"]["spec"]["draft"]["needs"]],
                ["need-1", "need-2"],
            )

    def test_oversize_fails_before_call_instead_of_omitting_evidence(self):
        self.packet["content_evidence"] = {
            "answer": _evidence("X" * complete.MAX_COMPLETE_PROMPT_BYTES)
        }
        with patch("stage1_eval.model_calls.subprocess.run") as calls:
            with self.assertRaisesRegex(EvaluationError, "no evidence was omitted"):
                self.invoke()
        calls.assert_not_called()
        self.assertFalse((self.root / "complete/result.json").exists())

    def test_equal_null_scores_with_different_missing_codes_require_adjudication(self):
        self.different_code = True
        with patch("stage1_eval.model_calls.subprocess.run", side_effect=self.respond):
            result = self.invoke()
        self.assertEqual(result["adjudicated_phases"], ["content"])

    def test_major_review_rejects_ungrounded_confirmation_and_keeps_failures(self):
        self.false_major = True
        with patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=self.respond
        ) as calls:
            with self.assertRaisesRegex(EvaluationError, "contrary process evidence"):
                complete._call(
                    self.packet,
                    "process",
                    "review",
                    [],
                    None,
                    None,
                    self.root / "major",
                    "review",
                    self.options,
                    False,
                )
        self.assertEqual(calls.call_count, 2)
        self.assertEqual(
            len(list((self.root / "major/model-logs").glob("*.model-call"))), 2
        )
        self.assertFalse((self.root / "major/review.result.json").exists())

    def test_core_batches_preserve_every_work_and_missing_need_is_rejected(self):
        self.packet["extraction"]["works"] = [{"work_id": f"w{i}"} for i in range(5)]
        with patch("stage1_eval.model_calls.subprocess.run", side_effect=self.respond):
            result = self.invoke()
        self.assertEqual(len(result["selected"]["content"]["core_assessments"]), 5)
        core = [p for p in self.prompts if p["unit_kind"] == "core"]
        self.assertEqual(
            [len(p["packet"]["assigned_work_ids"]) for p in core], [4, 1, 4, 1]
        )

        def invalid(prompt, schema, root, label, options, normalize, **kwargs):
            raw = {
                "criteria": [{"criterion_id": "P2V3.SCOPE", "passages": []}],
                "core_assessments": [],
                "omission_assessments": [],
                "major_issues": [],
                "addressed_need_ids": ["need-1"],
            }
            return normalize(raw), {}

        with patch.object(complete, "run_unit", side_effect=invalid):
            with self.assertRaisesRegex(EvaluationError, "every frozen need"):
                complete._call(
                    self.packet,
                    "content",
                    "content",
                    [],
                    None,
                    None,
                    self.root / "invalid",
                    "criterion",
                    self.options,
                    False,
                    criterion="P2V3.SCOPE",
                    review={"omission_assessments": [], "major_issues": []},
                )

    def test_pipeline_connects_original_fields_audits_all_criteria_and_aggregation(
        self,
    ):
        scenario = source_fixture.SourcePipelineTests()
        scenario.setUp()
        self.addCleanup(scenario.doCleanups)
        scenario.flow.judge.side_effect = complete.judge_packet_complete

        def native(command, **kwargs):
            prompt = kwargs["input"].decode()
            if prompt.startswith(
                ("Extract only the original", "Audit only the supplied")
            ):
                return scenario.original.respond(command, **kwargs)
            return self.respond(command, **kwargs)

        with (
            patch.object(
                source_fixture.pipeline,
                "collect_sources_v31",
                return_value=scenario.sources,
            ),
            patch(
                "stage1_eval.model_calls.subprocess.run", side_effect=native
            ) as calls,
        ):
            result = source_fixture.pipeline.evaluate_v31(scenario.flow.args)
            self.assertEqual(
                sum(len(d["criteria"]) for d in result["dimensions"].values()), 10
            )
            self.assertEqual(result["evaluator_status"], "complete")
            self.assertEqual(result["scientific_readiness_status"], "inconclusive")
            costs = read_json(Path(scenario.flow.args.output) / "model-costs.json")
            self.assertGreater(costs["attempts"], 20)
            self.assertEqual(costs["attempts_without_usage"], costs["attempts"])
            self.assertIsNone(costs["tokens"]["input_tokens"])
            scenario.flow.args.resume_verified = True
            calls.reset_mock()
            self.assertEqual(
                source_fixture.pipeline.evaluate_v31(
                    scenario.flow.args, replay_only=True
                ),
                result,
            )
            calls.assert_not_called()


if __name__ == "__main__":
    unittest.main()

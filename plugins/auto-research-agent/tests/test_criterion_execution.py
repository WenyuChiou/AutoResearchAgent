"""Native archived executions; test outputs are synthetic, never AI evidence."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import unittest
from unittest import mock

import test_evaluator_units_v31 as fixtures
from stage1_eval.common import EvaluationError, canonical, read_json, sha
from stage1_eval.criterion_execution import (
    MAX_PLAN_UNITS_PER_CRITERION,
    PROMPT_BYTES,
    judge_process_complete,
    judge_process_criterion,
)
from stage1_eval.coverage_plan import build_coverage_plan


def packet(text, name="arbitrary-file"):
    return {
        "task": "Synthetic literature question",
        "spec": {"needs": ["synthetic need"]},
        "process_evidence": {
            name: {
                "text": text,
                "sha256": sha(text.encode()),
                "origin": "subject-delivered-artifact",
            }
        },
    }


class CriterionExecutionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.EvaluatorUnitTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root, self.options = self.fixture.root, self.fixture.options
        self.prompts = []

    def respond(self, command, **kwargs):
        prompt = kwargs["input"].decode()
        self.assertLessEqual(len(prompt.encode()), PROMPT_BYTES)
        data, _ = json.JSONDecoder().raw_decode(prompt.split("\n", 1)[1])
        self.prompts.append(data)
        observations = []
        for alias in reversed(data["assigned"]):
            text = data["spans"][alias]["text"]
            disposition = "contrary" if "CONTRARY" in text else "supporting"
            observations.append(
                {
                    "span": alias,
                    "disposition": disposition,
                    "reason": "Synthetic test disposition.",
                }
            )
        counts = {
            kind: sum(row["disposition"] == kind for row in observations)
            + sum(child["counts"].get(kind, 0) for child in data["children"].values())
            for kind in ("supporting", "contrary", "uncertain")
        }
        value = {
            "summaries": {
                key: "Synthetic " + key if count else ""
                for key, count in counts.items()
            },
            "observations": observations,
            "children": [
                {"child": key, "handling": "Preserve all inherited evidence."}
                for key in reversed(data["children"])
            ],
        }
        if data["final"]:
            missing = not data["children"]
            value["verdict"] = {
                "status": "unverifiable" if missing else "scored",
                "score": None if missing else (1 if counts["contrary"] else 2),
                "conclusion_code": (
                    "unverifiable"
                    if missing
                    else (
                        "partially-meets-anchor"
                        if counts["contrary"]
                        else "meets-anchor"
                    )
                ),
                "reason": "Synthetic anchor assessment, not a scientific result.",
                "missing_evidence": ["No evidence captured"] if missing else [],
                "missing_evidence_codes": (
                    ["decision-records-absent"] if missing else []
                ),
            }
        return self.fixture.completed(command, value)

    def invoke(self, subject, name="run", **kwargs):
        return judge_process_criterion(
            subject, "P3V3.DECISION_TRACE", self.root / name, self.options, **kwargs
        )

    def test_all_83_spans_reach_independent_native_units_and_tail_survives(self):
        text = "".join(
            f"{n:02d}:"
            + ("CONTRARY" if n in (41, 82) else "positive")
            + "x" * 888
            + "\n"
            for n in range(83)
        )
        subject = packet(text)
        index, _ = build_coverage_plan(subject, "process", max_unit_bytes=4500)
        self.assertGreaterEqual(len(index), 83)
        with mock.patch(
            "stage1_eval.model_calls._execute_bound_process", side_effect=self.respond
        ) as run:
            result = self.invoke(subject)
        self.assertEqual(set(result["roles"]), {"r1", "r2"})
        self.assertFalse(result["formal_eligible"])
        first = result["roles"]["r1"]
        self.assertEqual(first["verdict"]["score"], 1)
        self.assertEqual(
            first["coverage"]["expected_unit_ids"],
            first["coverage"]["completed_unit_ids"],
        )
        self.assertEqual(first["coverage"]["pending_unit_ids"], [])
        rows = [
            row
            for node in first["nodes"].values()
            for row in node["value"]["observations"]
        ]
        self.assertEqual(len(rows), len(index))
        self.assertTrue(
            any(
                "CONTRARY" in row["passage"]["text"] and row["passage"]["start"] > 70000
                for row in rows
            )
        )
        self.assertGreater(first["nodes"]["final"]["counts"]["contrary"], 0)
        self.assertEqual(run.call_count, 2 * len(first["nodes"]))
        self.assertFalse(any("prior_judgments" in data for data in self.prompts))
        with mock.patch("stage1_eval.model_calls._execute_bound_process") as replay:
            self.assertEqual(self.invoke(subject, replay_only=True), result)
        replay.assert_not_called()

    def test_semantic_disagreement_triggers_new_adjudication_generations(self):
        def disagree(command, **kwargs):
            self.respond(command, **kwargs)
            output = Path(command[command.index("-o") + 1])
            value = read_json(output)
            if "r2" in output.parts and value["observations"]:
                value["observations"][0]["disposition"] = "uncertain"
                value["summaries"]["uncertain"] = "Synthetic uncertainty."
            return self.fixture.completed(command, value)

        with mock.patch(
            "stage1_eval.model_calls._execute_bound_process", side_effect=disagree
        ):
            result = self.invoke(packet("positive evidence"))
        self.assertEqual(set(result["roles"]), {"r1", "r2", "adj"})
        self.assertEqual(result["selected_role"], "adj")
        self.assertEqual(
            result["roles"]["r1"]["verdict"]["score"],
            result["roles"]["r2"]["verdict"]["score"],
        )
        self.assertTrue(any("prior_judgments" in data for data in self.prompts))
        for data in self.prompts:
            self.assertNotIn("r1", data)
            self.assertNotIn("r2", data)

    def test_missing_evidence_code_disagreement_triggers_adjudication(self):
        def disagree(command, **kwargs):
            self.respond(command, **kwargs)
            output = Path(command[command.index("-o") + 1])
            value = read_json(output)
            if "r2" in output.parts and "verdict" in value:
                value["verdict"]["missing_evidence"] = [
                    "The stopping rationale is absent."
                ]
                value["verdict"]["missing_evidence_codes"] = ["stop-rationale-absent"]
            return self.fixture.completed(command, value)

        with mock.patch(
            "stage1_eval.model_calls._execute_bound_process", side_effect=disagree
        ):
            result = self.invoke(packet(""), name="missing-disagreement")
        self.assertEqual(set(result["roles"]), {"r1", "r2", "adj"})
        self.assertEqual(result["selected_role"], "adj")
        self.assertEqual(
            result["roles"]["r1"]["verdict"]["conclusion_code"],
            result["roles"]["r2"]["verdict"]["conclusion_code"],
        )
        self.assertNotEqual(
            result["roles"]["r1"]["verdict"]["missing_evidence_codes"],
            result["roles"]["r2"]["verdict"]["missing_evidence_codes"],
        )

    def test_missing_duplicate_and_rehashed_coverage_or_result_cannot_replay(self):
        subject = packet("positive evidence " * 500)
        with mock.patch(
            "stage1_eval.model_calls._execute_bound_process", side_effect=self.respond
        ):
            self.invoke(subject)
        for relative, mutate in (
            ("plan.json", lambda row: row["plan"]["units"].pop()),
            (
                "plan.json",
                lambda row: row["plan"]["units"].append(
                    deepcopy(row["plan"]["units"][0])
                ),
            ),
            ("r1/result.json", lambda row: row["coverage"]["completed_unit_ids"].pop()),
            ("result.json", lambda row: row.update(selected_role="adj")),
        ):
            path = self.root / "run" / relative
            original = path.read_bytes()
            changed = json.loads(original)
            mutate(changed)
            path.write_bytes(canonical(changed))
            sha(path.read_bytes())
            with mock.patch("stage1_eval.model_calls._execute_bound_process") as replay:
                with self.assertRaises(EvaluationError):
                    self.invoke(subject, replay_only=True)
            replay.assert_not_called()
            path.write_bytes(original)
        changed = deepcopy(subject)
        changed["process_evidence"]["arbitrary-file"]["source_version"] = "changed"
        with self.assertRaises(EvaluationError):
            self.invoke(changed, replay_only=True)

    def test_failed_middle_unit_records_pending_and_does_not_retry_timeout(self):
        count = 0

        def timeout(command, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise subprocess.TimeoutExpired(
                    command, 600, output=b"", stderr=b"timeout"
                )
            return self.respond(command, **kwargs)

        subject = packet("positive\n" * 3000)
        with mock.patch(
            "stage1_eval.model_calls._execute_bound_process", side_effect=timeout
        ):
            with self.assertRaises(EvaluationError):
                self.invoke(subject)
        failure = read_json(next((self.root / "run/r1").glob("*.error.json")))
        self.assertEqual(len(failure["completed_unit_ids"]), 1)
        self.assertTrue(failure["pending_unit_ids"])
        self.assertFalse(failure["semantic_aggregation_complete"])
        with mock.patch("stage1_eval.model_calls._execute_bound_process") as replay:
            with self.assertRaises(EvaluationError):
                self.invoke(subject)
        replay.assert_not_called()
        self.assertFalse((self.root / "run/result.json").exists())

    def test_format_filename_order_and_padding_keep_contrary_disposition(self):
        for n, text in enumerate(
            (
                "positive\nCONTRARY",
                "positive\n" * 200 + "CONTRARY",
                json.dumps({"notes": "positive\nCONTRARY"}),
            )
        ):
            with mock.patch(
                "stage1_eval.model_calls._execute_bound_process",
                side_effect=self.respond,
            ):
                result = self.invoke(packet(text, name=f"format-{n}"), name=f"run-{n}")
            self.assertEqual(result["roles"]["r1"]["verdict"]["score"], 1)

    def test_aggregation_cannot_erase_contrary_and_bound_failures_are_errors(self):
        def erase(command, **kwargs):
            self.respond(command, **kwargs)
            path = Path(command[command.index("-o") + 1])
            value = read_json(path)
            if value["children"]:
                value["summaries"]["contrary"] = ""
            return self.fixture.completed(command, value)

        with mock.patch(
            "stage1_eval.model_calls._execute_bound_process", side_effect=erase
        ):
            with self.assertRaisesRegex(EvaluationError, "polarity"):
                self.invoke(packet("CONTRARY"))
        oversized = packet("positive")
        oversized["task"] = "too large" * 2000
        with mock.patch("stage1_eval.model_calls._execute_bound_process") as run:
            with self.assertRaisesRegex(EvaluationError, "byte limit"):
                self.invoke(oversized, name="oversized")
        run.assert_not_called()

    def test_oversized_invalid_output_cannot_launch_unbounded_correction(self):
        with mock.patch(
            "stage1_eval.model_calls._execute_bound_process",
            side_effect=lambda command, **kwargs: self.fixture.completed(
                command, {"bad": "x" * 9000}
            ),
        ) as run:
            with self.assertRaisesRegex(EvaluationError, "byte limit"):
                self.invoke(packet("positive"))
        self.assertEqual(run.call_count, 1)
        calls = list((self.root / "run/r1").glob("*.model-call"))
        self.assertEqual(len(calls), 1)
        self.assertNotIn("correction", calls[0].name)

    def test_global_execution_budget_rejects_before_first_model_call(self):
        text = "".join(
            f"{n:03d}:positive" + "x" * 888 + "\n"
            for n in range(2 * MAX_PLAN_UNITS_PER_CRITERION + 8)
        )
        subject = packet(text)
        _, plan = build_coverage_plan(subject, "process", max_unit_bytes=4500)
        self.assertGreater(len(plan["units"]), MAX_PLAN_UNITS_PER_CRITERION)
        with mock.patch("stage1_eval.model_calls._execute_bound_process") as run:
            with self.assertRaisesRegex(
                EvaluationError, "execution budget exceeded before model calls"
            ):
                judge_process_complete(subject, self.root / "over-budget", self.options)
        run.assert_not_called()
        self.assertEqual(list((self.root / "over-budget").rglob("*.model-call")), [])

    def test_all_three_process_criteria_and_empty_input_unknown(self):
        with mock.patch(
            "stage1_eval.model_calls._execute_bound_process", side_effect=self.respond
        ):
            result = judge_process_complete(packet(""), self.root / "all", self.options)
        self.assertEqual(len(result), 3)
        for row in result.values():
            self.assertIsNone(row["roles"]["r1"]["verdict"]["score"])
            self.assertTrue(row["major_error_review_required"])

    def test_native_raw_and_decoded_views_share_a_neutral_document_identity(self):
        subject = packet(
            json.dumps(
                {
                    "item": {
                        "id": "action-one",
                        "aggregated_output": "Synthetic result",
                        "exit_code": 0,
                    }
                }
            )
        )
        subject["process_evidence"]["arbitrary-file"]["origin"] = "subject-native-trace"
        with mock.patch(
            "stage1_eval.model_calls._execute_bound_process", side_effect=self.respond
        ):
            self.invoke(subject)
        spans = [row for data in self.prompts for row in data["spans"].values()]
        self.assertEqual(
            {row["view"] for row in spans}, {"text", "item.aggregated_output"}
        )
        self.assertEqual({row.get("document") for row in spans}, {"d1"})

    def test_unicode_repartition_preserves_every_original_character_and_replays(self):
        text = "研究🚀" * 900
        subject = packet(text)
        with mock.patch(
            "stage1_eval.model_calls._execute_bound_process", side_effect=self.respond
        ):
            result = self.invoke(subject)
        plan = read_json(self.root / "run/plan.json")["plan"]
        self.assertEqual(plan["kind"], "Stage1CriterionCoveragePlan.v2")
        self.assertEqual(plan["span_characters"], 300)
        passages = [
            row["passage"]
            for node in result["roles"]["r1"]["nodes"].values()
            for row in node["value"]["observations"]
        ]
        self.assertEqual(
            "".join(
                row["text"] for row in sorted(passages, key=lambda row: row["start"])
            ),
            text,
        )
        with mock.patch("stage1_eval.model_calls._execute_bound_process") as replay:
            self.assertEqual(self.invoke(subject, replay_only=True), result)
        replay.assert_not_called()


if __name__ == "__main__":
    unittest.main()

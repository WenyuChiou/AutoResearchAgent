"""One-pair reporting remains separate from formal admission and approval."""

import copy
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from test_comparison_report import result
from test_stage1_ab_general_v3 import runs
from stage1_ab import pilot, runner, general_v31
from stage1_ab.__main__ import parser_for_commands
from stage1_ab.general_v31 import _replay_result
from stage1_eval.common import canonical


class PilotReportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.background = self.root / "background.json"
        self.background.write_bytes(b"{}")
        self.lock = {
            "kind": "Stage1ABPublicLockV3",
            "schema_version": "3.1.0",
            "execution_class": "pilot",
            "evaluator_bundle_sha256": "bundle",
            "evaluator_execution_policy": {},
            "plugin_tree_sha256": "tree",
            "background_sha256": runner.sha(b"{}"),
            "passive_observer": {"test": "same"},
            "paired_repeats": runs()[:1],
            "evaluator_runtime": {"model": "gpt-5.6-sol", "reasoning": "high"},
            "runtime": {
                "model_id": "gpt-5.6-sol",
                "reasoning": "high",
                "mode": "default",
                "search_enabled": True,
            },
        }
        self.lock_path = self.root / "lock.json"
        self.results, self.records = [], []
        for arm, run_id in (("baseline", "a-1"), ("treatment", "b-1")):
            root = self.root / arm
            root.mkdir()
            for name in (
                "model-costs.json",
                "judgments.json",
                "subject-sources.json",
                "source-audits.json",
                "native-field-availability.json",
                "judging/result.json",
                "original-fields/result.json",
                "source-audits/r1/result.json",
                "source-audits/r2/result.json",
            ):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"{}")
            (root / "evaluation-input.json").write_bytes(
                canonical({"binding": {"run_id": run_id, "series_id": "series"}})
            )
            path = root / "result.json"
            path.write_bytes(canonical(result()))
            self.results.append(path)
            self.records.append(
                {
                    "run_id": run_id,
                    "condition": arm,
                    "status": "complete",
                    "lock_kind": "Stage1ABPublicLockV3",
                    "series_id": "series",
                    "stage1_receipt": {"synthetic": True},
                }
            )
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in (
            ("bundle_sha_v31", "bundle"),
            ("execution_policy", {}),
            ("_observer_binding", {"test": "same"}),
            ("_require_complete_evaluator", None),
        ):
            self.stack.enter_context(patch.object(pilot, name, return_value=value))
        self.stack.enter_context(patch.object(runner, "tree_sha", return_value="tree"))
        self.capture = self.stack.enter_context(
            patch.object(
                runner,
                "verify_capture",
                side_effect=lambda p, **_: self.records[int(p)],
            )
        )
        self.replay = self.stack.enter_context(
            patch.object(
                pilot,
                "_replay_result",
                side_effect=lambda p, *_a, **_k: json.loads(p.read_bytes()),
            )
        )

    def invoke(self):
        self.lock_path.write_bytes(canonical(self.lock))
        for record in self.records:
            record["lock_sha256"] = runner.sha(self.lock_path.read_bytes())
        return pilot.pilot_report(
            self.lock_path,
            self.background,
            self.results,
            ["0", "1"],
            self.root / "pilot.json",
        )

    def test_unscored_pair_has_machine_eligibility_and_never_grants_freeze(self):
        value = self.invoke()
        self.assertEqual(value["decision"], "unscored-pilot")
        self.assertTrue(value["replay_verified"])
        self.assertFalse(value["freeze_ready"])
        self.assertFalse(value["formal_subject_runs_authorized"])
        self.assertIsNone(value["formal_quality_score"])
        self.assertEqual(len(value["pairs"][0]["criteria"]), 10)
        self.assertTrue(
            all(
                c.kwargs["execution_class"] == "exploratory-pilot"
                for c in self.replay.call_args_list
            )
        )
        self.assertTrue((self.root / "pilot.criteria.csv").is_file())
        self.assertTrue((self.root / "pilot.html").is_file())

    def test_unknowns_require_cause_review_and_keep_bound_artifact_paths(self):
        self.results[0].write_bytes(canonical(result(unknown=("P1V3.IDENTITY",))))
        value = self.invoke()
        self.assertEqual(value["acceptance_status"], "requires-cause-review")
        cause = value["unknown_cause_review"][0]
        self.assertEqual(cause["criterion_id"], "P1V3.IDENTITY")
        self.assertTrue(cause["unknown_reason"])
        self.assertIn("source-audits.json", cause["review_artifacts"])
        self.assertIsNone(value["pairs"][0]["dimensions"]["P1"]["delta"])

    def test_formal_lock_wrong_model_observer_and_pair_count_fail_before_replay(self):
        original = copy.deepcopy(self.lock)
        for change in (
            {"execution_class": "formal"},
            {"passive_observer": {}},
            {"evaluator_runtime": {"model": "gpt-6-astra", "reasoning": "high"}},
            {"runtime": {"model_id": "gpt-6-astra"}},
            {"paired_repeats": runs()},
        ):
            self.lock = {**original, **change}
            with (
                self.subTest(change=change),
                self.assertRaises(runner.ExecutionBlocked),
            ):
                self.invoke()
        self.replay.assert_not_called()

    def test_duplicate_run_wrong_binding_and_missing_artifacts_are_rejected(self):
        old = self.records[1]["run_id"]
        self.records[1]["run_id"] = self.records[0]["run_id"]
        with self.assertRaisesRegex(runner.ExecutionBlocked, "duplicated"):
            self.invoke()
        self.records[1]["run_id"] = old
        input_path = self.results[1].parent / "evaluation-input.json"
        saved = input_path.read_bytes()
        input_path.write_bytes(
            canonical({"binding": {"run_id": "wrong", "series_id": "series"}})
        )
        with self.assertRaisesRegex(runner.ExecutionBlocked, "different capture"):
            self.invoke()
        input_path.write_bytes(saved)
        (self.results[1].parent / "native-field-availability.json").unlink()
        with self.assertRaisesRegex(runner.ExecutionBlocked, "artifact missing"):
            self.invoke()

    def test_replay_class_is_explicit_and_default_formal_cannot_admit_pilot(self):
        saved = result()
        saved["evaluator_identity"].update(
            reasoning="high", evaluator_code_sha256="b" * 64
        )
        saved.update(
            schema_version="3.1.0",
            evaluator_version="3.1.0",
            execution_class="exploratory-pilot",
            evaluation_input_sha256="a" * 64,
        )
        self.results[0].write_bytes(canonical(saved))
        with self.assertRaisesRegex(runner.ExecutionBlocked, "cannot enter formal"):
            _replay_result(
                self.results[0], "0", self.lock_path, self.background, self.lock
            )
        with self.assertRaisesRegex(runner.ExecutionBlocked, "unsupported"):
            _replay_result(
                self.results[0],
                "0",
                self.lock_path,
                self.background,
                self.lock,
                execution_class="repair-diagnostic",
            )

    def test_cli_has_exact_two_run_arity(self):
        args = parser_for_commands().parse_args(
            [
                "pilot-report-v31",
                "lock",
                "background",
                "output",
                "--results",
                "a",
                "b",
                "--capture-dirs",
                "a",
                "b",
            ]
        )
        self.assertEqual(args.command, "pilot-report-v31")
        self.assertEqual(len(args.results), 2)

    def test_pilot_replay_uses_verified_offline_path_and_explicit_execution_class(self):
        saved = result()
        saved["evaluator_identity"].update(
            model="gpt-5.6-sol", reasoning="high", evaluator_code_sha256="b" * 64
        )
        value = {
            "execution_class": "exploratory-pilot",
            "policy": general_v31.execution_policy(),
            "identity": saved["evaluator_identity"],
            "model_config": {
                "codex": "synthetic-codex",
                "evaluator_home": "synthetic-home",
                "model": "gpt-5.6-sol",
                "reasoning": "high",
            },
        }
        saved.update(
            schema_version="3.1.0",
            evaluator_version="3.1.0",
            execution_class="exploratory-pilot",
            evaluation_input_sha256=runner.sha(canonical(value)),
        )
        self.lock.update(
            rubric_sha256=saved["rubric_sha256"], spec_sha256=saved["spec_sha256"]
        )
        self.results[0].write_bytes(canonical(saved))
        (self.results[0].parent / "evaluation-input.json").write_bytes(canonical(value))
        with patch.object(general_v31, "evaluate_v31", return_value=saved) as replay:
            actual = _replay_result(
                self.results[0],
                "0",
                self.lock_path,
                self.background,
                self.lock,
                execution_class="exploratory-pilot",
            )
        self.assertEqual(actual, saved)
        self.assertTrue(replay.call_args.kwargs["replay_only"])
        self.assertTrue(replay.call_args.args[0].resume_verified)
        self.assertFalse(replay.call_args.args[0].portable_diagnostic)
        self.assertEqual(replay.call_args.args[0].execution_class, "exploratory-pilot")


if __name__ == "__main__":
    unittest.main()

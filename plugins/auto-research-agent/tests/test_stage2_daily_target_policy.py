# ruff: noqa: E402 -- load repository CLI and fixture helpers without installation.
"""Daily v3 assessment-target framing remains explicit and opt-in."""

import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parent),
]

from stage1_eval import model_calls
from stage1_eval.common import EvaluationError
from stage2_common import Stage2Error, canonical_hash
import stage2_eval.evaluation_v3 as evaluator
from stage2_eval.evaluation_v3 import CRITERIA_V3
from stage2_live import assessment_target_policy as target_policy
from stage2_live import daily_v3, judge_schemas, judges
from stage2_live.daily_v3 import run_daily_evaluation_v3
import test_stage2_daily_v3 as daily_fixture
from test_stage2_evaluation_v3 import content_assessment, judge


class DailyTargetPolicyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = daily_fixture.DailyV3Tests(
            "test_regular_selection_automatically_scores_and_renders"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.native_adapter = object()
        self.calls = []
        self.prompts = {}
        self.schemas = {}

    def _run(
        self,
        name,
        *,
        binding=None,
        disagree=False,
        technical_role=None,
        resume=False,
        resume_receipt=None,
    ):
        prefix = target_policy.TARGET_PREFIX if binding is not None else ""

        def unit(**kwargs):
            self.assertIs(kwargs["call_adapter"], self.native_adapter)
            label = kwargs["label"]
            self.calls.append(label)
            self.prompts[label] = kwargs["prompt"]
            self.schemas[label] = kwargs["schema"]
            unframed = kwargs["prompt"].removeprefix(prefix)
            payload, _ = json.JSONDecoder().raw_decode(unframed.split("\n", 1)[1])
            view = payload["content_view"]
            if label.endswith("content"):
                value = content_assessment(view)
            else:
                role = payload["role"]
                scores = {
                    key: 1 if disagree and role == "R2" else 2 for key in CRITERIA_V3
                }
                value = judge(
                    view,
                    payload["action_view"],
                    self.fixture.packet,
                    role,
                    scores,
                    technical=role == technical_role,
                )
            kwargs["validate"](value)
            return value, {"native-mock": True}

        with (
            patch("stage2_live.daily_v3.codex_runtime_sha", return_value="a" * 64),
            patch("stage2_live.daily_v3.call_model_v31", new=self.native_adapter),
            patch("stage2_live.daily_v3._run_unit", side_effect=unit),
        ):
            return run_daily_evaluation_v3(
                self.fixture.selection,
                self.fixture.sources,
                codex="synthetic-codex",
                r1_home=self.fixture.homes["r1"],
                r2_home=self.fixture.homes["r2"],
                adj_home=self.fixture.homes["adj"],
                model="test-model",
                reasoning="high",
                execution_policy={},
                output_dir=self.fixture.root / name,
                resume=resume,
                resume_receipt=resume_receipt,
                assessment_target_policy=binding,
            )

    def test_legacy_default_uses_native_adapter_without_target_fields_or_prefix(self):
        result = self._run("legacy")
        request = json.loads(
            (self.fixture.root / "legacy" / "request.json").read_bytes()
        )

        self.assertEqual(request["adapter_mode"], "native")
        self.assertEqual(result["adapter_mode"], "native")
        self.assertNotIn("assessment_target_policy", request)
        self.assertNotIn("assessment_target_policy", result)
        self.assertTrue(
            all(
                not prompt.startswith(target_policy.TARGET_PREFIX)
                for prompt in self.prompts.values()
            )
        )

    def test_opt_in_freezes_exact_policy_and_prefixes_both_call_kinds(self):
        binding = target_policy.target_policy_binding()
        result = self._run("targeted", binding=binding)
        request = json.loads(
            (self.fixture.root / "targeted" / "request.json").read_bytes()
        )
        files = [
            Path(module.__file__)
            for module in (
                evaluator,
                model_calls,
                judges,
                judge_schemas,
                daily_v3,
                target_policy,
            )
        ]
        expected_code_sha = canonical_hash(
            {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
        )
        frozen_policy = judges._execution_policy(
            {"evaluator_bundle_sha256": expected_code_sha}
        )
        expected_config_sha = canonical_hash(
            {
                "model": "test-model",
                "reasoning": "high",
                "runtime": "a" * 64,
                "policy": frozen_policy,
                "assessment_target_policy": binding,
            }
        )

        self.assertEqual(request["assessment_target_policy"], binding)
        self.assertEqual(result["assessment_target_policy"], binding)
        self.assertEqual(request["code_sha256"], expected_code_sha)
        self.assertEqual(request["config_sha256"], expected_config_sha)
        self.assertEqual(
            self.calls, ["r1-content", "r1-judge", "r2-content", "r2-judge"]
        )
        self.assertTrue(
            all(
                prompt.startswith(target_policy.TARGET_PREFIX)
                for prompt in self.prompts.values()
            )
        )
        self.assertEqual(
            len(self.schemas["r1-judge"]["properties"]["criteria"]["items"]["anyOf"]),
            9,
        )

    def test_tampered_policy_is_rejected_before_any_model_unit(self):
        binding = target_policy.target_policy_binding()
        tampered = {**binding, "schema_version": "3.0.0"}

        with patch("stage2_live.daily_v3._run_unit") as run_unit:
            with self.assertRaisesRegex(
                Stage2Error, "assessment-target-policy-binding"
            ):
                run_daily_evaluation_v3(
                    self.fixture.selection,
                    self.fixture.sources,
                    codex="synthetic-codex",
                    r1_home=self.fixture.homes["r1"],
                    r2_home=self.fixture.homes["r2"],
                    adj_home=self.fixture.homes["adj"],
                    model="test-model",
                    reasoning="high",
                    execution_policy={},
                    output_dir=self.fixture.root / "tampered",
                    assessment_target_policy=tampered,
                )

        run_unit.assert_not_called()
        self.assertFalse((self.fixture.root / "tampered").exists())

    def test_resume_rejects_target_policy_change_before_new_calls(self):
        binding = target_policy.target_policy_binding()
        first = self._run("resume", binding=binding)
        call_count = len(self.calls)

        with self.assertRaisesRegex(
            EvaluationError, "daily-v3 resume requires unchanged science and settings"
        ):
            self._run(
                "resume",
                binding=None,
                resume=True,
                resume_receipt=first["replay_receipt"],
            )

        self.assertEqual(len(self.calls), call_count)

    def test_opt_in_preserves_null_comments_and_pending_audit_behavior(self):
        binding = target_policy.target_policy_binding()
        pending = self._run("audit", binding=binding, disagree=True)

        self.assertEqual(pending["status"], "audit-required")
        self.assertIsNone(pending["merged"])
        self.assertEqual(
            pending["judgments"]["R1"]["criteria"][0]["rationale"],
            f"R1 source-bound comment for {CRITERIA_V3[0]}.",
        )

        self.calls.clear()
        failed = self._run("null", binding=binding, technical_role="R1")
        first = failed["judgments"]["R1"]["criteria"][0]
        self.assertEqual(failed["status"], "failed")
        self.assertIsNone(first["score"])
        self.assertEqual(first["rationale"], "The evaluator transport failed.")
        self.assertFalse(failed["formal_ready"])


if __name__ == "__main__":
    unittest.main()

# ruff: noqa: E402 -- load repository CLI and shared synthetic archive helpers.
"""Faithful synthetic archives test replay mechanics, never live research quality."""

import copy
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

from stage1_eval.common import EvaluationError, canonical
from stage1_eval.model_calls import _attempt_files, _request_config
from stage2_common import Stage2Error, canonical_hash
from stage2_eval.evaluation_v3 import CRITERIA_V3
from stage2_live import assessment_target_policy as target
from stage2_live.daily_replay_v3 import verify_daily_v3
from stage2_live.daily_v3 import run_daily_evaluation_v3
import test_stage2_controller as archives
import test_stage2_daily_replay_v3 as legacy_replay
import test_stage2_daily_v3 as daily_fixture
from test_stage2_evaluation_v3 import content_assessment, judge


def _write(path, value):
    path.write_bytes(canonical(value) + b"\n")


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DailyTargetReplayTests(unittest.TestCase):
    def setUp(self):
        self.fixture = daily_fixture.DailyV3Tests(
            "test_regular_selection_automatically_scores_and_renders"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.codex = self.fixture.root / "synthetic-codex.exe"
        self.codex.write_bytes(b"synthetic archive runtime; never executed")
        self.binding = target.target_policy_binding()
        self.prompts = {}
        self.context_policy = None

    def _source_policy(self):
        source = self.fixture.packet["sources"][0]
        evidence = self.fixture.packet["evidence"][0]
        text = (self.fixture.sources / source["path"]).read_text(encoding="utf-8")
        return {
            "kind": "Stage2SourceContextPolicy",
            "schema_version": "1.0.0",
            "max_adjacent_paragraphs": 1,
            "max_characters_per_context": 1000,
            "entries": [
                {
                    "evidence_id": evidence["evidence_id"],
                    "source_id": source["source_id"],
                    "work_id": source["work_id"],
                    "version_id": source["version_id"],
                    "source_sha256": source["sha256"],
                    "quote_start": text.index(evidence["quote"]),
                    "semantic_role": "current-study",
                    "claim_type": "finding",
                    "checked_scope": None,
                    "policy_exceptions": [],
                }
            ],
        }

    def _archive(
        self, *, targeted=True, disagree=False, fail_label=None, context=False
    ):
        self.context_policy = self._source_policy() if context else None

        def synthetic_call(prompt, schema_path, output_dir, label, **options):
            self.prompts[label] = prompt
            unframed = prompt.removeprefix(target.TARGET_PREFIX)
            payload, _ = json.JSONDecoder().raw_decode(unframed.split("\n", 1)[1])
            view = payload["content_view"]
            if label == fail_label:
                raise Stage2Error("synthetic transport interruption")
            if label.endswith("content"):
                value = content_assessment(view)
            else:
                role = payload["role"]
                scores = {
                    key: 1 if disagree and role == "R2" else 2 for key in CRITERIA_V3
                }
                value = judge(
                    view, payload["action_view"], self.fixture.packet, role, scores
                )
            # Model JSON key order is irrelevant to the fixture's scientific content.
            value = json.loads(canonical(value))
            config = _request_config(
                options["codex"],
                options["evaluator_home"],
                options["model"],
                options["reasoning"],
            )
            provenance = archives._write_faithful_model_archive(
                Path(output_dir),
                label,
                prompt,
                json.loads(schema_path.read_bytes()),
                value,
                config,
                options["execution_policy"],
            )
            return value, provenance

        run = self.fixture.root / "targeted-daily"
        with patch("stage2_live.daily_v3.call_model_v31", new=synthetic_call):
            bundle = run_daily_evaluation_v3(
                self.fixture.selection,
                self.fixture.sources,
                codex=str(self.codex),
                r1_home=self.fixture.homes["r1"],
                r2_home=self.fixture.homes["r2"],
                adj_home=self.fixture.homes["adj"],
                model="test-model",
                reasoning="high",
                execution_policy={},
                output_dir=run,
                source_context_policy=self.context_policy,
                assessment_target_policy=self.binding if targeted else None,
            )
        request = json.loads((run / "request.json").read_bytes())
        config = {
            "codex": str(self.codex),
            "runtime_sha256": _digest(self.codex),
            "model": "test-model",
            "reasoning": "high",
            "policy": {},
            "code_sha256": request["code_sha256"],
            "homes": {
                role.upper(): str(home) for role, home in self.fixture.homes.items()
            },
        }
        if targeted:
            config["assessment_target_policy"] = copy.deepcopy(self.binding)
        if context:
            for key in ("source_context_policy_sha256", "source_context_sha256"):
                config[key] = request[key]
        return run, bundle["replay_receipt"], config

    def _verify(self, run, receipt, config, *, binding=True):
        with patch(
            "stage1_eval.model_calls.call_model_v31",
            side_effect=AssertionError("model dispatch forbidden during replay"),
        ) as dispatch:
            verified = verify_daily_v3(
                run,
                receipt,
                selection=self.fixture.selection,
                source_root=self.fixture.sources,
                expected_config=config,
                source_context_policy=self.context_policy,
                assessment_target_policy=self.binding if binding is True else binding,
            )
        dispatch.assert_not_called()
        return verified

    def _rehash_result(self, run, receipt, mutate):
        path = run / "result.json"
        result = json.loads(path.read_bytes())
        mutate(result)
        _write(path, result)
        return {**receipt, "result_sha256": _digest(path)}

    def _rebind_prompt(self, run, label, receipt, prompt):
        """Rehash every affected local claim; the frozen expected prompt still wins."""
        archive = run / f"{label}.model-call"
        (archive / "prompt.txt").write_bytes(prompt.encode("utf-8"))
        request = json.loads((archive / "request.json").read_bytes())
        request["prompt_sha256"] = _digest(archive / "prompt.txt")
        request["request_fingerprint_sha256"] = canonical_hash(
            {
                key: value
                for key, value in request.items()
                if key != "request_fingerprint_sha256"
            }
        )
        _write(archive / "request.json", request)
        attempt_path = _attempt_files(archive, 1)["record"]
        attempt = json.loads(attempt_path.read_bytes())
        attempt["request_fingerprint_sha256"] = request["request_fingerprint_sha256"]
        _write(attempt_path, attempt)
        unit_path = run / f"{label}.unit.json"
        unit = json.loads(unit_path.read_bytes())
        unit["provenance"]["initial"].update(
            prompt_sha256=request["prompt_sha256"],
            request_fingerprint_sha256=request["request_fingerprint_sha256"],
            attempt_record_sha256=_digest(attempt_path),
        )
        _write(unit_path, unit)
        changed = copy.deepcopy(receipt)
        changed["unit_receipts"][label] = _digest(unit_path)
        return self._rehash_result(
            run,
            changed,
            lambda result: result.update(unit_receipts=changed["unit_receipts"]),
        )

    def test_opt_in_replays_faithful_native_archives_read_only(self):
        run, receipt, config = self._archive()
        before = legacy_replay.DailyReplayV3Tests._files(run)
        verified = self._verify(run, receipt, config)
        self.assertTrue(verified["authenticated"])
        self.assertEqual(verified["status"], "complete")
        self.assertEqual(verified["original_model_calls"], 4)
        self.assertEqual(verified["new_model_calls"], 0)
        self.assertFalse(verified["formal_ready"])
        self.assertFalse(verified["improvement_demonstrated"])
        self.assertEqual(legacy_replay.DailyReplayV3Tests._files(run), before)

    def test_target_and_source_context_prompts_match_including_adj(self):
        run, receipt, config = self._archive(disagree=True, context=True)
        verified = self._verify(run, receipt, config)
        self.assertEqual(verified["status"], "audit-required")
        self.assertEqual(verified["original_model_calls"], 6)
        self.assertEqual(
            set(self.prompts),
            {
                f"{role}-{kind}"
                for role in ("r1", "r2", "adj")
                for kind in ("content", "judge")
            },
        )
        for prompt in self.prompts.values():
            self.assertTrue(prompt.startswith(target.TARGET_PREFIX))
            self.assertIn("source_context", prompt)
        self.assertFalse(verified["formal_ready"])
        self.assertFalse(verified["improvement_demonstrated"])

    def test_stale_tampered_or_unsupported_policy_rejected_before_unit_replay(self):
        run, receipt, config = self._archive()
        for key, value in (
            ("module_sha256", "0" * 64),
            ("prompt_sha256", "1" * 64),
            ("schema_version", "3.0.0"),
            ("kind", "forged-policy"),
        ):
            with (
                self.subTest(key=key),
                patch("stage2_live.daily_replay_v3.replay_unit") as replay,
            ):
                with self.assertRaisesRegex(
                    Stage2Error, "assessment-target-policy-binding"
                ):
                    self._verify(
                        run, receipt, config, binding={**self.binding, key: value}
                    )
                replay.assert_not_called()

    def test_opt_in_requires_explicit_matching_config_and_supplied_policy(self):
        run, receipt, config = self._archive()
        missing = {
            key: value
            for key, value in config.items()
            if key != "assessment_target_policy"
        }
        wrong = {
            **config,
            "assessment_target_policy": {**self.binding, "prompt_sha256": "0" * 64},
        }
        for settings, binding, reason in (
            (config, None, "expected-config-shape"),
            (missing, True, "expected-config-shape"),
            (wrong, True, "assessment-target-policy-mismatch"),
            (missing, None, "request-bytes-mismatch"),
        ):
            with (
                self.subTest(reason=reason),
                self.assertRaisesRegex(Stage2Error, reason),
            ):
                self._verify(run, receipt, settings, binding=binding)

    def test_removed_or_changed_prefix_rejected_even_after_rehash(self):
        for label, mutation in (
            ("r1-content", lambda prompt: prompt.removeprefix(target.TARGET_PREFIX)),
            (
                "r1-judge",
                lambda prompt: prompt.replace("Assessment target:", "Wrong target:", 1),
            ),
            ("adj-judge", lambda prompt: prompt.removeprefix(target.TARGET_PREFIX)),
        ):
            with self.subTest(label=label):
                # Each transition gets an independent complete synthetic archive.
                child = DailyTargetReplayTests(
                    "test_opt_in_replays_faithful_native_archives_read_only"
                )
                child.setUp()
                try:
                    run, receipt, config = child._archive(disagree=True)
                    changed = child._rebind_prompt(
                        run, label, receipt, mutation(child.prompts[label])
                    )
                    with self.assertRaisesRegex(EvaluationError, "request fingerprint"):
                        child._verify(run, changed, config)
                finally:
                    child.doCleanups()

    def test_rehash_tamper_rejected(self):
        run, receipt, config = self._archive()
        request_path = run / "request.json"
        request = json.loads(request_path.read_bytes())
        request["assessment_target_policy"]["prompt_sha256"] = "0" * 64
        _write(request_path, request)
        changed = self._rehash_result(
            run,
            receipt,
            lambda result: result.update(request_sha256=canonical_hash(request)),
        )
        with self.assertRaisesRegex(Stage2Error, "request-bytes-mismatch"):
            self._verify(run, changed, config)

    def test_rehashed_result_target_binding_is_recomputed(self):
        run, receipt, config = self._archive()
        changed = self._rehash_result(
            run,
            receipt,
            lambda result: result["assessment_target_policy"].update(
                module_sha256="0" * 64
            ),
        )
        with self.assertRaisesRegex(Stage2Error, "result-recomputation-mismatch"):
            self._verify(run, changed, config)

    def test_external_unit_receipt_still_rejects_mutated_unit(self):
        run, receipt, config = self._archive()
        path = run / "r1-content.unit.json"
        unit = json.loads(path.read_bytes())
        unit["provenance"]["initial"]["prompt_sha256"] = "0" * 64
        _write(path, unit)
        with self.assertRaisesRegex(Stage2Error, "unit-receipt-mismatch"):
            self._verify(run, receipt, config)

    def test_rehashed_unit_receipt_cannot_hide_changed_native_provenance(self):
        run, receipt, config = self._archive()
        path = run / "r1-content.unit.json"
        unit = json.loads(path.read_bytes())
        unit["provenance"]["initial"]["prompt_sha256"] = "0" * 64
        _write(path, unit)
        changed = copy.deepcopy(receipt)
        changed["unit_receipts"]["r1-content"] = _digest(path)
        changed = self._rehash_result(
            run,
            changed,
            lambda result: result.update(unit_receipts=changed["unit_receipts"]),
        )
        with self.assertRaisesRegex(EvaluationError, "provenance changed"):
            self._verify(run, changed, config)

    def test_incomplete_archive_remains_unauthenticated(self):
        run, receipt, config = self._archive(fail_label="r2-judge")
        with patch("stage2_live.daily_replay_v3.replay_unit") as replay:
            verified = self._verify(run, receipt, config)
        self.assertFalse(verified["authenticated"])
        self.assertEqual(verified["status"], "failed-archive-retained")
        self.assertFalse(verified["formal_ready"])
        self.assertFalse(verified["improvement_demonstrated"])
        replay.assert_not_called()

    def test_rehashed_audit_required_cannot_promote_formal_or_complete(self):
        run, receipt, config = self._archive(disagree=True)
        original = (run / "result.json").read_bytes()
        for field, value in (
            ("formal_ready", True),
            ("improvement_demonstrated", True),
            ("status", "complete"),
        ):
            (run / "result.json").write_bytes(original)
            changed = self._rehash_result(
                run, receipt, lambda result: result.update({field: value})
            )
            with self.subTest(field=field), self.assertRaises(Stage2Error):
                self._verify(run, changed, config)

    def test_legacy_archive_replays_without_target_config_or_prefix(self):
        run, receipt, config = self._archive(targeted=False)
        verified = self._verify(run, receipt, config, binding=None)
        self.assertTrue(verified["authenticated"])
        self.assertNotIn("assessment_target_policy", config)
        for prompt in self.prompts.values():
            self.assertFalse(prompt.startswith(target.TARGET_PREFIX))


if __name__ == "__main__":
    unittest.main()

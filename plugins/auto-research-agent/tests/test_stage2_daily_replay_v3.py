# ruff: noqa: E402 -- load repository CLI and fixture helpers without installation.
"""Synthetic capture seams test replay mechanics; they are not native evidence."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parent),
]

from stage1_eval.common import canonical
from stage2_common import Stage2Error, canonical_hash
from stage2_live.__main__ import main as live_main
from stage2_live.daily_replay_v3 import verify_daily_v3
import test_stage2_daily_v3 as daily_fixture


class DailyReplayV3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = daily_fixture.DailyV3Tests(
            "test_regular_selection_automatically_scores_and_renders"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def _archive(self, *, disagree=False, failed=False, context_policy=None):
        self.fixture.run_judges(
            disagree=disagree, fail=failed, source_context_policy=context_policy
        )
        run = self.fixture.root / "judges"
        request = json.loads((run / "request.json").read_bytes())
        request["adapter_mode"] = "native"
        (run / "request.json").write_bytes(canonical(request) + b"\n")
        result_path = run / "result.json"
        result = json.loads(result_path.read_bytes())
        result["adapter_mode"] = "native"
        result["request_sha256"] = canonical_hash(request)
        labels = {
            f"{role.lower()}-{kind}": hashlib.sha256(
                f"synthetic-{role}-{kind}".encode()
            ).hexdigest()
            for role in result.get("judgments", {})
            for kind in ("content", "judge")
        }
        result["unit_receipts"] = labels
        result_path.write_bytes(canonical(result) + b"\n")
        receipt = {
            "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            "unit_receipts": labels,
        }
        config = {
            "codex": "synthetic-codex",
            "runtime_sha256": "a" * 64,
            "model": "test-model",
            "reasoning": "high",
            "homes": {
                role.upper(): str(self.fixture.homes[role].resolve())
                for role in ("r1", "r2", "adj")
            },
            "policy": {},
            "code_sha256": request["code_sha256"],
        }
        if context_policy is not None:
            for key in ("source_context_policy_sha256", "source_context_sha256"):
                config[key] = request[key]
        return run, result, receipt, config

    @staticmethod
    def _files(root):
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    @staticmethod
    def _config(codex, home, model, reasoning):
        return {
            "codex": codex,
            "codex_home": home,
            "model": model,
            "reasoning": reasoning,
            "codex_executable_sha256": "a" * 64,
        }

    def _replay(self, result, *, calls=1):
        def replay(root, label, receipt, **kwargs):
            role = label.split("-", 1)[0].upper()
            value = (
                result["action_views"][role]["content_assessment"]
                if label.endswith("content")
                else result["judgments"][role]
            )
            kwargs["validate"](value)
            return {
                "value": value,
                "provenance": {"synthetic_mechanics": True},
                "actual_call_count": calls,
                "archive_sha256s": {"synthetic-mechanics": receipt},
            }

        return replay

    def _verify(
        self,
        run,
        result,
        receipt,
        config,
        *,
        calls=1,
        selection=None,
        context_policy=None,
    ):
        with (
            patch(
                "stage2_live.daily_replay_v3.codex_runtime_sha", return_value="a" * 64
            ),
            patch(
                "stage2_live.daily_replay_v3._request_config", side_effect=self._config
            ),
            patch(
                "stage2_live.daily_replay_v3.replay_unit",
                side_effect=self._replay(result, calls=calls),
            ),
        ):
            return verify_daily_v3(
                run,
                receipt,
                selection=selection or self.fixture.selection,
                source_root=self.fixture.sources,
                expected_config=config,
                source_context_policy=context_policy,
            )

    def test_opt_in_replay_matches_live_prompts_and_rejects_tampering(self):
        packet = self.fixture.packet
        source, evidence = packet["sources"][0], packet["evidence"][0]
        text = (self.fixture.sources / source["path"]).read_text(encoding="utf-8")
        policy = {
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
        run, result, receipt, config = self._archive(context_policy=policy)
        before = self._files(run)
        original = self._replay(result)

        def check_prompt(root, label, digest, **kwargs):
            self.assertEqual(kwargs["prompt"], self.fixture.prompts[label])
            return original(root, label, digest, **kwargs)

        with patch.object(self, "_replay", return_value=check_prompt):
            self.assertTrue(
                self._verify(run, result, receipt, config, context_policy=policy)[
                    "authenticated"
                ]
            )
        self.assertEqual(self._files(run), before)
        changed = copy.deepcopy(policy)
        changed["entries"][0]["semantic_role"] = "cited-work"
        with self.assertRaises(Stage2Error):
            self._verify(run, result, receipt, config, context_policy=changed)
        for key in ("source_context_policy_sha256", "source_context_sha256"):
            with self.subTest(key=key), self.assertRaises(Stage2Error):
                self._verify(
                    run,
                    result,
                    receipt,
                    {**config, key: "0" * 64},
                    context_policy=policy,
                )
        changed_result = copy.deepcopy(result)
        changed_result["source_context"]["contexts"][0]["semantic_role"] = "cited-work"
        result_path = run / "result.json"
        result_path.write_bytes(canonical(changed_result) + b"\n")
        changed_receipt = {
            **receipt,
            "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        }
        with self.assertRaises(Stage2Error):
            self._verify(run, result, changed_receipt, config, context_policy=policy)

    def test_replays_audit_required_archive_without_writes_or_isolation_claim(self):
        run, result, receipt, config = self._archive(disagree=True)
        before = self._files(run)
        verified = self._verify(run, result, receipt, config)
        self.assertTrue(verified["authenticated"])
        self.assertEqual(verified["status"], "audit-required")
        self.assertEqual(verified["new_model_calls"], 0)
        self.assertEqual(verified["original_model_calls"], 6)
        self.assertFalse(verified["formal_ready"])
        self.assertIn(
            "physical A/B isolation not established", verified["context_separation"]
        )
        self.assertEqual(self._files(run), before)

    def test_rejects_zero_calls_wrong_config_cross_role_and_rehashed_result(self):
        run, result, receipt, config = self._archive()
        with self.assertRaisesRegex(Stage2Error, "call-count"):
            self._verify(run, result, receipt, config, calls=0)

        wrong = {**config, "model": "wrong-model"}
        with self.assertRaisesRegex(Stage2Error, "request-bytes"):
            self._verify(run, result, receipt, wrong)

        wrong_home = copy.deepcopy(config)
        wrong_home["homes"]["ADJ"] = str(self.root / "different-adj-home")
        with self.assertRaisesRegex(Stage2Error, "request-bytes"):
            self._verify(run, result, receipt, wrong_home)

        with (
            patch(
                "stage2_live.daily_replay_v3._rubric",
                return_value={"rubric_id": "rehashed-wrong-rubric"},
            ),
            self.assertRaisesRegex(Stage2Error, "request-bytes"),
        ):
            self._verify(run, result, receipt, config)

        for field, value in (("version_id", "v2"), ("sha256", "0" * 64)):
            changed = copy.deepcopy(self.fixture.selection)
            changed["evaluation_packet"]["sources"][0][field] = value
            with self.subTest(field=field), self.assertRaises(Stage2Error):
                self._verify(run, result, receipt, config, selection=changed)

        crossed = copy.deepcopy(receipt)
        crossed["unit_receipts"]["r1-content"] = crossed["unit_receipts"].pop(
            "r2-content"
        )
        with self.assertRaisesRegex(Stage2Error, "unit-receipt-role"):
            self._verify(run, result, crossed, config)

        saved = json.loads((run / "result.json").read_bytes())
        saved["formal_ready"] = True
        (run / "result.json").write_bytes(canonical(saved) + b"\n")
        rehashed = {
            **receipt,
            "result_sha256": hashlib.sha256(
                (run / "result.json").read_bytes()
            ).hexdigest(),
        }
        with self.assertRaisesRegex(Stage2Error, "result-recomputation"):
            self._verify(run, result, rehashed, config)

    def test_failed_archive_is_readable_but_not_authenticated_complete(self):
        run, result, receipt, config = self._archive(failed=True)
        with (
            patch("stage2_live.daily_replay_v3.replay_unit") as replay,
            patch(
                "stage2_live.daily_replay_v3.codex_runtime_sha", return_value="a" * 64
            ),
            patch(
                "stage2_live.daily_replay_v3._request_config", side_effect=self._config
            ),
        ):
            verified = verify_daily_v3(
                run,
                receipt,
                selection=self.fixture.selection,
                source_root=self.fixture.sources,
                expected_config=config,
            )
        self.assertFalse(verified["authenticated"])
        self.assertEqual(verified["status"], "failed-archive-retained")
        replay.assert_not_called()

    def test_finalized_result_requires_parent_native_replay(self):
        run, _, receipt, _ = self._archive(disagree=True)
        result_path = run / "result.json"
        result = json.loads(result_path.read_bytes())
        result["parent_replay_receipt"] = copy.deepcopy(receipt)
        result["audit_finalization"] = {
            "parent_bundle_sha256": "b" * 64,
            "audit_sha256": "c" * 64,
            "new_model_calls": 0,
        }
        result_path.write_bytes(canonical(result) + b"\n")
        receipt["result_sha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
        verified = verify_daily_v3(
            run,
            receipt,
            selection={},
            source_root=self.root,
            expected_config={},
        )
        self.assertFalse(verified["authenticated"])
        self.assertEqual(verified["status"], "parent-native-replay-required")
        self.assertEqual(verified["new_model_calls"], 0)

    def test_cli_dispatches_read_only_verifier(self):
        paths = {
            name: self.root / f"{name}.json"
            for name in ("receipt", "selection", "config")
        }
        for path in paths.values():
            path.write_text("{}", encoding="utf-8")
        output = self.root / "verified.json"
        with patch(
            "stage2_live.daily_replay_v3.verify_daily_v3",
            return_value={"authenticated": True, "new_model_calls": 0},
        ) as verify:
            code = live_main(
                [
                    "verify-daily-v3",
                    "--run-dir",
                    str(self.root / "run"),
                    "--receipt",
                    str(paths["receipt"]),
                    "--selection",
                    str(paths["selection"]),
                    "--source-root",
                    str(self.root / "sources"),
                    "--config",
                    str(paths["config"]),
                    "--output",
                    str(output),
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.read_text())["new_model_calls"], 0)
        self.assertEqual(verify.call_args.args, (str(self.root / "run"), {}))


if __name__ == "__main__":
    unittest.main()

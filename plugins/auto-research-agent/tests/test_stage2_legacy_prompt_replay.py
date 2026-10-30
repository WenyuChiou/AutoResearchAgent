# ruff: noqa: E402 -- load repository CLI and fixture helpers without installation.
"""Offline native-archive contract for legacy (no source-context) daily-v3 replay.

The only injected seam is the OS process; archives, receipts and prompts are the
real production ones. This proves engineering recovery compatibility only.
"""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parent),
]

from stage1_eval.common import canonical
from stage2_eval.evaluation_v3 import CRITERIA_V3
from stage2_live.daily_replay_v3 import verify_daily_v3
from stage2_live.daily_v3 import run_daily_evaluation_v3
from stage2_live.native import codex_runtime_sha
from stage2_live.replay import replay_unit
import test_stage2_daily_v3 as daily_fixture
from test_stage2_evaluation_v3 import content_assessment, judge

TRANSPORT = "stage1_eval.model_calls._execute_bound_process"
POLICY = {"max_semantic_corrections_per_unit": 1}


def _transcript(value):
    rows = [
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": json.dumps(value)},
        },
        {"type": "turn.completed"},
    ]
    return ("\n".join(json.dumps(row) for row in rows) + "\n").encode()


class LegacyPromptReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fixture = daily_fixture.DailyV3Tests(
            "test_regular_selection_automatically_scores_and_renders"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.codex = self.root / "codex-standalone.bin"
        self.codex.write_bytes(b"synthetic standalone executable")
        self.process_calls = []
        self.native_orders = {}
        self.broken_first_content = False
        self.disagree = False

    def _process(self, command, **kwargs):
        prompt = kwargs["input"].decode("utf-8")
        self.process_calls.append(prompt)
        body = prompt.split("\n", 1)[1]
        correction = "\nThe output below failed" in body
        payload, _ = json.JSONDecoder().raw_decode(body)
        view = payload["content_view"]
        if "role" not in payload:
            value = content_assessment(view)
            if self.broken_first_content and not correction:
                value["findings"] = []
        else:
            scores = {key: 2 for key in CRITERIA_V3}
            if self.disagree and payload["role"] == "R2":
                scores[CRITERIA_V3[0]] = 1
            value = judge(
                view,
                payload["action_view"],
                self.fixture.packet,
                payload["role"],
                scores,
            )
        self.native_orders[len(self.process_calls)] = list(value)
        Path(command[command.index("-o") + 1]).write_bytes(json.dumps(value).encode())
        return SimpleNamespace(returncode=0, stdout=_transcript(value), stderr=b"")

    def _run_native(self):
        fx = self.fixture
        with patch(TRANSPORT, side_effect=self._process):
            bundle = run_daily_evaluation_v3(
                fx.selection,
                fx.sources,
                codex=self.codex,
                r1_home=fx.homes["r1"],
                r2_home=fx.homes["r2"],
                adj_home=fx.homes["adj"],
                model="test-model",
                reasoning="high",
                execution_policy=POLICY,
                output_dir=fx.root / "judges",
            )
        run = fx.root / "judges"
        request = json.loads((run / "request.json").read_bytes())
        receipt = {
            "result_sha256": hashlib.sha256(
                (run / "result.json").read_bytes()
            ).hexdigest(),
            "unit_receipts": dict(bundle["unit_receipts"]),
        }
        config = {
            "codex": str(self.codex),
            "runtime_sha256": codex_runtime_sha(self.codex),
            "model": "test-model",
            "reasoning": "high",
            "homes": {
                role.upper(): str(fx.homes[role]) for role in ("r1", "r2", "adj")
            },
            "policy": POLICY,
            "code_sha256": request["code_sha256"],
        }
        return run, receipt, config

    def _verify(self, run, receipt, config):
        with patch(TRANSPORT, side_effect=AssertionError("replay must not dispatch")):
            return verify_daily_v3(
                run,
                receipt,
                selection=self.fixture.selection,
                source_root=self.fixture.sources,
                expected_config=config,
            )

    @staticmethod
    def _snapshot(run):
        return {
            p.relative_to(run).as_posix(): p.read_bytes()
            for p in run.rglob("*")
            if p.is_file()
        }

    def test_legacy_native_archive_replays_with_original_prompt_bytes(self):
        run, receipt, config = self._run_native()
        calls = len(self.process_calls)
        self.assertEqual(calls, 4)
        before = self._snapshot(run)
        report = self._verify(run, receipt, config)
        self.assertTrue(report["authenticated"])
        self.assertEqual(report["new_model_calls"], 0)
        self.assertEqual(len(self.process_calls), calls)
        self.assertEqual(before, self._snapshot(run))

    def test_semantic_correction_replays_with_original_prompt_bytes(self):
        self.broken_first_content = True
        run, receipt, config = self._run_native()
        self.assertTrue((run / "r1-content-correction.model-call").is_dir())
        report = self._verify(run, receipt, config)
        self.assertTrue(report["authenticated"])
        self.assertEqual(report["new_model_calls"], 0)

    def test_adjudication_replays_original_prompts_and_keeps_audit_pending(self):
        self.disagree = True
        run, receipt, config = self._run_native()
        result = json.loads((run / "result.json").read_bytes())
        self.assertEqual(set(result["judgments"]), {"R1", "R2", "ADJ"})
        self.assertEqual(result["status"], "audit-required")
        self.assertIsNone(result["merged"])
        self.assertFalse(result["formal_ready"])
        self.assertFalse(result["improvement_demonstrated"])
        before = self._snapshot(run)
        calls = len(self.process_calls)
        self.assertEqual(calls, 6)
        report = self._verify(run, receipt, config)
        self.assertTrue(report["authenticated"])
        self.assertEqual(report["new_model_calls"], 0)
        self.assertEqual(len(self.process_calls), calls)
        self.assertEqual(before, self._snapshot(run))

    def test_replay_unit_returns_native_key_order(self):
        run, receipt, config = self._run_native()
        first = self.native_orders[1]
        self.assertNotEqual(first, sorted(first))
        seen = {}

        def spy(*args, **kwargs):
            result = replay_unit(*args, **kwargs)
            seen[args[1]] = result["value"]
            return result

        with patch("stage2_live.daily_replay_v3.replay_unit", side_effect=spy):
            self._verify(run, receipt, config)
        self.assertEqual(list(seen["r1-content"]), first)
        self.assertEqual(list(seen["r1-judge"]), self.native_orders[2])

    def test_receipt_unit_and_archive_tampering_still_rejected(self):
        run, receipt, config = self._run_native()
        bad = copy.deepcopy(receipt)
        bad["unit_receipts"]["r1-content"] = "0" * 64
        with self.assertRaises(ValueError):
            self._verify(run, bad, config)
        unit = run / "r1-judge.unit.json"
        original = unit.read_bytes()
        saved = json.loads(original)
        saved["value"]["evaluator_status"] = "failed"
        unit.write_bytes(canonical(saved) + b"\n")
        rehashed = copy.deepcopy(receipt)
        rehashed["unit_receipts"]["r1-judge"] = hashlib.sha256(
            unit.read_bytes()
        ).hexdigest()
        with self.assertRaises(ValueError):
            self._verify(run, rehashed, config)
        unit.write_bytes(original)
        prompt = run / "r2-content.model-call" / "prompt.txt"
        prompt.write_bytes(prompt.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            self._verify(run, receipt, config)


if __name__ == "__main__":
    unittest.main()

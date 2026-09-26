import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))

from stage1_eval.common import EvaluationError, read_json  # noqa: E402
from stage1_eval.units import run_unit  # noqa: E402


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["value"],
    "properties": {"value": {"type": "integer"}},
}
POLICY = {
    "schema_version": "3.1.0",
    "evaluator_bundle_sha256": "b" * 64,
    "timeout_seconds": 600,
    "max_transient_transport_retries": 1,
}


def transcript(value):
    events = [
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": json.dumps(value)},
        },
        {"type": "turn.completed"},
    ]
    return ("\n".join(json.dumps(event) for event in events) + "\n").encode()


class EvaluatorUnitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.home = self.root / "home"
        self.home.mkdir()
        self.codex = self.root / "codex"
        self.codex.write_bytes(b"fake executable")
        self.schema = self.root / "schema.json"
        self.schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
        self.options = {
            "codex": self.codex,
            "evaluator_home": self.home,
            "model": "test-model",
            "reasoning": "high",
            "execution_policy": POLICY,
        }

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def normalize(value):
        if value["value"] <= 0:
            raise EvaluationError("value must be positive")
        return value

    @staticmethod
    def completed(command, value):
        Path(command[command.index("-o") + 1]).write_bytes(json.dumps(value).encode())
        return SimpleNamespace(returncode=0, stdout=transcript(value), stderr=b"")

    def responder(self, values):
        pending = iter(values)

        def run(command, **_kwargs):
            value = next(pending)
            if isinstance(value, BaseException):
                raise value
            return self.completed(command, value)

        return run

    def invoke(self, *, prompt="unit prompt", replay_only=False, options=None):
        return run_unit(
            prompt,
            self.schema,
            self.output,
            "semantic-unit",
            options or self.options,
            self.normalize,
            replay_only=replay_only,
        )

    def test_invalid_initial_gets_one_correction_then_replays_without_calls(self):
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run",
            side_effect=self.responder([{"value": 0}, {"value": 1}]),
        ) as run:
            value, provenance = self.invoke()
        self.assertEqual(run.call_count, 2)
        self.assertEqual(value, {"value": 1})
        self.assertIsNotNone(provenance["correction"])
        self.assertEqual(provenance["correction_reason"], "value must be positive")
        self.assertTrue((self.output / "semantic-unit.unit.json").is_file())

        with mock.patch("stage1_eval.model_calls.subprocess.run") as replay:
            replayed, replay_provenance = self.invoke(replay_only=True)
        replay.assert_not_called()
        self.assertEqual(replayed, value)
        self.assertEqual(replay_provenance, provenance)

    def test_second_semantic_failure_stops_after_one_correction(self):
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run",
            side_effect=self.responder([{"value": 0}, {"value": -1}]),
        ) as run:
            with self.assertRaisesRegex(EvaluationError, "value must be positive"):
                self.invoke()
        self.assertEqual(run.call_count, 2)
        self.assertTrue((self.output / "semantic-unit.model-call").is_dir())
        self.assertTrue((self.output / "semantic-unit-correction.model-call").is_dir())
        self.assertFalse((self.output / "semantic-unit.unit.json").exists())

    def test_timeout_does_not_start_semantic_correction(self):
        timeout = subprocess.TimeoutExpired(
            ["codex"], 600, output=b"partial", stderr=b"timeout"
        )
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=timeout
        ) as run:
            with self.assertRaisesRegex(EvaluationError, "incomplete or failed"):
                self.invoke()
        self.assertEqual(run.call_count, 1)
        self.assertFalse((self.output / "semantic-unit-correction.model-call").exists())

    def test_saved_unit_value_tamper_is_rejected(self):
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run",
            side_effect=self.responder([{"value": 1}]),
        ):
            self.invoke()
        receipt = self.output / "semantic-unit.unit.json"
        stored = read_json(receipt)
        stored["value"] = {"value": 999}
        receipt.write_text(json.dumps(stored), encoding="utf-8")
        with mock.patch("stage1_eval.model_calls.subprocess.run") as run:
            with self.assertRaisesRegex(
                EvaluationError, "saved normalized result changed"
            ):
                self.invoke(replay_only=True)
        run.assert_not_called()

    def test_input_and_policy_drift_reject_without_execution(self):
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run",
            side_effect=self.responder([{"value": 1}]),
        ):
            self.invoke()
        with mock.patch("stage1_eval.model_calls.subprocess.run") as run:
            with self.assertRaisesRegex(EvaluationError, "request fingerprint"):
                self.invoke(prompt="changed prompt", replay_only=True)
        run.assert_not_called()

        changed = {
            **self.options,
            "execution_policy": {**POLICY, "max_transient_transport_retries": 0},
        }
        with mock.patch("stage1_eval.model_calls.subprocess.run") as run:
            with self.assertRaisesRegex(EvaluationError, "request fingerprint"):
                self.invoke(replay_only=True, options=changed)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

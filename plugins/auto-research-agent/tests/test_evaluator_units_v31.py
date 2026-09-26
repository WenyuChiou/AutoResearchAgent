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
from stage1_eval.model import _api_schema  # noqa: E402
from stage1_eval.model_calls import replay_native_model_call_archive  # noqa: E402
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

    def test_schema_bound_failure_gets_one_correction_and_strict_replay_stays_closed(
        self,
    ):
        schema = {**SCHEMA, "properties": {"value": {"type": "integer", "maximum": 10}}}
        self.schema.write_text(json.dumps(schema), encoding="utf-8")
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run",
            side_effect=self.responder([{"value": 25}, {"value": 3}]),
        ) as run:
            value, provenance = self.invoke()
        self.assertEqual(run.call_count, 2)
        self.assertEqual(value, {"value": 3})
        self.assertIn(
            "local schema validation at value", provenance["correction_reason"]
        )
        correction_prompt = run.call_args_list[1].kwargs["input"].decode()
        self.assertIn("25 is greater than the maximum of 10", correction_prompt)
        archive = self.output / "semantic-unit.model-call"
        record = read_json(archive / "attempt-01.record.json")
        self.assertEqual(record["generation_status"], "completed")
        self.assertEqual(record["semantic_status"], "rejected")
        self.assertEqual(record["status"], "native-completed")
        request = read_json(archive / "request.json")
        with self.assertRaisesRegex(EvaluationError, "local schema validation"):
            replay_native_model_call_archive(
                archive,
                expected_prompt="unit prompt",
                expected_schema=self.schema,
                expected_config=request["config"],
                expected_policy=POLICY,
            )
        with mock.patch("stage1_eval.model_calls.subprocess.run") as replay:
            self.assertEqual(self.invoke(replay_only=True), (value, provenance))
        replay.assert_not_called()
        # The correction route still validates raw bytes against archived hashes.
        (archive / "attempt-01.output.json").write_text(
            '{"value": 2}', encoding="utf-8"
        )
        with mock.patch("stage1_eval.model_calls.subprocess.run") as replay:
            with self.assertRaisesRegex(EvaluationError, "bytes changed"):
                self.invoke(replay_only=True)
        replay.assert_not_called()

    def test_second_schema_failure_cannot_complete_a_unit(self):
        schema = {**SCHEMA, "properties": {"value": {"type": "integer", "maximum": 10}}}
        self.schema.write_text(json.dumps(schema), encoding="utf-8")
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run",
            side_effect=self.responder([{"value": 25}, {"value": 20}]),
        ) as run:
            with self.assertRaisesRegex(EvaluationError, "local schema validation"):
                self.invoke()
        self.assertEqual(run.call_count, 2)
        self.assertFalse((self.output / "semantic-unit.unit.json").exists())

    def test_generation_descriptions_preserve_limits_without_corrupting_field_names(
        self,
    ):
        schema = {
            "type": "object",
            "properties": {
                "maximum": {
                    "type": "array",
                    "maxItems": 4,
                    "description": "Original instruction.",
                    "items": {"type": "integer", "maximum": 10},
                }
            },
        }
        original = json.loads(json.dumps(schema))
        legacy = _api_schema(schema)
        enriched = _api_schema(schema, preserve_constraints=True)
        self.assertEqual(schema, original)
        array = enriched["properties"]["maximum"]
        self.assertNotIn("maxItems", array)
        self.assertIn('"maxItems": 4', array["description"])
        self.assertTrue(array["description"].startswith("Original instruction."))
        self.assertIn('"maximum": 10', array["items"]["description"])
        self.assertEqual(
            legacy["properties"]["maximum"]["description"], "Original instruction."
        )

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

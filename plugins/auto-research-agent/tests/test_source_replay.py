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

from stage1_eval.common import EvaluationError, canonical, sha  # noqa: E402
from stage1_eval.source_replay import EVENT_KIND, REPORT_SCHEMA, replay_source_bytes  # noqa: E402


class SourceReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.result = self.root / "source result.json"
        self.source = {
            "receipt_sha256": "a" * 64,
            "source_version": "sha256:" + "b" * 64,
        }
        self.result.write_bytes(canonical(self.source))
        self.journal = self.root / "validation/replay-events.jsonl"
        self.prefix = [sys.executable, "-m", "research_hub"]
        self.report = {
            "schema_version": REPORT_SCHEMA,
            "valid": True,
            "errors": [],
            "result_path": str(self.result.resolve()),
            **self.source,
        }

    def invoke(self, result=None):
        with mock.patch(
            "stage1_eval.source_replay.subprocess.run",
            return_value=result or self.completed(),
        ) as run:
            value = replay_source_bytes(self.result, self.prefix, self.journal)
        return value, run

    def completed(self, *, value=None, code=0, stdout=None):
        return SimpleNamespace(
            returncode=code,
            stdout=stdout
            if stdout is not None
            else canonical(self.report if value is None else value),
            stderr=b"diagnostic\xff",
        )

    def events(self):
        return [json.loads(line) for line in self.journal.read_bytes().splitlines()]

    def test_documented_command_and_exact_raw_events_without_deep_import(self):
        with mock.patch.dict(sys.modules, {"research_hub.source_fetch": None}):
            value, run = self.invoke()
        self.assertEqual(value, self.report)
        args, kwargs = run.call_args
        self.assertEqual(
            args[0], self.prefix + ["source", "validate", str(self.result), "--json"]
        )
        self.assertEqual(
            kwargs,
            {"capture_output": True, "timeout": 120, "check": False, "shell": False},
        )
        registered, finished = self.events()
        self.assertEqual(registered["attempt_id"], finished["attempt_id"])
        self.assertEqual(registered["result_sha256"], sha(self.result.read_bytes()))
        self.assertEqual(bytes.fromhex(finished["stdout_hex"]), canonical(self.report))
        self.assertEqual(bytes.fromhex(finished["stderr_hex"]), b"diagnostic\xff")
        self.assertFalse(finished["counts_as_source_acquisition"])

    def test_successful_rechecks_append_without_overwriting_prior_observations(self):
        self.invoke()
        prior = self.journal.read_bytes()
        self.invoke()
        self.assertTrue(self.journal.read_bytes().startswith(prior))
        self.assertEqual(len(self.events()), 4)
        self.assertNotEqual(
            self.events()[0]["attempt_id"], self.events()[2]["attempt_id"]
        )

    def test_schema_source_version_receipt_path_and_false_valid_rejected(self):
        changes = (
            {"schema_version": "unknown"},
            {"valid": False},
            {"valid": 1},
            {"errors": ["tampered original extraction"]},
            {"receipt_sha256": "c" * 64},
            {"source_version": "sha256:" + "d" * 64},
            {"result_path": str(self.root / "other.json")},
        )
        for number, change in enumerate(changes):
            self.journal = self.root / f"case-{number}.jsonl"
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(EvaluationError, "pinned CLI replay"),
            ):
                self.invoke(self.completed(value={**self.report, **change}))
            self.assertFalse(self.events()[-1]["validation_passed"])

    def test_malformed_stdout_and_nonzero_exit_preserve_failure_and_do_not_retry(self):
        for number, result in enumerate(
            (self.completed(stdout=b"bad JSON"), self.completed(code=1))
        ):
            self.journal = self.root / f"bad-{number}.jsonl"
            with self.assertRaises(EvaluationError):
                self.invoke(result)
            prior = self.journal.read_bytes()
            with (
                mock.patch("stage1_eval.source_replay.subprocess.run") as run,
                self.assertRaisesRegex(
                    EvaluationError, "failed source replay is preserved"
                ),
            ):
                replay_source_bytes(self.result, self.prefix, self.journal)
            run.assert_not_called()
            self.assertEqual(self.journal.read_bytes(), prior)

    def test_timeout_and_spawn_failure_keep_partial_output_and_returncode_unknown(self):
        for number, error in enumerate(
            (
                subprocess.TimeoutExpired(
                    "hub", 120, output=b"partial", stderr=b"timeout"
                ),
                OSError("missing executable"),
            )
        ):
            self.journal = self.root / f"launch-{number}.jsonl"
            with (
                mock.patch(
                    "stage1_eval.source_replay.subprocess.run", side_effect=error
                ) as run,
                self.assertRaises(EvaluationError),
            ):
                replay_source_bytes(self.result, self.prefix, self.journal)
            self.assertEqual(run.call_count, 1)
            event = self.events()[-1]
            self.assertIsNone(event["returncode"])
            self.assertEqual(
                event["status"], "timeout" if number == 0 else "spawn-error"
            )
            if number == 0:
                self.assertEqual(bytes.fromhex(event["stdout_hex"]), b"partial")

    def test_partial_or_malformed_journal_blocks_launch(self):
        self.journal.parent.mkdir()
        for raw in (
            b"",
            b"broken",
            canonical({"kind": "unknown"}) + b"\n",
            canonical({"kind": EVENT_KIND, "event": "registered"}) + b"\n",
        ):
            self.journal.write_bytes(raw)
            with (
                mock.patch("stage1_eval.source_replay.subprocess.run") as run,
                self.assertRaises(EvaluationError),
            ):
                replay_source_bytes(self.result, self.prefix, self.journal)
            run.assert_not_called()
            self.assertEqual(self.journal.read_bytes(), raw)

    def test_invalid_command_prefix_fails_before_journal_or_launch(self):
        for prefix in ([], "hub", [""], [1]):
            with (
                mock.patch("stage1_eval.source_replay.subprocess.run") as run,
                self.assertRaises(EvaluationError),
            ):
                replay_source_bytes(self.result, prefix, self.journal)
            run.assert_not_called()
        self.assertFalse(self.journal.exists())

    def test_rehashed_tamper_rejected_on_saved_journal_or_result(self):
        self.invoke()
        original = self.journal.read_bytes()
        for key, value in (
            ("command", ["other"]),
            ("stdout_sha256", "0" * 64),
            ("stdout_hex", "not hex"),
        ):
            events = [json.loads(line) for line in original.splitlines()]
            events[-1][key] = value
            self.journal.write_bytes(
                b"".join(canonical(event) + b"\n" for event in events)
            )
            with (
                self.subTest(key=key),
                mock.patch("stage1_eval.source_replay.subprocess.run") as run,
                self.assertRaisesRegex(EvaluationError, "journal binding changed"),
            ):
                replay_source_bytes(self.result, self.prefix, self.journal)
            run.assert_not_called()
        self.journal.write_bytes(original)
        self.result.write_bytes(
            canonical({**self.source, "source_version": "different"})
        )
        with (
            mock.patch("stage1_eval.source_replay.subprocess.run") as run,
            self.assertRaisesRegex(EvaluationError, "journal binding changed"),
        ):
            replay_source_bytes(self.result, self.prefix, self.journal)
        run.assert_not_called()

    def test_invalid_source_or_change_during_execution_keeps_terminal_failure(self):
        for number, raw in enumerate(
            (
                b"bad JSON",
                canonical({}),
                canonical({"receipt_sha256": "bad", "source_version": ""}),
            )
        ):
            self.result.write_bytes(raw)
            self.journal = self.root / f"input-{number}.jsonl"
            with self.assertRaises(EvaluationError):
                self.invoke()
            self.assertEqual(len(self.events()), 2)
            self.assertFalse(self.events()[-1]["validation_passed"])
        self.result.write_bytes(canonical(self.source))
        self.journal = self.root / "mutation.jsonl"

        def mutate(*args, **kwargs):
            self.result.write_bytes(b"changed")
            return self.completed()

        with (
            mock.patch("stage1_eval.source_replay.subprocess.run", side_effect=mutate),
            self.assertRaises(EvaluationError),
        ):
            replay_source_bytes(self.result, self.prefix, self.journal)
        self.assertFalse(self.events()[-1]["validation_passed"])


if __name__ == "__main__":
    unittest.main()

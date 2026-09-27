"""Real pipe drainage and replay checks for the common passive observer."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage1_ab import observer, runner, sequence  # noqa: E402
from stage1_ab.capture_history import capture_saved_history  # noqa: E402
from stage1_eval.common import EvaluationError, canonical, read_json, sha  # noqa: E402
from stage1_eval.formal import observe_capture_v31  # noqa: E402
from test_capture_v31 import _write_capture  # noqa: E402
import test_stage1_ab_execution as execution_fixture  # noqa: E402


class PassiveObserverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.output = self.root / "observer"
        self.event = (
            canonical(
                {
                    "type": "item.completed",
                    "item": {"id": "x", "type": "command_execution"},
                }
            )
            + b"\n"
        )

    def run_subject(self):
        script = (
            "import sys; sys.stdin.buffer.read(); "
            "sys.stderr.buffer.write(b'e'*150000); sys.stderr.buffer.flush(); "
            f"sys.stdout.buffer.write({self.event!r}); sys.stdout.buffer.flush()"
        )
        return observer.run_observed(
            [sys.executable, "-c", script],
            input=b"synthetic prompt",
            env=dict(os.environ),
            cwd=self.workspace,
            output=self.output,
        )

    def test_actual_process_preserves_both_pipes_and_event_bound_snapshot_sequence(
        self,
    ):
        (self.workspace / "notes.txt").write_bytes(b"source observation")
        result = self.run_subject()
        self.assertEqual(result.stdout, self.event)
        self.assertEqual(result.stderr, b"e" * 150000)
        self.assertEqual(result.returncode, 0)
        value = observer.verify_observation(
            self.output, result.stdout, observer.binding()
        )
        self.assertEqual(
            [r["trigger"] for r in value["observations"]],
            ["before-start", "item.completed", "after-exit"],
        )
        self.assertEqual(len(list((self.output / "blobs").iterdir())), 1)
        self.assertTrue(all(r["observed_at"] for r in value["observations"]))
        self.assertNotIn("duration", value["observations"][1])

    def test_deleted_and_overwritten_versions_survive_as_process_evidence(self):
        capture = self.root / "capture"
        capture.mkdir()
        record = _write_capture(capture)
        record["condition"] = "baseline"
        record["attempts"][0]["ended_at"] = "2026-09-27T01:00:00Z"
        self.output = capture / "attempt-01.observer"
        notes = self.workspace / "notes.txt"
        notes.write_bytes(b"original reason")
        original_snapshot = observer._snapshot
        count = 0

        def sampled(workspace, root):
            nonlocal count
            count += 1
            if count == 2:
                notes.write_bytes(b"revised reason")
            elif count == 3:
                notes.unlink()
            return original_snapshot(workspace, root)

        with patch.object(observer, "_snapshot", side_effect=sampled):
            result = self.run_subject()
        (capture / "attempt-01.jsonl").write_bytes(result.stdout)
        (capture / "attempt-01.lock.json").write_bytes(
            canonical({"passive_observer": observer.binding()})
        )
        files = record["attempts"][0]["files"]
        for path in capture.rglob("*"):
            if path.is_file() and path.name != "run.json":
                files[path.relative_to(capture).as_posix()] = sha(path.read_bytes())
        (capture / "run.json").write_bytes(canonical(record))
        with patch(
            "stage1_ab.capture_history.runner.verify_capture", return_value=record
        ):
            subject, returned = observe_capture_v31(capture, portable=True)
            record["condition"] = "treatment"
            other = capture_saved_history(capture, verify_runtime=False)
        self.assertEqual(returned["condition"], "baseline")
        texts = {r["text"] for r in subject["evidence"].values()}
        self.assertTrue({"original reason", "revised reason"}.issubset(texts))
        self.assertEqual(subject["evidence"], other[0]["evidence"])
        self.assertEqual(subject["field_availability"], other[2])
        self.assertEqual(
            subject["capture_history"]["passive_observations"][0]["observations"][-1][
                "files"
            ],
            {},
        )
        fields = subject["field_availability"]["events"][0]["values"]
        for key in ("native_duration_ms", "http_status", "backend", "result_count"):
            self.assertIsNone(fields[key])

    def test_replay_rejects_rehashed_missing_events_and_changed_blobs(self):
        (self.workspace / "notes.txt").write_bytes(b"original")
        result = self.run_subject()
        manifest = self.output / "manifest.json"
        original = manifest.read_bytes()
        changed = read_json(manifest)
        changed["observations"].pop(1)
        manifest.write_bytes(canonical(changed))
        with self.assertRaisesRegex(EvaluationError, "events incomplete"):
            observer.verify_observation(self.output, result.stdout, observer.binding())
        manifest.write_bytes(original)
        next((self.output / "blobs").iterdir()).write_bytes(b"changed")
        with self.assertRaisesRegex(EvaluationError, "blob changed"):
            observer.verify_observation(self.output, result.stdout, observer.binding())

    def test_sampling_errors_cannot_become_complete_observation(self):
        with patch.object(
            observer,
            "_snapshot",
            return_value={
                "files": {},
                "errors": [
                    {"path": "notes", "error": "file changed during observation"}
                ],
            },
        ):
            result = self.run_subject()
        with self.assertRaisesRegex(EvaluationError, "sampling failed"):
            observer.verify_observation(self.output, result.stdout, observer.binding())

    def test_observer_cannot_write_inside_subject_workspace(self):
        self.output = self.workspace / "leaked-evaluator-records"
        with self.assertRaisesRegex(EvaluationError, "outside subject workspace"):
            self.run_subject()
        self.assertFalse(self.output.exists())

    def test_capture_routes_both_conditions_through_frozen_observer(self):
        fixture = execution_fixture.Stage1ABExecutionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        lock = read_json(fixture.lock)
        lock["passive_observer"] = observer.binding()
        fixture.lock.write_bytes(canonical(lock))
        preflight = read_json(fixture.preflight)
        preflight["lock_sha256"] = sha(fixture.lock.read_bytes())
        fixture.preflight.write_bytes(canonical(preflight))
        sequence.create(lock, fixture.lock, fixture.preflight, sha)
        native = observer.run_observed
        commands = []

        def synthetic_subject(command, **kwargs):
            commands.append(command)
            self.assertEqual(command[command.index("-m") + 1], "gpt-5.6-sol")
            self.assertIn('model_reasoning_effort="high"', command)
            final_path = command[command.index("-o") + 1]
            raw = execution_fixture.event_bytes(search="synthetic search")
            script = (
                "import sys; from pathlib import Path; sys.stdin.buffer.read(); "
                f"Path({final_path!r}).write_bytes(b'synthetic final'); "
                f"sys.stdout.buffer.write({raw!r})"
            )
            return native([sys.executable, "-c", script], **kwargs)

        with (
            patch.object(
                runner,
                "probe_profile",
                return_value={"codex_version": "codex-cli 0.153.0"},
            ),
            patch.object(runner, "_runtime_pin"),
            patch.object(runner, "_assert_host_isolation"),
            patch.object(observer, "run_observed", side_effect=synthetic_subject),
        ):
            for arm in ("baseline", "treatment"):
                output = fixture.root / arm
                result = runner.capture(
                    "codex",
                    fixture.lock,
                    arm,
                    1,
                    fixture.profile,
                    fixture.workspace,
                    fixture.prompt,
                    output,
                    fixture.root / "private",
                    fixture.preflight,
                )
                # This legacy fixture requires a B ledger, deliberately absent.
                self.assertEqual(
                    result["status"], "complete" if arm == "baseline" else "incomplete"
                )
                self.assertIn(
                    "attempt-01.observer/manifest.json", result["attempts"][0]["files"]
                )
                saved = read_json(output / "attempt-01.observer/manifest.json")
                self.assertEqual(saved["binding"], lock["passive_observer"])
        self.assertEqual(len(commands), 2)


if __name__ == "__main__":
    unittest.main()

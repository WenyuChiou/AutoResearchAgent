"""All saved versions and literal native-field availability at verified boundary."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage1_ab.capture_history import capture_saved_history, main  # noqa: E402
from stage1_eval.common import EvaluationError, canonical, read_json, sha  # noqa: E402
from test_capture_v31 import _write_capture  # noqa: E402


class CaptureHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.record = _write_capture(self.root, 3)
        self.record["condition"] = "baseline"
        self.tail = "CONTRARY: reason for excluding the candidate."
        self.snapshot(
            1,
            {
                "report.md": b"earlier report",
                "notes.txt": ("padding\n" * 40_000 + self.tail).encode(),
            },
        )
        self.snapshot(2, {"report.md": b"updated report"})
        self.snapshot(3, {"report.md": b"updated report", "opaque.bin": b"\xff\x00"})
        final = self.root / "attempt-03.final.txt"
        final.write_bytes(b"Read report.md for the delivered research summary.")
        self.record["attempts"][-1]["files"][final.name] = sha(final.read_bytes())
        for number, attempt in enumerate(self.record["attempts"], 1):
            attempt["ended_at"] = f"2026-09-27T01:0{number}:00Z"
        event = {
            "type": "item.completed",
            "item": {
                "id": "failure-1",
                "type": "command_execution",
                "command": "synthetic public search",
                "exit_code": 1,
                "status": "failed",
                "arguments": {"query": "synthetic scope"},
                "aggregated_output": "HTTP 429",
            },
        }
        transcript = self.root / "attempt-01.jsonl"
        transcript.write_bytes(canonical(event) + b"\n")
        self.record["attempts"][0]["files"][transcript.name] = sha(
            transcript.read_bytes()
        )

    def snapshot(self, number, files):
        for name, raw in files.items():
            path = self.root / "workspace" / f"{number:02d}" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            self.record["attempts"][number - 1]["files"][
                path.relative_to(self.root).as_posix()
            ] = sha(raw)

    def capture(self):
        with patch(
            "stage1_ab.capture_history.runner.verify_capture", return_value=self.record
        ):
            return capture_saved_history(self.root, verify_runtime=False)

    def test_saved_history_keeps_deleted_modified_and_unchanged_versions_without_truncation(
        self,
    ):
        subject, history, _ = self.capture()
        text = "\n".join(row["text"] for row in subject["evidence"].values())
        self.assertIn(self.tail, text)
        self.assertEqual(
            subject["evidence"]["attempt-01-workspace-1"]["text"],
            "padding\n" * 40_000 + self.tail,
        )
        self.assertIn(
            "notes.txt", history["snapshots"][1]["deleted_since_previous_snapshot"]
        )
        self.assertEqual(history["snapshots"][1]["files"][0]["change"], "modified")
        final_files = {r["path"]: r for r in history["snapshots"][2]["files"]}
        self.assertEqual(final_files["report.md"]["change"], "unchanged")
        self.assertEqual(final_files["opaque.bin"]["text_status"], "non-utf8")
        self.assertIsNone(final_files["opaque.bin"]["evidence_id"])
        delivered = [
            r
            for r in subject["evidence"].values()
            if r["origin"] == "subject-delivered-artifact"
        ]
        self.assertEqual([r["text"] for r in delivered], ["updated report"])
        self.assertIn("unavailable", history["between_snapshot_history"])

    def test_raw_failure_fields_stay_exact_and_missing_native_fields_remain_null(self):
        subject, history, availability = self.capture()
        event = availability["events"][0]
        self.assertEqual(event["values"]["action_id"], "failure-1")
        self.assertEqual(event["values"]["exit_code"], 1)
        self.assertEqual(event["values"]["aggregated_output"], "HTTP 429")
        self.assertEqual(event["values"]["arguments"], {"query": "synthetic scope"})
        for field in (
            "backend",
            "result_count",
            "native_timestamp",
            "stdout",
            "stderr",
        ):
            self.assertIsNone(event["values"][field])
            self.assertIsNone(event["field_paths"][field])
        self.assertEqual(history["snapshots"][0]["observed_at"], "2026-09-27T01:01:00Z")
        self.assertIn(
            "not file-write or tool time",
            history["snapshots"][0]["timestamp_semantics"],
        )
        self.assertIn("exit_code", subject["evidence"][event["evidence_id"]]["text"])

    def test_same_passive_policy_for_both_conditions_and_no_research_calls(self):
        first = self.capture()
        self.record["condition"] = "treatment"
        with patch("subprocess.run", side_effect=AssertionError("no new tool calls")):
            second = self.capture()
        self.assertEqual(first, second)

    def test_missing_modified_extra_and_wrong_attempt_files_fail_closed(self):
        path = self.root / "workspace/01/report.md"
        original = path.read_bytes()
        for mutation in ("missing", "modified", "extra", "wrong-attempt", "escape"):
            with self.subTest(mutation=mutation):
                if mutation == "missing":
                    path.unlink()
                elif mutation == "modified":
                    path.write_bytes(b"different")
                elif mutation == "extra":
                    (path.parent / "extra.txt").write_bytes(b"unrecorded")
                elif mutation == "wrong-attempt":
                    self.record["attempts"][0]["files"]["workspace/02/foreign.txt"] = (
                        "a" * 64
                    )
                else:
                    self.record["attempts"][0]["files"][
                        "workspace/01/../escape.txt"
                    ] = "a" * 64
                with self.assertRaises(EvaluationError):
                    self.capture()
                path.write_bytes(original)
                (path.parent / "extra.txt").unlink(missing_ok=True)
                self.record["attempts"][0]["files"].pop(
                    "workspace/02/foreign.txt", None
                )
                self.record["attempts"][0]["files"].pop(
                    "workspace/01/../escape.txt", None
                )

    def test_unsafe_path_rejected_before_shared_verifier_reads_files(self):
        self.record["attempts"][0]["files"]["../outside.txt"] = "a" * 64
        (self.root / "run.json").write_bytes(canonical(self.record))
        with patch("stage1_ab.capture_history.runner.verify_capture") as verify:
            with self.assertRaisesRegex(EvaluationError, "unsafe relative path"):
                capture_saved_history(self.root)
        verify.assert_not_called()

    def test_empty_snapshot_and_native_timestamp_are_observed_without_inference(self):
        record = _write_capture(self.root, 1)
        event = {
            "type": "item.completed",
            "timestamp": "provided-native-value",
            "item": {"id": "x", "type": "reasoning"},
        }
        transcript = self.root / "attempt-01.jsonl"
        transcript.write_bytes(canonical(event) + b"\n")
        record["attempts"][0]["files"][transcript.name] = sha(transcript.read_bytes())
        # Empty workspaces may be absent, but unrecorded existing files are rejected.
        with tempfile.TemporaryDirectory() as empty:
            target = Path(empty)
            for name in ("run.json", "attempt-01.jsonl", "attempt-01.final.txt"):
                (target / name).write_bytes((self.root / name).read_bytes())
            with patch(
                "stage1_ab.capture_history.runner.verify_capture", return_value=record
            ):
                _, history, availability = capture_saved_history(
                    target, verify_runtime=False
                )
        self.assertEqual(history["snapshots"][0]["files"], [])
        self.assertIsNone(history["snapshots"][0]["observed_at"])
        self.assertEqual(
            availability["events"][0]["values"]["native_timestamp"],
            "provided-native-value",
        )

    def test_cli_requires_runtime_validation_and_preserves_previous_output(self):
        output = self.root / "converted"
        with patch(
            "stage1_ab.capture_history.runner.verify_capture", return_value=self.record
        ) as verify:
            self.assertEqual(main([str(self.root), str(output)]), 0)
            saved = (output / "subject.json").read_bytes()
            self.assertEqual(main([str(self.root), str(output)]), 1)
        self.assertEqual((output / "subject.json").read_bytes(), saved)
        self.assertTrue(
            all(
                call.kwargs == {"verify_runtime": True}
                for call in verify.call_args_list
            )
        )
        self.assertEqual(
            read_json(output / "workspace-history.json")["kind"],
            "Stage1SavedCaptureHistory.v1",
        )
        (self.root / "run.json").write_bytes(b"[]")
        rejected = self.root / "bad-record-output"
        self.assertEqual(main([str(self.root), str(rejected)]), 1)
        self.assertFalse(rejected.exists())


if __name__ == "__main__":
    unittest.main()

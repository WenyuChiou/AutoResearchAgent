"""Lossless v3.1 capture adapter tests at the verified-run boundary."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from stage1_ab.capture_v31 import capture_subject  # noqa: E402
from stage1_eval.common import EvaluationError, sha  # noqa: E402


def _write_capture(root, count=1):
    attempts = []
    for number in range(1, count + 1):
        transcript = root / f"attempt-{number:02d}.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": f"event-{number}",
                        "type": "reasoning",
                        "text": f"attempt {number}",
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        final_path = root / f"attempt-{number:02d}.final.txt"
        final_path.write_text(f"final answer {number}", encoding="utf-8")
        attempts.append(
            {
                "files": {
                    transcript.name: sha(transcript.read_bytes()),
                    final_path.name: sha(final_path.read_bytes()),
                },
                "status": "complete",
            }
        )
    (root / "run.json").write_text("{}\n", encoding="utf-8")
    return {"status": "complete", "attempts": attempts}


class CaptureV31Tests(unittest.TestCase):
    def test_absent_empty_workspace_is_valid_and_all_attempts_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = _write_capture(root, 2)
            with patch(
                "stage1_ab.capture_v31.runner.verify_capture", return_value=record
            ) as verify:
                subject, returned = capture_subject(root, verify_runtime=False)
        verify.assert_called_once_with(root.resolve(), verify_runtime=False)
        self.assertIs(returned, record)
        self.assertIn("attempt-01-trace-1", subject["evidence"])
        self.assertIn("attempt-02-trace-1", subject["evidence"])
        inventory = json.loads(subject["evidence"]["attempt-inventory"]["text"])
        self.assertTrue(inventory["empty_workspace"])
        self.assertEqual([row["attempt"] for row in inventory["attempts"]], [1, 2])
        self.assertEqual(subject["evidence"]["workspace-inventory"]["text"], "[]")

    def test_tamper_in_any_attempt_transcript_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = _write_capture(root, 2)
            (root / "attempt-01.jsonl").write_text("{}\n", encoding="utf-8")
            with (
                patch(
                    "stage1_ab.capture_v31.runner.verify_capture", return_value=record
                ),
                self.assertRaisesRegex(
                    EvaluationError, "attempt transcript binding changed"
                ),
            ):
                capture_subject(root)


if __name__ == "__main__":
    unittest.main()

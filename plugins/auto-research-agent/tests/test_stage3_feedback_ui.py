"""Run the synthetic Stage 3 feedback UI contract without network or models."""

from pathlib import Path
import re
import shutil
import subprocess
import unittest


class Stage3FeedbackUITests(unittest.TestCase):
    def test_comment_revision_and_receipt_recovery_contract(self):
        node = shutil.which("node")
        self.assertIsNotNone(
            node, "Node is required; the feedback UI contract did not run"
        )
        root = Path(__file__).resolve().parents[3]
        ui = root / "harness-ui"
        contracts = (
            ui / "test_v9_stage3_feedback.cjs",
            ui / "test_v9_stage3_bridge.cjs",
        )
        for required in (
            *contracts,
            ui / "v9-stage3-feedback.js",
            ui / "v9-stage3-feedback.css",
            ui / "run_v9.py",
        ):
            self.assertTrue(
                required.is_file(), f"Required UI fixture is missing: {required}"
            )
        result = subprocess.run(
            [
                node,
                "--test",
                "--test-reporter=tap",
                *(str(contract) for contract in contracts),
            ],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            timeout=25,
            check=False,
            shell=False,
        )
        print(result.stdout, end="")
        self.assertEqual(result.returncode, 0, result.stdout)
        counts = {
            key: int(value)
            for key, value in re.findall(
                r"^# (tests|pass|fail|cancelled|skipped|todo) (\d+)\r?$",
                result.stdout,
                re.MULTILINE,
            )
        }
        self.assertGreater(counts.get("tests", 0), 0, result.stdout)
        self.assertEqual(counts.get("pass"), counts["tests"], result.stdout)
        for key in ("fail", "cancelled", "skipped", "todo"):
            self.assertEqual(counts.get(key), 0, result.stdout)


if __name__ == "__main__":
    unittest.main()

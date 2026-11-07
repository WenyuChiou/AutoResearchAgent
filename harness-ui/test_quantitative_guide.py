"""Run quantitative display contracts without research or a network host."""

from pathlib import Path
import shutil
import subprocess
import unittest


class QuantitativeGuideTests(unittest.TestCase):
    def run_contract(self, filename):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for quantitative display checks")
        result = subprocess.run(
            [node, "--test", str(Path(__file__).with_name(filename))],
            capture_output=True,
            text=True,
            encoding="utf8",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_source_and_version_contract(self):
        self.run_contract("test_v9_quantitative_contract.cjs")

    def test_late_reads_and_original_plan_survival(self):
        self.run_contract("test_v9_quantitative_guide.cjs")

    def test_numeric_view_and_inert_text(self):
        self.run_contract("test_v9_quantitative_view.cjs")


if __name__ == "__main__":
    unittest.main()

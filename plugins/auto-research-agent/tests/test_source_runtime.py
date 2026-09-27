"""A parser installation failure must stop the evaluator before model work."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage1_eval.common import EvaluationError  # noqa: E402
from stage1_eval.source_runtime import source_runtime_preflight  # noqa: E402


class SourceRuntimeTests(unittest.TestCase):
    def test_real_pdf_text_probe_and_parser_bytes_are_repeatable(self):
        first = source_runtime_preflight()
        self.assertEqual(first, source_runtime_preflight())
        self.assertEqual(first["probe_pages"], 1)
        self.assertEqual(set(first["modules"]), {"pdfplumber", "pdfminer"})
        self.assertTrue(
            all(
                len(row["python_tree_sha256"]) == 64
                for row in first["modules"].values()
            )
        )

    def test_missing_reader_is_runtime_failure_not_unavailable_paper(self):
        with patch(
            "stage1_eval.source_runtime.importlib.import_module",
            side_effect=ModuleNotFoundError("pdfplumber"),
        ):
            with self.assertRaisesRegex(
                EvaluationError, "missing parser is not unavailable scientific evidence"
            ):
                source_runtime_preflight()

    def test_importable_but_broken_reader_fails_probe(self):
        with patch("pdfplumber.open", side_effect=ValueError("broken parser")):
            with self.assertRaisesRegex(
                EvaluationError, "preflight failed before evaluation"
            ):
                source_runtime_preflight()


if __name__ == "__main__":
    unittest.main()

"""Exercise the scoped Stage 2 UI with deterministic authored data."""

from pathlib import Path
from html.parser import HTMLParser
import shutil
import subprocess
import unittest


class EmbeddedSelectionTests(unittest.TestCase):
    def test_implicit_submission_defaults_to_save_only(self):
        """Enter in a valid text field must not imply planning dispatch."""

        class DefaultSubmitters(HTMLParser):
            def __init__(self):
                super().__init__()
                self.form = None
                self.first = {}

            def handle_starttag(self, tag, attributes):
                attrs = dict(attributes)
                if tag == "form":
                    self.form = attrs.get("id")
                elif tag == "button" and self.form:
                    if attrs.get("type", "submit") == "submit":
                        self.first.setdefault(self.form, attrs.get("id"))

            def handle_endtag(self, tag):
                if tag == "form":
                    self.form = None

        parser = DefaultSubmitters()
        html = (
            Path(__file__).parents[1]
            / "cli/research_workspace_native/web/project-stage2-selection.html"
        )
        parser.feed(html.read_text(encoding="utf-8"))
        self.assertEqual(
            parser.first,
            {"direction-intent": "intent-save", "choice": "submit"},
        )

    def test_scoped_mount_is_version_bound_and_preserves_pending_keys(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for selection UI tests")
        script = Path(__file__).with_suffix(".cjs")
        result = subprocess.run(
            [node, "--test", str(script)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            timeout=45,
            check=False,
            shell=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("fail 0", result.stdout)

    def test_comparison_summary_and_preference_access(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for comparison UI tests")
        result = subprocess.run(
            [
                node,
                str(
                    Path(__file__).with_name(
                        "test_project_stage2_selection_comparison.cjs"
                    )
                ),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            timeout=25,
            check=False,
            shell=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Comparison summaries", result.stdout)


if __name__ == "__main__":
    unittest.main()

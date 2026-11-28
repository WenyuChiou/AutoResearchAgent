"""The Quickstart and the entry documents must name one entry, and mark the old launcher."""

from pathlib import Path
import unittest

REPO = Path(__file__).resolve().parent.parent
PLUGIN = "plugins/auto-research-agent"
# Documents that still describe the old launcher: each must say it is kept for compatibility only.
LAUNCHER_DOCS = (
    f"{PLUGIN}/references/research-workspace/PORTABLE_ATLAS_SETUP.md",
    f"{PLUGIN}/references/research-workspace/atlas-launch-guide.md",
    f"{PLUGIN}/references/research-workspace/examples/UNIVERSAL_PROJECTS.md",
    f"{PLUGIN}/references/stage1-automatic-execution.md",
    f"{PLUGIN}/cli/research_workspace_native/README.md",
)
LAUNCHER_DOCS_ZH = (f"{PLUGIN}/references/research-workspace/stage1-bounded-run.md",)


def read(rel):
    return (REPO / rel).read_text(encoding="utf-8")


class SingleEntryDocumentTests(unittest.TestCase):
    def test_quickstarts_point_at_the_wiki_entry_and_state_the_limits(self):
        for name in ("QUICKSTART.md", "QUICKSTART.zh-CN.md"):
            with self.subTest(name=name):
                text = read(f"harness-ui/{name}")
                self.assertIn("Start-Wiki.ps1", text)
                self.assertIn("run_v9.py", text)
                self.assertIn("run-project-workspace.py", text)
                self.assertIn("-Real", text)

    def test_every_document_about_the_old_launcher_marks_it_compatibility_only(self):
        for rel in LAUNCHER_DOCS:
            with self.subTest(rel=rel):
                text = read(rel)
                self.assertIn("Compatibility only", text)
                self.assertIn("Start-Wiki.ps1", text)
        for rel in LAUNCHER_DOCS_ZH:
            with self.subTest(rel=rel):
                text = read(rel)
                self.assertIn("仅兼容", text)
                self.assertIn("Start-Wiki.ps1", text)

    def test_the_launcher_says_it_is_compatibility_only_in_its_own_docstring(self):
        text = read(
            f"{PLUGIN}/references/research-workspace/examples/run-project-workspace.py"
        )
        self.assertIn("Compatibility only", text.split('"""')[1])


if __name__ == "__main__":
    unittest.main()

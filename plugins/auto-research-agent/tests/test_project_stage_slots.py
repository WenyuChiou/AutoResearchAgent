"""Six StageSlots presentation guards; actual shared projection, authored DOM."""

from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
WEB = PLUGIN / "cli/research_workspace_native/web"
sys.path.insert(0, str(PLUGIN / "cli"))
from research_workspace_native.project_contract import project_view  # noqa: E402


class Mounts(HTMLParser):
    """Retain physical HTML ancestry instead of source substring positions."""

    void_tags = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self):
        super().__init__()
        self.stack = []
        self.ids = {}
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        identity = attrs.get("id")
        if identity:
            self.ids.setdefault(identity, []).append(
                tuple(item[1] for item in self.stack if item[1])
            )
        if tag == "script":
            self.scripts.append(attrs.get("src"))
        if tag not in self.void_tags:
            self.stack.append((tag, identity))

    def handle_endtag(self, tag):
        if tag in self.void_tags:
            return
        if not self.stack or self.stack[-1][0] != tag:
            raise AssertionError(f"Unbalanced stage HTML at closing {tag}")
        self.stack.pop()


class ProjectStageSlotsTests(unittest.TestCase):
    def test_shared_projection_six_slots_guards_and_presentation_only_navigation(self):
        project = dict(
            project_ref="authored-project",
            project_id="authored-project-id",
            input_version=1,
            revision=0,
            brief_sha256="a" * 64,
            plan=None,
            settings=None,
        )
        intake = SimpleNamespace(read=lambda credential, ref: project)
        contract = project_view(
            intake, "authored-private-credential", project["project_ref"]
        )
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node required for actual StageSlots source checks")
        result = subprocess.run(
            [node, str(PLUGIN / "tests/browser/project-stage-slots-test.cjs")],
            input=json.dumps(dict(project=project, contract=contract)),
            encoding="utf8",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        report = json.loads(result.stdout.strip())
        self.assertEqual(report["kind"], "ProjectStageSlotsAuthoredDomChecks")
        self.assertEqual(report["stages"], 6)
        self.assertEqual(report["languages"], 3)
        self.assertGreaterEqual(report["refused_contracts"], 30)
        self.assertEqual(report["side_effects"], 0)
        print(result.stdout.strip())

    def test_physical_stage_mounts_are_unique_and_stage2_is_outside_stage1_actions(
        self,
    ):
        mounts = Mounts()
        mounts.feed((WEB / "projects.html").read_text(encoding="utf8"))
        self.assertEqual(mounts.stack, [], "HTML is physically balanced")
        self.assertEqual(
            [identity for identity, rows in mounts.ids.items() if len(rows) != 1],
            [],
            "duplicate IDs would route operations or result mounts to the wrong stage",
        )
        for number in range(1, 7):
            stage = f"project-stage-{number}"
            self.assertIn(stage, mounts.ids)
            self.assertIn(f"project-stage-nav-{number}", mounts.ids)
            for area in ("title", "status", "operations", "results"):
                identity = f"{stage}-{area}"
                self.assertIn(identity, mounts.ids)
                self.assertIn(stage, mounts.ids[identity][0])
            for other in range(1, 7):
                if other != number:
                    self.assertNotIn(f"project-stage-{other}", mounts.ids[stage][0])
        self.assertIn("project-stage-1-operations", mounts.ids["stage1-actions"][0])
        self.assertIn("project-stage-1-results", mounts.ids["project-atlas-inline"][0])
        self.assertIn(
            "project-stage-2-operations", mounts.ids["project-stage2-controls"][0]
        )
        self.assertNotIn("stage1-actions", mounts.ids["project-stage2-controls"][0])
        self.assertIn(
            "project-stage-2-results", mounts.ids["project-stage-2-result-state"][0]
        )
        self.assertIn("/projects-stages.js", mounts.scripts)
        self.assertLess(
            mounts.scripts.index("/projects-stages.js"),
            mounts.scripts.index("/projects.js"),
        )


if __name__ == "__main__":
    unittest.main()

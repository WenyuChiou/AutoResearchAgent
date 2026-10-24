"""Typed input identity reaches the real six-stage script without research."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
from research_workspace_native.project_contract import project_view  # noqa: E402


class TypedStageNavigationTests(unittest.TestCase):
    def check_navigation(self, version):
        project = dict(
            project_ref="authored-project",
            project_id="authored-project-id",
            input_version=version,
            revision=0,
            brief_sha256="a" * 64,
            plan=None,
            settings=None,
        )
        contract = project_view(
            SimpleNamespace(read=lambda credential, ref: project),
            "authored-private-credential",
            project["project_ref"],
        )
        contract["stages"]["2"]["attempts"] = [{"status": "retained-current-marker"}]
        self.assertEqual(contract["identity"]["input_version"], version)
        self.assertIs(type(contract["identity"]["input_version"]), type(version))
        self.assertEqual(
            contract["schema_version"], "1.1.0" if type(version) is str else "1.0.0"
        )
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node required for the actual six-stage script")
        result = subprocess.run(
            [node, str(PLUGIN / "tests/browser/project-typed-navigation-test.cjs")],
            input=json.dumps(dict(project=project, contract=contract)),
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["languages"], 3)
        self.assertGreaterEqual(report["refused_contracts"], 30)
        self.assertEqual(report["side_effects"], 0)
        print(result.stdout.strip())

    def test_integer_keeps_legacy_schema_and_navigation(self):
        self.check_navigation(1)

    def test_imported_strings_keep_exact_type_and_selection_link(self):
        for version in (
            "fresh-1",
            "20261009-A03",
            "1",
            "\U0001f600" * 128,
            "\ufeffversion",
        ):
            with self.subTest(version=version):
                self.check_navigation(version)


if __name__ == "__main__":
    unittest.main()

"""Regression checks for component selection and required-job conclusions."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import ci_scope


class ScopeTests(unittest.TestCase):
    def test_non_runtime_docs_and_evidence_select_only_contract_smoke(self):
        self.assertEqual(
            ci_scope.plugin_test_scope(
                [
                    "plugins/auto-research-agent/README.md",
                    "plugins/auto-research-agent/CONTRIBUTING.md",
                    "review-evidence/wiki/screenshots/mobile.png",
                    "review-evidence/wiki/tests.log",
                ]
            ),
            "docs",
        )

    def test_atlas_markup_and_styles_select_workspace_interface_checks(self):
        assets = "plugins/auto-research-agent/references/research-workspace/atlas/"
        self.assertEqual(
            ci_scope.plugin_test_scope([assets + "atlas.html", assets + "atlas.css"]),
            "ui",
        )
        self.assertEqual(
            ci_scope.plugin_test_scope([assets + "atlas.css", "review-evidence/x.md"]),
            "ui",
        )

    def test_executable_prompts_interfaces_governance_and_unknowns_keep_full_suite(
        self,
    ):
        for path in [
            "plugins/auto-research-agent/skills/stage1/SKILL.md",
            "plugins/auto-research-agent/cli/research_workspace_native/atlas_host.py",
            "plugins/auto-research-agent/references/research-workspace/atlas/atlas-ui.js",
            "plugins/auto-research-agent/requirements-test.txt",
            "plugins/auto-research-agent/evals/capability-metric-map.v3.json",
            "plugins/auto-research-agent/AGENTS.md",
            ".github/workflows/stage1-plugin.yml",
            ".github/workflows/research-pr-metadata.yml",
            ".github/scripts/ci_scope.py",
            "review-evidence/test.py",
            "unknown.html",
            "codex-rs/core/src/lib.rs",
        ]:
            with self.subTest(path=path):
                self.assertEqual(ci_scope.plugin_test_scope([path]), "full")
                self.assertEqual(
                    ci_scope.plugin_test_scope(["review-evidence/x.md", path]), "full"
                )
        self.assertEqual(ci_scope.plugin_test_scope([]), "full")

    def test_selected_suites_run_failure_and_do_not_run_unrelated_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            tests = Path(directory)
            for name in (
                "test_stage_contracts.py",
                "test_workspace_widget.py",
                "test_native_message_widget.py",
                "test_stage2_widget.py",
            ):
                # Actual import/discovery and execution, without product processes.
                (tests / name).write_text(
                    "import unittest\nclass Example(unittest.TestCase):\n"
                    "    def test_guard(self):\n        self.fail('synthetic failure')\n",
                    encoding="utf-8",
                )
            try:
                for scope, count in [("docs", 1), ("ui", 3), ("full", 4)]:
                    with self.subTest(scope=scope):
                        suite = ci_scope.plugin_suite(tests, scope)
                        self.assertEqual(suite.countTestCases(), count)
                        result = unittest.TestResult()
                        suite.run(result)
                        self.assertFalse(result.wasSuccessful())
                        self.assertEqual(len(result.failures), count)
                with self.assertRaises(ValueError):
                    ci_scope.plugin_suite(tests, "skipped")
            finally:
                for name in (
                    "test_stage_contracts",
                    "test_workspace_widget",
                    "test_native_message_widget",
                    "test_stage2_widget",
                ):
                    sys.modules.pop(name, None)

    def test_empty_selected_suite_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                ci_scope.plugin_suite(Path(directory), "ui")

    def test_plugin_changes_and_renames_preserve_engine_boundary(self):
        self.assertTrue(ci_scope.plugin_only(["plugins/auto-research-agent/skill.md"]))
        self.assertTrue(ci_scope.plugin_only([".github/workflows/stage1-plugin.yml"]))
        self.assertTrue(
            ci_scope.plugin_only(
                [
                    ".github/scripts/check_research_pr_dependencies.py",
                    ".github/pull_request_template.md",
                    ".github/scripts/fixtures/pr_bodies/implementation-only.md",
                    ".github/scripts/fixtures/pr_evidence/live-run.json",
                    ".github/scripts/invariant-registry.v1.json",
                    ".github/scripts/criterion-submetric-map.v1.json",
                ]
            )
        )
        for paths in [
            [],
            ["codex-rs/core/src/lib.rs"],
            ["unknown/file"],
            ["plugins/auto-research-agent/a.py", "sdk/python/old.py"],
            ["plugins/another-plugin/plugin.json"],
        ]:
            with self.subTest(paths=paths):
                self.assertFalse(ci_scope.plugin_only(paths))

    def test_base_advancing_does_not_make_plugin_pr_an_engine_change(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)

            def git(*args):
                return subprocess.check_output(
                    ["git", *args], cwd=repo, text=True
                ).strip()

            git("init", "--initial-branch=main")
            git("config", "user.name", "CI test")
            git("config", "user.email", "ci@example.invalid")
            (repo / "engine.txt").write_text("original", encoding="utf-8")
            git("add", "engine.txt")
            git("commit", "-m", "base")
            git("checkout", "-b", "plugin")
            path = repo / "plugins/auto-research-agent/new.txt"
            path.parent.mkdir(parents=True)
            path.write_text("plugin", encoding="utf-8")
            git("add", "plugins/auto-research-agent/new.txt")
            git("commit", "-m", "plugin")
            head = git("rev-parse", "HEAD")
            git("checkout", "main")
            (repo / "engine.txt").write_text("unrelated new work", encoding="utf-8")
            git("add", "engine.txt")
            git("commit", "-m", "advanced base")
            base = git("rev-parse", "HEAD")
            self.assertEqual(
                ci_scope.changed_paths(base, head, repo),
                ["plugins/auto-research-agent/new.txt"],
            )
            self.assertEqual(
                ci_scope.changed_paths(base, head, repo, event="push"),
                ["engine.txt", "plugins/auto-research-agent/new.txt"],
            )

    def test_gate_accepts_only_planned_skips(self):
        needs = {name: {"result": "skipped"} for name in ci_scope.ENGINE_JOBS}
        needs.update(
            scope={"result": "success", "outputs": {"plugin_only": "true"}},
            stage1={"result": "success"},
        )
        needs["blob-size-policy"] = {"result": "success"}
        self.assertEqual(ci_scope.check_results(needs), [])
        for name, result in [
            ("stage1", "skipped"),
            ("stage1", "failure"),
            ("stage1", "cancelled"),
            ("scope", "failure"),
            ("bazel", "failure"),
            ("blob-size-policy", "skipped"),
        ]:
            with self.subTest(name=name, result=result):
                bad = json.loads(json.dumps(needs))
                bad[name]["result"] = result
                self.assertTrue(ci_scope.check_results(bad))
        del needs["stage1"]
        self.assertTrue(ci_scope.check_results(needs))

    def test_full_scope_and_unknown_plan_fail_closed(self):
        needs = {name: {"result": "success"} for name in ci_scope.ENGINE_JOBS}
        needs.update(
            scope={"result": "success", "outputs": {"plugin_only": "false"}},
            stage1={"result": "success"},
        )
        needs["blob-size-policy"] = {"result": "success"}
        self.assertEqual(ci_scope.check_results(needs), [])
        needs["bazel"]["result"] = "skipped"
        self.assertTrue(ci_scope.check_results(needs))
        needs["scope"]["outputs"]["plugin_only"] = ""
        self.assertTrue(ci_scope.check_results(needs))
        env = {**os.environ, "NEEDS": json.dumps(needs)}
        process = subprocess.run(
            [sys.executable, str(Path(ci_scope.__file__)), "check"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(process.returncode, 0)

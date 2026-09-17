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
    def test_plugin_changes_and_renames_preserve_engine_boundary(self):
        self.assertTrue(ci_scope.plugin_only(["plugins/auto-research-agent/skill.md"]))
        self.assertTrue(ci_scope.plugin_only([".github/workflows/stage1-plugin.yml"]))
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

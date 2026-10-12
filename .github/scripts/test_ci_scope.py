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
    def test_governance_fast_path_requires_only_regular_allowlisted_edits(self):
        root = {
            "status": "M",
            "old_mode": "100644",
            "new_mode": "100644",
            "old_path": "AGENTS.md",
            "new_path": "AGENTS.md",
        }
        nested = {
            **root,
            "old_path": "plugins/auto-research-agent/AGENTS.md",
            "new_path": "plugins/auto-research-agent/AGENTS.md",
        }
        # Metadata-shaped data is not enough: governance scope needs blobs that
        # the trusted local Git object database can read and decode as text.
        self.assertFalse(ci_scope.governance_only([root, nested]))
        self.assertEqual(
            ci_scope.plugin_test_scope(
                [root["old_path"]], [root], event="pull_request"
            ),
            "full",
        )
        self.assertEqual(
            ci_scope.plugin_test_scope([root["old_path"]], [root], event="push"),
            "full",
        )
        self.assertFalse(ci_scope.governance_only([]))
        runtime = {**root, "old_path": "src/runtime.py", "new_path": "src/runtime.py"}
        self.assertFalse(ci_scope.governance_only([root, runtime]))
        for change in (
            {**root, "status": "D"},
            {**root, "status": "R", "old_path": "src/runtime.py"},
            {**root, "old_mode": "100755"},
            {**root, "new_mode": "120000"},
            {**root, "status": "T"},
        ):
            with self.subTest(change=change):
                self.assertFalse(ci_scope.governance_only([change]))

    def test_selector_and_workflow_changes_cannot_use_governance_fast_path(self):
        for path in (
            ".github/scripts/ci_scope.py",
            ".github/scripts/stage1_test_scope.py",
            ".github/workflows/stage1-plugin.yml",
        ):
            record = {
                "status": "M",
                "old_mode": "100644",
                "new_mode": "100644",
                "old_path": path,
                "new_path": path,
            }
            with self.subTest(path=path):
                self.assertFalse(ci_scope.governance_only([record]))
                self.assertEqual(
                    ci_scope.plugin_test_scope([path], [record], event="pull_request"),
                    "full",
                )

    def test_raw_diff_parser_requires_complete_records_and_keeps_rename_endpoints(
        self,
    ):
        sha = b"a" * 40
        raw = b":100644 100644 " + sha + b" " + sha + b" R100\0src/old.py\0AGENTS.md\0"
        records = ci_scope.parse_raw_diff(raw)
        self.assertEqual(records[0]["status"], "R")
        self.assertEqual(records[0]["old_path"], "src/old.py")
        self.assertEqual(records[0]["new_path"], "AGENTS.md")
        self.assertFalse(ci_scope.governance_only(records))
        self.assertEqual(ci_scope.parse_raw_diff(b""), [])
        malformed_records = (
            b"broken\0",
            raw.rstrip(b"\0"),
            b":100644 100644 " + sha + b" " + sha + b" R100\0src/old.py\0",
        )
        for malformed in malformed_records:
            with self.subTest(malformed=malformed):
                with self.assertRaises(ValueError):
                    ci_scope.parse_raw_diff(malformed)

    def test_git_metadata_rejects_deletion_rename_and_mode_change(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)

            def git(*args):
                return subprocess.check_output(
                    ["git", *args], cwd=repo, text=True, timeout=20
                ).strip()

            git("init")
            git("config", "user.name", "Scope contract test")
            git("config", "user.email", "scope@example.invalid")
            git("config", "core.filemode", "true")
            (repo / "AGENTS.md").write_text("governance\n", encoding="utf-8")
            runtime = repo / "src/runtime.py"
            runtime.parent.mkdir()
            runtime.write_text("runtime\n", encoding="utf-8")
            git("add", "AGENTS.md", "src/runtime.py")
            git("commit", "-m", "base")
            base = git("rev-parse", "HEAD")

            (repo / "AGENTS.md").write_text("governance update\n", encoding="utf-8")
            git("add", "AGENTS.md")
            git("commit", "-m", "governance edit")
            governance_head = git("rev-parse", "HEAD")
            records = ci_scope.changed_records(base, governance_head, repo)
            self.assertTrue(ci_scope.governance_only(records, repo), records)
            self.assertEqual(
                ci_scope.plugin_test_scope(
                    ["AGENTS.md"],
                    records,
                    event="pull_request",
                    repo=repo,
                ),
                "governance",
            )

            git("update-index", "--chmod=+x", "AGENTS.md")
            git("commit", "-m", "mode change")
            mode_head = git("rev-parse", "HEAD")
            mode_records = ci_scope.changed_records(governance_head, mode_head, repo)
            self.assertEqual(mode_records[0]["status"], "M")
            self.assertNotEqual(
                mode_records[0]["old_mode"], mode_records[0]["new_mode"]
            )
            self.assertFalse(ci_scope.governance_only(mode_records))

        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)

            def git(*args):
                return subprocess.run(
                    ["git", *args],
                    cwd=repo,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=20,
                ).stdout.strip()

            git("init")
            git("config", "user.name", "Scope contract test")
            git("config", "user.email", "scope@example.invalid")
            source = repo / "src/runtime.py"
            source.parent.mkdir()
            source.write_text("runtime\n", encoding="utf-8")
            git("add", "src/runtime.py")
            git("commit", "-m", "base")
            base = git("rev-parse", "HEAD")
            git("mv", "src/runtime.py", "AGENTS.md")
            git("commit", "-m", "rename into allowlist")
            head = git("rev-parse", "HEAD")
            records = ci_scope.changed_records(base, head, repo)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["status"], "R")
            self.assertEqual(
                (records[0]["old_path"], records[0]["new_path"]),
                ("src/runtime.py", "AGENTS.md"),
            )
            self.assertFalse(ci_scope.governance_only(records))

    def test_real_git_bad_blobs_fail_closed_on_both_diff_sides(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)

            def git(*args):
                return subprocess.check_output(
                    ["git", *args], cwd=repo, text=True, timeout=20
                ).strip()

            git("init")
            git("config", "user.name", "Scope contract test")
            git("config", "user.email", "scope@example.invalid")
            path = repo / "AGENTS.md"
            path.write_text("governance rules\n", encoding="utf-8")
            git("add", "AGENTS.md")
            git("commit", "-m", "base")
            base = git("rev-parse", "HEAD")

            for payload in (b"rules\0binary", b"\xff\xfeunknown", b""):
                with self.subTest(payload=payload):
                    git("reset", "--hard", base)
                    path.write_bytes(payload)
                    git("add", "AGENTS.md")
                    git("commit", "-m", "binary or empty governance blob")
                    head = git("rev-parse", "HEAD")
                    self.assertEqual(git("rev-parse", "HEAD^"), base)
                    records = ci_scope.changed_records(base, head, repo)
                    self.assertFalse(ci_scope.governance_only(records, repo))

            git("reset", "--hard", base)
            path.write_bytes(b"invalid\0old blob")
            git("add", "AGENTS.md")
            git("commit", "-m", "invalid old governance blob")
            invalid_old = git("rev-parse", "HEAD")
            path.write_text("repaired governance rules\n", encoding="utf-8")
            git("add", "AGENTS.md")
            git("commit", "-m", "repair governance blob")
            repaired_head = git("rev-parse", "HEAD")
            self.assertEqual(git("rev-parse", "HEAD^"), invalid_old)
            records = ci_scope.changed_records(invalid_old, repaired_head, repo)
            self.assertFalse(ci_scope.governance_only(records, repo))

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

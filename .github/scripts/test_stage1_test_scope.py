"""Behavioral checks for affected tests and the fail-closed CI runner."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import stage1_test_scope as scope


REPO = Path(__file__).resolve().parents[2]
PASSING = "import unittest\nclass T(unittest.TestCase):\n def test_ok(self): pass\n"
TESTS = scope.TEST_DIR.as_posix() + "/"


class Stage1TestScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.write(TESTS + "test_plugin_loading.py", PASSING)
        self.write(TESTS + "test_stage_contracts.py", PASSING)
        for name in ("stage1_test_scope.py", "ci_scope.py"):
            target = self.repo / ".github/scripts" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / ".github/scripts" / name, target)

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def fixture(
        self, selection=None, event=None, kind="workflow_dispatch", contracts=False
    ):
        script = self.repo / ".github/scripts/stage1_test_scope.py"
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        if selection is None:
            event_path = self.write("event.json", json.dumps(event or {}))
            env.update(GITHUB_EVENT_PATH=str(event_path), GITHUB_EVENT_NAME=kind)
            command = [sys.executable, str(script)] + (
                ["--contracts"] if contracts else []
            )
        else:
            command = [
                sys.executable,
                "-c",
                "import json,sys; import stage1_test_scope as s; "
                "sys.exit(s.run_suite(json.loads(sys.argv[1])))",
                json.dumps(selection),
            ]
            env["PYTHONPATH"] = str(script.parent)
        return subprocess.run(
            command, cwd=self.repo, env=env, capture_output=True, text=True, timeout=20
        )

    def git(self, *args):
        return subprocess.check_output(
            ["git", *args], cwd=self.repo, text=True, timeout=20
        ).strip()

    def test_docs_and_ci_use_loading_and_stage_contract_guards(self):
        for path in (
            "plugins/auto-research-agent/README.md",
            ".github/workflows/stage1-plugin.yml",
            ".github/scripts/ci_scope.py",
            ".github/scripts/test_stage1_test_scope.py",
        ):
            with self.subTest(path=path):
                paths = [path, ".github/pull_request_template.md"]
                self.assertEqual(
                    scope.plan(paths, self.repo)["modules"],
                    ["test_plugin_loading", "test_stage_contracts"],
                )
                self.assertEqual(scope.plan(paths, self.repo)["mode"], "selected")

    def test_test_references_expand_transitively(self):
        for name, source in {
            "test_changed": PASSING,
            "test_direct": "import test_changed",
            "test_indirect": "importlib.import_module('test_direct')",
            "test_unrelated": PASSING,
        }.items():
            self.write(TESTS + name + ".py", source)
        result = scope.plan([TESTS + "test_changed.py"], repo=self.repo)
        self.assertEqual(
            result["modules"],
            [
                "test_changed",
                "test_direct",
                "test_indirect",
                "test_plugin_loading",
                "test_stage_contracts",
            ],
        )

    def test_uncertain_inputs_keep_full_suite(self):
        for path in (
            "plugins/auto-research-agent/tools/shared.py",
            TESTS + "__init__.py",
            "plugins/auto-research-agent/requirements-test.txt",
            "unknown.py",
            TESTS + "test_deleted.py",
            TESTS + "fixtures/data.json",
            "plugins/auto-research-agent/skills/stage1-literature/SKILL.md",
        ):
            with self.subTest(path=path):
                result = scope.plan(
                    [".github/pull_request_template.md", path], self.repo
                )
                self.assertEqual((result["mode"], result["modules"]), ("full", []))
        self.assertEqual(scope.plan([], repo=self.repo)["mode"], "full")

    def test_pr_uses_merge_base_and_push_uses_previous_tip(self):
        self.git("init", "--initial-branch=main")
        self.git("config", "user.name", "CI fixture")
        self.git("config", "user.email", "ci@example.invalid")
        self.write("engine.txt", "original")
        self.git("add", "engine.txt")
        self.git("commit", "-m", "base")
        self.git("checkout", "-b", "plugin")
        path = TESTS + "test_changed.py"
        self.write(path, PASSING)
        self.git("add", path)
        self.git("commit", "-m", "test change")
        head = self.git("rev-parse", "HEAD")
        self.git("checkout", "main")
        self.write("engine.txt", "unrelated base advance")
        self.git("add", "engine.txt")
        self.git("commit", "-m", "advanced base")
        base = self.git("rev-parse", "HEAD")
        pull = {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}
        self.assertEqual(scope.event_paths(pull, "pull_request", self.repo), [path])
        self.assertEqual(
            scope.event_paths({"before": base, "after": head}, "push", repo=self.repo),
            ["engine.txt", path],
        )

    def test_unavailable_or_malformed_shas_fail(self):
        self.git("init", "--initial-branch=main")
        for base, head in (("HEAD", "f" * 40), ("0" * 40, "f" * 40)):
            event = {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}
            with self.subTest(base=base):
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    scope.event_paths(event, "pull_request", repo=self.repo)
                failed = self.fixture(event=event, kind="pull_request")
                self.assertNotEqual(failed.returncode, 0)
                self.assertNotIn('"passed": true', failed.stdout)

    def test_manual_and_initial_push_run_full_fixture_suite(self):
        self.write(TESTS + "test_other.py", PASSING)
        for name, event in (("workflow_dispatch", {}), ("push", {"before": "0" * 40})):
            with self.subTest(event_name=name):
                result = self.fixture(event=event, kind=name)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                rows = [json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual((rows[0]["mode"], rows[-1]["tests_run"]), ("full", 3))

    def test_real_failures_and_import_errors_fail_runner(self):
        for source, key in (
            (PASSING.replace("pass", "self.fail('fixture failure')"), "failures"),
            ("import nonexistent_ci_fixture_dependency", "errors"),
            ("raise RuntimeError('fixture import error')", None),
        ):
            with self.subTest(key=key):
                self.write(TESTS + "test_fixture.py", source)
                result = self.fixture({"mode": "selected", "modules": ["test_fixture"]})
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                if key:
                    summary = json.loads(result.stdout.splitlines()[-1])
                    self.assertEqual(summary["tests_run"], 1)
                    self.assertEqual(summary[key], 1)
                    self.assertFalse(summary["passed"])
                else:
                    self.assertIn("fixture import error", result.stderr)

    def test_empty_requested_module_fails_even_with_loading_smoke(self):
        self.write(TESTS + "test_empty.py", "# no executable tests\n")
        for modules in (["test_empty"], ["test_empty", "test_plugin_loading"]):
            with self.subTest(modules=modules):
                result = self.fixture({"mode": "selected", "modules": modules})
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_contract_flag_runs_real_contract_fixtures(self):
        for name in scope.CONTRACT_MODULES:
            self.write(".github/scripts/" + name + ".py", PASSING)
        result = self.fixture(contracts=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            json.loads(result.stdout.splitlines()[-1])["tests_run"],
            len(scope.CONTRACT_MODULES),
        )
        self.write(
            ".github/scripts/test_ci_scope.py", "raise RuntimeError('contract failure')"
        )
        self.assertNotEqual(self.fixture(contracts=True).returncode, 0)

    def test_workflow_preserves_required_matrix_and_runner_steps(self):
        workflow = (REPO / ".github/workflows/stage1-plugin.yml").read_text("utf-8")
        entry = "python .github/scripts/stage1_test_scope.py"
        self.assertIn("  contracts:\n", workflow)
        self.assertIn("os: [ubuntu-latest, windows-latest, macos-latest]", workflow)
        self.assertIn("runs-on: ${{ matrix.os }}", workflow)
        self.assertEqual(
            workflow.count("fetch-depth: 0"), workflow.count("uses: actions/checkout@")
        )
        self.assertEqual(workflow.count(entry), 2)
        self.assertIn(entry + " --contracts", workflow)


if __name__ == "__main__":
    unittest.main()

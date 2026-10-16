"""Regression tests proving the Stage 1 CI quality commands reject bad input."""

import os
import re
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


class Stage1CiQualityTests(unittest.TestCase):
    @staticmethod
    def _scope_condition(expression, scope):
        if not expression.startswith("${{") or not expression.endswith("}}"):
            raise AssertionError(f"scope condition is not explicit: {expression}")
        source = expression[3:-2].strip()
        tokens = re.split(r"\s+(&&|\|\|)\s+", source)
        comparisons = tokens[::2]
        operators = tokens[1::2]
        if len(set(operators)) > 1:
            raise AssertionError(f"unsupported mixed scope condition: {expression}")
        results = []
        for comparison in comparisons:
            match = re.fullmatch(
                r"needs\.scope\.outputs\.plugin_test_scope\s*(==|!=)\s*'([^']+)'",
                comparison,
            )
            if match is None:
                raise AssertionError(f"unsupported scope comparison: {comparison}")
            equal = scope == match.group(2)
            results.append(equal if match.group(1) == "==" else not equal)
        if not operators:
            return results[0]
        return all(results) if operators[0] == "&&" else any(results)

    def test_workflow_conditionals_use_supported_github_operators(self):
        workflow = yaml.load(
            (REPO_ROOT / ".github/workflows/stage1-plugin.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        conditions = [job.get("if", "") for job in workflow["jobs"].values()] + [
            step.get("if", "")
            for job in workflow["jobs"].values()
            for step in job["steps"]
        ]
        # GitHub's expression reference lists ==, !=, &&, and ||, not Python membership operators.
        for condition in conditions:
            self.assertNotRegex(condition, r"\b(?:not\s+)?in\b")
            self.assertNotRegex(condition, r"\b(?:and|or)\b")

        steps = workflow["jobs"]["contracts"]["steps"]
        by_name = {step.get("name", step.get("run", "")): step for step in steps}
        node_setup = next(
            step
            for step in steps
            if step.get("uses", "").startswith("actions/setup-node@")
        )
        gates = {
            "install": by_name["npm install --global @openai/codex@0.153.0"]["if"],
            "node_setup": node_setup["if"],
            "cli_version": by_name["codex --version"]["if"],
            "format": by_name["Check plugin and CI Python formatting"]["if"],
            "quality": by_name["Check plugin and CI Python quality"]["if"],
            "plugin_contracts": by_name["Plugin loading and stage contracts"]["if"],
            "pr_contracts": by_name["Research PR contract tests"]["if"],
            "governance": by_name["Governance scope and validator contracts"]["if"],
        }
        for scope in ("docs", "governance", "ui", "full"):
            with self.subTest(scope=scope):
                ui_or_full = scope in {"ui", "full"}
                not_docs_or_governance = scope in {"ui", "full"}
                for gate in ("install", "node_setup", "cli_version"):
                    self.assertEqual(
                        self._scope_condition(gates[gate], scope),
                        not_docs_or_governance,
                    )
                for gate in ("format", "quality"):
                    self.assertEqual(
                        self._scope_condition(gates[gate], scope), ui_or_full
                    )
                for gate in ("plugin_contracts", "pr_contracts"):
                    self.assertEqual(
                        self._scope_condition(gates[gate], scope),
                        scope != "governance",
                    )
                self.assertEqual(
                    self._scope_condition(gates["governance"], scope),
                    scope == "governance",
                )

    def test_metadata_cannot_replace_source_contract_statuses(self):
        workflows = REPO_ROOT / ".github/workflows"
        source = yaml.load(
            (workflows / "stage1-plugin.yml").read_text(), Loader=yaml.BaseLoader
        )
        metadata = yaml.load(
            (workflows / "research-pr-metadata.yml").read_text(), Loader=yaml.BaseLoader
        )
        self.assertEqual(
            source["on"]["pull_request"]["types"], ["opened", "synchronize", "reopened"]
        )
        self.assertNotIn("pull_request_target", source["on"])
        self.assertEqual(
            metadata["on"]["pull_request"]["types"],
            ["opened", "synchronize", "reopened", "edited", "ready_for_review"],
        )
        self.assertEqual(set(metadata["jobs"]), {"pr-contract"})
        self.assertNotIn("pr-contract", source["jobs"])
        job = source["jobs"]["contracts"]
        self.assertEqual(
            job["strategy"]["matrix"]["os"],
            ["ubuntu-latest", "windows-latest", "macos-latest"],
        )
        self.assertEqual(job["needs"], "scope")
        self.assertEqual(job["if"], "${{ always() }}")
        plugin_step = next(
            step
            for step in job["steps"]
            if step.get("name") == "Plugin loading and stage contracts"
        )
        self.assertEqual(
            plugin_step["env"]["PLUGIN_TEST_WORKERS"],
            "3",
        )
        self.assertEqual(source["permissions"], metadata["permissions"])
        scope_checkout = source["jobs"]["scope"]["steps"][0]
        self.assertEqual(scope_checkout["with"]["persist-credentials"], "false")
        self.assertEqual(
            source["concurrency"]["cancel-in-progress"],
            "${{ github.event_name == 'pull_request' }}",
        )

    def test_automatic_standard_profile_and_manual_full_are_explicit(self):
        workflow = yaml.load(
            (REPO_ROOT / ".github/workflows/stage1-plugin.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        profile = workflow["on"]["workflow_dispatch"]["inputs"]["test_profile"]
        self.assertEqual(profile["type"], "choice")
        self.assertEqual(profile["options"], ["full", "standard"])
        self.assertEqual(profile["default"], "full")
        self.assertEqual(
            workflow["jobs"]["contracts"]["env"]["PLUGIN_TEST_PROFILE"],
            "${{ github.event_name == 'workflow_dispatch' && inputs.test_profile || 'standard' }}",
        )
        self.assertEqual(
            workflow["jobs"]["contracts"]["env"]["PLUGIN_TEST_PLATFORM"],
            "${{ runner.os }}",
        )

    def test_parser_checks_use_fresh_copy_environment_without_uv_overlay(self):
        workflow = yaml.load(
            (REPO_ROOT / ".github/workflows/stage1-plugin.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        steps = workflow["jobs"]["contracts"]["steps"]
        names = {step.get("name"): step for step in steps}
        install = names["Prepare single-link Python test environment"]
        self.assertEqual(install["shell"], "pwsh")
        self.assertIn("--link-mode copy", install["run"])
        self.assertIn("$env:RUNNER_TEMP", install["run"])
        self.assertIn("$env:GITHUB_PATH", install["run"])
        self.assertIn("--managed-python 3.11", install["run"])
        self.assertIn(".resolve(strict=True)", install["run"])
        self.assertIn("-m venv --copies --without-pip", install["run"])
        self.assertIn("if ($IsMacOS)", install["run"])
        self.assertIn("shutil.copyfile", install["run"])
        self.assertIn("libpython3.11.dylib", install["run"])
        self.assertEqual(install["run"].count("exit $LASTEXITCODE"), 6)
        for name, suffix in (
            ("Plugin loading and stage contracts", ""),
            ("Research PR contract tests", " --contracts"),
            ("Governance scope and validator contracts", " --governance"),
        ):
            with self.subTest(step=name):
                self.assertLess(steps.index(install), steps.index(names[name]))
                self.assertEqual(
                    names[name]["run"],
                    "python .github/scripts/stage1_test_scope.py" + suffix,
                )

    def test_contract_environment_keeps_spawned_and_nested_imports_read_only(self):
        workflow = yaml.load(
            (REPO_ROOT / ".github/workflows/stage1-plugin.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        env = dict(os.environ)
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        env.update(workflow["jobs"]["contracts"].get("env", {}))
        with tempfile.TemporaryDirectory(prefix="ci-cache-") as directory:
            root = Path(directory)
            (root / "synthetic_import.py").write_text("VALUE = 1\n", encoding="utf8")
            script = root / "cache_probe.py"
            script.write_text(
                """from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import subprocess
import sys

def worker():
    import synthetic_import
    assert synthetic_import.VALUE == 1
    assert sys.dont_write_bytecode
    subprocess.run(
        [sys.executable, '-c',
         'import sys, synthetic_import; assert sys.dont_write_bytecode'],
        check=True,
    )
    return True

if __name__ == '__main__':
    import synthetic_import
    assert synthetic_import.VALUE == 1
    assert sys.dont_write_bytecode
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context('spawn')
    ) as executor:
        assert executor.submit(worker).result()
""",
                encoding="utf8",
            )
            result = subprocess.run(
                [sys.executable, str(script)],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(list(root.rglob("*.pyc")), [])

    def test_required_platform_guard_rejects_selector_failure_and_unknown_plan(self):
        path = REPO_ROOT / ".github/workflows/stage1-plugin.yml"
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        command = shlex.split(workflow["jobs"]["contracts"]["steps"][0]["run"])
        self.assertEqual(command[:2], ["python", "-c"])
        for result, scope, expected in [
            ("success", "docs", 0),
            ("success", "ui", 0),
            ("success", "full", 0),
            ("success", "governance", 0),
            ("failure", "docs", 1),
            ("cancelled", "full", 1),
            ("skipped", "ui", 1),
            ("success", "", 1),
            ("success", "unknown", 1),
        ]:
            with self.subTest(result=result, scope=scope):
                process = subprocess.run(
                    [sys.executable, *command[1:]],
                    env={
                        **os.environ,
                        "SCOPE_RESULT": result,
                        "PLUGIN_TEST_SCOPE": scope,
                    },
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(process.returncode, expected, process.stderr)

    def test_governance_plan_keeps_required_jobs_and_runs_bounded_contracts(self):
        workflow = yaml.load(
            (REPO_ROOT / ".github/workflows/stage1-plugin.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        job = workflow["jobs"]["contracts"]
        steps = {step.get("name", step.get("run", "")): step for step in job["steps"]}
        self.assertEqual(job["if"], "${{ always() }}")
        self.assertEqual(
            job["strategy"]["matrix"]["os"],
            ["ubuntu-latest", "windows-latest", "macos-latest"],
        )
        governance = steps["Governance scope and validator contracts"]
        self.assertEqual(
            governance["if"],
            "${{ needs.scope.outputs.plugin_test_scope == 'governance' }}",
        )
        self.assertIn("--governance", governance["run"])
        self.assertEqual(
            steps["Plugin loading and stage contracts"]["if"],
            "${{ needs.scope.outputs.plugin_test_scope != 'governance' }}",
        )
        self.assertEqual(
            steps["Research PR contract tests"]["if"],
            "${{ needs.scope.outputs.plugin_test_scope != 'governance' }}",
        )

    def test_ruff_check_rejects_unused_import(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unused.py"
            path.write_text("import os\n", encoding="utf-8")
            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "--frozen",
                    "--project",
                    str(REPO_ROOT / "scripts"),
                    "ruff",
                    "check",
                    str(path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("F401", result.stdout)

    def test_git_diff_check_rejects_crlf_with_trailing_whitespace(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)

            def git(*args, check=True):
                return subprocess.run(
                    ["git", *args],
                    cwd=repo,
                    check=check,
                    capture_output=True,
                    text=True,
                )

            git("init")
            git("config", "user.name", "CI test")
            git("config", "user.email", "ci@example.invalid")
            git("config", "core.autocrlf", "false")
            path = repo / "quality.txt"
            path.write_bytes(b"clean\n")
            git("add", "quality.txt")
            git("commit", "-m", "clean")
            path.write_bytes(b"bad trailing space \r\n")
            result = git("diff", "--check", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("trailing whitespace", result.stdout)


if __name__ == "__main__":
    unittest.main()

"""Behavioral checks for affected tests and the fail-closed CI runner."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

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
        for path in scope.DOCS | scope.CI_FILES:
            self.write(path, "# existing scope fixture\n")
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
        self,
        selection=None,
        event=None,
        kind="workflow_dispatch",
        contracts=False,
        workers=1,
        profile="standard",
        platform="",
    ):
        script = self.repo / ".github/scripts/stage1_test_scope.py"
        env = {
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PLUGIN_TEST_WORKERS": str(workers),
            "PLUGIN_TEST_PROFILE": profile,
            "PLUGIN_TEST_PLATFORM": platform,
        }
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
                "sys.exit(s.run_suite(json.loads(sys.argv[1]), workers=int(sys.argv[2]), profile=sys.argv[3], platform=sys.argv[4]))",
                json.dumps(selection),
                str(workers),
                profile,
                platform,
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
            "plugins/auto-research-agent/references/research-workspace/PORTABLE_ATLAS_SETUP.md",
            ".github/scripts/test_stage1_test_scope.py",
        ):
            with self.subTest(path=path):
                paths = [path, ".github/pull_request_template.md"]
                self.assertEqual(
                    scope.plan(paths, self.repo)["modules"],
                    ["test_plugin_loading", "test_stage_contracts"],
                )
                self.assertEqual(scope.plan(paths, self.repo)["mode"], "selected")

    def test_pure_docs_select_only_stage_contracts_after_path_validation(self):
        paths = [
            "plugins/auto-research-agent/README.md",
            "plugins/auto-research-agent/CONTRIBUTING.md",
            "review-evidence/release/SEAL.md",
        ]
        self.write(paths[-1], "Release evidence\n")
        for changed in ([path] for path in paths):
            with self.subTest(paths=changed):
                result = scope.plan(changed, self.repo)
                self.assertEqual(result["mode"], "selected")
                self.assertEqual(result["modules"], ["test_stage_contracts"])
        self.assertEqual(
            scope.plan(paths, self.repo)["modules"], ["test_stage_contracts"]
        )
        (self.repo / paths[-1]).unlink()
        self.assertEqual(scope.plan(paths, self.repo)["mode"], "full")

    def test_non_docs_changes_still_execute_cli_loading(self):
        self.write(
            TESTS + "test_plugin_loading.py",
            "raise RuntimeError('required CLI loading failed')",
        )
        for path in (
            ".github/pull_request_template.md",
            TESTS + "test_changed.py",
            "plugins/auto-research-agent/tools/shared.py",
        ):
            with self.subTest(path=path):
                self.write(path, PASSING)
                result = self.fixture(scope.plan([path], self.repo))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("required CLI loading failed", result.stderr)

    def slow_fixture(self):
        self.write(
            TESTS + "test_source_saved_pipeline.py",
            PASSING.replace("pass", "self.fail('long integration sentinel')"),
        )
        self.write(
            TESTS + "test_alias.py", "from test_source_saved_pipeline import T\n"
        )
        return {
            "mode": "full",
            "changed_paths": [".github/scripts/stage1_test_scope.py"],
        }

    def test_standard_profile_accounts_deferred_duplicates_without_running_them(self):
        result = self.fixture(self.slow_fixture(), workers=2)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        profile = next(row for row in rows if "test_profile" in row)
        self.assertEqual(profile["discovered_tests"], 4)
        self.assertEqual(profile["selected_tests"], 2)
        self.assertEqual(profile["deferred_tests"], 2)
        self.assertEqual(len(set(profile["deferred_test_ids"])), 1)
        self.assertEqual(profile["deferred_status"], "not-run; not a pass")
        self.assertEqual(rows[-1]["tests_run"], 2)
        self.assertEqual(rows[-1]["skips"], 0)

    def test_full_profile_executes_long_tests_and_preserves_duplicate_failures(self):
        result = self.fixture(self.slow_fixture(), workers=2, profile="full")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        profile = next(row for row in rows if "test_profile" in row)
        self.assertEqual(profile["deferred_tests"], 0)
        self.assertEqual(rows[-1]["planned_tests"], 4)
        self.assertEqual(rows[-1]["tests_run"], 4)
        self.assertEqual(rows[-1]["failures"], 2)
        self.assertIn("long integration sentinel", result.stderr)

    def test_all_automatic_change_types_defer_long_integration(self):
        selection = self.slow_fixture()
        for paths in (
            [TESTS + "test_source_saved_pipeline.py"],
            ["plugins/auto-research-agent/cli/unknown/main.py"],
            ["plugins/auto-research-agent/evals/capability-metric-map.v3.json"],
            [TESTS + "deleted.py"],
            ["requirements.txt"],
            [],
        ):
            with self.subTest(paths=paths):
                selection["changed_paths"] = paths
                result = self.fixture(selection)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("long integration sentinel", result.stderr)
                row = next(
                    json.loads(line)
                    for line in result.stdout.splitlines()
                    if "deferred_test_ids" in line
                )
                self.assertEqual(row["deferred_tests"], 2)

    def test_automatic_events_cannot_enable_full_profile(self):
        self.slow_fixture()
        for event in ("pull_request", "pull_request_target", "push", "workflow_call"):
            with self.subTest(event=event):
                result = self.fixture(event={}, kind=event, profile="full")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("explicit manual full run", result.stderr)
                self.assertNotIn("long integration sentinel", result.stderr)

    def test_manual_full_profile_reaches_real_long_test_failures(self):
        self.slow_fixture()
        result = self.fixture(event={}, profile="full")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("long integration sentinel", result.stderr)

    def test_cli_rejects_invalid_profile_before_running_tests(self):
        self.slow_fixture()
        result = self.fixture(event={}, profile="unknown")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertNotIn("long integration sentinel", result.stderr)

    def test_windows_standard_runs_smoke_without_importing_unrelated_modules(self):
        selection = self.slow_fixture()
        self.write(
            TESTS + "test_unrelated.py", "raise RuntimeError('not a smoke test')"
        )
        result = self.fixture(selection, workers=3, platform="Windows")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        scope_row = next(row for row in rows if "plugin_check_scope" in row)
        self.assertEqual(
            scope_row["modules"], ["test_plugin_loading", "test_stage_contracts"]
        )
        self.assertEqual(scope_row["windows_integration_status"], "not-run; not a pass")
        self.assertEqual(rows[-1]["tests_run"], 2)
        self.assertEqual(rows[-1]["skips"], 0)
        self.assertNotIn("not a smoke test", result.stderr)

    def test_windows_smoke_propagates_failures_and_missing_required_modules(self):
        selection = {"mode": "full"}
        self.write(
            TESTS + "test_plugin_loading.py",
            PASSING.replace("pass", "self.fail('smoke failure')"),
        )
        result = self.fixture(selection, platform="Windows")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("smoke failure", result.stderr)
        (self.repo / TESTS / "test_stage_contracts.py").unlink()
        result = self.fixture(selection, platform="Windows")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertGreater(json.loads(result.stdout.splitlines()[-1])["errors"], 0)

    def test_docs_smoke_does_not_require_cli_loading_on_any_platform(self):
        self.write(
            TESTS + "test_plugin_loading.py",
            "raise RuntimeError('CLI not installed for docs')",
        )
        self.git("init")
        self.git("config", "user.name", "Windows docs scope test")
        self.git("config", "user.email", "ci@example.invalid")
        readme = "plugins/auto-research-agent/README.md"
        self.git("add", readme)
        self.git("commit", "-m", "docs baseline")
        base = self.git("rev-parse", "HEAD")
        self.write(readme, "Updated documentation\n")
        self.git("add", readme)
        self.git("commit", "-m", "docs update")
        head = self.git("rev-parse", "HEAD")
        event = {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}
        for platform in ("", "Linux", "macOS", "Windows"):
            with self.subTest(platform=platform):
                result = self.fixture(
                    event=event, kind="pull_request", platform=platform
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                rows = [json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual(rows[0]["modules"], ["test_stage_contracts"])
                self.assertEqual(rows[-1]["tests_run"], 1)
                self.assertEqual(rows[-1]["skips"], 0)
        (self.repo / TESTS / "test_stage_contracts.py").unlink()
        missing = self.fixture(event=event, kind="pull_request", platform="Linux")
        self.assertNotEqual(missing.returncode, 0)
        self.assertGreater(json.loads(missing.stdout.splitlines()[-1])["errors"], 0)

    def test_windows_manual_full_and_other_platforms_keep_non_smoke_failures(self):
        selection = self.slow_fixture()
        self.write(
            TESTS + "test_non_smoke.py",
            PASSING.replace("pass", "self.fail('non-smoke failure')"),
        )
        for platform, profile in (
            ("Windows", "full"),
            ("Linux", "standard"),
            ("macOS", "standard"),
        ):
            with self.subTest(platform=platform, profile=profile):
                result = self.fixture(selection, platform=platform, profile=profile)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("non-smoke failure", result.stderr)
                self.assertNotIn('"plugin_check_scope": "windows-smoke"', result.stdout)

    def test_windows_cli_and_contract_modes_keep_their_required_checks(self):
        self.write(
            TESTS + "test_unrelated.py", "raise RuntimeError('not a smoke test')"
        )
        result = self.fixture(event={}, platform="Windows")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"plugin_check_scope": "windows-smoke"', result.stdout)
        for name in scope.CONTRACT_MODULES:
            self.write(".github/scripts/" + name + ".py", PASSING)
        result = self.fixture(contracts=True, platform="Windows")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            json.loads(result.stdout.splitlines()[-1])["tests_run"],
            len(scope.CONTRACT_MODULES),
        )
        self.assertNotIn('"plugin_check_scope": "windows-smoke"', result.stdout)

    def test_unknown_platform_fails_before_test_execution(self):
        result = self.fixture(event={}, platform="unknown")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("PLUGIN_TEST_PLATFORM", result.stderr)

    def test_governance_fast_path_requires_verified_allowlisted_changes(self):
        self.git("init")
        self.git("config", "user.name", "Stage 1 scope test")
        self.git("config", "user.email", "scope@example.invalid")
        self.write("AGENTS.md", "initial governance\n")
        self.write(
            "plugins/auto-research-agent/AGENTS.md", "initial plugin governance\n"
        )
        self.git("add", "AGENTS.md", "plugins/auto-research-agent/AGENTS.md")
        self.git("commit", "-m", "base")
        base = self.git("rev-parse", "HEAD")
        self.write("AGENTS.md", "updated governance\n")
        self.git("add", "AGENTS.md")
        self.git("commit", "-m", "governance edit")
        head = self.git("rev-parse", "HEAD")
        records = scope.changed_records(base, head, self.repo)
        allowed = scope.plan(
            ["AGENTS.md"], self.repo, records, event_name="pull_request"
        )
        self.assertEqual(allowed["mode"], "governance")
        self.assertEqual(allowed["modules"], list(scope.GOVERNANCE_MODULES))
        self.assertEqual(scope.plan(["AGENTS.md"], self.repo)["mode"], "full")
        self.assertNotEqual(
            scope.plan(["AGENTS.md"], self.repo, records, event_name="push")["mode"],
            "governance",
        )
        mixed = [
            records[0],
            {
                "status": "M",
                "old_mode": "100644",
                "new_mode": "100644",
                "old_path": "src/runtime.py",
                "new_path": "src/runtime.py",
            },
        ]
        selection = scope.plan(
            ["AGENTS.md", "src/runtime.py"],
            self.repo,
            mixed,
            event_name="pull_request",
        )
        self.assertEqual(selection["mode"], "full")

    def test_selector_or_workflow_changes_never_select_governance(self):
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
                self.assertEqual(
                    scope.plan([path], self.repo, [record], event_name="pull_request")[
                        "mode"
                    ],
                    "full",
                )

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

    def test_deleted_contracts_run_full_suite_and_expose_governance_failure(self):
        assets = "plugins/auto-research-agent/references/research-workspace/atlas/"
        for path in sorted(scope.DOCS | {assets + "atlas.css", "review-evidence/x.md"}):
            with self.subTest(path=path):
                self.write(path, "scope fixture\n").unlink()
                self.write(
                    TESTS + "test_governance_entrypoint.py",
                    PASSING.replace("pass", "self.fail('deleted contract')"),
                )
                selection = scope.plan([path], self.repo)
                self.assertEqual(
                    (selection["mode"], selection["modules"]), ("full", [])
                )
                executed = self.fixture(selection)
                self.assertNotEqual(
                    executed.returncode, 0, executed.stdout + executed.stderr
                )
                summary = json.loads(executed.stdout.splitlines()[-1])
                self.assertEqual((summary["tests_run"], summary["failures"]), (3, 1))
                self.assertFalse(summary["passed"])

    def test_deleted_ci_inputs_keep_full_suite(self):
        for path in sorted(scope.CI_FILES):
            with self.subTest(path=path):
                (self.repo / path).unlink()
                selection = scope.plan([path], self.repo)
                self.assertEqual(
                    (selection["mode"], selection["modules"]), ("full", [])
                )

    def test_incoming_presentation_scope_keeps_interface_checks(self):
        assets = "plugins/auto-research-agent/references/research-workspace/atlas/"
        self.write(assets + "atlas.css", "/* scope fixture */\n")
        self.write("review-evidence/x.md", "scope fixture\n")
        self.write(TESTS + "test_workspace_widget.py", PASSING)
        self.write(TESTS + "test_native_message_widget.py", PASSING)
        self.write(
            TESTS + "test_stage2_unrelated.py",
            PASSING.replace("pass", "self.fail('unrelated test must not run')"),
        )
        result = scope.plan([assets + "atlas.css", "review-evidence/x.md"], self.repo)
        self.assertEqual(result["mode"], "selected")
        self.assertEqual(
            result["modules"],
            [
                "test_native_message_widget",
                "test_plugin_loading",
                "test_stage_contracts",
                "test_workspace_widget",
            ],
        )
        executed = self.fixture(result)
        self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
        self.assertEqual(json.loads(executed.stdout.splitlines()[-1])["tests_run"], 4)
        self.write(assets + "atlas-ui.js", "// existing unclassified input\n")
        self.assertEqual(
            scope.plan([assets + "atlas.css", assets + "atlas-ui.js"], self.repo)[
                "mode"
            ],
            "full",
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
                if path != TESTS + "test_deleted.py":
                    self.write(path, "existing shared input\n")
                result = scope.plan(
                    [".github/pull_request_template.md", path], self.repo
                )
                self.assertEqual((result["mode"], result["modules"]), ("full", []))
                self.assertEqual(
                    result["reason"].startswith("Deleted or unavailable"),
                    path == TESTS + "test_deleted.py",
                )
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

    def test_parallel_full_suite_keeps_every_case_and_module_lifecycle(self):
        self.write(
            TESTS + "test_group.py",
            """import unittest
from pathlib import Path
class Group(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.completed = 0
  Path("lifecycle.txt").write_text("start\\n")
 @classmethod
 def tearDownClass(cls):
  assert cls.completed == 2
  with Path("lifecycle.txt").open("a") as stream: stream.write("end\\n")
 def test_first(self): type(self).completed += 1
 def test_second(self): type(self).completed += 1
""",
        )
        self.write(
            TESTS + "test_skip.py",
            PASSING.replace(
                "def test_ok", '@unittest.skip("existing skip")\n def test_ok'
            ),
        )
        result = self.fixture(workers=3)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(
            (summary["planned_tests"], summary["tests_run"], summary["skips"]),
            (5, 5, 1),
        )
        self.assertEqual(summary["incomplete_partitions"], 0)
        self.assertEqual((self.repo / "lifecycle.txt").read_text(), "start\nend\n")

    def test_balancing_preserves_duplicate_ids_and_intact_modules(self):
        ids = [f"test_{module}.T.test_{n}" for module in "abcd" for n in range(2)]
        ids.append(ids[0])
        with patch.object(
            scope,
            "MODULE_SECONDS",
            {"test_a": 100, "test_b": 80, "test_c": 20, "test_d": 10},
        ):
            groups = scope.partition_tests(ids, 2)
        self.assertEqual(
            scope.Counter(n for group in groups for n in group), scope.Counter(ids)
        )
        self.assertEqual({n.split(".")[0] for n in groups[0]}, {"test_a", "test_d"})
        self.assertEqual({n.split(".")[0] for n in groups[1]}, {"test_b", "test_c"})
        self.assertEqual(scope.partition_tests([], 3), [])

    def test_deadline_modules_run_after_workers_without_losing_cases(self):
        self.write(
            TESTS + "test_group.py",
            PASSING.replace(
                "pass",
                "__import__('pathlib').Path('worker-finished').write_text('done')",
            ),
        )
        for module in (
            "test_stage2_demo",
            "test_owned_source_observations",
            "test_portable_atlas_git_checkout",
            "test_project_model_reading",
            "test_project_resource_budget",
            "test_saved_source_parser_worker",
            "test_source_saved_pipeline",
            "test_stage_model_safety",
        ):
            self.write(
                TESTS + module + ".py",
                """import multiprocessing, unittest
from pathlib import Path
class Serial(unittest.TestCase):
 def test_after_workers(self):
  self.assertNotEqual(multiprocessing.current_process().name, 'MainProcess')
  self.assertEqual(Path('worker-finished').read_text(), 'done')
""",
            )
        # Synthetic cases cover the manual serial lane; automatic CI stays standard.
        result = self.fixture(workers=3, profile="full")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(
            (
                summary["planned_tests"],
                summary["tests_run"],
                summary["incomplete_partitions"],
            ),
            (11, 11, 0),
        )
        self.assertIn('"serial_tests": 8', result.stdout)

    def test_calibration_balances_heavy_modules_without_splitting_them(self):
        modules = (
            "test_project_expansions",
            "test_project_stage1_atlas",
            "test_project_reading_registration",
            "test_source_saved_pipeline",
            "test_project_stage1_records",
            "test_project_stage1_delivery",
        )
        ids = [f"{module}.T.test_{n}" for module in modules for n in range(2)]
        groups = scope.partition_tests(ids, 3)
        self.assertEqual(
            scope.Counter(name for group in groups for name in group),
            scope.Counter(ids),
        )
        self.assertEqual(
            {frozenset(name.split(".")[0] for name in group) for group in groups},
            {
                frozenset({"test_project_expansions", "test_project_stage1_delivery"}),
                frozenset({"test_project_stage1_atlas", "test_project_stage1_records"}),
                frozenset(
                    {"test_project_reading_registration", "test_source_saved_pipeline"}
                ),
            },
        )

    def test_source_mutating_fixtures_wait_for_capture_readers_and_each_other(self):
        self.write(
            TESTS + "test_stage2_review_pre_dispatch.py",
            """import os, unittest
from pathlib import Path
class CaptureReader(unittest.TestCase):
 def test_unchanged_tree(self):
  self.assertFalse(Path('evals/private/shared-fixture').exists())
  Path('capture-reader-finished').write_text(str(os.getpid()))
""",
        )
        for module in (
            "test_evaluation_plan",
            "test_judge_bundle",
            "test_paired_evaluation",
            "test_stage1_ab_contract_v2",
            "test_stage1_ab_execution",
        ):
            self.write(
                TESTS + module + ".py",
                """import os, unittest
from pathlib import Path
class SourceWriter(unittest.TestCase):
 def test_write_after_readers(self):
  self.assertTrue(Path('capture-reader-finished').is_file())
  shared = Path('evals/private/shared-fixture')
  shared.parent.mkdir(parents=True, exist_ok=True)
  with shared.open('x') as stream: stream.write('synthetic evidence')
  self.addCleanup(shared.unlink)
  with Path('writer-pids').open('a') as stream: stream.write(str(os.getpid()) + '\\n')
""",
            )
        result = self.fixture(workers=3)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(
            (summary["planned_tests"], summary["tests_run"], summary["skips"]),
            (8, 8, 0),
        )
        self.assertEqual(summary["incomplete_partitions"], 0)
        self.assertIn('"serial_tests": 5', result.stdout)
        writer_pids = (self.repo / "writer-pids").read_text().splitlines()
        self.assertEqual(len(writer_pids), 5)
        self.assertEqual(len(set(writer_pids)), 1)
        self.assertNotEqual(
            writer_pids[0], (self.repo / "capture-reader-finished").read_text()
        )
        self.assertFalse((self.repo / "evals/private/shared-fixture").exists())

    def test_serial_only_inventory_and_failure_remain_required(self):
        (self.repo / (TESTS + "test_plugin_loading.py")).unlink()
        (self.repo / (TESTS + "test_stage_contracts.py")).unlink()
        for source, code in (
            (PASSING, 0),
            (PASSING.replace("pass", "self.fail('serial failure')"), 1),
        ):
            with self.subTest(code=code):
                self.write(TESTS + "test_stage2_demo.py", source)
                result = self.fixture(workers=3)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                summary = json.loads(result.stdout.splitlines()[-1])
                self.assertEqual(
                    (summary["planned_tests"], summary["tests_run"]), (1, 1)
                )
                self.assertEqual(summary["passed"], code == 0)

    def test_serial_zero_exit_never_reports_success(self):
        self.write(
            TESTS + "test_stage2_demo.py",
            PASSING.replace("pass", "raise SystemExit(0)"),
        )
        result = self.fixture(workers=3)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual((summary["errors"], summary["incomplete_partitions"]), (1, 0))
        self.assertFalse(summary["passed"])

    def test_serial_process_exit_zero_is_incomplete(self):
        self.write(
            TESTS + "test_stage2_demo.py",
            PASSING.replace("pass", "__import__('os')._exit(0)"),
        )
        result = self.fixture(workers=3)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(summary["incomplete_partitions"], 1)
        self.assertLess(summary["tests_run"], summary["planned_tests"])
        self.assertFalse(summary["passed"])

    def test_parallel_full_suite_propagates_failures_import_errors_and_crashes(self):
        for source, marker in (
            (PASSING.replace("pass", "self.fail('parallel failure')"), '"failures": 1'),
            (
                "import nonexistent_parallel_dependency",
                "Full discovery contains import errors",
            ),
            (PASSING.replace("pass", "__import__('os')._exit(7)"), '"passed": false'),
        ):
            with self.subTest(marker=marker):
                self.write(TESTS + "test_broken.py", source)
                result = self.fixture(workers=3)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(marker, result.stdout + result.stderr)

    def test_parallel_worker_refuses_missing_selector_and_invalid_worker_count(self):
        sys.path.insert(0, str(self.repo / scope.TEST_DIR))
        self.addCleanup(sys.path.remove, str(self.repo / scope.TEST_DIR))
        with self.assertRaisesRegex(ValueError, "Worker test inventory"):
            scope.run_partition(
                ["test_plugin_loading.T.test_missing"], self.repo / scope.TEST_DIR
            )
        for workers in (0, 4):
            result = self.fixture(workers=workers)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("between one and three", result.stderr)

    def test_parallel_worker_system_exit_zero_never_reports_success(self):
        self.write(
            TESTS + "test_worker_exit.py",
            "import multiprocessing\n"
            "if multiprocessing.current_process().name != 'MainProcess':\n"
            " raise SystemExit(0)\n" + PASSING,
        )
        result = self.fixture(workers=3)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(summary["incomplete_partitions"], 1)
        self.assertFalse(summary["passed"])

    def test_workflow_preserves_required_matrix_and_runner_steps(self):
        workflow = (REPO / ".github/workflows/stage1-plugin.yml").read_text("utf-8")
        entry = "python .github/scripts/stage1_test_scope.py"
        self.assertIn("  contracts:\n", workflow)
        self.assertIn("os: [ubuntu-latest, windows-latest, macos-latest]", workflow)
        self.assertIn("runs-on: ${{ matrix.os }}", workflow)
        self.assertEqual(
            workflow.count("fetch-depth: 0"), workflow.count("uses: actions/checkout@")
        )
        self.assertEqual(workflow.count(entry), 3)
        self.assertIn(entry + " --contracts", workflow)
        self.assertIn(entry + " --governance", workflow)


if __name__ == "__main__":
    unittest.main()

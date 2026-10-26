"""Behavioral checks for versioned routes and the existing public CI runner."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import ci_test_routing as routing
import stage1_test_scope as scope


REPO = Path(__file__).resolve().parents[2]
PASSING = "import unittest\nclass T(unittest.TestCase):\n def test_ok(self): pass\n"


class RoutingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name).resolve()
        self.owner = "plugins/auto-research-agent/cli/stage2_workflow/decision_cards.py"
        self.write(self.owner, "# pure projection fixture\n")
        for name in [
            "test_plugin_loading",
            "test_stage_contracts",
            "test_stage2_projection",
        ]:
            self.write(f"{routing.TEST_DIRECTORY}/{name}.py", PASSING)
        self.table = {
            "schema_version": 1,
            "routes": [
                {
                    "id": "stage2-presentation",
                    "owners": [self.owner],
                    "test_patterns": ["test_stage2_*.py"],
                }
            ],
        }
        self.catalog()

    def write(self, path, text):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf8")
        return target

    def catalog(self):
        return self.write(routing.CATALOG_PATH, json.dumps(self.table))

    def record(self, path):
        return {
            "status": "M",
            "old_path": path,
            "new_path": path,
            "old_mode": "100644",
            "new_mode": "100644",
            "old_sha": "1" * 40,
            "new_sha": "2" * 40,
        }

    def plan(self, paths=None, records=None, event="pull_request"):
        return scope.plan(
            paths or [self.owner],
            self.repo,
            records=records if records is not None else [self.record(self.owner)],
            event_name=event,
        )

    def test_public_plan_routes_regular_projection_edit(self):
        result = self.plan()
        self.assertEqual(result["mode"], "selected")
        self.assertIn("test_stage2_projection", result["modules"])
        self.assertEqual(result["ci_routes"], ["stage2-presentation"])
        self.assertEqual(len(result["routing_catalog_sha256"]), 64)
        self.assertEqual(self.plan(event="push")["modules"], result["modules"])

    def test_two_routes_union_with_changed_tests_and_transitive_consumers(self):
        other = self.owner.replace("decision_cards.py", "decision_card_views.py")
        self.write(other, "# second pure projection\n")
        self.write(f"{routing.TEST_DIRECTORY}/test_stage3_pane.py", PASSING)
        self.write(
            f"{routing.TEST_DIRECTORY}/test_consumer.py",
            "import test_stage2_projection\n" + PASSING,
        )
        self.table["routes"].append(
            {
                "id": "stage3-presentation",
                "owners": [other],
                "test_patterns": ["test_stage3_*.py"],
            }
        )
        self.catalog()
        result = self.plan(
            [self.owner, other], [self.record(self.owner), self.record(other)]
        )
        self.assertEqual(
            result["ci_routes"], ["stage2-presentation", "stage3-presentation"]
        )
        self.assertIn("test_stage3_pane", result["modules"])
        self.assertIn("test_consumer", result["modules"])
        self.assertEqual(len(result["modules"]), len(set(result["modules"])))

    def test_unknown_shared_or_mixed_source_never_uses_a_partial_route(self):
        for path in [
            "plugins/auto-research-agent/cli/stage2_workflow/store.py",
            "plugins/auto-research-agent/cli/research_workspace_native/project_host.py",
            "plugins/auto-research-agent/requirements-test.txt",
            "unknown.py",
        ]:
            with self.subTest(path=path):
                self.write(path, "# shared fixture\n")
                self.assertEqual(self.plan([self.owner, path])["mode"], "full")
        self.assertEqual(scope.plan([self.owner], self.repo)["mode"], "full")

    def test_every_routing_owner_change_keeps_the_broad_standard_gate(self):
        for path in routing.ROUTING_FILES | {
            ".github/scripts/stage1_test_scope.py",
            ".github/scripts/ci_scope.py",
            ".github/workflows/stage1-plugin.yml",
        }:
            with self.subTest(path=path):
                self.assertEqual(self.plan([path])["mode"], "full")

    def test_rename_delete_add_mode_change_or_ambiguous_record_stays_broad(self):
        variants = [{"status": value} for value in ["A", "D", "R", "C", "T"]]
        variants += [
            {"old_path": "old.py"},
            {"old_mode": "120000"},
            {"new_mode": "100755"},
            {"old_sha": "bad"},
            {"new_sha": "1" * 40},
        ]
        for delta in variants:
            with self.subTest(delta=delta):
                row = {**self.record(self.owner), **delta}
                self.assertEqual(self.plan(records=[row])["mode"], "full")
        row = self.record(self.owner)
        self.assertEqual(self.plan(records=[row, row])["mode"], "full")
        (self.repo / self.owner).unlink()
        self.assertEqual(self.plan()["mode"], "full")

    def test_absent_catalog_cannot_enable_a_narrow_route(self):
        (self.repo / routing.CATALOG_PATH).unlink()
        self.assertEqual(self.plan()["mode"], "full")

    def test_closed_schema_and_duplicate_json_fields_are_rejected(self):
        for raw in [
            "{}",
            "[]",
            '{"schema_version":true,"routes":[]}',
            '{"schema_version":1,"routes":[],"extra":1}',
            '{"schema_version":1,"schema_version":1,"routes":[]}',
        ]:
            with self.subTest(raw=raw):
                self.write(routing.CATALOG_PATH, raw)
                with self.assertRaises(ValueError):
                    self.plan()

    def test_unsafe_duplicate_owners_and_patterns_are_rejected(self):
        original = json.loads(json.dumps(self.table))
        cases = [
            ("owners", ["../escape.py"]),
            ("owners", ["/absolute.py"]),
            ("owners", ["plugins/auto-research-agent/cli/../escape.py"]),
            ("owners", [self.owner, self.owner]),
            ("test_patterns", ["../test_escape.py"]),
            ("test_patterns", []),
            ("test_patterns", ["test_*.py", "test_*.py"]),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.table = json.loads(json.dumps(original))
                self.table["routes"][0][key] = value
                self.catalog()
                with self.assertRaises(ValueError):
                    self.plan()
        self.table = original
        self.table["routes"].append(dict(self.table["routes"][0]))
        self.catalog()
        with self.assertRaises(ValueError):
            self.plan()

    def test_missing_declared_selector_is_an_error_not_a_smoke_pass(self):
        self.table["routes"][0]["test_patterns"] = ["test_missing_*.py"]
        self.catalog()
        with self.assertRaisesRegex(ValueError, "no tests"):
            self.plan()

    def test_actual_repository_catalog_has_real_owners_and_nonempty_suites(self):
        catalog = routing.load_catalog(REPO)
        self.assertTrue(
            {
                "stage2-workflow-backend",
                "stage2-live-backend",
                "stage3-planning-backend",
            }
            <= {row["id"] for row in catalog["routes"]}
        )
        for route in catalog["routes"]:
            for owner in route["owners"]:
                self.assertTrue((REPO / owner).is_file(), owner)
                selected = routing.routed_modules(owner, REPO, [self.record(owner)])
                self.assertTrue(selected["modules"], owner)
        for path in [
            "cli/research_workspace_native/project_host.py",
            "cli/research_workspace_native/store.py",
            "cli/stage2_live/native.py",
            "cli/stage2_live/native_policy.py",
            "cli/stage2_live/native_process.py",
        ]:
            self.assertIsNone(
                routing.routed_modules(
                    "plugins/auto-research-agent/" + path,
                    REPO,
                    [self.record("plugins/auto-research-agent/" + path)],
                )
            )

    def test_public_runner_excludes_unrelated_failure_and_propagates_selected_failure(
        self,
    ):
        self.write(
            f"{routing.TEST_DIRECTORY}/test_unrelated.py",
            PASSING.replace("pass", "self.fail('unrelated')"),
        )
        selection = self.plan()
        command = [
            sys.executable,
            "-B",
            "-c",
            "import json,sys,stage1_test_scope as s; sys.exit(s.run_suite(json.loads(sys.argv[1]),repo=__import__('pathlib').Path(sys.argv[2]),workers=3))",
            json.dumps(selection),
            str(self.repo),
        ]
        env = {
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(REPO / ".github/scripts"),
        }

        def invoke():
            return subprocess.run(
                command,
                cwd=self.repo,
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )

        green = invoke()
        self.assertEqual(green.returncode, 0, green.stdout + green.stderr)
        summary = json.loads(green.stdout.splitlines()[-1])
        self.assertEqual(summary["tests_run"], 3)
        self.assertEqual(summary["planned_tests"], 3)
        self.assertEqual(summary["incomplete_partitions"], 0)
        self.write(
            f"{routing.TEST_DIRECTORY}/test_stage2_projection.py",
            PASSING.replace("pass", "self.fail('selected')"),
        )
        red = invoke()
        self.assertNotEqual(red.returncode, 0)
        self.assertFalse(json.loads(red.stdout.splitlines()[-1])["passed"])

    def test_registered_routing_checks_are_always_in_contract_inventory(self):
        self.assertIn("test_ci_test_routing", scope.CONTRACT_MODULES)
        self.write(
            f"{routing.TEST_DIRECTORY}/test_empty_ci_route.py", "# no test cases\n"
        )
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "empty"):
                scope.run_suite(
                    {"mode": "selected", "modules": ["test_empty_ci_route"]},
                    repo=self.repo,
                )

    def test_stage_owned_backends_exclude_unrelated_stage1_suites(self):
        cases = [
            "cli/stage2_workflow/store.py",
            "cli/stage2_workflow/orchestration.py",
            "cli/stage2_live/controller.py",
            "cli/stage3_plan/campaign.py",
            "cli/stage3_plan/jobs.py",
            "cli/research_workspace_native/project_stage2_selection.py",
        ]
        for owner in cases:
            path = "plugins/auto-research-agent/" + owner
            with self.subTest(owner=owner):
                selected = scope.plan([path], REPO, records=[self.record(path)])
                self.assertEqual(selected["mode"], "selected", selected)
                self.assertIn("test_plugin_loading", selected["modules"])
                self.assertIn("test_stage_contracts", selected["modules"])
                self.assertNotIn("test_retrieval_execution", selected["modules"])
                self.assertNotIn("test_stage1_deliverable", selected["modules"])
                self.assertNotIn("test_project_stage1_library", selected["modules"])

    def test_backend_routes_keep_bridge_and_provider_consumers(self):
        cases = {
            "cli/research_workspace_native/project_stage2.py": {
                "test_project_stage1_discovery_records",
                "test_stage1_core_records",
                "test_stage1_screening_records",
            },
            "cli/stage2_workflow/import_stage1.py": {
                "test_stage1_stage2_handoff",
                "test_saved_source_stage2_intake",
                "test_stage1_import_host_replay",
                "test_project_stage1_discovery_records",
                "test_stage1_core_records",
                "test_stage1_screening_records",
            },
            "cli/stage2_workflow/store.py": {"test_stage_pipeline_prompt_bounds"},
            "cli/stage3_plan/native.py": {
                "test_native_incomplete_responses",
                "test_provider_schema_projection",
            },
            "cli/stage3_plan/intake.py": {
                "test_stage123_imported_selection_recovery_e2e",
                "test_project_stage2_selection_http",
            },
        }
        for owner, required in cases.items():
            path = "plugins/auto-research-agent/" + owner
            with self.subTest(owner=owner):
                selected = scope.plan([path], REPO, records=[self.record(path)])
                self.assertEqual(selected["mode"], "selected")
                self.assertTrue(required <= set(selected["modules"]))

    def test_backend_route_union_and_modified_shared_fallback(self):
        a = "plugins/auto-research-agent/cli/stage2_live/controller.py"
        b = "plugins/auto-research-agent/cli/stage3_plan/campaign.py"
        one = scope.plan([a], REPO, records=[self.record(a)])
        two = scope.plan([b], REPO, records=[self.record(b)])
        both = scope.plan([a, b], REPO, records=[self.record(a), self.record(b)])
        self.assertEqual(both["mode"], "selected")
        self.assertEqual(
            set(both["modules"]), set(one["modules"]) | set(two["modules"])
        )
        for shared in [
            "cli/stage2_live/native.py",
            "cli/stage2_live/native_policy.py",
            "cli/stage2_live/trace_files.py",
            "cli/stage1_eval/model_calls.py",
            "cli/research_workspace_native/project_host.py",
        ]:
            path = "plugins/auto-research-agent/" + shared
            with self.subTest(shared=shared):
                selected = scope.plan(
                    [a, path], REPO, records=[self.record(a), self.record(path)]
                )
                self.assertEqual(selected["mode"], "full")

    def test_stage3_source_inventory_changes_reject_before_worker_execution(self):
        # Explicit partial fixture: the baseline reaches the later loader guard.
        # This exercises byte/inventory rejection only, never a worker or model.
        guard = r"""
import json, pathlib, sys, tempfile
sys.path.insert(0, sys.argv[1])
from research_workspace_native.source_worker_runner import ContainedSourceJobRunner
from stage1_deliverable.common import canonical, sha
with tempfile.TemporaryDirectory() as temporary:
    repo = pathlib.Path(temporary).resolve()
    cli = repo / 'plugins/auto-research-agent/cli'
    source = cli / 'stage3_plan/prompts.py'
    source.parent.mkdir(parents=True)
    source.write_text('VALUE = 1\n', encoding='utf8')
    files = {'cli/stage3_plan/prompts.py': sha(source.read_bytes())}
    inventory = sha(canonical(files))
    config = dict(kind='OwnedSourceWorkerConfiguration', schema_version='1.0.0',
        repo=str(repo), files=files, inventory_sha256=inventory,
        interpreter=sys.executable, interpreter_sha256='1'*64,
        git_executable=str(repo/'git.exe'), git_sha256='2'*64,
        execution_source_sha256=inventory, runtime_sha256='3'*64,
        resolver_sha256='4'*64, materials_root=str(repo/'materials'),
        cleanup_reserve_seconds=1, guard_timeout_seconds=1,
        max_stdout_bytes=1024, max_stderr_bytes=1024, max_frames=1)
    runner = ContainedSourceJobRunner(config)
    def rejection():
        try:
            runner._pins()
        except ValueError as error:
            return str(error)
        raise AssertionError('partial fixture must not admit a worker')
    observed = {'baseline': rejection()}
    source.write_text('VALUE = 2\n', encoding='utf8')
    observed['modified'] = rejection()
    source.write_text('VALUE = 1\n', encoding='utf8')
    (source.parent/'new_module.py').write_text('VALUE = 3\n', encoding='utf8')
    observed['added'] = rejection()
    print(json.dumps(observed))
"""
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                guard,
                str(REPO / "plugins/auto-research-agent/cli"),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "baseline": "source-worker-required-module-missing",
                "modified": "source-worker-inventory-bytes-differ",
                "added": "source-worker-complete-source-required",
            },
        )


if __name__ == "__main__":
    unittest.main()

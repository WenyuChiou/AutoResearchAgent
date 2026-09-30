"""Independent admission and subprocess ownership regressions; synthetic only."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from unittest.mock import patch

import test_stage1_output_scheduler as fixtures


scheduler = fixtures.scheduler


class SchedulerAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.Stage1OutputSchedulerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def live_fixture(self, name):
        plan = self.fixture.fixture(name, count=1)
        job = plan["jobs"][0]
        base = Path(plan["control_root"]).parent
        generation = base / "legacy"
        generation.mkdir()
        (generation / "evaluations").mkdir()
        job["output"] = str(generation / "evaluations" / job["id"])
        plan["evidence_scope"] = "repair-diagnostic"
        plan["legacy"] = {"generation": str(generation), "fenced_target": job["id"]}
        codex = base / "synthetic-codex.exe"
        guard = Path(scheduler.__file__).with_name("offline_replay.py")
        codex.write_bytes(b"synthetic executable; never launched")
        plan["runtime"] = {
            "python_executable": sys.executable,
            "cli_root": str(fixtures.PLUGIN / "cli"),
            "codex_executable": str(codex),
            "replay_guard": str(guard),
        }
        inputs = {}
        for key in ("task", "spec", "lock", "background"):
            path = base / (key + ".json")
            path.write_text("{}", encoding="utf-8")
            inputs[key] = str(path)
        inputs["subject"] = str(Path(job["capture_root"]) / "answer.txt")
        job["inputs"] = inputs
        config = base / "research-hub.json"
        fixtures.write_json(
            config,
            {
                "knowledge_base": {"root": job["cache"]},
                "no_zotero": True,
                "disable_pdf_fallback": True,
            },
        )
        job["hub_config"] = str(config)
        profile_config = Path(job["profile"]) / "config.toml"
        profile_config.write_text(
            'model="gpt-5.6-sol"\nmodel_reasoning_effort="high"\n'
            'approval_policy="never"\ncli_auth_credentials_store="file"\n',
            encoding="utf-8",
        )
        for path in [
            codex,
            config,
            profile_config,
            *inputs.values(),
            *Path(scheduler.__file__).parent.glob("*.py"),
        ]:
            plan["bindings"].append({"path": str(path), "sha256": fixtures.sha(path)})
        job["env"] = {
            "PYTHONPATH": plan["runtime"]["cli_root"],
            "RESEARCH_HUB_CONFIG": str(config),
            "RESEARCH_HUB_ALLOW_EXTERNAL_ROOT": "1",
        }
        job["evaluate"], job["replay"] = scheduler.live_commands(plan, job)
        return plan

    def validate(self, plan):
        # Syntax/admission validation only: never import or invoke a real evaluator.
        return scheduler.validate_amendment(plan, "a" * 64)

    def test_fixed_live_command_contract_accepts_bound_synthetic_inputs(self):
        self.validate(self.live_fixture("valid"))

    def test_wrong_actual_profile_capture_output_model_and_guard_are_rejected(self):
        for field in ("profile", "capture", "output", "model", "guard", "extra-argv"):
            with self.subTest(field=field):
                plan = self.live_fixture("argv-" + field)
                job = plan["jobs"][0]
                if field == "guard":
                    index = job["replay"].index(plan["runtime"]["replay_guard"])
                    job["replay"][index] = str(self.fixture.worker)
                elif field == "extra-argv":
                    job["evaluate"].append("--replay-only")
                elif field == "output":
                    job["evaluate"][job["evaluate"].index(job["output"])] += "-other"
                else:
                    option = {
                        "profile": "--evaluator-home",
                        "capture": "--capture",
                        "model": "--model",
                    }[field]
                    index = job["evaluate"].index(option) + 1
                    job["evaluate"][index] += "-other"
                with self.assertRaises(scheduler.SchedulerError):
                    self.validate(plan)

    def test_unbound_runtime_or_configuration_cannot_enter_live_contract(self):
        for field in (
            "codex_executable",
            "replay_guard",
            "hub_config",
            "profile_config",
        ):
            with self.subTest(field=field):
                plan = self.live_fixture("unbound-" + field)
                job = plan["jobs"][0]
                value = (
                    str(Path(job["profile"]) / "config.toml")
                    if field == "profile_config"
                    else job[field]
                    if field == "hub_config"
                    else plan["runtime"][field]
                )
                plan["bindings"] = [
                    binding
                    for binding in plan["bindings"]
                    if Path(binding["path"]).resolve() != Path(value).resolve()
                ]
                with self.assertRaises(scheduler.SchedulerError):
                    self.validate(plan)

    def test_shared_actual_cache_or_changed_source_policy_is_rejected(self):
        for field in ("root", "no_zotero", "disable_pdf_fallback"):
            with self.subTest(field=field):
                plan = self.live_fixture("config-" + field)
                job = plan["jobs"][0]
                config = json.loads(Path(job["hub_config"]).read_text())
                if field == "root":
                    config["knowledge_base"]["root"] = str(
                        self.fixture.root / "shared-cache"
                    )
                else:
                    config[field] = False
                fixtures.write_json(job["hub_config"], config)
                with self.assertRaises(scheduler.SchedulerError):
                    self.validate(plan)

    def test_different_bound_guard_cannot_masquerade_as_reviewed_replay(self):
        plan = self.live_fixture("different-guard")
        guard = self.fixture.root / "different-guard.py"
        guard.write_text("# Synthetic impostor; never executed\n", encoding="utf-8")
        plan["runtime"]["replay_guard"] = str(guard)
        plan["bindings"].append({"path": str(guard), "sha256": fixtures.sha(guard)})
        job = plan["jobs"][0]
        job["evaluate"], job["replay"] = scheduler.live_commands(plan, job)
        with self.assertRaises(scheduler.SchedulerError):
            self.validate(plan)

    def test_modified_profile_settings_are_rejected(self):
        for key, value in (
            ("model_reasoning_effort", "low"),
            ("approval_policy", "untrusted"),
            ("cli_auth_credentials_store", "keyring"),
            ("unexpected_setting", "enabled"),
        ):
            with self.subTest(key=key):
                plan = self.live_fixture("profile-" + key)
                path = Path(plan["jobs"][0]["profile"]) / "config.toml"
                text = path.read_text(encoding="utf-8")
                lines = [
                    line for line in text.splitlines() if not line.startswith(key + "=")
                ]
                lines.append(f'{key}="{value}"')
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                with self.assertRaises(scheduler.SchedulerError):
                    self.validate(plan)

    def test_child_environment_and_import_root_cannot_diverge(self):
        for field in (
            "PYTHONPATH",
            "PYTHONHOME",
            "RESEARCH_HUB_CONFIG",
            "cli_root",
            "python_executable",
        ):
            with self.subTest(field=field):
                plan = self.live_fixture("env-" + field)
                if field in ("cli_root", "python_executable"):
                    plan["runtime"][field] = str(
                        self.fixture.root / "different-runtime"
                    )
                else:
                    plan["jobs"][0]["env"][field] = str(
                        self.fixture.root / "different-root"
                    )
                with self.assertRaises(scheduler.SchedulerError):
                    self.validate(plan)

    def test_relocated_output_is_rejected_even_with_matching_rebuilt_argv(self):
        plan = self.live_fixture("relocated")
        job = plan["jobs"][0]
        job["output"] = str(self.fixture.root / "new-output")
        job["evaluate"], job["replay"] = scheduler.live_commands(plan, job)
        with self.assertRaises(scheduler.SchedulerError):
            self.validate(plan)

    def frozen_binding_fixture(self, name):
        plan = self.live_fixture(name)
        runtime = plan["runtime"]
        runtime.update(
            evaluator_bundle_sha256="b" * 64,
            execution_policy={"synthetic_policy": 1},
            research_hub_package_sha256="c" * 64,
        )
        root = Path(plan["legacy"]["generation"])
        fixtures.write_json(
            root / "capture-inventory.json",
            {job["id"]: job["capture_manifest"] for job in plan["jobs"]},
        )
        original = {
            key: copy.deepcopy(runtime[key])
            for key in (
                "evaluator_bundle_sha256",
                "execution_policy",
                "research_hub_package_sha256",
            )
        }
        original.update(
            codex_executable_sha256=fixtures.sha(runtime["codex_executable"]),
            python_executable_sha256=fixtures.sha(runtime["python_executable"]),
            capture_inventory_sha256=fixtures.sha(root / "capture-inventory.json"),
        )
        fixtures.write_json(root / "plan.json", original)
        plan["legacy"]["plan_sha256"] = fixtures.sha(root / "plan.json")
        return plan

    def verify_mocked_runtime(self, plan):
        # Only the read-only runtime identity helpers are mocked. File hashes and
        # old-versus-successor contracts use the real verification code.
        runtime = plan["runtime"]
        with ExitStack() as stack:
            for target, value in (
                (
                    "stage1_eval.pipeline_v31.bundle_sha_v31",
                    runtime["evaluator_bundle_sha256"],
                ),
                (
                    "stage1_eval.pipeline_v31.execution_policy",
                    runtime["execution_policy"],
                ),
                (
                    "stage1_eval.runtime.installed_package_sha256",
                    runtime["research_hub_package_sha256"],
                ),
            ):
                stack.enter_context(patch(target, return_value=value))
            stack.enter_context(
                patch.object(
                    scheduler.subprocess,
                    "Popen",
                    side_effect=AssertionError("No external calls allowed"),
                )
            )
            scheduler.verify_bindings(plan)

    def test_original_capture_manifest_blocks_target_substitution(self):
        plan = self.frozen_binding_fixture("capture-substitution")
        self.verify_mocked_runtime(plan)
        plan["jobs"][0]["capture_manifest"] = {"answer.txt": "f" * 64}
        with self.assertRaisesRegex(scheduler.SchedulerError, "target/capture"):
            self.verify_mocked_runtime(plan)

    def test_current_runtime_cannot_redefine_original_frozen_contract(self):
        for key in (
            "evaluator_bundle_sha256",
            "execution_policy",
            "research_hub_package_sha256",
        ):
            with self.subTest(key=key):
                plan = self.frozen_binding_fixture("old-runtime-" + key)
                plan["runtime"][key] = (
                    {"synthetic_policy": 2} if key == "execution_policy" else "f" * 64
                )
                with self.assertRaisesRegex(
                    scheduler.SchedulerError, "frozen evaluator"
                ):
                    self.verify_mocked_runtime(plan)

    def test_original_capture_inventory_bytes_must_match_old_plan(self):
        plan = self.frozen_binding_fixture("inventory-bytes")
        root = Path(plan["legacy"]["generation"])
        fixtures.write_json(root / "capture-inventory.json", {})
        with self.assertRaisesRegex(
            scheduler.SchedulerError, "original capture inventory"
        ):
            self.verify_mocked_runtime(plan)

    def test_prior_replay_requires_actual_successful_zero_call_receipt(self):
        good = {
            "offline_guard": True,
            "blocked_actions": [],
            "new_model_calls": 0,
            "exit_code": 0,
        }
        for variant in ("valid", "missing", "blocked", "new-calls", "failed"):
            with self.subTest(variant=variant):
                plan = self.fixture.legacy_fixture("prior-replay-" + variant)
                legacy = plan["legacy"]
                root = Path(legacy["generation"])
                legacy["processes"][0]["command_line"] = legacy["runner_script"]
                for pid, parent in ((73100, 73099), (73102, 73101)):
                    legacy["processes"].append(
                        {
                            "pid": pid,
                            "parent_pid": parent,
                            "created_utc": "2026-01-01T00:00:00Z",
                            "executable": sys.executable,
                            "command_line": "synthetic",
                        }
                    )
                legacy["expected_stderr"] = (
                    "stage1-eval: EvaluationError: v3.1 output exists; verified resume must be explicit\n"
                )
                legacy["expected_commands"] = {
                    key: ["synthetic", key]
                    for key in (
                        "previous-evaluate",
                        "previous-replay",
                        "job-0-evaluate",
                    )
                }
                fixtures.write_json(
                    root / "logs/previous-evaluate-start.json",
                    {"command": legacy["expected_commands"]["previous-evaluate"]},
                )
                self.fixture.reserve(plan)
                self.fixture.finish_legacy(plan)
                for key, command in legacy["expected_commands"].items():
                    fixtures.write_json(
                        root / "logs" / (key + "-start.json"), {"command": command}
                    )
                _, digest = self.fixture.save(plan)
                # Exercise the real handoff branch against synthetic preserved
                # receipts, without launching a scheduler or evaluator.
                plan["evidence_scope"] = "repair-diagnostic"
                receipt = dict(good)
                if variant == "blocked":
                    receipt["blocked_actions"] = ["socket.connect"]
                elif variant == "new-calls":
                    receipt["new_model_calls"] = 1
                elif variant == "failed":
                    receipt["exit_code"] = 2
                if variant != "missing":
                    fixtures.write_json(
                        root / "logs/previous-replay.stdout.txt", receipt
                    )
                if variant == "valid":
                    result = scheduler.verify_handoff(
                        plan, digest, process_inspector=lambda: []
                    )
                    self.assertTrue(result["intentional_orchestration_failure"])
                else:
                    with self.assertRaises(
                        (scheduler.SchedulerError, FileNotFoundError)
                    ):
                        scheduler.verify_handoff(
                            plan, digest, process_inspector=lambda: []
                        )

    def test_different_control_roots_cannot_launch_same_output_twice(self):
        plan = self.fixture.fixture("cross-control", count=1)
        other = copy.deepcopy(plan)
        other["control_root"] += "-second"
        paths = []
        for index, value in enumerate((plan, other)):
            path = self.fixture.root / f"cross-control-{index}.json"
            fixtures.write_json(path, value)
            paths.append((path, fixtures.sha(path)))
        admission = threading.Barrier(2)
        real_popen = subprocess.Popen
        processes = []
        process_lock = threading.Lock()

        def synchronized_handoff(*args, **kwargs):
            admission.wait(timeout=10)
            return {}

        def delayed_popen(argv, **kwargs):
            # Keep the output absent long enough to expose check-then-launch races.
            if "evaluate" in argv:
                time.sleep(0.2)
            child = real_popen(argv, **kwargs)
            with process_lock:
                processes.append((argv, child))
            return child

        def invoke(item):
            path, digest = item
            try:
                return scheduler.run(path, digest, approval_sha256=digest)
            except (scheduler.SchedulerError, FileExistsError):
                return "rejected"

        try:
            with (
                patch.object(scheduler, "verify_handoff", synchronized_handoff),
                patch.object(scheduler.subprocess, "Popen", delayed_popen),
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                list(pool.map(invoke, paths))
            self.assertEqual(sum("evaluate" in argv for argv, _ in processes), 1)
        finally:
            for _, child in processes:
                child.wait(timeout=10)

    def test_process_receipt_failure_drains_child_before_return(self):
        plan = self.fixture.fixture(
            "receipt-failure", count=2, max_jobs=1, delays={0: 0.2}
        )
        real_save = scheduler.save
        real_popen = subprocess.Popen
        processes = []

        def receipt_failure(path, value):
            if Path(path).name == "evaluate-process.json":
                raise OSError("synthetic receipt write failure")
            return real_save(path, value)

        def record_popen(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            processes.append(child)
            return child

        try:
            with (
                patch.object(scheduler, "save", receipt_failure),
                patch.object(scheduler.subprocess, "Popen", record_popen),
            ):
                result = self.fixture.run_plan(plan)
            self.assertTrue(processes)
            self.assertTrue(all(child.poll() is not None for child in processes))
            self.assertTrue(
                (Path(plan["jobs"][0]["output"]) / "finished.json").is_file()
            )
            self.assertFalse(Path(plan["jobs"][1]["output"]).exists())
            self.assertEqual(result["status"], "failed-preserved")
        finally:
            for child in processes:
                child.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()

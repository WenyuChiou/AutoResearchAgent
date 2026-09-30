"""Synthetic subprocess contracts; no live evaluator, model, or source calls."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))

from stage1_operator import scheduler  # noqa: E402


WORKER = r"""
import hashlib, json, os, pathlib, sys, time
phase, output, job, delay, failure, rendezvous = [a for a in sys.argv[1:] if a != '--resume-verified']
output = pathlib.Path(output)
if phase == 'replay':
    result = json.loads((output / 'result.json').read_text())
    assert result['job_id'] == job
    for role in ('r1', 'r2'):
        assert (output / role / 'evidence.txt').read_text() == job + ':' + role
    raise SystemExit(0)
output.mkdir(parents=True, exist_ok=True)
(output / 'started.json').write_text(json.dumps({'pid': os.getpid(), 'at': time.time()}))
if rendezvous != '-':
    deadline = time.monotonic() + 10
    while not pathlib.Path(rendezvous).exists():
        if time.monotonic() > deadline:
            raise SystemExit(23)
        time.sleep(.01)
time.sleep(float(delay))
for role in ('r1', 'r2'):
    directory = output / role
    directory.mkdir()
    (directory / 'evidence.txt').write_text(job + ':' + role)
keys = ('CODEX_HOME', 'RESEARCH_HUB_ROOT', 'TMP', 'TEMP', 'TMPDIR')
(output / 'environment.json').write_text(json.dumps({key: os.environ[key] for key in keys}))
for key in ('CODEX_HOME', 'RESEARCH_HUB_ROOT', 'TMP'):
    pathlib.Path(os.environ[key], 'synthetic-owner.txt').write_text(job)
(output / 'result.json').write_text(json.dumps({'job_id': job, 'roles': ['r1', 'r2']}))
(output / 'finished.json').write_text(json.dumps({'at': time.time(), 'failure': failure}))
raise SystemExit(int(failure))
"""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


class Stage1OutputSchedulerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="s1-scheduler-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.worker = self.root / "synthetic_worker.py"
        self.worker.write_text(WORKER, encoding="utf-8")

    def fixture(self, name="batch", *, count=3, max_jobs=2, delays=None, failures=None):
        base = self.root / name
        base.mkdir()
        jobs = []
        for index in range(count):
            job_id = f"job-{index}"
            home = base / job_id
            home.mkdir()
            capture = home / "capture"
            capture.mkdir()
            (capture / "answer.txt").write_text(
                "synthetic saved answer", encoding="utf-8"
            )
            output = home / "output"
            profile, cache, temp = (home / name for name in ("profile", "cache", "tmp"))
            for directory in (profile, cache, temp):
                directory.mkdir()
            delay = (delays or {}).get(index, 0.03)
            failure = (failures or {}).get(index, 0)
            tail = [str(output), job_id, str(delay), str(failure), "-"]
            jobs.append(
                {
                    "id": job_id,
                    "output": str(output),
                    "profile": str(profile),
                    "cache": str(cache),
                    "temp": str(temp),
                    "cwd": str(home),
                    "evaluate": [sys.executable, str(self.worker), "evaluate", *tail],
                    "replay": [sys.executable, str(self.worker), "replay", *tail],
                    "env": {
                        "CODEX_HOME": str(profile),
                        "RESEARCH_HUB_ROOT": str(cache),
                        "TMP": str(temp),
                        "TEMP": str(temp),
                        "TMPDIR": str(temp),
                    },
                    "capture_root": str(capture),
                    "capture_manifest": {"answer.txt": sha(capture / "answer.txt")},
                    "result": "result.json",
                }
            )
        return {
            "kind": "Stage1OutputSchedule.v1",
            "evidence_scope": "synthetic-test",
            "max_jobs": max_jobs,
            "control_root": str(base / "control"),
            "bindings": [
                {"path": str(self.worker), "sha256": sha(self.worker)},
                {"path": sys.executable, "sha256": sha(sys.executable)},
            ],
            "jobs": jobs,
            "legacy": None,
            "executor_sha256": sha(scheduler.__file__),
        }

    def save(self, plan):
        path = Path(plan["control_root"]).parent / "amendment.json"
        write_json(path, plan)
        return path, sha(path)

    def run_plan(self, plan):
        path, digest = self.save(plan)
        return scheduler.run(path, digest, approval_sha256=digest)

    def cli(self, plan):
        path, digest = self.save(plan)
        environment = dict(os.environ, PYTHONPATH=str(PLUGIN / "cli"))
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "stage1_operator",
                "run",
                str(path),
                "--sha256",
                digest,
                "--approved-sha256",
                digest,
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def wait_file(self, path, child=None):
        deadline = time.monotonic() + 10
        while not path.exists():
            if child is not None and child.poll() is not None:
                self.fail(f"scheduler exited before {path.name}: {child.communicate()}")
            if time.monotonic() >= deadline:
                self.fail(f"synthetic rendezvous timed out: {path}")
            time.sleep(0.01)

    def legacy_fixture(self, name="legacy"):
        plan = self.fixture(name, count=2)
        base = Path(plan["control_root"]).parent
        legacy = base / "legacy"
        (legacy / "logs").mkdir(parents=True)
        (legacy / "evaluations").mkdir()
        runner = legacy / "runner.py"
        runner.write_text("# Synthetic old runner bytes\n", encoding="utf-8")
        old = {
            "targets": ["previous", "job-0", "job-1"],
            "operator_script_sha256": sha(runner),
        }
        write_json(legacy / "plan.json", old)
        identities = [
            {
                "pid": 73101,
                "parent_pid": 73100,
                "created_utc": "2026-01-01T00:00:00Z",
                "executable": sys.executable,
            }
        ]
        plan["legacy"] = {
            "generation": str(legacy),
            "active_target": "previous",
            "fenced_target": "job-0",
            "runner_pid": 73101,
            "runner_script": str(runner),
            "runner_sha256": sha(runner),
            "plan_sha256": sha(legacy / "plan.json"),
            "processes": identities,
        }
        write_json(
            legacy / "batch-start.json",
            {"pid": 73101, "plan_sha256": sha(legacy / "plan.json")},
        )
        write_json(legacy / "logs/previous-evaluate-start.json", {"synthetic": True})
        job = plan["jobs"][0]
        job["output"] = str(legacy / "evaluations/job-0")
        job["evaluate"][3] = job["output"]
        job["replay"][3] = job["output"]
        job["evaluate"].append("--resume-verified")
        return plan

    def reserve(self, plan):
        path, digest = self.save(plan)
        return scheduler.reserve_fence(
            path,
            digest,
            approval_sha256=digest,
            process_inspector=lambda: plan["legacy"]["processes"],
        )

    def finish_legacy(self, plan, *, stderr_newline="\n"):
        legacy = Path(plan["legacy"]["generation"])
        for phase in ("evaluate", "replay"):
            write_json(
                legacy / f"logs/previous-{phase}.json",
                {
                    "target": "previous",
                    "phase": phase,
                    "exit_code": 0,
                    "capture_all_files_unchanged": True,
                    "replay_archive_unchanged": phase == "replay",
                },
            )
        write_json(legacy / "logs/job-0-evaluate-start.json", {"synthetic": True})
        write_json(
            legacy / "logs/job-0-evaluate.json",
            {
                "target": "job-0",
                "phase": "evaluate",
                "exit_code": 2,
                "capture_all_files_unchanged": True,
            },
        )
        (legacy / "logs/job-0-evaluate.stderr.txt").write_bytes(
            (
                "stage1-eval: EvaluationError: v3.1 output exists; verified resume must be explicit"
                + stderr_newline
            ).encode()
        )
        write_json(
            legacy / "batch-stop.json",
            {
                "status": "failed-preserved",
                "target": "job-0",
                "phase": "evaluate",
                "completed": ["previous"],
            },
        )

    def run_legacy(self, plan, processes=None):
        path, digest = self.save(plan)
        return scheduler.run(
            path,
            digest,
            approval_sha256=digest,
            process_inspector=lambda: processes or [],
        )

    def test_parallel_workers_have_isolated_paths_and_independent_roles(self):
        plan = self.fixture(count=2, delays={0: 0.15, 1: 0.15})
        for index, job in enumerate(plan["jobs"]):
            job["evaluate"][-1] = str(
                Path(plan["jobs"][1 - index]["output"]) / "started.json"
            )
        result = self.run_plan(plan)
        self.assertEqual(result["status"], "complete")
        spans = []
        for job in plan["jobs"]:
            output = Path(job["output"])
            environment = json.loads((output / "environment.json").read_text())
            self.assertEqual(environment, job["env"])
            for key in ("profile", "cache", "temp"):
                self.assertEqual(
                    (Path(job[key]) / "synthetic-owner.txt").read_text(), job["id"]
                )
            spans.append(
                (
                    json.loads((output / "started.json").read_text())["at"],
                    json.loads((output / "finished.json").read_text())["at"],
                )
            )
            self.assertEqual(
                (output / "r1/evidence.txt").read_text(), job["id"] + ":r1"
            )
            self.assertEqual(
                (output / "r2/evidence.txt").read_text(), job["id"] + ":r2"
            )
        self.assertLess(max(start for start, _ in spans), min(end for _, end in spans))

    def test_resume_no_reexecution_rejects_duplicate_coordinator(self):
        plan = self.fixture(count=1, delays={0: 0.5})
        child = self.cli(plan)
        try:
            output = Path(plan["jobs"][0]["output"])
            self.wait_file(output / "started.json", child)
            before = (output / "started.json").read_bytes()
            with self.assertRaises((scheduler.SchedulerError, FileExistsError)):
                self.run_plan(plan)
            stdout, stderr = child.communicate(timeout=15)
            self.assertEqual(child.returncode, 0, (stdout, stderr))
            self.assertEqual((output / "started.json").read_bytes(), before)
        finally:
            if child.poll() is None:
                child.communicate(timeout=15)

    def test_completed_or_stale_control_claim_is_never_silently_reclaimed(self):
        for mode in ("complete", "stale"):
            with self.subTest(mode=mode):
                plan = self.fixture(mode, count=1)
                if mode == "complete":
                    self.run_plan(plan)
                else:
                    Path(plan["control_root"]).mkdir()
                    write_json(
                        Path(plan["control_root"]) / "owner.json", {"pid": 99999999}
                    )
                with self.assertRaises((scheduler.SchedulerError, FileExistsError)):
                    self.run_plan(plan)
                if mode == "stale":
                    self.assertFalse(Path(plan["jobs"][0]["output"]).exists())

    def test_failure_stops_admission_and_preserves_other_inflight_worker(self):
        plan = self.fixture(count=3, delays={0: 0.1, 1: 0.3}, failures={0: 9})
        plan["jobs"][0]["evaluate"][-1] = str(
            Path(plan["jobs"][1]["output"]) / "started.json"
        )
        result = self.run_plan(plan)
        self.assertEqual(result["status"], "failed-preserved")
        self.assertEqual(
            [job["status"] for job in result["jobs"]],
            ["failed", "complete", "not-admitted"],
        )
        failed, draining, pending = (Path(job["output"]) for job in plan["jobs"])
        self.assertEqual(
            json.loads((failed / "finished.json").read_text())["failure"], "9"
        )
        self.assertTrue((draining / "finished.json").exists())
        self.assertFalse(pending.exists())

    def test_sequential_and_parallel_results_are_identical_in_target_order(self):
        values = []
        for cap in (1, 2):
            plan = self.fixture(f"cap-{cap}", max_jobs=cap, delays={0: 0.15, 1: 0.01})
            result = self.run_plan(plan)
            values.append(
                [
                    json.loads((Path(job["output"]) / "result.json").read_text())
                    for job in plan["jobs"]
                ]
            )
            self.assertIsInstance(result, dict)
            self.assertEqual(
                [job["id"] for job in result["jobs"]],
                [job["id"] for job in plan["jobs"]],
            )
            self.assertEqual(result["status"], "complete")
            spans = [
                (
                    json.loads((Path(job["output"]) / "started.json").read_text())[
                        "at"
                    ],
                    json.loads((Path(job["output"]) / "finished.json").read_text())[
                        "at"
                    ],
                )
                for job in plan["jobs"]
            ]
            peak = max(
                sum(start <= point < end for start, end in spans) for point, _ in spans
            )
            self.assertLessEqual(peak, cap)
        self.assertEqual(values[0], values[1])

    def test_runtime_bytes_bound_and_external_amendment_tampering_blocks_calls(self):
        for kind in ("amendment", "approval", "executor", "bound-file"):
            with self.subTest(kind=kind):
                plan = self.fixture(kind, count=1)
                if kind == "executor":
                    plan["executor_sha256"] = "0" * 64
                path, digest = self.save(plan)
                approval = digest
                if kind == "amendment":
                    plan["max_jobs"] = 1
                    write_json(path, plan)
                elif kind == "approval":
                    approval = "0" * 64
                elif kind == "bound-file":
                    self.worker.write_text(WORKER + "\n# changed\n", encoding="utf-8")
                with self.assertRaises(scheduler.SchedulerError):
                    scheduler.run(path, digest, approval_sha256=approval)
                self.assertFalse(Path(plan["jobs"][0]["output"]).exists())
                self.worker.write_text(WORKER, encoding="utf-8")

    def test_dependency_sha_bound_before_scheduler_execution(self):
        from stage1_eval.pipeline_v31 import bundle_sha_v31, execution_policy

        plan = self.legacy_fixture("dependency")
        plan["evidence_scope"] = "repair-diagnostic"
        plan["runtime"] = {
            "evaluator_bundle_sha256": bundle_sha_v31(),
            "execution_policy": execution_policy(),
            "research_hub_package_sha256": "a" * 64,
            "codex_executable": sys.executable,
            "python_executable": sys.executable,
        }
        legacy = Path(plan["legacy"]["generation"])
        capture_inventory = {job["id"]: job["capture_manifest"] for job in plan["jobs"]}
        write_json(legacy / "capture-inventory.json", capture_inventory)
        old = json.loads((legacy / "plan.json").read_text())
        old.update(
            evaluator_bundle_sha256=plan["runtime"]["evaluator_bundle_sha256"],
            execution_policy=plan["runtime"]["execution_policy"],
            research_hub_package_sha256="a" * 64,
            codex_executable_sha256=sha(sys.executable),
            python_executable_sha256=sha(sys.executable),
            capture_inventory_sha256=sha(legacy / "capture-inventory.json"),
        )
        write_json(legacy / "plan.json", old)
        plan["legacy"]["plan_sha256"] = sha(legacy / "plan.json")
        with patch(
            "stage1_eval.runtime.installed_package_sha256", return_value="a" * 64
        ):
            scheduler.verify_bindings(plan)
        with patch(
            "stage1_eval.runtime.installed_package_sha256", return_value="b" * 64
        ):
            with self.assertRaisesRegex(scheduler.SchedulerError, "dependency changed"):
                scheduler.verify_bindings(plan)
        self.assertFalse(Path(plan["jobs"][0]["output"]).exists())

    def test_shared_paths_duplicate_jobs_and_live_without_fence_are_rejected(self):
        for kind in ("profile", "cache", "temp", "output", "id", "live"):
            with self.subTest(kind=kind):
                plan = self.fixture("invalid-" + kind, count=2)
                if kind == "live":
                    plan["evidence_scope"] = "repair-diagnostic"
                else:
                    plan["jobs"][1][kind] = plan["jobs"][0][kind]
                with self.assertRaises(scheduler.SchedulerError):
                    self.run_plan(plan)
                self.assertFalse(Path(plan["jobs"][0]["output"]).exists())

    def test_earlier_capture_cannot_overlap_later_job_writable_directory(self):
        plan = self.fixture("capture-overlap", count=2)
        plan["jobs"][1]["cache"] = plan["jobs"][0]["capture_root"]
        with self.assertRaises(scheduler.SchedulerError):
            self.run_plan(plan)
        self.assertFalse(Path(plan["jobs"][0]["output"]).exists())

    def test_capture_bytes_mismatch_blocks_first_admission(self):
        plan = self.fixture(count=1)
        capture = Path(plan["jobs"][0]["capture_root"]) / "answer.txt"
        capture.write_text("changed synthetic capture", encoding="utf-8")
        result = self.run_plan(plan)
        self.assertEqual(result["status"], "failed-preserved")
        self.assertFalse(Path(plan["jobs"][0]["output"]).exists())

    def test_replay_mutation_is_preserved_as_failure_without_new_admission(self):
        plan = self.fixture(count=2, max_jobs=1)
        output = Path(plan["jobs"][0]["output"])
        plan["jobs"][0]["replay"] = [
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; "
            "Path(sys.argv[1], 'result.json').write_text('{}')",
            str(output),
        ]
        result = self.run_plan(plan)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "failed-preserved")
        self.assertEqual((output / "result.json").read_text(), "{}")
        self.assertFalse(Path(plan["jobs"][1]["output"]).exists())

    def test_rehashed_plan_cannot_raise_cap_beyond_two(self):
        for cap in (0, 3, True, "2"):
            with self.subTest(cap=cap):
                plan = self.fixture("cap-invalid-" + str(cap), count=1)
                plan["max_jobs"] = cap
                with self.assertRaises(scheduler.SchedulerError):
                    self.run_plan(plan)
                self.assertFalse(Path(plan["jobs"][0]["output"]).exists())

    def test_exact_fence_and_terminal_legacy_admit_successor_once(self):
        plan = self.legacy_fixture()
        self.reserve(plan)
        self.finish_legacy(plan)
        legacy = Path(plan["legacy"]["generation"])
        preserved = {path: path.read_bytes() for path in (legacy / "logs").glob("*")}
        result = self.run_legacy(plan)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["handoff"]["prior_completed"], ["previous"])
        self.assertTrue(result["handoff"]["intentional_orchestration_failure"])
        for path, raw in preserved.items():
            self.assertEqual(path.read_bytes(), raw)
        with self.assertRaises((scheduler.SchedulerError, FileExistsError)):
            self.run_legacy(plan)

    def test_live_parent_or_descendant_blocks_all_successor_calls(self):
        for live in ("parent", "child"):
            with self.subTest(live=live):
                plan = self.legacy_fixture(live)
                self.reserve(plan)
                self.finish_legacy(plan)
                processes = (
                    plan["legacy"]["processes"]
                    if live == "parent"
                    else [{"pid": 73102, "parent_pid": 73101}]
                )
                with self.assertRaises(scheduler.SchedulerError):
                    self.run_legacy(plan, processes)
                self.assertFalse(
                    (Path(plan["jobs"][0]["output"]) / "started.json").exists()
                )
                self.assertFalse(Path(plan["control_root"]).exists())

    def test_tampered_fence_and_true_prior_failure_never_become_handoff(self):
        for kind in (
            "marker",
            "extra-file",
            "prior-replay",
            "different-failure",
            "plan",
        ):
            with self.subTest(kind=kind):
                plan = self.legacy_fixture("broken-" + kind)
                self.reserve(plan)
                self.finish_legacy(plan)
                legacy = Path(plan["legacy"]["generation"])
                output = Path(plan["jobs"][0]["output"])
                if kind == "marker":
                    (output / "ownership-fence.json").write_text("{}")
                elif kind == "extra-file":
                    (output / "unexpected.json").write_text("{}")
                elif kind == "prior-replay":
                    path = legacy / "logs/previous-replay.json"
                    value = json.loads(path.read_text())
                    value["exit_code"] = 2
                    write_json(path, value)
                elif kind == "different-failure":
                    (legacy / "logs/job-0-evaluate.stderr.txt").write_text(
                        "unexpected failure\n"
                    )
                else:
                    (legacy / "plan.json").write_text("{}")
                with self.assertRaises(scheduler.SchedulerError):
                    self.run_legacy(plan)
                self.assertFalse((output / "started.json").exists())

    def test_fence_reservation_race_has_exactly_one_owner(self):
        plan = self.legacy_fixture("race")
        path, digest = self.save(plan)

        def reserve():
            try:
                scheduler.reserve_fence(
                    path,
                    digest,
                    approval_sha256=digest,
                    process_inspector=lambda: plan["legacy"]["processes"],
                )
                return "owner"
            except (scheduler.SchedulerError, FileExistsError):
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: reserve(), range(2)))
        self.assertEqual(sorted(results), ["owner", "rejected"])
        marker = Path(plan["jobs"][0]["output"]) / "ownership-fence.json"
        self.assertEqual(json.loads(marker.read_text())["amendment_sha256"], digest)

    def test_fence_newline_is_exactly_bound_for_windows_receipt(self):
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=repr(newline)):
                plan = self.legacy_fixture("newline-" + str(len(newline)))
                plan["legacy"]["expected_stderr"] = (
                    "stage1-eval: EvaluationError: v3.1 output exists; verified resume must be explicit"
                    + newline
                )
                self.reserve(plan)
                self.finish_legacy(plan, stderr_newline=newline)
                result = self.run_legacy(plan)
                self.assertEqual(result["status"], "complete")

    def test_unbound_process_identity_cannot_reserve_fence(self):
        for kind in ("empty", "wrong-runner", "missing-creation"):
            with self.subTest(kind=kind):
                plan = self.legacy_fixture("identity-" + kind)
                if kind == "empty":
                    plan["legacy"]["processes"] = []
                elif kind == "wrong-runner":
                    plan["legacy"]["processes"][0]["pid"] += 1
                else:
                    del plan["legacy"]["processes"][0]["created_utc"]
                with self.assertRaises(scheduler.SchedulerError):
                    self.reserve(plan)
                self.assertFalse(Path(plan["jobs"][0]["output"]).exists())


if __name__ == "__main__":
    unittest.main()

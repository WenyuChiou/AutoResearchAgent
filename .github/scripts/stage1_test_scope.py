"""Run affected tests with explicit accounting for manual-only long integration."""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from fnmatch import fnmatchcase
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import re
import sys
import traceback
import unittest

from ci_scope import (
    UI_TEST_PATTERNS,
    changed_paths_from_records,
    changed_records,
    governance_only,
    plugin_test_scope,
)


REPO = Path(__file__).resolve().parents[2]
TEST_DIR = Path("plugins/auto-research-agent/tests")
SMOKE = "test_plugin_loading"
BASE_MODULES = {SMOKE, "test_stage_contracts"}
# Scheduling estimates from Windows job 115763053921 at 304420f0.
# Rounded adjacent module-log windows can include setup/cleanup and buffering;
# they balance workers only and never select tests or alter any deadline.
MODULE_SECONDS = {
    "test_project_expansions": 745,
    "test_project_stage1_atlas": 650,
    "test_project_reading_registration": 595,
    "test_source_saved_pipeline": 485,
    "test_retrieval_execution": 470,
    "test_project_stage1_records": 415,
    "test_project_stage1_delivery": 310,
    "test_stage1_deliverable": 305,
    "test_stage1_core_records": 295,
    "test_project_reading_review": 260,
    "test_project_stage1_claims": 245,
    "test_research_workspace_source_availability": 240,
    "test_saved_source_parser_worker": 235,
    "test_coverage_gate": 215,
    "test_project_saved_claims": 210,
    "test_project_model_reading": 205,
    "test_project_source_reading_review": 205,
    "test_project_stage2_context": 165,
    "test_project_saved_record_owner": 150,
    "test_project_stage1_query_http": 150,
    "test_source_evidence": 140,
    "test_planned_queries": 130,
    "test_project_records_recovery": 130,
    "test_project_resource_budget": 130,
    "test_project_stage1_source_service": 125,
    "test_project_stage1_library": 120,
    "test_project_planned_query_contract": 115,
    "test_project_source_permit": 115,
    "test_atlas_review_example": 110,
    "test_project_query_history": 110,
    "test_project_source_dispatch": 110,
    "test_project_stage1_discovery_records": 100,
    "test_native_readable": 95,
    "test_plugin_loading": 95,
    "test_project_stage2_frontier": 95,
    "test_export_stop_fields": 90,
    "test_planned_query_http": 90,
    "test_project_stage1_coverage": 90,
    "test_project_atlas_screening": 85,
    "test_source_credentials": 85,
    "test_retrieval_audit": 81,
    "test_planned_query_contract": 63,
}
# Socket, subprocess and asynchronous-unit deadlines remain unchanged. Run these
# fixtures after worker exit so slow CI disk/CPU contention does not compete.
# Explicit long integration cases from the Windows module windows above.
# Automatic PR/main CI never runs these; full mode is explicitly manual.
SLOW_INTEGRATION_MODULES = {
    "test_project_expansions",
    "test_project_stage1_atlas",
    "test_project_reading_registration",
    "test_source_saved_pipeline",
    "test_retrieval_execution",
    "test_project_stage1_records",
    "test_project_stage1_delivery",
    "test_stage1_deliverable",
}

SERIAL_DEADLINE_MODULES = {
    "test_owned_source_observations",
    "test_portable_atlas_git_checkout",
    "test_stage2_demo",
    "test_stage2_demo_safety",
    "test_project_source_reading_http",
    "test_project_stage1_delivery_http",
    "test_project_model_reading",
    "test_project_resource_budget",
    "test_saved_source_parser_worker",
    "test_stage_model_safety",
}
# These legacy validator fixtures create temporary evidence below the plugin
# source root. Run them only after source-bound recovery/capture readers exit;
# their byte-identity guards must still reject any real concurrent tree change.
SERIAL_SOURCE_MUTATION_MODULES = {
    "test_evaluation_plan",
    "test_judge_bundle",
    "test_paired_evaluation",
    "test_stage1_ab_contract_v2",
    "test_stage1_ab_execution",
}
DOCS = {
    "plugins/auto-research-agent/README.md",
    "plugins/auto-research-agent/CONTRIBUTING.md",
    "plugins/auto-research-agent/references/research-workspace/PORTABLE_ATLAS_SETUP.md",
    ".github/pull_request_template.md",
}
CI_FILES = {
    ".github/workflows/stage1-plugin.yml",
    ".github/workflows/research-pr-metadata.yml",
    ".github/workflows/blocking-ci.yml",
    ".github/scripts/ci_scope.py",
    ".github/scripts/test_ci_scope.py",
    ".github/scripts/stage1_test_scope.py",
    ".github/scripts/test_stage1_test_scope.py",
    ".github/scripts/test_stage1_ci_quality.py",
}
SELF_REFERENTIAL_CI_FILES = {
    ".github/scripts/ci_scope.py",
    ".github/scripts/stage1_test_scope.py",
    ".github/workflows/stage1-plugin.yml",
}
CONTRACT_MODULES = (
    "test_ci_scope",
    "test_stage1_test_scope",
    "test_validate_research_pr",
    "test_check_research_pr_dependencies",
    "test_stage1_ci_quality",
)
GOVERNANCE_MODULES = (
    "test_ci_scope",
    "test_stage1_test_scope",
    "test_validate_research_pr",
)


def plan(paths, repo=REPO, records=None, event_name=None):
    """Only standalone test edits and explicitly named CI/docs use selection."""
    full = {"mode": "full", "modules": [], "changed_paths": sorted(set(paths))}
    if not paths:
        return {**full, "reason": "No bounded change set (manual or initial push)"}
    changed_selector = SELF_REFERENTIAL_CI_FILES.intersection(paths)
    if changed_selector:
        return {
            **full,
            "reason": "Changed CI scope selector or workflow: "
            + ", ".join(sorted(changed_selector)),
        }
    if event_name == "pull_request" and governance_only(records, repo):
        return {
            "mode": "governance",
            "modules": list(GOVERNANCE_MODULES),
            "changed_paths": sorted(set(paths)),
            "reason": (
                "Verified allowlisted governance-only PR; run selector and "
                "validator regression contracts"
            ),
        }
    modules = set(BASE_MODULES)
    for path in paths:
        if not (repo / path).is_file():
            return {**full, "reason": f"Deleted or unavailable input: {path}"}
        if path in DOCS | CI_FILES:
            continue
        presentation_scope = plugin_test_scope([path])
        if presentation_scope in {"docs", "ui"}:
            if presentation_scope == "ui":
                interface_modules = {
                    test.stem
                    for test in (repo / TEST_DIR).glob("test_*.py")
                    if any(
                        fnmatchcase(test.name, pattern) for pattern in UI_TEST_PATTERNS
                    )
                }
                if not interface_modules:
                    return {
                        **full,
                        "reason": "No interface tests for presentation input",
                    }
                modules.update(interface_modules)
            continue
        relative = Path(path)
        if (
            relative.parent != TEST_DIR
            or not re.fullmatch(r"test_[A-Za-z0-9_]+\.py", relative.name)
            or not (repo / relative).is_file()
        ):
            return {**full, "reason": f"Shared, deleted, or unclassified input: {path}"}
        modules.add(relative.stem)
    # Include test modules that refer to another selected module, including
    # literal dynamic imports. Extra matches only increase coverage. Shared
    # fixtures/resources are deliberately not eligible for this narrow path.
    sources = {
        path.stem: path.read_text(encoding="utf-8")
        for path in (repo / TEST_DIR).glob("test_*.py")
    }
    previous = set()
    while previous != modules:
        previous = set(modules)
        pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, modules)) + r")\b")
        modules.update(
            name for name, source in sources.items() if pattern.search(source)
        )
    return {
        "mode": "selected",
        "modules": sorted(modules),
        "changed_paths": sorted(set(paths)),
        "reason": "CI/docs and affected test modules; production inputs unchanged",
    }


def event_changes(event, event_name, repo=REPO):
    if event_name == "pull_request":
        pull = event["pull_request"]
        return changed_records(pull["base"]["sha"], pull["head"]["sha"], repo)
    if event_name == "push" and event.get("before") not in (None, "0" * 40):
        return changed_records(event["before"], event["after"], repo, event="push")
    return []


def event_paths(event, event_name, repo=REPO):
    return changed_paths_from_records(event_changes(event, event_name, repo))


def test_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_ids(item)
        else:
            yield item.id()


def partition_tests(ids, workers):
    """Balance estimated module work without splitting or omitting any test ID."""
    modules = {}
    for name in ids:
        modules.setdefault(name.rsplit(".", 2)[0], []).append(name)
    groups = [[] for _ in range(min(workers, len(modules)))]
    costs = {
        name: max(len(rows), MODULE_SECONDS.get(name, 0))
        for name, rows in modules.items()
    }
    ordered = sorted(modules, key=lambda name: (-costs[name], name))
    loads = [0] * len(groups)
    for name in ordered:
        index = min(range(len(groups)), key=lambda index: (loads[index], index))
        groups[index].extend(modules[name])
        loads[index] += costs[name]
    if Counter(name for group in groups for name in group) != Counter(ids):
        raise ValueError("Parallel test inventory differs from full discovery")
    return groups


def run_partition(ids, directory):
    sys.path.insert(0, str(directory))
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames(ids)
    actual = list(test_ids(suite))
    if loader.errors or Counter(actual) != Counter(ids):
        raise ValueError("Worker test inventory differs from full discovery")
    digest = hashlib.sha256(json.dumps(ids).encode()).hexdigest()
    print(json.dumps({"worker_started": digest, "planned_tests": len(ids)}), flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = {
        "test_ids_sha256": digest,
        "planned_tests": len(ids),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skips": len(result.skipped),
        "passed": result.wasSuccessful() and result.testsRun == len(ids),
    }
    print(json.dumps({"worker_completed": summary}), flush=True)
    return summary


def run_parallel(suite, directory, workers):
    ids = list(test_ids(suite))
    exclusive = SERIAL_DEADLINE_MODULES | SERIAL_SOURCE_MUTATION_MODULES
    serial = [name for name in ids if name.rsplit(".", 2)[0] in exclusive]
    groups = partition_tests(
        [name for name in ids if name.rsplit(".", 2)[0] not in exclusive],
        workers,
    )
    if Counter([*serial, *(name for group in groups for name in group)]) != Counter(
        ids
    ):
        raise ValueError("Serial/parallel test inventory differs from full discovery")
    print(
        json.dumps(
            {
                "parallel_workers": len(groups),
                "serial_tests": len(serial),
                "planned_tests": len(ids),
            }
        ),
        flush=True,
    )
    results = []
    incomplete = 0
    if groups:
        with ProcessPoolExecutor(
            max_workers=len(groups), mp_context=multiprocessing.get_context("spawn")
        ) as executor:
            futures = [
                executor.submit(run_partition, group, directory) for group in groups
            ]
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except (Exception, SystemExit):
                    incomplete += 1
                    traceback.print_exc()
    if serial:
        # Keep the supervisor alive even if a serial fixture terminates itself.
        with ProcessPoolExecutor(
            max_workers=1, mp_context=multiprocessing.get_context("spawn")
        ) as executor:
            try:
                results.append(
                    executor.submit(run_partition, serial, directory).result()
                )
            except (Exception, SystemExit):
                incomplete += 1
                traceback.print_exc()
    summary = {
        "planned_tests": len(ids),
        "tests_run": sum(item["tests_run"] for item in results),
        "failures": sum(item["failures"] for item in results),
        "errors": sum(item["errors"] for item in results),
        "skips": sum(item["skips"] for item in results),
        "incomplete_partitions": incomplete,
        "passed": not incomplete
        and bool(results)
        and all(item["passed"] for item in results),
    }
    print(json.dumps(summary), flush=True)
    return 0 if summary["passed"] else 1


def apply_test_profile(suite, profile):
    """Account every test occurrence, including integration checks deferred here."""
    if profile not in {"standard", "full"}:
        raise ValueError("Unknown plugin test profile")
    ids = list(test_ids(suite))
    deferred_modules = SLOW_INTEGRATION_MODULES if profile == "standard" else set()
    selected = unittest.TestSuite()
    deferred = []

    def add(items):
        for item in items:
            if isinstance(item, unittest.TestSuite):
                add(item)
            elif item.id().rsplit(".", 2)[0] in deferred_modules:
                deferred.append(item.id())
            else:
                selected.addTest(item)

    add(suite)
    if Counter([*test_ids(selected), *deferred]) != Counter(ids):
        raise ValueError("Selected/deferred inventory differs from discovery")
    print(
        json.dumps(
            {
                "test_profile": profile,
                "discovered_tests": len(ids),
                "selected_tests": selected.countTestCases(),
                "deferred_tests": len(deferred),
                "deferred_test_ids": deferred,
                "deferred_status": "not-run; not a pass",
                "full_suite_requested": profile == "full",
            }
        ),
        flush=True,
    )
    return selected


def run_suite(selection, repo=REPO, contracts=False, workers=1, profile="standard"):
    if not 1 <= workers <= 3:
        raise ValueError("Test workers must be between one and three")
    governance = selection["mode"] == "governance"
    test_dir = Path(".github/scripts") if contracts or governance else TEST_DIR
    directory = repo / test_dir
    sys.path.insert(0, str(directory))
    loader = unittest.TestLoader()
    if not contracts and selection["mode"] == "full":
        suite = loader.discover(str(directory))
    else:
        suite = unittest.TestSuite()
        modules = (
            CONTRACT_MODULES
            if contracts
            else GOVERNANCE_MODULES
            if governance
            else selection["modules"]
        )
        for name in modules:
            module_suite = loader.loadTestsFromName(name)
            if module_suite.countTestCases() == 0:
                raise ValueError(f"Selected test module is empty: {name}")
            suite.addTests(module_suite)
    if not contracts and not governance:
        suite = apply_test_profile(suite, profile)
    if suite.countTestCases() == 0:
        raise ValueError("Selected test suite is empty")
    if workers > 1 and not contracts and selection["mode"] == "full":
        if loader.errors:
            raise ValueError(
                "Full discovery contains import errors: " + str(loader.errors)
            )
        return run_parallel(suite, directory, workers)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(
        json.dumps(
            {
                "tests_run": result.testsRun,
                "failures": len(result.failures),
                "errors": len(result.errors),
                "skips": len(result.skipped),
                "passed": result.wasSuccessful(),
            }
        ),
        flush=True,
    )
    return 0 if result.wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", action="store_true")
    parser.add_argument("--governance", action="store_true")
    parser.add_argument(
        "--workers", type=int, default=os.environ.get("PLUGIN_TEST_WORKERS", "1")
    )
    parser.add_argument(
        "--profile",
        choices=("standard", "full"),
        default=os.environ.get("PLUGIN_TEST_PROFILE", "standard"),
    )
    args = parser.parse_args()
    if args.profile not in ("standard", "full"):
        parser.error("PLUGIN_TEST_PROFILE must be standard or full")
    if args.profile == "full" and os.environ.get("GITHUB_EVENT_NAME") in {
        "pull_request",
        "pull_request_target",
        "push",
        "workflow_call",
    }:
        parser.error("Long integration tests require an explicit manual full run")
    if args.contracts and args.governance:
        parser.error("--contracts and --governance are mutually exclusive")
    if args.contracts:
        selection = {"mode": "contracts", "modules": list(CONTRACT_MODULES)}
    elif args.governance:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text("utf-8"))
        records = event_changes(event, os.environ["GITHUB_EVENT_NAME"])
        paths = changed_paths_from_records(records)
        if not event.get("pull_request") or not governance_only(records, REPO):
            raise ValueError(
                "Governance contract scope requires verified allowlisted PR changes"
            )
        selection = plan(paths, records=records, event_name="pull_request")
        if selection["mode"] != "governance":
            raise ValueError("Governance contract scope could not be verified")
    else:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text("utf-8"))
        records = event_changes(event, os.environ["GITHUB_EVENT_NAME"])
        paths = changed_paths_from_records(records)
        selection = plan(
            paths, records=records, event_name=os.environ.get("GITHUB_EVENT_NAME")
        )
    print(json.dumps(selection), flush=True)
    return run_suite(
        selection, contracts=args.contracts, workers=args.workers, profile=args.profile
    )


if __name__ == "__main__":
    raise SystemExit(main())

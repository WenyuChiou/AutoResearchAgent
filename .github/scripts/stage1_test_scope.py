"""Run affected plugin tests; uncertain inputs retain the full contract suite."""

import argparse
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import re
import sys
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
DOCS = {
    "plugins/auto-research-agent/README.md",
    "plugins/auto-research-agent/CONTRIBUTING.md",
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


def run_suite(selection, repo=REPO, contracts=False):
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
    if suite.countTestCases() == 0:
        raise ValueError("Selected test suite is empty")
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
    args = parser.parse_args()
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
    return run_suite(selection, contracts=args.contracts)


if __name__ == "__main__":
    raise SystemExit(main())

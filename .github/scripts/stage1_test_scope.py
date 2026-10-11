"""Run affected plugin tests; uncertain inputs retain the full contract suite."""

import argparse
import json
import os
from pathlib import Path
import re
import sys
import unittest

from ci_scope import changed_paths


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
    ".github/workflows/blocking-ci.yml",
    ".github/scripts/ci_scope.py",
    ".github/scripts/test_ci_scope.py",
    ".github/scripts/stage1_test_scope.py",
    ".github/scripts/test_stage1_test_scope.py",
    ".github/scripts/test_stage1_ci_quality.py",
}
CONTRACT_MODULES = (
    "test_ci_scope",
    "test_stage1_test_scope",
    "test_validate_research_pr",
    "test_check_research_pr_dependencies",
    "test_stage1_ci_quality",
)


def plan(paths, repo=REPO):
    """Only standalone test edits and explicitly named CI/docs use selection."""
    full = {"mode": "full", "modules": [], "changed_paths": sorted(set(paths))}
    if not paths:
        return {**full, "reason": "No bounded change set (manual or initial push)"}
    modules = set(BASE_MODULES)
    for path in paths:
        if path in DOCS | CI_FILES:
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


def event_paths(event, event_name, repo=REPO):
    if event_name == "pull_request":
        pull = event["pull_request"]
        return changed_paths(pull["base"]["sha"], pull["head"]["sha"], repo)
    if event_name == "push" and event.get("before") not in (None, "0" * 40):
        return changed_paths(event["before"], event["after"], repo, event="push")
    return []


def run_suite(selection, repo=REPO, contracts=False):
    directory = repo / (Path(".github/scripts") if contracts else TEST_DIR)
    sys.path.insert(0, str(directory))
    loader = unittest.TestLoader()
    if not contracts and selection["mode"] == "full":
        suite = loader.discover(str(directory))
    else:
        suite = unittest.TestSuite()
        for name in CONTRACT_MODULES if contracts else selection["modules"]:
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
    args = parser.parse_args()
    if args.contracts:
        selection = {"mode": "contracts", "modules": list(CONTRACT_MODULES)}
    else:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text("utf-8"))
        selection = plan(event_paths(event, os.environ["GITHUB_EVENT_NAME"]))
    print(json.dumps(selection), flush=True)
    return run_suite(selection, contracts=args.contracts)


if __name__ == "__main__":
    raise SystemExit(main())

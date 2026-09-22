"""Select plugin-only checks and reject failures or unplanned skipped jobs."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys


ENGINE_JOBS = {"bazel", "cargo-deny", "codespell", "repo-checks", "rust-ci", "sdk"}
PLUGIN_CI = {
    ".agents/plugins/marketplace.json",
    ".github/workflows/stage1-plugin.yml",
    ".github/workflows/blocking-ci.yml",
    ".github/scripts/ci_scope.py",
    ".github/scripts/test_ci_scope.py",
    ".github/scripts/validate_research_pr.py",
    ".github/scripts/test_validate_research_pr.py",
    ".github/scripts/check_research_pr_dependencies.py",
    ".github/scripts/test_check_research_pr_dependencies.py",
    ".github/scripts/test_stage1_ci_quality.py",
    ".github/scripts/criterion-submetric-map.v1.json",
    ".github/scripts/invariant-registry.v1.json",
    ".github/pull_request_template.md",
}


def plugin_only(paths):
    return bool(paths) and all(
        path.startswith("plugins/auto-research-agent/")
        or path.startswith(".github/scripts/fixtures/pr_bodies/")
        or path.startswith(".github/scripts/fixtures/pr_evidence/")
        or path in PLUGIN_CI
        for path in paths
    )


def changed_paths(base, head, cwd=None, event="pull_request"):
    if not all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in (base, head)):
        raise ValueError("Expected full Git commit SHAs")
    comparison = f"{base}..{head}" if event == "push" else f"{base}...{head}"
    output = subprocess.check_output(
        ["git", "diff", "--name-only", "--no-renames", "-z", comparison],
        cwd=cwd,
    )
    return output.decode("utf-8").rstrip("\0").split("\0") if output else []


def check_results(needs):
    scope = needs.get("scope", {})
    selection = scope.get("outputs", {}).get("plugin_only")
    errors = (
        [] if selection in ("true", "false") else ["Missing or invalid CI selection"]
    )
    for name in ENGINE_JOBS | {"scope", "stage1", "blob-size-policy"} | needs.keys():
        result = needs.get(name, {}).get("result", "missing")
        allowed = (
            {"success", "skipped"}
            if name in ENGINE_JOBS and selection == "true"
            else {"success"}
        )
        if result not in allowed:
            errors.append(f"{name}: {result}")
    return sorted(errors)


if __name__ == "__main__":
    if sys.argv[1:] == ["check"]:
        failures = check_results(json.loads(os.environ["NEEDS"]))
        print(
            "\n".join(failures)
            if failures
            else "All selected checks passed; all skips match the plan."
        )
        raise SystemExit(bool(failures))
    event = json.loads(
        Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
    )
    # PR diffs use the merge base, so unrelated commits arriving on main are
    # not attributed here. Pushes compare the previous tip with the new tip.
    # Manual/new-branch events retain full checks; unavailable commits fail.
    pull = event.get("pull_request")
    if pull:
        paths = changed_paths(pull["base"]["sha"], pull["head"]["sha"])
    elif event.get("before") and event["before"] != "0" * 40:
        paths = changed_paths(event["before"], event["after"], event="push")
    else:
        paths = []
    selected = str(plugin_only(paths)).lower()
    print(json.dumps({"plugin_only": selected, "changed_paths": paths}))
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"plugin_only={selected}\n")

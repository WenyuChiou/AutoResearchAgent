"""Select plugin-only checks and reject failures or unplanned skipped jobs."""

import json
from fnmatch import fnmatchcase
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_JOBS = {"bazel", "cargo-deny", "codespell", "repo-checks", "rust-ci", "sdk"}
PLUGIN_CI = {
    ".agents/plugins/marketplace.json",
    ".github/workflows/stage1-plugin.yml",
    ".github/workflows/research-pr-metadata.yml",
    ".github/workflows/blocking-ci.yml",
    ".github/scripts/ci_scope.py",
    ".github/scripts/test_ci_scope.py",
    ".github/scripts/stage1_test_scope.py",
    ".github/scripts/test_stage1_test_scope.py",
    ".github/scripts/validate_research_pr.py",
    ".github/scripts/test_validate_research_pr.py",
    ".github/scripts/check_research_pr_dependencies.py",
    ".github/scripts/test_check_research_pr_dependencies.py",
    ".github/scripts/test_stage1_ci_quality.py",
    ".github/scripts/criterion-submetric-map.v1.json",
    ".github/scripts/invariant-registry.v1.json",
    ".github/pull_request_template.md",
    "AGENTS.md",
    "plugins/auto-research-agent/AGENTS.md",
}

GOVERNANCE_ONLY_PATHS = {
    "AGENTS.md",
    "plugins/auto-research-agent/AGENTS.md",
}


PLUGIN_DOCS = {
    "plugins/auto-research-agent/README.md",
    "plugins/auto-research-agent/CONTRIBUTING.md",
}
ATLAS_PRESENTATION = {
    "plugins/auto-research-agent/references/research-workspace/atlas/atlas.html",
    "plugins/auto-research-agent/references/research-workspace/atlas/atlas.css",
}
UI_TEST_PATTERNS = (
    "test_stage_contracts.py",
    "test_plugin_loading.py",
    "test_workspace*.py",
    "test_research_workspace*.py",
    "test_atlas*.py",
    "test_project*.py",
    "test_native_atlas*.py",
    "test_native_message*.py",
    "test_native_known_unsent.py",
)


def plugin_test_scope(paths, records=None, event="pull_request", repo=None):
    """Choose test scope; pull_request code runs from the untrusted candidate ref.

    Governance scope is a performance optimization, not a security boundary.
    The selector itself and its workflow are outside the allowlist.
    """
    if event == "pull_request" and governance_only(records, repo):
        return "governance"
    if not paths:
        return "full"
    presentation = False
    for path in paths:
        if ".." in path.split("/") or "\\" in path:
            return "full"
        if path in ATLAS_PRESENTATION:
            presentation = True
        elif path in PLUGIN_DOCS or (
            path.startswith("review-evidence/")
            and Path(path).suffix in {".md", ".txt", ".log", ".png", ".jpg", ".jpeg"}
        ):
            continue
        else:
            # Prompts, JavaScript, fixtures, dependencies and policy remain full.
            return "full"
    return "ui" if presentation else "docs"


def plugin_suite(tests, scope):
    """Discover real tests for the plan; no empty or unknown plan can pass."""
    loader = unittest.TestLoader()
    if scope == "full":
        suite = loader.discover(str(tests))
    elif scope in {"docs", "ui"}:
        patterns = ("test_stage_contracts.py",) if scope == "docs" else UI_TEST_PATTERNS
        names = sorted(
            path.name
            for path in tests.glob("test_*.py")
            if any(fnmatchcase(path.name, pattern) for pattern in patterns)
        )
        print(json.dumps({"plugin_test_scope": scope, "test_modules": names}))
        suite = unittest.TestSuite(
            loader.discover(str(tests), pattern=name) for name in names
        )
    else:
        raise ValueError("Missing or invalid plugin test scope")
    if not suite.countTestCases():
        raise ValueError("Selected plugin suite contains no tests")
    return suite


def plugin_only(paths):
    return bool(paths) and all(
        path.startswith("plugins/auto-research-agent/")
        or path.startswith(".github/scripts/fixtures/pr_bodies/")
        or path.startswith(".github/scripts/fixtures/pr_evidence/")
        or path in PLUGIN_CI
        for path in paths
    )


def governance_only(records, repo=None):
    """Recognize allowlisted edits only after validating both Git text blobs."""
    if not records:
        return False
    root = Path(repo) if repo is not None else REPO_ROOT
    try:
        for record in records:
            if not (
                record["status"] == "M"
                and record["old_path"] == record["new_path"]
                and record["old_path"] in GOVERNANCE_ONLY_PATHS
                and record["old_mode"] == record["new_mode"] == "100644"
            ):
                return False
            old_sha = record["old_sha"]
            new_sha = record["new_sha"]
            if (
                not all(
                    isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha)
                    for sha in (old_sha, new_sha)
                )
                or old_sha == new_sha
            ):
                return False
            blobs = [
                subprocess.check_output(
                    ["git", "cat-file", "blob", sha],
                    cwd=root,
                    stderr=subprocess.DEVNULL,
                )
                for sha in (old_sha, new_sha)
            ]
            if not all(_is_nonempty_utf8_text(blob) for blob in blobs):
                return False
    except (KeyError, OSError, subprocess.CalledProcessError, TypeError, ValueError):
        return False
    return True


def _is_nonempty_utf8_text(blob):
    if not blob or b"\0" in blob:
        return False
    try:
        text = blob.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return False
    if text.startswith("\ufeff"):
        return False
    return not any(
        (ord(char) < 0x20 and char not in "\t\r\n") or 0x7F <= ord(char) <= 0x9F
        for char in text
    )


def changed_paths_from_records(records):
    """Flatten every changed path once, including rename/copy endpoints."""
    paths = []
    seen = set()
    for record in records:
        for path in (record["old_path"], record["new_path"]):
            if path and path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


def parse_raw_diff(output):
    """Parse git diff --raw -z records, retaining both rename endpoints."""
    if not output:
        return []
    fields = output.split(b"\0")
    if fields[-1] != b"":
        raise ValueError("Malformed NUL-delimited Git diff")
    fields.pop()
    records = []
    index = 0
    while index < len(fields):
        header = fields[index]
        index += 1
        match = re.fullmatch(
            rb":([0-7]{6}) ([0-7]{6}) ([0-9a-f]{40}) ([0-9a-f]{40}) ([A-Z][0-9]*)",
            header,
        )
        if not match:
            raise ValueError("Malformed Git diff metadata")
        old_mode, new_mode, old_sha, new_sha, raw_status = match.groups()
        status = raw_status[:1].decode("ascii")
        count = 2 if status in {"R", "C"} else 1
        if index + count > len(fields):
            raise ValueError("Incomplete Git diff path record")
        try:
            paths = [fields[index + offset].decode("utf-8") for offset in range(count)]
        except UnicodeDecodeError as error:
            raise ValueError("Git diff path is not valid UTF-8") from error
        index += count
        records.append(
            {
                "status": status,
                "old_mode": old_mode.decode("ascii"),
                "new_mode": new_mode.decode("ascii"),
                "old_sha": old_sha.decode("ascii"),
                "new_sha": new_sha.decode("ascii"),
                "old_path": paths[0],
                "new_path": paths[-1],
            }
        )
    return records


def changed_records(base, head, cwd=None, event="pull_request"):
    if not all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in (base, head)):
        raise ValueError("Expected full Git commit SHAs")
    comparison = f"{base}..{head}" if event == "push" else f"{base}...{head}"
    output = subprocess.check_output(
        [
            "git",
            "diff",
            "--raw",
            "-z",
            "--no-abbrev",
            "--no-ext-diff",
            "--find-renames",
            comparison,
        ],
        cwd=cwd,
    )
    return parse_raw_diff(output)


def changed_paths(base, head, cwd=None, event="pull_request"):
    records = changed_records(base, head, cwd, event)
    return changed_paths_from_records(records)


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
    if sys.argv[1:] == ["run-plugin"]:
        root = Path(__file__).resolve().parents[2]
        suite = plugin_suite(
            root / "plugins/auto-research-agent/tests",
            os.environ.get("PLUGIN_TEST_SCOPE"),
        )
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        raise SystemExit(not result.wasSuccessful())
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
        records = changed_records(pull["base"]["sha"], pull["head"]["sha"])
    elif event.get("before") and event["before"] != "0" * 40:
        records = changed_records(event["before"], event["after"], event="push")
    else:
        records = []
    paths = changed_paths_from_records(records)
    selected = str(plugin_only(paths)).lower()
    test_scope = plugin_test_scope(
        paths,
        records,
        event=os.environ.get("GITHUB_EVENT_NAME", ""),
        repo=REPO_ROOT,
    )
    print(
        json.dumps(
            {
                "plugin_only": selected,
                "plugin_test_scope": test_scope,
                "changed_paths": paths,
            }
        )
    )
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"plugin_only={selected}\n")
        output.write(f"plugin_test_scope={test_scope}\n")

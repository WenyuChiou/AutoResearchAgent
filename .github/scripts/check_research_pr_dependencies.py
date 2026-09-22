"""Verify pull-request prerequisite state and immutable dependency pins."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from validate_research_pr import (
    DEPENDENCY_PIN,
    label_value,
    sections,
    semicolon_entries,
)


PR_URL = re.compile(r"^https://github\.com/[^/\s]+/[^/\s]+/pull/\d+/?$")
DEFAULT_REPOSITORY = "WenyuChiou/AutoResearchAgent"


class GitHubCliResolver:
    """Resolve PR state through the authenticated GitHub CLI."""

    def resolve(self, url):
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                url,
                "--json",
                "state,isDraft,mergedAt,reviewDecision,headRefOid,mergeCommit",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)


def _entries(value):
    if not value or value.casefold() == "none":
        return []
    return semicolon_entries(value)


def _repository_from_url(url):
    parts = url.rstrip("/").split("/")
    return f"{parts[3]}/{parts[4]}" if len(parts) >= 7 else ""


def validate_dependencies(body, is_draft, resolver, current_repository=None):
    """Return dependency-state errors for one PR body."""

    parsed = sections(body or "")
    what = parsed.get("What", "")
    evaluation = parsed.get("Evaluation", "")
    readiness = label_value(evaluation, "Evaluation readiness").casefold()
    current_repository = (
        current_repository or os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPOSITORY
    )
    errors = []

    internal = _entries(label_value(what, "Internal prerequisite PR(s)"))
    for url in internal:
        if not PR_URL.fullmatch(url):
            continue
        if _repository_from_url(url).casefold() != current_repository.casefold():
            errors.append(
                f"internal prerequisite must belong to {current_repository}: {url}"
            )
            continue
        try:
            state = resolver.resolve(url)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
            errors.append(f"could not resolve internal prerequisite {url}: {error}")
            continue
        merged = bool(state.get("mergedAt"))
        review_decision = (state.get("reviewDecision") or "").upper()
        if not is_draft and not merged:
            errors.append(f"ready PR requires merged internal prerequisite: {url}")
        if not is_draft and not merged and review_decision == "CHANGES_REQUESTED":
            errors.append(f"ready PR prerequisite has changes requested: {url}")

    external = _entries(label_value(what, "External dependency pin(s)"))
    for entry in external:
        match = DEPENDENCY_PIN.fullmatch(entry)
        if not match:
            continue
        url, expected_sha, declared_state = match.groups()
        try:
            state = resolver.resolve(url)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
            errors.append(f"could not resolve external dependency {url}: {error}")
            continue
        merged = bool(state.get("mergedAt"))
        if declared_state.casefold() == "open":
            actual_sha = state.get("headRefOid")
            if merged or (state.get("state") or "").upper() != "OPEN":
                errors.append(
                    f"external dependency declared open but is not open: {url}"
                )
        else:
            merge_commit = state.get("mergeCommit") or {}
            actual_sha = merge_commit.get("oid")
            if not merged:
                errors.append(
                    f"external dependency declared merged but is not merged: {url}"
                )
        if actual_sha != expected_sha:
            errors.append(
                f"external dependency SHA mismatch for {url}: expected "
                f"{expected_sha}, got {actual_sha or 'missing'}"
            )
        if (
            not is_draft
            or readiness in {"stage-executable", "improvement-demonstrated"}
        ) and not merged:
            errors.append(
                f"ready or executable PR requires merged external dependency: {url}"
            )
        if (
            not is_draft
            and not merged
            and (state.get("reviewDecision") or "").upper() == "CHANGES_REQUESTED"
        ):
            errors.append(f"ready PR external dependency has changes requested: {url}")
    return errors


def context_from_event(path):
    event = json.loads(path.read_text(encoding="utf-8"))
    pull_request = event.get("pull_request")
    if not pull_request:
        return None
    return pull_request.get("body") or "", bool(pull_request.get("draft"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-file", type=Path)
    args = parser.parse_args()
    event_path = args.event_file or (
        Path(os.environ["GITHUB_EVENT_PATH"])
        if os.environ.get("GITHUB_EVENT_PATH")
        else None
    )
    if event_path is None:
        print("No pull-request event; dependency check skipped.")
        return 0
    context = context_from_event(event_path)
    if context is None:
        print("No pull-request event; dependency check skipped.")
        return 0
    body, is_draft = context
    errors = validate_dependencies(
        body,
        is_draft,
        GitHubCliResolver(),
        os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPOSITORY,
    )
    if errors:
        print("Research PR dependency check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Research PR dependency check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

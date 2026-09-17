"""Validate the research-harness pull-request explanation contract."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


REQUIRED_SECTIONS = ("Why", "What", "How", "Example", "Evaluation", "Validation")
HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
METRIC = re.compile(r"\bP[1-9]\b")
CAPABILITY_DECISIONS = {"reuse", "wrap", "extend", "build-new"}
REQUIRED_LABELS = {
    "Why": ("Target primary metric(s)",),
    "What": ("Affected capability ID(s)", "Capability decision"),
    "Evaluation": (
        "Hard measures",
        "Human judgment rubric",
        "Major-error guardrail",
        "Per-PR metric evidence",
        "Live paired A/B",
    ),
}
DEFAULT_REGISTRY = (
    Path(__file__).resolve().parents[2]
    / "plugins/auto-research-agent/evals/capability-metric-map.v1.json"
)


def sections(body):
    matches = list(HEADING.finditer(body))
    return {
        match.group(1).strip(): body[
            match.end() : matches[index + 1].start()
            if index + 1 < len(matches)
            else len(body)
        ].strip()
        for index, match in enumerate(matches)
    }


def visible_text(value):
    return COMMENT.sub("", value).strip()


def label_has_value(value, label):
    pattern = re.compile(rf"^-\s*{re.escape(label)}:[ \t]*([^\r\n]+)$", re.MULTILINE)
    match = pattern.search(visible_text(value))
    return bool(match and match.group(1).strip())


def label_value(value, label):
    pattern = re.compile(rf"^-\s*{re.escape(label)}:[ \t]*([^\r\n]+)$", re.MULTILINE)
    match = pattern.search(visible_text(value))
    return match.group(1).strip() if match else ""


def load_capability_metrics(path=DEFAULT_REGISTRY):
    registry = json.loads(path.read_text(encoding="utf-8"))
    return {
        entry["capability_id"]: {
            "metrics": {effect["metric_id"] for effect in entry["metric_effects"]},
            "owner_path": entry["owner_path"],
        }
        for entry in registry["capabilities"]
    }


def capability_ids(value):
    return [item.strip() for item in re.split(r"[,;]", value) if item.strip()]


def path_is_capability_entry(path):
    normalized = path.replace("\\", "/")
    if normalized == ".github/scripts/validate_research_pr.py":
        return True
    roots = (
        "plugins/auto-research-agent/skills/",
        "plugins/auto-research-agent/tools/",
        "plugins/auto-research-agent/mcp/",
        "plugins/auto-research-agent/cli/",
        "plugins/auto-research-agent/validators/",
        "plugins/auto-research-agent/gates/",
    )
    matched_root = next((root for root in roots if normalized.startswith(root)), None)
    if matched_root is None:
        return False
    root_relative = normalized.removeprefix(matched_root)
    return root_relative not in {"README.md", "__init__.py"} and not any(
        part == "__pycache__" for part in normalized.split("/")
    )


def capabilities_for_changed_paths(changed_paths, known_capabilities):
    required = set()
    unowned = []
    for changed_path in changed_paths:
        normalized = changed_path.replace("\\", "/")
        if not path_is_capability_entry(normalized):
            continue
        owners = [
            capability_id
            for capability_id, entry in known_capabilities.items()
            if normalized == entry["owner_path"]
            or normalized.startswith(f"{entry['owner_path'].rstrip('/')}/")
        ]
        if owners:
            required.update(owners)
        else:
            unowned.append(normalized)
    return required, unowned


def changed_files(base_sha, head_sha, cwd=None):
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACMRT",
            f"{base_sha}...{head_sha}",
        ],
        check=True,
        capture_output=True,
        cwd=cwd,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def validate_pr_body(body, known_capabilities=None, changed_paths=None):
    parsed = sections(body or "")
    errors = []
    for name in REQUIRED_SECTIONS:
        if name not in parsed:
            errors.append(f"missing section: ## {name}")
        elif not visible_text(parsed[name]):
            errors.append(f"empty section: ## {name}")
    for section, labels in REQUIRED_LABELS.items():
        for label in labels:
            if not label_has_value(parsed.get(section, ""), label):
                errors.append(f"{section} requires a non-empty '{label}:' value")
    why_and_evaluation = "\n".join(
        visible_text(parsed.get(name, "")) for name in ("Why", "Evaluation")
    )
    if not METRIC.search(why_and_evaluation):
        errors.append("Why or Evaluation must name at least one primary metric P1-P9")
    decision = label_value(parsed.get("What", ""), "Capability decision").lower()
    if decision not in CAPABILITY_DECISIONS:
        errors.append(
            "Capability decision must be exactly reuse, wrap, extend, or build-new"
        )
    declared_metrics = set(METRIC.findall(why_and_evaluation))
    declared_capabilities = capability_ids(
        label_value(parsed.get("What", ""), "Affected capability ID(s)")
    )
    if known_capabilities is not None:
        for capability_id in declared_capabilities:
            if capability_id not in known_capabilities:
                errors.append(
                    f"unknown capability ID '{capability_id}'; register it in "
                    "capability-metric-map.v1.json"
                )
                continue
            capability_metrics = known_capabilities[capability_id]["metrics"]
            if declared_metrics.isdisjoint(capability_metrics):
                expected = ", ".join(sorted(capability_metrics))
                errors.append(
                    f"capability '{capability_id}' has no declared target metric in common "
                    f"with its registry entry ({expected})"
                )
        if changed_paths is not None:
            required, unowned = capabilities_for_changed_paths(
                changed_paths, known_capabilities
            )
            for path in unowned:
                errors.append(f"changed capability path '{path}' has no registry owner")
            missing = required.difference(declared_capabilities)
            if missing:
                errors.append(
                    "changed capabilities missing from 'Affected capability ID(s):': "
                    + ", ".join(sorted(missing))
                )
    example = visible_text(parsed.get("Example", ""))
    for label in ("Before", "After"):
        if not re.search(rf"^{label}:[ \t]*[^\s\r\n].*$", example, re.MULTILINE):
            errors.append(f"Example requires a non-empty '{label}:' value")
    return errors


def context_from_event(path):
    event = json.loads(path.read_text(encoding="utf-8"))
    pull_request = event.get("pull_request")
    if not pull_request:
        return None
    return {
        "body": pull_request.get("body") or "",
        "base_sha": pull_request["base"]["sha"],
        "head_sha": pull_request["head"]["sha"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--body-file", type=Path)
    args = parser.parse_args()
    if args.body_file:
        body = args.body_file.read_text(encoding="utf-8")
        paths = None
    else:
        event_path = os.environ.get("GITHUB_EVENT_PATH")
        if not event_path:
            print("No pull-request event; PR contract check skipped.")
            return 0
        context = context_from_event(Path(event_path))
        if context is None:
            print("No pull-request event; PR contract check skipped.")
            return 0
        body = context["body"]
        paths = changed_files(context["base_sha"], context["head_sha"])
    errors = validate_pr_body(body, load_capability_metrics(), paths)
    if errors:
        print("Research PR contract failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Research PR contract passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

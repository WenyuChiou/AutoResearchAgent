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
EXECUTION_STATUSES = {"complete", "partial", "blocked"}
EVALUATION_MODES = {"deterministic", "ai-judge", "hybrid"}
AI_JUDGE_EVIDENCE = re.compile(
    r"^(artifact|deferred|not-applicable)\s*:\s*(.+)$", re.IGNORECASE
)
ARTIFACT_REF = re.compile(
    r"(?:https://|[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+|"
    r"[A-Za-z0-9_.-]+\.(?:jsonl?|md|txt|csv|ya?ml))"
)
EXTERNAL_PR = re.compile(r"https://github\.com/([^/\s]+)/([^/\s]+)/pull/\d+/?$")
IMPROVEMENT_STATEMENT = re.compile(
    r"^(improved|not improved|not yet demonstrated)\s*(?:—|:|-)\s*"
    r"(.+?);\s*evidence:\s*(.+)$",
    re.IGNORECASE,
)
EVIDENCE_SIGNAL = re.compile(
    r"(?:\b\d+(?:/\d+|(?:\.\d+)?%)?\b|\btests?\s+(?:pass(?:ed)?|fail(?:ed)?)\b|"
    r"\b(?:artifact|schema|fixture|benchmark|paired|metric|measurement|milestone|a/b)\b|"
    r"https://|[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)",
    re.IGNORECASE,
)
SKILL_TEST_LABELS = (
    "Skill test scenario",
    "Skill test command",
    "Skill test expected",
    "Skill test actual",
    "Skill test limitations",
)
PLACEHOLDER_VALUE = re.compile(
    r"^(?:tbd|todo|n/?a|none|pending|unknown|not[ -]tested|not[ -]run|"
    r"placeholder|fill[ -](?:this|me))(?:\s+(?:later|yet|here|please|soon))?$",
    re.IGNORECASE,
)
REQUIRED_LABELS = {
    "Why": ("Plain-language summary", "Target primary metric(s)"),
    "What": (
        "Affected capability ID(s)",
        "Capability decision",
        "Related external PR(s)",
    ),
    "Evaluation": (
        "Rubric version",
        "Rubric criterion ID(s)",
        "Evaluation mode",
        "Hard measures",
        "AI-judge evidence",
        "Major-error guardrail",
        "Per-PR metric evidence",
        "Improvement statement",
        "Live paired A/B",
    ),
    "Validation": (
        "Execution status",
        "Remaining work or blocker",
        "Review and merge owner",
    ),
}
DEFAULT_REGISTRY = (
    Path(__file__).resolve().parents[2]
    / "plugins/auto-research-agent/evals/capability-metric-map.v1.json"
)
DEFAULT_RUBRIC_DIR = (
    Path(__file__).resolve().parents[2] / "plugins/auto-research-agent/evals/rubrics"
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


def label_has_concrete_value(value, label):
    return text_is_concrete(label_value(value, label))


def text_is_concrete(value):
    candidate = value.strip().strip("`._- ")
    return bool(candidate and not PLACEHOLDER_VALUE.fullmatch(candidate))


def load_capability_metrics(path=DEFAULT_REGISTRY):
    registry = json.loads(path.read_text(encoding="utf-8"))
    return {
        entry["capability_id"]: {
            "metrics": {effect["metric_id"] for effect in entry["metric_effects"]},
            "criteria": {
                criterion_id
                for effect in entry["metric_effects"]
                for criterion_id in effect["rubric_criteria"]
            },
            "owner_path": entry["owner_path"],
        }
        for entry in registry["capabilities"]
    }


def capability_ids(value):
    return [item.strip() for item in re.split(r"[,;]", value) if item.strip()]


def load_rubrics(directory=DEFAULT_RUBRIC_DIR):
    rubrics = {}
    for path in sorted(directory.glob("*.json")):
        rubric = json.loads(path.read_text(encoding="utf-8"))
        if rubric.get("status") != "frozen":
            continue
        version = rubric["rubric_version"]
        if version in rubrics:
            raise ValueError(f"duplicate rubric version: {version}")
        criteria = {}
        for metric in rubric["metrics"]:
            for criterion_id in metric["criterion_ids"]:
                if criterion_id in criteria:
                    raise ValueError(
                        f"duplicate criterion ID in {version}: {criterion_id}"
                    )
                criteria[criterion_id] = metric["id"]
        rubrics[version] = criteria
    return rubrics


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


def validate_pr_body(
    body, known_capabilities=None, changed_paths=None, known_rubrics=None
):
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
    target_metrics = label_value(parsed.get("Why", ""), "Target primary metric(s)")
    if not METRIC.search(target_metrics):
        errors.append("Target primary metric(s) must name at least one metric P1-P9")
    decision = label_value(parsed.get("What", ""), "Capability decision").lower()
    if decision not in CAPABILITY_DECISIONS:
        errors.append(
            "Capability decision must be exactly reuse, wrap, extend, or build-new"
        )
    plain_summary = label_value(parsed.get("Why", ""), "Plain-language summary")
    if plain_summary and (
        not text_is_concrete(plain_summary) or len(plain_summary) < 25
    ):
        errors.append(
            "Plain-language summary must be one concrete sentence explaining the "
            "problem, change, and benefit"
        )
    external_prs = label_value(parsed.get("What", ""), "Related external PR(s)")
    if external_prs and external_prs.casefold() != "none":
        external_entries = [entry.strip() for entry in external_prs.split(";")]
        invalid_external = []
        for entry in external_entries:
            match = EXTERNAL_PR.fullmatch(entry)
            if not match or (
                match.group(1).casefold() == "wenyuchiou"
                and match.group(2).casefold() == "autoresearchagent"
            ):
                invalid_external.append(entry)
        if invalid_external:
            errors.append(
                "Related external PR(s) must be 'None' or a semicolon-separated "
                "list of external GitHub pull-request URLs"
            )
    improvement = label_value(parsed.get("Evaluation", ""), "Improvement statement")
    improvement_match = IMPROVEMENT_STATEMENT.fullmatch(improvement)
    if not improvement_match:
        errors.append(
            "Improvement statement must begin with improved, not improved, or "
            "not yet demonstrated and use '; evidence:' in the same sentence"
        )
    else:
        change = improvement_match.group(2)
        evidence = improvement_match.group(3)
        if (
            not text_is_concrete(change)
            or len(change.split()) < 4
            or not text_is_concrete(evidence)
            or not EVIDENCE_SIGNAL.search(evidence)
        ):
            errors.append(
                "Improvement statement must include a concrete change and a "
                "measurement, test result, artifact, or explicit milestone deferral"
            )
    merge_owner = label_value(parsed.get("Validation", ""), "Review and merge owner")
    if merge_owner.casefold() != "core team":
        errors.append("Review and merge owner must be exactly 'core team'")
    execution_status = label_value(
        parsed.get("Validation", ""), "Execution status"
    ).casefold()
    if execution_status not in EXECUTION_STATUSES:
        errors.append("Execution status must be exactly complete, partial, or blocked")
    remaining = label_value(parsed.get("Validation", ""), "Remaining work or blocker")
    if remaining and remaining.casefold() != "none" and not text_is_concrete(remaining):
        errors.append("Remaining work or blocker must be 'None' or concrete")
    if execution_status in {"partial", "blocked"} and remaining.casefold() == "none":
        errors.append(
            "Partial or blocked execution must describe the remaining work or blocker"
        )
    declared_metrics = set(METRIC.findall(target_metrics))
    rubrics = known_rubrics if known_rubrics is not None else load_rubrics()
    rubric_version = label_value(parsed.get("Evaluation", ""), "Rubric version")
    rubric_criteria = rubrics.get(rubric_version, {})
    if rubric_version and rubric_version not in rubrics:
        errors.append("Rubric version must name a registered rubric version")
    declared_criteria = capability_ids(
        label_value(parsed.get("Evaluation", ""), "Rubric criterion ID(s)")
    )
    unknown_criteria = [
        criterion_id
        for criterion_id in declared_criteria
        if criterion_id not in rubric_criteria
    ]
    if unknown_criteria:
        errors.append(
            "unknown rubric criterion ID(s): " + ", ".join(sorted(unknown_criteria))
        )
    criterion_metrics = {
        rubric_criteria[criterion_id]
        for criterion_id in declared_criteria
        if criterion_id in rubric_criteria
    }
    undeclared_criterion_metrics = criterion_metrics.difference(declared_metrics)
    if undeclared_criterion_metrics:
        errors.append(
            "rubric criteria require undeclared target metric(s): "
            + ", ".join(sorted(undeclared_criterion_metrics))
        )
    missing_criterion_metrics = declared_metrics.difference(criterion_metrics)
    if missing_criterion_metrics:
        errors.append(
            "target metrics missing a rubric criterion ID: "
            + ", ".join(sorted(missing_criterion_metrics))
        )
    evaluation_mode = label_value(
        parsed.get("Evaluation", ""), "Evaluation mode"
    ).casefold()
    if evaluation_mode not in EVALUATION_MODES:
        errors.append(
            "Evaluation mode must be exactly deterministic, ai-judge, or hybrid"
        )
    ai_judge_evidence = label_value(parsed.get("Evaluation", ""), "AI-judge evidence")
    evidence_match = AI_JUDGE_EVIDENCE.fullmatch(ai_judge_evidence)
    evidence_kind = evidence_match.group(1).casefold() if evidence_match else ""
    evidence_detail = evidence_match.group(2).strip() if evidence_match else ""
    invalid_evidence = not evidence_match or not text_is_concrete(evidence_detail)
    if evidence_kind == "artifact":
        invalid_evidence |= ARTIFACT_REF.search(evidence_detail) is None
    elif evidence_kind in {"deferred", "not-applicable"}:
        invalid_evidence |= len(evidence_detail.split()) < 5
    if ai_judge_evidence and invalid_evidence:
        errors.append(
            "AI-judge evidence must use 'artifact: PATH', 'deferred: REASON', "
            "or 'not-applicable: REASON' with concrete detail"
        )
    declared_capabilities = capability_ids(
        label_value(parsed.get("What", ""), "Affected capability ID(s)")
    )
    if any(
        capability_id.startswith("skill:") for capability_id in declared_capabilities
    ):
        validation = parsed.get("Validation", "")
        for label in SKILL_TEST_LABELS:
            if not label_has_concrete_value(validation, label):
                errors.append(
                    f"Validation requires a concrete '{label}:' value for skill changes"
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
            capability_criteria = known_capabilities[capability_id].get(
                "criteria", set()
            )
            if capability_criteria and set(declared_criteria).isdisjoint(
                capability_criteria
            ):
                expected = ", ".join(sorted(capability_criteria))
                errors.append(
                    f"capability '{capability_id}' has no declared rubric criterion "
                    f"in common with its registry entry ({expected})"
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
    errors = validate_pr_body(body, load_capability_metrics(), paths, load_rubrics())
    if errors:
        print("Research PR contract failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Research PR contract passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

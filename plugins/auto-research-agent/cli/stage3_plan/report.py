"""Readable scientific argument and per-question design, from saved content."""

import json

from .review import plan_status
from .storage import inspect_package


def _text(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_plan(package_dir, *, expected_manifest_sha256, review=None):
    saved = inspect_package(package_dir, expected_manifest_sha256)
    artifacts = saved["artifacts"]
    if "plan.json" not in artifacts:
        failure = artifacts.get("failure.json", {"message": "incomplete attempt"})
        return f"# Stage 3 planning attempt\n\nStatus: failed. No research executed.\n\n{failure['message']}\n"
    plan = artifacts["plan.json"]
    intake = artifacts["request.json"]["intake"]
    lines = [
        f"# Research plan: {_text(plan['plan_id'])} v{plan['version']}",
        "",
        f"Status: {plan_status(plan, intake, review, admission_scope=artifacts['request.json']['admission_scope'])}; execution_authorized=false.",
        "",
        "Structural coverage and semantic review are distinct. No result has been observed.",
        "",
        f"Source planning manifest: {plan['source_manifest_sha256']}",
        "",
        "## Scientific argument",
    ]
    for row in intake["scientific_arguments"]:
        lines += ["", f"### {row['candidate_id']} v{row['candidate_version']}"]
        argument = row["argument"]
        for label, key in [
            ("Background and importance", "motivation"),
            ("Current research and applications", "current_state"),
            ("Gaps", "gaps"),
            ("Challenges", "challenges"),
            ("Proposed contribution", "contribution_claims"),
        ]:
            lines += [
                "",
                f"**{label}**",
                "",
                "```json",
                json.dumps(argument[key], ensure_ascii=False, indent=2),
                "```",
            ]
    lines += [
        "",
        "## Question-to-evidence matrix",
        "",
        "| Question | Evidence / measurement | Resources | Designs | Analysis | Results / blockers |",
        "|---|---|---|---|---|---|",
    ]
    for row in plan["question_plans"]:
        lines.append(
            "| "
            + " | ".join(
                _text(value)
                for value in (
                    row["question_ref"],
                    row["evidence_needed"] + "; " + row["measurement"],
                    ", ".join(
                        use["resource_id"] + ": " + use["fit_rationale"]
                        for use in row["resource_uses"]
                    ),
                    ", ".join(row["design_ids"]),
                    ", ".join(row["analysis_ids"]),
                    ", ".join(row["result_ids"] + row["blockers"]),
                )
            )
            + " |"
        )
    for label, key in [
        ("Scientific questions", "questions"),
        ("Per-question plan and minimum output", "question_plans"),
        ("Research procedures and stopping conditions", "designs"),
        ("Analysis and inference limits", "analyses"),
        ("Planned results and interpretation", "results"),
        ("Resources and scale estimates", "resources"),
        ("Milestones and dependencies", "milestones"),
        ("Unknowns", "unknowns"),
    ]:
        lines += [
            "",
            f"## {label}",
            "",
            "```json",
            json.dumps(plan[key], ensure_ascii=False, indent=2),
            "```",
        ]
    lines += [
        "",
        "## Semantic review",
        "",
        json.dumps(review, ensure_ascii=False, indent=2)
        if review
        else "Not performed. Structural validation is not scientific acceptance.",
        "",
    ]
    return "\n".join(lines)

"""Editable complete claim reports; oversized Excel cells retain exact JSON links."""

import html
import json

from stage1_deliverable.common import sha
from stage1_deliverable.views import workbook_bytes


def claim_reports(rows, verification_raw):
    path = "literature/claim_verification.json"
    digest = sha(verification_raw)
    markdown, table = (
        [
            "# Newly reviewed saved claims",
            "",
            "Old relations are retained; new judgments are declared source reviews.",
            "",
        ],
        [],
    )
    for number, row in enumerate(rows):
        report = {
            key: row.get(key)
            for key in (
                "claim_id",
                "work_id",
                "version_id",
                "relation",
                "current_relation",
                "reason_state",
                "reason_code",
                "explanation",
                "current_assertion",
                "original_claim",
                "new_assessment",
            )
        }
        markdown.extend(
            [
                "## " + html.escape(" ".join(str(row["claim_id"]).splitlines())),
                "",
                "<pre>"
                + html.escape(json.dumps(report, ensure_ascii=False, sort_keys=True))
                + "</pre>",
                "",
            ]
        )
        cells = {}
        for key, value in report.items():
            raw = (
                json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (dict, list))
                else str(value)
            )
            cells[key] = (
                dict(
                    path=path,
                    sha256=digest,
                    pointer=f"/rows/{number}/{key}",
                    content_truncated=False,
                )
                if len(raw.encode("utf-16-le")) // 2 > 32767
                else value
            )
        table.append(cells)
    if not table:
        table = [dict(claim_id=None, relation=None, explanation="No saved claims")]
    return {
        "literature/claim_assessments.md": ("\n".join(markdown) + "\n").encode("utf-8"),
        "literature/claim_assessments.xlsx": workbook_bytes(
            {"ClaimAssessments": table}
        ),
    }

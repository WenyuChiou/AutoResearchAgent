"""Tests for the transparent external Stage 2 v3 evaluation report."""

import copy
import json
import sys
import unittest
from html import unescape
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))

from stage2_check.report_evaluation import (  # noqa: E402
    CRITERIA,
    EvaluationProjectionError,
    evaluation_wiki_projection,
    render_evaluation_html,
    render_evaluation_markdown,
    validate_projection,
)


HASHES = {
    "selection_sha256": "1" * 64,
    "source_sha256": "2" * 64,
    "rubric_sha256": "3" * 64,
    "bundle_sha256": "4" * 64,
}


def evidence(identifier="ev-1", href="#source-ev-1"):
    return {"evidence_id": identifier, "locator": "page 4, paragraph 2", "href": href}


def judgment(score, rationale, *, audit=False):
    row = {
        "score": score,
        "status": "assessed" if score is not None else "unknown",
        "rationale": rationale,
        "evidence_refs": [evidence()] if score is not None else [],
        "confidence": "high" if score is not None else "low",
        "unknown_reason": None if score is not None else "evidence unavailable",
    }
    if audit:
        row["audit_status"] = "not-required"
    return row


def row(criterion_id, score, *, disagreement=False, adj=False):
    r1 = judgment(score, f"R1 reason for {criterion_id}")
    r2_score = 2 if disagreement and score != 2 else (0 if disagreement else score)
    r2 = judgment(r2_score, f"R2 reason for {criterion_id}")
    adjudication = judgment(score, f"ADJ reason for {criterion_id}") if adj else None
    return {
        "criterion_id": criterion_id,
        "final": judgment(score, f"Final reason for {criterion_id}", audit=True),
        "judges": {"R1": r1, "R2": r2, "ADJ": adjudication},
        "disagreement": disagreement,
    }


def dimensions_for(rows, *, complete=True):
    output = {}
    for dimension, start in (("P4", 0), ("P5", 3), ("P6", 6)):
        selected = [
            item["final"]
            for item in rows
            if item["criterion_id"] in CRITERIA[start : start + 3]
        ]
        assessed = sum(item["status"] == "assessed" for item in selected)
        raw_sum = (
            sum(item["score"] for item in selected)
            if len(selected) == 3 and assessed == 3
            else None
        )
        output[dimension] = {
            "score": round(100 * raw_sum / 6, 6)
            if complete and raw_sum is not None
            else None,
            "sum": raw_sum if complete else None,
            "max": 6,
            "assessed": assessed,
            "required": 3,
        }
    return output


def completed_view():
    rows = [row(criterion_id, index % 3) for index, criterion_id in enumerate(CRITERIA)]
    return {
        "rubric_id": "stage2-general-v3",
        "evaluation_status": "completed",
        "dimensions": dimensions_for(rows),
        "rows": rows,
        "provenance": copy.deepcopy(HASHES),
        "errors": [],
    }


class Stage2EvaluationReportTests(unittest.TestCase):
    def test_balanced_nine_criteria_use_fixed_dimension_math_without_total(self):
        view = completed_view()
        projected = validate_projection(view)
        self.assertEqual(
            projected["dimensions"],
            {
                "P4": {"score": 50.0, "sum": 3, "max": 6, "assessed": 3, "required": 3},
                "P5": {"score": 50.0, "sum": 3, "max": 6, "assessed": 3, "required": 3},
                "P6": {"score": 50.0, "sum": 3, "max": 6, "assessed": 3, "required": 3},
            },
        )
        markdown = render_evaluation_markdown(view).decode()
        html = render_evaluation_html(view).decode()
        self.assertNotIn("Total", markdown)
        self.assertNotIn("Total", html)
        self.assertEqual(len(projected["rows"]), 9)

    def test_partial_unknown_is_null_not_zero(self):
        view = completed_view()
        view["rows"][1] = row(CRITERIA[1], None)
        view["dimensions"] = dimensions_for(view["rows"])
        projected = validate_projection(view)
        self.assertEqual(
            projected["dimensions"]["P4"],
            {"score": None, "sum": None, "max": 6, "assessed": 2, "required": 3},
        )
        for rendered in (
            render_evaluation_markdown(view).decode(),
            render_evaluation_html(view).decode(),
        ):
            self.assertIn("Unknown", rendered)
            self.assertNotIn("evidence unavailable</td><td>0", rendered)

    def test_all_final_and_judge_comments_are_retained_with_adjudication(self):
        view = completed_view()
        view["rows"][0] = row(CRITERIA[0], 1, disagreement=True, adj=True)
        view["dimensions"] = dimensions_for(view["rows"])
        markdown = unescape(render_evaluation_markdown(view).decode()).replace("\\", "")
        html = unescape(render_evaluation_html(view).decode())
        wiki = json.dumps(evaluation_wiki_projection(view), ensure_ascii=False)
        for text in (
            f"Final reason for {CRITERIA[0]}",
            f"R1 reason for {CRITERIA[0]}",
            f"R2 reason for {CRITERIA[0]}",
            f"ADJ reason for {CRITERIA[0]}",
            "not-required",
        ):
            self.assertIn(text, markdown)
            self.assertIn(text, html)
            self.assertIn(text, wiki)

    def test_source_text_is_escaped_in_html_and_markdown(self):
        view = completed_view()
        attack = '<script>alert("x")</script> [click](javascript:alert(1)) | table'
        view["rows"][0]["final"]["rationale"] = attack
        view["rows"][0]["judges"]["R1"]["rationale"] = attack
        markdown = render_evaluation_markdown(view).decode()
        html = render_evaluation_html(view).decode()
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("[click](javascript:", markdown)
        self.assertIn("\\[click\\]\\(javascript:alert\\(1\\)\\)", markdown)

    def test_malicious_urls_are_non_clickable_in_all_projections(self):
        for malicious in (
            "javascript:alert(1)",
            "file:///private/report",
            "https://127.0.0.1/private",
            "http://example.org/report",
            "../private/report.html",
            "C:/private/report.html",
            "//server/private/report.html",
            "local.md) <img src=x onerror=alert(1)> (local.md",
            "local.md%29%20%3Cimg%20src=x%20onerror=alert%281%29%3E",
        ):
            with self.subTest(url=malicious):
                view = completed_view()
                for target in (
                    view["rows"][0]["final"],
                    view["rows"][0]["judges"]["R1"],
                ):
                    target["evidence_refs"][0]["href"] = malicious
                projected = evaluation_wiki_projection(view)
                self.assertIsNone(
                    projected["rows"][0]["final"]["evidence_refs"][0]["href"]
                )
                self.assertNotIn(malicious, render_evaluation_markdown(view).decode())
                self.assertNotIn(malicious, render_evaluation_html(view).decode())

    def test_markdown_html_and_wiki_expose_the_same_rows_and_evidence(self):
        view = completed_view()
        view["rows"][4]["final"]["evidence_refs"] = [
            evidence("ev-safe", "sources/evidence.html#ev-safe")
        ]
        markdown = unescape(render_evaluation_markdown(view).decode()).replace("\\", "")
        html = unescape(render_evaluation_html(view).decode())
        wiki = evaluation_wiki_projection(view)
        self.assertEqual(
            [item["criterion_id"] for item in wiki["rows"]], list(CRITERIA)
        )
        for item in wiki["rows"]:
            for rendered in (markdown, html):
                self.assertIn(item["criterion_id"], rendered)
                self.assertIn(item["final"]["rationale"], rendered)
        for rendered in (markdown, html):
            self.assertIn("ev-safe", rendered)
            self.assertIn("sources/evidence.html#ev-safe", rendered)

    def test_pending_and_failed_states_are_readable_without_invented_zero(self):
        for status, errors in (
            ("pending", []),
            ("failed", ["judge transport failed <retry>"]),
        ):
            with self.subTest(status=status):
                view = {
                    "rubric_id": "stage2-general-v3",
                    "evaluation_status": status,
                    "dimensions": dimensions_for([], complete=False),
                    "rows": [],
                    "provenance": {key: None for key in HASHES},
                    "errors": errors,
                }
                for rendered in (
                    render_evaluation_markdown(view).decode(),
                    render_evaluation_html(view).decode(),
                ):
                    self.assertIn("Evaluation not completed", rendered)
                    self.assertIn("Unknown", rendered)
                    self.assertNotIn("| 0 | 0 | 6 |", rendered)
                self.assertEqual(
                    evaluation_wiki_projection(view)["dimensions"]["P4"]["score"], None
                )

    def test_completed_projection_rejects_missing_rows_and_wrong_math(self):
        missing = completed_view()
        missing["rows"].pop()
        with self.assertRaisesRegex(EvaluationProjectionError, "all nine"):
            validate_projection(missing)
        wrong_math = completed_view()
        wrong_math["dimensions"]["P4"]["sum"] = 6
        with self.assertRaisesRegex(EvaluationProjectionError, "does not match"):
            validate_projection(wrong_math)


if __name__ == "__main__":
    unittest.main()

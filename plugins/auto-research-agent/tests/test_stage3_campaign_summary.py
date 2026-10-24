"""Synthetic offline campaign checks; not a scientific evaluation."""

from stage3_campaign_test_support import CampaignFixture
from stage3_plan.campaign import binding
from stage3_plan.campaign_records import record_campaign
from stage3_plan.contracts import Stage3Error
from stage3_plan.evaluation import CRITERIA


class CampaignSummaryTests(CampaignFixture):
    def _malformed_grading_receipt(self):
        unit = next(u for u in self.manifest["units"] if u["role"] == "R1")
        raw = self.root / "malformed-judgment.json"
        raw.write_bytes(b"{bad")
        output = self.root / "failed-receipt"
        with self.assertRaises(Stage3Error):
            record_campaign(
                self.campaign,
                expected_sha256=self.campaign_sha,
                unit_id=unit["unit_id"],
                judgment=raw,
                expected_judgment_sha256=binding(raw)["sha256"],
                output=output,
            )
        return binding(output / "receipt.json")

    def test_format_failure_keeps_configured_grader_error_audit_pending(self):
        self.prepare()
        result = self.summary([self._malformed_grading_receipt()])
        self.assertEqual(len(result["failed_receipts"]), 1)
        self.assertEqual(result["audit_pending_subjects"], 1)
        self.assertEqual(
            [s["audit_pending"] for s in result["subjects"] if s["audit_pending"]],
            [["grader_error"]],
        )
        self.assertFalse(result["usable_for_formal_pairing"])
        self.assertTrue(all(value is False for value in result["policy"].values()))

    def test_format_failure_without_trigger_does_not_add_audit_gate(self):
        self.definition["analysis"]["audit_triggers"] = ["disagreement"]
        self.prepare()
        result = self.summary([self._malformed_grading_receipt()])
        self.assertEqual(len(result["failed_receipts"]), 1)
        self.assertEqual(result["audit_pending_subjects"], 0)

    def test_summary_counts_base_cases_not_variants_questions_or_raters(self):
        self.prepare()
        refs = [
            self.record(unit, score=1 if unit["arm"] == "A" else 2)["receipt_binding"]
            for unit in self.manifest["units"]
            if unit["role"] != "ADJ"
        ]
        result = self.summary(refs)
        for dimension in CRITERIA:
            self.assertEqual(
                result["dimensions"][dimension],
                {
                    "planned_pairs": 2,
                    "observed_scored_pairs": 2,
                    "pair_outcomes": {"win": 2},
                    "planned_independent_base_cases": 1,
                    "base_case_outcomes": {"win": 1},
                },
            )
        self.assertIsNone(result["cost"])
        self.assertIsNone(result["human_interventions"])
        self.assertFalse(result["usable_for_formal_pairing"])

    def test_disagreement_keeps_raw_roles_adjudication_and_audit_pending(self):
        self.prepare()
        units = [
            u
            for u in self.manifest["units"]
            if u["case_id"] == "case-0" and u["arm"] == "A"
        ]
        refs = [
            self.record(u, score=1 if u["role"] == "R1" else 2)["receipt_binding"]
            for u in units
            if u["role"] != "ADJ"
        ]
        before = self.summary(refs)["subjects"][0]
        self.assertEqual(before["adjudication"], "pending")
        adj = next(u for u in units if u["role"] == "ADJ")
        refs.append(self.record(adj)["receipt_binding"])
        subject = self.summary(refs)["subjects"][0]
        self.assertEqual(subject["adjudication"], "recorded")
        self.assertEqual(subject["roles_recorded"], ["ADJ", "R1", "R2"])
        self.assertIn("disagreement", subject["audit_pending"])

    def test_errors_unknown_and_not_run_are_distinct(self):
        self.prepare()
        refs = []
        for unit in self.manifest["units"]:
            if unit["case_id"] == "case-0" and unit["role"] != "ADJ":
                refs.append(
                    self.record(
                        unit,
                        status="grader_error" if unit["arm"] == "A" else "unverifiable",
                    )["receipt_binding"]
                )
        result = self.summary(refs)
        for dimension in CRITERIA:
            self.assertEqual(
                result["dimensions"][dimension]["observed_scored_pairs"], 0
            )
        statuses = [s["score_vector"]["P7"]["status"] for s in result["subjects"]]
        self.assertEqual(set(statuses), {"grader_error", "unverifiable", "not-run"})

    def test_public_record_and_summary_commands_keep_missing_pair_visible(self):
        import io
        import json
        from contextlib import redirect_stderr, redirect_stdout
        from stage3_plan.__main__ import main
        from stage3_plan.campaign import binding

        self.prepare()
        unit = next(u for u in self.manifest["units"] if u["role"] == "R1")
        judgment = self.save("cli-judgment.json", self.judgment(unit))
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                [
                    "campaign-record",
                    "--campaign",
                    str(self.campaign),
                    "--expected-sha256",
                    self.campaign_sha,
                    "--unit-id",
                    unit["unit_id"],
                    "--judgment",
                    str(judgment),
                    "--expected-judgment-sha256",
                    binding(judgment)["sha256"],
                    "--output",
                    str(self.root / "cli-unit"),
                ]
            )
        self.assertEqual(code, 0, stderr.getvalue())
        receipt = json.loads(stdout.getvalue())["receipt_binding"]
        index = self.save(
            "cli-index.json",
            {
                "kind": "Stage3CampaignIndex",
                "schema_version": "1.0.0",
                "campaign_sha256": self.campaign_sha,
                "receipts": [receipt],
                "human_interventions": None,
            },
        )
        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                [
                    "campaign-summary",
                    "--campaign",
                    str(self.campaign),
                    "--expected-sha256",
                    self.campaign_sha,
                    "--index",
                    str(index),
                    "--expected-index-sha256",
                    binding(index)["sha256"],
                ]
            )
        self.assertEqual(code, 0, stderr.getvalue())
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["dimensions"]["P7"]["observed_scored_pairs"], 0)
        self.assertEqual(result["role_record_states"]["R1"]["recorded"], 1)
        self.assertTrue(all(v is False for v in result["policy"].values()))

    def test_subject_failures_and_absent_subjects_keep_their_denominator(self):
        from stage3_plan.campaign import binding

        failure = self.root / "subject-failure.raw"
        failure.write_bytes(b"Injected timeout; no native request dispatched.")
        self.definition["cases"][0]["subjects"] = [
            {"repeat": 1, "arm": "A", "request": None, "failure": binding(failure)}
        ]
        self.definition["cases"][1]["subjects"] = []
        self.prepare()
        result = self.summary([])
        self.assertEqual(result["subject_failures"], 1)
        self.assertEqual(result["subject_not_run"], 3)
        self.assertEqual(result["audit_pending_subjects"], 0)
        self.assertEqual(result["dimensions"]["P7"]["planned_pairs"], 2)
        self.assertEqual(
            result["dimensions"]["P7"]["planned_independent_base_cases"], 1
        )
        self.assertEqual(
            result["dimensions"]["P7"]["base_case_outcomes"], {"incomplete": 1}
        )

"""Opt-in planning metadata tests use injected fixtures, never research calls."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]
from stage3_plan.__main__ import main  # noqa: E402
from stage3_plan.contracts import Stage3Error, canonical_bytes, digest, validate_plan  # noqa: E402
from stage3_plan.planner import draft_synthetic_plan  # noqa: E402
from stage3_plan.planning_conditions import condition_sources  # noqa: E402
from stage3_plan.report import render_plan  # noqa: E402
from stage3_plan.validation import check_plan  # noqa: E402
from stage3_plan_fixtures import make_intake, make_plan  # noqa: E402


def unknown(ref, **changes):
    row = {
        "description": "Material comparability remains to be established.",
        "question_refs": [ref],
        "resolution": "Inspect the relevant product definitions before fixing the design.",
        "blocking": True,
        "unknown_id": "u-material",
        "kind": "material-fit",
        "resolve_before": "material-design",
        "resource_ids": ["resource-1"],
        "owner": None,
        "resolution_evidence_needed": "Product definitions and a defensible unit comparison.",
        "recheck_trigger": "A relevant product or design version changes.",
        "fallback": "Propose a narrower scope and state which question remains unanswered.",
        "scope_change_required": False,
        "disposition": "unresolved",
    }
    row.update(changes)
    return row


class Stage3ConditionsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.plan = make_plan()
        self.plan.update(schema_version="1.1.0", condition_dispositions=[])
        self.intake = make_intake(self.plan)
        self.intake["selection_conditions"] = ["Use the admitted public material."]
        argument = self.intake["scientific_arguments"][0]["argument"]
        argument.update(
            motivation={"text": "Synthetic motivation", "status": "proposal"}
        )
        for key in ("current_state", "gaps", "challenges", "contribution_claims"):
            argument[key] = []
        self.calls = []
        self.add_condition()

    def add_condition(self, *, source_index=0, unknown_ids=None, disposition="planned"):
        source = condition_sources(self.intake)[source_index]
        self.plan["condition_dispositions"].append(
            {
                "condition_ref": source["condition_ref"],
                "source_sha256": source["source_sha256"],
                "question_refs": [self.plan["questions"][0]["question_ref"]],
                "interpretation": "Plan within the saved condition, without asserting permission.",
                "disposition": disposition,
                "response": "Retain the source condition in the evidence and design review.",
                "unknown_ids": [] if unknown_ids is None else unknown_ids,
            }
        )

    def callback(self, **request):
        self.calls.append(request)
        return {
            "raw_response": canonical_bytes(self.plan),
            "provenance": {
                "kind": "synthetic-injected-callback",
                "execution_authorized": False,
            },
        }

    def draft(self, **changes):
        args = dict(
            configuration={"model": "synthetic-model", "reasoning": "medium"},
            plan_id=self.plan["plan_id"],
            schema_version="1.1.0",
        )
        args.update(changes)
        return draft_synthetic_plan(
            self.intake, self.root / "plan", self.callback, **args
        )

    def test_opt_in_schema_is_passed_and_archived_without_observations(self):
        saved = self.draft()
        schema = json.loads((self.root / "plan/schema.json").read_text())
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.1.0")
        self.assertEqual(
            self.calls[0]["schema_path"].name, "stage3-research-plan.v1_1.schema.json"
        )
        prompt = self.calls[0]["prompt"]
        before, context = prompt.split("ADMITTED_CONTEXT\n", 1)
        self.assertIn("condition_dispositions", before)
        self.assertIn("planning_condition_sources", json.loads(context))
        self.assertFalse(saved["manifest"]["execution_authorized"])
        self.assertEqual(
            saved["artifacts"]["plan.json"]["results"][0]["status"], "not-run"
        )
        self.assertIsNone(
            saved["artifacts"]["plan.json"]["results"][0]["observed_value"]
        )

    def test_downgraded_callback_is_retained_as_failed_attempt(self):
        self.plan = make_plan()
        with self.assertRaisesRegex(Stage3Error, "original evidence retained"):
            self.draft()
        self.assertTrue((self.root / "plan/failure.json").is_file())
        self.assertTrue((self.root / "plan/raw-response.json").is_file())
        self.assertFalse((self.root / "plan/plan.json").exists())

    def test_resume_rejects_schema_switch_without_second_callback(self):
        saved = self.draft()
        with self.assertRaisesRegex(Stage3Error, "changed"):
            self.draft(
                schema_version="1.0.0",
                resume_manifest_sha256=saved["manifest"]["manifest_sha256"],
            )
        self.assertEqual(len(self.calls), 1)

    def test_changed_source_condition_fails_even_after_plan_hash_is_recomputed(self):
        self.intake["selection_conditions"][0] = "A different saved condition."
        report = check_plan(self.plan, intake=self.intake)
        self.assertFalse(report["structural_valid"])
        self.assertEqual(len(digest(self.plan)), 64)
        with self.assertRaisesRegex(Stage3Error, "original evidence retained"):
            self.draft()

    def test_source_unresolved_cannot_be_omitted_or_marked_nonblocking(self):
        self.intake["unresolved"] = ["The required material has not been checked."]
        self.assertFalse(check_plan(self.plan, intake=self.intake)["structural_valid"])
        ref = self.plan["questions"][0]["question_ref"]
        self.plan["unknowns"] = [unknown(ref, blocking=False)]
        self.add_condition(source_index=1, unknown_ids=["u-material"])
        self.assertFalse(check_plan(self.plan, intake=self.intake)["structural_valid"])
        self.plan["unknowns"][0]["blocking"] = True
        report = check_plan(self.plan, intake=self.intake)
        self.assertTrue(report["structural_valid"], report["issues"])
        self.assertIn(ref, report["blocked_questions"])

    def test_deferred_resource_and_scope_change_remain_blocked(self):
        ref = self.plan["questions"][0]["question_ref"]
        self.plan["resources"][0]["availability"] = "unknown"
        self.intake["resources"][0]["status"] = "unknown"
        self.plan["question_plans"][0]["resource_uses"][0]["status"] = "unknown"
        self.plan["unknowns"] = [unknown(ref, disposition="deferred")]
        report = check_plan(self.plan, intake=self.intake)
        self.assertTrue(report["structural_valid"], report["issues"])
        self.assertIn(ref, report["blocked_questions"])
        self.plan["unknowns"][0].update(blocking=False, scope_change_required=True)
        self.assertIn(
            ref, check_plan(self.plan, intake=self.intake)["blocked_questions"]
        )

    def test_late_deadline_is_not_a_valid_resolution_schedule(self):
        ref = self.plan["questions"][0]["question_ref"]
        self.plan["unknowns"] = [unknown(ref, resolve_before="plan-review")]
        self.assertFalse(check_plan(self.plan, intake=self.intake)["structural_valid"])

    def test_render_displays_planned_evidence_deadline_and_unassigned_owner(self):
        ref = self.plan["questions"][0]["question_ref"]
        self.plan["unknowns"] = [unknown(ref)]
        saved = self.draft()
        text = render_plan(
            self.root / "plan",
            expected_manifest_sha256=saved["manifest"]["manifest_sha256"],
        )
        for expected in (
            "Conditions and unknown resolution timing",
            "material-design",
            "Unassigned",
            "Product definitions",
            "not verified resolutions",
            "execution_authorized=false",
        ):
            self.assertIn(expected, text)

    def test_legacy_default_closed_shape_and_opt_in_cannot_self_authorize(self):
        legacy = make_plan()
        validate_plan(legacy)
        self.assertNotIn("resolution_schedule", check_plan(legacy))
        legacy["condition_dispositions"] = []
        with self.assertRaises(Stage3Error):
            validate_plan(legacy)
        self.plan["execution_authorized"] = True
        with self.assertRaises(Stage3Error):
            validate_plan(self.plan)

    def test_cli_passes_explicit_schema_version_without_live_native_call(self):
        argv = [
            "draft",
            "--planning-package",
            "input",
            "--delivery",
            "delivery",
            "--expected-source-manifest-sha256",
            "a" * 64,
            "--output",
            "out",
            "--plan-id",
            "p",
            "--model",
            "synthetic",
            "--reasoning",
            "medium",
            "--codex",
            "unused",
            "--codex-home",
            "unused",
            "--capture-dir",
            "unused",
            "--timeout-seconds",
            "1",
            "--plan-schema-version",
            "1.1.0",
        ]
        with (
            patch("stage3_plan.native.NativePlanner") as native,
            patch(
                "stage3_plan.__main__.draft_plan",
                return_value={"manifest": {"execution_authorized": False}},
            ) as draft,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(main(argv), 0)
        native.assert_called_once()
        self.assertEqual(draft.call_args.kwargs["schema_version"], "1.1.0")

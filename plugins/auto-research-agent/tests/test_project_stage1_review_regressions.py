"""Authored review-boundary regressions; no live models, queries or original data."""

from copy import deepcopy
from pathlib import Path
import json
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

import test_project_stage1_execution as fixture
from research_workspace_native import project_stage1_execution as execution_module
from research_workspace_native import project_stage1_review_units as units
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
from stage1_review_test_support import continue_with_diagnostics


class AutomaticReviewBoundaryRegressions(unittest.TestCase):
    def leaf(self, task="leaf"):
        value = fixture.AutomaticReadingUnitTests.snapshot(self)
        value.update(schema_version="1.1.0", task_ref=task)
        return value

    def root(self, children):
        return dict(
            schema_version="1.1.0",
            unit="synthesis",
            task_ref="root",
            child_task_refs=[c["task_ref"] for c in children],
            children=children,
            cluster_ids=["cluster"],
        )

    def test_valid_large_children_fit_and_cannot_be_promoted_to_complete(self):
        children, originals = [], {}
        for task in ("left", "right"):
            snapshot = self.leaf(task)
            value = fixture.answer(snapshot)
            value["limitations"] = [f"{task}-{i}:" + "x" * 496 for i in range(16)]
            raw = canonical(value)
            self.assertLessEqual(len(raw), 16384)
            result = units.validate_result(raw, snapshot)
            originals[task] = deepcopy(result)
            children.append(units.child_context(task, result))
        snapshot = self.root(children)
        self.assertGreater(len(canonical(snapshot)), 10000)
        text = units.prompt(snapshot)
        self.assertLessEqual(len(text.encode("utf8")), 10000)
        self.assertEqual(text, units.prompt(deepcopy(snapshot)))
        shown = json.loads(text.rsplit("\n", 1)[-1])
        self.assertFalse(shown["projection"]["complete"])
        self.assertEqual(
            shown["projection"]["full_children_sha256"], sha(canonical(children))
        )
        value = fixture.answer(shown)
        reviewed = units.validate_result(canonical(value), snapshot)
        self.assertFalse(reviewed["semantic_projection_complete"])
        forged = deepcopy(value)
        forged["decision"] = "include"
        with self.assertRaises(SessionApiError):
            units.validate_result(canonical(forged), snapshot)
        for task, original in originals.items():
            self.assertEqual(
                original["review"]["limitations"][-1], f"{task}-15:" + "x" * 496
            )
        self.assertEqual(snapshot["children"], children)

    def test_new_claim_reasons_are_required_specific_bounded_and_inherited(self):
        snapshot = self.leaf()
        valid = fixture.answer(snapshot)
        checked = units.validate_result(canonical(valid), snapshot)
        for assessment in (
            None,
            {"reason_code": "bad code", "rationale": "Specific."},
            {"reason_code": "scope-partial", "rationale": "partial"},
            {"reason_code": "scope-partial", "rationale": "字" * 400},
        ):
            bad = deepcopy(valid)
            if assessment is None:
                del bad["claims"][0]["assessment"]
            else:
                bad["claims"][0]["assessment"] = assessment
            with self.assertRaises(SessionApiError):
                units.validate_result(canonical(bad), snapshot)
        root = self.root([units.child_context("leaf", checked)])
        value = fixture.answer(json.loads(units.prompt(root).rsplit("\n", 1)[-1]))
        review = units.validate_result(canonical(value), root)
        self.assertEqual(
            review["review"]["claims"][0]["assessment"],
            valid["claims"][0]["assessment"],
        )
        value["claims"][0]["assessment"]["rationale"] = (
            "A different interpretation of the assertion."
        )
        with self.assertRaises(SessionApiError):
            units.validate_result(canonical(value), root)

    def test_full_note_retains_intermediate_root_limits_questions_and_claim_reasons(
        self,
    ):
        leaf = self.leaf()
        first = units.validate_result(canonical(fixture.answer(leaf)), leaf)
        middle = self.root([units.child_context("leaf", first)])
        middle["task_ref"] = "middle"
        value = fixture.answer(json.loads(units.prompt(middle).rsplit("\n", 1)[-1]))
        value["limitations"] = ["Intermediate population limitation must survive."]
        second = units.validate_result(canonical(value), middle)
        root = self.root([units.child_context("middle", second)])
        value = fixture.answer(json.loads(units.prompt(root).rsplit("\n", 1)[-1]))
        value["limitations"] = ["Root measurement limitation must survive."]
        value["questions"] = [
            dict(
                category="preference",
                question="Which outcome is in scope?",
                attempted="Compared the saved confirmed needs.",
                remaining_conflict="Two outcomes need a choice.",
                options=["First outcome", "Second outcome"],
                impact="The scope changes the intended interpretation.",
            )
        ]
        third = units.validate_result(canonical(value), root)
        note = units.full_note(
            dict(leaf=leaf, middle=middle, root=root),
            dict(leaf=first, middle=second, root=third),
        )
        for text in (
            "Intermediate population limitation",
            "Root measurement limitation",
            "Which outcome is in scope?",
            "fixture-scope-partial",
        ):
            self.assertIn(text.encode(), note)

    def test_historical_10_review_still_replays_without_inventing_reasons(self):
        snapshot = self.leaf()
        snapshot["schema_version"] = "1.0.0"
        value = fixture.answer(snapshot)
        checked = units.validate_result(canonical(value), snapshot)
        self.assertEqual(checked["schema_version"], "1.0.0")
        self.assertNotIn("assessment", checked["review"]["claims"][0])
        self.assertNotIn("semantic_projection_complete", checked)


class AutomaticReviewOwnerRegressions(unittest.TestCase):
    fixture = fixture.AutomaticStage1ProductionTests.fixture

    def test_actual_snapshot_binds_confirmed_meaning_and_refuses_rehashed_scope(self):
        case, saved, host, execution, calls = self.fixture()
        ref = saved["ref"]
        work = next(w for w in execution.work_items(ref) if w.get("next_task"))
        snapshot = execution.snapshot(ref, work["next_task"])
        brief = case.intake.brief_binding(ref)["brief"]
        plan = saved["ledger"].coverage_state().plan
        meaning = snapshot["semantic_context"]
        self.assertEqual(meaning["needs"], brief["needs"])
        self.assertEqual(
            meaning["inclusion_criteria"], plan["proposal"]["inclusion_criteria"]
        )
        self.assertEqual(
            meaning["clusters"][0]["question"],
            plan["proposal"]["clusters"][0]["question"],
        )
        self.assertEqual(meaning["brief_content_sha256"], sha(canonical(brief)))
        self.assertIn(brief["needs"][0]["question"], units.prompt(snapshot))
        variants = []
        for scope in ("Authored geography A", "Authored geography B"):
            changed = deepcopy(brief)
            event = changed["decisions"][-1]
            event.update(status="specified", value=scope, user_input=scope)
            event.pop("selected_suggestion", None)
            self.assertEqual(
                changed["original_description"], brief["original_description"]
            )
            variants.append(units.semantic_context(changed, plan))
        self.assertNotEqual(variants[0], variants[1])
        for meaning, scope in zip(
            variants, ("Authored geography A", "Authored geography B")
        ):
            projected = dict(snapshot, semantic_context=meaning)
            self.assertIn(scope, units.prompt(projected))
        altered = deepcopy(snapshot)
        altered["semantic_context"] = variants[1]
        altered["task_ref"] = units.task_ref(
            {k: v for k, v in altered.items() if k != "task_ref"}
        )
        with self.assertRaises(SessionApiError):
            execution.guard(
                ref,
                dict(
                    saved_reading=altered,
                    task_ref=altered["task_ref"],
                    automatic_parent_sha256=execution.permit_sha256,
                ),
            )
        with patch.object(
            execution_module,
            "prompt",
            side_effect=AssertionError("passive reads must not serialize prompts"),
        ):
            execution.read("alice-token", ref)
        oversized = deepcopy(snapshot)
        oversized["semantic_context"]["needs"][0]["question"] = "字" * 4000
        changes = case.intake.db.total_changes
        with patch.object(execution, "snapshot", return_value=oversized):
            with self.assertRaisesRegex(SessionApiError, "auto-review-prompt-bound"):
                execution.register_task(ref, work["next_task"])
        self.assertEqual(case.intake.db.total_changes, changes)
        self.assertEqual(list(execution.root.glob("*.permit.json")), [])
        self.assertEqual(calls, [])

    def test_charged_large_results_recover_read_export_reasons_and_do_not_resend(self):
        original = fixture.answer

        def large(snapshot):
            value = original(snapshot)
            if snapshot["unit"] == "segment":
                value["limitations"] = [
                    f"Child limitation {i}:" + "x" * 480 for i in range(16)
                ]
            else:
                value["limitations"] = [
                    "Saved root limitation remains visible in the complete note."
                ]
            return value

        with patch.object(fixture, "answer", side_effect=large):
            case, saved, host, execution, calls = self.fixture(long_source=True)
            ref = saved["ref"]
            result, failures = continue_with_diagnostics(
                host,
                "alice-token",
                ref,
                run_id="review-fix-synthetic",
                deadline=time.monotonic() + 300,
                max_actions=64,
            )
            self.assertEqual(
                result["reason"],
                "saved-delivery",
                dict(result=result, dispatch_failures=failures),
            )
            count = len(calls)
            self.assertGreater(count, 2)
            progress = execution.read("alice-token", ref)
            self.assertEqual(progress["automatic_resolved"], [])
            self.assertTrue(
                all(
                    not row["semantic_projection_complete"]
                    for row in progress["automatically_recorded"]
                )
            )
            self.assertTrue(
                all(
                    "synthesis-evidence-projection-incomplete" in row["reason_codes"]
                    for row in progress["automatic_pending"]
                )
            )
            exported = execution.export_notes(
                "alice-token", ref, case.root / "new-full-notes"
            )
            self.assertEqual(exported["note_count"], 2)
            state = case.intake._load("alice", ref)
            claim_count = 0
            for applied in state["stage1_automatic_production"]["applied"].values():
                note = Path(applied["note_path"]).read_bytes()
                self.assertIn(b"Child limitation 15:", note)
                self.assertIn(b"Saved root limitation", note)
                for cid in applied["exact_spans"]:
                    claim_count += 1
                    assessment = saved["ledger"].event(cid)["assessment"]
                    self.assertEqual(assessment["reason_code"], "fixture-scope-partial")
                    self.assertIn(assessment["rationale"].encode(), note)
            self.assertGreater(claim_count, 0)
            # Assert the actual native records exporter, rather than a filename
            # belonging only to the separate legacy workspace review exporter.
            exported_claims = {}
            for offer in state["stage1_delivery_offers"].values():
                records = json.loads(Path(offer["records_path"]).read_bytes())
                for row in records.get("core_claim_history", []):
                    event = row["payload"]
                    exported_claims[event["event_id"]] = event
            for applied in state["stage1_automatic_production"]["applied"].values():
                for cid in applied["exact_spans"]:
                    self.assertEqual(
                        exported_claims[cid]["assessment"],
                        saved["ledger"].event(cid)["assessment"],
                    )
                    self.assertEqual(exported_claims[cid]["schema_version"], "1.1.0")
            # Actually release/reopen the SQLite and model owners. Reading,
            # exporting and replaying charged results must survive the restart.
            old_models = host.project_models
            old_models.close()
            case.reopen()
            models = fixture.ProjectModelService(
                case.intake,
                provider_factory=old_models.factory,
                model="synthetic-reader",
                local_cap_seconds=30,
                reading_records=case.producer,
            )
            self.addCleanup(models.close)
            execution = execution_module.ProjectStage1ExecutionService(
                case.stage1,
                models,
                case.producer,
                permit_path=execution.root / "parent.json",
                permit_sha256=execution.permit_sha256,
                output_root=execution.root,
            )
            host.projects, host.project_models = case.intake, models
            host.project_stage1, host.project_stage1_records = (
                case.stage1,
                case.producer,
            )
            host.project_stage1_delivery = case.delivery
            host.project_records_prepare = fixture.ProjectRecordsPrepareService(
                case.producer
            )
            host.project_stage1_execution = execution
            self.assertEqual(
                execution.read("alice-token", ref)["notes"], progress["notes"]
            )
            again = host.continue_stage1(
                "alice-token",
                ref,
                run_id="review-fix-synthetic",
                deadline=time.monotonic() + 30,
                max_actions=64,
            )
            self.assertEqual(again["reason"], "saved-delivery", again)
            self.assertEqual(len(calls), count)
            self.assertEqual(
                execution.read("alice-token", ref)["model_calls_reserved"], count
            )


if __name__ == "__main__":
    unittest.main()

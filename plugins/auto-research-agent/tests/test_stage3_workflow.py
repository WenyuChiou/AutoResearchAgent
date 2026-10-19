"""Offline workflow mechanics; synthetic records do not authenticate humans."""

import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]
from stage3_plan.__main__ import main  # noqa: E402
from stage3_plan.contracts import Stage3Error, canonical_bytes, digest  # noqa: E402
from stage3_plan.planner import draft_plan, draft_synthetic_plan  # noqa: E402
from stage3_plan.preparation import prepare_ab, file_binding  # noqa: E402
from stage3_plan.workflow import advance_workflow, inspect_workflow, start_workflow  # noqa: E402
from stage3_plan_fixtures import make_intake, make_plan  # noqa: E402
from test_stage3_plan_decision import semantic_review  # noqa: E402


class Stage3WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.plan = make_plan(question_count=2, shared_path=True)
        self.intake = make_intake(self.plan)
        # Only the strict-admission seam is mocked. No real selection is claimed.
        self.admission = patch(
            "stage3_plan.workflow.admit_intake",
            side_effect=lambda *a, **k: copy.deepcopy(self.intake),
        )
        self.admission.start()
        self.addCleanup(self.admission.stop)
        self.native = patch(
            "stage3_plan.native.NativePlanner.__call__",
            side_effect=AssertionError("no native calls permitted"),
        )
        self.native_call = self.native.start()
        self.addCleanup(self.native.stop)
        self.current = self.root / "checkpoint-1.json"
        self.saved = start_workflow(
            "source",
            "delivery",
            expected_source_manifest_sha256=self.plan["source_manifest_sha256"],
            output=self.current,
            workflow_id="synthetic-workflow",
        )

    def transition(self, action, binding):
        output = (
            self.root / f"checkpoint-{self.saved['checkpoint']['revision'] + 1}.json"
        )
        self.saved = advance_workflow(
            self.current,
            expected_checkpoint_sha256=self.saved["checkpoint_sha256"],
            action=action,
            output=output,
            binding=binding,
        )
        self.current = output
        return self.saved["checkpoint"]["status"]

    def attach_plan(self, *, failed=False, synthetic=False):
        self.plan_dir = self.root / "plan"
        callback = (
            Mock(side_effect=RuntimeError("original planning failure"))
            if failed
            else Mock(
                return_value={
                    "raw_response": canonical_bytes(self.plan),
                    "provenance": {"kind": "synthetic"},
                }
            )
        )
        callback.request_context = {"kind": "synthetic-workflow-test"}
        with patch("stage3_plan.intake.admit_intake", return_value=self.intake):
            kwargs = dict(
                output_dir=self.plan_dir,
                callback=callback,
                configuration={"model": "synthetic-model", "reasoning": "medium"},
                plan_id=self.plan["plan_id"],
            )
            if synthetic:
                saved = draft_synthetic_plan(
                    self.intake,
                    self.plan_dir,
                    callback,
                    configuration=kwargs["configuration"],
                    plan_id=self.plan["plan_id"],
                )
            elif failed:
                with self.assertRaises(Stage3Error):
                    draft_plan(
                        "source",
                        "delivery",
                        expected_manifest_sha256=self.plan["source_manifest_sha256"],
                        **kwargs,
                    )
                from stage3_plan.storage import read_json

                saved = {"manifest": read_json(self.plan_dir / "manifest.json")}
            else:
                saved = draft_plan(
                    "source",
                    "delivery",
                    expected_manifest_sha256=self.plan["source_manifest_sha256"],
                    **kwargs,
                )
        self.callback = callback
        return self.transition(
            "attach-plan",
            {
                "package": str(self.plan_dir),
                "manifest_sha256": saved["manifest"]["manifest_sha256"],
            },
        )

    def file_ref(self, name, value):
        path = self.root / name
        path.write_bytes(canonical_bytes(value))
        return {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    def definition(self):
        rubric = PLUGIN / "evals/rubrics/stage23-general.v1.json"
        return {
            "kind": "Stage3ABPreparationDefinition",
            "schema_version": "1.0.0",
            "case_id": "synthetic-case",
            "intake_sha256": digest(self.intake),
            "common_prompt": "Plan the selected scientific questions using their saved context.",
            "runtime": {
                "model": "synthetic-model",
                "reasoning": "medium",
                "tool_policy": "none",
                "timeout_seconds": 60,
            },
            "arms": {
                arm: {
                    "build_sha256": arm.lower() * 64,
                    "protocol": "Generic planning"
                    if arm == "A"
                    else "Question-linked planning harness",
                }
                for arm in ("A", "B")
            },
            "rubric": {
                "path": str(rubric),
                "sha256": hashlib.sha256(rubric.read_bytes()).hexdigest(),
            },
            "judges": {
                role: {"model": "synthetic-judge", "reasoning": "medium"}
                for role in ("R1", "R2", "ADJ")
            },
            "decision_rule": "Draft rule for later formal protocol review; no result exists.",
            "audit_triggers": ["major-error", "judge-disagreement", "close-pair"],
        }

    def test_start_and_resume_reuse_selection_without_native_calls(self):
        before = self.current.read_bytes()
        result = inspect_workflow(
            self.current, expected_checkpoint_sha256=self.saved["checkpoint_sha256"]
        )
        self.assertEqual(
            result["checkpoint"]["status"]["planning_status"], "awaiting-plan"
        )
        self.assertEqual(
            result["checkpoint"]["status"]["selected_candidates"],
            self.intake["selected_candidates"],
        )
        self.assertEqual(result["resume_action"], "verified-replay-no-calls")
        self.assertEqual(self.current.read_bytes(), before)
        self.native_call.assert_not_called()

    def test_plan_review_and_replay_preserve_no_execution(self):
        original = self.current
        original_bytes = original.read_bytes()
        self.assertEqual(self.attach_plan()["planning_status"], "draft")
        review = semantic_review(self.plan, self.intake)
        status = self.transition("attach-review", self.file_ref("review.json", review))
        self.assertEqual(status["planning_status"], "ready-for-plan-review")
        self.assertFalse(status["execution_authorized"])
        self.assertNotEqual(status["planning_status"], "plan-confirmed")
        inspect_workflow(
            self.current, expected_checkpoint_sha256=self.saved["checkpoint_sha256"]
        )
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertEqual(self.callback.call_count, 1)
        self.native_call.assert_not_called()

    def test_unknown_review_stays_needs_information(self):
        self.attach_plan()
        status = self.transition(
            "attach-review",
            self.file_ref(
                "review.json", semantic_review(self.plan, self.intake, status="unknown")
            ),
        )
        self.assertEqual(status["planning_status"], "needs-information")

    def test_failed_planning_attempt_is_retained_as_failed(self):
        status = self.attach_plan(failed=True)
        self.assertEqual(status["planning_status"], "failed")
        self.assertIn(
            "original planning failure", (self.plan_dir / "failure.json").read_text()
        )
        self.native_call.assert_not_called()

    def test_synthetic_scope_cannot_be_attached_as_strict_plan(self):
        with self.assertRaisesRegex(Stage3Error, "strict selected intake"):
            self.attach_plan(synthetic=True)

    def test_external_hash_tampering_and_rehashed_status_forgery_fail(self):
        with self.assertRaises(Stage3Error):
            inspect_workflow(self.current, expected_checkpoint_sha256="b" * 64)
        forged = copy.deepcopy(self.saved["checkpoint"])
        forged["status"]["planning_status"] = "plan-confirmed"
        self.current.write_bytes(canonical_bytes(forged))
        with self.assertRaisesRegex(Stage3Error, "projection/status"):
            inspect_workflow(self.current, expected_checkpoint_sha256=digest(forged))

    def test_stale_source_or_review_is_not_reused(self):
        self.attach_plan()
        review = semantic_review(self.plan, self.intake)
        review["plan_sha256"] = "b" * 64
        with self.assertRaisesRegex(Stage3Error, "review binding"):
            self.transition("attach-review", self.file_ref("wrong-review.json", review))
        self.intake["questions"][0]["text"] = "Changed question"
        with self.assertRaises(Stage3Error):
            inspect_workflow(
                self.current, expected_checkpoint_sha256=self.saved["checkpoint_sha256"]
            )

    def test_review_without_plan_and_output_overwrite_are_refused(self):
        with self.assertRaisesRegex(Stage3Error, "requires a saved plan"):
            self.transition("attach-review", self.file_ref("review.json", {}))
        with self.assertRaises(FileExistsError):
            start_workflow(
                "source",
                "delivery",
                expected_source_manifest_sha256=self.plan["source_manifest_sha256"],
                output=self.current,
                workflow_id="another",
            )

    def test_source_revision_clears_plan_review_and_ab_but_keeps_history(self):
        self.attach_plan()
        old_checkpoint = self.current
        new_intake = copy.deepcopy(self.intake)
        new_intake["resources"][0]["name"] = "New bounded condition"
        from stage3_plan.workflow import admit_intake as original_admit

        def admit(package, delivery, **kwargs):
            return (
                new_intake
                if str(package).endswith("new-source")
                else original_admit(package, delivery, **kwargs)
            )

        with patch("stage3_plan.workflow.admit_intake", side_effect=admit):
            status = self.transition(
                "revise-source",
                {
                    "package": "new-source",
                    "delivery": "delivery",
                    "manifest_sha256": "c" * 64,
                },
            )
            inspect_workflow(
                self.current, expected_checkpoint_sha256=self.saved["checkpoint_sha256"]
            )
            forged = copy.deepcopy(self.saved["checkpoint"])
            forged["revision_impact"]["confirmation_invalidated"] = False
            forged_path = self.root / "forged-impact.json"
            forged_path.write_bytes(canonical_bytes(forged))
            with self.assertRaisesRegex(Stage3Error, "revision impact"):
                inspect_workflow(forged_path, expected_checkpoint_sha256=digest(forged))
        self.assertEqual(status["planning_status"], "awaiting-plan")
        self.assertIsNone(self.saved["checkpoint"]["bindings"]["plan"])
        self.assertTrue(
            self.saved["checkpoint"]["revision_impact"]["confirmation_invalidated"]
        )
        self.assertTrue(old_checkpoint.is_file())

    def test_ab_preparation_has_three_unrun_pairs_and_separate_null_scores(self):
        status = self.transition(
            "prepare-ab", self.file_ref("definition.json", self.definition())
        )
        prepared = status["ab_preparation"]
        self.assertEqual(status["evaluation_status"], "preparation-only")
        self.assertEqual(
            [p["order"] for p in prepared["pairs"]],
            [["A", "B"], ["B", "A"], ["A", "B"]],
        )
        for pair in prepared["pairs"]:
            for run in pair["runs"].values():
                self.assertEqual(
                    run,
                    {
                        "status": "not-run",
                        "scores": {"P7": None, "P8": None, "P9": None},
                    },
                )
        self.assertFalse(prepared["formal_execution_enabled"])
        self.native_call.assert_not_called()

    def test_ab_rejects_different_input_execution_fields_and_rubric_drift(self):
        for change in (
            {"intake_sha256": "b" * 64},
            {"execution_authorized": True},
            {"scores": {"P7": 2}},
        ):
            with self.subTest(change=change):
                definition = self.definition()
                definition.update(change)
                with self.assertRaises(Stage3Error):
                    prepare_ab(definition, self.intake)
        definition = self.definition()
        definition["rubric"]["sha256"] = "b" * 64
        with self.assertRaises(Stage3Error):
            prepare_ab(definition, self.intake)

    def test_cli_inspection_and_failure_never_launch_models(self):
        with redirect_stdout(io.StringIO()) as output:
            code = main(
                [
                    "workflow-inspect",
                    "--checkpoint",
                    str(self.current),
                    "--expected-checkpoint-sha256",
                    self.saved["checkpoint_sha256"],
                ]
            )
        self.assertEqual(code, 0)
        self.assertIn("verified-replay-no-calls", output.getvalue())
        with redirect_stderr(io.StringIO()) as errors:
            code = main(
                [
                    "workflow-inspect",
                    "--checkpoint",
                    str(self.current),
                    "--expected-checkpoint-sha256",
                    "b" * 64,
                ]
            )
        self.assertEqual(code, 1)
        self.assertIn('"execution_authorized": false', errors.getvalue())
        self.native_call.assert_not_called()

    def test_pinned_json_uses_the_single_verified_snapshot(self):
        from stage3_plan.storage import read_bytes

        ref = self.file_ref("race.json", {"value": "pinned"})

        def replace_after_read(path):
            raw = read_bytes(path)
            Path(path).write_bytes(canonical_bytes({"value": "replacement"}))
            return raw

        with patch(
            "stage3_plan.preparation.read_bytes", side_effect=replace_after_read
        ) as read:
            self.assertEqual(
                file_binding(ref["path"], ref["sha256"]), {"value": "pinned"}
            )
        self.assertEqual(read.call_count, 1)
        for raw in (b'{"v":1,"v":2}', b'{"v":NaN}'):
            Path(ref["path"]).write_bytes(raw)
            with self.assertRaises(Stage3Error):
                file_binding(ref["path"], hashlib.sha256(raw).hexdigest())

    def test_rehashed_impact_and_illegal_transition_are_rejected(self):
        forged = copy.deepcopy(self.saved["checkpoint"])
        forged["revision_impact"] = {
            "confirmation_invalidated": False,
            "execution_authorized": True,
        }
        self.current.write_bytes(canonical_bytes(forged))
        with self.assertRaisesRegex(Stage3Error, "revision impact"):
            inspect_workflow(self.current, expected_checkpoint_sha256=digest(forged))
        self.current.write_bytes(canonical_bytes(self.saved["checkpoint"]))
        self.transition(
            "prepare-ab", self.file_ref("definition.json", self.definition())
        )
        forged = copy.deepcopy(self.saved["checkpoint"])
        forged["action"] = "attach-review"
        self.current.write_bytes(canonical_bytes(forged))
        with self.assertRaisesRegex(Stage3Error, "unrelated bindings"):
            inspect_workflow(self.current, expected_checkpoint_sha256=digest(forged))

    def test_missing_ancestor_and_oversized_history_fail_closed(self):
        first = self.current
        self.transition(
            "prepare-ab", self.file_ref("definition.json", self.definition())
        )
        self.transition(
            "prepare-ab", self.saved["checkpoint"]["bindings"]["ab_definition"]
        )
        first.unlink()
        with self.assertRaises(Stage3Error):
            inspect_workflow(
                self.current, expected_checkpoint_sha256=self.saved["checkpoint_sha256"]
            )
        forged = copy.deepcopy(self.saved["checkpoint"])
        forged["revision"] = 65
        self.current.write_bytes(canonical_bytes(forged))
        with self.assertRaises(Stage3Error):
            inspect_workflow(self.current, expected_checkpoint_sha256=digest(forged))

    def test_malformed_rubric_stays_a_structured_cli_failure(self):
        definition = self.definition()
        rubric = json.loads(Path(definition["rubric"]["path"]).read_bytes())
        rubric["criteria"][0]["id"] = []
        definition["rubric"] = self.file_ref("bad-rubric.json", rubric)
        ref = self.file_ref("definition.json", definition)
        with redirect_stderr(io.StringIO()) as errors:
            code = main(
                [
                    "workflow-prepare-ab",
                    "--checkpoint",
                    str(self.current),
                    "--expected-checkpoint-sha256",
                    self.saved["checkpoint_sha256"],
                    "--artifact",
                    ref["path"],
                    "--expected-artifact-sha256",
                    ref["sha256"],
                    "--output",
                    str(self.root / "unused.json"),
                ]
            )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(errors.getvalue())["status"], "failed")


class StrictLegacyWorkflowTest(unittest.TestCase):
    def test_actual_strict_structured_selection_enters_workflow_without_mocks(self):
        from stage2_common import canonical_hash
        from stage2_workflow import (
            initialize_workflow,
            inspect_workflow as inspect_stage2,
        )
        from stage2_workflow.orchestration import prepare_review_batch
        from stage2_workflow.planning_handoff import prepare_planning_handoff
        from test_stage2_delivery import Stage2DeliveryTests
        from test_stage2_planning_handoff import Stage2PlanningHandoffTests
        from test_stage2_scientific_argument import Stage2ScientificArgumentTests

        fixture = Stage2DeliveryTests(
            "test_full_cycle_binds_package_and_preserves_embedded_checker"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        structured = Stage2ScientificArgumentTests(
            "test_packet_2_5_is_opt_in_and_requires_a_core_closed_argument"
        )
        structured.setUp()
        self.addCleanup(structured.doCleanups)
        fixture.packet = copy.deepcopy(structured.packet)
        fixture.sources = structured.fixture.source_root
        candidate = fixture.packet["candidates"][0]
        candidate["candidate_id"] = "candidate-1"
        for review in fixture.packet["prior_work_reviews"]:
            review["candidate_id"] = candidate["candidate_id"]
            review["candidate_sha256"] = canonical_hash(candidate)
        fixture.packet_path.write_bytes(canonical_bytes(fixture.packet))
        fixture.workflow = fixture.root / "structured-workflow"
        initialize_workflow(
            fixture.packet_path,
            fixture.sources,
            fixture.workflow,
            {"model": "synthetic", "reasoning": "medium"},
            {"path": "policy.json", "sha256": "a" * 64},
            canonical_hash(fixture.packet),
        )
        fixture.state = inspect_stage2(fixture.workflow)
        fixture.snapshot = fixture.state["latest_snapshot"]["event"]["payload"][
            "snapshot_sha256"
        ]
        fixture.batch = prepare_review_batch(
            fixture.packet,
            fixture.snapshot,
            [
                {
                    "candidate_id": candidate["candidate_id"],
                    "candidate_version": candidate["version"],
                    "included": True,
                    "distance": 0,
                    "reason": "Synthetic structured selection.",
                }
            ],
            "structured-seed",
        )
        delivery = fixture.root / "structured-delivery"
        reviews, resolutions = fixture._complete_inputs()
        evidence_id = fixture.packet["evidence"][0]["evidence_id"]
        for row in reviews:
            for finding in row["review"]["assessment"]["checks"].values():
                finding["evidence_ids"] = [evidence_id]
        resolution = resolutions["candidate_resolutions"][0]["resolution"]
        resolution["evidence_ids"] = [evidence_id]
        for finding in resolution["assessment"]["checks"].values():
            finding["evidence_ids"] = [evidence_id]
        resolution["review_sha256s"] = [
            canonical_hash(row["review"]) for row in reviews
        ]
        manifest = fixture._build(delivery, reviews, resolutions)
        interaction, _, interaction_hash = Stage2PlanningHandoffTests._record_choice(
            fixture.root, fixture.workflow, delivery, manifest, fixture.state, candidate
        )
        package = fixture.root / "structured-package"
        prepared = prepare_planning_handoff(
            delivery,
            interaction,
            expected_delivery_manifest_sha256=manifest["manifest_sha256"],
            expected_interaction_file_sha256=interaction_hash,
            output_dir=package,
        )
        output = fixture.root / "structured-workflow.json"
        saved = start_workflow(
            package,
            delivery,
            expected_source_manifest_sha256=prepared["manifest"]["manifest_sha256"],
            output=output,
            workflow_id="strict-structured-synthetic",
        )
        replay = inspect_workflow(
            output, expected_checkpoint_sha256=saved["checkpoint_sha256"]
        )
        self.assertEqual(
            replay["checkpoint"]["status"]["planning_status"], "awaiting-plan"
        )
        self.assertEqual(
            replay["checkpoint"]["status"]["question_refs"],
            [f"{candidate['candidate_id']}@{candidate['version']}/question-core"],
        )
        self.assertFalse(replay["checkpoint"]["execution_authorized"])

    def test_actual_strict_saved_delivery_retains_legacy_unknowns(self):
        from test_stage2_planning_handoff import Stage2PlanningHandoffTests

        fixture = Stage2PlanningHandoffTests(
            "test_legacy_package_is_explicit_about_unknown_context_and_no_authority"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        prepared = fixture.prepare()
        saved = start_workflow(
            fixture.output,
            fixture.delivery,
            expected_source_manifest_sha256=prepared["manifest"]["manifest_sha256"],
            output=fixture.fixture.root / "workflow.json",
            workflow_id="strict-synthetic-delivery",
        )
        self.assertEqual(
            saved["checkpoint"]["status"]["planning_status"], "needs-information"
        )
        self.assertFalse(saved["checkpoint"]["execution_authorized"])


if __name__ == "__main__":
    unittest.main()

"""CLI coverage for explicit opt-in Stage 2 v3 entry points."""

import json
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ruff: noqa: E402 -- repository CLIs are intentionally imported without install.
from stage2_eval.__main__ import main as eval_main
from stage2_live.__main__ import main as live_main
from stage2_workflow.__main__ import main as workflow_main
from stage2_workflow import initialize_workflow, inspect_workflow
from stage2_check.run import build_selection
from stage2_common import Stage2Error, canonical_hash
from stage2_fixture_helpers import write_stage2_fixture


class Stage2V3CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def save(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def workflow_selection(self, name, *, candidate_count=1, revise_first=False):
        source_root = self.root / (name + "-sources")
        packet = write_stage2_fixture(
            source_root,
            candidate_count=candidate_count,
            revise_first=revise_first,
        )
        packet["unresolved"] = []
        packet_path = self.save(name + "-packet.json", packet)
        run = self.root / (name + "-run")
        initialize_workflow(
            packet_path,
            source_root,
            run,
            {"model": "test-model", "reasoning": "medium"},
            {"path": "policy.json", "sha256": "a" * 64},
            canonical_hash(packet),
        )
        state = inspect_workflow(run)
        selection = build_selection(state["latest_snapshot"]["checker"])
        return run, source_root, state, selection

    def test_help_paths_do_not_dispatch_models(self):
        with patch("stage1_eval.model_calls.call_model_v31") as model:
            for entry in (live_main, eval_main, workflow_main):
                with self.subTest(entry=entry.__module__):
                    with self.assertRaises(SystemExit) as stopped:
                        entry(["--help"])
                    self.assertEqual(stopped.exception.code, 0)
            model.assert_not_called()

    def test_daily_v3_dispatches_with_external_replay_receipt(self):
        selection = self.save("selection.json", {"selection": "synthetic"})
        policy = self.save("policy.json", {"policy": "synthetic"})
        receipt = self.root / "receipts" / "daily.json"
        with patch(
            "stage2_live.daily_v3.run_daily_evaluation_v3",
            return_value={
                "status": "complete",
                "formal_ready": False,
                "replay_receipt": {
                    "result_sha256": "a" * 64,
                    "unit_receipts": {"r1": "b" * 64},
                },
            },
        ) as run:
            code = live_main(
                [
                    "daily-v3",
                    "--selection",
                    str(selection),
                    "--source-root",
                    str(self.root / "sources"),
                    "--codex",
                    "codex",
                    "--r1-home",
                    str(self.root / "r1"),
                    "--r2-home",
                    str(self.root / "r2"),
                    "--adj-home",
                    str(self.root / "adj"),
                    "--model",
                    "model",
                    "--reasoning",
                    "high",
                    "--policy",
                    str(policy),
                    "--output",
                    str(self.root / "daily-output"),
                    "--replay-receipt-output",
                    str(receipt),
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(
            run.call_args.args[:2],
            ({"selection": "synthetic"}, str(self.root / "sources")),
        )
        self.assertFalse(run.call_args.kwargs["resume"])
        self.assertEqual(json.loads(receipt.read_text())["result_sha256"], "a" * 64)

    def test_daily_v3_resume_requires_external_receipt(self):
        selection = self.save("selection.json", {})
        policy = self.save("policy.json", {})
        with patch("stage2_live.daily_v3.run_daily_evaluation_v3") as run:
            code = live_main(
                [
                    "daily-v3",
                    "--selection",
                    str(selection),
                    "--source-root",
                    str(self.root),
                    "--codex",
                    "codex",
                    "--r1-home",
                    str(self.root / "r1"),
                    "--r2-home",
                    str(self.root / "r2"),
                    "--adj-home",
                    str(self.root / "adj"),
                    "--model",
                    "model",
                    "--reasoning",
                    "high",
                    "--policy",
                    str(policy),
                    "--output",
                    str(self.root / "daily-output"),
                    "--replay-receipt-output",
                    str(self.root / "receipt.json"),
                    "--resume",
                ]
            )
        self.assertEqual(code, 2)
        run.assert_not_called()

    def test_calibrate_v3_and_source_update_dispatch_exact_signatures(self):
        dataset = self.save("dataset.json", {"cases": []})
        reference = self.save("reference.json", {"judgments": []})
        policy = self.save("policy.json", {})
        with patch(
            "stage2_live.rubric_quality_v3.run_quality_v3",
            return_value={"status": "complete", "formal_ready": False},
        ) as quality:
            code = live_main(
                [
                    "calibrate-v3",
                    "--dataset",
                    str(dataset),
                    "--reference",
                    str(reference),
                    "--codex",
                    "codex",
                    "--r1-home",
                    str(self.root / "r1"),
                    "--r2-home",
                    str(self.root / "r2"),
                    "--model",
                    "model",
                    "--reasoning",
                    "high",
                    "--policy",
                    str(policy),
                    "--output",
                    str(self.root / "quality"),
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(quality.call_args.args, ({"cases": []}, {"judgments": []}))
        self.assertEqual(
            quality.call_args.kwargs["output_dir"], str(self.root / "quality")
        )

        files = {
            name: self.save(name + ".json", value)
            for name, value in (
                ("packet", {"packet": True}),
                ("additions", [{"source": True}]),
                ("revisions", [{"candidate": True}]),
                ("impact", {"candidate": "affected"}),
            )
        }
        with patch(
            "stage2_live.source_updates.prepare_source_update",
            return_value={"status": "complete", "review_required": True},
        ) as update:
            code = live_main(
                [
                    "source-update",
                    "--packet",
                    str(files["packet"]),
                    "--source-root",
                    str(self.root / "old-sources"),
                    "--additions",
                    str(files["additions"]),
                    "--revisions",
                    str(files["revisions"]),
                    "--impact",
                    str(files["impact"]),
                    "--output",
                    str(self.root / "updated"),
                    "--expected-packet-sha256",
                    "c" * 64,
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(update.call_args.kwargs["expected_packet_sha256"], "c" * 64)
        self.assertIsNone(update.call_args.kwargs["unresolved"])

    def test_prepare_profile_workspace_is_opt_in_and_legacy_call_is_identical(self):
        common = [
            "prepare-profile",
            "--destination",
            str(self.root / "profile"),
            "--skills-response",
            str(self.root / "skills.json"),
            "--skills-sha256",
            "a" * 64,
        ]
        with patch(
            "stage2_live.__main__.prepare_profile",
            return_value={"kind": "Stage2Profile", "formal_ready": False},
        ) as prepare:
            code = live_main(common + ["--output", str(self.root / "legacy.json")])
        self.assertEqual(code, 0)
        prepare.assert_called_once_with(
            str(self.root / "profile"), str(self.root / "skills.json"), "a" * 64
        )

        workspace = self.root / "workspace"
        with patch(
            "stage2_live.__main__.prepare_profile",
            return_value={"kind": "Stage2Profile", "formal_ready": False},
        ) as prepare:
            code = live_main(
                common
                + [
                    "--workspace",
                    str(workspace),
                    "--output",
                    str(self.root / "workspace.json"),
                ]
            )
        self.assertEqual(code, 0)
        prepare.assert_called_once_with(
            str(self.root / "profile"),
            str(self.root / "skills.json"),
            "a" * 64,
            workspace=str(workspace),
        )

    def test_verify_quality_v3_dispatches_read_only_with_external_inputs(self):
        receipt = self.save("quality-receipt.json", {"receipt": True})
        dataset = self.save("quality-dataset.json", {"cases": []})
        reference = self.save("quality-reference.json", {"judgments": []})
        config = self.save("quality-config.json", {"config": True})
        output = self.root / "quality-verification.json"
        verified = {
            "authenticated": True,
            "qa_pass": True,
            "formal_ready": False,
            "actual_model_attempts": 18,
        }
        with (
            patch(
                "stage2_live.v3_replay.verify_quality_v3", return_value=verified
            ) as verify,
            patch("stage1_eval.model_calls.call_model_v31") as model,
        ):
            code = live_main(
                [
                    "verify-quality-v3",
                    "--root",
                    str(self.root / "native-calls"),
                    "--receipt",
                    str(receipt),
                    "--dataset",
                    str(dataset),
                    "--reference",
                    str(reference),
                    "--config",
                    str(config),
                    "--output",
                    str(output),
                ]
            )
        self.assertEqual(code, 0)
        verify.assert_called_once_with(
            str(self.root / "native-calls"),
            {"receipt": True},
            dataset={"cases": []},
            reference={"judgments": []},
            expected_config={"config": True},
        )
        model.assert_not_called()
        self.assertEqual(json.loads(output.read_text()), verified)

    def test_prepare_content_v3_uses_genuine_packet_validation(self):
        source_root = self.root / "sources"
        packet = write_stage2_fixture(source_root, candidate_count=1)
        packet_path = self.save("packet.json", packet)
        output = self.root / "content-view.json"
        code = eval_main(
            [
                "prepare-content-v3",
                "--packet",
                str(packet_path),
                "--source-root",
                str(source_root),
                "--subject-id",
                "opaque-cli-v3",
                "--input-sha256",
                "1" * 64,
                "--config-sha256",
                "2" * 64,
                "--output",
                str(output),
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(output.read_text())["rubric_id"], "stage2-general-v3"
        )
        packet["evidence"][0]["quote"] = "not an exact source span"
        packet_path.write_text(json.dumps(packet))
        with self.assertRaisesRegex(Stage2Error, "exact contiguous"):
            eval_main(
                [
                    "prepare-content-v3",
                    "--packet",
                    str(packet_path),
                    "--source-root",
                    str(source_root),
                    "--subject-id",
                    "opaque-cli-v3",
                    "--input-sha256",
                    "1" * 64,
                    "--config-sha256",
                    "2" * 64,
                    "--output",
                    str(self.root / "invalid.json"),
                ]
            )

    def test_pure_v3_merge_bundle_and_pair_commands_dispatch_without_models(self):
        source_root = self.root / "sources"
        packet = write_stage2_fixture(source_root, candidate_count=1)
        packet_path = self.save("packet.json", packet)
        values = {
            name: self.save(name + ".json", {name: True})
            for name in ("content-view", "action-view", "r1", "r2")
        }
        merged_output = self.root / "merged.json"
        with (
            patch(
                "stage2_eval.evaluation_v3.merge_judgments_v3",
                return_value={"kind": "Stage2JudgeBundle", "diagnostic_only": True},
            ) as merge,
            patch("stage1_eval.model_calls.call_model_v31") as model,
        ):
            code = eval_main(
                [
                    "merge-v3",
                    "--packet",
                    str(packet_path),
                    "--source-root",
                    str(source_root),
                    "--content-view",
                    str(values["content-view"]),
                    "--action-view",
                    str(values["action-view"]),
                    "--r1",
                    str(values["r1"]),
                    "--r2",
                    str(values["r2"]),
                    "--output",
                    str(merged_output),
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(merge.call_args.args[0], {"r1": True})
        model.assert_not_called()

        bundle = self.save("judge-bundle.json", {"bundle": True})
        validation_output = self.root / "bundle-validation.json"
        with patch("stage2_eval.evaluation_v3.validate_bundle_v3") as validate:
            code = eval_main(
                [
                    "validate-bundle-v3",
                    "--bundle",
                    str(bundle),
                    "--output",
                    str(validation_output),
                ]
            )
        self.assertEqual(code, 0)
        validate.assert_called_once_with({"bundle": True})
        self.assertTrue(json.loads(validation_output.read_text())["valid"])

        pairs = self.save("pairs.json", [{"pair": 1}])
        comparison_output = self.root / "comparison.json"
        with patch(
            "stage2_eval.evaluation_v3.compare_pairs_v3",
            return_value={"kind": "Stage2PairedDiagnostic", "decision": "inconclusive"},
        ) as compare:
            code = eval_main(
                [
                    "compare-v3",
                    "--pairs",
                    str(pairs),
                    "--output",
                    str(comparison_output),
                ]
            )
        self.assertEqual(code, 0)
        compare.assert_called_once_with([{"pair": 1}])
        self.assertEqual(
            json.loads(comparison_output.read_text())["decision"], "inconclusive"
        )

    def test_evaluated_delivery_derives_workflow_bindings_and_verify_needs_receipt(
        self,
    ):
        run, source_root, state, selection_value = self.workflow_selection(
            "current", revise_first=True
        )
        selection_value = copy.deepcopy(selection_value)
        selection_value["evaluation_packet"]["candidates"].reverse()
        selection = self.save("selection.json", selection_value)
        snapshots = self.save(
            "snapshots.json", selection_value["evaluation_packet"]["sources"]
        )
        bundle = self.save("bundle.json", {"bundle": True})
        with patch(
            "stage2_workflow.evaluation_delivery.build_evaluated_delivery",
            return_value={"kind": "Stage2EvaluatedDelivery", "formal_ready": False},
        ) as build:
            code = workflow_main(
                [
                    "evaluated-deliver-v3",
                    "--run",
                    str(run),
                    "--expected-head",
                    state["head_sha256"],
                    "--selection",
                    str(selection),
                    "--source-snapshots",
                    str(snapshots),
                    "--source-root",
                    str(source_root),
                    "--bundle",
                    str(bundle),
                    "--expected-bundle-sha256",
                    "a" * 64,
                    "--output",
                    str(self.root / "delivery"),
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(build.call_args.kwargs["event_head"], state["head_sha256"])
        self.assertEqual(
            build.call_args.kwargs["stored_packet_sha256"],
            state["latest_snapshot"]["checker"]["manifest"]["stored_packet_sha256"],
        )

        verify_output = self.root / "verified.json"
        with patch(
            "stage2_workflow.evaluation_delivery.inspect_evaluated_delivery",
            return_value={"kind": "Stage2EvaluatedDelivery", "formal_ready": False},
        ) as verify:
            code = workflow_main(
                [
                    "verify-evaluated-delivery",
                    "--delivery",
                    str(self.root / "delivery"),
                    "--expected-manifest-sha256",
                    "b" * 64,
                    "--output",
                    str(verify_output),
                ]
            )
        self.assertEqual(code, 0)
        verify.assert_called_once_with(
            str(self.root / "delivery"), expected_manifest_sha256="b" * 64
        )
        self.assertEqual(json.loads(verify_output.read_text())["formal_ready"], False)

    def test_evaluated_delivery_rejects_cross_workflow_selection(self):
        _, _, _, stale_selection = self.workflow_selection("stale")
        run, source_root, state, current_selection = self.workflow_selection(
            "other", candidate_count=2
        )
        selection = self.save("stale-selection.json", stale_selection)
        snapshots = self.save(
            "stale-snapshots.json", stale_selection["evaluation_packet"]["sources"]
        )
        bundle = self.save("stale-bundle.json", {"bundle": True})
        with patch(
            "stage2_workflow.evaluation_delivery.build_evaluated_delivery"
        ) as build:
            code = workflow_main(
                [
                    "evaluated-deliver-v3",
                    "--run",
                    str(run),
                    "--expected-head",
                    state["head_sha256"],
                    "--selection",
                    str(selection),
                    "--source-snapshots",
                    str(snapshots),
                    "--source-root",
                    str(source_root),
                    "--bundle",
                    str(bundle),
                    "--expected-bundle-sha256",
                    "a" * 64,
                    "--output",
                    str(self.root / "stale-delivery"),
                ]
            )
        self.assertEqual(code, 2)
        build.assert_not_called()

        stale_current = copy.deepcopy(current_selection)
        stale_current["evaluation_packet"]["candidates"].pop()
        selection = self.save("stale-current-selection.json", stale_current)
        snapshots = self.save(
            "stale-current-snapshots.json",
            stale_current["evaluation_packet"]["sources"],
        )
        with patch(
            "stage2_workflow.evaluation_delivery.build_evaluated_delivery"
        ) as build:
            code = workflow_main(
                [
                    "evaluated-deliver-v3",
                    "--run",
                    str(run),
                    "--expected-head",
                    state["head_sha256"],
                    "--selection",
                    str(selection),
                    "--source-snapshots",
                    str(snapshots),
                    "--source-root",
                    str(source_root),
                    "--bundle",
                    str(bundle),
                    "--expected-bundle-sha256",
                    "a" * 64,
                    "--output",
                    str(self.root / "stale-current-delivery"),
                ]
            )
        self.assertEqual(code, 2)
        build.assert_not_called()

    def test_verify_evaluated_delivery_requires_explicit_output(self):
        with self.assertRaises(SystemExit) as stopped:
            workflow_main(
                [
                    "verify-evaluated-delivery",
                    "--delivery",
                    str(self.root / "delivery"),
                    "--expected-manifest-sha256",
                    "a" * 64,
                ]
            )
        self.assertEqual(stopped.exception.code, 2)


if __name__ == "__main__":
    unittest.main()

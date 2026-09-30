"""Offline recovery admits only an explicitly selected, reviewed byte transition."""

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))

from stage1_eval.common import EvaluationError, sha  # noqa: E402
from stage1_eval import reason_recovery  # noqa: E402


class ReviewedDeltaTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.files = {
            "cli/stage1_ab/observer.py": "a148c72b6218bcd816f2778aa5f73c715bc1277fa5e44b32d59f09dbd28c16c6",
            "cli/stage1_eval/judging.py": "b2ae35a4b79465e48e27c5aece8bd7afe2a75089935c1094d43b7a891f57fba8",
            "cli/stage1_eval/pipeline_v31.py": "ccde8fd8c25d92375e8280542e5ae0aca09794e2cc43d913f750e2a0f3dc23cf",
        }
        for relative in self.files:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((PLUGIN / relative).read_bytes())
        self.inventory = {
            "files": {
                "plugins/auto-research-agent/" + relative: digest
                for relative, digest in self.files.items()
            }
        }

    def invoke(self, declaration="accepted-pr65-pr67-v1", inventory=None):
        return reason_recovery.verify_contract_changes(
            inventory or self.inventory, self.root, declaration
        )

    def test_reviewed_transition_requires_explicit_manifest_opt_in(self):
        with self.assertRaisesRegex(EvaluationError, "unexplained evaluator"):
            self.invoke(None)
        receipt = self.invoke()
        self.assertEqual(receipt["policy_id"], "accepted-pr65-pr67-v1")
        self.assertEqual(len(receipt["changes"]), 3)
        self.assertEqual(
            {row["path"]: row["old_sha256"] for row in receipt["changes"]},
            self.files,
        )

    def test_reviewed_filename_with_wrong_old_hash_is_rejected(self):
        inventory = copy.deepcopy(self.inventory)
        inventory["files"]["plugins/auto-research-agent/cli/stage1_ab/observer.py"] = (
            "f" * 64
        )
        with self.assertRaisesRegex(EvaluationError, "unexplained evaluator"):
            self.invoke(inventory=inventory)

    def test_reviewed_filename_with_rehashed_changed_new_bytes_is_rejected(self):
        path = self.root / "cli/stage1_eval/judging.py"
        path.write_bytes(path.read_bytes() + b"\n# unreviewed change\n")
        with self.assertRaisesRegex(EvaluationError, "unexplained evaluator"):
            self.invoke()

    def test_missing_transition_member_is_rejected(self):
        inventory = copy.deepcopy(self.inventory)
        del inventory["files"]["plugins/auto-research-agent/cli/stage1_eval/judging.py"]
        with self.assertRaisesRegex(EvaluationError, "incomplete reviewed"):
            self.invoke(inventory=inventory)

    def test_unrelated_model_schema_rubric_policy_and_capture_changes_are_rejected(
        self,
    ):
        for relative in (
            "cli/stage1_eval/model.py",
            "evals/schemas/source-v3.schema.json",
            "evals/rubrics/stage1-general.v3.json",
            "evals/stage1/execution-policy.v3_1.json",
            "cli/stage1_ab/capture_history.py",
        ):
            with self.subTest(relative=relative):
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"unreviewed")
                inventory = copy.deepcopy(self.inventory)
                inventory["files"]["plugins/auto-research-agent/" + relative] = sha(
                    b"original"
                )
                with self.assertRaisesRegex(EvaluationError, "unexplained evaluator"):
                    self.invoke(inventory=inventory)

    def test_unknown_reviewed_delta_id_is_rejected(self):
        with self.assertRaisesRegex(EvaluationError, "unsupported reviewed"):
            self.invoke("allow-anything")

    def test_unchanged_contract_keeps_legacy_behavior(self):
        inventory = copy.deepcopy(self.inventory)
        for relative in self.files:
            inventory["files"]["plugins/auto-research-agent/" + relative] = sha(
                (self.root / relative).read_bytes()
            )
        self.assertEqual(
            self.invoke(None, inventory), {"policy_id": None, "changes": []}
        )

    def test_dictionary_inventory_records_support_exact_reviewed_pairs(self):
        inventory = copy.deepcopy(self.inventory)
        inventory["files"] = {
            key: {"sha256": digest, "bytes": 1}
            for key, digest in inventory["files"].items()
        }
        self.assertEqual(self.invoke(inventory=inventory), self.invoke())

    def test_public_dry_run_checks_manifest_delta_before_revalidation(self):
        generation = self.root / "generation"
        source = {"evaluator_bundle_sha256": "old", "targets": []}
        manifest = {
            "kind": reason_recovery.KIND,
            "reason_delta": [400, 1024],
            "source_plan": {"path": str(generation / "plan.json"), "sha256": "source"},
            "target_plan": {"path": "target", "sha256": "target"},
            "generation": {"path": "generation"},
            "old_code": {"path": "old-code"},
            "captures": {"path": "captures"},
            "outputs": [],
        }
        code = copy.deepcopy(self.inventory)
        code["files"].update(
            {
                "plugins/auto-research-agent/cli/stage1_eval/" + name: "unused"
                for name in ("model.py", "model_calls.py", "source_audit_units.py")
            }
        )
        # Unchanged unrelated modules still need their original hash.
        for name in ("model.py", "model_calls.py"):
            code["files"]["plugins/auto-research-agent/cli/stage1_eval/" + name] = sha(
                (PLUGIN / "cli/stage1_eval" / name).read_bytes()
            )
        bound = {
            "manifest": manifest,
            manifest["source_plan"]["path"]: source,
            "target": {"target_policy": {}},
            "generation": {"files": {}},
            "old-code": code,
            "captures": {"captures": {}},
            str(generation / "capture-inventory.json"): {},
        }
        source["capture_inventory_sha256"] = "capture"
        with (
            mock.patch.object(
                reason_recovery, "bound_json", side_effect=lambda r: bound[r["path"]]
            ),
            mock.patch.object(reason_recovery, "_plan_contract"),
            mock.patch.object(
                reason_recovery, "verify_inventory", return_value=generation
            ),
            mock.patch.object(reason_recovery, "verify_operator_runtime"),
            mock.patch.object(
                reason_recovery, "verify_code_contract", return_value=self.root
            ),
            mock.patch.object(reason_recovery, "historical_attempts", return_value=[]),
            mock.patch("stage1_eval.pipeline_v31.bundle_sha_v31", return_value="new"),
            mock.patch("stage1_eval.pipeline_v31.execution_policy", return_value={}),
        ):
            with self.assertRaisesRegex(EvaluationError, "unexplained evaluator"):
                reason_recovery.dry_run("manifest", "external")
            manifest["reviewed_code_delta"] = "accepted-pr65-pr67-v1"
            result = reason_recovery.dry_run("manifest", "external")
        self.assertEqual(len(result["reviewed_code_delta"]["changes"]), 3)
        self.assertEqual(result["counts"], {"accepted": 0, "rejected": 0, "missing": 0})
        self.assertFalse(result["future_execution_authorized"])


if __name__ == "__main__":
    unittest.main()

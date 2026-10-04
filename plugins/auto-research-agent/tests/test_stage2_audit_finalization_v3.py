# ruff: noqa: E402 -- load repository CLI and fixture helpers without installation.
"""Append-only finalization of an independently produced Stage 2 v3 audit."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parent),
]

from stage1_eval.common import EvaluationError
from stage2_common import Stage2Error, canonical_hash
from stage2_live.__main__ import main as live_main
from stage2_live.daily_v3 import finalize_daily_evaluation_v3
import test_stage2_daily_v3 as daily_test
from test_stage2_evaluation_v3 import named_audit


class AuditFinalizationV3Tests(unittest.TestCase):
    def setUp(self):
        self.daily = daily_test.DailyV3Tests(
            methodName="test_disagreement_keeps_comments_and_pending_real_audit"
        )
        self.daily.setUp()
        self.addCleanup(self.daily.doCleanups)
        self.bundle = self.daily.run_judges(disagree=True)
        self.audit = named_audit(self.bundle["judgments"]["ADJ"])
        self.parent_sha = canonical_hash(self.bundle)

    def archive_hashes(self):
        root = self.daily.root / "judges"
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in root.rglob("*")
            if path.is_file()
        }

    def finalize(self, output_name="finalized", **overrides):
        return finalize_daily_evaluation_v3(
            overrides.get("bundle", self.bundle),
            overrides.get("selection", self.daily.selection),
            self.daily.sources,
            overrides.get("audit", self.audit),
            self.daily.root / output_name,
            expected_bundle_sha256=overrides.get("expected", self.parent_sha),
            parent_replay_receipt=overrides.get("parent_receipt"),
        )

    def test_persisted_parent_requires_external_receipt_before_output(self):
        persisted = json.loads(
            (self.daily.root / "judges" / "result.json").read_bytes()
        )
        with self.assertRaisesRegex(Stage2Error, "bound parent replay receipt"):
            self.finalize(
                "missing-parent-receipt",
                bundle=persisted,
                expected=canonical_hash(persisted),
            )
        self.assertFalse((self.daily.root / "missing-parent-receipt").exists())
        result = self.finalize(
            "persisted-parent",
            bundle=persisted,
            expected=canonical_hash(persisted),
            parent_receipt=self.bundle["replay_receipt"],
        )
        self.assertEqual(result["parent_replay_receipt"], self.bundle["replay_receipt"])
        self.assertEqual(result["status"], "complete")

    def test_wrong_external_parent_receipt_fails_before_output(self):
        wrong = copy.deepcopy(self.bundle["replay_receipt"])
        wrong["result_sha256"] = "f" * 64
        with self.assertRaisesRegex(Stage2Error, "bound parent replay receipt"):
            self.finalize("wrong-parent-receipt", parent_receipt=wrong)
        self.assertFalse((self.daily.root / "wrong-parent-receipt").exists())

    def test_finalization_is_append_only_and_dispatches_no_models(self):
        before = self.archive_hashes()
        with (
            patch("stage2_live.daily_v3.call_model_v31") as model,
            patch("stage2_live.daily_v3._run_unit") as unit,
        ):
            result = self.finalize()
        model.assert_not_called()
        unit.assert_not_called()
        self.assertEqual(self.archive_hashes(), before)
        self.assertEqual(result["status"], "complete")
        self.assertIsNone(result["failure"])
        self.assertEqual(result["merged"]["audit_status"], "accepted")
        self.assertEqual(result["audit_finalization"]["new_model_calls"], 0)
        self.assertEqual(
            result["audit_finalization"]["parent_bundle_sha256"], self.parent_sha
        )
        self.assertEqual(
            result["audit_finalization"]["audit_sha256"], canonical_hash(self.audit)
        )
        self.assertEqual(result["parent_replay_receipt"], self.bundle["replay_receipt"])
        self.assertFalse(result["formal_ready"])
        self.assertFalse(result["improvement_demonstrated"])
        saved = self.daily.root / "finalized" / "result.json"
        self.assertEqual(
            result["replay_receipt"]["result_sha256"],
            hashlib.sha256(saved.read_bytes()).hexdigest(),
        )
        saved_value = json.loads(saved.read_bytes())
        self.assertNotIn("replay_receipt", saved_value)
        self.assertIn("parent_replay_receipt", saved_value)

    def test_invalid_audit_and_stale_science_are_rejected_without_output(self):
        invalid = copy.deepcopy(self.audit)
        invalid["reviewer_role"] = "ai"
        with self.assertRaisesRegex(Stage2Error, "cannot self-certify"):
            self.finalize("invalid-audit", audit=invalid)
        self.assertFalse((self.daily.root / "invalid-audit").exists())

        stale = copy.deepcopy(self.daily.selection)
        stale["action_record"]["choice_rationale"] = "Changed after evaluation."
        with self.assertRaisesRegex(Stage2Error, "science-binding"):
            self.finalize("stale-science", selection=stale)
        self.assertFalse((self.daily.root / "stale-science").exists())

    def test_nonempty_output_is_rejected_before_science_or_audit_changes(self):
        output = self.daily.root / "occupied"
        output.mkdir()
        marker = output / "keep.txt"
        marker.write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(EvaluationError, "empty output"):
            self.finalize("occupied")
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_cli_dispatches_explicit_finalization_inputs(self):
        paths = {}
        for name, value in (
            ("bundle", self.bundle),
            ("selection", self.daily.selection),
            ("audit", self.audit),
        ):
            path = self.daily.root / f"{name}.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            paths[name] = path
        output = self.daily.root / "cli-finalized"
        with patch(
            "stage2_live.daily_v3.finalize_daily_evaluation_v3",
            return_value={
                "status": "complete",
                "formal_ready": False,
                "improvement_demonstrated": False,
            },
        ) as finalize:
            code = live_main(
                [
                    "finalize-daily-v3",
                    "--bundle",
                    str(paths["bundle"]),
                    "--selection",
                    str(paths["selection"]),
                    "--source-root",
                    str(self.daily.sources),
                    "--audit",
                    str(paths["audit"]),
                    "--expected-bundle-sha256",
                    self.parent_sha,
                    "--output",
                    str(output),
                ]
            )
        self.assertEqual(code, 0)
        finalize.assert_called_once_with(
            self.bundle,
            self.daily.selection,
            str(self.daily.sources),
            self.audit,
            str(output),
            expected_bundle_sha256=self.parent_sha,
            parent_replay_receipt=None,
        )


if __name__ == "__main__":
    unittest.main()

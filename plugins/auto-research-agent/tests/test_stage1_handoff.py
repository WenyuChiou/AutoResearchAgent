"""Checkpoint snapshots preserve exactly the reviewed Stage 1 inputs."""

from pathlib import Path
import tempfile
import unittest

from test_stage1_ledger import fixture, rewrite_for_tamper_test
from stage1_ledger.journal import canonical, decode
from stage1_ledger.contracts import check
from stage1_ledger.validation import validate_run
from stage1_ledger.store import Ledger


class Stage1HandoffTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ledger, self.refs, self.work, _ = fixture(
            Path(self.directory.name) / "run"
        )

    def outputs(self, checkpoint):
        return [
            decode(self.ledger.read_ref(ref), ref["path"])
            for ref in checkpoint["stage_result"]["outputs"]
        ]

    def test_checkpoint_preserves_reversal_provenance_and_pending_stage2(self):
        state = self.ledger.state_hash()
        checkpoint = self.ledger.checkpoint()
        candidates, claims, decisions, handoff = self.outputs(checkpoint)
        self.assertEqual(len(candidates["rows"][0]["discoveries"]), 2)
        self.assertEqual(claims["rows"], [])
        self.assertEqual(
            [row["new_decision"] for row in decisions["rows"]], ["include", "exclude"]
        )
        self.assertEqual(handoff["papers"], [])
        self.assertEqual(
            handoff["stage2"], {"status": "not-started", "execution_authorized": False}
        )
        self.assertFalse(handoff["eligible_for_stage2"])
        self.assertEqual(self.ledger.state_hash(), state)
        self.assertTrue(validate_run(self.ledger.root)["valid"])
        again = self.ledger.checkpoint()
        self.assertEqual(
            again["stage_result"]["outputs"], checkpoint["stage_result"]["outputs"]
        )
        self.assertEqual(self.ledger.state_hash(), state)

    def test_new_decision_creates_new_snapshot_without_replacing_old_bytes(self):
        first = self.ledger.checkpoint()
        old_refs = first["stage_result"]["outputs"]
        old_bytes = [self.ledger.read_ref(ref) for ref in old_refs]
        self.ledger.decide(
            self.work,
            "include",
            reason="scope-match",
            rationale="Synthetic reconsideration",
            evidence_refs=[self.refs[0]],
        )
        second = self.ledger.checkpoint()
        handoff = self.outputs(second)[-1]
        self.assertEqual([p["work_id"] for p in handoff["papers"]], [self.work])
        self.assertIn("Synthetic household record", handoff["manual_paper_list"])
        self.assertEqual(handoff["papers"][0]["identity_review"], "not-assessed")
        self.assertIsNone(handoff["papers"][0]["reviewed_version_id"])
        self.assertFalse(handoff["stage2"]["execution_authorized"])
        self.assertNotEqual(old_refs, second["stage_result"]["outputs"])
        self.assertEqual(old_bytes, [self.ledger.read_ref(ref) for ref in old_refs])
        self.assertTrue(validate_run(self.ledger.root)["valid"])

    def test_missing_snapshot_fails_without_regeneration(self):
        checkpoint = self.ledger.checkpoint()
        ref = checkpoint["stage_result"]["outputs"][-1]
        path = self.ledger.root / ref["path"]
        original = path.read_bytes()
        path.unlink()
        report = validate_run(self.ledger.root)
        self.assertFalse(report["valid"])
        self.assertIn(ref["path"], " ".join(report["errors"]))
        self.ledger.recover()
        self.assertFalse(path.exists())
        path.write_bytes(original)
        self.assertTrue(validate_run(self.ledger.root)["valid"])

    def test_rehashed_output_reordering_and_empty_new_contract_are_rejected(self):
        self.ledger.checkpoint()
        rewrite_for_tamper_test(
            self.ledger,
            lambda rows: rows[-1]["payload"]["stage_result"]["outputs"].reverse(),
        )
        self.assertIn(
            "handoff-output-replay", " ".join(validate_run(self.ledger.root)["errors"])
        )
        rewrite_for_tamper_test(
            self.ledger,
            lambda rows: rows[-1]["payload"]["stage_result"].update(outputs=[]),
        )
        self.assertIn(
            "handoff-output-set", " ".join(validate_run(self.ledger.root)["errors"])
        )

    def test_snapshot_schema_rejects_new_version_and_stage2_execution(self):
        handoff = self.outputs(self.ledger.checkpoint())[-1]
        check(handoff, "Stage1Handoff")
        handoff["stage2"]["execution_authorized"] = True
        with self.assertRaises(ValueError):
            check(handoff, "Stage1Handoff")
        handoff["stage2"]["execution_authorized"] = False
        handoff["schema_version"] = "99.0.0"
        with self.assertRaises(ValueError):
            check(handoff, "Stage1Handoff")

    def test_legacy_manifest_and_empty_checkpoint_outputs_remain_readable(self):
        ledger = Ledger.create(
            Path(self.directory.name) / "legacy",
            run_id="legacy",
            objective="Synthetic old run",
        )
        manifest = ledger.manifest
        manifest.pop("checkpoint_output_contract")
        (ledger.root / "run_manifest.json").write_bytes(canonical(manifest))
        ledger.checkpoint()
        rewrite_for_tamper_test(
            ledger, lambda rows: rows[-1]["payload"]["stage_result"].update(outputs=[])
        )
        self.assertTrue(validate_run(ledger.root)["valid"])


if __name__ == "__main__":
    unittest.main()

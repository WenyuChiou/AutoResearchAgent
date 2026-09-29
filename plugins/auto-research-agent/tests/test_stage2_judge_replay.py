# ruff: noqa: E402 -- import the repository CLI without installing a package.
"""Read-only tests for authenticating Stage 2 judge archives."""

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
sys.path.insert(0, str(PLUGIN / "cli"))
sys.path.insert(0, str(HERE))

from stage1_eval.common import canonical
from stage2_common import Stage2Error, canonical_hash
from stage2_fixture_helpers import write_stage2_fixture
from stage2_live.judge_replay import verify_judges
from stage2_live.judges import run_stage2_judges
from test_stage2_evaluation import action_record, named_audit
from test_stage2_live_judges import POLICY, FakeCallAdapter


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class Stage2JudgeReplayTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.sources = self.root / "sources"
        self.packet = write_stage2_fixture(self.sources, candidate_count=2)
        self.actions = action_record(self.packet)
        self.homes = {}
        for role in ("R1", "R2", "ADJ"):
            path = self.root / f"home-{role.lower()}"
            path.mkdir()
            self.homes[role] = path
        self.codex = self.root / "codex"
        self.codex.write_bytes(b"fixed runtime")
        self.archive_index = 0
        self.config = {
            "codex": str(self.codex),
            "codex_executable_sha256": sha(self.codex.read_bytes()),
            "model": "test-model",
            "reasoning": "high",
            "reviewer_homes": {role: str(path) for role, path in self.homes.items()},
        }

    def build(self, *, disagreement=False):
        self.archive_index += 1
        output = self.root / (
            f"{'disagreed' if disagreement else 'agreed'}-{self.archive_index}"
        )
        generated = run_stage2_judges(
            self.packet,
            self.sources,
            "opaque-subject-01",
            "1" * 64,
            "2" * 64,
            self.actions,
            r1_home=self.homes["R1"],
            r2_home=self.homes["R2"],
            adj_home=self.homes["ADJ"],
            codex=self.codex,
            model="test-model",
            reasoning="high",
            execution_policy=POLICY,
            output_dir=output,
            call_adapter=FakeCallAdapter(self.packet, disagreement=disagreement),
        )
        request_path = output / "request.json"
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request["adapter_mode"] = "native"
        request_path.write_bytes(canonical(request) + b"\n")
        result_path = output / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["request_sha256"] = canonical_hash(request)
        result_path.write_bytes(canonical(result) + b"\n")
        receipt = {
            "result_sha256": sha(result_path.read_bytes()),
            "unit_receipts": generated["replay_receipt"]["unit_receipts"],
        }
        return output, receipt

    def fake_replay(self, calls):
        def replay(root, label, receipt, *, prompt, schema, config, policy, validate):
            unit_path = Path(root) / f"{label}.unit.json"
            if not unit_path.is_file():
                raise Stage2Error("missing replay unit")
            if sha(unit_path.read_bytes()) != receipt:
                raise Stage2Error("unit receipt mismatch")
            saved = json.loads(unit_path.read_text(encoding="utf-8"))
            validate(copy.deepcopy(saved["value"]))
            calls.append((label, config["evaluator_home"], prompt, schema, policy))
            return {
                "value": saved["value"],
                "provenance": saved["provenance"],
                "actual_call_count": 1,
                "archive_sha256s": {"initial": label[0] * 64},
                "unit_sha256": receipt,
                "portable_path_limitation": "same-host",
            }

        return replay

    def verify(self, output, receipt, *, audit=None, config=None):
        calls = []
        with (
            patch("stage2_live.judge_replay.replay_unit", self.fake_replay(calls)),
            patch(
                "stage2_live.judges.call_model_v31",
                side_effect=AssertionError("model dispatch forbidden"),
            ),
        ):
            result = verify_judges(
                output,
                receipt,
                packet=self.packet,
                source_root=self.sources,
                subject_id="opaque-subject-01",
                input_sha256="1" * 64,
                config_sha256="2" * 64,
                action_record=self.actions,
                expected_config=config or self.config,
                expected_policy=POLICY,
                named_audit=audit,
            )
        return result, calls

    def test_agreement_authenticates_roles_and_skips_adjudicator(self):
        output, receipt = self.build()
        result, calls = self.verify(output, receipt)

        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["actual_call_count"], 4)
        self.assertEqual([row[0] for row in calls], list(receipt["unit_receipts"]))
        self.assertEqual(
            [row[1] for row in calls],
            [str(self.homes["R1"].resolve())] * 2
            + [str(self.homes["R2"].resolve())] * 2,
        )
        self.assertFalse(result["scientific_approval"])

    def test_disagreement_requires_real_named_audit(self):
        output, receipt = self.build(disagreement=True)
        pending, calls = self.verify(output, receipt)
        self.assertEqual(pending["status"], "audit-required")
        self.assertIsNone(pending["bundle"])
        self.assertEqual([row[0] for row in calls][-2:], ["adj-content", "adj-judge"])

        saved = json.loads((output / "result.json").read_text(encoding="utf-8"))
        audited, _ = self.verify(
            output, receipt, audit=named_audit(saved["judgments"]["ADJ"])
        )
        self.assertTrue(audited["bundle"]["audit_accepted"])
        self.assertTrue(audited["named_audit_applied"])
        self.assertEqual(audited["saved_result"]["status"], "audit-required")

    def test_wrong_role_home_and_non_distinct_homes_fail(self):
        output, receipt = self.build()
        changed = copy.deepcopy(self.config)
        changed["reviewer_homes"]["R1"] = str(self.root / "other-home")
        (self.root / "other-home").mkdir()
        with self.assertRaisesRegex(Stage2Error, "request-mismatch"):
            self.verify(output, receipt, config=changed)

        aliased = copy.deepcopy(self.config)
        aliased["reviewer_homes"]["R2"] = aliased["reviewer_homes"]["R1"]
        with self.assertRaisesRegex(Stage2Error, "exist-and-be-distinct"):
            self.verify(output, receipt, config=aliased)

    def test_missing_unit_and_result_receipt_tamper_fail_closed(self):
        output, receipt = self.build()
        (output / "r1-content.unit.json").unlink()
        with self.assertRaisesRegex(Stage2Error, "missing replay unit"):
            self.verify(output, receipt)

        output, receipt = self.build(disagreement=True)
        receipt["result_sha256"] = "f" * 64
        with self.assertRaisesRegex(Stage2Error, "result-receipt-mismatch"):
            self.verify(output, receipt)

    def test_changed_action_view_and_adjudicator_receipts_fail(self):
        output, receipt = self.build(disagreement=True)
        path = output / "r2-action-view.json"
        changed = json.loads(path.read_text(encoding="utf-8"))
        changed["action_record"]["latest_dispositions"][0]["reason"] = (
            "baseline treatment text"
        )
        path.write_bytes(canonical(changed) + b"\n")
        with self.assertRaisesRegex(Stage2Error, "action-view-mismatch"):
            self.verify(output, receipt)

        output, receipt = self.build(disagreement=True)
        path = output / "adj-action-view.json"
        changed = json.loads(path.read_text(encoding="utf-8"))
        changed["action_record"]["choice_rationale"] = "changed ADJ view"
        path.write_bytes(canonical(changed) + b"\n")
        with self.assertRaisesRegex(Stage2Error, "adj-action-view-mismatch"):
            self.verify(output, receipt)

        output, receipt = self.build(disagreement=True)
        receipt["unit_receipts"].pop("adj-judge")
        with self.assertRaisesRegex(Stage2Error, "unit-receipt-set"):
            self.verify(output, receipt)

    def test_changed_action_record_reconstructs_different_view(self):
        output, receipt = self.build()
        changed = copy.deepcopy(self.actions)
        changed["choice_rationale"] = "A different retained decision."
        calls = []
        with (
            patch("stage2_live.judge_replay.replay_unit", self.fake_replay(calls)),
            self.assertRaisesRegex(Stage2Error, "request-mismatch"),
        ):
            verify_judges(
                output,
                receipt,
                packet=self.packet,
                source_root=self.sources,
                subject_id="opaque-subject-01",
                input_sha256="1" * 64,
                config_sha256="2" * 64,
                action_record=changed,
                expected_config=self.config,
                expected_policy=POLICY,
            )


if __name__ == "__main__":
    unittest.main()

"""Validate reconciliation of independent rubric judges."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator, FormatChecker


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = PLUGIN_ROOT / "evals"
sys.path.insert(0, str(PLUGIN_ROOT))

from validators.holdout_manifest import canonical_sha256  # noqa: E402
from validators.judge_bundle import validate_bundle  # noqa: E402


def load(relative_path):
    return json.loads((EVAL_ROOT / relative_path).read_text(encoding="utf-8"))


class JudgeBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load("schemas/judge-bundle.v1.schema.json")
        Draft202012Validator.check_schema(cls.schema)
        cls.schema_validator = Draft202012Validator(
            cls.schema, format_checker=FormatChecker()
        )
        cls.example = load("examples/judge-bundle.synthetic.json")
        cls.r1 = load("examples/rubric-judge-result-stage1-r1.synthetic.json")
        cls.r2 = load("examples/rubric-judge-result-stage1-r2.synthetic.json")
        (EVAL_ROOT / "private").mkdir(exist_ok=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=EVAL_ROOT / "private")
        self.temp_path = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write_artifact(self, name, value):
        path = self.temp_path / name
        path.write_text(json.dumps(value), encoding="utf-8")
        relative = path.relative_to(EVAL_ROOT).as_posix()
        return {"path": relative, "canonical_sha256": canonical_sha256(value)}

    def write_byte_artifact(self, name, content):
        path = self.temp_path / name
        path.write_bytes(content)
        return {
            "path": path.relative_to(EVAL_ROOT).as_posix(),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    def test_agreed_fixture_is_pairing_ready(self):
        self.schema_validator.validate(self.example)
        self.assertEqual(validate_bundle(self.example), [])

    def test_hash_role_and_subject_mismatch_fail_closed(self):
        bad_hash = deepcopy(self.example)
        bad_hash["artifacts"]["auto_r1"]["canonical_sha256"] = "0" * 64
        self.assertTrue(
            any(
                "does not match artifact bytes" in error
                for error in validate_bundle(bad_hash)
            )
        )

        wrong_role = deepcopy(self.r2)
        wrong_role["judge"]["role"] = "auto-r1"
        bundle = deepcopy(self.example)
        bundle["artifacts"]["auto_r2"] = self.write_artifact(
            "wrong-role.json", wrong_role
        )
        self.assertTrue(
            any(
                "must use judge role auto-r2" in error
                for error in validate_bundle(bundle)
            )
        )

        wrong_subject = deepcopy(self.r2)
        wrong_subject["subject_artifact"]["sha256"] = "9" * 64
        bundle = deepcopy(self.example)
        bundle["artifacts"]["auto_r2"] = self.write_artifact(
            "wrong-subject.json", wrong_subject
        )
        self.assertTrue(
            any(
                "subject artifact does not match the bundle" in error
                for error in validate_bundle(bundle)
            )
        )

    def test_disagreement_requires_adjudication_then_human_audit(self):
        r2 = deepcopy(self.r2)
        row = next(item for item in r2["metric_results"] if item["metric_id"] == "P2")
        row["score"] = 1
        row["criterion_results"][0]["outcome"] = "partial"
        bundle = deepcopy(self.example)
        bundle["artifacts"]["auto_r2"] = self.write_artifact("r2-disagrees.json", r2)
        self.assertIn("judge disagreement requires Auto-ADJ", validate_bundle(bundle))

        adj = deepcopy(r2)
        adj["evaluation_id"] = "eval-run01-a-adj"
        adj["judge"] = {
            "role": "auto-adj",
            "model": "gpt-5.6-sol",
            "reasoning": "high",
            "config_id": "aging-adj-v1",
            "prompt_sha256": "a" * 64,
            "evaluation_config_sha256": "7" * 64,
            "execution_context_id": "judge-context-3",
            "condition_blinded": True,
        }
        adj["created_at"] = "2026-09-17T16:05:00-04:00"
        adj["adjudicates_evaluation_ids"] = [
            self.r1["evaluation_id"],
            r2["evaluation_id"],
        ]
        adj["audit_trigger_ids"] = ["judge-disagreement"]
        adj["requires_human_audit"] = True
        bundle["artifacts"]["auto_adj"] = self.write_artifact("adj.json", adj)
        bundle["status"] = "audit-required"
        bundle["selected_evaluation_id"] = None
        bundle["usable_for_pairing"] = False
        self.assertEqual(validate_bundle(bundle), [])

        bundle["artifacts"]["human_audit"] = {
            "audit_id": "audit-run01-a",
            "actor_id": "human-organizer-a",
            "actor_type": "human",
            "attestation_ref": "course-roster:organizer-a",
            "reviewed_evaluation_ids": [
                self.r1["evaluation_id"],
                r2["evaluation_id"],
                adj["evaluation_id"],
            ],
            "decision": "accept-selected",
            "reason": "The adjudication follows the frozen rubric and cited evidence.",
            "artifact": self.write_byte_artifact(
                "audit-run01-a.json", b'{"decision":"accept-selected"}\n'
            ),
            "completed_at": "2026-09-17T16:20:00-04:00",
        }
        bundle["status"] = "completed"
        bundle["selected_evaluation_id"] = adj["evaluation_id"]
        bundle["usable_for_pairing"] = True
        self.assertEqual(validate_bundle(bundle), [])

    def test_rejected_audit_completes_record_but_blocks_pairing(self):
        r1 = deepcopy(self.r1)
        r1["audit_trigger_ids"] = ["external-claim"]
        r1["requires_human_audit"] = True
        r2 = deepcopy(self.r2)
        r2["audit_trigger_ids"] = ["external-claim"]
        r2["requires_human_audit"] = True
        bundle = deepcopy(self.example)
        bundle["artifacts"]["auto_r1"] = self.write_artifact("r1-audit.json", r1)
        bundle["artifacts"]["auto_r2"] = self.write_artifact("r2-audit.json", r2)
        bundle["artifacts"]["human_audit"] = {
            "audit_id": "audit-reject",
            "actor_id": "human-organizer-a",
            "actor_type": "human",
            "attestation_ref": "course-roster:organizer-a",
            "reviewed_evaluation_ids": [r1["evaluation_id"], r2["evaluation_id"]],
            "decision": "reject",
            "reason": "The evidence is insufficient for the proposed external claim.",
            "artifact": self.write_byte_artifact(
                "audit-reject.json", b'{"decision":"reject"}\n'
            ),
            "completed_at": "2026-09-17T16:20:00-04:00",
        }
        bundle["status"] = "completed"
        bundle["selected_evaluation_id"] = None
        bundle["usable_for_pairing"] = False
        self.assertEqual(validate_bundle(bundle), [])

    def test_subject_provenance_mode_config_and_time_are_bound(self):
        bad_subject = deepcopy(self.example)
        bad_subject["subject_artifact"]["sha256"] = "0" * 64
        self.assertTrue(
            any("subject sha256" in error for error in validate_bundle(bad_subject))
        )

        wrong_mode = deepcopy(self.r2)
        wrong_mode["study_mode"] = "confirmatory"
        bundle = deepcopy(self.example)
        bundle["artifacts"]["auto_r2"] = self.write_artifact(
            "wrong-mode.json", wrong_mode
        )
        self.assertTrue(any("study_mode" in error for error in validate_bundle(bundle)))

        wrong_config = deepcopy(self.r2)
        wrong_config["judge"]["prompt_sha256"] = "0" * 64
        bundle = deepcopy(self.example)
        bundle["artifacts"]["auto_r2"] = self.write_artifact(
            "wrong-config.json", wrong_config
        )
        self.assertTrue(
            any("prompt_sha256" in error for error in validate_bundle(bundle))
        )

        legacy = deepcopy(self.r2)
        for field in (
            "reasoning",
            "prompt_sha256",
            "evaluation_config_sha256",
            "execution_context_id",
        ):
            del legacy["judge"][field]
        bundle = deepcopy(self.example)
        bundle["artifacts"]["auto_r2"] = self.write_artifact("legacy-r2.json", legacy)
        self.assertTrue(
            any(
                "lacks frozen-plan provenance" in error
                for error in validate_bundle(bundle)
            )
        )

        predated = deepcopy(self.r2)
        predated["created_at"] = "2026-09-17T14:59:00-04:00"
        bundle = deepcopy(self.example)
        bundle["artifacts"]["auto_r2"] = self.write_artifact("predated.json", predated)
        self.assertTrue(
            any(
                "after the evaluation plan is frozen" in error
                for error in validate_bundle(bundle)
            )
        )

    def test_duplicate_ids_unneeded_adjudication_and_bad_audit_fail(self):
        duplicate = deepcopy(self.r2)
        duplicate["evaluation_id"] = self.r1["evaluation_id"]
        bundle = deepcopy(self.example)
        bundle["artifacts"]["auto_r2"] = self.write_artifact(
            "duplicate-id.json", duplicate
        )
        self.assertTrue(
            any(
                "evaluation IDs must be unique" in error
                for error in validate_bundle(bundle)
            )
        )

        unneeded = deepcopy(self.r1)
        unneeded["evaluation_id"] = "eval-run01-a-unneeded-adj"
        unneeded["judge"] = {
            "role": "auto-adj",
            "model": "gpt-5.6-sol",
            "reasoning": "high",
            "config_id": "aging-adj-v1",
            "prompt_sha256": "a" * 64,
            "evaluation_config_sha256": "7" * 64,
            "execution_context_id": "judge-context-3",
            "condition_blinded": True,
        }
        unneeded["adjudicates_evaluation_ids"] = [
            self.r1["evaluation_id"],
            self.r2["evaluation_id"],
        ]
        unneeded["audit_trigger_ids"] = ["judge-disagreement"]
        unneeded["requires_human_audit"] = True
        unneeded["created_at"] = "2026-09-17T16:05:00-04:00"
        bundle = deepcopy(self.example)
        bundle["artifacts"]["auto_adj"] = self.write_artifact(
            "unneeded-adj.json", unneeded
        )
        self.assertTrue(
            any(
                "must not run when R1 and R2 agree" in error
                for error in validate_bundle(bundle)
            )
        )

        r1 = deepcopy(self.r1)
        r2 = deepcopy(self.r2)
        for result in (r1, r2):
            result["audit_trigger_ids"] = ["external-claim"]
            result["requires_human_audit"] = True
        bundle = deepcopy(self.example)
        bundle["artifacts"]["auto_r1"] = self.write_artifact("r1-trigger.json", r1)
        bundle["artifacts"]["auto_r2"] = self.write_artifact("r2-trigger.json", r2)
        bundle["artifacts"]["human_audit"] = {
            "audit_id": "audit-bad",
            "actor_id": "human-organizer-a",
            "actor_type": "human",
            "attestation_ref": "course-roster:organizer-a",
            "reviewed_evaluation_ids": [r1["evaluation_id"], "unknown-evaluation"],
            "decision": "accept-selected",
            "reason": "Synthetic invalid audit.",
            "artifact": self.write_byte_artifact("bad-audit.json", b"{}\n"),
            "completed_at": "2026-09-17T15:30:00-04:00",
        }
        bundle["status"] = "completed"
        bundle["selected_evaluation_id"] = r1["evaluation_id"]
        bundle["usable_for_pairing"] = True
        audit_errors = validate_bundle(bundle)
        self.assertTrue(any("must review every" in error for error in audit_errors))
        self.assertTrue(any("completed after" in error for error in audit_errors))


if __name__ == "__main__":
    unittest.main()

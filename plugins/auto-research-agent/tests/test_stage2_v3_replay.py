# ruff: noqa: E402 -- import the repository CLI without installing a package.
"""Deterministic tests for read-only Stage 2 v3 calibration replay."""

import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
sys.path.insert(0, str(PLUGIN / "cli"))
sys.path.insert(0, str(HERE))

from stage1_eval.common import canonical, read_json
from stage2_common import Stage2Error, canonical_hash
from stage2_eval.rubric_quality_v3 import evaluate_quality_v3
from stage2_live.v3_replay import (
    _expected_request,
    _quality_code_sha,
    verify_quality_v3,
)
from test_stage2_rubric_quality_v3 import batch, synthetic_fixture


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def saved_provenance():
    return {
        "attempt": 1,
        "execution_status": "native-complete",
        "reused_completed_generation": False,
        "request_fingerprint_sha256": "c" * 64,
    }


def replayed_provenance():
    return {
        "attempt": 1,
        "execution_status": "native-replayed",
        "reused_completed_generation": False,
        "request_fingerprint_sha256": "c" * 64,
    }


def blind_batch(value, aliases):
    case_aliases = {value: key for key, value in aliases["case_ids"].items()}
    blinded = copy.deepcopy(value)
    for row in blinded["judgments"]:
        original_case = row["case_id"]
        case_alias = case_aliases[original_case]
        evidence_aliases = {
            value: key for key, value in aliases["evidence_ids"][case_alias].items()
        }
        row["case_id"] = case_alias
        row["evidence_ids"] = [
            evidence_aliases[evidence_id] for evidence_id in row["evidence_ids"]
        ]
    return blinded


class QualityV3ReplayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        # macOS exposes /var via /private/var; use the real fixture root while
        # retaining production rejection of caller-supplied symlink ancestors.
        self.parent = Path(temporary.name).resolve()
        self.root = self.parent / "native_calls"
        self.root.mkdir()
        self.codex = self.parent / "codex.exe"
        self.codex.write_bytes(b"frozen codex runtime")
        self.homes = {"R1": self.parent / "r1-home", "R2": self.parent / "r2-home"}
        for home in self.homes.values():
            home.mkdir()
        self.dataset, self.reference, self.rubric = synthetic_fixture()
        for case in self.dataset["cases"]:
            case["observation"] = "synthetic observation"
            case["presentation"] = "synthetic subject record"
        self.config = {
            "codex": str(self.codex),
            "runtime_sha256": digest(self.codex),
            "model": "test-model",
            "reasoning": "high",
            "homes": {role: str(path) for role, path in self.homes.items()},
            "policy": {
                "schema_version": "3.1.0",
                "timeout_seconds": 600,
                "max_transient_transport_retries": 1,
                "max_semantic_corrections_per_unit": 1,
            },
        }
        self.request, self.role_configs, self.policy = _expected_request(
            self.dataset, self.reference, self.rubric, self.config
        )
        write_json(self.parent / "dataset.json", self.dataset)
        write_json(self.parent / "reference.json", self.reference)
        write_json(
            self.parent / "pre_call_freeze.json",
            {
                "dataset_sha256": canonical_hash(self.dataset),
                "reference_sha256": canonical_hash(self.reference),
                "rubric_sha256": canonical_hash(self.rubric),
                "presentations": 72,
                "designated_judgments": 144,
                "formal_ab": False,
                "human_approval_claimed": False,
                "created_at": "synthetic",
            },
        )
        write_json(self.root / "request.json", self.request)
        self.values = {}
        self.unit_receipts = {}
        combined = {}
        for role in ("R1", "R2"):
            combined[role] = batch(self.dataset, self.reference, role)
            for index, criterion in enumerate(self.rubric["criteria"], 1):
                cases = [
                    row
                    for row in self.dataset["cases"]
                    if row["criterion_id"] == criterion["id"]
                ]
                ids = {row["case_id"] for row in cases}
                label = f"{role.lower()}-{index:02d}"
                value = {
                    "kind": "Stage2RubricQualityBatchV3",
                    "role": role,
                    "judgments": [
                        copy.deepcopy(row)
                        for row in combined[role]["judgments"]
                        if row["case_id"] in ids
                    ],
                }
                from stage2_live.rubric_quality_v3 import prepare_quality_batch

                prepared = prepare_quality_batch(role, cases, self.rubric)
                raw_value = blind_batch(value, prepared["aliases"])
                self.values[label] = raw_value
                write_json(
                    self.root / f"{label}.schema.json",
                    prepared["schema"],
                )
                unit = {
                    "label": label,
                    "value": raw_value,
                    "provenance": {"initial": saved_provenance(), "correction": None},
                }
                unit_path = write_json(self.root / f"{label}.unit.json", unit)
                self.unit_receipts[label] = digest(unit_path)
                write_json(self.root / f"{label}.completed.json", value)
                archive = self.root / f"{label}.model-call"
                archive.mkdir()
                (archive / "synthetic-bound.txt").write_bytes(label.encode())
        report = evaluate_quality_v3(
            self.dataset, self.reference, self.rubric, combined["R1"], combined["R2"]
        )
        self.result = {
            "request_sha256": canonical_hash(self.request),
            "roles": combined,
            "quality_report": report,
            "unit_receipts": self.unit_receipts,
            "native_qa_pass": True,
            "formal_ready": False,
            "actual_model_attempts": 18,
            "cost": "unknown",
        }
        self.result_path = write_json(self.root / "result.json", self.result)
        self.receipt = {
            "result_sha256": digest(self.result_path),
            "request_sha256": canonical_hash(self.request),
            "unit_receipts": copy.deepcopy(self.unit_receipts),
        }

    def replay_archive(self, archive, **_kwargs):
        label = Path(archive).name.removesuffix(".model-call")
        label = label.removesuffix("-correction")
        return copy.deepcopy(self.values[label]), replayed_provenance()

    def snapshot(self):
        return {
            path.relative_to(self.parent).as_posix(): path.read_bytes()
            for path in self.parent.rglob("*")
            if path.is_file()
        }

    def verify(self, **overrides):
        arguments = {
            "dataset": self.dataset,
            "reference": self.reference,
            "expected_config": self.config,
        }
        arguments.update(overrides)
        return verify_quality_v3(self.root, self.receipt, **arguments)

    def producer_binding(self, *, ast_change=False):
        import stage2_eval.rubric_quality_v3 as evaluator
        import stage2_live.rubric_quality_v3 as live

        archive = self.parent / "producer_code_before_format"
        archive.mkdir(exist_ok=True)
        current = {
            "live": Path(live.__file__).read_bytes(),
            "evaluator": Path(evaluator.__file__).read_bytes(),
        }
        archived = {name: b"\n\n" + raw for name, raw in current.items()}
        if ast_change:
            archived["live"] += b"\nMIGRATION_SENTINEL = 1\n"
        paths = {}
        hashes = {}
        for name, raw in archived.items():
            paths[name] = archive / f"{name}.py"
            paths[name].write_bytes(raw)
            hashes[name] = hashlib.sha256(raw).hexdigest()
        return {
            "live_path": str(paths["live"]),
            "evaluator_path": str(paths["evaluator"]),
            "live_sha256": hashes["live"],
            "evaluator_sha256": hashes["evaluator"],
            "code_sha256": canonical_hash(hashes),
            "reason": "format-only",
        }

    def install_migrated_request(self, binding):
        request, _, _ = _expected_request(
            self.dataset,
            self.reference,
            self.rubric,
            self.config,
            binding,
        )
        write_json(self.root / "request.json", request)
        self.result["request_sha256"] = canonical_hash(request)
        write_json(self.result_path, self.result)
        self.receipt["request_sha256"] = canonical_hash(request)
        self.receipt["result_sha256"] = digest(self.result_path)
        return request

    def test_authenticates_all_18_units_read_only_and_recomputes_qa(self):
        before = self.snapshot()
        with (
            patch(
                "stage2_live.replay.replay_native_model_call_archive",
                side_effect=self.replay_archive,
            ) as replay,
            patch(
                "stage1_eval.model_calls.call_model_v31",
                side_effect=AssertionError("model dispatch forbidden"),
            ) as dispatch,
        ):
            verified = self.verify()
        dispatch.assert_not_called()
        self.assertEqual(replay.call_count, 18)
        self.assertTrue(verified["authenticated"])
        self.assertTrue(verified["qa_pass"])
        self.assertFalse(verified["formal_ready"])
        self.assertEqual(verified["actual_model_attempts"], 18)
        self.assertEqual(verified["quality_report"], self.result["quality_report"])
        self.assertEqual(self.snapshot(), before)

    def test_rejects_result_unit_role_and_saved_pass_tamper(self):
        original_result = self.result_path.read_bytes()
        self.result_path.write_bytes(original_result + b" ")
        with self.assertRaisesRegex(Stage2Error, "result-receipt-mismatch"):
            self.verify()
        self.result_path.write_bytes(original_result)

        swapped = copy.deepcopy(self.receipt)
        swapped["unit_receipts"]["r1-01"], swapped["unit_receipts"]["r2-01"] = (
            swapped["unit_receipts"]["r2-01"],
            swapped["unit_receipts"]["r1-01"],
        )
        with self.assertRaisesRegex(Stage2Error, "unit-receipt-mismatch"):
            verify_quality_v3(
                self.root,
                swapped,
                dataset=self.dataset,
                reference=self.reference,
                expected_config=self.config,
            )

        unit_path = self.root / "r1-01.unit.json"
        original_unit = unit_path.read_bytes()
        original_value = copy.deepcopy(self.values["r1-01"])
        swapped_role = read_json(unit_path)
        swapped_role["value"]["role"] = "R2"
        write_json(unit_path, swapped_role)
        self.receipt["unit_receipts"]["r1-01"] = digest(unit_path)
        self.values["r1-01"] = copy.deepcopy(swapped_role["value"])
        correction = self.root / "r1-01-correction.model-call"
        correction.mkdir()
        (correction / "synthetic-bound.txt").write_bytes(b"correction")
        with (
            patch(
                "stage2_live.replay.replay_native_model_call_archive",
                side_effect=self.replay_archive,
            ),
            self.assertRaisesRegex(Stage2Error, "batch-role"),
        ):
            self.verify()
        unit_path.write_bytes(original_unit)
        (correction / "synthetic-bound.txt").unlink()
        correction.rmdir()
        self.receipt["unit_receipts"]["r1-01"] = self.unit_receipts["r1-01"]
        self.values["r1-01"] = original_value

        tampered = copy.deepcopy(self.result)
        tampered["native_qa_pass"] = False
        write_json(self.result_path, tampered)
        self.receipt["result_sha256"] = digest(self.result_path)
        with (
            patch(
                "stage2_live.replay.replay_native_model_call_archive",
                side_effect=self.replay_archive,
            ),
            self.assertRaisesRegex(Stage2Error, "result-recomputation-mismatch"),
        ):
            self.verify()

    def test_rejects_changed_inputs_config_and_injected_mode_before_replay(self):
        changed_dataset = copy.deepcopy(self.dataset)
        changed_dataset["cases"][0]["observation"] = "changed"
        with self.assertRaises(Stage2Error):
            self.verify(dataset=changed_dataset)

        changed_config = copy.deepcopy(self.config)
        changed_config["model"] = "changed-model"
        with self.assertRaisesRegex(Stage2Error, "request-bytes-mismatch"):
            self.verify(expected_config=changed_config)

        request = read_json(self.root / "request.json")
        request["mode"] = "injected-test"
        write_json(self.root / "request.json", request)
        with (
            patch("stage2_live.v3_replay.replay_unit") as replay,
            self.assertRaisesRegex(Stage2Error, "request-bytes-mismatch"),
        ):
            self.verify()
        replay.assert_not_called()

    def test_rejects_missing_freeze_and_current_code_binding_change(self):
        (self.parent / "pre_call_freeze.json").unlink()
        with self.assertRaisesRegex(Stage2Error, "missing-replay-file"):
            self.verify()

        write_json(
            self.parent / "pre_call_freeze.json",
            {
                "dataset_sha256": canonical_hash(self.dataset),
                "reference_sha256": canonical_hash(self.reference),
                "rubric_sha256": canonical_hash(self.rubric),
                "presentations": 72,
                "designated_judgments": 144,
                "formal_ab": False,
                "human_approval_claimed": False,
            },
        )
        request = read_json(self.root / "request.json")
        request["code_sha256"] = "f" * 64
        write_json(self.root / "request.json", request)
        with self.assertRaisesRegex(Stage2Error, "request-bytes-mismatch"):
            self.verify()

    def test_format_only_producer_binding_migrates_old_hash_and_stays_read_only(self):
        binding = self.producer_binding()
        request = self.install_migrated_request(binding)
        before = self.snapshot()
        with patch(
            "stage2_live.replay.replay_native_model_call_archive",
            side_effect=self.replay_archive,
        ):
            verified = self.verify(producer_binding=binding)
        self.assertEqual(
            verified["producer_migration_status"], "format-only-ast-equivalent"
        )
        self.assertEqual(verified["producer_code_sha256"], binding["code_sha256"])
        self.assertEqual(verified["current_code_sha256"], _quality_code_sha())
        self.assertNotEqual(
            verified["producer_code_sha256"], verified["current_code_sha256"]
        )
        self.assertEqual(request["code_sha256"], binding["code_sha256"])
        self.assertFalse(verified["formal_ready"])
        self.assertEqual(self.snapshot(), before)
        with self.assertRaisesRegex(Stage2Error, "request-bytes-mismatch"):
            self.verify()

    def test_producer_binding_rejects_ast_change_and_false_hashes(self):
        changed = self.producer_binding(ast_change=True)
        with self.assertRaisesRegex(Stage2Error, "live-ast-changed"):
            self.verify(producer_binding=changed)

        false_hash = self.producer_binding()
        false_hash["live_sha256"] = "0" * 64
        with self.assertRaisesRegex(Stage2Error, "live-sha256-mismatch"):
            self.verify(producer_binding=false_hash)


if __name__ == "__main__":
    unittest.main()

"""Read-only rubric-quality admission revalidates immutable native evidence."""

import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage1_eval.common import canonical  # noqa: E402
from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_eval.evaluation import RUBRIC_PATH, _load_rubric  # noqa: E402
from stage2_eval.rubric_quality import evaluate_quality  # noqa: E402
import stage2_eval.rubric_admission as admission  # noqa: E402
from stage2_live.judges import _execution_policy  # noqa: E402
from stage2_live.native import codex_runtime_sha  # noqa: E402
from stage2_live.rubric_adjudication import _base_labels  # noqa: E402
from stage2_live.rubric_quality import _load_guidance  # noqa: E402
from test_stage2_rubric_quality import fixtures, judgments  # noqa: E402


class RubricAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.run = self.root / "run"
        self.run.mkdir()
        self.binary = self.root / "codex.exe"
        self.binary.write_bytes(b"synthetic codex")
        for name in ("r1", "r2"):
            (self.root / name).mkdir()
        self.dataset, self.reference = fixtures()
        self.dataset_sha = canonical_hash(self.dataset)
        self.reference_sha = canonical_hash(self.reference)
        rubric, rubric_sha = _load_rubric(RUBRIC_PATH)
        _, guidance_sha = _load_guidance(rubric)
        self.code_sha = "a" * 64
        self.policy = _execution_policy({"evaluator_bundle_sha256": self.code_sha})
        self.bindings = {
            "dataset_sha256": self.dataset_sha,
            "rubric_sha256": rubric_sha,
            "guidance_sha256": guidance_sha,
            "code_sha256": self.code_sha,
            "runtime_sha256": codex_runtime_sha(self.binary),
            "model": "gpt-test",
            "reasoning": "medium",
            "execution_policy_sha256": canonical_hash(self.policy),
            "evaluator_homes": {
                "R1": str((self.root / "r1").resolve()),
                "R2": str((self.root / "r2").resolve()),
            },
        }
        self.roles = {
            role: judgments(self.dataset, role, self.bindings) for role in ("R1", "R2")
        }
        report = evaluate_quality(
            self.dataset,
            self.reference,
            self.roles["R1"],
            self.roles["R2"],
            dataset_sha256=self.dataset_sha,
            reference_sha256=self.reference_sha,
            bindings={
                key: value
                for key, value in self.bindings.items()
                if key != "dataset_sha256"
            },
        )
        report["native_qa_pass"] = report["passed"]
        self.request = {
            "kind": "Stage2RubricQualityRequest",
            "schema_version": "1.0.0",
            **self.bindings,
            "reference_sha256": self.reference_sha,
            "adapter_mode": "native",
            "batch_size": 7,
            "units_per_role": 8,
            "planned_units": 16,
            "cost": "unknown",
            "resume_supported": False,
        }
        self.result = {
            "kind": "Stage2RubricQualityRun",
            "schema_version": "1.0.0",
            "status": "complete",
            "adapter_mode": "native",
            "evidence_class": "native-live-diagnostic",
            "request_sha256": canonical_hash(self.request),
            "bindings": self.bindings,
            "roles": self.roles,
            "quality_report": report,
            "unit_receipts": {label: "b" * 64 for label in _base_labels()},
            "formal_ready": False,
        }
        self._write_run()

    def tearDown(self):
        self.temporary.cleanup()

    def _write_run(self):
        (self.run / "request.json").write_bytes(canonical(self.request) + b"\n")
        (self.run / "result.json").write_bytes(canonical(self.result) + b"\n")
        self.result_sha = hashlib.sha256(
            (self.run / "result.json").read_bytes()
        ).hexdigest()
        for label in _base_labels():
            (self.run / f"{label}.schema.json").write_text("{}", encoding="utf-8")
            (self.run / f"{label}.unit.json").write_text("{}", encoding="utf-8")
            archive = self.run / f"{label}.model-call"
            archive.mkdir(exist_ok=True)
            (archive / "request.json").write_bytes(
                canonical({"execution_policy": self.policy}) + b"\n"
            )

    def verify(self):
        before = {
            path.relative_to(self.run): (path.stat().st_mtime_ns, path.read_bytes())
            for path in self.run.rglob("*")
            if path.is_file()
        }
        with mock.patch.object(admission, "_REPLAY_BASE", return_value=self.roles):
            result = admission.verify_rubric_quality_admission(
                self.dataset,
                self.reference,
                dataset_sha256=self.dataset_sha,
                reference_sha256=self.reference_sha,
                run_dir=self.run,
                run_result_sha256=self.result_sha,
                codex=self.binary,
            )
        after = {
            path.relative_to(self.run): (path.stat().st_mtime_ns, path.read_bytes())
            for path in self.run.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)
        return result

    def test_synthetic_positive_recomputes_fixed_counts_but_cannot_admit(self):
        result = self.verify()
        self.assertEqual(result["kind"], "Stage2RubricQualityAdmission")
        self.assertEqual(result["counts"]["within_range_total"], 112)
        self.assertEqual(result["counts"]["agreement_total"], 56)
        self.assertEqual(result["counts"]["invariant_total"], 56)
        self.assertEqual(result["replayed_model_units"], 16)
        self.assertEqual(result["new_model_calls"], 0)
        self.assertEqual(result["evidence_class"], "synthetic-test-only")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["formal_ready"])

    def test_failed_raw_quality_and_missing_rows_cannot_admit(self):
        self.roles["R2"]["judgments"][0]["major_error"] = True
        report = evaluate_quality(
            self.dataset,
            self.reference,
            self.roles["R1"],
            self.roles["R2"],
            dataset_sha256=self.dataset_sha,
            reference_sha256=self.reference_sha,
            bindings={
                key: value
                for key, value in self.bindings.items()
                if key != "dataset_sha256"
            },
        )
        report["native_qa_pass"] = False
        self.result["roles"] = self.roles
        self.result["quality_report"] = report
        self._write_run()
        result = self.verify()
        self.assertFalse(result["accepted"])
        self.assertIn(
            "significant reviewer disagreements require adjudication", result["reasons"]
        )

        missing = copy.deepcopy(self.roles)
        missing["R1"]["judgments"].pop()
        missing_report = evaluate_quality(
            self.dataset,
            self.reference,
            missing["R1"],
            missing["R2"],
            dataset_sha256=self.dataset_sha,
            reference_sha256=self.reference_sha,
            bindings={
                key: value
                for key, value in self.bindings.items()
                if key != "dataset_sha256"
            },
        )
        missing_report["native_qa_pass"] = False
        self.roles = missing
        self.result["roles"] = missing
        self.result["quality_report"] = missing_report
        self._write_run()
        result = self.verify()
        self.assertIn("evaluator judgments are missing", result["reasons"])

    def test_runtime_guidance_and_archive_tamper_fail_closed(self):
        self.binary.write_bytes(b"changed runtime")
        with self.assertRaisesRegex(Stage2Error, "runtime"):
            self.verify()
        self.binary.write_bytes(b"synthetic codex")
        with (
            mock.patch.object(admission, "_load_guidance", return_value=({}, "f" * 64)),
            self.assertRaisesRegex(Stage2Error, "guidance"),
        ):
            self.verify()
        (self.run / "r1-01.schema.json").unlink()
        with self.assertRaisesRegex(Stage2Error, "missing base"):
            self.verify()

    def test_tampered_result_and_malformed_input_fail_typed_without_dispatch(self):
        (self.run / "result.json").write_bytes(
            (self.run / "result.json").read_bytes() + b" "
        )
        with self.assertRaisesRegex(Stage2Error, "result hash"):
            self.verify()
        malformed = []
        with self.assertRaisesRegex(Stage2Error, "dataset must be an object"):
            admission.verify_rubric_quality_admission(
                malformed,
                self.reference,
                dataset_sha256=canonical_hash(malformed),
                reference_sha256=self.reference_sha,
                run_dir=self.run,
                run_result_sha256=self.result_sha,
                codex=self.binary,
            )

    def test_fake_or_incomplete_base_run_is_rejected(self):
        for field, value in (
            ("evidence_class", "injected-fake-test-only"),
            ("status", "evaluator-failure"),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.result)
                changed[field] = value
                (self.run / "result.json").write_bytes(canonical(changed) + b"\n")
                digest = hashlib.sha256(
                    (self.run / "result.json").read_bytes()
                ).hexdigest()
                with self.assertRaisesRegex(Stage2Error, "native evidence|incomplete"):
                    with mock.patch.object(
                        admission, "_REPLAY_BASE", return_value=self.roles
                    ):
                        admission.verify_rubric_quality_admission(
                            self.dataset,
                            self.reference,
                            dataset_sha256=self.dataset_sha,
                            reference_sha256=self.reference_sha,
                            run_dir=self.run,
                            run_result_sha256=digest,
                            codex=self.binary,
                        )

    def test_primitive_native_result_raises_stage2_error(self):
        for value in ([], None, "invalid", 1):
            with self.subTest(value=value):
                (self.run / "result.json").write_bytes(canonical(value) + b"\n")
                self.result_sha = hashlib.sha256(
                    (self.run / "result.json").read_bytes()
                ).hexdigest()
                with self.assertRaises(Stage2Error):
                    self.verify()


if __name__ == "__main__":
    unittest.main()

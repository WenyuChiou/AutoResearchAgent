"""Native rubric QA is additional readiness evidence, never a promotion flag."""

import copy
import json
import os
from pathlib import Path
import sys
import subprocess
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stage2_eval.formal import (  # noqa: E402
    FormalError,
    _rubric_quality_blockers,
    validate_readiness_v1,
)
import test_stage2_formal as formal_fixtures  # noqa: E402


class FormalRubricGateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = formal_fixtures.Stage2FormalTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        formal_fixtures.write_json(self.root / "qa-dataset.json", {"cases": []})
        formal_fixtures.write_json(self.root / "qa-reference.json", {"rows": []})
        (self.root / "qa-run").mkdir()
        self.expected = {
            "verification_code_sha256": "1" * 64,
            "model": "gpt-test",
            "reasoning": "high",
            "runtime_sha256": "2" * 64,
            "rubric_sha256": "3" * 64,
            "guidance_sha256": "4" * 64,
            "execution_policy_sha256": "6" * 64,
        }
        self.binding = {
            **self.expected,
            "dataset": formal_fixtures.reference(
                self.root, self.root / "qa-dataset.json"
            ),
            "reference": formal_fixtures.reference(
                self.root, self.root / "qa-reference.json"
            ),
            "run_dir": "qa-run",
            "run_result_sha256_receipt": "5" * 64,
            "codex_executable": str((self.root / "codex.exe").resolve()),
        }

    def result(self, **changes):
        return {
            "accepted": True,
            "formal_ready": False,
            "bindings": self.expected,
            **changes,
        }

    def verifiers(self):
        return {
            "inspect_preflight": lambda *a, **kw: {
                "status": "passed",
                "runtime_gate": True,
            },
            "verify_preflight": lambda *a, **kw: {
                "status": "passed",
                "runtime_gate": True,
            },
            "verify_controller": lambda *a, **kw: {
                "pilot_executable": True,
                "authentic_native_execution": True,
                "synthetic_test_only": False,
            },
            "verify_calibration_unit": lambda root, *a, **kw: {
                "result": json.loads(
                    (root / "calibration-result.json").read_text(encoding="utf-8")
                )
            },
            "verify_rubric_quality": lambda *a, **kw: self.result(),
        }

    def test_versioned_gate_is_required_and_synthetic_never_promotes(self):
        manifest = self.fixture._readiness_manifest()
        judge = self.fixture.plan["evaluator_contracts"]["judge"]
        for field in ("model", "reasoning", "runtime_sha256"):
            self.expected[field] = judge[field]
            self.binding[field] = judge[field]
        manifest["schema_version"] = "1.1.0"
        path, receipt = self.fixture._save_manifest(manifest, "qa-readiness.json")
        with self.assertRaisesRegex(FormalError, "readiness manifest fields"):
            validate_readiness_v1(
                path, self.root, receipt, _synthetic_test_verifiers=self.verifiers()
            )
        manifest["rubric_quality"] = self.binding
        path, receipt = self.fixture._save_manifest(
            manifest, "qa-readiness-complete.json"
        )
        result = validate_readiness_v1(
            path, self.root, receipt, _synthetic_test_verifiers=self.verifiers()
        )
        self.assertFalse(result["formal_ready"])
        self.assertEqual(result["blockers"], ["synthetic-test-only"])

    def test_unaccepted_qa_stays_blocked(self):
        self.assertEqual(
            _rubric_quality_blockers(
                self.binding, self.root, lambda *a, **kw: self.result(accepted=False)
            ),
            ["rubric-quality-not-accepted"],
        )

    def test_current_verifier_and_settings_cannot_be_swapped(self):
        for field in self.expected:
            with self.subTest(field=field):
                different = {**self.expected, field: "changed"}
                with self.assertRaisesRegex(
                    FormalError, "differs from manifest binding"
                ):
                    _rubric_quality_blockers(
                        self.binding,
                        self.root,
                        lambda *a, **kw: self.result(bindings=different),
                    )

    def test_qa_cannot_self_declare_formal_ready(self):
        with self.assertRaisesRegex(FormalError, "QA cannot itself"):
            _rubric_quality_blockers(
                self.binding, self.root, lambda *a, **kw: self.result(formal_ready=True)
            )

    def test_calibration_for_another_judge_cannot_satisfy_plan(self):
        with self.assertRaisesRegex(FormalError, "judge differs from frozen"):
            _rubric_quality_blockers(
                self.binding,
                self.root,
                lambda *a, **kw: self.result(),
                judge_contract={
                    "model": "different",
                    "reasoning": "high",
                    "runtime_sha256": "2" * 64,
                },
            )

    def test_reference_tamper_and_path_escape_reject_before_replay(self):
        invalid = copy.deepcopy(self.binding)
        invalid["run_dir"] = "../outside"
        with self.assertRaisesRegex(FormalError, "unsafe"):
            _rubric_quality_blockers(
                invalid, self.root, lambda *a, **kw: self.fail("must not replay")
            )
        (self.root / "qa-reference.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(FormalError, "hash mismatch"):
            _rubric_quality_blockers(
                self.binding, self.root, lambda *a, **kw: self.fail("must not replay")
            )

    def test_linked_run_root_rejected_before_resolution(self):
        target = self.root / "qa-run"
        alias = self.root / "qa-alias"
        if os.name == "nt":
            process = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(alias), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
        else:
            try:
                alias.symlink_to(target, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"Host does not grant directory links: {error}")
        invalid = {**self.binding, "run_dir": "qa-alias"}
        with self.assertRaisesRegex(FormalError, "linked path component"):
            _rubric_quality_blockers(
                invalid, self.root, lambda *a, **kw: self.fail("must not replay")
            )


if __name__ == "__main__":
    unittest.main()

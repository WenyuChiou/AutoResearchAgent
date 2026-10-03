"""Regression tests for the read-only Stage 2 formal-admission contracts."""

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
import io
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "cli"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(CLI))
sys.path.insert(0, str(TESTS))

# ruff: noqa: E402 -- repository CLIs are intentionally imported without install.
from stage2_eval.formal import (
    FormalError,
    freeze_formal_plan_v1,
    validate_formal_plan_v1,
    validate_formal_result_v1,
    validate_readiness_v1,
)
from stage2_common import canonical_hash
from stage2_eval import __main__ as eval_cli
from stage2_eval.evaluation import RUBRIC_PATH
from stage2_live.calibration import prepare_calibration
import test_stage2_evaluation as evaluation_fixtures
import test_stage2_diagnostics as diagnostic_fixtures


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return path


def reference(root, path):
    path = Path(path)
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


class Stage2FormalTests(unittest.TestCase):
    def test_production_only_preflight_cannot_replace_formal_isolation(self):
        manifest = self._readiness_manifest()
        report = {
            "kind": "Stage2ProductionRuntimePreflight",
            "status": "passed",
            "runtime_gate": True,
            "validation_scope": "production-single",
        }
        path = write_json(self.root / "preflight-A.json", report)
        manifest["preflights"][0]["report"] = reference(self.root, path)
        manifest_path, digest = self._save_manifest(manifest, "readiness.json")
        with self.assertRaisesRegex(FormalError, "production-only preflight"):
            validate_readiness_v1(manifest_path, self.root, digest)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write_json(self.root / "brief.json", {"brief": "common"})
        write_json(self.root / "stage1-sources.json", {"sources": ["same"]})
        (self.root / "prompt.txt").write_text("same frozen prompt", encoding="utf-8")
        (self.root / "rubric.json").write_bytes(RUBRIC_PATH.read_bytes())
        runs = []
        for index, (order, arm) in enumerate(
            (
                ("AB", "A"),
                ("AB", "B"),
                ("BA", "B"),
                ("BA", "A"),
                ("AB", "A"),
                ("AB", "B"),
            ),
            1,
        ):
            runs.append(
                {
                    "pair_id": f"pair-{(index + 1) // 2}",
                    "order": order,
                    "arm": arm,
                    "subject_id": f"subject-{index}",
                    "harness_bindings": None
                    if arm == "A"
                    else {"stage2_plugin": "2" * 64, "research_dependency": "3" * 64},
                }
            )
        self.config = {
            "brief": reference(self.root, self.root / "brief.json"),
            "rubric": reference(self.root, self.root / "rubric.json"),
            "stage1_source_manifest": reference(
                self.root, self.root / "stage1-sources.json"
            ),
            "prompt": reference(self.root, self.root / "prompt.txt"),
            "model": "gpt-5.6-sol",
            "reasoning": "high",
            "task": "Stage 2 direction selection",
            "native_capability_policy": {
                "search": True,
                "files": True,
                "subagents": True,
            },
            "cutoff": "2026-09-29T00:00:00Z",
            "investment_policy": {
                "elapsed_time": "bounded by frozen runner policy",
                "model_calls": "record every actual call",
                "unknown_cost": "remain unknown",
            },
            "runtime_sha256": "1" * 64,
            "plugin_sha256": "2" * 64,
            "dependency_sha256": "3" * 64,
            "evaluator_contracts": {
                role: {
                    "model": "judge-model",
                    "reasoning": "high",
                    "runtime_sha256": "4" * 64,
                    "policy_sha256": "5" * 64,
                }
                for role in ("extraction", "actions", "judge")
            },
            "runtime_contracts": {
                arm: {
                    "inventory_sha256": "6" * 64,
                    "policy_bindings": {"sandbox": "workspace-write"},
                    "config_bindings": {}
                    if arm == "A"
                    else {"stage2_plugin": "2" * 64, "research_dependency": "3" * 64},
                }
                for arm in ("A", "B")
            },
            "runs": runs,
        }
        self.plan = freeze_formal_plan_v1(self.config, self.root)

    def _bundles(self, *, audit_first=False):
        fixture = evaluation_fixtures.Stage2EvaluationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        bundles = []
        for index, subject in enumerate(
            [row["subject_id"] for row in self.plan["runs"]]
        ):
            major = "fabricated-evidence" if audit_first and index == 0 else None
            bundles.append(fixture._bundle(subject, 1, 1, 1, 1, major=major))
        return bundles

    def _formal_manifest(self, *, audit_first=False):
        bundles = self._bundles(audit_first=audit_first)
        rows = []
        for planned, bundle in zip(self.plan["runs"], bundles, strict=True):
            subject = planned["subject_id"]
            capture = self.root / "captures" / subject
            capture.mkdir(parents=True, exist_ok=True)
            extraction = write_json(
                self.root / "extractions" / f"{subject}.json",
                {
                    "subject_id": subject,
                    "source_locations": ["source-1#paragraph-1"],
                },
            )
            extraction_ref = reference(self.root, extraction)
            receipt = write_json(
                self.root / "extractions" / f"{subject}.receipt.json",
                {
                    "result_sha256": extraction_ref["sha256"],
                    "unit_receipts": {"shared-extraction": "4" * 64},
                },
            )
            judge_input = write_json(
                self.root / "judges" / f"{subject}.input.json",
                {
                    "subject_id": subject,
                    "content_first": True,
                    "source_locations": ["source-1#paragraph-1"],
                },
            )
            judge_archive = self.root / "judges" / f"{subject}.archive"
            judge_archive.mkdir(exist_ok=True)
            judge_unit_receipts = {}
            labels = ["r1-content", "r1-judge", "r2-content", "r2-judge"]
            if bundle["adjudicated"]:
                labels.extend(("adj-content", "adj-judge"))
            for label in labels:
                unit_path = write_json(
                    judge_archive / f"{label}.unit.json", {"label": label}
                )
                (judge_archive / f"{label}.model-call").mkdir(exist_ok=True)
                write_json(
                    judge_archive / f"{label}.model-call/request.json",
                    {"label": label},
                )
                judge_unit_receipts[label] = hashlib.sha256(
                    unit_path.read_bytes()
                ).hexdigest()
            judge_receipt_path = write_json(
                self.root / "judges" / f"{subject}.receipt.json",
                {
                    "result_sha256": "6" * 64,
                    "unit_receipts": judge_unit_receipts,
                },
            )
            bundle_path = write_json(
                self.root / "judges" / f"{subject}.bundle.json", bundle
            )
            audit_ref = None
            if bundle["audit_required"]:
                audit_path = write_json(
                    self.root / "judges" / f"{subject}.audit.json",
                    bundle["raw"]["audit"],
                )
                audit_ref = reference(self.root, audit_path)
            rows.append(
                {
                    "subject_id": subject,
                    "native_capture": {
                        "directory": capture.relative_to(self.root).as_posix(),
                        "record_sha256_receipt": hashlib.sha256(
                            subject.encode()
                        ).hexdigest(),
                    },
                    "extraction": {
                        "artifact": extraction_ref,
                        "external_replay_receipt": reference(self.root, receipt),
                        "source_locations": ["source-1#paragraph-1"],
                        "packet": reference(
                            self.root, self.root / "stage1-sources.json"
                        ),
                        "source_root": "captures",
                        "snapshot_sha256": "a" * 64,
                        "config": {},
                        "policy": {},
                    },
                    "judge_input": reference(self.root, judge_input),
                    "judge_archive": {
                        "directory": judge_archive.relative_to(self.root).as_posix(),
                        "external_replay_receipt": reference(
                            self.root, judge_receipt_path
                        ),
                        "config": {},
                        "policy": {},
                        "action_record": reference(self.root, self.root / "brief.json"),
                    },
                    "judge_bundle": reference(self.root, bundle_path),
                    "named_audit": audit_ref,
                    "action_extraction": {},
                    "execution_environment": {},
                }
            )
        by_subject = {row["subject_id"]: bundle for row, bundle in zip(rows, bundles)}
        pairs = []
        for index, order in enumerate(("AB", "BA", "AB")):
            planned = self.plan["runs"][index * 2 : index * 2 + 2]
            by_arm = {row["arm"]: row for row in planned}
            a = by_subject[by_arm["A"]["subject_id"]]
            b = by_subject[by_arm["B"]["subject_id"]]
            pairs.append(
                {
                    "pair_id": f"pair-{index + 1}",
                    "order": order,
                    "A": a,
                    "B": b,
                    "A_content_view_sha256": a["content_view_sha256"],
                    "B_content_view_sha256": b["content_view_sha256"],
                }
            )
        pair_path = write_json(self.root / "pairs.json", pairs)
        return {
            "kind": "Stage2FormalResultManifest",
            "schema_version": "1.0.0",
            "plan_sha256": self.plan["plan_sha256"],
            "evidence_class": "synthetic-test-only",
            "runs": rows,
            "pairs": reference(self.root, pair_path),
            "claim_audit": None,
            "readiness": reference(self.root, self.root / "brief.json"),
            "readiness_receipt": reference(self.root, self.root / "brief.json")[
                "sha256"
            ],
        }

    def _save_manifest(self, value, name="formal-result.json"):
        path = write_json(self.root / name, value)
        return path.relative_to(self.root).as_posix(), hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

    def _readiness_manifest(self):
        report = {"status": "passed", "runtime_gate": True}
        probe = {"probe": "frozen"}
        inventory = {"inventory": "frozen"}
        preflights = []
        for arm in ("A", "B"):
            report_path = write_json(self.root / f"preflight-{arm}.json", report)
            probe_path = write_json(self.root / f"probe-{arm}.json", probe)
            inventory_path = write_json(self.root / f"inventory-{arm}.json", inventory)
            capture = self.root / f"preflight-capture-{arm}"
            capture.mkdir()
            preflights.append(
                {
                    "arm": arm,
                    "report": reference(self.root, report_path),
                    "capture_dir": capture.relative_to(self.root).as_posix(),
                    "capture_record_sha256_receipt": "7" * 64,
                    "probe_spec": reference(self.root, probe_path),
                    "inventory_receipt": reference(self.root, inventory_path),
                }
            )
        pilots = []
        for topic in ("US-aging", "flaky-tests"):
            controller = self.root / f"pilot-{topic}"
            controller.mkdir()
            pilots.append(
                {
                    "topic_id": topic,
                    "controller_dir": controller.relative_to(self.root).as_posix(),
                    "controller_manifest_sha256_receipt": hashlib.sha256(
                        topic.encode()
                    ).hexdigest(),
                    "brief": reference(
                        self.root,
                        write_json(self.root / f"{topic}-brief.json", {"topic": topic}),
                    ),
                }
            )

        base = diagnostic_fixtures.cases()[0]
        cases = []
        for index in range(13):
            case = copy.deepcopy(base)
            case["case_id"] = f"calibration-{index + 1}"
            case["research_candidate"]["id"] = f"candidate-{index + 1}"
            case["claim_under_review"]["id"] = f"claim-{index + 1}"
            case["source_facts"][0]["evidence_id"] = f"fact-{index + 1}"
            cases.append(case)
        cases_path = write_json(self.root / "calibration/cases.json", cases)
        recipes = []
        for variant in ("base", "order", "verbosity", "prestige", "preference"):
            payload = {
                "recipe_id": variant,
                "presentation_note": f"Frozen {variant} presentation.",
                "case_order": list(range(1, 14)),
            }
            recipes.append({**payload, "recipe_sha256": canonical_hash(payload)})
        recipe_value = {"schema_version": "2.0.0", "recipes": recipes}
        recipes_path = write_json(self.root / "calibration/recipes.json", recipe_value)
        frozen_units = prepare_calibration(cases, recipe_value)
        units = []
        result_refs = {}
        for frozen in frozen_units:
            variant = frozen["variant"]
            directory = self.root / "calibration" / variant
            directory.mkdir(parents=True)
            frozen_path = write_json(directory / "frozen-unit.json", frozen)
            unit_path = write_json(
                directory / "diagnostic.unit.json", {"variant": variant}
            )
            (directory / "diagnostic.model-call").mkdir()
            write_json(
                directory / "diagnostic.model-call/request.json",
                {"variant": variant},
            )
            result = {
                "kind": "Stage2CalibrationUnit",
                "schema_version": "2.1.0",
                "variant": variant,
                "unit_sha256": canonical_hash(frozen),
                "case_outputs": 13,
                "evidence_class": "supplied-fact-live-diagnostic",
                "unit_receipts": {
                    "diagnostic": hashlib.sha256(unit_path.read_bytes()).hexdigest()
                },
            }
            result_path = write_json(directory / "calibration-result.json", result)
            result_ref = reference(self.root, result_path)
            result_refs[variant] = result_ref["sha256"]
            units.append(
                {
                    "variant": variant,
                    "frozen_unit": reference(self.root, frozen_path),
                    "result": result_ref,
                    "replay_receipt": reference(
                        self.root,
                        write_json(
                            directory / "receipt.json",
                            {
                                "result_sha256": result_ref["sha256"],
                                "unit_receipts": result["unit_receipts"],
                            },
                        ),
                    ),
                    "config": {},
                    "policy": {},
                }
            )
        audit = {
            "kind": "Stage2CalibrationSemanticAudit",
            "schema_version": "1.0.0",
            "reviewer": "Independent reviewer",
            "reviewer_role": "independent-ai",
            "result_sha256s": result_refs,
            "decision": "accepted",
            "rationale": "The source-supplied variants were reviewed independently.",
            "preassessment": reference(self.root, self.root / "brief.json"),
            "review_record": reference(self.root, self.root / "brief.json"),
            "case_reviews": [
                {
                    "variant": v,
                    "case_id": c["case_id"],
                    "status": "accepted",
                    "reason": "Fixture source support",
                    "evidence_ids": [c["source_facts"][0]["evidence_id"]],
                }
                for v in ("base", "order", "verbosity", "prestige", "preference")
                for c in cases
            ],
        }
        audit_path = write_json(self.root / "calibration/audit.json", audit)
        plan_path = write_json(self.root / "formal-plan.json", self.plan)
        return {
            "kind": "Stage2FormalReadinessManifest",
            "schema_version": "1.0.0",
            "preflights": preflights,
            "pilots": pilots,
            "calibration": {
                "cases": reference(self.root, cases_path),
                "recipes": reference(self.root, recipes_path),
                "units": units,
                "semantic_audit": reference(self.root, audit_path),
            },
            "formal_plan": reference(self.root, plan_path),
        }

    @staticmethod
    def _synthetic_verifier(kind, value, path):
        if kind not in {"capture", "extraction"}:
            raise AssertionError(kind)
        if not Path(path).exists():
            raise AssertionError(path)

    def test_duplicate_or_out_of_order_sessions_are_rejected(self):
        from stage2_eval.formal import _verify_run_chronology

        rows = [
            {
                "event_summary": {"thread_id": f"s{i}"},
                "started_at": f"2026-09-29T0{i}:00:00+00:00",
                "ended_at": f"2026-09-29T0{i}:01:00+00:00",
            }
            for i in range(6)
        ]
        _verify_run_chronology(rows)
        rows[1]["event_summary"]["thread_id"] = "s0"
        with self.assertRaisesRegex(FormalError, "distinct native session"):
            _verify_run_chronology(rows)
        rows[1]["event_summary"]["thread_id"] = "s1"
        rows[1]["started_at"] = rows[0]["started_at"]
        with self.assertRaisesRegex(FormalError, "observed execution order"):
            _verify_run_chronology(rows)
        manifest = self._formal_manifest()
        manifest["runs"][1]["native_capture"] = manifest["runs"][0]["native_capture"]
        path, receipt = self._save_manifest(manifest)
        with self.assertRaisesRegex(FormalError, "distinct capture"):
            validate_formal_result_v1(
                path,
                self.root,
                receipt,
                self.plan,
                _synthetic_test_verifier=self._synthetic_verifier,
            )

    def test_plan_freezes_common_inputs_and_six_unique_subjects(self):
        validate_formal_plan_v1(self.plan, self.root)
        self.assertEqual(
            [row["arm"] for row in self.plan["runs"]],
            ["A", "B", "B", "A", "A", "B"],
        )
        changed = copy.deepcopy(self.config)
        changed["investment_policy"]["api_money_limit"] = 50
        with self.assertRaisesRegex(FormalError, "API money limit"):
            freeze_formal_plan_v1(changed, self.root)
        changed["investment_policy"]["api_money_limit"] = {
            "amount": 50,
            "currency": "USD",
            "authorization_ref": "explicit-user-fixture",
        }
        freeze_formal_plan_v1(changed, self.root)
        changed = copy.deepcopy(self.config)
        changed["runs"][2]["order"] = "AB"
        with self.assertRaisesRegex(FormalError, "AB, BA, AB"):
            freeze_formal_plan_v1(changed, self.root)

    def test_artifact_refs_reject_wrong_hash_parent_and_drive_paths(self):
        changed = copy.deepcopy(self.config)
        changed["prompt"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(FormalError, "prompt hash mismatch"):
            freeze_formal_plan_v1(changed, self.root)
        changed = copy.deepcopy(self.config)
        changed["prompt"]["path"] = "../prompt.txt"
        with self.assertRaisesRegex(FormalError, "unsafe prompt"):
            freeze_formal_plan_v1(changed, self.root)

        changed = copy.deepcopy(self.config)
        changed["prompt"]["path"] = "C:/prompt.txt"
        with self.assertRaisesRegex(FormalError, "unsafe prompt"):
            freeze_formal_plan_v1(changed, self.root)

    def test_changed_rubric_and_evaluator_settings_are_rejected(self):
        from stage2_eval.formal import _verify_evaluator_contract

        (self.root / "rubric.json").write_text("{}", encoding="utf-8")
        changed = copy.deepcopy(self.config)
        changed["rubric"] = reference(self.root, self.root / "rubric.json")
        with self.assertRaisesRegex(FormalError, "rubric differs"):
            freeze_formal_plan_v1(changed, self.root)
        with self.assertRaisesRegex(FormalError, "differs from frozen"):
            _verify_evaluator_contract(self.plan, "judge", {}, {})

    def test_formal_cli_reports_missing_evidence_as_evaluator_failure(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            status = eval_cli.main(
                [
                    "validate-readiness",
                    "--evidence-root",
                    str(self.root),
                    "--manifest",
                    "absent.json",
                    "--receipt",
                    "0" * 64,
                    "--output",
                    str(self.root / "failure.json"),
                ]
            )
        report = json.loads((self.root / "failure.json").read_text(encoding="utf-8"))
        self.assertEqual(status, 2)
        self.assertEqual(report["error_type"], "evaluator_failure")
        self.assertFalse(report["formal_ready"])
        self.assertNotIn("score", report)

    def test_synthetic_six_run_path_is_permanently_non_public(self):
        manifest = self._formal_manifest()
        path, receipt = self._save_manifest(manifest)
        result = validate_formal_result_v1(
            path,
            self.root,
            receipt,
            self.plan,
            _synthetic_test_verifier=self._synthetic_verifier,
        )
        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(result["blockers"], ["synthetic-test-only"])
        self.assertFalse(result["formal_ready"])
        self.assertEqual(len(result["comparison"]["pairs"]), 3)

    def test_missing_calls_and_arm_contamination_fail_closed(self):
        manifest = self._formal_manifest()
        first = manifest["runs"][0]
        receipt_path = (
            self.root / first["extraction"]["external_replay_receipt"]["path"]
        )
        write_json(
            receipt_path,
            {
                "result_sha256": first["extraction"]["artifact"]["sha256"],
                "unit_receipts": {},
            },
        )
        first["extraction"]["external_replay_receipt"] = reference(
            self.root, receipt_path
        )
        path, receipt = self._save_manifest(manifest)
        with self.assertRaisesRegex(FormalError, "lacks native model calls"):
            validate_formal_result_v1(
                path,
                self.root,
                receipt,
                self.plan,
                _synthetic_test_verifier=self._synthetic_verifier,
            )
        manifest = self._formal_manifest()
        judge_path = self.root / manifest["runs"][0]["judge_input"]["path"]
        write_json(judge_path, {"arm_map": {"subject-1": "A"}})
        manifest["runs"][0]["judge_input"] = reference(self.root, judge_path)
        path, receipt = self._save_manifest(manifest, "arm-contamination.json")
        with self.assertRaisesRegex(FormalError, "arm map"):
            validate_formal_result_v1(
                path,
                self.root,
                receipt,
                self.plan,
                _synthetic_test_verifier=self._synthetic_verifier,
            )

    def test_missing_judge_audit_and_incomplete_pairs_fail_closed(self):
        manifest = self._formal_manifest()
        bundle_path = self.root / manifest["runs"][0]["judge_bundle"]["path"]
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        bundle["raw"]["r2"] = None
        write_json(bundle_path, bundle)
        manifest["runs"][0]["judge_bundle"] = reference(self.root, bundle_path)
        path, receipt = self._save_manifest(manifest)
        with self.assertRaisesRegex(FormalError, "R1/R2 archives"):
            validate_formal_result_v1(
                path,
                self.root,
                receipt,
                self.plan,
                _synthetic_test_verifier=self._synthetic_verifier,
            )
        manifest = self._formal_manifest(audit_first=True)
        manifest["runs"][0]["named_audit"] = None
        path, receipt = self._save_manifest(manifest, "missing-audit.json")
        with self.assertRaisesRegex(FormalError, "named audit"):
            validate_formal_result_v1(
                path,
                self.root,
                receipt,
                self.plan,
                _synthetic_test_verifier=self._synthetic_verifier,
            )
        manifest = self._formal_manifest()
        pairs_path = self.root / manifest["pairs"]["path"]
        pairs = json.loads(pairs_path.read_text(encoding="utf-8"))[:2]
        write_json(pairs_path, pairs)
        manifest["pairs"] = reference(self.root, pairs_path)
        path, receipt = self._save_manifest(manifest, "incomplete-pairs.json")
        with self.assertRaisesRegex(FormalError, "three complete pairs"):
            validate_formal_result_v1(
                path,
                self.root,
                receipt,
                self.plan,
                _synthetic_test_verifier=self._synthetic_verifier,
            )

    def test_public_result_is_inconclusive_without_authenticated_extraction_replay(
        self,
    ):
        manifest = self._formal_manifest()
        manifest["evidence_class"] = "authentic-native"
        path, receipt = self._save_manifest(manifest)

        # Public validation reaches the capture verifier first. Empty synthetic
        # capture directories cannot masquerade as authentic native evidence.
        with self.assertRaisesRegex(FormalError, "kind"):
            validate_formal_result_v1(path, self.root, receipt, self.plan)

    def test_readiness_replays_both_gates_but_calibration_stays_blocked(self):
        manifest = self._readiness_manifest()
        path, receipt = self._save_manifest(manifest, "readiness.json")
        calls = {"inspect": 0, "verify": 0, "controller": []}

        def inspect(*args, **kwargs):
            calls["inspect"] += 1
            return {"status": "passed", "runtime_gate": True}

        def verify(*args, **kwargs):
            calls["verify"] += 1
            return {"status": "passed", "runtime_gate": True}

        def controller(path, receipt):
            calls["controller"].append(Path(path).name)
            return {
                "pilot_executable": True,
                "authentic_native_execution": True,
                "synthetic_test_only": False,
            }

        result = validate_readiness_v1(
            path,
            self.root,
            receipt,
            _synthetic_test_verifiers={
                "inspect_preflight": inspect,
                "verify_preflight": verify,
                "verify_controller": controller,
                "verify_calibration_unit": lambda root, *a, **kw: {
                    "result": json.loads(
                        (root / "calibration-result.json").read_text(encoding="utf-8")
                    )
                },
            },
        )
        self.assertEqual(
            calls,
            {
                "inspect": 2,
                "verify": 2,
                "controller": ["pilot-US-aging", "pilot-flaky-tests"],
            },
        )
        self.assertFalse(result["formal_ready"])
        self.assertEqual(
            result["blockers"],
            [
                "synthetic-test-only",
            ],
        )
        with self.assertRaisesRegex(FormalError, "externally retained"):
            validate_readiness_v1(
                path,
                self.root,
                "0" * 64,
                _synthetic_test_verifiers={
                    "inspect_preflight": inspect,
                    "verify_preflight": verify,
                    "verify_controller": controller,
                    "verify_calibration_unit": lambda root, *a, **kw: {
                        "result": json.loads(
                            (root / "calibration-result.json").read_text(
                                encoding="utf-8"
                            )
                        )
                    },
                },
            )


if __name__ == "__main__":
    unittest.main()

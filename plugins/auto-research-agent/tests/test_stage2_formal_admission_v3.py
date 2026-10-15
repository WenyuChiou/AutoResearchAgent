import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "cli"))
sys.path.insert(0, str(HERE))

# ruff: noqa: E402 -- repository CLIs are imported without installation.
from stage2_eval.formal import FormalError
from stage2_eval.formal_admission_v3 import (
    READINESS_BLOCKERS,
    validate_formal_result_v2,
    validate_readiness_v2,
)
from stage2_eval.formal_v3 import freeze_formal_plan_v2
import test_stage2_evaluation_v3 as evaluation_v3_fixtures
import test_stage2_formal as formal_fixtures


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    return path


def reference(root, path):
    return {
        "path": Path(path).relative_to(root).as_posix(),
        "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
    }


def binding(root, path):
    artifact = reference(root, path)
    return {"artifact": artifact, "receipt": artifact["sha256"]}


class Stage2FormalAdmissionV3Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

        fixture = formal_fixtures.Stage2FormalTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.config = copy.deepcopy(fixture.config)
        self._copy_fixture_inputs(fixture.root)
        self.plan = freeze_formal_plan_v2(self.config, self.root)
        self.plan_path = write_json(self.root / "plan.json", self.plan)
        self.readiness = self._readiness_manifest()
        self.readiness_path = write_json(self.root / "readiness.json", self.readiness)

    def _copy_fixture_inputs(self, old_root):
        for key in ("brief", "prompt"):
            source = old_root / self.config[key]["path"]
            target = self.root / self.config[key]["path"]
            target.write_bytes(source.read_bytes())
            self.config[key] = reference(self.root, target)
        rubric = self.root / "rubric-v3.json"
        from stage2_eval.evaluation_v3 import RUBRIC_PATH_V3

        rubric.write_bytes(RUBRIC_PATH_V3.read_bytes())
        self.config["rubric"] = reference(self.root, rubric)
        source = self.root / "common-source.txt"
        source.write_text("Neutral common evidence.", encoding="utf-8")
        common = write_json(
            self.root / "common.json",
            {
                "kind": "Stage2FormalCommonEvidence",
                "schema_version": "1.0.0",
                "brief": self.config["brief"],
                "sources": [
                    {
                        "source_id": "s1",
                        "work_id": "w1",
                        "version_id": "v1",
                        "artifact": reference(self.root, source),
                        "evidence_level": "full-text",
                    }
                ],
                "claims": [],
                "unknowns": ["Completeness is unknown."],
            },
        )
        self.config["stage1_source_manifest"] = reference(self.root, common)

    def _readiness_manifest(self):
        preflights = []
        for arm in ("A", "B"):
            path = write_json(self.root / f"preflight-{arm}.json", {"status": "saved"})
            preflights.append({"arm": arm, "evidence": binding(self.root, path)})
        pilots = []
        for topic in ("US-aging", "flaky-tests"):
            path = write_json(self.root / f"pilot-{topic}.json", {"status": "saved"})
            pilots.append({"topic_id": topic, "evidence": binding(self.root, path)})
        calibration = write_json(
            self.root / "calibration.json", {"status": "saved", "criteria": 9}
        )
        return {
            "kind": "Stage2FormalReadinessManifest",
            "schema_version": "2.0.0",
            "formal_plan": binding(self.root, self.plan_path),
            "source_context": {
                "artifact": copy.deepcopy(self.plan["stage1_source_manifest"]),
                "receipt": self.plan["stage1_source_manifest"]["sha256"],
            },
            "preflights": preflights,
            "pilots": pilots,
            "calibration": binding(self.root, calibration),
        }

    def _validate_readiness_manifest(self, manifest, name="readiness.json"):
        path = write_json(self.root / name, manifest)
        return validate_readiness_v2(
            path.relative_to(self.root).as_posix(),
            self.root,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )

    def _validate_readiness(self):
        return self._validate_readiness_manifest(self.readiness)

    def _execution_manifest(self):
        manifest = copy.deepcopy(self.readiness)
        manifest["schema_version"] = "2.1.0"
        manifest["executions"] = []
        actual = {}
        for arm in ("A", "B"):
            root = self.root / f"telemetry-{arm}"
            root.mkdir(exist_ok=True)
            prompt = self.root / f"prompt-{arm}.txt"
            prompt.write_bytes(b"Bounded neutral task.\n")
            contract = self.plan["runtime_contracts"][arm]
            request = {
                "codex": "fixture-native",
                "codex_home": str(self.root / f"home-{arm}"),
                "workspace": str(self.root / f"workspace-{arm}"),
                "model": self.plan["model"],
                "reasoning": self.plan["reasoning"],
                "input_bindings": {},
                "config_bindings": {},
                "policy_bindings": contract["policy_bindings"],
                "capture_dir": str(self.root / f"capture-{arm}"),
                "trace_root": str(root),
                "timeout_seconds": 600,
                "prompt_sha256": reference(self.root, prompt)["sha256"],
            }
            request_path = write_json(self.root / f"request-{arm}.json", request)
            inventory = {
                "capture": {
                    "stable_request_binding": {
                        "codex_runtime_sha256": self.plan["runtime_sha256"],
                        "model": self.plan["model"],
                        "reasoning": self.plan["reasoning"],
                        "policy_bindings": contract["policy_bindings"],
                        "config_bindings": {
                            key: {"sha256": value}
                            for key, value in contract["config_bindings"].items()
                        },
                    }
                },
                "coverage_complete": True,
                "call_accounting_complete": True,
                "token_usage_complete": True,
                "counts": {"inferences": 2, "threads": 1},
                "inferences": [
                    {
                        "model": self.plan["model"],
                        "reasoning": {"effort": self.plan["reasoning"]},
                    }
                ],
                "token_usage_totals": {"total_tokens": 100},
                "cost": {"amount": None, "state": "unknown"},
            }
            actual[str(root)] = copy.deepcopy(inventory)
            inventory_path = write_json(self.root / f"inventory-{arm}.json", inventory)
            manifest["executions"].append(
                {
                    "arm": arm,
                    "telemetry_root": root.relative_to(self.root).as_posix(),
                    "capture_request": binding(self.root, request_path),
                    "prompt": reference(self.root, prompt),
                    "producer_receipt": ("a" if arm == "A" else "b") * 64,
                    "inventory": binding(self.root, inventory_path),
                }
            )
        return manifest, actual

    def _inventory_replay(self, actual):
        # Controlled test seam only: no native dispatch and no readiness promotion.
        return mock.patch(
            "stage2_live.execution_inventory.inspect_execution_inventory",
            side_effect=lambda root, receipt, *, capture_request: copy.deepcopy(
                actual[str(root)]
            ),
        )

    def test_opt_in_execution_replay_removes_only_stale_collector_blocker(self):
        manifest, actual = self._execution_manifest()
        with self._inventory_replay(actual) as replay:
            result = self._validate_readiness_manifest(manifest)
        self.assertEqual(replay.call_count, 2)
        self.assertEqual(
            replay.call_args.kwargs["capture_request"]["prompt"],
            b"Bounded neutral task.\n",
        )
        self.assertEqual(
            result["blockers"],
            [
                value
                for value in READINESS_BLOCKERS
                if value != "per-execution-inventory-collector-unavailable"
            ],
        )
        self.assertFalse(result["formal_ready"])
        self.assertFalse(result["external_claim_ready"])
        self.assertEqual(result["execution_inventories"][0]["cost"]["amount"], None)

    def test_incomplete_execution_preserves_unknown_usage_and_blocks(self):
        manifest, actual = self._execution_manifest()
        root = str(self.root / "telemetry-A")
        actual[root].update(
            coverage_complete=False, token_usage_complete=False, token_usage_totals=None
        )
        row = manifest["executions"][0]
        path = self.root / row["inventory"]["artifact"]["path"]
        write_json(path, actual[root])
        row["inventory"] = binding(self.root, path)
        with self._inventory_replay(actual):
            result = self._validate_readiness_manifest(manifest)
        self.assertIn("execution-inventory-incomplete:A", result["blockers"])
        self.assertIsNone(result["execution_inventories"][0]["token_usage_totals"])
        self.assertFalse(result["formal_ready"])

    def test_rehashed_inventory_labels_cannot_replace_authentic_replay(self):
        manifest, actual = self._execution_manifest()
        row = manifest["executions"][0]
        path = self.root / row["inventory"]["artifact"]["path"]
        forged = copy.deepcopy(actual[str(self.root / "telemetry-A")])
        forged["counts"]["inferences"] = 0
        write_json(path, forged)
        row["inventory"] = binding(self.root, path)
        with (
            self._inventory_replay(actual),
            self.assertRaisesRegex(FormalError, "authentic replay"),
        ):
            self._validate_readiness_manifest(manifest)

    def test_execution_prompt_and_trace_must_match_bound_request(self):
        for key, replacement, error in [
            ("prompt_sha256", "0" * 64, "prompt differs"),
            ("trace_root", str(self.root), "telemetry differs"),
        ]:
            with self.subTest(key=key):
                manifest, actual = self._execution_manifest()
                row = manifest["executions"][0]
                path = self.root / row["capture_request"]["artifact"]["path"]
                request = json.loads(path.read_bytes())
                request[key] = replacement
                write_json(path, request)
                row["capture_request"] = binding(self.root, path)
                with (
                    self._inventory_replay(actual) as replay,
                    self.assertRaisesRegex(FormalError, error),
                ):
                    self._validate_readiness_manifest(manifest)
                replay.assert_not_called()

    def test_execution_duplicates_and_outside_paths_are_rejected(self):
        for key, replacement in [
            ("producer_receipt", "a" * 64),
            ("telemetry_root", "telemetry-A"),
            ("telemetry_root", "../outside"),
        ]:
            with self.subTest(key=key, replacement=replacement):
                manifest, actual = self._execution_manifest()
                manifest["executions"][1][key] = replacement
                with self._inventory_replay(actual), self.assertRaises(FormalError):
                    self._validate_readiness_manifest(manifest)

    def test_execution_effective_runtime_policy_and_extensions_match_plan(self):
        for field, changed in [
            ("model", "other-model"),
            ("codex_runtime_sha256", "f" * 64),
            ("policy_bindings", {"policy": "changed"}),
            ("config_bindings", {"extra": {"sha256": "f" * 64}}),
        ]:
            with self.subTest(field=field):
                manifest, actual = self._execution_manifest()
                root = str(self.root / "telemetry-A")
                actual[root]["capture"]["stable_request_binding"][field] = changed
                row = manifest["executions"][0]
                path = self.root / row["inventory"]["artifact"]["path"]
                write_json(path, actual[root])
                row["inventory"] = binding(self.root, path)
                with self._inventory_replay(actual), self.assertRaises(FormalError):
                    self._validate_readiness_manifest(manifest)

    def test_execution_replay_failure_and_synthetic_arguments_reject(self):
        manifest, actual = self._execution_manifest()
        with (
            mock.patch(
                "stage2_live.execution_inventory.inspect_execution_inventory",
                side_effect=ValueError("producer receipt invalid"),
            ),
            self.assertRaisesRegex(FormalError, "replay rejected"),
        ):
            self._validate_readiness_manifest(manifest)
        row = manifest["executions"][0]
        path = self.root / row["capture_request"]["artifact"]["path"]
        request = json.loads(path.read_bytes())
        request["process_runner"] = "injected"
        write_json(path, request)
        row["capture_request"] = binding(self.root, path)
        with self._inventory_replay(actual) as replay, self.assertRaises(FormalError):
            self._validate_readiness_manifest(manifest)
        replay.assert_not_called()

    def test_child_model_or_effort_drift_cannot_hide_in_requested_runtime(self):
        for field, changed in [
            ("model", "other-model"),
            ("reasoning", {"effort": "low"}),
            ("reasoning", None),
        ]:
            with self.subTest(field=field):
                manifest, actual = self._execution_manifest()
                root = str(self.root / "telemetry-A")
                child = copy.deepcopy(actual[root]["inferences"][0])
                child[field] = changed
                actual[root]["inferences"].append(child)
                row = manifest["executions"][0]
                path = self.root / row["inventory"]["artifact"]["path"]
                write_json(path, actual[root])
                row["inventory"] = binding(self.root, path)
                with (
                    self._inventory_replay(actual),
                    self.assertRaisesRegex(FormalError, "effective model"),
                ):
                    self._validate_readiness_manifest(manifest)

    def test_legacy_version_cannot_opt_in_without_new_manifest_version(self):
        manifest, actual = self._execution_manifest()
        manifest["schema_version"] = "2.0.0"
        with self._inventory_replay(actual) as replay, self.assertRaises(FormalError):
            self._validate_readiness_manifest(manifest)
        replay.assert_not_called()

    def _validate_result(self, manifest, name="result.json"):
        path = write_json(self.root / name, manifest)
        return validate_formal_result_v2(
            path.relative_to(self.root).as_posix(),
            self.root,
            hashlib.sha256(path.read_bytes()).hexdigest(),
            self.plan,
        )

    def _result_manifest(self):
        fixture = evaluation_v3_fixtures.Stage2EvaluationV3Tests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        rows = []
        bundles = {}
        for planned in self.plan["runs"]:
            bundle_value = fixture.bundle(planned["subject_id"])
            path = write_json(
                self.root / "bundles" / f"{planned['subject_id']}.json", bundle_value
            )
            rows.append(
                {
                    "subject_id": planned["subject_id"],
                    "judge_bundle": binding(self.root, path),
                }
            )
            bundles[planned["subject_id"]] = bundle_value
        pairs = []
        for index, order in enumerate(("AB", "BA", "AB")):
            planned = self.plan["runs"][index * 2 : index * 2 + 2]
            by_arm = {row["arm"]: bundles[row["subject_id"]] for row in planned}
            pairs.append(
                {
                    "pair_id": f"pair-{index + 1}",
                    "order": order,
                    "A": by_arm["A"],
                    "B": by_arm["B"],
                    "A_content_view_sha256": by_arm["A"]["content_view_sha256"],
                    "B_content_view_sha256": by_arm["B"]["content_view_sha256"],
                }
            )
        pair_path = write_json(self.root / "pairs.json", pairs)
        return {
            "kind": "Stage2FormalResultManifest",
            "schema_version": "2.0.0",
            "plan_sha256": self.plan["plan_sha256"],
            "readiness": binding(self.root, self.readiness_path),
            "runs": rows,
            "pairs": binding(self.root, pair_path),
        }

    def test_readiness_binds_inputs_but_stays_closed(self):
        result = self._validate_readiness()
        self.assertEqual(result["blockers"], list(READINESS_BLOCKERS))
        self.assertEqual(result["validation_scope"], "artifact-binding-only")
        self.assertFalse(result["formal_ready"])
        self.assertFalse(result["external_claim_ready"])

    def test_readiness_rejects_contamination_missing_receipt_and_traversal(self):
        calibration = self.root / self.readiness["calibration"]["artifact"]["path"]
        write_json(calibration, {"condition_map": {"subject": "B"}})
        self.readiness["calibration"] = binding(self.root, calibration)
        self.readiness_path = write_json(self.readiness_path, self.readiness)
        with self.assertRaisesRegex(FormalError, "arm assignment"):
            self._validate_readiness()

        del self.readiness["calibration"]["receipt"]
        self.readiness_path = write_json(self.readiness_path, self.readiness)
        with self.assertRaises(FormalError):
            self._validate_readiness()

        self.readiness["calibration"] = {
            "artifact": {"path": "../outside.json", "sha256": "0" * 64},
            "receipt": "0" * 64,
        }
        self.readiness_path = write_json(self.readiness_path, self.readiness)
        with self.assertRaisesRegex(FormalError, "unsafe"):
            self._validate_readiness()

    def test_readiness_rejects_version_count_and_hash_changes(self):
        changed = copy.deepcopy(self.readiness)
        changed["schema_version"] = "1.1.0"
        with self.assertRaisesRegex(FormalError, "wrong.*version"):
            self._validate_readiness_manifest(changed, "old-readiness.json")

        changed = copy.deepcopy(self.readiness)
        changed["preflights"].pop()
        with self.assertRaisesRegex(FormalError, "A/B preflights"):
            self._validate_readiness_manifest(changed, "short-readiness.json")

        changed = copy.deepcopy(self.readiness)
        changed["formal_plan"]["artifact"]["sha256"] = "0" * 64
        changed["formal_plan"]["receipt"] = "0" * 64
        with self.assertRaisesRegex(FormalError, "hash mismatch"):
            self._validate_readiness_manifest(changed, "changed-readiness.json")

    def test_result_replays_nine_criteria_and_fixed_denominators_but_stays_closed(self):
        manifest = self._result_manifest()
        result = self._validate_result(manifest)
        self.assertEqual(result["comparison"]["pairs"][0]["A"]["P4"]["max"], 6)
        self.assertFalse(result["formal_ready"])
        self.assertFalse(result["external_claim_ready"])
        self.assertFalse(result["improvement_established"])

    def test_result_rejects_tamper_old_bundle_and_changed_pair_order(self):
        manifest = self._result_manifest()
        bundle_binding = manifest["runs"][0]["judge_bundle"]
        bundle_path = self.root / bundle_binding["artifact"]["path"]
        value = json.loads(bundle_path.read_text(encoding="utf-8"))
        value["criteria"][0]["score"] = 2
        write_json(bundle_path, value)
        manifest["runs"][0]["judge_bundle"] = binding(self.root, bundle_path)
        with self.assertRaisesRegex(FormalError, "replayed raw judgments"):
            self._validate_result(manifest)

        manifest = self._result_manifest()
        bundle_binding = manifest["runs"][0]["judge_bundle"]
        bundle_path = self.root / bundle_binding["artifact"]["path"]
        value = json.loads(bundle_path.read_text(encoding="utf-8"))
        value["criteria"] = value["criteria"][:7]
        value["rubric_id"] = "stage2-general-v2"
        write_json(bundle_path, value)
        manifest["runs"][0]["judge_bundle"] = binding(self.root, bundle_path)
        with self.assertRaisesRegex(FormalError, "wrong bundle rubric"):
            self._validate_result(manifest, "old-result.json")

        manifest = self._result_manifest()
        pair_path = self.root / manifest["pairs"]["artifact"]["path"]
        pairs = json.loads(pair_path.read_text(encoding="utf-8"))
        pairs[1]["order"] = "AB"
        write_json(pair_path, pairs)
        manifest["pairs"] = binding(self.root, pair_path)
        with self.assertRaisesRegex(FormalError, "differ from six bound runs"):
            self._validate_result(manifest, "order-result.json")

    def test_cli_reports_blocked(self):
        from stage2_eval.__main__ import main

        output = self.root / "cli-readiness.json"
        receipt = hashlib.sha256(self.readiness_path.read_bytes()).hexdigest()
        status = main(
            [
                "validate-readiness-v3",
                "--manifest",
                self.readiness_path.relative_to(self.root).as_posix(),
                "--evidence-root",
                str(self.root),
                "--receipt",
                receipt,
                "--output",
                str(output),
            ]
        )
        self.assertEqual(status, 2)
        result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["formal_ready"])

    def test_cli_malformed_rows_produce_blocked_artifacts(self):
        from stage2_eval.__main__ import main

        for field in ("preflights", "pilots", "runs"):
            for index, malformed in enumerate((None, [], "invalid")):
                with self.subTest(field=field, malformed=malformed):
                    value = (
                        self._result_manifest()
                        if field == "runs"
                        else copy.deepcopy(self.readiness)
                    )
                    value[field][0] = malformed
                    path = write_json(
                        self.root / f"malformed-{field}-{index}.json", value
                    )
                    output = self.root / f"blocked-{field}-{index}.json"
                    command = (
                        "validate-formal-result-v3"
                        if field == "runs"
                        else "validate-readiness-v3"
                    )
                    args = [
                        command,
                        "--manifest",
                        path.relative_to(self.root).as_posix(),
                        "--evidence-root",
                        str(self.root),
                        "--receipt",
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                        "--output",
                        str(output),
                    ]
                    if field == "runs":
                        args += ["--plan", str(self.plan_path)]
                    self.assertEqual(main(args), 2)
                    result = json.loads(output.read_text(encoding="utf-8"))
                    self.assertEqual(result["error_type"], "evaluator_failure")
                    self.assertEqual(result["status"], "blocked")
                    self.assertFalse(result["formal_ready"])

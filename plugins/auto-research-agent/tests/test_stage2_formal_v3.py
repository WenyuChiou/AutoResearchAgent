"""Versioned formal plans must not relabel historical rubric results."""

import copy
import unittest

import test_stage2_formal as formal_fixtures
from stage2_eval.evaluation_v3 import RUBRIC_PATH_V3
from stage2_eval.formal import FormalError, freeze_formal_plan_v1
from stage2_eval.formal_v3 import freeze_formal_plan_v2, validate_formal_plan_v2


class Stage2FormalV3Tests(unittest.TestCase):
    def test_duplicate_or_empty_claim_id_rejected_after_rehash(self):
        import hashlib
        import json

        self.use_v3()
        path = self.root / self.config["stage1_source_manifest"]["path"]
        original = json.loads(path.read_text(encoding="utf-8"))
        claim = {
            "claim_id": "c1",
            "source_id": "common1",
            "work_id": "work1",
            "version_id": "v1",
            "text": "Synthetic unsupported observation",
            "verification": "unknown",
            "locator": "",
        }
        for claims in ([claim, copy.deepcopy(claim)], [{**claim, "claim_id": ""}]):
            value = {**original, "claims": claims}
            path.write_text(json.dumps(value), encoding="utf-8")
            self.config["stage1_source_manifest"]["sha256"] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            with self.assertRaisesRegex(FormalError, "claim"):
                freeze_formal_plan_v2(self.config, self.root)

    def setUp(self):
        self.fixture = formal_fixtures.Stage2FormalTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.config = copy.deepcopy(self.fixture.config)

    def use_v3(self):
        import hashlib
        import json

        target = self.root / "rubric-v3.json"
        target.write_bytes(RUBRIC_PATH_V3.read_bytes())
        self.config["rubric"] = {
            "path": target.name,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }
        source = self.root / "common-source.txt"
        source.write_text(
            "Synthetic source facts; no prior B candidate or assessment.",
            encoding="utf-8",
        )
        manifest = self.root / "common-evidence.json"
        manifest.write_text(
            json.dumps(
                {
                    "kind": "Stage2FormalCommonEvidence",
                    "schema_version": "1.0.0",
                    "brief": self.config["brief"],
                    "sources": [
                        {
                            "source_id": "common1",
                            "work_id": "work1",
                            "version_id": "v1",
                            "artifact": {
                                "path": source.name,
                                "sha256": hashlib.sha256(
                                    source.read_bytes()
                                ).hexdigest(),
                            },
                            "evidence_level": "full-text",
                        }
                    ],
                    "claims": [],
                    "unknowns": ["Scientific completeness has not been established."],
                }
            ),
            encoding="utf-8",
        )
        self.config["stage1_source_manifest"] = {
            "path": manifest.name,
            "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        }

    def test_v3_common_input_rejects_prior_selection_even_with_new_hash(self):
        import hashlib
        import json

        self.use_v3()
        manifest = self.root / self.config["stage1_source_manifest"]["path"]
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["candidates"] = [{"question": "previous B proposal"}]
        manifest.write_text(json.dumps(value), encoding="utf-8")
        self.config["stage1_source_manifest"]["sha256"] = hashlib.sha256(
            manifest.read_bytes()
        ).hexdigest()
        with self.assertRaisesRegex(FormalError, "formal common evidence"):
            freeze_formal_plan_v2(self.config, self.root)

    def test_v3_plan_rejects_v2_rubric(self):
        with self.assertRaisesRegex(FormalError, "Stage2 v3"):
            freeze_formal_plan_v2(self.config, self.root)

    def test_v3_plan_bound_nine_criteria_and_fixed_denominators(self):
        self.use_v3()
        plan = freeze_formal_plan_v2(self.config, self.root)
        self.assertEqual(plan["schema_version"], "2.0.0")
        self.assertEqual(plan["rubric_id"], "stage2-general-v3")
        self.assertEqual(plan["dimension_denominators"], {"P4": 6, "P5": 6, "P6": 6})
        self.assertEqual(len(plan["criterion_ids"]), 9)
        validate_formal_plan_v2(plan, self.root)

    def test_v3_plan_rehashed_denominator_change_rejected(self):
        from stage2_common import canonical_hash

        self.use_v3()
        plan = freeze_formal_plan_v2(self.config, self.root)
        plan["dimension_denominators"]["P4"] = 2
        del plan["plan_sha256"]
        plan["plan_sha256"] = canonical_hash(plan)
        with self.assertRaises(FormalError):
            validate_formal_plan_v2(plan, self.root)

    def test_v3_plan_cannot_be_admitted_as_v1(self):
        self.use_v3()
        with self.assertRaisesRegex(FormalError, "Stage2 v2"):
            freeze_formal_plan_v1(self.config, self.root)

    def test_v3_plan_native_capabilities_equal(self):
        self.use_v3()
        self.config["runtime_contracts"]["A"]["policy_bindings"]["sandbox"] = "disabled"
        with self.assertRaisesRegex(FormalError, "native policies differ"):
            freeze_formal_plan_v2(self.config, self.root)

    def test_v3_cli_freeze_does_not_claim_readiness(self):
        import json
        from stage2_eval import __main__ as cli

        self.use_v3()
        config = self.root / "config.json"
        config.write_text(json.dumps(self.config), encoding="utf-8")
        output = self.root / "frozen.json"
        result = cli.main(
            [
                "freeze-formal-plan-v3",
                "--config",
                str(config),
                "--evidence-root",
                str(self.root),
                "--output",
                str(output),
            ]
        )
        self.assertEqual(result, 0)
        plan = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(plan["status"], "frozen")
        self.assertNotIn("formal_ready", plan)
        self.assertNotIn("improvement_established", plan)

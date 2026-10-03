"""Calibration transport must freeze policy before attempting model dispatch."""

import json
import copy
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_live.calibration import (
    run_calibration_unit,
    expand_source_ids,
    prepare_calibration,
    validate_calibration_unit,
)  # noqa: E402
from stage2_common import canonical_hash  # noqa: E402
import test_stage2_diagnostics as fixtures  # noqa: E402


class CalibrationTests(unittest.TestCase):
    def test_malformed_unit_fails_before_dispatch_and_cli_returns_failed_json(self):
        from unittest.mock import patch

        from stage2_eval.diagnostics import DiagnosticError
        from stage2_live.__main__ import main

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = root / "policy.json"
            policy.write_text("{}", encoding="utf-8")
            for unit in (None, []):
                with self.subTest(unit=unit):
                    with patch(
                        "stage2_live.calibration.codex_runtime_sha",
                        side_effect=AssertionError(
                            "must not dispatch or inspect runtime"
                        ),
                    ):
                        with self.assertRaisesRegex(
                            DiagnosticError, "must be an object"
                        ):
                            run_calibration_unit(
                                unit,
                                codex="missing-native-executable",
                                evaluator_home=root,
                                model="gpt-test",
                                reasoning="high",
                                execution_policy={},
                                output_dir=root / "output",
                            )
                        source = root / "unit.json"
                        source.write_text(json.dumps(unit), encoding="utf-8")
                        stderr = io.StringIO()
                        with contextlib.redirect_stderr(stderr):
                            result = main(
                                [
                                    "calibrate",
                                    "--unit",
                                    str(source),
                                    "--codex",
                                    "missing-native-executable",
                                    "--evaluator-home",
                                    str(root),
                                    "--model",
                                    "gpt-test",
                                    "--reasoning",
                                    "high",
                                    "--policy",
                                    str(policy),
                                    "--output",
                                    str(root / "output"),
                                    "--replay-receipt-output",
                                    str(root / "receipt.json"),
                                ]
                            )
                        self.assertEqual(result, 2)
                        response = json.loads(stderr.getvalue())
                        self.assertEqual(response["status"], "failed")
                        self.assertIn("must be an object", response["error"])
                        self.assertFalse((root / "output").exists())
                        self.assertFalse((root / "receipt.json").exists())

    def test_prepare_cli_can_freeze_v21_without_changing_legacy_default(self):
        from stage2_eval.__main__ import main

        root = Path(__file__).resolve().parents[1] / "evals/stage2/diagnostics"
        with tempfile.TemporaryDirectory() as temporary:
            for version in ("2.0.0", "2.1.0"):
                target = Path(temporary) / (version + ".json")
                args = [
                    "prepare-diagnostics",
                    "--cases",
                    str(root / "cases.v2.json"),
                    "--recipes",
                    str(root / "variants.v2.json"),
                    "--output",
                    str(target),
                ]
                if version == "2.1.0":
                    args += ["--output-version", version]
                self.assertEqual(main(args), 0)
                for unit in json.loads(target.read_text(encoding="utf-8")):
                    self.assertEqual(
                        unit.get("diagnostic_output_version", "2.0.0"), version
                    )
                    validate_calibration_unit(unit, output_version=version)

    def test_v21_units_bind_schema_prompt_and_source_id_expansion(self):
        fixture = fixtures.Stage2DiagnosticTests()
        fixture.setUp()
        recipes = {"schema_version": "2.0.0", "recipes": []}
        for name in ("base", "order", "verbosity", "prestige", "preference"):
            payload = {
                "recipe_id": name,
                "presentation_note": "Presentation only",
                "case_order": [1, 2],
            }
            recipes["recipes"].append(
                dict(payload, recipe_sha256=canonical_hash(payload))
            )
        unit = prepare_calibration(fixture.cases, recipes, output_version="2.1.0")[0]
        with self.assertRaisesRegex(ValueError, "version-aware runtime"):
            validate_calibration_unit(unit)
        validate_calibration_unit(unit, output_version="2.1.0")

        raw = fixtures.output_v21(fixture.rows)
        for row in raw["results"]:
            for group in [
                row["evidence_refs"],
                *(check["evidence_refs"] for check in row["checks"].values()),
            ]:
                for ref in group:
                    del ref["exact_quote"]
        raw["results"][0]["checks"]["materials"].update(
            score=0,
            judgment_basis="demonstrated-incompatibility",
            negative_evidence_ids=["fact-claim"],
        )
        expanded = expand_source_ids(raw, fixture.cases, output_version="2.1.0")
        self.assertEqual(
            expanded["results"][0]["checks"]["materials"]["negative_evidence_ids"],
            ["fact-claim"],
        )
        self.assertEqual(
            expanded["results"][0]["checks"]["materials"]["evidence_refs"][0][
                "exact_quote"
            ],
            fixture.cases[0]["source_facts"][0]["text"],
        )
        seen = []

        def adapter(prompt, schema, directory, label, **options):
            contract = json.loads(Path(schema).read_text(encoding="utf-8"))
            seen.append(contract["properties"]["schema_version"]["enum"])
            options["semantic_validator"](raw)
            return raw, {"test_adapter": True}

        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / "codex.exe"
            binary.write_bytes(b"synthetic native executable")
            run_calibration_unit(
                unit,
                codex=str(binary),
                evaluator_home=temp,
                model="gpt-test",
                reasoning="high",
                execution_policy={},
                output_dir=Path(temp) / "result",
                call_adapter=adapter,
            )
        self.assertEqual(seen, [["2.1.0"]])

    def test_source_ids_restore_exact_versioned_facts_without_accepting_forged_quotes(
        self,
    ):
        fixture = fixtures.Stage2DiagnosticTests()
        fixture.setUp()
        raw = fixtures.output(fixture.rows)
        for row in raw["results"]:
            for group in [
                row["evidence_refs"],
                *(check["evidence_refs"] for check in row["checks"].values()),
            ]:
                for ref in group:
                    del ref["exact_quote"]
        expanded = expand_source_ids(raw, fixture.cases)
        self.assertEqual(
            expanded["results"][0]["evidence_refs"][0]["exact_quote"],
            fixture.cases[0]["source_facts"][0]["text"],
        )
        bad = copy.deepcopy(raw)
        bad["results"][0]["evidence_refs"][0]["evidence_id"] = fixture.cases[1][
            "source_facts"
        ][0]["evidence_id"]
        with self.assertRaisesRegex(ValueError, "unknown case or source"):
            expand_source_ids(bad, fixture.cases)
        raw["results"][0]["evidence_refs"][0]["exact_quote"] = "invented"
        with self.assertRaisesRegex(ValueError, "must not supply a quote"):
            expand_source_ids(raw, fixture.cases)

    def test_policy_is_bound_before_dispatch_and_synthetic_cannot_promote(self):
        fixture = fixtures.Stage2DiagnosticTests()
        fixture.setUp()
        recipes = {"schema_version": "2.0.0", "recipes": []}
        for name in ("base", "order", "verbosity", "prestige", "preference"):
            payload = {
                "recipe_id": name,
                "presentation_note": "Presentation only",
                "case_order": [1, 2],
            }
            recipes["recipes"].append(
                dict(payload, recipe_sha256=canonical_hash(payload))
            )
        unit = prepare_calibration(fixture.cases, recipes, source_ids=False)[0]
        calls = []

        def adapter(prompt, schema, directory, label, **options):
            calls.append(options)
            value = fixtures.output(fixture.rows)
            options["semantic_validator"](value)
            return value, {"test_adapter": True}

        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / "codex.exe"
            binary.write_bytes(b"synthetic native executable")
            result = run_calibration_unit(
                unit,
                codex=str(binary),
                evaluator_home=temp,
                model="gpt-test",
                reasoning="high",
                execution_policy={},
                output_dir=Path(temp) / "result",
                call_adapter=adapter,
            )
            self.assertEqual(len(calls), 1)
            self.assertEqual(
                len(calls[0]["execution_policy"]["evaluator_bundle_sha256"]), 64
            )
            self.assertEqual(result["case_outputs"], 2)
            self.assertEqual(result["evidence_class"], "synthetic-test-only")
            self.assertFalse(result["formal_ready"])
            with self.assertRaisesRegex(ValueError, "externally receipted resume"):
                run_calibration_unit(
                    unit,
                    codex=str(binary),
                    evaluator_home=temp,
                    model="gpt-test",
                    reasoning="high",
                    execution_policy={},
                    output_dir=Path(temp) / "result",
                    call_adapter=adapter,
                )
            self.assertEqual(len(calls), 1)

    def test_variant_tamper_and_launcher_rejected_before_dispatch(self):
        root = Path(__file__).resolve().parents[1] / "evals/stage2/diagnostics"
        cases = json.loads((root / "cases.v2.json").read_text(encoding="utf-8"))
        recipes = json.loads((root / "variants.v2.json").read_text(encoding="utf-8"))
        units = prepare_calibration(cases, recipes)
        for unit in units:
            validate_calibration_unit(unit)
            legacy = copy.deepcopy(unit)
            recipe = legacy.pop("recipe")
            validate_calibration_unit(legacy, legacy_recipe=recipe)
            with self.assertRaisesRegex(ValueError, "recipe payload"):
                validate_calibration_unit(legacy)
        for key, value in (
            ("variant", "preference"),
            ("case_count", 999),
            ("recipe_sha256", "0" * 64),
            ("evidence_transport", "unknown"),
        ):
            broken = dict(units[0], **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_calibration_unit(broken)
        with tempfile.TemporaryDirectory() as temp:
            shim = Path(temp) / "codex.cmd"
            shim.write_text("vendor.exe", encoding="utf-8")
            for resume in (False, True):
                with (
                    self.subTest(resume=resume),
                    self.assertRaisesRegex(ValueError, "indirect script"),
                ):
                    run_calibration_unit(
                        units[0],
                        codex=str(shim),
                        evaluator_home=temp,
                        model="gpt-test",
                        reasoning="high",
                        execution_policy={},
                        output_dir=Path(temp) / "out",
                        resume=resume,
                        call_adapter=lambda *a, **kw: self.fail(
                            "must reject before dispatch"
                        ),
                    )
            self.assertFalse((Path(temp) / "out").exists())


if __name__ == "__main__":
    unittest.main()

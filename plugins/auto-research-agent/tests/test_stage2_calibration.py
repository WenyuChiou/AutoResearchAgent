"""Calibration transport must freeze policy before attempting model dispatch."""

import json
import copy
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

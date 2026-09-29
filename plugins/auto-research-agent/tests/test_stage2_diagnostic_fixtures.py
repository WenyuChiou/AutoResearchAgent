import hashlib
import json
import unittest
from pathlib import Path
import sys

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))
from stage2_eval.diagnostics import _validate_cases  # noqa: E402
from stage2_live.calibration import prepare_calibration  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "evals/stage2/diagnostics"


class FixtureTests(unittest.TestCase):
    def test_cases(self):
        c = json.loads((ROOT / "cases.v2.json").read_text(encoding="utf-8"))
        _validate_cases(c)
        self.assertEqual(len(c), 13)
        for i, x in enumerate(c, 1):
            s = f"S{i:02d}"
            self.assertEqual(x["case_id"], s + "-case")
            self.assertEqual(x["research_candidate"]["id"], s + "-candidate")
            self.assertEqual(x["claim_under_review"]["id"], s + "-claim")
            for j, f in enumerate(x["source_facts"], 1):
                self.assertEqual(f["evidence_id"], f"{s}:E0{j}")
                self.assertEqual(
                    f["sha256"], hashlib.sha256(f["text"].encode()).hexdigest()
                )
        d = json.dumps(c)
        for k in ("accepted", "required", "legacy", "scenario", "target"):
            self.assertNotIn('"' + k + '"', d)

    def test_freeze_preserves_all_case_bytes_and_detects_tamper(self):
        cases = json.loads((ROOT / "cases.v2.json").read_text(encoding="utf-8"))
        recipes = json.loads((ROOT / "variants.v2.json").read_text(encoding="utf-8"))
        units = prepare_calibration(cases, recipes)
        self.assertEqual(sum(unit["case_count"] for unit in units), 65)
        original = {c["case_id"]: c for c in cases}
        for unit in units:
            self.assertEqual({c["case_id"]: c for c in unit["cases"]}, original)
        recipes["recipes"][0]["case_order"].reverse()
        with self.assertRaisesRegex(ValueError, "recipe hash"):
            prepare_calibration(cases, recipes)

    def test_variants(self):
        rs = json.loads((ROOT / "variants.v2.json").read_text())["recipes"]
        self.assertEqual(
            [r["recipe_id"] for r in rs],
            ["base", "order", "verbosity", "prestige", "preference"],
        )
        self.assertEqual(rs[1]["case_order"], list(range(13, 0, -1)))
        self.assertEqual(len({r["recipe_sha256"] for r in rs}), 5)


if __name__ == "__main__":
    unittest.main()

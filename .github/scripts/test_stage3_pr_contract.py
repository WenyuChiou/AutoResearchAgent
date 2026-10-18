"""Generic planning extensions are consumed by actual PR validation paths."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_research_pr as validator  # noqa: E402


class Stage3PRContractTests(unittest.TestCase):
    def test_generic_registry_rubric_submetrics_and_selectors_are_admitted(self):
        metrics = validator.load_capability_metrics()
        self.assertEqual(metrics["cli:stage3-plan"]["metrics"], {"P7", "P8", "P9"})
        rubric = validator.load_rubrics()["stage23-general-v1"]
        submetrics = validator.load_operational_submetrics()
        mappings = validator.load_criterion_submetrics()
        invariants = validator.load_invariant_registry()
        for criterion, metric, submetric, invariant in (
            (
                "P7V1.QUESTION_DESIGN",
                "P7",
                "S3V1_QUESTION_PATH",
                "stage3-question-paths",
            ),
            (
                "P8V1.EVIDENCE_INTERPRETATION",
                "P8",
                "S3V1_EVIDENCE_RESULT",
                "stage3-result-boundary",
            ),
            (
                "P9V1.FEASIBILITY",
                "P9",
                "S3V1_DEPENDENCIES",
                "stage3-confirmation-boundary",
            ),
        ):
            self.assertEqual(rubric[criterion], metric)
            self.assertEqual(submetrics[submetric], {metric})
            self.assertEqual(mappings[criterion], {submetric})
            self.assertIn(
                invariant,
                validator.required_invariants(
                    {criterion}, {"cli:stage3-plan"}, metrics
                ),
            )
            self.assertIn(invariant, invariants)


if __name__ == "__main__":
    unittest.main()

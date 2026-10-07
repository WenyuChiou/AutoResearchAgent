"""Regression tests for the pure Stage 2 comparison projection."""

import copy
from pathlib import Path
import sys
import unittest


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))

from research_workspace.stage2_comparison import build_comparison_view  # noqa: E402


def attachment():
    return {
        "selection": {
            "current_options": [
                {
                    "candidate": {
                        "candidate_id": "candidate-1",
                        "version": 2,
                        "question": "Which bounded design is answerable?",
                        "opportunity": "A recorded measurement gap.",
                        "value": "Improve a bounded decision.",
                        "approach": "Compare two recorded designs.",
                        "requirements": ["A linked dataset"],
                        "limitations": [],
                        "evidence_ids": ["ev-right"],
                    },
                    "assessment": {
                        "disposition": "park",
                        "reason": "Access remains unknown.",
                        "next_step": "Check the license.",
                        "checks": {
                            "materials": {
                                "status": "unknown",
                                "score": 2,
                                "permission": "granted",
                            }
                        },
                    },
                }
            ],
            "evaluation_packet": {
                "literature": [
                    {
                        "work_id": "work-1",
                        "version_id": "v1",
                        "title": "Recorded title",
                        "authors": ["Recorded Author"],
                        "year": 2024,
                        "roles": [{"role": "topic-core"}],
                        "evidence_level": "full-text",
                        "source_ids": ["src-right"],
                        "classification": {
                            "data_type": "Recorded classification data",
                            "method": "Conflicting classification method",
                        },
                        "findings": {
                            "question": "Recorded rationale",
                            "method": "Recorded findings method",
                            "main_findings": "Recorded main finding",
                            "limitations": "",
                            "relevance": None,
                        },
                    }
                ],
                "comparison": "Exact packet-level comparison.",
                "resources": {"compute": "fixed", "cost": None},
                "evidence": [
                    {
                        "evidence_id": "ev-right",
                        "source_id": "src-right",
                        "work_id": "work-1",
                        "version_id": "v1",
                        "locator": "line 1",
                        "quote": "Recorded quote.",
                        "evidence_level": "full-text",
                        "score": 99,
                        "permission": "approved",
                    },
                    {
                        "evidence_id": "ev-wrong-version",
                        "source_id": "src-right",
                        "work_id": "work-1",
                        "version_id": "v2",
                    },
                    {
                        "evidence_id": "ev-wrong-source",
                        "source_id": "src-other",
                        "work_id": "work-1",
                        "version_id": "v1",
                    },
                ],
            },
        }
    }


class Stage2ComparisonViewTests(unittest.TestCase):
    def test_projects_recorded_values_and_exact_paths_without_mutation(self):
        value = attachment()
        original = copy.deepcopy(value)
        view = build_comparison_view(value)
        row = view["literature"][0]

        self.assertEqual(value, original)
        self.assertEqual(row["key"], '["work-1","v1"]')
        self.assertEqual(row["evidence_ids"], ["ev-right"])
        self.assertEqual(
            row["cells"]["question"],
            {
                "text": "Recorded rationale",
                "field": "selection.evaluation_packet.literature[0].findings.question",
            },
        )
        self.assertEqual(row["cells"]["findings"]["text"], "Recorded main finding")
        self.assertEqual(row["cells"]["method"]["text"], "Recorded findings method")
        self.assertEqual(row["cells"]["data"]["text"], "Recorded classification data")
        self.assertEqual(view["comparison"], "Exact packet-level comparison.")
        self.assertEqual(view["resources"], {"compute": "fixed", "cost": None})
        view["literature"][0]["authors"].append("View-only change")
        view["directions"][0]["checks"]["materials"]["status"] = "changed"
        view["resources"]["compute"] = "changed"
        self.assertEqual(value, original)

    def test_missing_empty_and_conflicting_values_are_not_upgraded(self):
        view = build_comparison_view(attachment())
        row = view["literature"][0]
        direction = view["directions"][0]

        self.assertEqual(row["cells"]["limitations"]["text"], "")
        self.assertEqual(
            row["cells"]["relevance"],
            {
                "text": None,
                "field": "selection.evaluation_packet.literature[0].findings.relevance",
            },
        )
        self.assertEqual(row["cells"]["validation"], {"text": None, "field": None})
        self.assertEqual(direction["limitations"], [])
        self.assertEqual(direction["checks"]["materials"]["score"], 2)
        self.assertNotIn("score", view["evidence"][0])
        self.assertNotIn("permission", view["evidence"][0])
        self.assertNotIn("permission", direction)

    def test_empty_legacy_literature_and_unknown_fields_stay_distinct(self):
        value = {"selection": {"current_options": [], "evaluation_packet": {}}}
        view = build_comparison_view(value)
        self.assertEqual(view["literature"], [])
        self.assertEqual(view["directions"], [])
        self.assertIsNone(view["comparison"])
        self.assertIsNone(view["resources"])

        value = attachment()
        work = value["selection"]["evaluation_packet"]["literature"][0]
        work.pop("authors")
        work["source_ids"] = []
        row = build_comparison_view(value)["literature"][0]
        self.assertIsNone(row["authors"])
        self.assertEqual(row["source_ids"], [])
        self.assertEqual(row["evidence_ids"], [])


if __name__ == "__main__":
    unittest.main()

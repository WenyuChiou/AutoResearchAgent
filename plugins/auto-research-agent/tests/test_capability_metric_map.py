"""Ensure every plugin capability declares measurable evaluation effects."""

import json
from pathlib import Path
import re
import unittest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]
REGISTRY = PLUGIN_ROOT / "evals/capability-metric-map.v1.json"
SCORECARD = PLUGIN_ROOT / "evals/primary-scorecard.v1.json"
RUBRIC = PLUGIN_ROOT / "evals/rubrics/aging-bidirectional-rubric.v1.json"
CAPABILITY_ID = re.compile(
    r"^(?:skill|mcp-tool|cli|validator|gate):[a-z0-9]+(?:-[a-z0-9]+)*$"
)


class CapabilityMetricMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        scorecard = json.loads(SCORECARD.read_text(encoding="utf-8"))
        cls.metric_ids = {
            metric["id"] for stage in scorecard["stages"] for metric in stage["metrics"]
        }
        rubric = json.loads(RUBRIC.read_text(encoding="utf-8"))
        cls.rubric_criteria = {
            criterion_id: metric["id"]
            for metric in rubric["metrics"]
            for criterion_id in metric["criterion_ids"]
        }

    def test_capability_ids_and_owner_paths_are_unique(self):
        entries = self.registry["capabilities"]
        ids = [entry["capability_id"] for entry in entries]
        owners = [entry["owner_path"] for entry in entries]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(owners), len(set(owners)))

    def test_capability_ids_are_canonical_and_match_kind(self):
        for entry in self.registry["capabilities"]:
            with self.subTest(capability=entry["capability_id"]):
                self.assertRegex(entry["capability_id"], CAPABILITY_ID)
                prefix = entry["capability_id"].split(":", 1)[0]
                self.assertEqual(prefix, entry["kind"])

    def test_all_standardized_capability_entry_points_are_registered(self):
        registered = {entry["owner_path"] for entry in self.registry["capabilities"]}
        expected = {
            path.parent.relative_to(REPO_ROOT).as_posix()
            for path in (PLUGIN_ROOT / "skills").glob("*/SKILL.md")
        }
        expected.add(".github/scripts/validate_research_pr.py")
        for directory in ("tools", "mcp", "cli", "validators", "gates"):
            root = PLUGIN_ROOT / directory
            if root.exists():
                for path in root.iterdir():
                    if path.name in {"README.md", "__init__.py", "__pycache__"}:
                        continue
                    expected.add(path.relative_to(REPO_ROOT).as_posix())
        self.assertEqual(registered, expected)

    def test_each_capability_has_valid_metrics_measures_and_tests(self):
        requirements = self.registry["requirements"]
        for entry in self.registry["capabilities"]:
            with self.subTest(capability=entry["capability_id"]):
                self.assertIn(entry["kind"], requirements["allowed_kinds"])
                self.assertIn(entry["status"], requirements["allowed_statuses"])
                self.assertIn(
                    entry["metric_role"], requirements["allowed_metric_roles"]
                )
                self.assertTrue((REPO_ROOT / entry["owner_path"]).exists())
                self.assertTrue(entry["problem"].strip())
                self.assertTrue(entry["mechanism"].strip())
                self.assertTrue(entry["metric_effects"])
                for effect in entry["metric_effects"]:
                    self.assertIn(effect["metric_id"], self.metric_ids)
                    self.assertTrue(effect["rubric_criteria"])
                    for criterion_id in effect["rubric_criteria"]:
                        self.assertEqual(
                            self.rubric_criteria[criterion_id], effect["metric_id"]
                        )
                    self.assertIn(
                        effect["expected_direction"],
                        requirements["allowed_directions"],
                    )
                    self.assertTrue(
                        all(item.strip() for item in effect["hard_measures"])
                    )
                    self.assertTrue(effect["human_judgment"].strip())
                self.assertTrue(all(item.strip() for item in entry["guardrails"]))
                self.assertTrue(entry["test_refs"])
                for test_ref in entry["test_refs"]:
                    self.assertTrue((REPO_ROOT / test_ref).is_file(), test_ref)

    def test_foundation_does_not_claim_measured_improvement(self):
        for entry in self.registry["capabilities"]:
            if entry["status"] == "foundation":
                self.assertFalse(entry["quality_improvement_claimed"])


if __name__ == "__main__":
    unittest.main()

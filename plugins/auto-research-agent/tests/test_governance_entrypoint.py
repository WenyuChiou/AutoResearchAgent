"""Keep contributor instruction routing and readiness boundaries connected."""

from pathlib import Path
import re
import unittest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]
ROOT_AGENTS = REPO_ROOT / "AGENTS.md"
PLUGIN_AGENTS = PLUGIN_ROOT / "AGENTS.md"
READINESS = PLUGIN_ROOT / "evals/READINESS_AND_TEAM_WORKFLOW.zh-TW.md"
SMOKE_EVIDENCE = PLUGIN_ROOT / "evals/evidence/instruction-routing-smoke-2026-09-20.md"
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


class GovernanceEntrypointTests(unittest.TestCase):
    def test_root_routes_shared_harness_paths_to_plugin_contract(self):
        text = ROOT_AGENTS.read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        self.assertIn("# AutoResearchAgent fork routing", text)
        self.assertIn("plugins/auto-research-agent/AGENTS.md", text)
        self.assertIn(
            "read and follow `plugins/auto-research-agent/AGENTS.md` before "
            "planning or editing",
            normalized,
        )
        for path in (
            "plugins/auto-research-agent/",
            ".github/scripts/validate_research_pr.py",
            ".github/scripts/test_validate_research_pr.py",
            ".github/workflows/stage1-plugin.yml",
            ".github/pull_request_template.md",
        ):
            self.assertIn(path, text)

    def test_plugin_contract_links_resolve_and_covers_required_controls(self):
        text = PLUGIN_AGENTS.read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        links = [link for link in MARKDOWN_LINK.findall(text) if "://" not in link]
        expected_links = [
            "CONTRIBUTING.md",
            "evals/README.md",
            "evals/EVALUATION_WORKFLOW.zh-TW.md",
            "evals/METRICS_EXPLAINED.zh-TW.md",
            "evals/OPERATIONAL_DEFINITIONS.zh-TW.md",
            "evals/rubrics/AGING_BIDIRECTIONAL_RUBRIC_V1.zh-TW.md",
            "evals/PR_GUIDE.md",
            "evals/capability-metric-map.v1.json",
            "evals/READINESS_AND_TEAM_WORKFLOW.zh-TW.md",
            "skills/stage1-literature/SKILL.md",
            "README.md",
        ]
        self.assertEqual(links, expected_links)
        for link in links:
            with self.subTest(link=link):
                self.assertTrue((PLUGIN_ROOT / link).resolve().exists(), link)
        for term in (
            "reuse`, `wrap`, `extend`, or `build-new`",
            "capability-metric-map.v1.json",
            "private holdout",
            "Auto-R1 and Auto-R2",
            "not yet demonstrated",
            "core team reviews and merges",
            "WenyuChiou/AutoResearchAgent",
        ):
            self.assertIn(term, text)
        for boundary in (
            "Keep the private holdout, benchmark titles, answer keys, and "
            "condition map out of production prompts, queries, fixtures, tools, "
            "and stopping logic.",
            "Scientific-quality improvement requires the frozen paired live A/B",
            "Contributors and their AI do not approve or merge their own harness PRs.",
            "do not send this harness to OpenAI upstream.",
        ):
            self.assertIn(boundary, normalized)

    def test_readiness_keeps_evaluation_and_improvement_claims_separate(self):
        text = READINESS.read_text(encoding="utf-8")
        positions = [text.index(f"Level {level} ") for level in range(4)]
        self.assertEqual(positions, sorted(positions))
        for required in (
            "Instruction-ready",
            "Evaluation-ready",
            "Stage-executable",
            "Improvement-demonstrated",
            "Stage 1 尚未完成",
            "尚未執行",
            "target 至少兩組改善且零退步",
            "核心組",
        ):
            self.assertIn(required, text)
        self.assertNotRegex(text, r"(?<!Auto-)R[12](?![0-9])")
        self.assertIn("evidence/instruction-routing-smoke-2026-09-20.md", text)
        evidence = SMOKE_EVIDENCE.read_text(encoding="utf-8")
        self.assertIn("Codex CLI: 0.153.3", evidence)
        self.assertIn(
            "af9b45e5bd7570b09f6bf621cd2e9205c2bf12739ad9f4681062b66c60c78785",
            evidence,
        )
        self.assertIn("It made no repository edits.", evidence)
        self.assertIn("does not prove research-quality improvement", evidence)


if __name__ == "__main__":
    unittest.main()

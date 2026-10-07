"""Regression tests for opt-in Stage 2 comparison preparation."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest


CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from stage2_common import canonical_hash  # noqa: E402
from stage2_ideation.prompts import (  # noqa: E402
    build_extraction_task,
    build_research_task,
)


SNAPSHOT = "a" * 64


def packet(topic, question, family_names, *, schema_version="2.2.0"):
    return {
        "kind": "Stage2Packet",
        "schema_version": schema_version,
        "packet_id": "packet-comparison-preparation",
        "brief": {
            "kind": "ResearchBrief",
            "schema_version": "1.0.0",
            "original_description": topic,
            "needs": [{"need_id": "need-1", "question": question}],
            "scope_fields": [
                {
                    "field": "geography",
                    "material": False,
                    "reason": "This question is not geographically bounded.",
                },
                {
                    "field": "study_design",
                    "material": True,
                    "reason": "The user must decide whether designs are restricted.",
                },
            ],
            "suggestions": [],
            "decisions": [
                {
                    "event_id": "decision-1",
                    "field": "study_design",
                    "status": "unrestricted",
                    "value": None,
                    "actor": "test-user",
                    "source_ref": "comparison-preparation-test",
                    "recorded_at": "2026-10-06T12:00:00-04:00",
                    "user_input": "Keep study design unrestricted.",
                    "authority": "user",
                }
            ],
            "previous_sha256": None,
        },
        "resources": "Use the supplied sources and inspect more only when needed.",
        "comparison": "No topic-derived comparison has been prepared yet.",
        "literature": [
            {
                "work_id": f"work-{index}",
                "version_id": "v1",
                "family": family,
            }
            for index, family in enumerate(family_names, 1)
        ],
        "sources": [
            {
                "source_id": f"src-{index}",
                "work_id": f"work-{index}",
                "version_id": "v1",
                "evidence_level": "full-text",
            }
            for index in range(1, len(family_names) + 1)
        ],
        "evidence": [],
        "unresolved": ["The comparison dimensions remain unknown."],
        "candidates": [],
        "research_tables": None,
    }


def stage2_input(task):
    prompt = task["prompt"]
    start = prompt.index("<stage2_input>") + len("<stage2_input>")
    end = prompt.index("</stage2_input>")
    return json.loads(prompt[start:end])


class ComparisonPreparationTests(unittest.TestCase):
    def setUp(self):
        self.topics = [
            packet(
                "Compare urban heat exposure measurements.",
                "Which measurements support neighborhood heat decisions?",
                ["remote sensing", "wearable sensing"],
            ),
            packet(
                "Compare compiler test-reduction strategies.",
                "Which reduction strategies preserve failure semantics?",
                ["delta debugging", "grammar-guided reduction"],
            ),
        ]

    def test_opt_in_tasks_prepare_comparison_before_synthesis_for_each_topic(self):
        prompts = []
        ordered_steps = (
            "Restate the confirmed research brief",
            "Inspect representative works from distinct literature families",
            "Interpret the key concepts",
            "Define topic-derived comparison dimensions",
            "Build a source-bound matrix",
            "Only after the matrix, synthesize",
        )
        for source_packet in self.topics:
            with self.subTest(topic=source_packet["brief"]["original_description"]):
                task = build_research_task(source_packet, SNAPSHOT)
                payload = stage2_input(task)
                positions = [task["prompt"].index(step) for step in ordered_steps]

                self.assertEqual(positions, sorted(positions))
                self.assertEqual(payload["brief"], source_packet["brief"])
                self.assertEqual(
                    payload["comparison_preparation_policy"],
                    "topic-derived-source-bound-comparison-v1",
                )
                self.assertIn(
                    source_packet["brief"]["needs"][0]["question"], task["prompt"]
                )
                self.assertIn("different operational meanings", task["prompt"])
                self.assertIn(
                    "Partially comparable and noncomparable studies", task["prompt"]
                )
                self.assertIn(
                    "missing matrix\ncell is not automatically", task["prompt"]
                )
                self.assertIn("citation lineage", task["prompt"])
                self.assertIn(
                    "substantive\n   explanatory or decision value", task["prompt"]
                )
                self.assertIn("necessary variables and granularity", task["prompt"])
                self.assertIn("scope and time of the actual\ncheck", task["prompt"])
                self.assertNotIn("aging", task["prompt"].lower())
                self.assertNotIn("country", task["prompt"].lower())
                self.assertNotIn("react", task["prompt"].lower())
                self.assertNotIn("reflection", task["prompt"].lower())
                prompts.append(task["prompt"])

        self.assertNotEqual(prompts[0], prompts[1])

    def test_policy_identifier_is_bound_into_only_the_opt_in_input_hash(self):
        task = build_research_task(self.topics[0], SNAPSHOT)
        payload = stage2_input(task)
        expected = canonical_hash(
            {
                "kind": "Stage2IdeationResearchTask",
                "snapshot_sha256": SNAPSHOT,
                "payload": payload,
            }
        )
        prior_payload = copy.deepcopy(payload)
        prior_payload.pop("comparison_preparation_policy")
        prior_hash = canonical_hash(
            {
                "kind": "Stage2IdeationResearchTask",
                "snapshot_sha256": SNAPSHOT,
                "payload": prior_payload,
            }
        )

        self.assertEqual(task["input_hash"], expected)
        self.assertNotEqual(task["input_hash"], prior_hash)

    def test_legacy_research_tasks_remain_byte_identical(self):
        expected_input_hash = (
            "7d4b7b20ff62a0e06b6da99366eba61ed20c9169ea23e3d5afa90cb95e554df1"
        )
        expected_prompt_sha256 = (
            "b79020677c46a439918900bc5bc1473f23d2b46df0913ed58b1745c0bd43ddaf"
        )
        for version in ("2.0.0", "2.1.0"):
            legacy = copy.deepcopy(self.topics[0])
            legacy["schema_version"] = version
            legacy.pop("research_tables")
            task = build_research_task(legacy, SNAPSHOT)

            self.assertEqual(task["input_hash"], expected_input_hash)
            self.assertEqual(
                hashlib.sha256(task["prompt"].encode("utf-8")).hexdigest(),
                expected_prompt_sha256,
            )
            self.assertNotIn("comparison_preparation_policy", task["prompt"])

    def test_research_stays_native_and_saved_proposal_extraction_stays_tool_free(self):
        source_packet = self.topics[1]
        research = build_research_task(source_packet, SNAPSHOT)
        extraction = build_extraction_task(
            "A saved natural-language proposal with no retained direction.",
            source_packet,
            SNAPSHOT,
        )

        self.assertEqual(research["tools_policy"], "native")
        self.assertIn("full native research environment", research["prompt"])
        self.assertIn("natural prose", research["prompt"])
        self.assertNotIn("<extraction_schema>", research["prompt"])
        self.assertEqual(extraction["tools_policy"], "none")
        self.assertIn("saved proposal", extraction["prompt"])
        self.assertIn("without tools or new research", extraction["prompt"])


if __name__ == "__main__":
    unittest.main()

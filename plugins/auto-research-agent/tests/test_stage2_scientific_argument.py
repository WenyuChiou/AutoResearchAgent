"""Deterministic contract tests for opt-in Stage 2 packet 2.5 arguments."""

import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "cli")]

from stage2_check.report import _candidate_details  # noqa: E402
from stage2_check.report_html import _candidate as candidate_html  # noqa: E402
from stage2_common import Stage2Error, canonical_hash, validate_packet  # noqa: E402
from stage2_common.scientific_argument import validate_scientific_argument  # noqa: E402
from stage2_ideation.prompts import build_extraction_task, build_research_task  # noqa: E402
from stage2_ideation.__main__ import _enable_tables  # noqa: E402
from stage2_live.extraction import build_span_index, expand_span_ids, generation_schema  # noqa: E402
from stage2_workflow.planning_handoff import DELIVERY_REFS, _project_handoff  # noqa: E402
from test_stage2_prior_work import Stage2PriorWorkTests  # noqa: E402


def claim(text, evidence_ids=(), source_refs=(), proposal_spans=(), status="proposal"):
    return {
        "text": text,
        "status": status,
        "evidence_ids": list(evidence_ids),
        "source_refs": list(source_refs),
        "proposal_spans": list(proposal_spans),
    }


def argument(evidence_id, source_ref, *, resource_refs=(), proposal_spans=()):
    return {
        "motivation": claim(
            "The bounded decision needs a scientific explanation.",
            proposal_spans=proposal_spans,
        ),
        "current_state": [
            claim(
                "The saved source establishes the current observation.",
                [evidence_id],
                [source_ref],
                status="fact",
            )
        ],
        "gaps": [
            {
                "gap_id": "gap-measurement",
                "statement": claim(
                    "The measurement relation remains unknown.", status="unknown"
                ),
                "importance": claim("Resolving it would support the bounded decision."),
            }
        ],
        "challenges": [
            {
                "challenge_id": "challenge-design",
                "kind": "scientific",
                "statement": claim(
                    "The comparison must distinguish the proposed mechanism."
                ),
                "gap_ids": ["gap-measurement"],
                "question_ids": ["question-core"],
            }
        ],
        "questions": [
            {
                "question_id": "question-core",
                "text": "Does the bounded design distinguish the proposed mechanism?",
                "priority": "core",
                "gap_ids": ["gap-measurement"],
                "object": "The bounded measurement design",
                "intended_claim": "The design distinguishes the mechanism under stated conditions.",
                "status": "proposal",
            }
        ],
        "contribution_claims": [
            {
                "text": "The comparison may resolve the bounded gap.",
                "question_ids": ["question-core"],
                "status": "proposal",
            }
        ],
        "resource_refs": list(resource_refs),
    }


class Stage2ScientificArgumentTests(unittest.TestCase):
    def setUp(self):
        fixture = Stage2PriorWorkTests(
            "test_review_version_detection_keeps_legacy_and_prior_work_hashes"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.packet = copy.deepcopy(fixture.packet)
        self.candidate = self.packet["candidates"][0]
        evidence_id = self.packet["evidence"][0]["evidence_id"]
        source = self.packet["sources"][0]
        source_ref = {
            key: source[key] for key in ("source_id", "work_id", "version_id")
        }
        self.candidate["scientific_argument"] = argument(evidence_id, source_ref)
        self.packet["schema_version"] = "2.5.0"
        self.packet["prior_work_reviews"][0]["candidate_sha256"] = canonical_hash(
            self.candidate
        )

    def test_packet_2_5_is_opt_in_and_requires_a_core_closed_argument(self):
        validate_packet(self.fixture.packet, self.fixture.source_root)
        validate_packet(self.packet, self.fixture.source_root)
        invalid = copy.deepcopy(self.packet)
        invalid["candidates"][0]["scientific_argument"]["questions"][0]["priority"] = (
            "secondary"
        )
        invalid["prior_work_reviews"][0]["candidate_sha256"] = canonical_hash(
            invalid["candidates"][0]
        )
        with self.assertRaisesRegex(Stage2Error, "requires a core question"):
            validate_packet(invalid, self.fixture.source_root)

    def test_resource_refs_use_direction_resource_id_for_same_candidate_version(self):
        candidate = self.candidate
        self.packet["research_tables"] = {
            "dimensions": [],
            "work_refs": [],
            "cells": [],
            "direction_resources": [
                {
                    "resource_id": "resource-data",
                    "candidate_id": candidate["candidate_id"],
                    "candidate_version": candidate["version"],
                }
            ],
        }
        candidate["scientific_argument"]["resource_refs"] = [
            {
                "resource_id": "resource-data",
                "question_ids": ["question-core"],
                "purpose": "Measure the bounded outcome.",
                "fit_status": "proposed",
                "evidence_ids": [],
            }
        ]
        validate_scientific_argument(candidate, self.packet, error_type=Stage2Error)
        candidate["scientific_argument"]["resource_refs"][0]["resource_id"] = (
            "resource-name"
        )
        with self.assertRaisesRegex(Stage2Error, "resource_ref does not resolve"):
            validate_scientific_argument(candidate, self.packet, error_type=Stage2Error)

    def test_prompts_extraction_and_reports_retain_the_argument(self):
        raw = "The bounded decision needs a scientific explanation."
        span_index = build_span_index(raw)
        span_id = span_index["spans"][0]["span_id"]
        schema = generation_schema(span_index, self.packet)
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.2.0")
        self.assertIn("scientific_argument", schema["$defs"]["candidate"]["required"])
        self.assertIn(
            "scientific argument", build_research_task(self.packet, "a" * 64)["prompt"]
        )
        self.assertEqual(
            build_extraction_task(raw, self.packet, "a" * 64)["schema_version"], "1.2.0"
        )

        generated_candidate = copy.deepcopy(self.candidate)
        generated_candidate.pop("candidate_id")
        generated_candidate.pop("version")
        generated_candidate.pop("parent_version")
        generated_candidate["scientific_argument"]["motivation"]["proposal_spans"] = [
            {"span_id": span_id}
        ]
        generated = {
            "comparison_rows": [],
            "candidates": [
                {
                    "candidate": generated_candidate,
                    "existing_candidate_id": None,
                    "spans": [{"span_id": span_id}],
                }
            ],
            "research_tables": None,
        }
        expanded = expand_span_ids(generated, raw, span_index, self.packet)
        self.assertEqual(
            expanded["candidates"][0]["candidate"]["scientific_argument"]["motivation"][
                "proposal_spans"
            ],
            [{"start": 0, "end": len(raw)}],
        )

        evidence = {row["evidence_id"]: row for row in self.packet["evidence"]}
        lines = []
        _candidate_details(lines, self.candidate, evidence)
        self.assertIn("Scientific argument:", lines)
        self.assertIn("Scientific argument", candidate_html(self.candidate, evidence))

    def test_cli_opt_in_creates_only_an_unformed_packet_2_5_seed(self):
        seed = copy.deepcopy(self.fixture.packet)
        seed["candidates"] = []
        seed["prior_work_reviews"] = []
        source = self.fixture.root / "unformed-2.4.json"
        output = self.fixture.root / "unformed-2.5.json"
        source.write_text(json.dumps(seed), encoding="utf-8")
        args = SimpleNamespace(
            packet=source,
            source_root=self.fixture.source_root,
            output=output,
            supplemental_versions=False,
            prior_work_reviews=False,
            scientific_arguments=True,
        )
        with redirect_stdout(io.StringIO()):
            _enable_tables(args)
        produced = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(produced["schema_version"], "2.5.0")
        self.assertEqual(produced["candidates"], [])
        self.assertEqual(produced["prior_work_reviews"], [])
        self.assertIsNone(produced["research_tables"])
        validate_packet(produced, self.fixture.source_root)

        formed = self.fixture.root / "formed-2.4.json"
        formed.write_text(json.dumps(self.fixture.packet), encoding="utf-8")
        args.packet = formed
        args.output = self.fixture.root / "must-not-exist.json"
        with self.assertRaisesRegex(Stage2Error, "unformed packet 2.4"):
            _enable_tables(args)

    def test_planning_handoff_retains_argument_prior_work_and_no_authority(self):
        selected = {
            "candidate_id": self.candidate["candidate_id"],
            "candidate_version": self.candidate["version"],
        }
        delivery = {
            "selection": {
                "evaluation_packet": self.packet,
                "current_options": [{"candidate": self.candidate}],
            },
            "manifest": {
                "manifest_sha256": "a" * 64,
                "files": [{"path": path} for path in DELIVERY_REFS.values()],
            },
        }
        record = {
            "decision": {"selected": [selected]},
            "report_manifest_sha256": "b" * 64,
            "snapshot_sha256": "c" * 64,
        }
        handoff = _project_handoff(delivery, record, "d" * 64, "e" * 64)
        projected = handoff["evaluation_packet"]["candidates"][0]
        self.assertEqual(
            projected["scientific_argument"], self.candidate["scientific_argument"]
        )
        self.assertEqual(
            handoff["selected_prior_work_reviews"]["rows"],
            self.packet["prior_work_reviews"],
        )
        self.assertFalse(handoff["execution_authorized"])

    def test_workspace_pipeline_preserves_rich_review_view_for_2_5(self):
        from research_workspace_native.stage_pipeline import StagePipeline

        pipeline = StagePipeline.__new__(StagePipeline)
        for version, expected in (
            ("2.4.0", "1.2.0"),
            ("2.5.0", "1.2.0"),
            ("2.3.0", "1.1.0"),
        ):
            pipeline.packet = {"schema_version": version}
            self.assertEqual(pipeline._view_version(), expected)


if __name__ == "__main__":
    unittest.main()

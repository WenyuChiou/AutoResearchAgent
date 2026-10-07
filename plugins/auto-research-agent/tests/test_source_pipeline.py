"""Real source units at the pipeline boundary, with synthetic native responses."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_original_fields as original_fixture
import test_pipeline_v31 as pipeline_fixture
from test_judging_v31 import _packet
from stage1_eval import pipeline_v31 as pipeline
from stage1_eval.common import EvaluationError, read_json
from stage1_eval.judging_v31 import judge_packet_v31
from stage1_eval.judging import CONTENT_IDS, PROCESS_IDS


class SourcePipelineTests(unittest.TestCase):
    def setUp(self):
        self.flow = pipeline_fixture.PipelineV31Tests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.original = original_fixture.OriginalFieldTests()
        self.original.setUp()
        self.addCleanup(self.original.doCleanups)
        self.flow.subject.update(self.original.subject)
        self.extraction = copy.deepcopy(self.original.extraction)
        self.extraction.update(extraction_complete=True, unextracted_reason=None)
        self.flow.extract.return_value = (self.extraction, self.original.provenance)
        self.sources = {
            "sources": [self.original.fixture.record],
            "receipts": [],
            "public_fetches": [],
        }

    def test_real_units_preserve_tail_contrary_and_replay_without_calls(self):
        with (
            patch.object(pipeline, "collect_sources_v31", return_value=self.sources),
            patch(
                "stage1_eval.model_calls._execute_bound_process",
                side_effect=self.original.respond,
            ) as calls,
        ):
            pipeline.evaluate_v31(self.flow.args)
            self.assertGreater(calls.call_count, 4)
            root = Path(self.flow.args.output)
            raw = read_json(root / "subject-extraction.json")
            self.assertNotIn("original_fields", raw["works"][0])
            enriched = read_json(root / "subject-original-extraction.json")
            self.assertEqual(
                {
                    r["raw_value"]
                    for r in enriched["works"][0]["original_fields"]["year"]
                },
                {"2019", "2020"},
            )
            packet = read_json(root / "evidence-packet.json")
            self.assertEqual(
                packet["content_evidence"]["source"]["text"],
                self.sources["sources"][0]["abstract"],
            )
            self.assertEqual(
                packet["content_evidence"]["source:identity"]["source_level"],
                "metadata",
            )
            audits = self.flow.judge.call_args.kwargs["source_audits"]
            for role in ("r1", "r2"):
                self.assertTrue(
                    any(row["contrary_leaf_ids"] for row in audits[role]["summaries"])
                )
                self.assertFalse(audits[role]["score_awarded"])
            saved = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            calls.reset_mock()
            self.flow.args.resume_verified = True
            pipeline.evaluate_v31(self.flow.args, replay_only=True)
            calls.assert_not_called()
            self.assertEqual(
                saved, {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            )

    def test_missing_original_provenance_stops_before_source_or_scoring(self):
        self.flow.extract.return_value = (self.extraction, {"work_source_map": {}})
        with patch.object(pipeline, "collect_sources_v31") as acquire:
            with self.assertRaisesRegex(EvaluationError, "span index changed"):
                pipeline.evaluate_v31(self.flow.args)
            acquire.assert_not_called()
        self.flow.judge.assert_not_called()
        self.assertFalse((Path(self.flow.args.output) / "result.json").exists())

    def test_source_error_is_evaluator_failure_not_subject_zero(self):
        with (
            patch.object(pipeline, "collect_sources_v31", return_value=self.sources),
            patch(
                "stage1_eval.model_calls._execute_bound_process",
                side_effect=self.original.respond,
            ),
            patch(
                "stage1_eval.source_audit_units.audit_sources",
                side_effect=EvaluationError("source unit incomplete"),
            ),
        ):
            with self.assertRaisesRegex(EvaluationError, "source unit incomplete"):
                pipeline.evaluate_v31(self.flow.args)
        root = Path(self.flow.args.output)
        self.assertFalse((root / "result.json").exists())
        self.assertEqual(
            read_json(root / "evaluation-attempt-001.json")["status"], "evaluator-error"
        )
        self.flow.judge.assert_not_called()

    def test_source_audits_are_independent_and_adjudication_sees_both(self):
        audits = {role: {"summaries": [], "leaves": []} for role in ("r1", "r2")}
        seen = []
        disagree_score = True

        def respond(prompt, schema, output, label, options, normalize, **kwargs):
            data = json.loads(prompt[prompt.index('{"unit_kind"') :])["packet"]
            if label.startswith("content"):
                role = label.split("-")[1]
                self.assertEqual(
                    set(data["source_audit_observations"]),
                    {"r1", "r2"} if role == "adj" else {role},
                )
                seen.append(role)
            else:
                self.assertNotIn("source_audit_observations", data)
            ids = CONTENT_IDS if label.startswith("content") else PROCESS_IDS
            rows = [
                {
                    "criterion_id": key,
                    "status": "unverifiable",
                    "score": None,
                    "passages": [],
                    "reason": "Missing source",
                    "missing_evidence": ["Missing source"],
                }
                for key in sorted(ids)
            ]
            if disagree_score and label == "content-r2-criteria":
                rows[-1].update(status="scored", score=0, missing_evidence=[])
            return normalize(
                {
                    "criteria": rows,
                    "core_assessments": [],
                    "omission_assessments": [],
                    "major_issues": [],
                }
            ), {}

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("stage1_eval.judging_v31.run_unit", side_effect=respond),
        ):
            judge_packet_v31(_packet(), directory, {}, source_audits=audits)
        self.assertEqual(seen, ["r1", "r2", "adj"])
        disagree_score = False
        for role, verdict in (("r1", "supported"), ("r2", "contradicted")):
            audits[role]["summaries"] = [
                {
                    "target": {"id": "work:year", "work_ids": ["work"]},
                    "verdict": verdict,
                    "unknown_reason": None,
                }
            ]
        seen.clear()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("stage1_eval.judging_v31.run_unit", side_effect=respond),
        ):
            judge_packet_v31(_packet(), directory, {}, source_audits=audits)
        self.assertEqual(seen, ["r1", "r2", "adj"])
        audits["r2"]["summaries"][0]["verdict"] = "supported"
        audits["r2"]["summaries"][0]["reason"] = "Equivalent wording differs."
        seen.clear()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("stage1_eval.judging_v31.run_unit", side_effect=respond),
        ):
            judge_packet_v31(_packet(), directory, {}, source_audits=audits)
        self.assertEqual(seen, ["r1", "r2"])


if __name__ == "__main__":
    unittest.main()

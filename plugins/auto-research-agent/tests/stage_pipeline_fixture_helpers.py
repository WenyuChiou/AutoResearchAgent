# ruff: noqa: E402 -- exercise repository CLI without installing the plugin.
"""Injected receipt fixtures prove orchestration guards, never native execution."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "cli"))
sys.path.insert(0, str(HERE))

from stage2_common import Stage2Error, canonical_hash
from stage2_fixture_helpers import write_stage2_fixture
from stage2_ideation import build_extraction_task
from stage2_live.extraction import build_span_index


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class StagePipelineFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = self.root / "sources"
        self.packet = write_stage2_fixture(self.sources, candidate_count=0)
        self.path = self.root / "packet.json"
        self.path.write_text(json.dumps(self.packet), encoding="utf8")
        self.uid, self.verifications = 0, 0
        self.pipeline = self.open()

    def verify(self, receipt, *, expected_prompt_sha256, expected_source_sha256):
        self.verifications += 1
        result = deepcopy(receipt)
        if (
            result["prompt_sha256"] != expected_prompt_sha256
            or result["source_sha256"] != expected_source_sha256
        ):
            raise Stage2Error("test-verifier-binding-differs")
        return result

    def open(self, max_calls=8):
        from research_workspace_native.stage_pipeline import StagePipeline

        return StagePipeline(
            self.path,
            self.sources,
            self.root / "pipeline",
            expected_packet_sha256=canonical_hash(self.packet),
            source_sha256="a" * 64,
            verify_receipt=self.verify,
            max_calls=max_calls,
        )

    def assessment(self):
        return dict(
            checks={
                axis: dict(
                    status="unknown",
                    score=None,
                    rationale="Synthetic source does not establish this enabling condition.",
                    evidence_ids=[],
                    blocking=True,
                    next_check="Obtain bounded evidence.",
                )
                for axis in (
                    "opportunity",
                    "value",
                    "answerability",
                    "materials",
                    "execution",
                )
            },
            disposition="park",
            reason="Evidence remains incomplete.",
            next_step="Review missing prerequisites.",
            scope_change_requested=False,
        )

    def output(self, task):
        phase = task["phase"]
        if phase == "extraction":
            raw = self.pipeline.prose["research"]["text"]
            binding = build_extraction_task(
                raw, self.pipeline.packet, self.pipeline.snapshot
            )
            spans = [{"span_id": build_span_index(raw)["spans"][0]["span_id"]}]
            return dict(
                kind="Stage2IdeationExtraction",
                schema_version="1.0.0",
                **{
                    key: binding[key]
                    for key in (
                        "snapshot_sha256",
                        "packet_sha256",
                        "raw_proposal_sha256",
                        "input_hash",
                    )
                },
                receipt=dict(
                    policy_boundary="declared-task-policy",
                    tools_policy="none",
                    tool_calls=[],
                    isolation_verified=False,
                ),
                bibliography=[],
                comparison_rows=[
                    dict(
                        dimension="validation boundary",
                        finding=raw,
                        comparability="unknown",
                        noncomparability=None,
                        source_roles=[],
                        shared_relationships=[],
                        evidence_ids=["ev-1"],
                        spans=spans,
                    )
                ],
                candidates=[
                    dict(
                        candidate=dict(
                            question="Can a bounded validation improve measurement?",
                            research_mode="exploratory",
                            opportunity="A recorded boundary remains unknown.",
                            value="Measurement might improve.",
                            approach="Compare on supplied bytes.",
                            requirements=["Retain declared limits."],
                            limitations=["Synthetic corpus only."],
                            evidence_ids=["ev-1"],
                        ),
                        existing_candidate_id=None,
                        route="improvement",
                        mechanism="Bounded validation.",
                        closest_work_refs=[],
                        strong_alternatives=["Keep current method."],
                        change_mind_conditions=[
                            "Missing evidence changes feasibility."
                        ],
                        claim_labels=[
                            dict(
                                text="Expected benefit is untested.",
                                status="untested-benefit",
                                evidence_ids=[],
                            )
                        ],
                        spans=spans,
                    )
                ],
                unresolved=["Prerequisites remain unknown."],
            )
        if phase in {"challenger-extraction", "feasibility-extraction"}:
            return dict(
                assessment=self.assessment(),
                assumptions=["Supplied corpus is synthetic."],
                strongest_alternative="Preserve current measurement.",
                change_conditions=["New evidence."],
            )
        if phase == "reconciliation-extraction":
            return dict(
                assessment=self.assessment(),
                method="synthesis",
                reason="Both saved reviews preserve uncertainty.",
                evidence_ids=["ev-1"],
                addressed=[],
                substantive_disagreements=[],
                changed_judgment_reason=None,
            )
        return "The supplied synthetic source records a measurement boundary; a bounded validation is untested."

    def receipt(self, task, text=None):
        self.uid += 1
        value = self.output(task) if text is None else text
        if isinstance(value, dict):
            value = json.dumps(value)
        path = self.root / f"injected-native-{self.uid}.jsonl"
        path.write_text(
            json.dumps({"injected_test_final": value, "unit": self.uid}),
            encoding="utf8",
        )
        return dict(
            status="completed",
            final_text=value,
            model="injected-test",
            thread_id=f"test-thread-{self.uid}",
            turn_id=f"test-turn-{self.uid}",
            prompt_sha256=task["prompt_sha256"],
            source_sha256="a" * 64,
            observed_tool_items=[],
            raw_artifact=dict(path=str(path), sha256=digest(path.read_bytes())),
        )

    def step(self, text=None):
        task = self.pipeline.next_task()
        self.pipeline.begin_task(task["task_sha256"])
        self.pipeline.accept(task["task_sha256"], self.receipt(task, text))
        return task

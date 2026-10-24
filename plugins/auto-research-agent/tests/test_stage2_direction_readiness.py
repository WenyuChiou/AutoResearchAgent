"""Direction-stage review bindings; synthetic judgments do not establish science."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "cli")]

from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from research_workspace_native.stage_pipeline import StagePipeline  # noqa: E402
from stage2_live.controller import _initial_review_view_version  # noqa: E402
from stage2_live.review_models import (  # noqa: E402
    _common_review_view_version,
    _review_prompt,
    _review_view_version,
    reconciliation_task,
)
from stage2_workflow.reviews import (  # noqa: E402
    prepare_review,
    reconcile_reviews,
    validate_review,
)
from test_stage2_checker import assessment, finding  # noqa: E402
from stage_pipeline_fixture_helpers import StagePipelineFixture  # noqa: E402
from stage2_workflow.store import initialize_workflow, inspect_workflow  # noqa: E402
import test_stage2_prior_work as prior_fixtures  # noqa: E402


SNAPSHOT = "a" * 64


class Stage2DirectionReadinessTests(unittest.TestCase):
    def setUp(self):
        fixture = prior_fixtures.Stage2PriorWorkTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.packet = fixture.packet
        self.fixture = fixture

    def view(self, role="challenger", version="1.3.0"):
        return prepare_review(
            self.packet,
            "direction-1",
            SNAPSHOT,
            role,
            review_view_version=version,
        )

    def review(self, role, version="1.3.0"):
        value = assessment(self.packet)
        value["candidate_id"] = "direction-1"
        evidence_id = self.packet["evidence"][0]["evidence_id"]
        for row in value["checks"].values():
            row["evidence_ids"] = [evidence_id]
        value["next_step"] = (
            "After human direction selection, Stage 3 will estimate calls, cost, "
            "staffing and the detailed schedule; these are not yet established."
        )
        return {
            "role": role,
            "view_sha256": canonical_hash(self.view(role, version)),
            "snapshot_sha256": SNAPSHOT,
            "candidate_id": "direction-1",
            "candidate_version": 1,
            "assessment": value,
            "session_id": f"synthetic-{role}",
            "native_artifact": {
                "path": f"synthetic/{role}.jsonl",
                "sha256": ("b" if role == "challenger" else "c") * 64,
            },
            "initial": True,
            "assumptions": ["A bounded, evidenced minimum route is sufficient here."],
            "strongest_alternative": "An enabling data condition could be unsuitable.",
            "change_conditions": ["Evidence that the necessary data are unsuitable."],
        }

    def test_rich_controller_uses_direction_readiness_not_legacy_design_view(self):
        self.assertEqual(_initial_review_view_version(self.packet), "1.3.0")
        legacy = {**self.packet, "schema_version": "2.3.0"}
        self.assertEqual(_initial_review_view_version(legacy), "1.1.0")

    def test_projecthost_pipeline_prepares_same_policy_for_both_independent_roles(self):
        pipeline = object.__new__(StagePipeline)
        pipeline.packet = self.packet
        pipeline.snapshot = SNAPSHOT
        pipeline.binding = {"rich_review_view_version": "1.3.0"}
        pipeline._prepare_batch()
        self.assertEqual(pipeline.batch["schema_version"], "1.3.0")
        self.assertEqual(len(pipeline.batch["assignments"]), 2)
        for row in pipeline.batch["assignments"]:
            self.assertEqual(
                row["view"]["assessment_contract"], self.view()["assessment_contract"]
            )

    def test_new_policy_is_in_initial_and_extraction_context_without_peer_scores(self):
        view = self.view()
        policy = view["assessment_contract"]
        self.assertEqual(policy["decision_scope"], "direction-selection")
        self.assertIn("stage3_planning", policy)
        self.assertEqual(
            view["prior_work_review"], self.packet["prior_work_reviews"][0]
        )
        self.assertNotIn("assessment", view)
        self.assertNotIn("scores", view)
        raw = "Synthetic original review: a necessary access condition is unknown."
        prompt = _review_prompt(view, raw)
        self.assertIn(raw, prompt)
        self.assertIn('"decision_scope": "direction-selection"', prompt)
        view["assessment_contract"]["stage3_planning"].clear()
        self.assertTrue(self.view()["assessment_contract"]["stage3_planning"])

    def test_legacy_and_new_views_remain_separately_reconstructible(self):
        hashes = []
        for version in ("1.0.0", "1.1.0", "1.2.0", "1.3.0"):
            with self.subTest(version=version):
                view = self.view(version=version)
                digest = canonical_hash(view)
                hashes.append(digest)
                self.assertEqual(
                    _review_view_version(
                        self.packet, "direction-1", SNAPSHOT, "challenger", digest
                    ),
                    version,
                )
                if version in {"1.1.0", "1.2.0"}:
                    self.assertNotIn("decision_scope", view["assessment_contract"])
        self.assertEqual(len(set(hashes)), 4)

    def test_legacy_policy_and_rehashed_current_policy_cannot_certify_new_review(self):
        old = self.review("challenger", "1.2.0")
        with self.assertRaisesRegex(Stage2Error, "view-mismatch"):
            validate_review(old, self.view(), self.packet)
        changed = self.view()
        changed["assessment_contract"]["stage3_planning"] = []
        row = self.review("challenger")
        row["view_sha256"] = canonical_hash(changed)
        with self.assertRaisesRegex(Stage2Error, "review-view-packet-mismatch"):
            validate_review(row, changed, self.packet)

    def test_missing_prior_work_still_blocks_before_review(self):
        self.packet["prior_work_reviews"] = []
        with self.assertRaisesRegex(Stage2Error, "prior-work-review-missing"):
            self.view()

    def test_synthesis_carries_same_direction_policy_and_future_planning(self):
        reviews = [self.review(role) for role in ("challenger", "feasibility")]
        original = copy.deepcopy(reviews)
        task = reconciliation_task(
            self.packet,
            "direction-1",
            SNAPSHOT,
            reviews,
            review_view_version="1.3.0",
        )
        self.assertEqual(
            task["assessment_contract"], self.view()["assessment_contract"]
        )
        self.assertEqual(task["reviews"], original)
        resolution = {
            "review_sha256s": [canonical_hash(row) for row in reviews],
            "method": "synthesis",
            "reason": "Both synthetic roles support the same direction-level route.",
            "evidence_ids": [self.packet["evidence"][0]["evidence_id"]],
            "addressed": [],
            "assessment": reviews[0]["assessment"],
            "substantive_disagreements": [],
            "changed_judgment_reason": None,
        }
        result = reconcile_reviews(
            self.packet,
            "direction-1",
            SNAPSHOT,
            reviews,
            resolution,
            review_view_version="1.3.0",
        )
        self.assertTrue(result["recommendation_eligible"])
        self.assertFalse(result["native_execution_verified"])

    def test_genuine_enabling_unknown_and_evidenced_failure_still_block(self):
        for status, score in (("unknown", None), ("assessed", 0)):
            with self.subTest(status=status):
                row = self.review("challenger")
                row["assessment"]["checks"]["materials"] = finding(
                    status,
                    score,
                    blocking=True,
                    evidence_ids=[]
                    if status == "unknown"
                    else [self.packet["evidence"][0]["evidence_id"]],
                )
                with self.assertRaisesRegex(Stage2Error, "recommendation-blocked"):
                    validate_review(row, self.view(), self.packet)

    def test_mixed_review_policy_versions_are_rejected(self):
        rows = [self.review("challenger"), self.review("feasibility", "1.2.0")]
        with self.assertRaisesRegex(Stage2Error, "mixed-review-view-versions"):
            _common_review_view_version(self.packet, "direction-1", SNAPSHOT, rows)

    def replay_tail(self, view_version):
        """Synthetic recovered review tail; earlier research is not regenerated."""
        # Compact authored fixture prose; keep the real prompt ceiling unchanged.
        self.packet = copy.deepcopy(self.packet)
        self.packet["unresolved"] = []
        self.packet["comparison"] = "Bounded synthetic comparison."
        for key in ("question", "opportunity", "value", "approach"):
            self.packet["candidates"][0][key] = "Bounded synthetic question."
        self.fixture.packet = self.packet
        self.packet["prior_work_reviews"] = [self.fixture.review()]
        native = StagePipelineFixture()
        native.setUp()
        self.addCleanup(native.doCleanups)
        root = native.root / "review-tail"
        root.mkdir()
        seed = native.root / "review-packet.json"
        raw = json.dumps(self.packet).encode()
        seed.write_bytes(raw)
        binding = {
            "kind": "StagePipelineBinding",
            "schema_version": "1.0.0",
            "packet_sha256": canonical_hash(self.packet),
            "packet_bytes_sha256": hashlib.sha256(raw).hexdigest(),
            "source_sha256": "a" * 64,
            "max_calls": 8,
            "content_provenance": "repository-synthetic-corpus",
            "sources": {row["path"]: row["sha256"] for row in self.packet["sources"]},
        }
        if view_version == "1.3.0":
            binding.update(
                schema_version="1.1.0", rich_review_view_version=view_version
            )
        initialize_workflow(
            seed,
            self.fixture.source_root,
            root / "workflow",
            {"pipeline_binding": canonical_hash(binding)},
            {"execution": "externally-admitted-receipt-fed", "search": False},
            canonical_hash(self.packet),
        )
        snapshot = inspect_workflow(root / "workflow")["latest_snapshot"]["event"][
            "payload"
        ]["snapshot_sha256"]

        def restore():
            pipeline = object.__new__(StagePipeline)
            pipeline.root, pipeline.run = root, root / "workflow"
            pipeline.packet_path, pipeline.sources = seed, self.fixture.source_root
            pipeline.binding, pipeline.packet = copy.deepcopy(binding), self.packet
            pipeline.snapshot, pipeline.source_sha = snapshot, "a" * 64
            pipeline.verify_receipt, pipeline.max_calls = native.verify, 8
            pipeline.position, pipeline.attempt = 3, 0
            pipeline.records, pipeline.reviews, pipeline.resolutions = [], [], []
            pipeline.pending, pipeline.failure, pipeline.batch = None, None, None
            pipeline.prose = {}
            return pipeline

        return restore, native

    @staticmethod
    def retained_files(root):
        return {
            str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob("*")
            if p.is_file()
        }

    def test_historical_pending_review_keeps_exact_prompt_without_writes(self):
        for version in ("1.2.0", "1.3.0"):
            with self.subTest(version=version):
                restore, _ = self.replay_tail(version)
                pipeline = restore()
                task = pipeline.next_task()
                pipeline.begin_task(task["task_sha256"])
                before = self.retained_files(pipeline.root)
                reopened = restore()
                with patch("research_workspace_native.stage_pipeline._write") as write:
                    reopened._reopen()
                    write.assert_not_called()
                self.assertEqual(reopened.pending, task)
                self.assertEqual(reopened._view_version(), version)
                self.assertEqual(self.retained_files(pipeline.root), before)

    def test_legacy_accepted_review_and_extraction_replay_without_dispatch_or_writes(
        self,
    ):
        for version in ("1.2.0",):
            with self.subTest(version=version):
                restore, native = self.replay_tail(version)
                pipeline = restore()
                for value in (
                    "Synthetic retained independent review; enabling materials unknown.",
                    {
                        "assessment": native.assessment(),
                        "assumptions": ["Synthetic fixture."],
                        "strongest_alternative": "Retain the current route.",
                        "change_conditions": ["An evidenced minimum material route."],
                    },
                ):
                    task = pipeline.next_task()
                    pipeline.begin_task(task["task_sha256"])
                    pipeline.accept(task["task_sha256"], native.receipt(task, value))
                self.assertEqual(len(pipeline.reviews), 1)
                before, unit_count = self.retained_files(pipeline.root), native.uid
                reopened = restore()
                with patch("research_workspace_native.stage_pipeline._write") as write:
                    reopened._reopen()
                    write.assert_not_called()
                self.assertEqual(reopened.reviews, pipeline.reviews)
                self.assertEqual(reopened.position, 5)
                self.assertEqual(native.uid, unit_count)
                self.assertEqual(self.retained_files(pipeline.root), before)

    def test_rehashed_mixed_version_pending_intent_remains_rejected(self):
        restore, _ = self.replay_tail("1.2.0")
        pipeline = restore()
        task = pipeline.next_task()
        pipeline.begin_task(task["task_sha256"])
        altered = restore()
        altered.binding["rich_review_view_version"] = "1.3.0"
        bad_task = altered.next_task()
        intent = pipeline.root / "intents" / "0001.json"
        intent.write_text(json.dumps(bad_task), encoding="utf8")
        with self.assertRaisesRegex(Stage2Error, "pipeline-pending-task-differs"):
            restore()._reopen()

    def test_pipeline_new_binding_is_pinned_and_legacy_binding_is_not_upgraded(self):
        native = StagePipelineFixture()
        native.setUp()
        self.addCleanup(native.doCleanups)
        self.assertEqual(native.pipeline.binding["schema_version"], "1.1.0")
        self.assertEqual(native.open().binding["rich_review_view_version"], "1.3.0")
        legacy = copy.deepcopy(native.pipeline.binding)
        legacy["schema_version"] = "1.0.0"
        legacy.pop("rich_review_view_version")
        legacy_root = native.root / "legacy-pipeline"
        legacy_root.mkdir()
        path = legacy_root / "binding.json"
        path.write_text(json.dumps(legacy), encoding="utf8")
        kwargs = {
            "expected_packet_sha256": canonical_hash(native.packet),
            "source_sha256": "a" * 64,
            "verify_receipt": native.verify,
        }
        StagePipeline(native.path, native.sources, legacy_root, **kwargs)
        before = self.retained_files(legacy_root)
        reopened = StagePipeline(native.path, native.sources, legacy_root, **kwargs)
        self.assertEqual(reopened.binding, legacy)
        self.assertEqual(self.retained_files(legacy_root), before)
        legacy["rich_review_view_version"] = "1.3.0"
        path.write_text(json.dumps(legacy), encoding="utf8")
        with self.assertRaisesRegex(Stage2Error, "pipeline-reopen-binding-differs"):
            StagePipeline(native.path, native.sources, legacy_root, **kwargs)


if __name__ == "__main__":
    unittest.main()

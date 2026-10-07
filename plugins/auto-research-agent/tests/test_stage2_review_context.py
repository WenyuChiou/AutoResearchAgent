"""Versioned initial-review context transport; no scientific judgments."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
sys.path.insert(0, str(PLUGIN / "tests"))

from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_live.review_models import (  # noqa: E402
    _common_review_view_version,
    _review_prompt,
    reconciliation_task,
    review_task,
)
from stage2_live import __main__ as live_cli  # noqa: E402
from stage2_live import controller  # noqa: E402
from stage2_workflow.orchestration import prepare_review_batch  # noqa: E402
from stage2_workflow.reviews import (  # noqa: E402
    prepare_review,
    reconcile_reviews,
    validate_review,
)
from stage2_fixture_helpers import write_stage2_fixture  # noqa: E402
from test_stage2_checker import assessment  # noqa: E402


SNAPSHOT = "a" * 64


class Stage2ReviewContextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.packet = write_stage2_fixture(Path(temporary.name), candidate_count=2)
        previous = self.packet["candidates"][0]
        current = copy.deepcopy(previous)
        current.update(
            version=2, parent_version=1, question="Current candidate question"
        )
        self.packet["candidates"].append(current)
        self.current_resource = {
            "resource_id": "optional-current",
            "candidate_id": "candidate-1",
            "candidate_version": 2,
            "category": "dataset",
            "name": "Optional current source",
            "purpose": "Conditional alternative",
            "url": "https://example.test/current",
            "version": None,
            "required": False,
            "status": "unknown",
            "access_conditions": "Lawful workflow unknown",
            "license": None,
            "cost_basis": "Cost unknown",
            "limitations": ["Fitness unknown"],
            "alternatives": ["Use the necessary public route"],
            "evidence_ids": [],
            "checked_at": None,
            "spans": [{"start": 0, "end": 1, "quote": "x"}],
        }
        old = {
            **copy.deepcopy(self.current_resource),
            "resource_id": "old",
            "candidate_version": 1,
        }
        other = {
            **copy.deepcopy(self.current_resource),
            "resource_id": "other",
            "candidate_id": "candidate-2",
            "candidate_version": 1,
        }
        self.packet["research_tables"] = {
            "direction_resources": [old, self.current_resource, other]
        }
        self.packet["assessments"] = [{"peer": "must not leak"}]
        self.packet["scores"] = {"external": 0}

    def review(self, role, version="1.1.0"):
        view = prepare_review(
            self.packet,
            "candidate-1",
            SNAPSHOT,
            role,
            review_view_version=version,
        )
        value = assessment(self.packet)
        value.update(candidate_id="candidate-1", candidate_version=2)
        return {
            "role": role,
            "view_sha256": canonical_hash(view),
            "snapshot_sha256": SNAPSHOT,
            "candidate_id": "candidate-1",
            "candidate_version": 2,
            "assessment": value,
            "session_id": f"session-{role}",
            "native_artifact": {
                "path": f"native/{role}.jsonl",
                "sha256": ("b" if role == "challenger" else "c") * 64,
            },
            "initial": True,
            "assumptions": ["Synthetic test assumption"],
            "strongest_alternative": "Synthetic alternative",
            "change_conditions": ["Synthetic change condition"],
        }

    def screening(self):
        return [
            {
                "candidate_id": candidate_id,
                "candidate_version": version,
                "included": True,
                "distance": 0,
                "reason": "Include for synthetic contract test",
            }
            for candidate_id, version in (("candidate-1", 2), ("candidate-2", 1))
        ]

    def test_legacy_default_is_exact_v1_shape_and_hash(self):
        default = prepare_review(self.packet, "candidate-1", SNAPSHOT, "challenger")
        explicit = prepare_review(
            self.packet,
            "candidate-1",
            SNAPSHOT,
            "challenger",
            review_view_version="1.0.0",
        )
        self.assertEqual(default, explicit)
        self.assertEqual(default["schema_version"], "1.0.0")
        self.assertNotIn("direction_resources", default)
        self.assertNotIn("assessment_contract", default)
        self.assertNotIn("assessments", default)
        self.assertNotIn("scores", default)
        self.assertEqual(
            canonical_hash(default),
            "57e73a539e95e78e725ad99f9da268a6afeb4e4edf448d85d0e3a571fcd26049",
        )

    def test_v11_preserves_only_current_candidate_resource_and_anchors(self):
        view = review_task(
            self.packet,
            "candidate-1",
            SNAPSHOT,
            "challenger",
            review_view_version="1.1.0",
        )
        self.assertEqual(view["direction_resources"], [self.current_resource])
        self.assertIsNot(view["direction_resources"][0], self.current_resource)
        self.assertFalse(view["direction_resources"][0]["required"])
        self.assertEqual(view["direction_resources"][0]["status"], "unknown")
        self.assertEqual(
            view["direction_resources"][0]["access_conditions"],
            "Lawful workflow unknown",
        )
        self.assertIsNone(view["direction_resources"][0]["license"])
        self.assertEqual(view["direction_resources"][0]["cost_basis"], "Cost unknown")
        self.assertEqual(
            view["assessment_contract"]["score_anchors"]["unknown"],
            "Evidence is insufficient to assess the axis; use status unknown and score null.",
        )
        self.assertIn(
            "no alternative exists",
            view["assessment_contract"]["axis_anchors"]["materials"]["0"],
        )
        self.assertIn(
            "Completed experiments",
            view["assessment_contract"]["stage_boundary"],
        )
        self.assertNotIn("assessments", view)
        self.assertNotIn("scores", view)

    def test_saved_v11_shape_survives_future_current_version(self):
        original = prepare_review(
            self.packet,
            "candidate-1",
            SNAPSHOT,
            "challenger",
            review_view_version="1.1.0",
        )
        with mock.patch("stage2_workflow.reviews.REVIEW_VIEW_VERSION_CURRENT", "1.2.0"):
            reconstructed = prepare_review(
                self.packet,
                "candidate-1",
                SNAPSHOT,
                "challenger",
                review_view_version="1.1.0",
            )
        self.assertEqual(reconstructed, original)
        self.assertEqual(canonical_hash(reconstructed), canonical_hash(original))

    def test_v11_rejects_malformed_resource_rows_before_filtering(self):
        self.packet["research_tables"]["direction_resources"].append(
            {"candidate_id": "candidate-2"}
        )
        with self.assertRaisesRegex(
            Stage2Error, "review-direction-resource-row-invalid"
        ):
            prepare_review(
                self.packet,
                "candidate-1",
                SNAPSHOT,
                "challenger",
                review_view_version="1.1.0",
            )

    def test_unknown_score_zero_and_rehashed_resource_tamper_reject(self):
        view = prepare_review(
            self.packet,
            "candidate-1",
            SNAPSHOT,
            "challenger",
            review_view_version="1.1.0",
        )
        row = self.review("challenger")
        row["assessment"]["checks"]["materials"].update(
            status="unknown", score=0, evidence_ids=[], next_check="Check access"
        )
        with self.assertRaisesRegex(Stage2Error, "schema:Stage2Check"):
            validate_review(row, view, self.packet)

        tampered = copy.deepcopy(view)
        tampered["direction_resources"][0]["required"] = True
        row = self.review("challenger")
        row["view_sha256"] = canonical_hash(tampered)
        with self.assertRaisesRegex(Stage2Error, "view-packet-mismatch"):
            validate_review(row, tampered, self.packet)

    def test_batch_and_reconciliation_bind_one_recognized_version(self):
        legacy = prepare_review_batch(self.packet, SNAPSHOT, self.screening(), "seed")
        current = prepare_review_batch(
            self.packet,
            SNAPSHOT,
            self.screening(),
            "seed",
            review_view_version="1.1.0",
        )
        self.assertEqual(legacy["schema_version"], "1.0.0")
        self.assertEqual(current["schema_version"], "1.1.0")
        self.assertTrue(
            all(
                row["view"]["schema_version"] == "1.1.0"
                for row in current["assignments"]
            )
        )
        reviews = [self.review(role) for role in ("challenger", "feasibility")]
        task = reconciliation_task(
            self.packet,
            "candidate-1",
            SNAPSHOT,
            reviews,
            review_view_version="1.1.0",
        )
        self.assertEqual(task["schema_version"], "1.1.0")
        self.assertEqual(
            _common_review_view_version(self.packet, "candidate-1", SNAPSHOT, reviews),
            "1.1.0",
        )
        mixed = [reviews[0], self.review("feasibility", "1.0.0")]
        with self.assertRaisesRegex(Stage2Error, "mixed-review-view-versions"):
            _common_review_view_version(self.packet, "candidate-1", SNAPSHOT, mixed)
        with self.assertRaisesRegex(Stage2Error, "review-view-mismatch"):
            reconcile_reviews(
                self.packet,
                "candidate-1",
                SNAPSHOT,
                mixed,
                review_view_version="1.1.0",
            )

    def test_v11_extractor_prompt_carries_contract_without_rewriting_science(self):
        view = prepare_review(
            self.packet,
            "candidate-1",
            SNAPSHOT,
            "challenger",
            review_view_version="1.1.0",
        )
        raw = "The saved reviewer explicitly reports an evidenced failure on one axis."
        prompt = _review_prompt(view, raw)
        self.assertIn("score 0 requires an evidenced failure", prompt)
        self.assertIn(
            "unverified enabling prerequisites remain unknown with score null", prompt
        )
        self.assertIn("Do not silently change an unambiguous evidenced score 0", prompt)
        self.assertIn(raw, prompt)

    def test_production_adapter_and_cli_propagate_explicit_version(self):
        view = prepare_review(
            self.packet,
            "candidate-1",
            SNAPSHOT,
            "challenger",
            review_view_version="1.1.0",
        )
        context = {
            "packet": self.packet,
            "source_root": "unused",
            "candidate_id": "candidate-1",
            "snapshot_sha256": SNAPSHOT,
            "role": "challenger",
            "view": view,
            "paths": {},
            "extractor_home": "extractor",
            "spec": {
                "native": {
                    "codex": "codex",
                    "model": "model",
                    "reasoning": "medium",
                    "extraction_policy": {},
                }
            },
            "output": Path("synthetic-output"),
        }
        with (
            mock.patch.object(
                controller._ProductionAdapter,
                "_capture",
                return_value={"record_sha256_receipt": "a" * 64},
            ),
            mock.patch.object(
                controller, "extract_review", return_value={"synthetic": True}
            ) as extract,
        ):
            controller._ProductionAdapter().review(context)
        self.assertEqual(extract.call_args.kwargs["review_view_version"], "1.1.0")

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name) / "view.json"
        with (
            mock.patch.object(live_cli, "_read", return_value=self.packet),
            mock.patch.object(live_cli, "validate_packet"),
            mock.patch.object(
                live_cli, "review_task", return_value={"ok": True}
            ) as task,
        ):
            status = live_cli.main(
                [
                    "review-task",
                    "--packet",
                    "packet.json",
                    "--source-root",
                    "sources",
                    "--candidate",
                    "candidate-1",
                    "--snapshot-sha256",
                    SNAPSHOT,
                    "--role",
                    "challenger",
                    "--review-view-version",
                    "1.1.0",
                    "--output",
                    str(output),
                ]
            )
        self.assertEqual(status, 0)
        self.assertEqual(task.call_args.kwargs["review_view_version"], "1.1.0")


if __name__ == "__main__":
    unittest.main()

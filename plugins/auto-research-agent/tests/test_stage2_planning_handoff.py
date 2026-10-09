"""Synthetic planning-handoff tests; no record authenticates an actual person."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]
from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_workflow import initialize_workflow, inspect_workflow  # noqa: E402
from stage2_workflow.delivery import build_delivery  # noqa: E402
from stage2_workflow.interaction import record_interaction  # noqa: E402
from stage2_workflow.orchestration import prepare_review_batch  # noqa: E402
from stage2_workflow.planning_handoff import (  # noqa: E402
    inspect_planning_handoff,
    prepare_planning_handoff,
)
from stage2_workflow.reviews import prepare_review  # noqa: E402
import test_stage2_delivery as delivery_tests  # noqa: E402
import test_stage2_prior_work_delivery as prior_fixture  # noqa: E402
from test_stage2_checker import assessment  # noqa: E402


class Stage2PlanningHandoffTests(unittest.TestCase):
    def setUp(self):
        fixture = delivery_tests.Stage2DeliveryTests(
            "test_full_cycle_binds_package_and_preserves_embedded_checker"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.delivery = fixture.root / "delivery"
        reviews, resolutions = fixture._complete_inputs()
        self.delivery_manifest = fixture._build(self.delivery, reviews, resolutions)
        self.interaction, self.decision, self.interaction_sha = self._record_choice(
            fixture.root,
            fixture.workflow,
            self.delivery,
            self.delivery_manifest,
            fixture.state,
            fixture.packet["candidates"][0],
        )
        self.output = fixture.root / "planning-package"

    @staticmethod
    def _record_choice(root, workflow, delivery, manifest, state, candidate):
        quote = f"Select {candidate['candidate_id']} version {candidate['version']} for synthetic planning."
        message = root / "selected-message.jsonl"
        message.write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": quote},
                }
            ),
            encoding="utf-8",
        )
        decision = {
            "actor": "synthetic-user",
            "kind": "select",
            "user_text": quote,
            "selected": [
                {
                    "candidate_id": candidate["candidate_id"],
                    "candidate_version": candidate["version"],
                }
            ],
            "conditions": ["Keep the recorded resource bounds."],
            "unresolved": ["Preserve unknown access conditions."],
            "rationale": "The synthetic fixture records a planning choice.",
            "scope_or_resource_change": False,
        }
        interaction = root / "planning-interaction"
        record_interaction(
            workflow,
            delivery,
            manifest["manifest_sha256"],
            decision,
            message,
            0,
            "planning-choice",
            interaction,
            state["head_sha256"],
        )
        digest = hashlib.sha256(
            (interaction / "interaction.json").read_bytes()
        ).hexdigest()
        return interaction, decision, digest

    def prepare(self):
        return prepare_planning_handoff(
            self.delivery,
            self.interaction,
            expected_delivery_manifest_sha256=self.delivery_manifest["manifest_sha256"],
            expected_interaction_file_sha256=self.interaction_sha,
            output_dir=self.output,
        )

    @staticmethod
    def _refresh_package_manifest(root):
        path = root / "planning_manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for row in manifest["files"]:
            data = (root / row["path"]).read_bytes()
            row.update(sha256=hashlib.sha256(data).hexdigest(), size=len(data))
        manifest["manifest_sha256"] = canonical_hash(
            {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        )
        path.write_text(
            json.dumps(
                manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
            encoding="utf-8",
        )
        return manifest["manifest_sha256"]

    def test_legacy_package_is_explicit_about_unknown_context_and_no_authority(self):
        result = self.prepare()
        handoff = result["handoff"]
        self.assertEqual(handoff["evaluation_packet"], self.fixture.packet)
        self.assertEqual(
            handoff["selected_direction_resources"],
            {"status": "unknown-not-recorded", "rows": []},
        )
        self.assertEqual(
            handoff["selected_prior_work_reviews"],
            {"status": "unknown-not-recorded", "rows": []},
        )
        self.assertEqual(handoff["decision"]["rationale"], self.decision["rationale"])
        self.assertFalse(handoff["execution_authorized"])
        source = handoff["evaluation_packet"]["sources"][0]
        source_base = self.delivery / handoff["source_base_in_required_delivery"]
        self.assertTrue((source_base / source["path"]).is_file())
        for name in ("interaction.json", "native-user-message.jsonl"):
            self.assertEqual(
                (self.output / name).read_bytes(),
                (self.interaction / name).read_bytes(),
            )

    def test_rich_roundtrip_retains_and_revalidates_planning_context(self):
        fixture = prior_fixture.Stage2PriorWorkDeliveryTests(
            "test_markdown_html_and_wiki_share_bound_review_and_limits"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        packet_path = fixture.root / "packet-2.4.json"
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        packet["prior_work_reviews"][0]["searches"] = [
            {
                "search_id": "planned-stage3-context",
                "need": "Retain the bounded need for later planning.",
                "query": "synthetic future bounded query",
                "status": "planned",
                "tool_ref": None,
                "raw_path": None,
                "raw_sha256": None,
                "outcome": "unknown",
                "work_refs": [],
            }
        ]
        packet_path = fixture.root / "planning-packet-2.4.json"
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        candidate = next(
            row
            for row in packet["candidates"]
            if row["candidate_id"] == fixture.candidate["candidate_id"]
            and row["version"] == fixture.candidate["version"]
        )
        workflow = fixture.root / "planning-workflow"
        initialize_workflow(
            packet_path,
            fixture.sources,
            workflow,
            {"model": "synthetic-review-model", "reasoning": "medium"},
            {"path": "policy.json", "sha256": "a" * 64},
            canonical_hash(packet),
        )
        state = inspect_workflow(workflow)
        snapshot = state["latest_snapshot"]["event"]["payload"]["snapshot_sha256"]
        screening = [
            {
                "candidate_id": candidate["candidate_id"],
                "candidate_version": candidate["version"],
                "included": True,
                "distance": 0,
                "reason": "The synthetic screening retains this current candidate.",
            }
        ]
        batch = prepare_review_batch(packet, snapshot, screening, "rich-handoff-seed")
        value = assessment(packet)
        value.update(
            candidate_id=candidate["candidate_id"],
            candidate_version=candidate["version"],
        )
        for finding in value["checks"].values():
            finding["evidence_ids"] = [fixture.evidence["evidence_id"]]
        reviews = []
        for role in ("challenger", "feasibility"):
            view = prepare_review(packet, candidate["candidate_id"], snapshot, role)
            review = {
                "role": role,
                "view_sha256": canonical_hash(view),
                "snapshot_sha256": snapshot,
                "candidate_id": candidate["candidate_id"],
                "candidate_version": candidate["version"],
                "assessment": copy.deepcopy(value),
                "session_id": f"synthetic-{role}",
                "native_artifact": {
                    "path": f"native/{role}.jsonl",
                    "sha256": canonical_hash([role]),
                },
                "initial": True,
                "assumptions": ["The recorded source bounds remain applicable."],
                "strongest_alternative": "The bounded source may not generalize.",
                "change_conditions": ["A source mismatch changes the judgment."],
            }
            reviews.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "candidate_version": candidate["version"],
                    "role": role,
                    "status": "complete",
                    "review": review,
                    "error": None,
                }
            )
        resolution = {
            "candidate_resolutions": [
                {
                    "candidate_id": candidate["candidate_id"],
                    "resolution": {
                        "review_sha256s": [
                            canonical_hash(row["review"]) for row in reviews
                        ],
                        "method": "synthesis",
                        "reason": "The synthetic reviews support bounded detailed planning.",
                        "evidence_ids": [fixture.evidence["evidence_id"]],
                        "addressed": [],
                        "assessment": value,
                        "substantive_disagreements": [],
                        "changed_judgment_reason": None,
                    },
                }
            ],
            "next_step": None,
        }
        delivery = fixture.root / "rich-delivery"
        manifest = build_delivery(
            workflow, batch, reviews, resolution, delivery, state["head_sha256"]
        )
        interaction, _, interaction_hash = self._record_choice(
            fixture.root,
            workflow,
            delivery,
            manifest,
            state,
            candidate,
        )
        output = fixture.root / "rich-package"
        result = prepare_planning_handoff(
            delivery,
            interaction,
            expected_delivery_manifest_sha256=manifest["manifest_sha256"],
            expected_interaction_file_sha256=interaction_hash,
            output_dir=output,
        )
        handoff = result["handoff"]
        self.assertEqual(handoff["evaluation_packet"], packet)
        self.assertEqual(handoff["research_tables"]["value"], packet["research_tables"])
        self.assertEqual(
            handoff["selected_direction_resources"]["rows"],
            packet["research_tables"]["direction_resources"],
        )
        self.assertEqual(
            handoff["selected_prior_work_reviews"]["rows"],
            packet["prior_work_reviews"],
        )
        path = output / "planning_handoff.json"
        changed = json.loads(path.read_text(encoding="utf-8"))
        changed["selected_direction_resources"]["rows"] = []
        changed["selected_prior_work_reviews"]["rows"] = []
        path.write_text(json.dumps(changed), encoding="utf-8")
        expected = self._refresh_package_manifest(output)
        with self.assertRaisesRegex(Stage2Error, "handoff-projection-mismatch"):
            inspect_planning_handoff(
                output, delivery, expected_manifest_sha256=expected
            )

    def test_wrong_retained_hash_or_native_message_is_rejected(self):
        with self.assertRaisesRegex(Stage2Error, "interaction-receipt-mismatch"):
            prepare_planning_handoff(
                self.delivery,
                self.interaction,
                expected_delivery_manifest_sha256=self.delivery_manifest[
                    "manifest_sha256"
                ],
                expected_interaction_file_sha256="0" * 64,
                output_dir=self.output,
            )
        native = self.interaction / "native-user-message.jsonl"
        native.write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "Different text"},
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(Stage2Error, "human-quote-mismatch"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_no_selection_and_foreign_selected_version_are_rejected(self):
        record_path = self.interaction / "interaction.json"
        original = json.loads(record_path.read_text(encoding="utf-8"))
        for mutate, reason in (
            (
                lambda value: value.update(
                    decision={
                        **value["decision"],
                        "kind": "clarify",
                        "selected": [],
                    },
                    human_selection="pending",
                    requires_new_report=True,
                    handoff=None,
                ),
                "selection-required",
            ),
            (
                lambda value: value["decision"]["selected"][0].update(
                    candidate_version=99
                ),
                "not-current-recommendation",
            ),
            (lambda value: value.update(schema_version="9.0.0"), "interaction-version"),
        ):
            value = copy.deepcopy(original)
            mutate(value)
            value["record_sha256"] = canonical_hash(
                {key: item for key, item in value.items() if key != "record_sha256"}
            )
            record_path.write_text(json.dumps(value), encoding="utf-8")
            self.interaction_sha = hashlib.sha256(record_path.read_bytes()).hexdigest()
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(Stage2Error, reason):
                    self.prepare()
            record_path.write_text(json.dumps(original), encoding="utf-8")

    def test_receiver_recomputes_projection_after_internal_rehash(self):
        result = self.prepare()
        handoff_path = self.output / "planning_handoff.json"
        handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
        for replacement in (True, 0):
            handoff["execution_authorized"] = replacement
            handoff_path.write_text(json.dumps(handoff), encoding="utf-8")
            refreshed = self._refresh_package_manifest(self.output)
            with (
                self.subTest(replacement=replacement),
                self.assertRaisesRegex(Stage2Error, "handoff-projection-mismatch"),
            ):
                inspect_planning_handoff(
                    self.output, self.delivery, expected_manifest_sha256=refreshed
                )
        self.assertFalse(result["handoff"]["execution_authorized"])


if __name__ == "__main__":
    unittest.main()

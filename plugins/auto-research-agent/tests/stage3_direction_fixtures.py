"""A shared sealed Stage2 2.5 fixture; no models, scores or research are run."""

from copy import deepcopy

from stage2_common import canonical_hash
from stage2_workflow import initialize_workflow, inspect_workflow
from stage2_workflow.advisory_handoff import prepare_advisory_handoff
from stage2_workflow.orchestration import prepare_review_batch
from stage2_workflow.reviews import prepare_review
from stage3_plan.contracts import canonical_bytes, digest
from stage3_plan.direction_intent import admit_direction_intent
from test_stage2_checker import assessment
import test_stage2_delivery as delivery_fixture
import test_stage2_scientific_argument as scientific_fixture


class DirectionFixture:
    def __init__(self, add_cleanup):
        fixture = delivery_fixture.Stage2DeliveryTests(
            "test_full_cycle_binds_package_and_preserves_embedded_checker"
        )
        fixture.setUp()
        fixture.root = fixture.root.resolve()
        add_cleanup(fixture.doCleanups)
        self.fixture = fixture
        scientific = scientific_fixture.Stage2ScientificArgumentTests(
            "test_packet_2_5_is_opt_in_and_requires_a_core_closed_argument"
        )
        scientific.setUp()
        add_cleanup(scientific.doCleanups)
        packet = deepcopy(scientific.packet)
        packet["unresolved"].append(
            "Packet-only access condition, distinct from user text."
        )
        fixture.packet = packet
        fixture.sources = scientific.fixture.source_root
        candidate = packet["candidates"][0]
        candidate["scientific_argument"]["questions"][0]["text"] = (
            "How do participants explain the recorded process?"
        )
        for review in packet["prior_work_reviews"]:
            if review["candidate_id"] == candidate["candidate_id"]:
                review["candidate_sha256"] = canonical_hash(candidate)
        fixture.packet_path.write_bytes(canonical_bytes(packet))
        fixture.workflow = fixture.root / "structured-workflow"
        initialize_workflow(
            fixture.packet_path,
            fixture.sources,
            fixture.workflow,
            {"model": "stub-review", "reasoning": "medium"},
            {"path": "policy.json", "sha256": "a" * 64},
            expected_packet_sha256=canonical_hash(packet),
        )
        fixture.state = inspect_workflow(fixture.workflow)
        fixture.snapshot = fixture.state["latest_snapshot"]["event"]["payload"][
            "snapshot_sha256"
        ]
        fixture.batch = prepare_review_batch(
            packet,
            fixture.snapshot,
            [
                {
                    "candidate_id": candidate["candidate_id"],
                    "candidate_version": 1,
                    "included": True,
                    "distance": 0,
                    "reason": "Retain this synthetic direction.",
                }
            ],
            "stub-seed",
        )
        value = assessment(packet, disposition="park")
        value["candidate_id"] = candidate["candidate_id"]
        for finding in value["checks"].values():
            finding["evidence_ids"] = [packet["evidence"][0]["evidence_id"]]
        value["checks"]["materials"].update(
            status="unknown",
            score=None,
            evidence_ids=[],
            blocking=True,
            rationale="Lawful access remains unknown.",
            next_check="Check the access documentation.",
        )

        def review(role, finding):
            view = prepare_review(
                packet, candidate["candidate_id"], fixture.snapshot, role
            )
            content = {
                "role": role,
                "view_sha256": digest(view),
                "snapshot_sha256": fixture.snapshot,
                "candidate_id": candidate["candidate_id"],
                "candidate_version": candidate["version"],
                "assessment": deepcopy(finding),
                "session_id": "stub-" + role,
                "native_artifact": {
                    "path": "stub/" + role + ".jsonl",
                    "sha256": digest(role),
                },
                "initial": True,
                "assumptions": ["Authored offline fixture."],
                "strongest_alternative": "Measurement mismatch.",
                "change_conditions": ["New evidence."],
            }
            return {
                "candidate_id": candidate["candidate_id"],
                "candidate_version": candidate["version"],
                "role": role,
                "status": "complete",
                "review": content,
                "error": None,
            }

        fixture._review = review
        reviews, resolutions = fixture._complete_inputs(value)
        resolutions["candidate_resolutions"][0]["candidate_id"] = candidate[
            "candidate_id"
        ]
        resolutions["candidate_resolutions"][0]["resolution"]["evidence_ids"] = [
            packet["evidence"][0]["evidence_id"]
        ]
        self.delivery = fixture.root / "direction-delivery"
        self.manifest = fixture._build(self.delivery, reviews, resolutions)
        self.advisory = fixture.root / "direction-advisory"
        prepared = prepare_advisory_handoff(
            self.delivery,
            expected_delivery_manifest_sha256=self.manifest["manifest_sha256"],
            output_dir=self.advisory,
        )
        self.intent = {
            "kind": "Stage2DirectionPlanningIntent",
            "schema_version": "1.0.0",
            "mode": "direction-advice",
            "key": "original-ui-key",
            "project_ref": "project-direction",
            "project_id": "project-direction-id",
            "input_version": 1,
            "brief_sha256": "b" * 64,
            "base_revision": 0,
            "request_sha256": "c" * 64,
            "submission_sha256": "d" * 64,
            "received_at": "2026-10-28T00:00:00Z",
            "principal": "fixture-principal",
            "delivery_manifest_sha256": self.manifest["manifest_sha256"],
            "workflow_manifest_sha256": self.manifest["workflow_manifest_sha256"],
            "workflow_head_sha256": self.manifest["workflow_head_sha256"],
            "snapshot_sha256": self.manifest["snapshot_sha256"],
            "preferred_directions": [
                {"candidate_id": candidate["candidate_id"], "candidate_version": 1}
            ],
            "user_input": "Please plan this qualitative direction; preserve access unknowns.",
            "conditions": ["Keep the original scientific question."],
            "unresolved": ["Material permission is unknown."],
            "advisory_manifest_sha256": prepared["manifest"]["manifest_sha256"],
            "selected_options": [],
            "human_selection": "pending",
            "input_origin": "projecthost-ui-submission",
            "identity_authenticated": False,
            "execution_authorized": False,
        }

    def source(self, intent=None):
        value = deepcopy(self.intent if intent is None else intent)
        return {
            "intent": value,
            "intent_sha256": digest(value),
            "advisory_dir": str(self.advisory.resolve()),
            "advisory_manifest_sha256": value["advisory_manifest_sha256"],
            "delivery_dir": str(self.delivery.resolve()),
            "delivery_manifest_sha256": self.manifest["manifest_sha256"],
        }

    def admit(self, source):
        return admit_direction_intent(
            source["intent"],
            source["advisory_dir"],
            source["delivery_dir"],
            expected_intent_sha256=source["intent_sha256"],
            expected_advisory_manifest_sha256=source["advisory_manifest_sha256"],
            expected_delivery_manifest_sha256=source["delivery_manifest_sha256"],
        )

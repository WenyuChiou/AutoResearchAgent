"""Synthetic public save/context/HTTP paths; zero models and no real selection."""

# ruff: noqa: E402 -- repository fixture imports.
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "cli"), str(HERE)]
from project_stage2_selection_fixture import Stage2SelectionFixture
import test_project_stage2_selection_http as http_fixture
import test_stage2_delivery as delivery_fixture
from test_stage2_delivery import _tree_hash
from test_stage2_checker import assessment, finding
from research_workspace_native.project_stage2_selection import (
    ProjectStage2SelectionService,
)
from research_workspace_native.session_api import SessionApiError
import stage2_workflow.direction_intent as core


def intent_body(body):
    body = deepcopy(body)
    decision = body.pop("decision")
    body.update(
        preferred_directions=[{"candidate_id": "candidate-1", "candidate_version": 1}],
        user_input=decision["user_text"],
        conditions=decision["conditions"],
        unresolved=decision["unresolved"],
    )
    return body


class DirectionIntentTests(Stage2SelectionFixture):
    def choice(self, *, parked=False):
        if parked:
            original = delivery_fixture.Stage2DeliveryTests._complete_inputs

            def parked_inputs(fixture, value=None):
                value = assessment(fixture.packet, disposition="park")
                value["checks"]["materials"] = finding("unknown", None, blocking=True)
                return original(fixture, value)

            with patch.object(
                delivery_fixture.Stage2DeliveryTests, "_complete_inputs", parked_inputs
            ):
                result = self.prepare_choice(ProjectStage2SelectionService)
        else:
            result = self.prepare_choice(ProjectStage2SelectionService)
        return result[0], intent_body(result[1]), result[2]

    def test_zero_recommendations_can_save_preference_without_selection_or_source_write(
        self,
    ):
        service, body, workflow = self.choice(parked=True)
        self.assertEqual(service.read("own", self.ref)["eligible"], [])
        before = _tree_hash(workflow)
        binding = service.bindings[self.ref]
        source = _tree_hash(Path(binding["delivery_root"]))
        first = service.direction_intent("own", self.ref, body)
        self.assertEqual(first["status"], "saved")
        self.assertFalse(first["execution_authorized"])
        view = service.read("own", self.ref)
        self.assertEqual(view["selection_status"], "pending")
        self.assertIsNone(view["planning_input"])
        self.assertEqual(
            view["direction_intent"]["intent_sha256"], first["intent_sha256"]
        )
        context = service.direction_intent_context(
            "own", self.ref, expected_intent_sha256=first["intent_sha256"]
        )
        intent = context["intent"]
        self.assertEqual(intent["preferred_directions"], body["preferred_directions"])
        self.assertEqual(intent["unresolved"], body["unresolved"])
        self.assertEqual(intent["selected_options"], [])
        self.assertEqual(intent["human_selection"], "pending")
        self.assertFalse(intent["identity_authenticated"])
        self.assertEqual(_tree_hash(workflow), before)
        self.assertEqual(_tree_hash(Path(binding["delivery_root"])), source)

    def test_original_key_replay_preserves_all_artifact_bytes_and_no_recompilation(
        self,
    ):
        service, body, _ = self.choice()
        first = service.direction_intent("own", self.ref, body)
        output = self.intake._path(self.ref, first["artifact_ref"])
        before = {
            p.relative_to(output).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in output.rglob("*")
            if p.is_file()
        }
        with patch.object(
            core, "prepare_advisory_handoff", side_effect=AssertionError("recompiled")
        ):
            second = service.direction_intent("own", self.ref, body)
        self.assertTrue(second["replayed"])
        self.assertEqual(second["intent_sha256"], first["intent_sha256"])
        self.assertEqual(
            before,
            {
                p.relative_to(output).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in output.rglob("*")
                if p.is_file()
            },
        )
        with self.assertRaisesRegex(SessionApiError, "payload-differs"):
            service.direction_intent(
                "own", self.ref, dict(body, user_input="different")
            )

    def test_changed_source_version_duplicate_and_foreign_preferences_reject(self):
        service, body, _ = self.choice()
        for field in (
            "delivery_manifest_sha256",
            "workflow_head_sha256",
            "snapshot_sha256",
        ):
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(SessionApiError, "view-stale"),
            ):
                service.direction_intent(
                    "own", self.ref, dict(body, **{field: "0" * 64})
                )
        for preferences in (
            [],
            body["preferred_directions"] * 2,
            [{"candidate_id": "foreign", "candidate_version": 1}],
            [{"candidate_id": "candidate-1", "candidate_version": True}],
        ):
            with (
                self.subTest(preferences=preferences),
                self.assertRaises(SessionApiError),
            ):
                service.direction_intent(
                    "own", self.ref, dict(body, preferred_directions=preferences)
                )
        with self.assertRaises(SessionApiError):
            service.direction_intent("other", self.ref, body)

    def test_partial_files_recover_with_original_key_preserving_written_bytes_and_failure(
        self,
    ):
        service, body, _ = self.choice()
        original = core._retain

        def interrupted(path, raw):
            if path.name == "intent.json":
                raise OSError("synthetic interruption before final seal")
            return original(path, raw)

        with (
            patch.object(core, "_retain", side_effect=interrupted),
            self.assertRaises(SessionApiError),
        ):
            service.direction_intent("own", self.ref, body)
        state = self.intake._load("researcher", self.ref)
        pending = state["stage2_direction_intent_pending"]
        output = self.intake._path(
            self.ref, "stage2-direction-" + pending["request_sha256"]
        )
        original_bytes = (output / "submission.json").read_bytes()
        with self.assertRaisesRegex(SessionApiError, "needs-recovery"):
            service.direction_intent(
                "own",
                self.ref,
                dict(body, key="replacement-key", revision=state["revision"]),
            )
        result = service.direction_intent("own", self.ref, body)
        self.assertEqual(result["status"], "saved")
        self.assertIn("recovered_from_receipt_sha256", result)
        self.assertEqual((output / "submission.json").read_bytes(), original_bytes)
        failures = self.intake.db.execute(
            "SELECT payload FROM intake_events WHERE project=? AND kind=?",
            (self.ref, "stage2-direction-intent-failed"),
        ).fetchall()
        self.assertEqual(len(failures), 1)
        self.assertIn("synthetic interruption", failures[0][0])

    def test_post_work_commit_interruption_recovers_without_rewriting_seal(self):
        service, body, _ = self.choice()
        done = False
        original = service._retain_direction

        def observed(*args):
            nonlocal done
            result = original(*args)
            done = True
            return result

        def deadline():
            if done:
                raise TimeoutError("synthetic post-work interruption")

        with (
            patch.object(service, "_retain_direction", side_effect=observed),
            self.assertRaises(SessionApiError),
        ):
            service.direction_intent("own", self.ref, body, check_deadline=deadline)
        result = service.direction_intent("own", self.ref, body)
        self.assertEqual(result["status"], "saved")
        self.assertTrue(result["replayed"])

    def test_tamper_extra_file_and_wrong_external_pin_reject(self):
        service, body, _ = self.choice()
        result = service.direction_intent("own", self.ref, body)
        with self.assertRaisesRegex(SessionApiError, "not-current"):
            service.direction_intent_context(
                "own", self.ref, expected_intent_sha256="0" * 64
            )
        output = self.intake._path(self.ref, result["artifact_ref"])
        (output / "extra.json").write_text("{}")
        with self.assertRaisesRegex(SessionApiError, "retained-input-invalid"):
            service.read("own", self.ref)
        (output / "extra.json").unlink()
        (output / "intent.json").write_text("{}")
        with self.assertRaisesRegex(SessionApiError, "retained-input-invalid"):
            service.read("own", self.ref)


class DirectionIntentHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        http_fixture.ProjectSelectionTests.setUpClass()

    def setUp(self):
        self.fixture = http_fixture.ProjectSelectionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_http_direction_endpoint_preserves_formal_route_and_auth_boundaries(self):
        f = self.fixture
        path = "/api/projects/" + f.ref + "/stage2/direction-intent"
        body = intent_body(f.selection_body())
        status, raw, _ = f.request(path, body)
        self.assertEqual(status, 200, raw)
        receipt = json.loads(raw)
        self.assertEqual(receipt["status"], "saved")
        status, raw, _ = f.request(path, body)
        self.assertEqual(status, 200, raw)
        self.assertTrue(json.loads(raw)["replayed"])
        status, _, _ = f.request(path, body, token="invalid")
        self.assertEqual(status, 401)
        status, _, _ = f.request(path, body, origin="https://untrusted.example")
        self.assertEqual(status, 403)
        status, _, _ = f.request(
            "/api/projects/foreign-project/stage2/direction-intent", body
        )
        self.assertNotEqual(status, 200)


if __name__ == "__main__":
    unittest.main()

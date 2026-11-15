"""Negative trust-boundary checks; real Host/browser coverage is separate."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.project_completion import (
    CompletionIdentity,
    completion_event_adapter,
    inspect_project_completion,
)
from research_workspace_native.session_api import SessionApiError


class ProjectCompletionTests(unittest.TestCase):
    def setUp(self):
        self.identity = CompletionIdentity(
            "task",
            "source-version",
            "isolated-host",
            "operation",
            "project-one",
            "input-v1",
            "a" * 64,
            "b" * 64,
            "c" * 64,
        )
        self.request = dict(
            key="planning-original-key",
            request_sha256="d" * 64,
            selection_request_sha256="b" * 64,
        )
        self.view = dict(
            project_ref="project-one",
            input_version="input-v1",
            delivery_manifest_sha256="a" * 64,
            selection_receipt=dict(request_sha256="b" * 64),
            selection_status="recorded",
            planning_status="verified",
            execution_authorized=False,
            input_origin="projecthost-ui-submission",
        )
        self.job = dict(
            project_ref="project-one",
            key="planning-original-key",
            request_sha256="d" * 64,
            status="completed",
            outcome="saved",
            plan_manifest_sha256="c" * 64,
            execution_authorized=False,
        )
        intake = SimpleNamespace(_lock=threading.RLock())
        self.selection = SimpleNamespace(
            intake=intake, read=Mock(side_effect=lambda *a: deepcopy(self.view))
        )
        self.planning = SimpleNamespace(
            intake=intake, inspect=Mock(side_effect=lambda *a: deepcopy(self.job))
        )
        self.contract = dict(
            task_id="task",
            version="source-version",
            environment="isolated-host",
            operation_id="operation",
        )
        self.observed = dict(
            phase="action",
            target="wiki-original-selection-submit",
            mechanism="click",
            origin="automation",
            result="passed",
            project_ref="project-one",
            operation_id="operation",
            submission_request_sha256="b" * 64,
            input_version="input-v1",
            planning_key="planning-original-key",
            planning_request_sha256="d" * 64,
            plan_manifest_sha256="c" * 64,
        )
        self.requirement = {
            k: self.observed[k] for k in ("phase", "target", "mechanism", "origin")
        }

    def inspect(self, identity=None):
        return inspect_project_completion(
            self.selection,
            self.planning,
            "credential",
            identity or self.identity,
            self.request,
        )

    def adapter(self, observed=None):
        return completion_event_adapter(
            self.selection,
            self.planning,
            "credential",
            self.identity,
            self.request,
            event_factory=lambda **kw: kw,
            observed_events={"action": self.observed if observed is None else observed},
        )

    def test_current_server_records_are_read_again_without_dispatch(self):
        event = self.inspect()
        result = self.adapter()(event, self.requirement, self.contract)
        self.assertEqual(result["result"], "passed")
        self.assertEqual(self.selection.read.call_count, 2)
        self.assertEqual(self.planning.inspect.call_count, 2)
        self.assertFalse(event["human_acceptance_verified"])
        self.assertFalse(event["execution_authorized"])

    def test_wrong_project_input_type_and_delivery_pin_are_rejected(self):
        for identity in (
            replace(self.identity, project_ref="another-project"),
            replace(self.identity, input_version=1),
            replace(self.identity, delivery_manifest_sha256="e" * 64),
        ):
            with self.subTest(identity=identity), self.assertRaises(SessionApiError):
                self.inspect(identity)
        self.planning.inspect.assert_not_called()

    def test_missing_or_other_submission_does_not_complete(self):
        for receipt in (None, {"request_sha256": "f" * 64}):
            self.view["selection_receipt"] = receipt
            with self.assertRaises(SessionApiError):
                self.inspect()
        self.planning.inspect.assert_not_called()

    def test_incomplete_failed_or_changed_plan_never_completes(self):
        original = deepcopy(self.job)
        for field, value in (
            ("status", "pending"),
            ("outcome", "failed"),
            ("plan_manifest_sha256", "e" * 64),
            ("request_sha256", "f" * 64),
            ("execution_authorized", True),
        ):
            self.job = dict(original, **{field: value})
            with self.subTest(field=field), self.assertRaises(SessionApiError):
                self.inspect()

    def test_direction_advice_cannot_be_promoted_to_formal_receiver(self):
        self.view.update(
            selection_status="pending",
            selection_receipt=None,
            direction_intent=dict(
                request_sha256="b" * 64, status="saved", intent_sha256="e" * 64
            ),
        )
        self.request.pop("selection_request_sha256")
        self.request.update(mode="direction-intent", direction_intent_sha256="e" * 64)
        result = self.inspect()
        self.assertEqual(result["planning_mode"], "direction-intent")
        self.assertFalse(result["formal_selected_receiver"])

    def test_event_json_cannot_replace_observer_or_host_evidence(self):
        event = self.inspect()
        for field, value in (
            ("plan_manifest_sha256", "e" * 64),
            ("identity_authenticated", True),
        ):
            with self.subTest(field=field), self.assertRaises(SessionApiError):
                self.adapter()(
                    dict(event, **{field: value}), self.requirement, self.contract
                )
        with self.assertRaises(SessionApiError):
            self.adapter({})(event, self.requirement, self.contract)

    def test_api_other_button_cross_operation_and_human_labels_are_rejected(self):
        event = self.inspect()
        for field, value in (
            ("mechanism", "api"),
            ("target", "another-button"),
            ("operation_id", "another-operation"),
            ("origin", "real_user"),
        ):
            observed = dict(self.observed, **{field: value})
            with self.subTest(field=field), self.assertRaises(SessionApiError):
                self.adapter(observed)(event, self.requirement, self.contract)

    def test_original_host_validation_failures_propagate(self):
        self.planning.inspect.side_effect = SessionApiError("saved-package-tampered")
        with self.assertRaisesRegex(SessionApiError, "saved-package-tampered"):
            self.inspect()

    def test_other_saved_plan_under_same_selection_cannot_reuse_observation(self):
        event = self.inspect()
        for field, value in (
            ("planning_key", "another-saved-job"),
            ("planning_request_sha256", "e" * 64),
            ("plan_manifest_sha256", "f" * 64),
            ("input_version", 1),
        ):
            with self.subTest(field=field), self.assertRaises(SessionApiError):
                self.adapter(dict(self.observed, **{field: value}))(
                    event, self.requirement, self.contract
                )


if __name__ == "__main__":
    unittest.main()

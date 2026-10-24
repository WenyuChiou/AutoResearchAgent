"""Trusted Host attachment and replay; no live executor or authority is supplied."""

# ruff: noqa: E402 -- repository CLI and deterministic authored fixtures.
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).parent),
]

import test_project_stage2 as fixture
import test_project_stage2_controller as driver_fixture
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.session_api import SessionApiError


class HostStage2ControllerTests(unittest.TestCase):
    body = driver_fixture.ProjectStage2ControllerTests.body
    driver = driver_fixture.ProjectStage2ControllerTests.driver
    core = driver_fixture.ProjectStage2ControllerTests.core

    @classmethod
    def setUpClass(cls):
        driver_fixture.ProjectStage2ControllerTests.setUpClass.__func__(cls)

    def setUp(self):
        self.token = "synthetic-host-" + "x" * 32
        original = fixture.ProjectIntakeService

        def local_store(root, *, authenticate):
            return original(
                root,
                authenticate=lambda key: (
                    "local-viewer" if key in ("own", self.token) else "foreign"
                ),
            )

        with patch.object(fixture, "ProjectIntakeService", side_effect=local_store):
            driver_fixture.ProjectStage2ControllerTests.setUp(self)

    def host(self, **changes):
        options = dict(
            projects=self.intake,
            credential=self.token,
            stage2=self.service,
            files={},
            views=[],
            port=0,
        )
        options.update(changes)
        host = ProjectHost(**options)
        self.addCleanup(host.server_close)
        return host

    def test_unconnected_host_and_foreign_user_never_execute(self):
        host = self.host()
        with patch(
            "research_workspace_native.project_stage2_controller.run_controller"
        ) as execute:
            with self.assertRaisesRegex(
                SessionApiError, "stage2-controller-not-connected"
            ):
                host.continue_stage2("own", self.ref, key="test")
            with self.assertRaises(SessionApiError):
                host.continue_stage2("foreign", self.ref, key="test")
        execute.assert_not_called()
        self.assertFalse(host.host_binding["project_stage2_operator_continuation"])

    def test_wrong_owner_or_untrusted_callback_rejected_before_listener(self):
        with self.assertRaisesRegex(ValueError, "same trusted Stage2 controller owner"):
            self.host(stage2_controllers={self.ref: lambda: None})
        driver = self.driver()
        driver.service = object()
        with self.assertRaisesRegex(ValueError, "same trusted Stage2 controller owner"):
            self.host(stage2_controllers={self.ref: driver})

    def test_attached_driver_reopens_saved_controller_without_new_entry(self):
        host = self.host(stage2_controllers={self.ref: self.driver()})
        with patch(
            "research_workspace_native.project_stage2_controller.run_controller",
            side_effect=self.core,
        ) as entry:
            first = host.continue_stage2("own", self.ref, key="host-controller")
            replay = host.continue_stage2("own", self.ref, key="host-controller")
        self.assertEqual(entry.call_count, 1)
        self.assertEqual(replay["controller"], first["controller"])
        self.assertTrue(replay["replayed"])
        self.assertFalse(first["research_delivery_ready"])
        self.assertFalse(first["execution_authorized"])
        self.assertEqual(first["stage3_receiver"], "not-started")
        self.assertTrue(host.host_binding["project_stage2_operator_continuation"])


if __name__ == "__main__":
    unittest.main()

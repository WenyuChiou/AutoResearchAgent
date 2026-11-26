"""Current native input and saved selection connections; authored engineering only."""

# ruff: noqa: E402 -- exercise the plugin and ordinary Wiki composition together.

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parents[3] / "harness-ui"),
]
from current_core_stage12_fixtures import current_core_stage1_case
from test_project_stage2_current_evidence import authenticate, request, VIEWER
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.project_stage_connections import (
    ConnectionStore,
    BindingTable,
)
from research_workspace_native.session_api import SessionApiError
from project_stage2_selection_fixture import Stage2SelectionFixture
from research_workspace_native.project_stage2_selection_view import (
    ProjectStage2SelectionView,
)
from wiki_stage23_services import configure_services


@contextmanager
def wiki(case):
    services = dict(
        projects=case.intake,
        credential=VIEWER,
        stage2=ProjectStage2Service(case.intake),
    )
    configure_services(services, SimpleNamespace())
    with ProjectHost(
        projects=case.intake,
        credential=VIEWER,
        stage1=case.stage1,
        stage2=services["stage2"],
        stage2_selection=services["stage2_selection"],
        files={},
        views=[],
        port=0,
    ) as host:
        thread = threading.Thread(target=host.serve_forever)
        thread.start()
        try:
            yield host.expected_origin
        finally:
            host.shutdown()
            thread.join(5)
            if thread.is_alive():
                raise RuntimeError("host did not stop")


def counts(intake):
    return {
        table: intake.db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
        for table in ("intake_actions", "intake_events")
    }


class CurrentConnectionTests(unittest.TestCase):
    def test_current_native_package_has_a_reopenable_registration(self):
        with (
            patch("test_project_stage1_delivery.authenticate", authenticate),
            current_core_stage1_case(screened=True) as data,
        ):
            case, ref = data["case"], data["project_ref"]
            source_files = {
                p: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in data["deliverable_dir"].rglob("*")
                if p.is_file()
            }
            original_history = data["ledger"].state_hash()
            route = f"/api/projects/{ref}"
            before = counts(case.intake)
            service = ProjectStage2Service(case.intake)

            def expired():
                raise SessionApiError("session-deadline-exceeded", 408)

            with self.subTest(case="expired-transport"):
                result = service.register_current(
                    ref,
                    credential=VIEWER,
                    delivery=case.delivery,
                    check_deadline=expired,
                )
                self.assertEqual(result["reason"], "session-deadline-exceeded")
                self.assertIsNone(result["receipt_id"])
                self.assertEqual(counts(case.intake), before)
            with wiki(case) as origin:
                status, overview = request(origin, route + "/overview")
                self.assertEqual(status, 200, overview)
                accepted = overview["stage2"]["current_evidence"]
                self.assertEqual(accepted["status"], "received", accepted)
                self.assertIs(type(accepted["input_version"]), int)
                self.assertFalse(accepted["activation_allowed"])
                self.assertEqual(
                    accepted["source"]["manifest_sha256"], data["manifest_sha256"]
                )
                self.assertTrue(accepted["connection_id"])
                self.assertTrue(accepted["receipt_id"])
                self.assertEqual(
                    overview["project"]["revision"], overview["stage2"]["revision"]
                )
                self.assertEqual(
                    overview["stage1"]["revision"], overview["stage2"]["revision"]
                )
                after = counts(case.intake)
                self.assertEqual(after["intake_actions"] - before["intake_actions"], 1)
                self.assertEqual(after["intake_events"] - before["intake_events"], 2)
                for _ in range(2):
                    self.assertEqual(
                        request(origin, route + "/stage2")[1]["current_evidence"],
                        accepted,
                    )
                self.assertEqual(counts(case.intake), after)
                self.assertEqual(
                    request(origin, route + "/stage2/selection"),
                    (409, {"error": "stage2-selection-unconnected"}),
                )
            case.reopen()
            with wiki(case) as origin:
                self.assertEqual(
                    request(origin, route + "/stage2")[1]["current_evidence"], accepted
                )
                self.assertEqual(counts(case.intake), after)
                # Same title is intentionally not an identity or reusable source.
                topic = case.intake.read(VIEWER, ref)["brief"]["original_description"]
                other = case.intake.create(
                    VIEWER, {"key": "same-title", "topic": topic}
                )["project_ref"]
                status, unrelated = request(origin, f"/api/projects/{other}/stage2")
                self.assertEqual(status, 200)
                self.assertEqual(
                    unrelated["current_evidence"]["reason"],
                    "stage1-current-checkpoint-unavailable",
                )
                self.assertIsNone(unrelated["current_evidence"]["receipt_id"])
                stable = counts(case.intake)
                record = ConnectionStore(case.intake, VIEWER).resolve(
                    ref, "stage2-input"
                )
                self.assertEqual(record["identity"]["project_id"], ref)
                marker = (
                    case.intake._path(
                        ref, "s2r-" + accepted["source_descriptor_sha256"][:32]
                    )
                    / "receipt.json"
                )
                raw = marker.read_bytes()
                try:
                    value = json.loads(raw)
                    value["source"]["input_version"] = "1"
                    marker.write_text(json.dumps(value), encoding="utf-8")
                    wrong = request(origin, route + "/stage2")[1]["current_evidence"]
                    self.assertEqual(wrong["status"], "blocked")
                    self.assertIsNone(wrong["connection_id"])
                finally:
                    marker.write_bytes(raw)
                connection_path = case.intake._path(
                    ref, "connection-" + accepted["connection_id"][:32] + ".json"
                )
                raw = connection_path.read_bytes()
                try:
                    connection_path.write_bytes(raw + b" ")
                    damaged = request(origin, route + "/stage2")[1]["current_evidence"]
                    self.assertEqual(damaged["status"], "blocked")
                    self.assertIsNone(damaged["connection_id"])
                finally:
                    connection_path.write_bytes(raw)
                self.assertEqual(counts(case.intake), stable)
            self.assertEqual(data["ledger"].state_hash(), original_history)
            for p, original in source_files.items():
                self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), original)
            print(
                "CONNECTION_EVIDENCE="
                + json.dumps(
                    dict(
                        project_ref=ref,
                        input_version=1,
                        packet_id=accepted["packet_id"],
                        receipt_id=accepted["receipt_id"],
                        connection_id=accepted["connection_id"],
                        before=before,
                        after=after,
                        source_manifest_sha256=data["manifest_sha256"],
                        research_calls=0,
                    )
                )
            )


class SelectionConnectionTests(Stage2SelectionFixture):
    def test_saved_selection_static_dynamic_reopen_and_tampering(self):
        ui, _, _ = self.prepare_choice()
        binding = ui.bindings[self.ref]
        store = ConnectionStore(self.intake, "own")
        original = ui.read("own", self.ref)
        before = counts(self.intake)
        saved = store.record_selection(self.ref, binding)
        after = counts(self.intake)
        self.assertEqual(after["intake_actions"] - before["intake_actions"], 1)
        self.assertEqual(store.record_selection(self.ref, binding), saved)
        self.assertEqual(counts(self.intake), after)
        dynamic = ProjectStage2SelectionView(self.intake, BindingTable({}, store))
        actual = dynamic.read("own", self.ref)
        self.assertEqual(actual["cards"], original["cards"])
        self.assertEqual(actual["selection_receipt"], original["selection_receipt"])
        self.assertFalse(actual["execution_authorized"])
        with self.assertRaisesRegex(SessionApiError, "selection-bindings-overlap"):
            BindingTable({self.ref: binding}, store)[self.ref]
        for field, value in [
            ("input_version", str(binding["input_version"])),
            ("brief_sha256", "0" * 64),
        ]:
            with self.subTest(field=field), self.assertRaises(SessionApiError):
                changed = deepcopy(binding)
                changed[field] = value
                store.record_selection(self.ref, changed)
        # A separate project, even the same title, cannot receive this workflow.
        other = self.intake.create(
            "own", {"key": "other", "topic": "Synthetic household research"}
        )["project_ref"]
        with self.assertRaises(SessionApiError):
            store.record_selection(other, binding)
        path = self.intake._path(
            self.ref, "connection-" + saved["connection_id"][:32] + ".json"
        )
        raw = path.read_bytes()
        try:
            path.write_bytes(raw + b" ")
            with self.assertRaises(SessionApiError):
                dynamic.read("own", self.ref)
        finally:
            path.write_bytes(raw)


if __name__ == "__main__":
    unittest.main()

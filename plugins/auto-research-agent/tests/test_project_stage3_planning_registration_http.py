"""Ordinary Wiki HTTP attaches a saved selection to one read-only planning owner."""

# ruff: noqa: E402 -- use the existing plugin and Wiki fixtures.
from contextlib import closing, contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "harness-ui"))

import test_project_stage2 as activation_fixture
from project_stage2_selection_fixture import Stage2SelectionFixture
from research_workspace_native.http import token_authenticator
from research_workspace_native.journal import Journal, JournalError
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.project_stage2_selection import (
    ProjectStage2SelectionService,
)
from research_workspace_native.project_stage_connections import (
    PLANNING_STAGE,
    ConnectionStore,
)
from stage3_plan.contracts import Stage3Error
from stage3_plan.jobs import POLICY
from test_project_stage2_current_evidence import request, VIEWER
from test_project_stage1_delivery import _io_root
from test_project_stage3_planning_config import settings, write_json
from run_v7 import configure_host_lifecycle
from wiki_stage2_continuation import install_stage2_continuation
from wiki_stage23_services import configure_services
from types import SimpleNamespace


class Stage3RuntimeHttpTests(Stage2SelectionFixture):
    def setUp(self):
        authenticate = token_authenticator({VIEWER: "local-viewer"})
        self.fixture_auth = lambda token: authenticate(
            VIEWER if token == "own" else token
        )
        temporary = tempfile.TemporaryDirectory(prefix="s3-http-")
        with (
            patch.object(
                activation_fixture.tempfile,
                "TemporaryDirectory",
                return_value=temporary,
            ),
            patch.object(
                activation_fixture,
                "ProjectIntakeService",
                side_effect=lambda root, **_: ProjectIntakeService(
                    root, authenticate=self.fixture_auth
                ),
            ),
        ):
            super().setUp()
        # Keep the production path and its length checks. Only cleanup uses
        # the same Windows extended path as the native package fixture.
        temporary.name = str(_io_root(self.root))
        selection, self.selection_body, _ = self.prepare_choice(
            ProjectStage2SelectionService
        )
        self.selection_path, self.selection_pin = write_json(
            self.root / "selection.json",
            {"schema_version": "1.0.0", "bindings": selection.bindings},
        )
        self.legacy = settings(self.root, [self.intake.read(VIEWER, self.ref)])
        row = self.legacy["bindings"][0]
        self.profile = {
            "kind": "ProjectStage3PlanningProfile",
            "schema_version": "1.0.0",
            "journal_path": self.legacy["journal_path"],
            "project_parent": str(self.root / "runtime"),
            "max_projects": 1,
            "jobs_root": "jobs",
            "configuration": row["configuration"],
            "native": {**row["native"], "capture_dir": "capture"},
            "recovery_pins": [
                {
                    "key": "cold-recovery-probe",
                    "request_sha256": "a" * 64,
                    "plan_manifest_sha256": "b" * 64,
                }
            ],
        }
        self.profile_path, self.profile_pin = write_json(
            self.root / "profile.json", self.profile
        )
        self.route = f"/api/projects/{self.ref}"
        self.connect = self.route + "/connections"
        self.plan = self.route + "/stage3/planning"
        self.connecting = SimpleNamespace(
            stage3_planning_profile=self.profile_path,
            stage3_planning_profile_sha256=self.profile_pin,
            selection_config=self.selection_path,
            selection_sha256=self.selection_pin,
        )
        self.native = self.enterContext(
            patch(
                "stage3_plan.native.NativePlanner.__call__",
                side_effect=AssertionError("Native planning forbidden"),
            )
        )
        self.addCleanup(self.native.assert_not_called)

    def configure(self, args):
        services = {
            "projects": self.intake,
            "credential": VIEWER,
            "stage2": ProjectStage2Service(self.intake),
        }
        configure_services(services, args)
        return services

    @contextmanager
    def wiki(self, args=None):
        services = self.configure(self.connecting if args is None else args)
        resources = services["planning_resources"]
        host = ProjectHost(
            projects=self.intake,
            credential=VIEWER,
            stage2=services["stage2"],
            stage2_selection=services["stage2_selection"],
            stage3_planning=resources.service,
            stage3_recovery_pins=resources.recovery_pins,
            files={},
            views=[],
            port=0,
        )
        configure_host_lifecycle(host, services)
        install_stage2_continuation(host, planning_resources=resources)
        thread = threading.Thread(
            target=host.serve_forever, kwargs={"poll_interval": 0.05}
        )
        thread.start()
        try:
            yield host.expected_origin, resources
        finally:
            host.shutdown()
            host.server_close()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertTrue(host.project_stage3_http.close()["threads_joined"])
            resources.close()

    def observed(self, origin, label, route, **kwargs):
        response = request(origin, route, **kwargs)
        print(
            json.dumps({"fixture": label, "status": response[0], "body": response[1]}),
            flush=True,
        )
        return response

    def connection_body(self, origin):
        code, project = request(origin, self.route)
        self.assertEqual(code, 200)
        return {
            **{
                key: project[key]
                for key in ("revision", "input_version", "brief_sha256")
            },
            "key": "connect-stage3",
            "stage": PLANNING_STAGE,
            "profile_sha256": self.profile_pin,
            "confirmed": True,
        }

    def legacy_args(self, config):
        path, pin = write_json(self.root / "legacy.json", config)
        return SimpleNamespace(
            **vars(self.connecting),
            stage3_planning_config=path,
            stage3_planning_sha256=pin,
        )

    def check_events(self, journal, project_id, expected):
        state = journal.snapshot(project_id)
        events = [row["kind"] for row in journal.events(project_id)]
        self.assertEqual(events, expected)
        self.assertEqual(state["intents"], {})
        self.assertEqual(state["requests"], {})
        self.assertEqual(state["turns"], {})
        print(
            json.dumps(
                {
                    "fixture": "journal",
                    "project_id": project_id,
                    "events": events,
                    "jobs": len(state["intents"]),
                    "owner_held": state["owner"] is not None,
                    "native_calls": self.native.call_count,
                }
            ),
            flush=True,
        )
        return state["owner"]

    def test_current_selection_attaches_releases_and_reopens_one_lease(self):
        project = self.intake.read(VIEWER, self.ref)
        project_id = project["project_id"]
        journal_path = self.profile["journal_path"]
        self.assertIs(type(project["input_version"]), int)
        self.assertFalse(Path(journal_path).exists())
        other = self.intake.create(
            VIEWER,
            {"key": "other-static-project", "topic": "Separate authored fixture"},
        )["project_ref"]
        healthy = settings(self.root, [self.intake.read(VIEWER, other)])
        overlapping = deepcopy(healthy)
        overlapping["bindings"][0]["native"]["capture_dir"] = str(
            Path(self.profile["project_parent"]) / self.ref / "capture"
        )
        with self.assertRaisesRegex(Stage3Error, "profile-output-overlap"):
            self.configure(self.legacy_args(overlapping))
        self.assertFalse(Path(journal_path).exists())
        with self.wiki() as (origin, resources):
            code, view = self.observed(origin, "pending-selection", self.plan)
            self.assertEqual(code, 200, view)
            self.assertEqual(view["selection_status"], "pending")
            self.assertFalse(view["planning_configured"])
            body = self.connection_body(origin)
            self.assertEqual(
                self.observed(
                    origin, "missing-selection-refused", self.connect, body=body
                ),
                (409, {"error": "stage3-current-selection-required"}),
            )
            self.assertEqual(resources.journal.events(project_id), [])
            code, selection = self.observed(
                origin,
                "saved-fixture-selection",
                self.route + "/stage2/select",
                body=self.selection_body,
            )
            self.assertEqual(code, 200, selection)
            self.assertEqual(selection["status"], "saved")
            self.assertFalse(selection["execution_authorized"])
            code, view = self.observed(origin, "unregistered-planning", self.plan)
            self.assertEqual(code, 200, view)
            self.assertFalse(view["planning_configured"])
            code, available = self.observed(origin, "connectable", self.connect)
            self.assertEqual(code, 200, available)
            self.assertEqual(
                available["connections"][PLANNING_STAGE]["status"], "connectable"
            )
            body = self.connection_body(origin)
            for label, change, status in (
                ("foreign-version", {"input_version": body["input_version"] + 1}, 409),
                ("string-version", {"input_version": str(body["input_version"])}, 400),
                ("browser-path", {"jobs_root": str(self.root)}, 400),
                ("brief-hash", {"brief_sha256": "0" * 64}, 409),
                ("profile-hash", {"profile_sha256": "0" * 64}, 409),
                ("stale-revision", {"revision": body["revision"] - 1}, 409),
            ):
                with self.subTest(refusal=label):
                    self.assertEqual(
                        request(origin, self.connect, body={**body, **change})[0],
                        status,
                    )
            self.assertEqual(resources.journal.events(project_id), [])
            code, saved = self.observed(origin, "registered", self.connect, body=body)
            self.assertEqual(code, 200, saved)
            received = saved["connections"][PLANNING_STAGE]
            self.assertEqual(received["status"], "connected")
            self.assertEqual(received["receipt_id"], body["key"])
            self.assertFalse(saved["execution_authorized"])
            self.assertEqual(request(origin, self.connect, body=body), (200, saved))
            stored = ConnectionStore(self.intake, VIEWER).resolve(
                self.ref, PLANNING_STAGE
            )
            self.assertEqual(stored["connection_id"], received["connection_id"])
            self.assertEqual(
                stored["derived_from"]["selection_request_sha256"],
                selection["request_sha256"],
            )
            self.assertEqual(
                stored["derived_from"]["planning_manifest_sha256"],
                selection["planning_manifest_sha256"],
            )
            print(
                json.dumps(
                    {
                        "fixture": "source",
                        "project_ref": self.ref,
                        "project_id": project_id,
                        "input_version": body["input_version"],
                        "connection_id": stored["connection_id"],
                        "receipt_id": stored["receipt_id"],
                        "identity": stored["identity"],
                        "derived_from": stored["derived_from"],
                    }
                ),
                flush=True,
            )
            first = self.check_events(
                resources.journal, project_id, ["project-bound", "owner-acquired"]
            )
            self.assertIsNotNone(first)
            with closing(Journal(journal_path)) as peer:
                with self.assertRaisesRegex(
                    JournalError, "already has an execution owner"
                ):
                    peer.acquire_owner(project_id, "peer")
            with self.wiki() as (competitor, _):
                code, busy = self.observed(competitor, "competing-lease", self.connect)
                self.assertEqual(code, 200, busy)
                self.assertEqual(
                    busy["connections"][PLANNING_STAGE]["status"], "unavailable"
                )
                self.assertEqual(
                    busy["connections"][PLANNING_STAGE]["reason"],
                    "stage3-planning-resource-unavailable",
                )
                self.assertEqual(request(competitor, self.plan)[0], 409)
            self.assertEqual(
                self.check_events(
                    resources.journal, project_id, ["project-bound", "owner-acquired"]
                ),
                first,
            )
            code, ready = self.observed(origin, "configured-planning", self.plan)
            self.assertEqual(code, 200, ready)
            self.assertTrue(ready["planning_configured"])
            self.assertEqual(
                ready["selection_request_sha256"], selection["request_sha256"]
            )
            self.assertIsNone(ready["job"])
            self.assertIsNone(ready["plan"])
            self.assertTrue(all(ready[key] is False for key in POLICY))
            original = self.profile_path.read_bytes()
            try:
                self.profile_path.write_bytes(original + b" ")
                self.assertEqual(request(origin, self.plan)[0], 409)
            finally:
                self.profile_path.write_bytes(original)

        events = ["project-bound", "owner-acquired", "owner-released"]
        with closing(Journal(journal_path)) as closed:
            self.assertIsNone(self.check_events(closed, project_id, events))
        self.intake.close()
        self.intake = ProjectIntakeService(
            self.store_root, authenticate=self.fixture_auth
        )
        with self.wiki() as (origin, resources):
            self.assertIsNone(self.check_events(resources.journal, project_id, events))
            self.assertEqual(
                self.observed(
                    origin,
                    "cold-recover-reaches-original-input-guard",
                    self.plan + "/recover",
                    body={"key": "cold-recovery-probe", "request_sha256": "a" * 64},
                ),
                (400, {"error": "intake-fields-invalid"}),
            )
            self.assertIsNone(self.check_events(resources.journal, project_id, events))
            code, reopened = self.observed(origin, "reopened-planning", self.plan)
            self.assertEqual((code, reopened), (200, ready))
            self.assertEqual(request(origin, self.connect, body=body), (200, saved))
            events.append("owner-acquired")
            second = self.check_events(resources.journal, project_id, events)
            self.assertNotEqual(first["token"], second["token"])
        with closing(Journal(journal_path)) as closed:
            self.assertIsNone(
                self.check_events(closed, project_id, events + ["owner-released"])
            )
        self.assertFalse(
            (Path(self.profile["project_parent"]) / self.ref / "jobs").exists()
        )

        with self.assertRaisesRegex(Stage3Error, "bindings-overlap"):
            self.configure(self.legacy_args(self.legacy))
        with self.assertRaisesRegex(Stage3Error, "output-overlap"):
            self.configure(self.legacy_args(overlapping))
        connection_path = self.intake._path(
            self.ref, "connection-" + stored["connection_id"][:32] + ".json"
        )
        retained_connection = connection_path.rename(
            connection_path.with_suffix(".retained")
        )
        try:
            with self.assertRaisesRegex(Stage3Error, "configuration-output-overlap"):
                self.configure(self.legacy_args(overlapping))
            own_root = Path(self.profile["project_parent"]) / other
            healthy["bindings"][0]["jobs_root"] = str(own_root / "jobs")
            healthy["bindings"][0]["native"]["capture_dir"] = str(own_root / "capture")
            with self.wiki(self.legacy_args(healthy)) as (origin, resources):
                code, unavailable = self.observed(
                    origin, "damaged-connection", self.connect
                )
                self.assertEqual(code, 200, unavailable)
                self.assertEqual(
                    unavailable["connections"][PLANNING_STAGE]["reason"],
                    "stage-connection-source-invalid",
                )
                code, available = self.observed(
                    origin,
                    "healthy-static-namespace",
                    f"/api/projects/{other}/connections",
                )
                self.assertEqual(code, 200, available)
                self.assertEqual(
                    available["connections"][PLANNING_STAGE]["status"], "connected"
                )
                self.assertEqual(resources.journal.snapshot(other)["intents"], {})
            with closing(Journal(journal_path)) as saved_journal:
                self.assertIsNone(
                    self.check_events(
                        saved_journal, project_id, events + ["owner-released"]
                    )
                )
        finally:
            retained_connection.rename(connection_path)
        different = deepcopy(self.legacy)
        different["journal_path"] = str(self.root / "different.sqlite")
        with self.assertRaisesRegex(Stage3Error, "profile-journal-differs"):
            self.configure(self.legacy_args(different))
        self.assertFalse(Path(different["journal_path"]).exists())

        journal = Path(journal_path)
        retained = journal.rename(journal.with_name("original-planning.sqlite"))
        try:
            with self.assertRaisesRegex(Stage3Error, "saved-journal-missing"):
                self.configure(self.connecting)
            self.assertFalse(journal.exists())
            # A newly provisioned empty file must not recreate the saved project.
            with closing(Journal(journal)):
                pass
            with self.wiki() as (origin, resources):
                code, unavailable = self.observed(
                    origin, "empty-replacement-journal", self.connect
                )
                self.assertEqual(code, 200, unavailable)
                self.assertEqual(
                    unavailable["connections"][PLANNING_STAGE]["status"], "unavailable"
                )
                self.assertEqual(request(origin, self.plan)[0], 409)
                self.assertEqual(resources.journal.events(project_id), [])
        finally:
            if journal.exists():
                journal.unlink()
            retained.rename(journal)

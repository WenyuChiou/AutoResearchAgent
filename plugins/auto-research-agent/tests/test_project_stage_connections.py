"""Current native input and saved selection connections; authored engineering only."""

# ruff: noqa: E402 -- exercise the plugin and ordinary Wiki composition together.

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from urllib.request import Request, urlopen
import unittest
from unittest.mock import patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parents[3] / "harness-ui"),
]
from current_core_stage12_fixtures import current_core_stage1_case
from test_project_stage2_current_evidence import authenticate, request, VIEWER
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_stage1_delivery import (
    ProjectStage1DeliveryService,
)
from research_workspace_native.http import SessionHandler
from research_workspace_native.project_model import ProjectModelService
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.project_stage2_selection import (
    ProjectStage2SelectionService,
)
from research_workspace_native.project_stage2_controller_connections import (
    Stage2ControllerConnections,
)
from research_workspace_native.project_stage2_current_evidence import (
    _reference,
    current_evidence,
)
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage_connections import (
    CONTROLLER_STAGE,
    ConnectionStore,
    BindingTable,
)
from research_workspace_native.session_api import SessionApiError
from project_stage2_selection_fixture import Stage2SelectionFixture
import test_project_stage2 as activation_fixture
from research_workspace_native.project_stage2_selection_view import (
    ProjectStage2SelectionView,
)
from wiki_stage23_services import configure_services
from wiki_stage2_continuation import install_stage2_continuation


@contextmanager
def wiki(case, controllers=None, *, connections=False):
    services = dict(
        projects=case.intake,
        credential=VIEWER,
        stage2=ProjectStage2Service(case.intake),
    )
    with patch(
        "research_workspace_native.project_stage2_controller_config.load_stage2_controllers",
        return_value=controllers,
    ):
        args = SimpleNamespace(
            stage2_controller_config="trusted-fixture" if controllers else None,
            stage2_controller_sha256="a" * 64 if controllers else None,
        )
        configure_services(services, args)
    with ProjectHost(
        projects=case.intake,
        credential=VIEWER,
        stage1=case.stage1,
        models=ProjectModelService(case.intake),
        stage2=services["stage2"],
        stage2_selection=services["stage2_selection"],
        files={},
        views=[],
        port=0,
    ) as host:
        if connections:
            install_stage2_continuation(host, services["stage2_controller_profile"])
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
            ExitStack() as fixture,
        ):
            # Recreate the saved-but-unreceived package from before automatic
            # handoff. Only its creation omits the new post-delivery hook.
            with patch.object(
                ProjectStage1DeliveryService,
                "_receive_stage2_input",
                autospec=True,
                side_effect=lambda _service, _credential, _ref, receipt, _deadline: (
                    receipt
                ),
            ):
                data = fixture.enter_context(current_core_stage1_case(screened=True))
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
            unpublished = current_evidence(
                case.delivery,
                VIEWER,
                case.stage1.read(VIEWER, ref),
                case.intake.read(VIEWER, ref),
                allow_publish=False,
            )
            self.assertEqual(unpublished["status"], "blocked")
            self.assertEqual(
                unpublished["reason"], "stage2-current-input-publication-unobserved"
            )
            self.assertFalse(list((case.intake.root / ref).glob("s2r-*")))
            self.assertEqual(counts(case.intake), before)

            def snapshot():
                state = case.intake._load(case.intake._principal(VIEWER), ref)
                root = case.intake.root / ref
                return (
                    counts(case.intake),
                    state["revision"],
                    state.get("stage_connections", {}).get("stage2-input"),
                    state.get("stage_connections", {}).get("stage2-selection"),
                    {
                        file.relative_to(root): file.read_bytes()
                        for file in root.rglob("*")
                        if file.is_file()
                    },
                )

            initial = snapshot()
            self.assertEqual(initial[2:4], (None, None))
            with wiki(case, connections=True) as origin:
                for _ in range(2):
                    status, overview = request(origin, route + "/overview")
                    self.assertEqual(status, 200, overview)
                    self.assertEqual(overview["stage2"]["offers"], [])
                    self.assertIsNone(
                        overview["stage2"]["current_evidence"]["receipt_id"]
                    )
                    self.assertEqual(snapshot(), initial)
            case.reopen()
            service = ProjectStage2Service(case.intake)
            with wiki(case, connections=True) as origin:
                status, overview = request(origin, route + "/overview")
                self.assertEqual(status, 200, overview)
                self.assertEqual(snapshot(), initial)
                intent = dict(
                    key="confirm-current-input",
                    revision=overview["project"]["revision"],
                    input_version=overview["project"]["input_version"],
                    brief_sha256=overview["project"]["brief_sha256"],
                    stage="stage2-input",
                    confirmed=True,
                )
                for target, body, expected_status in (
                    (route, dict(intent, confirmed=False), 400),
                    (route, dict(intent, input_version=True), 400),
                    (route, dict(intent, input_version=2), 409),
                    (route, dict(intent, revision=intent["revision"] - 1), 409),
                    ("/api/projects/project-" + "0" * 32, intent, 404),
                ):
                    status, rejected = request(
                        origin, target + "/connections", body=body
                    )
                    self.assertEqual(status, expected_status, rejected)
                    self.assertEqual(snapshot(), initial)

                status, explicit = request(origin, route + "/connections", body=intent)
                self.assertEqual(status, 200, explicit)
                self.assertFalse(explicit["execution_authorized"])
                self.assertEqual(
                    explicit["connections"]["stage2-input"]["receipt_id"], intent["key"]
                )
                registered = snapshot()
                self.assertIsNotNone(registered[2])
                self.assertIsNone(registered[3])
                self.assertEqual(
                    request(origin, route + "/connections", body=intent),
                    (200, explicit),
                )
                self.assertEqual(snapshot(), registered)
                [receiver] = list((case.intake.root / ref).glob("s2r-*"))
                resources = receiver / "resources.txt"
                original_resources = resources.read_bytes()
                try:
                    resources.write_bytes(original_resources + b"tampered")
                    rejected = request(origin, route + "/stage2")[1]
                    self.assertEqual(
                        rejected["current_evidence"]["reason"],
                        "stage2-input-bytes-differ",
                    )
                    self.assertIsNone(rejected["current_evidence"]["receipt_id"])
                    self.assertEqual(rejected["offers"], [])
                    self.assertEqual(counts(case.intake), registered[0])
                finally:
                    resources.write_bytes(original_resources)
                status, overview = request(origin, route + "/overview")
                self.assertEqual(status, 200, overview)
                accepted = overview["stage2"]["current_evidence"]
                self.assertEqual(accepted["status"], "received", accepted)
                self.assertEqual(
                    accepted["connection_id"],
                    explicit["connections"]["stage2-input"]["connection_id"],
                )
                self.assertIs(type(accepted["input_version"]), int)
                self.assertFalse(accepted["activation_allowed"])
                self.assertEqual(
                    accepted["source"]["manifest_sha256"], data["manifest_sha256"]
                )
                self.assertTrue(accepted["connection_id"])
                self.assertTrue(accepted["receipt_id"])
                self.assertEqual(overview["stage2"]["offers"], [accepted["offer"]])
                status, listed = request(origin, route + "/stage2/offers")
                self.assertEqual(status, 200, listed)
                self.assertEqual(listed["offers"], [accepted["offer"]])
                self.assertEqual(listed["current_evidence"], accepted)
                status, contract = request(origin, route + "/contract")
                self.assertEqual(status, 200, contract)
                self.assertEqual(contract["stages"]["2"]["offers"], [accepted["offer"]])
                self.assertEqual(snapshot(), registered)
                self.assertEqual(accepted["offer"]["status"], "receiving-only")
                offer = accepted["offer"]
                denied = dict(
                    key="cannot-activate-read-connection",
                    revision=overview["project"]["revision"],
                    input_version=1,
                    brief_sha256=overview["project"]["brief_sha256"],
                    offer_ref=offer["offer_ref"],
                    offer_sha256=offer["offer_sha256"],
                    confirmed=True,
                )
                with self.assertRaisesRegex(SessionApiError, "research-not-authorized"):
                    service.activate(VIEWER, ref, denied)
                self.assertEqual(
                    overview["project"]["revision"], overview["stage2"]["revision"]
                )
                self.assertEqual(
                    overview["models"]["revision"], overview["project"]["revision"]
                )
                self.assertEqual(
                    overview["model_offers"]["revision"],
                    overview["project"]["revision"],
                )
                self.assertEqual(overview["models"]["calls_reserved"], 0)
                self.assertEqual(
                    overview["stage1"]["reading_registration"]["revision"],
                    overview["project"]["revision"],
                )
                self.assertEqual(
                    overview["stage1"]["revision"], overview["stage2"]["revision"]
                )
                after = counts(case.intake)
                self.assertEqual(after["intake_actions"] - before["intake_actions"], 1)
                self.assertEqual(after["intake_events"] - before["intake_events"], 2)
                # The old receipt still passes _source's path guard. A changed
                # re-derived descriptor must not publish a new seed on read.
                paths = set((case.intake.root / ref).glob("s2r-*"))
                old_receipt = case.intake._path(
                    ref,
                    "s2r-"
                    + accepted["source_descriptor_sha256"][:32]
                    + "/receipt.json",
                )
                old_bytes = old_receipt.read_bytes()
                probe_host = SimpleNamespace(
                    projects=case.intake,
                    credential=VIEWER,
                    project_stage1=case.stage1,
                    project_stage1_delivery=case.delivery,
                    project_stage2_controllers={},
                )
                connections = Stage2ControllerConnections(probe_host, None)

                def changed_descriptor(*args):
                    return {**_reference(*args), "settings_sha256": "0" * 64}

                with (
                    patch(
                        "research_workspace_native.project_stage2_current_evidence._reference",
                        side_effect=changed_descriptor,
                    ),
                    self.assertRaisesRegex(
                        SessionApiError, "stage2-controller-current-input-differs"
                    ),
                ):
                    connections._source(VIEWER, ref, None)
                self.assertEqual(set((case.intake.root / ref).glob("s2r-*")), paths)
                self.assertEqual(old_receipt.read_bytes(), old_bytes)
                self.assertEqual(counts(case.intake), after)
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
                state = case.intake._load("local-viewer", ref)
                raw_state = json.dumps(state)
                for damaged_offer in (
                    None,
                    dict(
                        state["stage2_offers"][accepted["offer"]["offer_ref"]],
                        status="ready-for-researcher-activation",
                    ),
                ):
                    try:
                        changed = json.loads(raw_state)
                        if damaged_offer is None:
                            del changed["stage2_offers"][accepted["offer"]["offer_ref"]]
                        else:
                            changed["stage2_offers"][accepted["offer"]["offer_ref"]] = (
                                damaged_offer
                            )
                        case.intake.db.execute(
                            "UPDATE intake_projects SET state=? WHERE ref=?",
                            (json.dumps(changed), ref),
                        )
                        case.intake.db.commit()
                        status, rejected = request(origin, route + "/stage2")
                        self.assertEqual(status, 200)
                        self.assertEqual(
                            rejected["current_evidence"]["reason"],
                            "stage-connection-offer-differs",
                        )
                        self.assertEqual(
                            rejected["current_evidence"]["status"], "blocked"
                        )
                        self.assertEqual(rejected["offers"], [])
                        if damaged_offer is not None:
                            changed["stage2_offers"][accepted["offer"]["offer_ref"]][
                                "policy_ref"
                            ] = dict(
                                route="stage2-general-v3/daily_v3",
                                packet_profile="scientific-v3",
                                execution_authorized=False,
                            )
                            case.intake.db.execute(
                                "UPDATE intake_projects SET state=? WHERE ref=?",
                                (json.dumps(changed), ref),
                            )
                            case.intake.db.commit()
                            action = dict(
                                denied,
                                key="forged-read-connection",
                                revision=changed["revision"],
                            )
                            status, response = request(
                                origin, route + "/stage2/actions", body=action
                            )
                            self.assertEqual(status, 409, response)
                            self.assertEqual(
                                response["error"], "stage2-offer-journal-differs"
                            )
                            self.assertEqual(
                                response["receipt"]["status"], "known-unsent"
                            )
                            refused = {
                                name: value + 1 for name, value in stable.items()
                            }
                            self.assertEqual(counts(case.intake), refused)
                            self.assertEqual(
                                case.intake.db.execute(
                                    "SELECT COUNT(*) FROM intake_events WHERE kind IN ('stage2-activate-intent','stage2-activate-saved')"
                                ).fetchone()[0],
                                0,
                            )
                            replay_status, replay = request(
                                origin, route + "/stage2/actions", body=action
                            )
                            self.assertEqual(replay_status, 200)
                            self.assertEqual(replay["status"], "known-unsent")
                            self.assertTrue(replay["replayed"])
                            self.assertEqual(counts(case.intake), refused)
                    finally:
                        case.intake.db.execute(
                            "UPDATE intake_projects SET state=? WHERE ref=?",
                            (raw_state, ref),
                        )
                        case.intake.db.commit()

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

            self._completed_delivery(case, data)

    def _completed_delivery(self, case, data):
        from stage1_deliverable.common import sha
        from stage2_workflow import inspect_workflow
        from research_workspace_native.project_stage2_controller import (
            ProjectStage2ControllerDriver,
        )
        from test_stage1_current_core_stage123_e2e import (
            CurrentCoreSyntheticAdapter,
            CurrentCorePreparation,
        )
        from test_stage2_controller import Stage2ControllerTests

        service, ref = ProjectStage2Service(case.intake), data["project_ref"]
        resources = data["root"] / "controller-resources.txt"
        resources.write_text(
            case.intake.binding(ref)["settings"]["resource_envelope"], encoding="utf-8"
        )
        offer = service.register(
            ref,
            deliverable_dir=data["deliverable_dir"],
            expected_manifest_sha256=data["manifest_sha256"],
            handoff_path=data["handoff_path"],
            expected_handoff_sha256=data["handoff_sha256"],
            resources_path=resources,
            expected_resources_sha256=sha(resources.read_bytes()),
            policy_ref=dict(
                route="stage2-general-v3/daily_v3",
                execution_authorized=False,
                packet_profile="scientific-v3",
            ),
        )
        project = case.intake.read(VIEWER, ref)
        service.activate(
            VIEWER,
            ref,
            dict(
                key="explicit-synthetic-controller-fixture",
                revision=project["revision"],
                input_version=1,
                brief_sha256=project["brief_sha256"],
                confirmed=True,
                offer_ref=offer["offer_ref"],
                offer_sha256=offer["offer_sha256"],
            ),
        )
        binding = service.binding(ref)
        snapshot = inspect_workflow(binding["workflow_root"])["latest_snapshot"]
        preparation = SimpleNamespace(
            root=data["root"],
            workflow=Path(binding["workflow_root"]),
            packet=snapshot["packet"],
            base=snapshot["event"]["payload"]["snapshot_sha256"],
        )
        preparation.spec = Stage2ControllerTests._spec(preparation)
        original_preparation = CurrentCorePreparation(preparation)

        def open_driver(stage2):
            return ProjectStage2ControllerDriver(
                stage2,
                spec=preparation.spec,
                controller_dir=data["root"] / "controller",
                delivery_dir=data["root"] / "controller-delivery",
                prerequisite_handler=original_preparation,
            )

        driver = open_driver(service)
        with patch(
            "stage2_live.controller._ProductionAdapter",
            return_value=CurrentCoreSyntheticAdapter(),
        ):
            completed = driver.run(
                VIEWER, ref, key="authored-fixed-engineering-controller"
            )
        self.assertEqual(completed["status"], "saved", completed)
        before = counts(case.intake)
        revision = case.intake.read(VIEWER, ref)["revision"]
        with (
            patch.object(
                driver, "run", side_effect=AssertionError("GET cannot run controller")
            ),
            wiki(case, {ref: driver}) as origin,
        ):
            with urlopen(
                Request(
                    origin + "/project-bootstrap.js",
                    headers={"Origin": origin, "Sec-Fetch-Site": "same-origin"},
                ),
                timeout=25,
            ) as response:
                bootstrap = json.loads(
                    response.read().decode().split("=", 1)[1].strip().removesuffix(";")
                )
            self.assertIn(ref, bootstrap["stage2_selection_projects"])
            self.assertEqual(counts(case.intake), before)
            status, selected = request(origin, f"/api/projects/{ref}/stage2/selection")
            self.assertEqual(status, 200, selected)
            self.assertEqual(selected["selection_status"], "pending")
            self.assertEqual(selected["revision"], revision)
            self.assertFalse(selected["execution_authorized"])
            self.assertTrue(selected["cards"])
            after = counts(case.intake)
            self.assertEqual(after, before)
            self.assertIsNone(
                ConnectionStore(case.intake, VIEWER).resolve(ref, "stage2-selection")
            )
            self.assertEqual(
                request(origin, f"/api/projects/{ref}/stage2/selection"),
                (200, selected),
            )
            self.assertEqual(counts(case.intake), after)
        case.reopen()
        reopened = open_driver(ProjectStage2Service(case.intake))
        with (
            patch.object(
                reopened, "run", side_effect=AssertionError("GET cannot run controller")
            ),
            wiki(case, {ref: reopened}) as origin,
        ):
            self.assertEqual(
                request(origin, f"/api/projects/{ref}/stage2/selection"),
                (200, selected),
            )
            self.assertEqual(counts(case.intake), after)
            self.assertIsNone(
                ConnectionStore(case.intake, VIEWER).resolve(ref, "stage2-selection")
            )
        print(
            "SELECTION_EVIDENCE="
            + json.dumps(
                dict(
                    project_ref=ref,
                    input_version=1,
                    delivery_manifest_sha256=selected["delivery_manifest_sha256"],
                    selection_status=selected["selection_status"],
                    before=before,
                    after=after,
                    controller_calls_on_get=0,
                )
            )
        )


class SelectionConnectionTests(Stage2SelectionFixture):
    def test_blocked_current_source_keeps_independently_registered_offer(self):
        state = self.intake._load("researcher", self.ref)
        raw_state = json.dumps(state)
        bad = deepcopy(next(iter(state["stage2_offers"].values())))
        bad["offer_ref"] = "stage2-" + "0" * 32
        del bad["work_count"]
        state["stage2_offers"][bad["offer_ref"]] = bad
        self.intake.db.execute(
            "UPDATE intake_projects SET state=? WHERE ref=?",
            (json.dumps(state), self.ref),
        )
        self.intake.db.commit()
        before = counts(self.intake)
        self.service.receive_current = True
        host = SimpleNamespace(
            projects=self.intake,
            project_stage2=self.service,
            project_stage1_delivery=object(),
            project_stage1=object(),
        )
        try:
            for reason in (
                "stage-connection-offer-differs",
                "stage-connection-receipt-differs",
                "stage2-input-bytes-differ",
            ):
                with (
                    self.subTest(reason=reason),
                    patch.object(
                        self.service,
                        "register_current",
                        return_value={"status": "blocked", "reason": reason},
                    ),
                ):
                    result = ProjectHost.stage2_view(
                        host, "own", self.ref, project={}, stage1={}
                    )
                    self.assertEqual(
                        [row["offer_ref"] for row in result["offers"]],
                        [self.offer["offer_ref"]],
                    )
                    self.assertEqual(result["current_evidence"]["reason"], reason)
                    self.assertEqual(counts(self.intake), before)
            with patch.object(
                self.service,
                "register_current",
                return_value={
                    "status": "received",
                    "offer": {"offer_ref": "authored-verified-current-offer"},
                },
            ):
                result = ProjectHost.stage2_view(
                    host, "own", self.ref, project={}, stage1={}
                )
                self.assertEqual(
                    [row["offer_ref"] for row in result["offers"]],
                    [self.offer["offer_ref"], "authored-verified-current-offer"],
                )
                self.assertEqual(counts(self.intake), before)
        finally:
            self.intake.db.execute(
                "UPDATE intake_projects SET state=? WHERE ref=?", (raw_state, self.ref)
            )
            self.intake.db.commit()

    def test_damaged_other_project_does_not_block_discovery(self):
        store = ConnectionStore(self.intake, "own")
        store.record(
            self.ref, "stage2-selection", {"authored_storage_probe": 1}, derived_from={}
        )
        other = self.intake.create(
            "own", {"key": "damaged-other", "topic": "Synthetic household research"}
        )["project_ref"]
        original = self.intake.db.execute(
            "SELECT state FROM intake_projects WHERE ref=?", (other,)
        ).fetchone()[0]
        before = counts(self.intake)
        table = BindingTable({}, store)
        try:
            bad_state = json.loads(original)
            bad_state["stage_connections"] = None
            for raw in (json.dumps(bad_state), "{", "null", "[]"):
                with self.subTest(raw=raw):
                    self.intake.db.execute(
                        "UPDATE intake_projects SET state=? WHERE ref=?", (raw, other)
                    )
                    self.intake.db.commit()
                    self.assertEqual(list(table), [self.ref])
                    self.assertIn(self.ref, table)
                    self.assertNotIn(other, table)
                    with self.assertRaisesRegex(
                        SessionApiError, "stage-connection-source-invalid"
                    ):
                        table[other]
                    self.assertEqual(counts(self.intake), before)
        finally:
            self.intake.db.execute(
                "UPDATE intake_projects SET state=? WHERE ref=?", (original, other)
            )
            self.intake.db.commit()

    def test_unreadable_controller_discovery_does_not_block_other_projects(self):
        from research_workspace_native import project_stage_connections as connections

        store = ConnectionStore(self.intake, "own")
        bad = SimpleNamespace(records=self.root / "unreadable")
        table = BindingTable({}, store, {self.ref: bad})
        with patch.object(
            connections, "safe_path", side_effect=OSError("authored unreadable path")
        ):
            self.assertEqual(list(table), [])
            with self.assertRaisesRegex(
                SessionApiError, "stage2-selection-source-invalid"
            ):
                table.read_unregistered("own", self.ref)

    def test_new_input_version_keeps_original_connection_and_receipt(self):
        store = ConnectionStore(self.intake, "own")
        first = store.record(
            self.ref,
            "stage2-input",
            {"authored_storage_probe": 1},
            derived_from={"fixture": True},
        )
        path = self.intake._path(
            self.ref, "connection-" + first["connection_id"][:32] + ".json"
        )
        original = (path.read_bytes(), path.stat().st_mtime_ns)
        requests = {}
        for row in self.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE project=?", (self.ref,)
        ):
            value = json.loads(row[0])
            if value["kind"] in {"submit", "compile"}:
                requests[value["kind"]] = value["request"]
        current = self.intake.read("own", self.ref)
        self.intake.revise(
            "own",
            self.ref,
            dict(
                key="revise-same-topic",
                revision=current["revision"],
                input_version=current["input_version"],
                brief_sha256=current["brief_sha256"],
                topic=current["brief"]["original_description"],
                needs=[
                    {
                        "need_id": "consumption",
                        "question": "Synthetic household question",
                    }
                ],
            ),
        )
        for method in ("submit", "compile"):
            current = self.intake.read("own", self.ref)
            body = deepcopy(requests[method])
            body.update(
                key="next-" + method,
                revision=current["revision"],
                input_version=current["input_version"],
                brief_sha256=current["brief_sha256"],
            )
            getattr(self.intake, method)("own", self.ref, body)
        self.assertEqual(self.intake.binding(self.ref)["input_version"], 2)
        with self.assertRaises(SessionApiError):
            store.resolve(self.ref, "stage2-input")
        second = store.record(
            self.ref,
            "stage2-input",
            {"authored_storage_probe": 2},
            derived_from={"fixture": True},
        )
        self.assertEqual(second["identity"]["input_version"], 2)
        self.assertNotEqual(second["receipt_id"], first["receipt_id"])
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), original)

    def test_prework_deadline_recovers_but_unknown_write_does_not_retry(self):
        store = ConnectionStore(self.intake, "own")
        checks = []

        def expire_before_work():
            checks.append(True)
            if len(checks) == 2:
                raise SessionApiError("session-deadline-exceeded", 408)

        for _ in range(2):
            checks.clear()
            with self.assertRaises(SessionApiError):
                store.record(
                    self.ref,
                    "stage2-input",
                    {"authored_storage_probe": 1},
                    derived_from={},
                    check_deadline=expire_before_work,
                )
        self.assertIsNone(store.resolve(self.ref, "stage2-input"))
        recovered = store.record(
            self.ref, "stage2-input", {"authored_storage_probe": 1}, derived_from={}
        )
        self.assertTrue(recovered["receipt_id"].endswith("-2"))
        checks.clear()

        def expire_after_file():
            checks.append(True)
            if len(checks) == 3:
                raise SessionApiError("session-deadline-exceeded", 408)

        with self.assertRaises(SessionApiError):
            store.record(
                self.ref,
                "stage2-selection",
                {"authored_storage_probe": 1},
                derived_from={},
                check_deadline=expire_after_file,
            )
        before = counts(self.intake)
        with self.assertRaisesRegex(SessionApiError, "write-outcome-unobserved"):
            store.record(
                self.ref,
                "stage2-selection",
                {"authored_storage_probe": 1},
                derived_from={},
            )
        self.assertEqual(counts(self.intake), before)

    def test_controller_requests_preserve_unknown_under_original_and_new_keys(self):
        store = ConnectionStore(self.intake, "own")
        stage = CONTROLLER_STAGE
        before_revision = self.intake.read("own", self.ref)["revision"]
        checks = []

        def expire_after_file():
            checks.append(True)
            if len(checks) == 3:
                raise SessionApiError("session-deadline-exceeded", 408)

        def record(key, revision, deadline=None):
            return store.record(
                self.ref,
                stage,
                {"authored_storage_probe": True},
                derived_from={},
                expected_revision=revision,
                request_key=key,
                maximum_projects=1,
                check_deadline=deadline,
            )

        with self.assertRaisesRegex(SessionApiError, "intake-operation-failed"):
            record("controller-first", before_revision, expire_after_file)
        unknown = counts(self.intake)
        current = self.intake.read("own", self.ref)["revision"]
        for key, revision in (
            ("controller-first", before_revision),
            ("controller-next", current),
        ):
            with self.subTest(key=key):
                with self.assertRaisesRegex(
                    SessionApiError, "write-outcome-unobserved"
                ):
                    record(key, revision)
        self.assertEqual(counts(self.intake), unknown)
        self.assertIsNone(store.resolve(self.ref, stage))

    def test_controller_can_retry_a_host_deadline_before_work(self):
        store = ConnectionStore(self.intake, "own")
        requester = SimpleNamespace(
            deadline=time.monotonic() + 10,
            connection=SimpleNamespace(settimeout=lambda _: None),
        )
        checks = []

        def expire_before_work():
            checks.append(True)
            if len(checks) == 2:
                requester.deadline = time.monotonic() - 1
            SessionHandler._remaining(requester)

        def record(key, deadline=None):
            return store.record(
                self.ref,
                CONTROLLER_STAGE,
                {"authored_storage_probe": True},
                derived_from={},
                expected_revision=self.intake.read("own", self.ref)["revision"],
                request_key=key,
                maximum_projects=1,
                check_deadline=deadline,
            )

        with self.assertRaisesRegex(SessionApiError, "intake-operation-failed"):
            record("controller-expired-before-work", expire_before_work)
        self.assertIsNone(store.resolve(self.ref, CONTROLLER_STAGE))
        self.assertEqual(record("controller-retry")["receipt_id"], "controller-retry")

    def test_receipt_pointer_damage_and_long_root_are_rejected(self):
        store = ConnectionStore(self.intake, "own")
        store.record(
            self.ref, "stage2-input", {"authored_storage_probe": 1}, derived_from={}
        )
        state = self.intake._load("researcher", self.ref)
        state["stage_connections"]["stage2-input"]["key"] = "never-saved"
        self.intake.db.execute(
            "UPDATE intake_projects SET state=? WHERE ref=?",
            (json.dumps(state), self.ref),
        )
        self.intake.db.commit()
        with self.assertRaisesRegex(SessionApiError, "receipt-differs"):
            store.resolve(self.ref, "stage2-input")
        from research_workspace_native.project_stage1 import ProjectStage1Service

        native = ProjectStage1Service(self.intake)
        if os.name == "nt":
            with self.assertRaisesRegex(
                SessionApiError, "stage1-private-root-too-deep"
            ):
                native._output(self.ref, "long-root-" * 16)
        else:
            self.assertEqual(
                native._output(self.ref, "long-root-" * 16).name, "long-root-" * 16
            )

    def test_first_saved_selection_read_without_pointer_does_not_register(self):
        ui, _, _ = self.prepare_choice()
        binding = ui.bindings[self.ref]
        original = ui.read("own", self.ref)

        def read_state():
            return (
                counts(self.intake),
                self.intake.read("own", self.ref)["revision"],
                tuple(
                    sorted(
                        p.name
                        for p in self.store_root.joinpath(self.ref).glob(
                            "connection-*.json"
                        )
                    )
                ),
            )

        before = read_state()
        for reopen in (False, True):
            if reopen:
                self.intake.close()
                self.intake = ProjectIntakeService(
                    self.store_root, authenticate=self.authenticate
                )
            store = ConnectionStore(self.intake, "own")
            candidate = ProjectStage2SelectionView(
                self.intake, BindingTable({}, store, {self.ref: object()})
            )
            self.assertIsNone(store.resolve(self.ref, "stage2-selection"))
            with patch(
                "research_workspace_native.project_stage_connections._completed_binding",
                return_value=binding,
            ):
                for _ in range(2):
                    readback = candidate.read("own", self.ref)
                    self.assertEqual(read_state(), before)
                    self.assertEqual(readback, original)
            self.assertIsNone(store.resolve(self.ref, "stage2-selection"))

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
        self.intake.close()
        self.intake = ProjectIntakeService(
            self.store_root, authenticate=self.authenticate
        )
        store = ConnectionStore(self.intake, "own")
        dynamic = ProjectStage2SelectionView(self.intake, BindingTable({}, store))
        self.assertEqual(dynamic.read("own", self.ref), actual)
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


class SelectionRegistrationHttpTests(Stage2SelectionFixture):
    def setUp(self):
        def authenticate_fixture(credential):
            return "local-viewer" if credential in ("own", VIEWER) else None

        def local_viewer_intake(root, *, authenticate):
            return ProjectIntakeService(root, authenticate=authenticate_fixture)

        with patch.object(
            activation_fixture, "ProjectIntakeService", local_viewer_intake
        ):
            super().setUp()
        self.authenticate = authenticate_fixture

    def test_http_requires_explicit_current_selection_registration(self):
        ui, _, _ = self.prepare_choice()
        binding = ui.bindings[self.ref]

        @contextmanager
        def serve_selection():
            store = ConnectionStore(self.intake, VIEWER)
            table = BindingTable({}, store)
            selection = ProjectStage2SelectionService(self.intake, table)
            with ProjectHost(
                projects=self.intake,
                credential=VIEWER,
                stage2=ProjectStage2Service(self.intake),
                stage2_selection=selection,
                files={},
                views=[],
                port=0,
            ) as host:
                install_stage2_continuation(host, profile)
                connections = host.project_stage2_controllers
                table.controllers = {self.ref: sentinel}
                thread = threading.Thread(target=host.serve_forever)
                thread.start()
                try:
                    with patch.object(
                        connections,
                        "driver",
                        side_effect=lambda _, ref, __: (
                            sentinel if ref == self.ref else None
                        ),
                    ):
                        yield host.expected_origin, store, selection, connections
                finally:
                    host.shutdown()
                    thread.join(5)
                    self.assertFalse(thread.is_alive())

        profile = SimpleNamespace(sha256="a" * 64)
        sentinel = object()
        project = self.intake.read("own", self.ref)
        body = {
            key: project[key] for key in ("revision", "input_version", "brief_sha256")
        }
        body.update(
            key="register-saved-choice",
            stage="stage2-selection",
            confirmed=True,
            profile_sha256=profile.sha256,
        )
        route = f"/api/projects/{self.ref}"
        registration = route + "/connections"
        other = self.intake.create("own", {"key": "wrong-project", "topic": "Other"})[
            "project_ref"
        ]
        before = counts(self.intake)
        with (
            patch(
                "research_workspace_native.project_stage_connections._completed_binding",
                return_value=binding,
            ),
            serve_selection() as (origin, store, selection, connections),
        ):
            status, first = request(origin, route + "/stage2/selection", token=VIEWER)
            self.assertEqual(status, 200, first)
            self.assertEqual(first["selection_status"], "pending")
            self.assertFalse(first["execution_authorized"])
            self.assertEqual(
                request(origin, route + "/stage2/selection", token=VIEWER), (200, first)
            )
            self.assertEqual(counts(self.intake), before)
            with self.assertRaisesRegex(
                SessionApiError, "stage2-selection-unconnected"
            ):
                selection._current("own", self.ref)

            def register(payload=body):
                return request(origin, registration, token=VIEWER, body=payload)

            for payload, expected_status in (
                ({**body, "input_version": str(body["input_version"])}, 400),
                ({**body, "input_version": body["input_version"] + 1}, 409),
                ({**body, "profile_sha256": "b" * 64}, 409),
                ({**body, "confirmed": False}, 400),
            ):
                with self.subTest(payload=payload):
                    self.assertEqual(register(payload)[0], expected_status)
            self.assertEqual(
                request(origin, registration, token=None, body=body)[0], 401
            )
            self.assertEqual(
                request(
                    origin,
                    f"/api/projects/{other}/connections",
                    token=VIEWER,
                    body=body,
                )[0],
                409,
            )
            with patch.dict(connections.static, {self.ref: sentinel}):
                self.assertEqual(
                    register(),
                    (409, {"error": "stage2-selection-dynamic-controller-required"}),
                )
            self.assertEqual(counts(self.intake), before)
            self.assertIsNone(store.resolve(self.ref, "stage2-selection"))
            with ThreadPoolExecutor(max_workers=2) as pool:
                replies = [pool.submit(register) for _ in range(2)]
                saved, replay = [reply.result() for reply in replies]
            self.assertEqual(saved[0], 200, saved)
            self.assertEqual(saved, replay)
            self.assertFalse(saved[1]["execution_authorized"])
            self.assertEqual(
                saved[1]["connections"]["stage2-selection"]["receipt_id"], body["key"]
            )

        after = {
            "intake_actions": before["intake_actions"] + 1,
            "intake_events": before["intake_events"] + 2,
        }
        self.assertEqual(counts(self.intake), after)
        self.intake.close()
        self.intake = ProjectIntakeService(
            self.store_root, authenticate=self.authenticate
        )
        with (
            patch(
                "research_workspace_native.project_stage_connections._completed_binding",
                return_value=binding,
            ),
            serve_selection() as (origin, _, _, _),
        ):
            self.assertEqual(
                request(origin, registration, token=VIEWER, body=body), saved
            )
            status, registered = request(
                origin, route + "/stage2/selection", token=VIEWER
            )
            self.assertEqual(status, 200, registered)
            self.assertEqual(registered["cards"], first["cards"])
            self.assertEqual(registered["selection_status"], "pending")
            self.assertEqual(counts(self.intake), after)

            current = self.intake.read("own", self.ref)
            self.intake.revise(
                "own",
                self.ref,
                dict(
                    key="revise-fixture-after-registration",
                    revision=current["revision"],
                    input_version=current["input_version"],
                    brief_sha256=current["brief_sha256"],
                    topic=current["brief"]["original_description"],
                    needs=[
                        {
                            "need_id": "consumption",
                            "question": "Synthetic household question",
                        }
                    ],
                ),
            )
            self.assertEqual(self.intake.read("own", self.ref)["input_version"], 2)
            revised = counts(self.intake)
            self.assertEqual(
                request(origin, registration, token=VIEWER, body=body),
                (409, {"error": "stage2-selection-project-stale"}),
            )
            self.assertEqual(counts(self.intake), revised)


if __name__ == "__main__":
    unittest.main()

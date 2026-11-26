"""Current native input and saved selection connections; authored engineering only."""

# ruff: noqa: E402 -- exercise the plugin and ordinary Wiki composition together.

from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import threading
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
from research_workspace_native.project_model import ProjectModelService
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.project_stage2_current_evidence import current_evidence
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage_connections import (
    CONTROLLER_STAGE,
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
def wiki(case, controllers=None):
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
            legacy = current_evidence(
                case.delivery,
                VIEWER,
                case.stage1.read(VIEWER, ref),
                case.intake.read(VIEWER, ref),
            )
            self.assertEqual(legacy["status"], "received")
            resources = (
                case.intake._path(ref, "s2r-" + legacy["source_descriptor_sha256"][:32])
                / "resources.txt"
            )
            original_resources = resources.read_bytes()
            with wiki(case) as origin:
                try:
                    resources.write_bytes(original_resources + b"tampered")
                    rejected = request(origin, route + "/stage2")[1]
                    self.assertEqual(
                        rejected["current_evidence"]["reason"],
                        "stage2-input-bytes-differ",
                    )
                    self.assertIsNone(rejected["current_evidence"]["receipt_id"])
                    self.assertEqual(rejected["offers"], [])
                    self.assertEqual(counts(case.intake), before)
                finally:
                    resources.write_bytes(original_resources)
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
                self.assertEqual(overview["stage2"]["offers"], [accepted["offer"]])
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
        driver = ProjectStage2ControllerDriver(
            service,
            spec=preparation.spec,
            controller_dir=data["root"] / "controller",
            delivery_dir=data["root"] / "controller-delivery",
            prerequisite_handler=CurrentCorePreparation(preparation),
        )
        with patch(
            "stage2_live.controller._ProductionAdapter",
            return_value=CurrentCoreSyntheticAdapter(),
        ):
            completed = driver.run(
                VIEWER, ref, key="authored-fixed-engineering-controller"
            )
        self.assertEqual(completed["status"], "saved", completed)
        before = counts(case.intake)
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
            self.assertEqual(
                selected["revision"], case.intake.read(VIEWER, ref)["revision"]
            )
            self.assertFalse(selected["execution_authorized"])
            self.assertTrue(selected["cards"])
            after = counts(case.intake)
            self.assertEqual(after["intake_actions"] - before["intake_actions"], 1)
            self.assertEqual(
                request(origin, f"/api/projects/{ref}/stage2/selection"),
                (200, selected),
            )
            self.assertEqual(counts(case.intake), after)
        case.reopen()
        with wiki(case) as origin:
            self.assertEqual(
                request(origin, f"/api/projects/{ref}/stage2/selection"),
                (200, selected),
            )
            self.assertEqual(counts(case.intake), after)
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
                table.receive_completed(self.ref)

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


if __name__ == "__main__":
    unittest.main()

"""Native same-project input reception through ordinary ProjectHost HTTP."""

from contextlib import closing, contextmanager
from hashlib import sha256
import json
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from current_core_stage12_fixtures import current_core_stage1_case
from planned_query_raw_runner import run_cases
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1 import ProjectStage1Service
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.project_stage2_current_evidence import current_evidence
from stage1_ledger.journal import canonical
import project_stage1_query_cases as owned_fixture
import test_project_stage1_delivery as delivery_fixture

VIEWER = secrets.token_urlsafe(32)
OTHER_VIEWER = secrets.token_urlsafe(32)


def authenticate(credential):
    return {
        "alice-token": "local-viewer",
        VIEWER: "local-viewer",
        OTHER_VIEWER: "other-viewer",
    }.get(credential)


@contextmanager
def serve(case):
    with ProjectHost(
        projects=case.intake,
        credential=VIEWER,
        stage1=case.stage1,
        stage2=ProjectStage2Service(case.intake),
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
                raise RuntimeError("HTTP listener did not stop")


def request(origin, route, *, token=VIEWER, body=None):
    headers = {"Origin": origin, "Sec-Fetch-Site": "same-origin"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        response = urlopen(
            Request(
                origin + route,
                data=None if body is None else canonical(body),
                headers=headers,
            ),
            timeout=25,
        )
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


class ProjectStage2CurrentEvidenceTests(unittest.TestCase):
    def setUp(self):
        identity = patch("test_project_stage1_delivery.authenticate", authenticate)
        identity.start()
        self.addCleanup(identity.stop)

    def test_missing_query_guard_blocks_owned_snapshot_at_receiver_boundary(self):
        with (
            TemporaryDirectory(prefix="s2-owner-") as directory,
            closing(
                ProjectIntakeService(Path(directory), authenticate=authenticate)
            ) as intake,
        ):
            created = intake.create(
                VIEWER, {"key": "owned-boundary", "topic": "Offline boundary test"}
            )
            project = intake.read(VIEWER, created["project_ref"])
            stage1 = {
                "ledger": {"next_allowed_action": "stop-sufficient"},
                "checkpoint": {"event_id": "e000001", "current": True},
            }
            # Simulate an owned source snapshot at the receiver boundary after
            # the query owner became unavailable. No project row is overridden.
            delivery = SimpleNamespace(
                intake=intake,
                stage1=SimpleNamespace(intake=intake, query_service=None),
                _saved_context=Mock(
                    return_value=(None, None, None, {"query_owned": True}, None, None)
                ),
                binding=Mock(
                    side_effect=AssertionError(
                        "missing owner cannot validate a package"
                    )
                ),
            )
            result = current_evidence(delivery, VIEWER, stage1, project)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(
                result["reason"], "stage2-current-evidence-owner-unavailable"
            )
            self.assertFalse(result["execution_authorized"])
            self.assertFalse(intake.db.in_transaction)
            delivery.binding.assert_not_called()

    def test_cold_owned_project_reads_stage2_with_owner_unavailable(self):
        run_cases(
            "test_project_stage2_current_evidence.ProjectStage2CurrentEvidenceTests._cold_owned_project",
            self,
        )

    def _cold_owned_project(self):
        case = owned_fixture.ProjectQueryCases()
        self.addCleanup(case.doCleanups)
        with patch.object(owned_fixture, "authenticate", authenticate):
            case.setUp()
        case.authorize()
        case.bootstrap()
        self.assertEqual(
            case.stage1.read(VIEWER, case.ref)["stage1_status"], "query-ledger-active"
        )
        other = case.intake.create(
            VIEWER, {"key": "other-project", "topic": "Other offline project"}
        )
        case.queries.close()
        case.intake.close()
        with closing(
            ProjectIntakeService(case.root / "p", authenticate=authenticate)
        ) as reopened:
            cold = SimpleNamespace(
                intake=reopened, stage1=ProjectStage1Service(reopened)
            )
            with serve(cold) as origin:
                path = f"/api/projects/{case.ref}"
                status, stage2 = request(origin, path + "/stage2")
                self.assertEqual(status, 200)
                evidence = stage2["current_evidence"]
                self.assertEqual(evidence["status"], "blocked", evidence)
                self.assertEqual(
                    evidence["reason"], "stage2-current-evidence-owner-unavailable"
                )
                self.assertEqual(
                    (stage2["offers"], stage2["activation"], stage2["frontier"]),
                    ([], None, None),
                )
                status, overview = request(origin, path + "/overview")
                self.assertEqual(status, 200)
                self.assertEqual(
                    overview["stage1"]["stage1_status"], "query-runtime-unconnected"
                )
                self.assertEqual(overview["stage2"], stage2)
                self.assertEqual(
                    request(origin, path + "/stage2/offers"), (200, stage2)
                )
                status, unrelated = request(
                    origin, f"/api/projects/{other['project_ref']}/stage2"
                )
                self.assertEqual(status, 200)
                self.assertEqual(unrelated["project_ref"], other["project_ref"])
                self.assertEqual(
                    unrelated["current_evidence"]["reason"],
                    "stage1-current-checkpoint-unavailable",
                )

    def test_receive_and_reopen_one_offline_packet_without_activation(self):
        with current_core_stage1_case(screened=True) as data:
            case, ref = data["case"], data["project_ref"]
            route = "/api/projects/" + ref
            database = case.intake_root / "project-intake.sqlite"
            case.reopen()
            sha_before = sha256(database.read_bytes()).hexdigest()
            with serve(case) as origin:
                status, initial = request(origin, route + "/stage2")
                self.assertEqual(status, 200)
                accepted = initial["current_evidence"]
                self.assertEqual(accepted["status"], "received", accepted)
                self.assertIs(type(accepted["input_version"]), int)
                self.assertIs(accepted["execution_authorized"], False)
                self.assertEqual(
                    accepted["source"]["manifest_sha256"], data["manifest_sha256"]
                )
                self.assertEqual(
                    accepted["source"]["checkpoint_event_id"],
                    data["checkpoint"]["event_id"],
                )
                self.assertEqual(accepted["source_count"], 1)
                self.assertEqual(accepted["candidate_count"], 0)
                self.assertEqual(accepted["packet_schema_version"], "2.7.0")
                self.assertEqual(
                    (initial["offers"], initial["activation"], initial["frontier"]),
                    ([], None, None),
                )
                self.assertEqual(
                    request(origin, route + "/stage2/selection"),
                    (409, {"error": "stage2-selection-unconnected"}),
                )
                status, overview = request(origin, route + "/overview")
                self.assertEqual((status, overview["stage2"]), (200, initial))
                self.assertEqual(
                    request(origin, route + "/stage2/offers"), (200, initial)
                )
                self.assertEqual(
                    request(origin, route + "/stage2", token=OTHER_VIEWER),
                    (401, {"error": "credential-rejected"}),
                )
                self.assertEqual(
                    request(origin, route + "/stage2", token=None),
                    (401, {"error": "credential-required"}),
                )
            [receiver] = list((case.intake_root / ref).glob("s2r-*"))
            self.assertEqual(
                sha256((receiver / "receipt.json").read_bytes()).hexdigest(),
                accepted["receipt_sha256"],
            )
            self.assertEqual(
                json.loads((receiver / "seed/packet.json").read_bytes())["packet_id"],
                accepted["packet_id"],
            )
            before = sorted(
                (str(p), p.stat().st_mtime_ns)
                for p in receiver.rglob("*")
                if p.is_file()
            )
            case.reopen()
            with serve(case) as origin:
                self.assertEqual(request(origin, route + "/stage2"), (200, initial))
                self.assertEqual(request(origin, accepted["stage1_atlas_url"])[0], 200)
                bad_version = accepted["stage1_atlas_url"].replace(
                    "/atlas/1/", "/atlas/2/"
                )
                self.assertEqual(
                    request(origin, bad_version),
                    (409, {"error": "stale-input-version"}),
                )
                self.assertEqual(
                    sorted(
                        (str(p), p.stat().st_mtime_ns)
                        for p in receiver.rglob("*")
                        if p.is_file()
                    ),
                    before,
                )
                # Remove only our derived completion marker, leaving the real
                # source and packet untouched. Refresh preserves the unknown.
                marker = receiver / "receipt.json"
                original = marker.read_bytes()
                receipt = json.loads(original)
                receipt["source"]["input_version"] = "1"
                marker.write_bytes(canonical(receipt))
                status, invalid = request(origin, route + "/stage2")
                self.assertEqual(status, 200)
                self.assertEqual(
                    invalid["current_evidence"]["reason"],
                    "stage2-current-input-receipt-binding-differs",
                )
                marker.write_bytes(original)
                (receiver / "receipt.json").rename(receiver / "unobserved.json")
                status, pending = request(origin, route + "/stage2")
                self.assertEqual(status, 200)
                self.assertEqual(
                    pending["current_evidence"]["reason"],
                    "stage2-current-input-publication-unobserved",
                )
                self.assertFalse((receiver / "receipt.json").exists())
            self.assertEqual(sha256(database.read_bytes()).hexdigest(), sha_before)
            self.assertEqual(
                data["zero_callback_counts"],
                {"query_runner": 0, "source_service": 0, "model": 0},
            )
            with serve(case) as origin:
                status, saved = request(
                    origin,
                    route + "/stage1/checkpoint",
                    body={
                        "key": "new-checkpoint",
                        "revision": accepted["revision"],
                        "input_version": accepted["input_version"],
                        "brief_sha256": accepted["brief_sha256"],
                        "ledger_state_sha256": accepted["source"][
                            "ledger_state_sha256"
                        ],
                        "confirmed": True,
                    },
                )
                self.assertEqual(status, 200, saved)
                self.assertNotEqual(
                    saved["checkpoint_event_id"], accepted["checkpoint_event_id"]
                )
                status, projection = request(origin, route + "/stage2")
                self.assertEqual(status, 200)
                current = projection["current_evidence"]
                self.assertEqual(current["input_version"], accepted["input_version"])
                self.assertEqual(
                    current["checkpoint_event_id"], saved["checkpoint_event_id"]
                )
                self.assertEqual(current["reason"], "stage1-delivery-offer-stale")
                self.assertNotIn("packet_sha256", current)
                self.assertEqual(
                    list((case.intake_root / ref).glob("s2r-*")), [receiver]
                )

    def test_no_checkpoint_and_ineligible_gate_leave_intake_unchanged(self):
        delivery_fixture.ProjectStage1DeliveryTests.setUpClass()
        case = delivery_fixture.ProjectStage1DeliveryTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        fixture = case.saved(checkpoint=True)
        ref = fixture["ref"]
        with serve(case) as origin:
            status, overview = request(origin, f"/api/projects/{ref}/overview")
            self.assertEqual(status, 200)
            current = overview["stage2"]["current_evidence"]
            self.assertEqual(current["status"], "blocked")
            self.assertEqual(
                current["gate_blockers"],
                overview["stage1"]["ledger"]["gate"]["blocking_items"],
            )
            self.assertGreater(len(current["gate_blockers"]), 0)
            self.assertEqual(current["reason"], "stage1-not-eligible-for-stage2")
            status, created = request(
                origin,
                "/api/projects",
                body={"key": "missing-source", "topic": "Offline second project"},
            )
            self.assertEqual(status, 200)
            other = created["project_ref"]
            status, projection = request(origin, f"/api/projects/{other}/stage2")
            self.assertEqual(status, 200)
            self.assertEqual(
                projection["current_evidence"]["reason"],
                "stage1-current-checkpoint-unavailable",
            )
            self.assertEqual(projection["offers"], [])
        self.assertFalse(list(Path(case.intake_root).glob("*/s2r-*")))


if __name__ == "__main__":
    unittest.main()

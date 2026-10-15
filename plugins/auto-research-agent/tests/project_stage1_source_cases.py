"""Actual Core/SQLite source-job tests; authored runner, zero acquisition.

The typed runner only observes causal SQLite state and raises an authored
failure. It does not fetch a URL, publish a receipt, read a paper or authenticate
native execution. Tests use the existing confirmed-intake/source-offer fixture
and real resource reservations. Private-output and runtime guards stay intact.
"""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_resource_budget import resource_view
from research_workspace_native.project_stage1 import ProjectStage1Service
from research_workspace_native.project_stage1_source_service import (
    ProjectStage1SourceService,
    SourceJobRunner,
    STORE,
)
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
from test_project_source_permit import ProjectSourcePermitTests, source_config
from test_project_stage1_library import Stage1LibraryFixture, library_authenticate
from test_workspace_project_intake import bound_body


class AuthoredFailureRunner(SourceJobRunner):
    """Synthetic server seam, deliberately incapable of acquisition."""

    binding_sha256 = "2" * 64
    resolver_sha256 = "3" * 64

    def __init__(self, case):
        self.case = case
        self.calls = []
        self.owner_loss = False

    def run(self, request, output_dir, *, check_current):
        check_current()
        case = self.case
        state = case.intake._load(case.principal, case.ref)
        job = next(
            row
            for row in state[STORE]["jobs"].values()
            if row["transport_request"] == request
        )
        case.assertEqual(job["status"], "dispatching")
        case.assertIs(job["invocation_claimed"], True)
        case.assertEqual(job["invocation_observation"], "unobserved")
        case.assertEqual(Path(output_dir), Path(job["binding"]["output_dir"]))
        action = case.intake.action(case.token, job["key"], project_ref=case.ref)
        case.assertEqual(action["status"], "saved")
        resource = resource_view(case.intake, state, case.principal)
        case.assertGreaterEqual(resource["reserved"]["source_reads"], 1)
        reservation = state["project_resource_reservations"]["reservations"][
            job["request_sha256"]
        ]
        case.assertEqual(reservation["key"], job["key"])
        case.assertEqual(reservation["seconds"], job["binding"]["reservation_seconds"])
        self.calls.append(deepcopy(request))
        if self.owner_loss:
            case.sources.close()
            check_current()
        raise OSError("Authored offline runner failure; no source I/O performed")


class AuthoredReceiptRunner(AuthoredFailureRunner):
    """Only author private bytes in the existing parser fixture receipt format.

    Peer, HTTP and timestamp fields below are synthetic inputs for the physical
    receipt validator. No resolver, transport, SDK parser or external reader
    executes; accepting this fixture is not proof of an actual HTTP response.
    The field shape is from AcquiredSourceParserTests.fixture, with exact job
    request hashes and timestamps rebound to this service's authored clock.
    """

    def run(self, request, output_dir, *, check_current):
        check_current()
        self.calls.append(deepcopy(request))
        root = Path(output_dir)
        (root / "raw").mkdir(parents=True)
        raw = b"Authored public-receipt fixture bytes, no source acquisition."
        raw_path = root / "raw/001-response.html"
        raw_path.write_bytes(raw)
        began = datetime.fromtimestamp(
            self.case.now[0] + 0.01, timezone.utc
        ).isoformat()
        ended = datetime.fromtimestamp(
            self.case.now[0] + 0.02, timezone.utc
        ).isoformat()
        attempt = dict(
            sequence=1,
            url=request["source_uri"],
            started_at=began,
            finished_at=ended,
            resolved_addresses=["93.184.216.34"],
            selected_address="93.184.216.34",
            peer_address="93.184.216.34",
            http_request_attempted=True,
            http_status=200,
            content_type="text/html",
            outcome="http-body-complete",
            raw_path="raw/001-response.html",
            raw_sha256=sha(raw),
            body_bytes=len(raw),
            body_complete=True,
            error_code=None,
        )
        receipt = dict(
            kind="PublicSourceAcquisitionReceipt",
            schema_version="1.0.0",
            request=request,
            request_sha256=sha(canonical(request)),
            output_dir=str(root),
            started_at=began,
            finished_at=ended,
            status="completed",
            outcome="http-body-complete",
            final_url=request["source_uri"],
            http_attempts=1,
            http_requests_attempted=1,
            aggregate_bytes=len(raw),
            attempts=[attempt],
            selected_attempt_sequence=1,
            raw_path=attempt["raw_path"],
            raw_sha256=attempt["raw_sha256"],
            content_type=attempt["content_type"],
            body_bytes=len(raw),
            body_complete=True,
        )
        path = root / "public-source-acquisition.json"
        path.write_bytes(canonical(receipt) + b"\n")
        check_current()
        return dict(receipt_path=path.name, receipt_sha256=sha(path.read_bytes()))


class SourceServiceTests(Stage1LibraryFixture, unittest.TestCase):
    new = ProjectSourcePermitTests.new
    reserve_source = ProjectSourcePermitTests.reserve_source

    def setUp(self):
        # Short writable TEMP is an actual path, not a substituted private-output
        # guard. The original fixture prefix would exceed its Windows root cap.
        self.tmp = tempfile.TemporaryDirectory(prefix="s-")
        self._fixture_cleanup_started = False
        self.sources = None
        self.addCleanup(self._cleanup_fixture)
        self._setUp()
        self.now = [time.time()]
        self.transport = AuthoredFailureRunner(self)
        self.verifier_action = None
        self.materials_tmp = tempfile.TemporaryDirectory(prefix="sm-")
        self.addCleanup(self.materials_tmp.cleanup)
        self.materials = Path(self.materials_tmp.name).resolve()
        self.sources = self.service(self.transport)
        self.assertLessEqual(len(str(self.ledger.root)), 170)

    def tearDown(self):
        self._cleanup_fixture()

    def _cleanup_fixture(self):
        # unittest invokes tearDown before addCleanup. Close the current source
        # owner connection before the inherited fixture removes its directory.
        # The cleanup hook also covers a failed setUp; base cleanup runs once.
        if self._fixture_cleanup_started:
            return
        if self.sources is not None:
            self.sources.close()
        self._fixture_cleanup_started = True
        Stage1LibraryFixture.tearDown(self)

    def service(self, runner):
        def verify_config(config):
            if self.verifier_action is not None:
                return self.verifier_action(config)
            return True

        return ProjectStage1SourceService(
            self.intake,
            self.stage1,
            config=source_config(),
            materials_root=self.materials,
            runner=runner,
            verify_configuration=verify_config,
            clock=lambda: self.now[0],
        )

    def offered(self, name="pending"):
        return self.sources.offers(self.token, self.ref, self.work_by_name[name])

    def authorize(self, key="source-authorize", *, offer=None):
        offer = self.offered() if offer is None else offer
        body = dict(
            bound_body(self.intake.read(self.token, self.ref), key),
            work_ref=offer["work_ref"],
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            confirmed=True,
        )
        return self.sources.authorize(self.token, self.ref, body), body

    def execute_body(self, grant, key="source-execute"):
        return dict(
            bound_body(self.intake.read(self.token, self.ref), key),
            grant_ref=grant["grant_ref"],
            grant_sha256=grant["grant_sha256"],
            confirmed=True,
        )

    def queued(self):
        grant, authorization = self.authorize()
        body = self.execute_body(grant)
        result = self.sources.execute(self.token, self.ref, body)
        self.assertEqual(result["job_status"], "queued")
        self.assertEqual(len(self.transport.calls), 0)
        return grant, authorization, body

    def resources(self):
        return resource_view(
            self.intake, self.intake._load(self.principal, self.ref), self.principal
        )

    def reopen_all(self):
        old_intake, old_db, old_source = self.intake, self.intake.db, self.sources
        self.sources.close()
        self.intake.close()
        self.intake = ProjectIntakeService(self.root, authenticate=library_authenticate)
        self.stage1 = ProjectStage1Service(self.intake, query_runner=self.runner)
        self.sources = self.service(self.transport)
        self.assertIsNot(self.intake, old_intake)
        self.assertIsNot(self.intake.db, old_db)
        self.assertIsNot(self.sources, old_source)

    def test_get_and_exact_offer_are_read_only_and_do_not_claim_owner(self):
        before = self.inventory()
        view = self.sources.read(self.token, self.ref)
        offer = self.offered()
        self.assertFalse(view["stage1_complete"])
        self.assertFalse(view["automatic_dispatch"])
        self.assertFalse(offer["native_attestation"])
        self.assertFalse(offer["execution_authorized"])
        self.assertEqual(offer["document"]["limits"]["max_fetches"], 3)
        self.assertEqual(self.inventory(), before)
        self.assertNotIn(STORE, self.intake._load(self.principal, self.ref))
        self.assertFalse(self.transport.calls)
        self.runner.assert_not_called()

    def test_authentication_strict_body_configuration_and_selected_version_refuse(self):
        offer = self.offered()
        body = dict(
            bound_body(self.intake.read(self.token, self.ref), "bad-authorize"),
            work_ref=offer["work_ref"],
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            confirmed=True,
        )
        before = self.inventory()
        for credential, ref, changed in (
            ("invalid", self.ref, body),
            ("other-library-test-token-with-at-least-32-characters", self.ref, body),
            (self.token, self.ref + "-other", body),
            (self.token, self.ref, dict(body, confirmed=1)),
            (self.token, self.ref, dict(body, root=str(self.root))),
            (self.token, self.ref, dict(body, input_version=2)),
        ):
            with self.subTest(credential=credential, ref=ref, body=changed):
                with self.assertRaises(SessionApiError):
                    self.sources.authorize(credential, ref, changed)
                self.assertEqual(self.inventory(), before)
        original = deepcopy(self.sources.config)
        self.sources.config["execution_source_sha256"] = "4" * 64
        with self.assertRaisesRegex(SessionApiError, "source-offer-stale"):
            self.sources.authorize(self.token, self.ref, body)
        self.sources.config = original
        self.assertEqual(self.inventory(), before)
        self.query(3, [dict(self.metadata[2], version="v2")])
        changed = self.inventory()
        with self.assertRaisesRegex(SessionApiError, "source-offer-stale"):
            self.sources.authorize(self.token, self.ref, body)
        self.assertEqual(self.inventory(), changed)
        self.assertFalse(self.transport.calls)

    def test_unconnected_runner_refuses_before_intent_or_reservation(self):
        grant, _ = self.authorize()
        self.sources.runner = None
        body = self.execute_body(grant)
        before = self.inventory()
        with self.assertRaisesRegex(SessionApiError, "source-runner-unconnected"):
            self.sources.execute(self.token, self.ref, body)
        self.assertEqual(self.inventory(), before)
        self.assertEqual(self.resources()["reserved"]["source_reads"], 0)
        self.assertEqual(self.sources.read(self.token, self.ref)["jobs"], {})

    def test_causal_queue_real_sqlite_reopen_and_same_key_never_dispatch(self):
        _grant, _authorization, body = self.queued()
        resource = self.resources()
        self.assertEqual(resource["reserved"]["source_reads"], 1)
        self.assertEqual(resource["reserved"]["seconds"], 30)
        self.assertIsNone(resource["actual_seconds"])
        before = self.inventory()
        self.assertTrue(self.sources.execute(self.token, self.ref, body)["replayed"])
        self.assertEqual(self.inventory(), before)
        self.reopen_all()
        fresh = self.inventory()
        history = self.sources.history(self.token, self.ref)
        self.assertEqual(history["jobs"][body["key"]]["status"], "execution-unknown")
        self.assertEqual(history["jobs"][body["key"]]["saved_status"], "queued")
        self.assertEqual(self.inventory(), fresh)
        self.assertTrue(self.sources.execute(self.token, self.ref, body)["replayed"])
        restored = self.sources.reopen(self.token, self.ref)
        self.assertEqual(
            restored["jobs"][body["key"]]["saved_status"], "execution-unknown"
        )
        owner = self.intake._load(self.principal, self.ref)[STORE]["owner"]
        self.assertEqual(owner["epoch"], 2)
        self.sources.dispatch_pending(self.token, self.ref, body["key"])
        self.assertFalse(self.transport.calls)
        self.assertEqual(self.resources()["reserved"], resource["reserved"])

    def test_runner_failure_is_unknown_and_changed_payload_never_resends(self):
        _grant, _authorization, body = self.queued()
        result = self.sources.dispatch_pending(self.token, self.ref, body["key"])
        self.assertEqual(result["status"], "execution-unknown")
        self.assertEqual(len(self.transport.calls), 1)
        self.assertIsNone(result["result"])
        before = self.inventory()
        self.sources.dispatch_pending(self.token, self.ref, body["key"])
        self.sources.execute(self.token, self.ref, body)
        self.assertEqual(self.inventory(), before)
        with self.assertRaisesRegex(SessionApiError, "idempotency-payload-differs"):
            self.sources.execute(
                self.token, self.ref, dict(body, grant_sha256="f" * 64)
            )
        self.assertEqual(self.inventory(), before)
        self.assertEqual(len(self.transport.calls), 1)
        self.assertFalse(
            Path(
                self.intake._load(self.principal, self.ref)[STORE]["jobs"][body["key"]][
                    "binding"
                ]["output_dir"]
            ).exists()
        )

    def test_expiry_before_intent_and_queued_deadline_do_not_refund_or_dispatch(self):
        grant, _ = self.authorize()
        body = self.execute_body(grant)
        before = self.inventory()

        def expired():
            raise SessionApiError("authored-lock-owned-expiry", 408)

        with self.assertRaisesRegex(SessionApiError, "authored-lock-owned-expiry"):
            self.sources.execute(self.token, self.ref, body, check_deadline=expired)
        self.assertEqual(self.inventory(), before)
        self.assertEqual(self.resources()["reserved"]["source_reads"], 0)
        self.sources.execute(self.token, self.ref, body)
        resources = self.resources()
        self.now[0] += 31
        result = self.sources.dispatch_pending(self.token, self.ref, body["key"])
        self.assertEqual(result["status"], "refused-known-unsent")
        self.assertEqual(result["failure"]["code"], "source-job-deadline-expired")
        self.assertFalse(result["runner_invoked"])
        self.assertFalse(self.transport.calls)
        self.reopen_all()
        self.sources.reopen(self.token, self.ref)
        self.sources.dispatch_pending(self.token, self.ref, body["key"])
        self.assertEqual(self.resources()["reserved"], resources["reserved"])
        self.assertFalse(self.transport.calls)

    def test_owner_loss_after_dispatch_reopens_unknown_without_extra_io(self):
        _grant, _authorization, body = self.queued()
        self.transport.owner_loss = True
        result = self.sources.dispatch_pending(self.token, self.ref, body["key"])
        self.assertEqual(result["status"], "execution-unknown")
        self.assertEqual(len(self.transport.calls), 1)
        before = self.resources()["reserved"]
        self.reopen_all()
        self.sources.reopen(self.token, self.ref)
        self.sources.execute(self.token, self.ref, body)
        self.sources.dispatch_pending(self.token, self.ref, body["key"])
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(self.resources()["reserved"], before)

    def test_shared_actual_reservations_conserve_budget_and_never_auto_refund(self):
        self.reserve_source("other-actual-source-intent", 150)
        self.assertEqual(self.resources()["reserved"]["seconds"], 150)
        _grant, _authorization, body = self.queued()
        resource = self.resources()
        self.assertEqual(resource["reserved"]["seconds"], 180)
        self.assertEqual(resource["reserved"]["source_reads"], 2)
        self.assertEqual(resource["remaining"]["seconds"], 0)
        self.sources.dispatch_pending(self.token, self.ref, body["key"])
        self.reopen_all()
        self.sources.reopen(self.token, self.ref)
        self.assertEqual(self.resources()["reserved"], resource["reserved"])
        self.assertFalse(self.resources()["automatic_refund"])
        before = self.inventory()
        with self.assertRaisesRegex(
            SessionApiError, "project-source-requested-budget-insufficient"
        ):
            self.offered()
        self.assertEqual(self.inventory(), before)
        self.assertEqual(len(self.transport.calls), 1)

    def test_verifier_expiry_at_dispatch_retires_unsent_without_runner_io(self):
        _grant, _authorization, body = self.queued()
        reserved = self.resources()["reserved"]

        def expired_after_callback(_config):
            self.now[0] += 31
            return True

        self.verifier_action = expired_after_callback
        result = self.sources.dispatch_pending(self.token, self.ref, body["key"])
        self.assertEqual(result["status"], "refused-known-unsent")
        self.assertFalse(result["runner_invoked"])
        self.assertFalse(self.transport.calls)
        self.assertEqual(self.resources()["reserved"], reserved)
        self.reopen_all()
        history = self.sources.read(self.token, self.ref)
        self.assertEqual(
            history["jobs"][body["key"]]["saved_status"], "refused-known-unsent"
        )
        self.sources.dispatch_pending(self.token, self.ref, body["key"])
        self.assertFalse(self.transport.calls)

    def test_verifier_replacing_runner_refuses_before_execute_intent(self):
        grant, _ = self.authorize()
        body = self.execute_body(grant)
        replacement = AuthoredFailureRunner(self)

        def replace_runner(_config):
            self.sources.runner = replacement
            return True

        self.verifier_action = replace_runner
        before = self.inventory()
        with self.assertRaisesRegex(SessionApiError, "source-runner-instance-changed"):
            self.sources.execute(self.token, self.ref, body)
        self.assertEqual(self.inventory(), before)
        self.assertEqual(self.resources()["reserved"]["source_reads"], 0)
        self.assertFalse(self.transport.calls)
        self.assertFalse(replacement.calls)

    def test_physical_authored_receipt_expiring_during_save_cannot_commit_success(self):
        self.transport = AuthoredReceiptRunner(self)
        self.sources.close()
        self.sources = self.service(self.transport)
        _grant, _authorization, body = self.queued()
        reserved = self.resources()["reserved"]
        original_save = self.intake._save
        observation_save_calls = []

        def expire_after_actual_save(state, kind, payload):
            result = original_save(state, kind, payload)
            if kind == "source-job-observation-saved":
                observation_save_calls.append(kind)
                self.now[0] += 31
            return result

        with patch.object(self.intake, "_save", side_effect=expire_after_actual_save):
            result = self.sources.dispatch_pending(self.token, self.ref, body["key"])
        self.assertEqual(observation_save_calls, ["source-job-observation-saved"])
        self.assertEqual(result["status"], "execution-unknown")
        self.assertIsNone(result["result"])
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(self.resources()["reserved"], reserved)
        committed = self.intake.db.execute(
            "SELECT COUNT(*) FROM intake_events WHERE project=? AND kind=?",
            (self.ref, "source-job-observation-saved"),
        ).fetchone()[0]
        self.assertEqual(committed, 0)
        job = self.intake._load(self.principal, self.ref)[STORE]["jobs"][body["key"]]
        root = Path(job["binding"]["output_dir"])
        self.assertTrue((root / "public-source-acquisition.json").is_file())
        self.assertTrue((root / "raw/001-response.html").is_file())
        self.reopen_all()
        self.sources.reopen(self.token, self.ref)
        self.sources.execute(self.token, self.ref, body)
        self.sources.dispatch_pending(self.token, self.ref, body["key"])
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(self.resources()["reserved"], reserved)
        self.assertFalse(self.sources.read(self.token, self.ref)["core_source_bridge"])


def load_tests(loader, tests, pattern):
    return loader.loadTestsFromTestCase(SourceServiceTests)


if __name__ == "__main__":
    unittest.main()

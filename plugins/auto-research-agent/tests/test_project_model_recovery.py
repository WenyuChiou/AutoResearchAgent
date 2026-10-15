"""Real SQLite/HTTP/UI intent retirement, with no native or model execution."""

from copy import deepcopy
import threading
import unittest
from unittest.mock import patch

from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_model import ProjectModelService
from research_workspace_native.project_model_recovery import retired
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
import test_workspace_project_model as fixtures


class ModelRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.ProjectModelTests()
        self.case.setUp()

    def tearDown(self):
        self.case.tearDown()

    def unknown(self, *, principal="alice"):
        case = self.case
        authentication = (
            fixtures.authenticate
            if principal == "alice"
            else (lambda token: principal if token == "alice-token" else None)
        )
        case.intake.authenticate = authentication
        ref = case.project()
        offer, path = case.register(ref, principal=principal)
        original = case.body(ref, offer)
        with patch("research_workspace_native.project_model.threading.Thread") as t:
            t.return_value.is_alive.return_value = False
            case.model.execute("alice-token", ref, original)
        case.model.close()
        case.intake.close()
        case.intake = ProjectIntakeService(case.root, authenticate=authentication)
        case.model = ProjectModelService(case.intake, provider_factory=case.factory)
        case.model.register(
            ref,
            operation="suggest-topic",
            permit_path=path,
            permit_sha256=sha(path.read_bytes()),
        )
        return ref, offer, original

    def body(self, ref, *, key="end-unsent"):
        case = self.case
        job = case.model.history("alice-token", ref)["actions"][0]
        view = case.intake.read("alice-token", ref)
        return {
            "key": key,
            **{k: view[k] for k in ("revision", "input_version", "brief_sha256")},
            **{
                k: job["retirement_offer"][k]
                for k in ("job_ref", "job_request_sha256", "job_snapshot_sha256")
            },
            "confirmed": True,
            "user_input": "End the unsent attempt, retain Unknown.",
        }

    def change(self, ref, change):
        case = self.case
        case.model._transaction(
            "alice",
            ref,
            "synthetic-recovery-case",
            lambda s: (
                change(s["model_operations"]["jobs"][case.key]) or {"synthetic": True}
            ),
        )

    def test_true_reopen_retirement_preserves_unknown_budget_key_and_ui_intent(self):
        case = self.case
        ref, offer, original = self.unknown()
        before = case.model._job("alice", ref, case.key)
        resources = deepcopy(
            case.intake._load("alice", ref).get("project_resource_reservations")
        )
        body = self.body(ref)
        result = case.model.retire("alice-token", ref, body)
        self.assertEqual(result["retirement"]["status"], "retired-no-resend")
        after = case.model._job("alice", ref, case.key)
        self.assertEqual({k: v for k, v in after.items() if k != "retirement"}, before)
        self.assertTrue(retired(after))
        view = case.model.read("alice-token", ref)
        self.assertEqual(view["active_jobs"], [])
        self.assertEqual(
            (
                view["unknown_count"],
                view["blocking_unknown_count"],
                view["calls_reserved"],
            ),
            (1, 0, 1),
        )
        self.assertEqual(
            case.intake._load("alice", ref).get("project_resource_reservations"),
            resources,
        )
        replay = case.model.retire("alice-token", ref, {**body, "revision": 999})
        self.assertTrue(replay["replayed"])
        with self.assertRaises(SessionApiError):
            case.model.retire(
                "alice-token", ref, {**body, "user_input": "Changed reason"}
            )
        self.assertTrue(case.model.execute("alice-token", ref, original)["replayed"])
        public = case.model.history("alice-token", ref)["actions"][0]
        record = {
            "key": original["key"],
            "kind": "model-operation",
            "project_ref": ref,
            "request_sha256": public["request_sha256"],
        }
        self.assertEqual(case.actual_ui_reconcile(record, [public]), [])
        self.assertEqual((case.factories, case.io), (0, 0))

    def test_refuses_dispatch_active_worker_runtime_artifact_and_forged_target(self):
        case = self.case
        ref, _, _ = self.unknown()
        body = self.body(ref)
        for changed in ("job_request_sha256", "job_snapshot_sha256"):
            with self.assertRaisesRegex(SessionApiError, "target-differs"):
                case.model.retire("alice-token", ref, {**body, changed: "0" * 64})
        with self.assertRaises(SessionApiError):
            case.model.retire("bob-token", ref, body)
        for changed in ("owner", "root", "permit", "pid"):
            with self.assertRaisesRegex(SessionApiError, "fields"):
                case.model.retire("alice-token", ref, {**body, changed: "forged"})
        self.change(ref, lambda j: j.update(provider_reserved=True))
        with self.assertRaisesRegex(SessionApiError, "cleanup-unproven"):
            case.model.retire("alice-token", ref, self.body(ref))
        self.change(ref, lambda j: j.update(provider_reserved=False))
        thread = unittest.mock.Mock()
        thread.is_alive.return_value = True
        case.model._workers[(ref, case.key)] = thread
        with self.assertRaisesRegex(SessionApiError, "worker-active"):
            case.model.retire("alice-token", ref, self.body(ref))
        thread.is_alive.return_value = False
        job = case.model._job("alice", ref, case.key)
        folder = case.model._runtime_folder("alice", ref, job, create=True)
        (folder / "unobserved-native.sqlite3").write_bytes(b"Unverified")
        with self.assertRaisesRegex(SessionApiError, "runtime-unproven"):
            case.model.retire("alice-token", ref, self.body(ref))
        self.assertEqual((case.factories, case.io), (0, 0))
        self.assertEqual(
            case.model.read("alice-token", ref)["blocking_unknown_count"], 1
        )

    def test_binding_only_retirement_and_late_admission_are_fail_closed(self):
        case = self.case
        ref, offer, _ = self.unknown()
        job = case.model._job("alice", ref, case.key)
        folder = case.model._runtime_folder("alice", ref, job, create=True)
        marker = folder / "binding.json"
        original = marker.read_bytes()
        marker.write_bytes(
            canonical({**job["runtime_binding"], "principal": "bob"}) + b"\n"
        )
        with self.assertRaisesRegex(SessionApiError, "binding-collision"):
            case.model.retire("alice-token", ref, self.body(ref))
        marker.write_bytes(original)
        case.model.retire("alice-token", ref, self.body(ref))
        saved_offer = case.intake._load("alice", ref)["model_operations"]["offers"][
            offer["offer_ref"]
        ]
        event = {
            "phase": "reserve",
            "unit_key": "project-unit-" + sha(case.key.encode()),
            "prompt_sha256": job["prompt_sha256"],
            "source_sha256": job["source_sha256"],
            "permit_sha256": job["permit_sha256"],
        }
        with self.assertRaisesRegex(SessionApiError, "retired-no-resend"):
            case.model._admit("alice", ref, case.key, saved_offer, event)
        self.assertEqual((case.factories, case.io), (0, 0))

    def test_real_http_lost_response_history_no_resend_or_new_authority(self):
        case = self.case
        ref, _, _ = self.unknown(principal="local-viewer")
        token = "local-retirement-credential-at-least-32-characters"
        case.intake.authenticate = lambda value: (
            "local-viewer" if value in {token, "alice-token"} else None
        )
        host = ProjectHost(
            projects=case.intake,
            models=case.model,
            credential=token,
            files={},
            views=[],
            port=0,
        )
        server = threading.Thread(target=host.serve_forever, daemon=True)
        server.start()
        try:
            route = "/api/projects/" + ref
            body = self.body(ref)
            stale = {
                **body,
                "key": "stale-retirement",
                "revision": body["revision"] + 100,
            }
            code, rejected = case.http_request(
                host, token, route + "/models/retire", stale
            )
            self.assertEqual(code, 409, rejected)
            self.assertEqual(rejected["receipt"]["status"], "known-unsent")
            pending = {
                "key": stale["key"],
                "kind": "model-retirement",
                "project_ref": ref,
                "request_sha256": rejected["receipt"]["request_sha256"],
            }
            self.assertEqual(
                case.actual_ui_reconcile(pending, [rejected["receipt"]]), []
            )
            code, result = case.http_request(
                host, token, route + "/models/retire", body
            )
            self.assertEqual(code, 200, result)
            # Discard the response. Recovery reads saved observations only.
            code, page = case.http_request(host, token, route + "/models/actions/0")
            self.assertEqual(code, 200, page)
            self.assertEqual(page["actions"][0]["status"], "execution-unknown")
            self.assertEqual(
                page["actions"][0]["retirement"]["status"], "retired-no-resend"
            )
            code, replay = case.http_request(
                host, token, route + "/models/retire", body
            )
            self.assertEqual(code, 200, replay)
            self.assertTrue(replay["replayed"])
            code, _ = case.http_request(
                host, token, route + "/models/retire", {**body, "confirmed": False}
            )
            self.assertEqual(code, 400)
            self.assertEqual((case.factories, case.io), (0, 0))
        finally:
            host.shutdown()
            host.server_close()
            server.join(3)
            self.assertFalse(server.is_alive())


if __name__ == "__main__":
    unittest.main()

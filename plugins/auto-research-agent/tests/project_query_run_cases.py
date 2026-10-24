"""Original Core/query queue with fake subprocess capture; no external queries."""

from contextlib import contextmanager
from copy import deepcopy
import time
import unittest
from unittest.mock import patch

import project_stage1_query_cases as fixture
from research_workspace_native.project_stage1_run_grant import (
    ProjectStage1RunGrantService,
    SCOPE,
)
from research_workspace_native.project_run_authority import action_identity
from research_workspace_native.session_api import SessionApiError
from stage1_ledger.validation import validate_run
from stage1_retrieval.runtime_identity import verify_identity
from test_workspace_project_intake import bound_body


@contextmanager
def setup_case(*, consent_override=None):
    case = fixture.ProjectQueryCases(methodName="runTest")
    try:
        case.setUp()
        now = [time.time()]
        issuer = ProjectStage1RunGrantService(
            case.intake, runtime_sha256="a" * 64, clock=lambda: now[0]
        )
        case.queries.run_grants = issuer
        consent = (
            "Search this synthetic confirmed plan within its existing two-query resource cap."
            if consent_override is None
            else consent_override
        )
        grant = issuer.authorize(
            "alice-token",
            case.ref,
            {
                **bound_body(case.intake.read("alice-token", case.ref), "whole-run"),
                "confirmed": True,
                "user_input": consent,
                "scope": SCOPE,
                "operations": ["query"],
                "max_seconds": 100,
                "max_actions": 8,
            },
        )

        def derived(action, field):
            offer = case.queries.read("alice-token", case.ref)[field]
            body = {
                **bound_body(case.intake.read("alice-token", case.ref), "draft"),
                "confirmed": False,
                "offer_ref": offer["offer_ref"],
                "offer_sha256": offer["offer_sha256"],
            }
            if action == "query-authorize":
                body["user_input"] = consent
            token = issuer.derive(
                "alice-token",
                case.ref,
                grant_ref=grant["grant_ref"],
                grant_sha256=grant["grant_sha256"],
                operation="query",
                identity=action_identity(action, body),
            )
            body.update(
                key=token.key + "-work",
                revision=case.intake.read("alice-token", case.ref)["revision"],
            )
            return body, token

        yield case, issuer, grant, now, consent, derived
    finally:
        case.doCleanups()


def authorize(case, derived):
    body, token = derived("query-authorize", "authorization_offer")
    return (
        body,
        token,
        case.queries.authorize("alice-token", case.ref, body, run_authorization=token),
    )


def bootstrap(case, derived):
    body, token = derived("query-bootstrap", "bootstrap_offer")
    with patch(
        "stage1_retrieval.runtime_identity.verify_identity",
        side_effect=lambda pin, **kw: verify_identity(pin),
    ):
        result = case.queries.bootstrap(
            "alice-token", case.ref, body, run_authorization=token
        )
        case.queries.workers[case.ref].join(30)
        case.assertFalse(case.queries.workers[case.ref].is_alive())
    return body, token, result


class QueryRunTests(unittest.TestCase):
    def test_maximum_original_run_consent_stays_exact_without_widening_legacy(self):
        with setup_case(consent_override="x" * 8192) as (
            case,
            issuer,
            grant,
            now,
            consent,
            derived,
        ):
            body, token = derived("query-authorize", "authorization_offer")
            legacy = {**body, "confirmed": True}
            with self.assertRaises(SessionApiError):
                case.queries._request(legacy, authorization=True)
            result = case.queries.authorize(
                "alice-token", case.ref, body, run_authorization=token
            )
            self.assertEqual(result["status"], "saved", result)
            state = case.intake._load("alice", case.ref)
            authorization = state["stage1_query_authorization"]
            _, permit = case.queries._inspect_seal(
                case.intake, case.ref, authorization, case.queries.config, ready=False
            )
            self.assertEqual(permit["user_input"], consent)
            self.assertEqual(permit["run_request"]["run_user_input"], consent)
            self.assertEqual(permit["run_request"]["user_input"], consent)
            self.assertEqual(
                case.queries.read("alice-token", case.ref)["budget"],
                dict(probes=0, attempts=0, seconds=0),
            )

    def test_derived_seal_bootstrap_capture_extract_replay_and_no_json_authority(self):
        with setup_case() as (case, issuer, grant, now, consent, derived):
            body, token = derived("query-authorize", "authorization_offer")
            for credential, authority in [("bob-token", token), ("alice-token", {})]:
                with (
                    self.subTest(credential=credential),
                    self.assertRaises(SessionApiError),
                ):
                    case.queries.authorize(
                        credential, case.ref, body, run_authorization=authority
                    )
            with self.assertRaises(SessionApiError):
                case.queries.authorize("alice-token", case.ref, body)
            receipt = case.queries.authorize(
                "alice-token", case.ref, body, run_authorization=token
            )
            self.assertEqual(receipt["status"], "saved", receipt)
            state = case.intake._load("alice", case.ref)
            seal = state["stage1_query_authorization"]["permit"]
            self.assertEqual(seal["schema_version"], "1.1.0")
            self.assertFalse(seal["run_request"]["confirmed"])
            self.assertEqual(seal["run_request"]["run_user_input"], consent)
            self.assertLessEqual(seal["expires_at_unix"], grant["expires_at"])
            self.assertTrue(
                case.queries.authorize(
                    "alice-token", case.ref, body, run_authorization=token
                )["replayed"]
            )
            manual = case.body("bootstrap_offer", "manual-mixed-authority")
            with self.assertRaisesRegex(
                SessionApiError, "query-run-request-mode-differs"
            ):
                case.queries.bootstrap("alice-token", case.ref, manual)
            self.assertEqual(
                case.queries.read("alice-token", case.ref)["budget"],
                dict(probes=0, attempts=0, seconds=0),
            )
            bb, bt, _ = bootstrap(case, derived)
            view = case.queries.read("alice-token", case.ref)
            self.assertEqual(view["jobs"][0]["status"], "completed", view)
            state = case.intake._load("alice", case.ref)
            registration = next(iter(state["stage1_query_jobs"].values()))[
                "registration"
            ]
            self.assertIs(type(registration["project_input_version"]), int)
            self.assertIs(type(registration["input_version"]), str)
            self.assertEqual(
                registration["input_version"],
                case.intake.read("alice-token", case.ref)["brief_sha256"],
            )
            body, token = derived("query-execute", "query_offer")
            with case.fake_runner(), case.no_probe():
                queued = case.queries.execute(
                    "alice-token", case.ref, body, run_authorization=token
                )
                service = case.queries.services[case.ref]
                service._workers[case.ref].join(30)
                self.assertFalse(service._workers[case.ref].is_alive())
            action = service.get_action(
                "alice-token", case.ref, queued["query_action_key"]
            )
            self.assertEqual(action["status"], "completed", action)
            self.assertFalse(action["request"]["confirmed"])
            self.assertEqual(
                action["request"]["run_authority"],
                token.check(case.intake, "alice", case.ref, "query", token.identity),
            )
            self.assertTrue(action["result"]["execution_ref"])
            self.assertGreater(
                case.stage1.read("alice-token", case.ref)["ledger"]["counts"]["works"],
                0,
            )
            self.assertEqual(len(case.children), 1)
            self.assertTrue(
                case.queries.execute(
                    "alice-token", case.ref, body, run_authorization=token
                )["replayed"]
            )
            self.assertTrue(
                case.queries.bootstrap(
                    "alice-token", case.ref, bb, run_authorization=bt
                )["replayed"]
            )
            self.assertEqual(
                case.queries.read("alice-token", case.ref)["budget"],
                dict(probes=1, attempts=1, seconds=62),
            )
            self.assertEqual(len(case.children), 1)
            self.assertTrue(validate_run(registration["ledger_root"])["valid"])
            before = deepcopy(state["stage1_query_authorization"])
            case.queries.run_grants = None
            self.assertEqual(
                case.queries.read("alice-token", case.ref)["status"],
                "unavailable-or-stale",
            )
            self.assertEqual(
                case.intake._load("alice", case.ref)["stage1_query_authorization"],
                before,
            )
            case.queries.run_grants = issuer

    def test_fresh_query_owner_reconstructs_saved_run_proofs_without_resending(self):
        with setup_case() as (case, issuer, grant, now, consent, derived):
            authorize(case, derived)
            bootstrap(case, derived)
            body, token = derived("query-execute", "query_offer")
            with case.fake_runner(), case.no_probe():
                queued = case.queries.execute(
                    "alice-token", case.ref, body, run_authorization=token
                )
                case.queries.services[case.ref]._workers[case.ref].join(30)
            self.assertEqual(len(case.children), 1)
            case.queries.close()
            case.stage1.query_service = None
            case.intake.close()
            case.intake = fixture.ProjectIntakeService(
                case.root / "p", authenticate=fixture.authenticate
            )
            case.addCleanup(case.intake.close)
            case.stage1 = fixture.ProjectStage1Service(case.intake, limit=3)
            case.queries = case.bridge()
            fresh = ProjectStage1RunGrantService(
                case.intake, runtime_sha256="a" * 64, clock=lambda: now[0]
            )
            case.queries.run_grants = fresh
            with case.no_probe():
                self.assertEqual(
                    case.queries.read("alice-token", case.ref)["status"],
                    "owner-reopen-required",
                )
                case.queries.reopen("alice-token", case.ref)
                with self.assertRaises(SessionApiError):
                    case.queries.execute(
                        "alice-token", case.ref, body, run_authorization=token
                    )
                resumed = fresh.derive(
                    "alice-token",
                    case.ref,
                    grant_ref=grant["grant_ref"],
                    grant_sha256=grant["grant_sha256"],
                    operation="query",
                    identity=action_identity("query-execute", body),
                )
                result = case.queries.execute(
                    "alice-token", case.ref, body, run_authorization=resumed
                )
                self.assertTrue(result["replayed"])
                self.assertEqual(result["query_action_key"], queued["query_action_key"])
            self.assertEqual(len(case.children), 1)
            self.assertEqual(
                case.queries.read("alice-token", case.ref)["budget"],
                dict(probes=1, attempts=1, seconds=62),
            )

    def test_original_run_expiry_after_capture_preserves_attempt_and_refuses_completion(
        self,
    ):
        with setup_case() as (case, issuer, grant, now, consent, derived):
            authorize(case, derived)
            bootstrap(case, derived)
            body, token = derived("query-execute", "query_offer")
            service = case.queries.services[case.ref]
            import planned_query_fixture as raw_fixture

            original = raw_fixture.synthetic_audit

            def capture(*args, **kwargs):
                result = original(*args, **kwargs)
                now[0] = grant["expires_at"]
                return result

            with (
                patch.object(raw_fixture, "synthetic_audit", side_effect=capture),
                case.fake_runner(),
                case.no_probe(),
            ):
                queued = case.queries.execute(
                    "alice-token", case.ref, body, run_authorization=token
                )
                service._workers[case.ref].join(30)
                self.assertFalse(service._workers[case.ref].is_alive())
            action = service.get_action(
                "alice-token", case.ref, queued["query_action_key"]
            )
            self.assertEqual(action["status"], "execution-unknown", action)
            self.assertIn("backend_observation", action)
            ledger = __import__(
                "stage1_coverage.run", fromlist=["CoverageLedger"]
            ).CoverageLedger(service._projects[case.ref]["item"]["ledger_root"])
            actual = ledger.event(
                action["backend_observation"]["backend_result_id"], "ActionFinished"
            )
            self.assertEqual(actual["outcome"], "success_nonempty")
            self.assertEqual(len(case.children), 1)
            self.assertEqual(
                case.intake._load("alice", case.ref)["stage1_query_budget"],
                dict(probes=1, attempts=1, seconds=62),
            )
            with self.assertRaises(SessionApiError):
                case.queries.execute(
                    "alice-token", case.ref, body, run_authorization=token
                )
            self.assertEqual(len(case.children), 1)

    def test_original_run_expiry_at_spawn_refuses_backend_without_refund(self):
        with setup_case() as (case, issuer, grant, now, consent, derived):
            authorize(case, derived)
            bootstrap(case, derived)
            body, token = derived("query-execute", "query_offer")

            def admission(event):
                if type(event["phase"]) is dict:
                    now[0] = grant["expires_at"]
                return True

            case.queries.admit = admission
            with case.fake_runner(), case.no_probe():
                queued = case.queries.execute(
                    "alice-token", case.ref, body, run_authorization=token
                )
                service = case.queries.services[case.ref]
                service._workers[case.ref].join(30)
                self.assertFalse(service._workers[case.ref].is_alive())
            action = service.get_action(
                "alice-token", case.ref, queued["query_action_key"]
            )
            self.assertEqual(action["status"], "execution-unknown", action)
            self.assertEqual(case.children, [])
            self.assertEqual(
                case.intake._load("alice", case.ref)["stage1_query_budget"],
                dict(probes=1, attempts=1, seconds=62),
            )


if __name__ == "__main__":
    unittest.main()

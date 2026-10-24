"""Real source broker/SQLite, authored receipt runner; no network or SDK calls."""

from contextlib import contextmanager

from stage1_deliverable.common import canonical, sha
from copy import deepcopy
import unittest

import project_stage1_source_cases as fixture
from research_workspace_native.project_stage1_run_grant import (
    ProjectStage1RunGrantService,
    SCOPE,
)
from research_workspace_native.project_run_authority import action_identity
from research_workspace_native.project_stage1_source_service import STORE
from research_workspace_native.session_api import SessionApiError
from test_workspace_project_intake import bound_body


@contextmanager
def setup_case():
    case = fixture.SourceServiceTests(methodName="runTest")
    try:
        case.setUp()
        case.sources.close()
        case.transport = fixture.AuthoredReceiptRunner(case)
        case.sources = case.service(case.transport)
        issuer = ProjectStage1RunGrantService(
            case.intake, runtime_sha256="a" * 64, clock=lambda: case.now[0]
        )
        case.sources.run_grants = issuer
        consent = "Acquire this synthetic saved-plan source within the original resource and time bounds."
        grant = issuer.authorize(
            case.token,
            case.ref,
            {
                **bound_body(
                    case.intake.read(case.token, case.ref), "source-whole-run"
                ),
                "confirmed": True,
                "user_input": consent,
                "scope": SCOPE,
                "operations": ["source"],
                "max_seconds": 20,
                "max_actions": 8,
            },
        )

        def derived(action, extra):
            body = {
                **bound_body(case.intake.read(case.token, case.ref), "draft"),
                "confirmed": False,
                **extra,
            }
            token = issuer.derive(
                case.token,
                case.ref,
                grant_ref=grant["grant_ref"],
                grant_sha256=grant["grant_sha256"],
                operation="source",
                identity=action_identity(action, body),
            )
            body.update(
                key=token.key + "-work",
                revision=case.intake.read(case.token, case.ref)["revision"],
            )
            return body, token

        def revoke():
            return issuer.revoke(
                case.token,
                case.ref,
                {
                    **bound_body(
                        case.intake.read(case.token, case.ref), "cancel-whole-run"
                    ),
                    "grant_ref": grant["grant_ref"],
                    "grant_sha256": grant["grant_sha256"],
                },
            )

        yield case, issuer, grant, consent, derived, revoke
    finally:
        case.doCleanups()


def authorize(case, derived):
    offer = case.offered()
    body, token = derived(
        "source-authorize",
        dict(
            work_ref=offer["work_ref"],
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
        ),
    )
    receipt = case.sources.authorize(
        case.token, case.ref, body, run_authorization=token
    )
    return body, token, receipt


def execute_body(derived, grant):
    return derived(
        "source-execute",
        dict(grant_ref=grant["grant_ref"], grant_sha256=grant["grant_sha256"]),
    )


class SourceRunTests(unittest.TestCase):
    def test_derived_grant_queue_receipt_and_same_key_keep_actual_consent(self):
        with setup_case() as (case, issuer, original, consent, derived, revoke):
            offer = case.offered()
            body, token = derived(
                "source-authorize",
                dict(
                    work_ref=offer["work_ref"],
                    offer_ref=offer["offer_ref"],
                    offer_sha256=offer["offer_sha256"],
                ),
            )
            with self.assertRaises(SessionApiError):
                case.sources.authorize(case.token, case.ref, body, run_authorization={})
            with self.assertRaises(SessionApiError):
                case.sources.authorize(case.token, case.ref, body)
            with self.assertRaises(SessionApiError):
                case.sources.authorize(
                    "other-library-test-token-with-at-least-32-characters",
                    case.ref,
                    body,
                    run_authorization=token,
                )
            grant = case.sources.authorize(
                case.token, case.ref, body, run_authorization=token
            )
            self.assertEqual(grant["status"], "saved", grant)
            state = case.intake._load(case.principal, case.ref)
            saved = state[STORE]["grants"][grant["grant_ref"]]
            self.assertEqual(saved["document"]["schema_version"], "1.1.0")
            self.assertFalse(saved["request"]["confirmed"])
            self.assertNotIn("user_input", saved["request"])
            self.assertEqual(saved["request"]["run_user_input"], consent)
            self.assertLessEqual(saved["expires_at"], original["expires_at"])
            self.assertTrue(
                case.sources.authorize(
                    case.token, case.ref, body, run_authorization=token
                )["replayed"]
            )
            mixed = case.execute_body(grant, "mixed-manual")
            with self.assertRaisesRegex(
                SessionApiError, "source-run-request-mode-differs"
            ):
                case.sources.execute(case.token, case.ref, mixed)
            self.assertEqual(case.resources()["reserved"]["source_reads"], 0)
            body, token = execute_body(derived, grant)
            queued = case.sources.execute(
                case.token, case.ref, body, run_authorization=token
            )
            self.assertEqual(queued["job_status"], "queued")
            state = case.intake._load(case.principal, case.ref)
            job = state[STORE]["jobs"][body["key"]]
            self.assertFalse(job["action_request"]["confirmed"])
            self.assertLessEqual(job["binding"]["deadline_at"], original["expires_at"])
            self.assertEqual(case.resources()["reserved"]["source_reads"], 1)
            result = case.sources.dispatch_pending(case.token, case.ref, body["key"])
            self.assertEqual(result["status"], "source-observation-saved", result)
            self.assertEqual(len(case.transport.calls), 1)
            self.assertTrue(
                case.sources.execute(
                    case.token, case.ref, body, run_authorization=token
                )["replayed"]
            )
            case.sources.dispatch_pending(case.token, case.ref, body["key"])
            self.assertEqual(len(case.transport.calls), 1)
            self.assertEqual(case.resources()["reserved"]["source_reads"], 1)

    def test_rehashed_mutable_offer_cannot_replace_sealed_offer(self):
        for field in ("max_fetches", "timeout_seconds", "max_reserved_seconds"):
            with (
                self.subTest(field=field),
                setup_case() as (case, issuer, original, consent, derived, revoke),
            ):
                _, _, receipt = authorize(case, derived)
                state = case.intake._load(case.principal, case.ref)
                grant = state[STORE]["grants"][receipt["grant_ref"]]
                sealed = deepcopy(grant["document"])
                grant["offer"]["limits"][field] += 1
                grant["offer_sha256"] = sha(canonical(grant["offer"]))
                case.sources._proof(state, "authored-rehashed-offer", grant)
                case.intake._save(state, "authored-offer-rehash", {})
                self.assertEqual(grant["document"], sealed)
                self.assertEqual(grant["grant_sha256"], receipt["grant_sha256"])
                before = deepcopy(case.resources()["reserved"])
                body, token = execute_body(derived, receipt)
                with self.assertRaisesRegex(
                    SessionApiError, "source-run-grant-authority-differs"
                ):
                    case.sources.execute(
                        case.token, case.ref, body, run_authorization=token
                    )
                self.assertEqual(case.resources()["reserved"], before)
                self.assertEqual(case.transport.calls, [])
                self.assertEqual(
                    case.intake._load(case.principal, case.ref)[STORE]["jobs"], {}
                )

    def test_revoked_queued_run_refuses_without_transport_or_refund(self):
        with setup_case() as (case, issuer, original, consent, derived, revoke):
            _, _, grant = authorize(case, derived)
            body, token = execute_body(derived, grant)
            case.sources.execute(case.token, case.ref, body, run_authorization=token)
            reserved = deepcopy(case.resources()["reserved"])
            revoke()
            result = case.sources.dispatch_pending(case.token, case.ref, body["key"])
            # The original broker preserves this authority refusal as unknown.
            self.assertEqual(result["status"], "execution-unknown", result)
            self.assertFalse(result["runner_invoked"])
            self.assertFalse(result["invocation_claimed"])
            self.assertFalse(result["automatic_retry"])
            self.assertIsNone(result["result"])
            self.assertEqual(result["failure"]["code"], "stage1-run-grant-revoked")
            self.assertEqual(case.transport.calls, [])
            self.assertEqual(case.resources()["reserved"], reserved)
            with self.assertRaises(SessionApiError):
                case.sources.execute(
                    case.token, case.ref, body, run_authorization=token
                )
            self.assertEqual(case.transport.calls, [])

    def test_original_run_deadline_after_queue_is_not_renewed_by_dispatch(self):
        with setup_case() as (case, issuer, original, consent, derived, revoke):
            _, _, grant = authorize(case, derived)
            body, token = execute_body(derived, grant)
            case.sources.execute(case.token, case.ref, body, run_authorization=token)
            reserved = deepcopy(case.resources()["reserved"])
            case.now[0] = original["expires_at"]
            result = case.sources.dispatch_pending(case.token, case.ref, body["key"])
            self.assertEqual(result["status"], "refused-known-unsent", result)
            self.assertEqual(result["failure"]["code"], "source-job-deadline-expired")
            self.assertEqual(case.transport.calls, [])
            self.assertEqual(case.resources()["reserved"], reserved)


if __name__ == "__main__":
    unittest.main()

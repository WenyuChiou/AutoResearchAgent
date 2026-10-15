"""Real SQLite/ledger/runner, with no network, Python probe or child process."""

import atlas_test_paths  # noqa: F401
from copy import deepcopy
import threading
import time
import json
from types import SimpleNamespace
from unittest.mock import patch

from research_workspace_native.session_api import SessionApiError
from research_workspace_native.planned_query_contract import inspect_registration
from stage1_brief.formal_target import formal_target_state
from planned_query_fixture import QueryCase


class PlannedQueryTests(QueryCase):
    def test_real_runner_receipt_and_budget_precede_fake_child(self):
        observations = []

        def admit(event):
            state = service.view("secret", "case")
            observations.append(deepcopy(event))
            self.assertEqual(state["budget"], {"attempts": 1, "seconds": 32})
            self.assertEqual(len(state["history"]), 1)
            return True

        service = self.service(admit=admit)
        request = self.request(service)
        with self.no_probe(), self.fake_runner():
            service.execute("secret", "case", request, deadline=time.monotonic() + 30)
            result = self.wait(service)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["backend_outcome"], "success_nonempty")
        self.assertFalse(result["result"]["stage_complete"])
        self.assertEqual(len(self.children), 1)
        self.assertEqual(observations[0]["phase"], "before-runner")
        self.assertIsInstance(observations[1]["phase"], dict)
        self.assertEqual(self.ledger.candidates().__len__(), 1)
        self.assertIsNotNone(result["result"]["execution_ref"])

    def test_same_key_tabs_response_loss_and_changed_payload(self):
        service = self.service()
        request = self.request(service)
        with self.no_probe(), self.fake_runner():
            service.execute("secret", "case", request, deadline=time.monotonic() + 30)
            result = self.wait(service)
        self.assertEqual(service.execute("secret", "case", request, deadline=0), result)
        request["revision"] += 17
        self.assertEqual(service.execute("secret", "case", request, deadline=0), result)
        before = deepcopy(self.children)
        self.assertEqual(service.view("secret", "case")["history"], [result])
        self.assertEqual(service.get_action("secret", "case", "action-1"), result)
        request["offer_sha256"] = "0" * 64
        with self.assertRaisesRegex(SessionApiError, "idempotency-payload"):
            service.execute("secret", "case", request, deadline=time.monotonic() + 30)
        self.assertEqual(before, self.children)

    def test_concurrent_same_key_is_reserved_once(self):
        service = self.service()
        request, results, errors = self.request(service), [], []

        def send():
            try:
                results.append(
                    service.execute(
                        "secret", "case", request, deadline=time.monotonic() + 30
                    )
                )
            except Exception as error:
                errors.append(type(error).__name__)

        with self.no_probe(), self.fake_runner():
            threads = [threading.Thread(target=send) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
            self.wait(service)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(len(self.children), 1)
        self.assertEqual(service.view("secret", "case")["budget"]["attempts"], 1)

    def test_admission_is_literal_true_refusal_before_probe(self):
        self.permit.update(max_attempts=3, max_reserved_seconds=96)
        self.write_permit()
        for value in (False, 1, None):
            with self.subTest(value=value):
                service = self.service(admit=lambda event: value)
                request = self.request(service, "refusal-" + str(value))
                with patch("planned_query_fixture.runner.verify_identity") as probe:
                    service.execute(
                        "secret", "case", request, deadline=time.monotonic() + 30
                    )
                    row = self.wait(service, request["key"])
                probe.assert_not_called()
                self.assertEqual(row["outcome"], "refused-known-unsent")
                self.assertEqual(self.ledger.pending(), [])
                service.close()
        self.assertEqual(self.children, [])

    def test_final_permit_expiry_retains_uncertain_attempt_without_child(self):
        def admit(event):
            if isinstance(event["phase"], dict):
                # Simulate time passing during the caller's final admission check.
                clock.return_value = self.permit["expires_at_unix"]
            return True

        service = self.service(admit=admit)
        request = self.request(service)
        with (
            self.no_probe(),
            self.fake_runner(),
            patch(
                "research_workspace_native.planned_queries.time.time",
                return_value=time.time(),
            ) as clock,
        ):
            service.execute("secret", "case", request, deadline=time.monotonic() + 30)
            row = self.wait(service)
        self.assertEqual(row["status"], "execution-unknown")
        self.assertEqual(self.children, [])
        self.assertEqual(len(self.ledger.pending()), 2)
        self.assertEqual(service.execute("secret", "case", request, deadline=0), row)

    def test_reopen_new_owner_unknown_is_history_only(self):
        service = self.service()
        request = self.request(service)

        class Unstarted:
            def __init__(self, **kwargs):
                pass

            def start(self):
                pass

        with patch(
            "research_workspace_native.planned_queries.threading",
            SimpleNamespace(Thread=Unstarted),
        ):
            service.execute("secret", "case", request, deadline=time.monotonic() + 30)
        service._workers.clear()
        old_owner = service._projects["case"]["owner"]
        service.close()
        reopened = self.service()
        self.assertNotEqual(old_owner, reopened._projects["case"]["owner"])
        row = reopened.get_action("secret", "case", "action-1")
        self.assertEqual(row["status"], "execution-unknown")
        self.assertEqual(reopened.execute("secret", "case", request, deadline=0), row)
        with self.assertRaisesRegex(SessionApiError, "unreconciled"):
            self.request(reopened, "new-key")
        self.assertEqual(self.children, [])

    def test_reopen_after_backend_dispatch_keeps_observed_capture_and_never_retries(
        self,
    ):
        from planned_query_fixture import runner

        service = self.service()
        request = self.request(service)
        original = runner.resume

        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("response lost after complete capture")

        with (
            self.no_probe(),
            self.fake_runner(),
            patch.object(runner, "resume", side_effect=lost),
        ):
            service.execute("secret", "case", request, deadline=time.monotonic() + 30)
            self.wait(service)
        service.close()
        reopened = self.service()
        row = reopened.execute("secret", "case", request, deadline=0)
        self.assertEqual(row["status"], "execution-unknown")
        self.assertEqual(len(self.children), 1)
        self.assertEqual(len(list(self.ledger.root.glob("captures/*/process.json"))), 1)

    def test_partial_backend_failure_is_not_promoted_to_success(self):
        service = self.service()
        with self.no_probe(), self.fake_runner("partial"):
            service.execute(
                "secret", "case", self.request(service), deadline=time.monotonic() + 30
            )
            row = self.wait(service)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["result"]["backend_outcome"], "partial_failure")
        self.assertFalse(row["result"]["stage_complete"])
        self.assertEqual(len(self.children), 1)

    def test_project_source_request_deadline_and_budget_are_failclosed(self):
        service = self.service()
        request = self.request(service)
        for token, ref in (("bad", "case"), ("secret", "other")):
            with self.assertRaisesRegex(SessionApiError, "denied"):
                service.execute(token, ref, request, deadline=time.monotonic() + 30)
        with self.assertRaisesRegex(SessionApiError, "expired"):
            service.execute("secret", "case", request, deadline=0)
        changed = dict(request, root="caller-controlled")
        with self.assertRaisesRegex(SessionApiError, "fields"):
            service.execute("secret", "case", changed, deadline=time.monotonic() + 30)
        self.brief.write_bytes(self.brief.read_bytes() + b" ")
        with self.assertRaisesRegex(SessionApiError, "bytes-differ"):
            service.offer("secret", "case")
        self.assertEqual(service.view("secret", "case")["budget"]["attempts"], 0)
        self.assertEqual(self.children, [])

    def test_pending_intake_fails_before_database_creation(self):
        value = json.loads(self.brief.read_bytes())
        value["formal_final_count"]["decisions"] = []
        self.brief.write_bytes(json.dumps(value).encode())
        self.item["brief_sha256"] = (
            __import__("hashlib").sha256(self.brief.read_bytes()).hexdigest()
        )
        with self.assertRaisesRegex(ValueError, "clarification incomplete"):
            self.service()
        self.assertFalse((self.root / "query.sqlite3").exists())

    def test_budget_exhausted_preserves_two_attempts(self):
        service = self.service()
        with self.no_probe(), self.fake_runner():
            for key in ("action-1", "action-2"):
                service.execute(
                    "secret",
                    "case",
                    self.request(service, key),
                    deadline=time.monotonic() + 30,
                )
                self.wait(service, key)
        with self.assertRaisesRegex(SessionApiError, "budget-exhausted"):
            service.offer("secret", "case")
        self.assertEqual(
            service.view("secret", "case")["budget"], {"attempts": 2, "seconds": 64}
        )
        self.assertEqual(len(self.children), 2)

    def test_confirmed_intake_target_37_is_not_a_hardcoded_20_or_30(self):
        item, permit, _, _ = inspect_registration("case", self.item)
        self.assertEqual(
            formal_target_state(json.loads(self.brief.read_bytes()))["target"], 37
        )
        self.assertEqual(item["project_id"], "project-a")
        self.assertEqual(permit["max_results"], 3)

    def test_plan_tamper_and_expired_research_permit_refuse_before_intent(self):
        service = self.service()
        plan = self.plan / "coverage_plan.json"
        original = plan.read_bytes()
        plan.write_bytes(original + b" ")
        with self.assertRaisesRegex(SessionApiError, "plan-bytes"):
            service.offer("secret", "case")
        plan.write_bytes(original)
        with patch(
            "research_workspace_native.planned_query_contract.time.time",
            return_value=self.permit["expires_at_unix"],
        ):
            with self.assertRaisesRegex(SessionApiError, "budget-or-expiry"):
                service.offer("secret", "case")
        self.assertEqual(service.view("secret", "case")["history"], [])
        self.assertEqual(self.children, [])

    def test_final_admission_non_true_refuses_popen_after_saved_backend_intent(self):
        service = self.service(
            admit=lambda e: True if e["phase"] == "before-runner" else 1
        )
        with self.no_probe(), self.fake_runner():
            service.execute(
                "secret", "case", self.request(service), deadline=time.monotonic() + 30
            )
            row = self.wait(service)
        self.assertEqual(row["status"], "execution-unknown")
        self.assertEqual(self.children, [])
        self.assertEqual(len(self.ledger.pending()), 2)

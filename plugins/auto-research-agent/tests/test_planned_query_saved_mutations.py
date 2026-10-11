"""Owned real Core writes in a fresh raw-loader worker; no Hub/Codex/model I/O."""

import atlas_test_paths  # noqa: F401

from contextlib import contextmanager
from copy import deepcopy
import json
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch

import planned_query_fixture as fixtures
from planned_query_fixture import QueryCase
from planned_query_raw_runner import run_cases
from research_workspace_native.planned_query_contract import tree_sha
from research_workspace_native.query_storage import LedgerOwners
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
from stage1_export.bundle import export_run, validate_export


if fixtures.RAW_SOURCE_PROOF is None:

    class SavedMutationDiscoveryTests(unittest.TestCase):
        def test_all_scenarios_in_fresh_raw_loader(self):
            run_cases("test_planned_query_saved_mutations", self)

else:

    class SavedMutationTests(QueryCase):
        def invoke(
            self, service, key="saved-1", operation="stage1-checkpoint", producer=None
        ):
            return service.mutate_saved(
                "secret",
                "case",
                key,
                sha(canonical([operation, key])),
                tree_sha(self.ledger_root),
                operation,
                producer or (lambda ledger: ledger.checkpoint()),
            )

        def test_actual_checkpoint_intent_precedes_core_and_frontier_advances(self):
            service = self.service()
            before = service.inspect_saved("secret", "case")
            observed = []

            def checkpoint(ledger):
                # A separate read-only SQLite connection sees the committed intent.
                other = sqlite3.connect(
                    service.store.path.as_uri() + "?mode=ro", uri=True
                )
                try:
                    state = json.loads(
                        other.execute(
                            "SELECT state FROM projects WHERE id=?",
                            (service._pid("case"),),
                        ).fetchone()[0]
                    )
                finally:
                    other.close()
                intent = next(iter(state["intents"].values()))
                self.assertEqual(intent["status"], "dispatch-unobserved")
                self.assertEqual(state["query_budget"], {"attempts": 0, "seconds": 0})
                observed.append(intent)
                return ledger.checkpoint()

            with patch.object(
                service, "_execute", side_effect=AssertionError("no search")
            ):
                result = self.invoke(service, producer=checkpoint)
            self.assertEqual(result["status"], "completed")
            after = service.inspect_saved("secret", "case")
            self.assertEqual(len(observed), 1)
            self.assertNotEqual(before["tree_sha256"], after["tree_sha256"])
            self.assertEqual(
                before["ledger_state_sha256"], after["ledger_state_sha256"]
            )
            actual = self.ledger.events()[before["journal_sequence"] :]
            self.assertEqual(result["core_observation"]["core_events"], actual)
            self.assertEqual(
                result["core_observation"]["tree_sha256"], after["tree_sha256"]
            )
            self.assertEqual(after["state_sha256"], after["ledger_state_sha256"])
            self.assertEqual(result["result"], actual[-1]["payload"])
            self.assertEqual(actual[-1]["payload"]["kind"], "Checkpoint")
            self.assertEqual(after["budget"], before["budget"])
            self.assertEqual(self.children, [])

        def test_plan_intent_then_actual_export_use_same_owner_without_search(self):
            service = self.service()
            planned = self.permit["planned_ids"][0]
            start = self.invoke(
                service,
                key="plan",
                operation="stage1-plan-query",
                producer=lambda ledger: ledger.start_planned(planned),
            )
            self.assertEqual(start["status"], "completed")
            self.assertEqual(
                start["core_observation"]["core_events"][-1]["payload"]["operation"],
                "search",
            )
            self.assertEqual(
                start["result"],
                start["core_observation"]["core_events"][-1]["payload"]["event_id"],
            )
            # A planned-only search remains inspectable, with no external attempt.
            self.assertEqual(
                service.inspect_saved("secret", "case")["budget"]["attempts"], 0
            )
            self.invoke(service, key="checkpoint")
            output = self.root / "saved-export"
            result = self.invoke(
                service,
                key="export",
                operation="stage1-export",
                producer=lambda ledger: export_run(ledger.root, output),
            )
            self.assertEqual(result["status"], "completed")
            self.assertTrue(validate_export(output)["valid"])
            self.assertEqual(result["core_observation"]["core_events"], [])
            self.assertEqual(
                result["previous_frontier"]["tree_sha256"],
                result["core_observation"]["tree_sha256"],
            )
            self.assertEqual(self.children, [])

        def test_reopen_same_key_is_history_only_and_changed_identity_refuses(self):
            service = self.service()
            expected = tree_sha(self.ledger_root)
            request = sha(b"checkpoint-request")
            args = ("secret", "case", "stable", request, expected, "stage1-checkpoint")
            result = service.mutate_saved(*args, lambda ledger: ledger.checkpoint())
            budget = deepcopy(service.view("secret", "case")["budget"])
            service.close()
            reopened = self.service()
            before = reopened.store.events(reopened._pid("case"))
            with patch.object(
                reopened, "_saved_frontier", side_effect=AssertionError("history only")
            ):
                replay = reopened.mutate_saved(
                    *args, lambda _: self.fail("producer replayed")
                )
            self.assertEqual(replay, result)
            self.assertEqual(reopened.store.events(reopened._pid("case")), before)
            self.assertEqual(reopened.view("secret", "case")["budget"], budget)
            for changed in (
                args[:3] + (sha(b"other"),) + args[4:],
                args[:4] + ("f" * 64,) + args[5:],
                args[:5] + ("stage1-export",),
            ):
                with self.assertRaisesRegex(SessionApiError, "idempotency-payload"):
                    reopened.mutate_saved(
                        *changed, lambda _: self.fail("changed replay")
                    )

        def test_owner_stale_frontier_and_unjournaled_core_write_refuse_before_intent(
            self,
        ):
            service = self.service()
            with self.assertRaises(sqlite3.OperationalError):
                LedgerOwners([self.ledger_root])
            expected = tree_sha(self.ledger_root)
            before = service.view("secret", "case")
            with self.assertRaisesRegex(SessionApiError, "frontier-stale"):
                service.mutate_saved(
                    "secret",
                    "case",
                    "stale",
                    sha(b"x"),
                    "0" * 64,
                    "stage1-checkpoint",
                    lambda _: self.fail("stale producer"),
                )
            self.assertEqual(service.view("secret", "case"), before)
            # An actual valid Core write outside the service is still unjournaled.
            self.ledger.checkpoint()
            with self.assertRaisesRegex(SessionApiError, "ledger-changed"):
                service.inspect_saved("secret", "case")
            with self.assertRaisesRegex(SessionApiError, "ledger-changed"):
                service.mutate_saved(
                    "secret",
                    "case",
                    "outside",
                    sha(b"x"),
                    expected,
                    "stage1-checkpoint",
                    lambda _: self.fail("outside producer"),
                )
            self.assertEqual(service.view("secret", "case")["history"], [])

        def test_exhausted_expired_search_budget_does_not_authorize_or_block_local_write(
            self,
        ):
            self.permit["expires_at_unix"] = int(time.time()) - 1
            self.write_permit()
            service = self.service()
            p = service._projects["case"]
            with service.store._edit(
                p["pid"], p["owner"], None, "test-spent-budget", {}
            ) as state:
                state["query_budget"] = {"attempts": 2, "seconds": 64}
            with self.assertRaises(SessionApiError):
                service.offer("secret", "case")
            with patch.object(
                service, "_admit", side_effect=AssertionError("no admission")
            ):
                before = service.inspect_saved("secret", "case")
                result = self.invoke(service)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(
                service.inspect_saved("secret", "case")["budget"], before["budget"]
            )

        def test_producer_failure_retains_unknown_core_bytes_and_never_replays(self):
            service = self.service()
            expected = tree_sha(self.ledger_root)
            before = len(self.ledger.events())

            def fail(ledger):
                ledger.checkpoint()
                raise OSError("private physical path must not appear")

            args = (
                "secret",
                "case",
                "failed",
                sha(b"request"),
                expected,
                "stage1-checkpoint",
            )
            result = service.mutate_saved(*args, fail)
            self.assertEqual(result["status"], "execution-unknown")
            self.assertNotIn("private physical path", canonical(result).decode())
            self.assertGreater(len(self.ledger.events()), before)
            self.assertTrue(result["core_observation"]["core_events"])
            self.assertEqual(
                result["core_observation"]["tree_sha256"], tree_sha(self.ledger_root)
            )
            self.assertEqual(
                service.store.snapshot(service._pid("case"))["query_ledger_sha256"],
                expected,
            )
            with self.assertRaisesRegex(SessionApiError, "unreconciled-action"):
                service.inspect_saved("secret", "case")
            service.close()
            reopened = self.service()
            self.assertEqual(
                reopened.mutate_saved(*args, lambda _: self.fail("retry")), result
            )
            with self.assertRaises(SessionApiError):
                self.invoke(reopened, key="different")

        def test_observation_commit_failure_is_unknown_without_frontier_adoption(self):
            service = self.service()
            expected = tree_sha(self.ledger_root)
            original = service.store._edit

            @contextmanager
            def fail_observation(*args, **kwargs):
                with original(*args, **kwargs) as state:
                    yield state
                    if args[3] == "saved-ledger-observation":
                        raise sqlite3.OperationalError("synthetic pre-commit failure")

            with patch.object(service.store, "_edit", side_effect=fail_observation):
                result = self.invoke(service)
            self.assertEqual(result["status"], "execution-unknown")
            self.assertTrue(result["core_observation"]["core_events"])
            self.assertEqual(
                result["output_observation"],
                result["core_observation"]["core_events"][-1]["payload"],
            )
            self.assertEqual(
                service.store.snapshot(service._pid("case"))["query_ledger_sha256"],
                expected,
            )
            self.assertEqual(service.get_action("secret", "case", "saved-1"), result)

        def test_unrecordable_failure_reopen_invalidates_intent_and_never_calls_producer(
            self,
        ):
            service = self.service()
            expected, request = tree_sha(self.ledger_root), sha(b"request")
            original = service.store._edit

            @contextmanager
            def fail_finalization(*args, **kwargs):
                if args[3] in {"saved-ledger-observation", "saved-ledger-unknown"}:
                    raise sqlite3.OperationalError("unrecordable observation")
                with original(*args, **kwargs) as state:
                    yield state

            args = ("secret", "case", "crash", request, expected, "stage1-checkpoint")
            with patch.object(service.store, "_edit", side_effect=fail_finalization):
                with self.assertRaises(sqlite3.OperationalError):
                    service.mutate_saved(*args, lambda ledger: ledger.checkpoint())
            self.assertEqual(
                service.get_action("secret", "case", "crash")["status"],
                "dispatch-unobserved",
            )
            service.close()
            reopened = self.service()
            result = reopened.mutate_saved(*args, lambda _: self.fail("crash retry"))
            self.assertEqual(result["status"], "execution-unknown")
            with self.assertRaisesRegex(SessionApiError, "unreconciled-action"):
                reopened.inspect_saved("secret", "case")

        def test_concurrent_same_key_is_one_core_write_and_other_pending_write_refuses(
            self,
        ):
            service = self.service()
            expected = tree_sha(self.ledger_root)
            entered, release = threading.Event(), threading.Event()
            results, errors = [], []

            def producer(ledger):
                entered.set()
                self.assertTrue(release.wait(5))
                return ledger.checkpoint()

            def send():
                try:
                    results.append(
                        service.mutate_saved(
                            "secret",
                            "case",
                            "concurrent",
                            sha(b"x"),
                            expected,
                            "stage1-checkpoint",
                            producer,
                        )
                    )
                except BaseException as error:
                    errors.append(error)

            workers = [threading.Thread(target=send) for _ in range(2)]
            workers[0].start()
            self.assertTrue(entered.wait(5))
            workers[1].start()
            release.set()
            for worker in workers:
                worker.join(10)
                self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(results[0], results[1])
            self.assertEqual(
                sum(
                    row["payload"]["kind"] == "Checkpoint"
                    for row in self.ledger.events()
                ),
                1,
            )
            p = service._projects["case"]
            with service.store._edit(
                p["pid"], p["owner"], None, "test-pending-query", {}
            ) as state:
                state["intents"]["pending"] = {"status": "dispatching"}
            with self.assertRaisesRegex(SessionApiError, "unreconciled-action"):
                self.invoke(service, key="blocked")

        def test_shape_auth_source_attempt_marker_and_owner_loss_refuse_without_io(
            self,
        ):
            service = self.service()
            expected = tree_sha(self.ledger_root)
            for operation in ("source-acquisition", "stage1-execute-query", [], None):
                with self.assertRaisesRegex(SessionApiError, "operation-invalid"):
                    service.mutate_saved(
                        "secret",
                        "case",
                        "bad",
                        sha(b"x"),
                        expected,
                        operation,
                        lambda _: self.fail("ungranted producer"),
                    )
            with self.assertRaisesRegex(SessionApiError, "project-denied"):
                service.inspect_saved("foreign", "case")
            marker = self.root / "query.sqlite3.created"
            original = marker.read_bytes()
            marker.write_bytes(b"changed")
            with self.assertRaisesRegex(SessionApiError, "marker-differs"):
                service.inspect_saved("secret", "case")
            marker.write_bytes(original)
            service.ledger_owners.close()
            with self.assertRaisesRegex(SessionApiError, "ledger-owner-lost"):
                self.invoke(service)
            self.assertEqual(service.view("secret", "case")["history"], [])
            self.assertEqual(self.children, [])

        def test_unfinished_source_attempt_is_unknown_and_inspection_never_acquires_source(
            self,
        ):
            service = self.service()
            # Run an existing real runner with synthetic captures to establish an
            # actual candidate. The injected child and probe do no external I/O.
            request = self.request(service)
            with self.no_probe(), self.fake_runner():
                service.execute(
                    "secret", "case", request, deadline=time.monotonic() + 30
                )
                self.wait(service)
            candidate = next(iter(self.ledger.candidates().values()))

            def unfinished(ledger):
                return ledger.start_source(
                    work_id=candidate["work_id"],
                    version_id=candidate["version_ids"][0],
                    source_uri="https://example.org/synthetic",
                    tool="synthetic-no-io",
                    request={"public_only": True},
                    actor="researcher",
                    reason="offline pending intent only",
                )

            result = self.invoke(
                service,
                key="saved-import",
                operation="stage1-import-saved",
                producer=unfinished,
            )
            self.assertEqual(result["status"], "execution-unknown")
            self.assertTrue(
                any(
                    row["payload"]["kind"] == "SourceReadStarted"
                    for row in result["core_observation"]["core_events"]
                )
            )
            self.assertEqual(len(self.children), 1)
            with patch.object(
                service, "_execute", side_effect=AssertionError("no new search")
            ):
                with self.assertRaisesRegex(SessionApiError, "unreconciled-action"):
                    service.inspect_saved("secret", "case")

        def test_saved_import_producer_preserves_actual_core_event_and_budget(self):
            service = self.service()
            request = self.request(service)
            with self.no_probe(), self.fake_runner():
                service.execute(
                    "secret", "case", request, deadline=time.monotonic() + 30
                )
                self.wait(service)
            candidate = next(iter(self.ledger.candidates().values()))
            budget = deepcopy(service.view("secret", "case")["budget"])
            result = self.invoke(
                service,
                operation="stage1-import-saved",
                producer=lambda ledger: ledger.start_source_import(
                    work_id=candidate["work_id"],
                    version_id=candidate["version_ids"][0],
                    source_uri="saved:fixture",
                    actor="researcher",
                    reason="saved bytes only; no acquisition",
                ),
            )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(
                result["result"],
                result["core_observation"]["core_events"][-1]["payload"]["event_id"],
            )
            self.assertEqual(
                result["core_observation"]["core_events"][-1]["payload"]["kind"],
                "SourceImportStarted",
            )
            self.assertEqual(service.inspect_saved("secret", "case")["budget"], budget)
            self.assertEqual(len(self.children), 1)

        def test_unjournaled_control_frontier_tamper_cannot_acknowledge_outside_write(
            self,
        ):
            service = self.service()
            self.ledger.checkpoint()
            pid = service._pid("case")
            saved = service.store.snapshot(pid)
            saved["query_ledger_sha256"] = tree_sha(self.ledger_root)
            service.store.db.execute(
                "UPDATE projects SET state=? WHERE id=?",
                (canonical(saved).decode(), pid),
            )
            with self.assertRaisesRegex(SessionApiError, "state-history-differs"):
                service.inspect_saved("secret", "case")
            with self.assertRaisesRegex(SessionApiError, "state-history-differs"):
                self.invoke(service)
            self.assertEqual(service.view("secret", "case")["history"], [])

        def test_intent_commit_failure_has_zero_producer_and_no_budget_change(self):
            service = self.service()
            original = service.store._edit
            before = service.view("secret", "case")

            @contextmanager
            def reject_intent(*args, **kwargs):
                with original(*args, **kwargs) as state:
                    yield state
                    if args[3] == "saved-ledger-intent":
                        raise sqlite3.OperationalError(
                            "synthetic intent commit failure"
                        )

            with patch.object(service.store, "_edit", side_effect=reject_intent):
                with self.assertRaises(sqlite3.OperationalError):
                    self.invoke(
                        service, producer=lambda _: self.fail("uncommitted producer")
                    )
            self.assertEqual(service.view("secret", "case"), before)


if __name__ == "__main__":
    unittest.main()

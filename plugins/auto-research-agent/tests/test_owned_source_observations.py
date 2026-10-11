"""Actual owned Core/SQLite source observations; no reader or model executes."""

import atlas_test_paths  # noqa: F401
from copy import deepcopy
import unittest
from unittest.mock import patch

import project_stage1_query_cases as helpers
import test_stage1_deliverable as package_fixture
from research_workspace_native.owned_source_observations import OwnedSourceObservations
from research_workspace_native.planned_queries import PlannedQueryService
from research_workspace_native.planned_query_contract import tree_sha
from research_workspace_native.project_stage1_source_observation import (
    complete_saved_source,
)
from research_workspace_native.session_api import SessionApiError
from stage1_coverage.run import CoverageLedger
from stage1_deliverable.common import canonical, read_json, sha
from stage1_ledger.validation import validate_run


class OwnedSourceObservationTests(unittest.TestCase):
    def setUp(self):
        # Composition does not collect the fixture's unrelated test_* methods.
        self.case = helpers.ProjectQueryCases()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.case.authorize()
        self.case.bootstrap()
        with self.case.fake_runner(), self.case.no_probe():
            queued = self.case.queries.execute(
                "alice-token", self.case.ref, self.case.body("query_offer", "query")
            )
            service = self.case.queries.services[self.case.ref]
            service._workers[self.case.ref].join(30)
            self.assertFalse(service._workers[self.case.ref].is_alive())
        action = service.get_action(
            "alice-token", self.case.ref, queued["query_action_key"]
        )
        self.assertEqual(
            (action["status"], action["outcome"]), ("completed", "observed")
        )
        self.service = service
        self.project = service._projects[self.case.ref]
        self.observations = OwnedSourceObservations(service)
        self.ledger = CoverageLedger(self.project["item"]["ledger_root"])
        work_id, work = next(iter(self.ledger.candidates().items()))
        self.arguments = dict(
            work_id=work_id,
            version_id=work["version_ids"][0],
            source_uri="https://example.invalid/authored-source",
            tool="authored-core-source-fixture/v1",
            request=dict(
                public_only=True, url="https://example.invalid/authored-source"
            ),
            actor="offline-fixture",
            reason="Authored saved bytes; no external source acquisition.",
        )
        self.initial_tree = tree_sha(self.ledger.root)
        self.start_sha = sha(canonical(self.arguments))
        self.child_count = len(self.case.children)

    def inventory(self):
        return (
            {
                path.relative_to(self.case.root).as_posix(): sha(path.read_bytes())
                for path in self.case.root.rglob("*")
                if path.is_file() and ".sqlite" not in path.name
            },
            tuple(self.case.intake.db.iterdump()),
            tuple(self.service.store.db.iterdump()),
            len(self.case.children),
        )

    def start(self, *, key="source-start"):
        return self.observations.start(
            "alice-token",
            self.case.ref,
            key,
            self.start_sha,
            self.initial_tree,
            self.arguments,
        )

    def producer(self, source_id):
        def produce(ledger):
            text = ledger.save_bytes(
                b"Authored fixture evidence, not an acquired paper.", producer=source_id
            )
            finish = ledger.finish_source(
                attempt_id=source_id,
                outcome="available",
                observed_at=ledger.clock(),
                http_status=200,
                resolved_uri=self.arguments["source_uri"],
                raw_ref=text,
                text_ref=text,
                extraction=dict(method="identity", version="authored-fixture-v1"),
                reason="Local authored bytes only; no reader, identity, or science claim.",
            )
            return dict(source_id=source_id, finish_event_id=finish)

        return produce

    def finish(self, source_id, *, producer=None, key="source-finish"):
        expected = self.observations.read("alice-token", self.case.ref)["tree_sha256"]
        digest = sha(canonical(dict(source_id=source_id, authored_fixture=True)))
        row = self.observations.finish(
            "alice-token",
            self.case.ref,
            key,
            digest,
            expected,
            source_id,
            producer or self.producer(source_id),
        )
        return row, digest, expected

    def reopen_inner(self):
        old = self.service
        path, item = old.store.path, deepcopy(self.project["item"])
        old.close()
        reopened = PlannedQueryService(
            path,
            registrations={self.case.ref: item},
            authenticate=old._auth,
            admit=old._admit,
            verify_source=old._verify_source,
            executor=old._execute,
        )
        self.addCleanup(reopened.close)
        self.service = reopened
        self.project = reopened._projects[self.case.ref]
        self.observations = OwnedSourceObservations(reopened)
        return reopened

    def test_prepare_read_finish_preserves_exact_source_and_zero_external_io(self):
        budget = deepcopy(self.service.view("alice-token", self.case.ref)["budget"])
        start = self.start()
        self.assertEqual((start["status"], start["outcome"]), ("completed", "observed"))
        source_id = start["result"]["source_id"]
        raw_start = self.ledger.event(source_id, "SourceReadStarted")
        saved = self.service.store.snapshot(self.project["pid"])
        registered = saved["source_read_observations"][source_id]
        self.assertEqual(registered["start"], raw_start)
        self.assertEqual(registered["start_sha256"], sha(canonical(raw_start)))
        self.assertEqual(registered["request_sha256"], self.start_sha)
        before = self.inventory()
        frontier = self.observations.read("alice-token", self.case.ref)
        self.assertEqual(frontier["pending_source_ids"], [source_id])
        self.assertFalse(frontier["external_execution"])
        self.assertFalse(frontier["automatic_retry"])
        self.assertEqual(before, self.inventory())
        row, _, _ = self.finish(source_id)
        self.assertEqual(
            (row["status"], row["outcome"]), ("completed", "observed"), row
        )
        self.assertEqual(
            self.ledger.event(row["result"]["finish_event_id"])["attempt_id"], source_id
        )
        self.assertEqual(
            self.observations.read("alice-token", self.case.ref)["pending_source_ids"],
            [],
        )
        self.assertTrue(validate_run(self.ledger.root)["valid"])
        self.assertEqual(
            self.service.view("alice-token", self.case.ref)["budget"], budget
        )
        self.assertEqual(len(self.case.children), self.child_count)

    def test_saved_sdk_completion_and_true_reopen_replay_preserve_original_bytes(self):
        self.inputs = self.case.root / "authored-sdk-next"
        self.inputs.mkdir()
        output = (self.inputs / "source").resolve()
        self.arguments.update(
            source_uri="https://example.org/study",
            tool="research_hub.source_fetch",
            request=dict(
                operation="source fetch",
                doi="",
                url="https://example.org/study",
                title=package_fixture.TITLE,
                output_dir=str(output),
                public_only=True,
            ),
        )
        self.start_sha = sha(canonical(self.arguments))
        prepared = self.start()
        self.assertEqual(
            (prepared["status"], prepared["outcome"]),
            ("completed", "observed"),
            prepared,
        )
        source_id = prepared["result"]["source_id"]
        start = self.ledger.event(source_id, "SourceReadStarted")
        self.assertEqual(start["request"], self.arguments["request"])
        # The existing fixture calls the real pinned SDK parser with authored
        # response bytes and mocked HTTP/DNS. It does not acquire any source.
        package_fixture.ResearchDeliverableTests.make_records(self)
        path = output / "source-fetch-result.json"
        original = path.read_bytes()
        receipt = read_json(path)

        def complete(ledger):
            return complete_saved_source(
                ledger,
                materials_root=self.case.root,
                source_id=source_id,
                expected_start=start,
                result_path=path,
                expected_result_sha256=sha(original),
                runtime_sha256="1" * 64,
                reason="Authored SDK observation; not native/source execution attestation.",
            )

        finished, digest, expected = self.finish(source_id, producer=complete)
        self.assertEqual(
            (finished["status"], finished["outcome"]),
            ("completed", "observed"),
            finished,
        )
        result = finished["result"]
        finish = self.ledger.event(result["finish_event_id"], "SourceReadFinished")
        self.assertEqual(result["source_id"], source_id)
        self.assertEqual(result["finish"], finish)
        self.assertEqual(result["original_receipt_sha256"], sha(original))
        self.assertEqual(result["sdk_receipt_sha256"], receipt["receipt_sha256"])
        self.assertEqual(result["runtime_sha256"], "1" * 64)
        self.assertIn("not execution attestation", result["evidence_scope"])
        self.assertFalse(finished["external_execution"])
        self.assertFalse(finished["model_execution"])
        self.assertFalse(finished["automatic_retry"])
        self.assertEqual(
            sha(self.ledger.read_ref(finish["raw_ref"])), receipt["raw_sha256"]
        )
        self.assertEqual(
            sha(self.ledger.read_ref(finish["text_ref"])),
            receipt["extracted_text_sha256"],
        )
        description = result["source_description"]
        self.assertEqual(description["result_sha256"], sha(original))
        self.assertEqual(
            description["artifacts"],
            {
                relative: sha((path.parent / relative).read_bytes())
                for relative in description["artifacts"]
            },
        )
        self.assertEqual(path.read_bytes(), original)
        self.assertTrue(validate_run(self.ledger.root)["valid"])
        old_store, old_owner = self.service.store, self.project["owner"]
        self.reopen_inner()
        self.assertIsNot(self.service.store, old_store)
        self.assertNotEqual(self.project["owner"], old_owner)
        before = self.inventory()
        with (
            patch.object(
                CoverageLedger,
                "finish_source",
                side_effect=AssertionError("duplicate Core completion"),
            ) as repeated_write,
            patch.object(
                self.service, "_execute", side_effect=AssertionError("source reader")
            ),
        ):
            repeated = self.observations.finish(
                "alice-token",
                self.case.ref,
                "source-finish",
                digest,
                expected,
                source_id,
                lambda ledger: self.fail("replay called SDK completion"),
            )
            self.assertEqual(repeated, finished)
            self.assertEqual(
                self.observations.read("alice-token", self.case.ref)[
                    "pending_source_ids"
                ],
                [],
            )
            repeated_write.assert_not_called()
        self.assertEqual(before, self.inventory())
        self.assertEqual(len(self.case.children), self.child_count)

    def test_generic_saved_writer_and_search_offer_still_refuse_pending_source(self):
        self.start()
        current = self.observations.read("alice-token", self.case.ref)["tree_sha256"]
        before = self.inventory()
        with self.assertRaisesRegex(SessionApiError, "query-pending-write"):
            self.service.inspect_saved("alice-token", self.case.ref)
        with self.assertRaisesRegex(SessionApiError, "query-pending-source"):
            self.service.offer("alice-token", self.case.ref)
        with (
            patch.object(
                self.ledger, "checkpoint", side_effect=AssertionError("generic write")
            ),
            self.assertRaisesRegex(SessionApiError, "query-pending-write"),
        ):
            self.service.mutate_saved(
                "alice-token",
                self.case.ref,
                "blocked-generic",
                "9" * 64,
                current,
                "stage1-checkpoint",
                lambda ledger: ledger.checkpoint(),
            )
        self.assertEqual(before, self.inventory())

    def test_unowned_pending_refuses_even_with_a_consistent_new_store_frontier(self):
        source_id = self.ledger.start_source(**self.arguments)
        # An actual Core event and even a consistent new store frontier do not
        # constitute this adapter's exact source preparation observation.
        with self.service.store._edit(
            self.project["pid"],
            self.project["owner"],
            None,
            "fixture-unowned-source",
            {},
        ) as state:
            state["query_ledger_sha256"] = tree_sha(self.ledger.root)
        self.assertIn(source_id, self.ledger.pending())
        before = self.inventory()
        with self.assertRaisesRegex(SessionApiError, "source-pending-attempt-unowned"):
            self.observations.read("alice-token", self.case.ref)
        self.assertEqual(before, self.inventory())

    def test_changed_saved_start_digest_refuses_without_repair_or_core_write(self):
        source_id = self.start()["result"]["source_id"]
        with self.service.store._edit(
            self.project["pid"], self.project["owner"], None, "fixture-start-drift", {}
        ) as state:
            state["source_read_observations"][source_id]["start_sha256"] = "0" * 64
        before = self.inventory()
        with self.assertRaisesRegex(SessionApiError, "source-pending-attempt-unowned"):
            self.observations.read("alice-token", self.case.ref)
        self.assertEqual(before, self.inventory())

    def test_same_key_replays_before_frontier_and_changed_payload_refuses(self):
        first = self.start()
        before = self.inventory()
        self.assertEqual(first, self.start())
        changed = dict(self.arguments, reason="Changed source purpose")
        with self.assertRaisesRegex(
            SessionApiError, "source-idempotency-payload-differs"
        ):
            self.observations.start(
                "alice-token",
                self.case.ref,
                "source-start",
                self.start_sha,
                self.initial_tree,
                changed,
            )
        with self.assertRaisesRegex(
            SessionApiError, "source-idempotency-payload-differs"
        ):
            self.observations.start(
                "alice-token",
                self.case.ref,
                "source-start",
                "f" * 64,
                self.initial_tree,
                self.arguments,
            )
        self.assertEqual(before, self.inventory())
        source_id = first["result"]["source_id"]
        finished, digest, expected = self.finish(source_id)
        self.assertEqual(
            (finished["status"], finished["outcome"]),
            ("completed", "observed"),
            finished,
        )
        before = self.inventory()
        with patch.object(
            self.ledger, "finish_source", side_effect=AssertionError("duplicate finish")
        ):
            repeated = self.observations.finish(
                "alice-token",
                self.case.ref,
                "source-finish",
                digest,
                expected,
                source_id,
                lambda ledger: self.fail("replay called producer"),
            )
        self.assertEqual(finished, repeated)
        self.assertEqual(before, self.inventory())

    def test_principal_project_stale_tree_and_wrong_finish_refuse_without_mutation(
        self,
    ):
        before = self.inventory()
        for token, ref in (
            ("bob-token", self.case.ref),
            ("alice-token", "another-project"),
        ):
            with self.assertRaisesRegex(SessionApiError, "query-project-denied"):
                self.observations.read(token, ref)
            with self.assertRaisesRegex(SessionApiError, "query-project-denied"):
                self.observations.start(
                    token,
                    ref,
                    "source-start",
                    self.start_sha,
                    self.initial_tree,
                    self.arguments,
                )
        with self.assertRaisesRegex(SessionApiError, "source-local-frontier-stale"):
            self.observations.start(
                "alice-token",
                self.case.ref,
                "source-stale",
                self.start_sha,
                "0" * 64,
                self.arguments,
            )
        self.assertEqual(before, self.inventory())
        self.start()
        current = self.observations.read("alice-token", self.case.ref)["tree_sha256"]
        before = self.inventory()
        with self.assertRaisesRegex(
            SessionApiError, "source-finish-owned-start-required"
        ):
            self.observations.finish(
                "alice-token",
                self.case.ref,
                "wrong-finish",
                "a" * 64,
                current,
                "wrong-source",
                lambda ledger: self.fail("wrong source ran"),
            )
        self.assertEqual(before, self.inventory())

    def test_true_sqlite_reopen_retains_pending_history_without_reader_or_retry(self):
        start = self.start()
        source_id = start["result"]["source_id"]
        previous_owner = self.project["owner"]
        old_observations = self.observations
        old_store = self.service.store
        self.reopen_inner()
        self.assertIsNot(self.service.store, old_store)
        self.assertNotEqual(self.project["owner"], previous_owner)
        with self.assertRaisesRegex(SessionApiError, "query-service-closed"):
            old_observations.read("alice-token", self.case.ref)
        before = self.inventory()
        with (
            patch.object(
                self.service, "_execute", side_effect=AssertionError("reader")
            ),
            patch.object(
                self.service, "_admit", side_effect=AssertionError("admission")
            ),
            patch.object(
                self.service, "_verify_source", side_effect=AssertionError("probe")
            ),
        ):
            self.assertEqual(
                self.observations.read("alice-token", self.case.ref)[
                    "pending_source_ids"
                ],
                [source_id],
            )
            self.assertEqual(start, self.start())
        self.assertEqual(before, self.inventory())
        self.assertEqual(len(self.case.children), self.child_count)

    def test_real_owner_loss_after_core_finish_is_unknown_and_replay_never_runs(self):
        source_id = self.start()["result"]["source_id"]
        connection = self.service.store._owners[self.project["pid"]][1]
        producer = self.producer(source_id)

        def finish_then_lose(ledger):
            output = producer(ledger)
            connection.rollback()
            self.assertFalse(connection.in_transaction)
            return output

        row, digest, expected = self.finish(source_id, producer=finish_then_lose)
        self.assertEqual(
            (row["status"], row["outcome"]), ("execution-unknown", "unknown"), row
        )
        self.assertIn("output_observation", row, row)
        self.assertIn("finish_event_id", row["output_observation"])
        self.assertFalse(connection.in_transaction)
        self.assertNotIn(source_id, self.ledger.pending())
        self.assertEqual(
            row, self.service.get_action("alice-token", self.case.ref, "source-finish")
        )
        self.reopen_inner()
        before = self.inventory()
        with self.assertRaisesRegex(
            SessionApiError, "source-unreconciled-local-action"
        ):
            self.observations.read("alice-token", self.case.ref)
        repeated = self.observations.finish(
            "alice-token",
            self.case.ref,
            "source-finish",
            digest,
            expected,
            source_id,
            lambda ledger: self.fail("unknown replay called producer"),
        )
        self.assertEqual(row, repeated)
        self.assertEqual(before, self.inventory())
        self.assertEqual(len(self.case.children), self.child_count)

    def test_owner_loss_after_finished_sql_rolls_back_publication_and_saves_unknown(
        self,
    ):
        source_id = self.start()["result"]["source_id"]
        store = self.service.store
        original_db = store.db
        connection = store._owners[self.project["pid"]][1]
        injected = []

        class LoseAfterSql:
            def __getattr__(self, name):
                return getattr(original_db, name)

            def execute(self, sql, parameters=()):
                result = original_db.execute(sql, parameters)
                if (
                    sql.startswith("INSERT INTO events")
                    and parameters[2] == "source-observation-finished"
                    and not injected
                ):
                    connection.rollback()
                    injected.append(True)
                return result

        with patch.object(store, "db", LoseAfterSql()):
            row, _, _ = self.finish(source_id)
        self.assertEqual(injected, [True], row)
        self.assertEqual(
            (row["status"], row["outcome"]), ("execution-unknown", "unknown"), row
        )
        self.assertIn("output_observation", row, row)
        self.assertIn("finish_event_id", row["output_observation"])
        saved = store.snapshot(self.project["pid"])
        self.assertNotIn(
            "finish_event_id", saved["source_read_observations"][source_id]
        )
        self.assertNotEqual(saved["query_ledger_sha256"], tree_sha(self.ledger.root))
        published = [
            event
            for event in store.events(self.project["pid"])
            if event["kind"] == "source-observation-finished"
            and event["payload"].get("client_key") == "source-finish"
        ]
        self.assertEqual(published, [])
        self.assertEqual(len(self.case.children), self.child_count)

    def test_owner_loss_after_intent_sql_refuses_before_any_core_mutation(self):
        store = self.service.store
        original_db = store.db
        connection = store._owners[self.project["pid"]][1]
        injected = []
        before = self.inventory()

        class LoseAfterIntentSql:
            def __getattr__(self, name):
                return getattr(original_db, name)

            def execute(self, sql, parameters=()):
                result = original_db.execute(sql, parameters)
                if (
                    sql.startswith("INSERT INTO events")
                    and parameters[2] == "source-observation-intent"
                    and not injected
                ):
                    connection.rollback()
                    injected.append(True)
                return result

        with (
            patch.object(store, "db", LoseAfterIntentSql()),
            patch.object(
                CoverageLedger,
                "start_source",
                side_effect=AssertionError("Core producer"),
            ) as core_start,
            self.assertRaisesRegex(SessionApiError, "query-ledger-owner-lost"),
        ):
            self.start()
        self.assertEqual(injected, [True])
        core_start.assert_not_called()
        self.assertEqual(before, self.inventory())
        self.assertFalse(connection.in_transaction)


if __name__ == "__main__":
    unittest.main()

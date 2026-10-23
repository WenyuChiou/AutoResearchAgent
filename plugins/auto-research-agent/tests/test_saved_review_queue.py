"""Explicit queue admission/owner reports, real SQLite, no worker or research."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, redirect_stdout
from io import StringIO
import json
import os
import sqlite3
import unittest
from unittest.mock import patch

import test_saved_package_review as fixtures
from research_workspace_native.maintenance_inbox import (
    MaintenanceInbox,
    MaintenanceInboxError,
)
from research_workspace_native.saved_review_queue import (
    SavedReviewQueueService,
    SCHEMA,
    main,
)
from stage1_deliverable.common import canonical, sha


class SavedReviewQueueTests(unittest.TestCase):
    build = fixtures.SavedPackageReviewTests.build
    request = fixtures.SavedPackageReviewTests.request
    tearDown = fixtures.SavedPackageReviewTests.tearDown

    def setUp(self):
        fixtures.SavedPackageReviewTests.setUp(self)
        self.results = self.root / "Owner results with spaces"
        self.results.mkdir()
        self.policy = dict(
            schema_version=SCHEMA,
            routes={
                op: dict(
                    owner_ref=owner,
                    admit_principals=["reviewer-a"],
                    owner_principals=principals,
                )
                for op, owner, principals in [
                    ("submit-review", "review-followup", ["worker-a", "worker-b"]),
                    ("request-fix", "stage1-owner", ["worker-a", "worker-b"]),
                    ("request-handoff", "Core-owner", ["Core-worker"]),
                ]
            },
        )
        self.queue = self.build_queue()

    def build_queue(self, review=None, **kwargs):
        return SavedReviewQueueService(
            review or self.service,
            registration_path=self.registration_path,
            policy=self.policy,
            result_root=self.results,
            **kwargs,
        )

    def saved(self, operation="request-fix", key="original"):
        return self.service.submit(
            "reviewer-a",
            self.service.ref,
            self.request(operation, key=key, target=operation != "request-handoff"),
        )

    def admission(self, saved, key="admit"):
        return dict(
            key=key,
            source_key=saved["key"],
            source_record_sha256=saved["record_sha256"],
            source_review_revision=saved["review_revision"],
            confirmed=True,
        )

    def admit(self, operation="request-fix", key="original", admission_key="admit"):
        saved = self.saved(operation, key)
        return self.queue.admit(
            "reviewer-a", self.service.ref, self.admission(saved, admission_key)
        )

    def claim(self, admitted, principal="worker-a"):
        return self.queue.claim(
            principal,
            admitted["queue_ref"],
            dict(key="claim-" + admitted["key"], revision=1, confirmed=True),
        )

    def result(self):
        raw = b'{"kind":"OwnerReportedCandidate","Core_acceptance":false}'
        (self.results / "candidate.json").write_bytes(raw)
        return dict(path="candidate.json", bytes=len(raw), sha256=sha(raw))

    def finish_body(self, ref=None, **changes):
        value = dict(
            key="finish",
            revision=2,
            outcome="completed",
            reason="Actual owner report; independent acceptance still pending.",
            new_delivery_ref=ref or self.result(),
            confirmed=True,
        )
        value.update(changes)
        return value

    @contextmanager
    def rehashed(self, key, mutate, **columns):
        """Simulate local corruption/import after bypassing append-only triggers."""
        row = dict(
            self.inbox.db.execute(
                "SELECT * FROM maintenance_queue_events WHERE event_key=?", (key,)
            ).fetchone()
        )
        value = json.loads(row["payload"])
        mutate(value)
        changed = dict(
            row,
            payload=canonical(value).decode(),
            digest=sha(canonical(value)),
            **columns,
        )
        self.inbox.db.execute("DROP TRIGGER maintenance_queue_events_no_UPDATE")

        def update(data, current_seq):
            names = list(data)
            self.inbox.db.execute(
                "UPDATE maintenance_queue_events SET "
                + ",".join(n + "=?" for n in names)
                + " WHERE seq=?",
                [data[n] for n in names] + [current_seq],
            )

        update(changed, row["seq"])
        try:
            yield
        finally:
            update(row, changed["seq"])
            self.inbox.db.execute(
                "CREATE TRIGGER maintenance_queue_events_no_UPDATE BEFORE UPDATE ON maintenance_queue_events BEGIN SELECT RAISE(ABORT, 'immutable maintenance queue'); END"
            )

    def test_rehashed_authority_flags_and_exact_top_fields_are_rejected(self):
        admitted = self.admit()
        changes = [
            (name, value)
            for name in (
                "Core_acceptance",
                "execution_authorized",
                "research_execution_authorized",
                "formal_Stage2_import",
            )
            for value in (True, 0)
        ] + [
            ("owner_report_only", False),
            ("owner_report_only", 1),
            ("unexpected", True),
        ]
        for name, value in changes:
            with (
                self.subTest(name=name, value=value),
                self.rehashed("admit", lambda v: v.update({name: value})),
            ):
                with self.assertRaises(ValueError):
                    self.queue.action("reviewer-a", admitted["queue_ref"])
                with self.assertRaises(ValueError):
                    self.queue.admit("reviewer-a", self.service.ref, admitted["body"])

    def test_rehashed_admission_status_actor_body_and_row_binding_are_rejected(self):
        admitted = self.admit()
        mutations = [
            lambda v: v.update(status="owner-reported-completed"),
            lambda v: v.update(principal_ref="Core-worker"),
            lambda v: v.update(principal_ref="worker-a"),
            lambda v: v.update(action="finish"),
            lambda v: v.update(queue_revision=True),
            lambda v: v["body"].update(key="different-key"),
            lambda v: v["body"].update(confirmed=1),
            lambda v: v["body"].update(source_record_sha256="a" * 64),
            lambda v: v["body"].update(source_review_revision=True),
            lambda v: v["body"].update(source_key="not-the-original"),
            lambda v: v["body"].update(revision=1),
            lambda v: v["body"].pop("confirmed"),
            lambda v: v["source"]["context"].update(execution_authorized=True),
            lambda v: v.update(new_delivery_ref=self.result()),
        ]
        for i, mutate in enumerate(mutations):
            with self.subTest(mutation=i), self.rehashed("admit", mutate):
                with self.assertRaises(ValueError):
                    self.queue.action("reviewer-a", admitted["queue_ref"])
        for columns in ({"case_ref": "another-case"}, {"event_key": "another-key"}):
            with (
                self.subTest(columns=columns),
                self.rehashed("admit", lambda _: None, **columns),
            ):
                with self.assertRaises(ValueError):
                    self.queue.action("reviewer-a", admitted["queue_ref"])
        forged = "saved-queue-" + "a" * 40
        with self.rehashed(
            "admit", lambda v: v.update(queue_ref=forged), queue_ref=forged
        ):
            with self.assertRaises(ValueError):
                self.queue.action("reviewer-a", forged)

    def test_rehashed_owner_chain_result_shape_and_order_are_rejected(self):
        admitted = self.admit()
        self.claim(admitted)
        self.queue.finish("worker-a", admitted["queue_ref"], self.finish_body())
        mutations = [
            ("claim-admit", lambda v: v["body"].update(revision=2), {}),
            ("claim-admit", lambda v: v.update(principal_ref="worker-b"), {}),
            ("claim-admit", lambda _: None, {"seq": -1}),
            ("finish", lambda v: v.update(principal_ref="worker-b"), {}),
            ("finish", lambda v: v["body"].update(revision=1), {}),
            ("finish", lambda v: v.update(status="queued-for-owner"), {}),
            ("finish", lambda v: v.update(new_delivery_ref=None), {}),
            (
                "finish",
                lambda v: (
                    v.update(new_delivery_ref=None),
                    v["body"].update(new_delivery_ref=None),
                ),
                {},
            ),
        ]
        for key, mutate, columns in mutations:
            with (
                self.subTest(key=key, columns=columns),
                self.rehashed(key, mutate, **columns),
            ):
                with self.assertRaises(ValueError):
                    self.queue.history("reviewer-a", admitted["queue_ref"])
        for change in (
            {"path": "../candidate.json"},
            {"bytes": True},
            {"sha256": "invalid"},
        ):

            def mutate(value):
                value["body"]["new_delivery_ref"].update(change)
                value["new_delivery_ref"].update(change)

            with self.subTest(result=change), self.rehashed("finish", mutate):
                with self.assertRaises(ValueError):
                    self.queue.action("reviewer-a", admitted["queue_ref"])

        claim = self.inbox.db.execute(
            "SELECT * FROM maintenance_queue_events WHERE event_key='claim-admit'"
        ).fetchone()
        self.inbox.db.execute("DROP TRIGGER maintenance_queue_events_no_DELETE")
        self.inbox.db.execute(
            "DELETE FROM maintenance_queue_events WHERE event_key='claim-admit'"
        )
        try:
            with self.assertRaises(ValueError):
                self.queue.history("reviewer-a", admitted["queue_ref"])
        finally:
            self.inbox.db.execute(
                "INSERT INTO maintenance_queue_events VALUES(?,?,?,?,?,?,?,?)",
                tuple(claim),
            )
            self.inbox.db.execute(
                "CREATE TRIGGER maintenance_queue_events_no_DELETE BEFORE DELETE ON maintenance_queue_events BEGIN SELECT RAISE(ABORT, 'immutable maintenance queue'); END"
            )

    def test_completed_history_and_same_key_replay_do_not_read_current_result_bytes(
        self,
    ):
        admitted = self.admit()
        self.claim(admitted)
        body = self.finish_body()
        completed = self.queue.finish("worker-a", admitted["queue_ref"], body)
        (self.results / "candidate.json").unlink()
        with patch(
            "research_workspace_native.saved_review_queue.read",
            side_effect=AssertionError("passive read"),
        ):
            self.assertEqual(
                self.queue.action("reviewer-a", admitted["queue_ref"]), completed
            )
            replay = self.queue.finish("worker-a", admitted["queue_ref"], body)
            self.assertTrue(replay["replayed"])
            self.assertEqual(replay["record_sha256"], completed["record_sha256"])

    def test_all_three_intents_route_explicitly_and_original_rows_stay_unchanged(self):
        for i, operation in enumerate(self.policy["routes"]):
            saved = self.saved(operation, f"source-{i}")
            before = [
                tuple(r)
                for r in self.inbox.db.execute("SELECT * FROM maintenance_feedback")
            ]
            with (
                patch("subprocess.Popen", side_effect=AssertionError("no worker")),
                patch(
                    "socket.create_connection", side_effect=AssertionError("no network")
                ),
            ):
                queued = self.queue.admit(
                    "reviewer-a", self.service.ref, self.admission(saved, f"admit-{i}")
                )
            self.assertEqual(queued["status"], "queued-for-owner")
            self.assertEqual(
                queued["owner_ref"], self.policy["routes"][operation]["owner_ref"]
            )
            self.assertEqual(queued["source"]["context"], saved["context"])
            self.assertEqual(queued["source"]["target"], saved["target"])
            self.assertIsNone(queued["new_delivery_ref"])
            self.assertFalse(
                queued["Core_acceptance"]
                or queued["formal_Stage2_import"]
                or queued["research_execution_authorized"]
            )
            self.assertEqual(
                before,
                [
                    tuple(r)
                    for r in self.inbox.db.execute("SELECT * FROM maintenance_feedback")
                ],
            )
            self.assertEqual(
                self.service.action(self.service.ref, saved["key"])["status"],
                "recorded-not-dispatched",
            )

    def test_later_review_does_not_invalidate_original_request_revision(self):
        original = self.saved()
        self.saved("submit-review", "later-opinion")
        admitted = self.queue.admit(
            "reviewer-a", self.service.ref, self.admission(original)
        )
        self.assertEqual(admitted["source"]["review_revision"], 1)
        self.assertEqual(admitted["queue_revision"], 1)

    def test_original_A03_string_input_survives_queue_without_active_project(self):
        inbox, review = fixtures.SavedPackageReviewTests.input_registration(
            self, "20261009-A03", "known-input"
        )
        try:
            queue = SavedReviewQueueService(
                review,
                registration_path=self.root / "known-input.json",
                policy=self.policy,
                result_root=self.results,
            )
            body = self.request("request-fix")
            body["offer"] = review.offer(
                "reviewer-a", review.ref, "request-fix", self.target
            )
            saved = review.submit("reviewer-a", review.ref, body)
            admitted = queue.admit("reviewer-a", review.ref, self.admission(saved))
            self.assertEqual(
                admitted["source"]["context"]["input_version"], "20261009-A03"
            )
            self.assertIsNone(admitted["source"]["context"]["active_project_ref"])
        finally:
            inbox.close()

    def test_owner_claim_complete_and_real_reopen_keep_original_unknowns(self):
        admitted = self.admit()
        claim = self.claim(admitted)
        completed = self.queue.finish(
            "worker-a", admitted["queue_ref"], self.finish_body()
        )
        self.assertEqual(completed["status"], "owner-reported-completed")
        self.assertTrue(completed["owner_report_only"])
        self.inbox.close()
        self.inbox = MaintenanceInbox(self.db, self.bindings)
        self.service = self.build(self.inbox)
        self.queue = self.build_queue(allow_register=False)
        self.assertEqual(
            self.queue.history("reviewer-a", admitted["queue_ref"]),
            [admitted, claim, completed],
        )
        self.assertIsNone(completed["source"]["context"]["original_run_id"])
        self.assertIsNone(completed["source"]["context"]["input_version"])

    def test_two_sqlite_handles_same_key_deduplicate_without_worker(self):
        saved = self.saved()
        other = MaintenanceInbox(self.db, self.bindings)
        try:
            second = self.build_queue(self.build(other), allow_register=False)
            body = self.admission(saved)
            with ThreadPoolExecutor(max_workers=2) as pool:
                receipts = list(
                    pool.map(
                        lambda q: q.admit("reviewer-a", self.service.ref, body),
                        [self.queue, second],
                    )
                )
            self.assertEqual(sum(not r["replayed"] for r in receipts), 1)
            self.assertEqual(
                len(self.queue.history("reviewer-a", receipts[0]["queue_ref"])), 1
            )

            def claim(q, actor, key):
                try:
                    return q.claim(
                        actor,
                        receipts[0]["queue_ref"],
                        dict(key=key, revision=1, confirmed=True),
                    )
                except MaintenanceInboxError as error:
                    return str(error)

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = [
                    f.result()
                    for f in [
                        pool.submit(claim, self.queue, "worker-a", "claim-a"),
                        pool.submit(claim, second, "worker-b", "claim-b"),
                    ]
                ]
            self.assertEqual(sum(isinstance(row, dict) for row in outcomes), 1)
            self.assertIn("stale-queue-revision", outcomes)
            with self.assertRaisesRegex(MaintenanceInboxError, "already-admitted"):
                self.queue.admit(
                    "reviewer-a", self.service.ref, dict(body, key="another-key")
                )
            with self.assertRaises(MaintenanceInboxError):
                self.queue.claim(
                    "worker-a",
                    receipts[0]["queue_ref"],
                    dict(key="admit", revision=1, confirmed=True),
                )
        finally:
            other.close()

    def test_wrong_principal_reference_record_revision_and_policy_refuse(self):
        saved = self.saved()
        body = self.admission(saved)
        for principal, ref, change in [
            ("other", self.service.ref, {}),
            ("reviewer-a", "another-project", {}),
            ("reviewer-a", self.service.ref, {"source_record_sha256": "a" * 64}),
            ("reviewer-a", self.service.ref, {"source_review_revision": True}),
            ("reviewer-a", self.service.ref, {"owner_ref": "chosen-by-browser"}),
            ("reviewer-a", self.service.ref, {"confirmed": False}),
        ]:
            with self.subTest(change=change), self.assertRaises(MaintenanceInboxError):
                self.queue.admit(principal, ref, dict(body, **change))
        self.policy["routes"]["request-fix"]["owner_ref"] = "another-owner"
        with self.assertRaisesRegex(MaintenanceInboxError, "policy-binding"):
            self.build_queue()

    def test_claim_and_result_require_owner_and_current_queue_cas(self):
        admitted = self.admit()
        self.claim(admitted)
        for actor, revision in [
            ("reviewer-a", 2),
            ("Core-worker", 2),
            ("worker-b", 2),
            ("worker-a", 1),
            ("worker-a", True),
        ]:
            with (
                self.subTest(actor=actor, revision=revision),
                self.assertRaises(MaintenanceInboxError),
            ):
                self.queue.finish(
                    actor, admitted["queue_ref"], self.finish_body(revision=revision)
                )
        with self.assertRaises(MaintenanceInboxError):
            self.queue.claim(
                "worker-a",
                admitted["queue_ref"],
                dict(key="second-claim", revision=2, confirmed=True),
            )
        with self.assertRaises(MaintenanceInboxError):
            self.queue.action("other-reviewer", admitted["queue_ref"])

    def test_handoff_requires_actual_Core_owner_claim_without_acceptance(self):
        admitted = self.admit("request-handoff")
        with self.assertRaises(MaintenanceInboxError):
            self.claim(admitted)
        self.claim(admitted, "Core-worker")
        failed = self.queue.finish(
            "Core-worker",
            admitted["queue_ref"],
            self.finish_body(
                outcome="failed",
                new_delivery_ref=None,
                reason="Trusted Core acceptance not supplied.",
            ),
        )
        self.assertEqual(failed["status"], "owner-reported-failed")
        self.assertFalse(failed["Core_acceptance"] or failed["formal_Stage2_import"])

    def test_result_path_size_hash_hardlinks_and_absent_result_refuse(self):
        admitted = self.admit()
        self.claim(admitted)
        original = self.result()
        for result in [
            None,
            dict(original, sha256="a" * 64),
            dict(original, bytes=1),
            dict(original, path="../candidate.json"),
            dict(original, path=str(self.results / "candidate.json")),
        ]:
            with self.subTest(result=result), self.assertRaises((ValueError, OSError)):
                self.queue.finish(
                    "worker-a",
                    admitted["queue_ref"],
                    self.finish_body(new_delivery_ref=result),
                )
        os.link(self.results / "candidate.json", self.results / "hardlink.json")
        with self.assertRaises(ValueError):
            self.queue.finish("worker-a", admitted["queue_ref"], self.finish_body())

    def test_deadline_post_insert_source_and_result_drift_roll_back(self):
        admitted = self.admit()
        self.claim(admitted)
        for mutate in ["deadline", "source", "result"]:
            original = (self.package / "source-a.txt").read_bytes()
            body = self.finish_body()
            count = 0

            def guard():
                nonlocal count
                count += 1
                if count == 2:
                    if mutate == "deadline":
                        raise TimeoutError("expired")
                    target = (
                        self.package / "source-a.txt"
                        if mutate == "source"
                        else self.results / "candidate.json"
                    )
                    target.write_bytes(b"changed during commit")

            with (
                self.subTest(mutate=mutate),
                self.assertRaises((ValueError, TimeoutError)),
            ):
                self.queue.finish(
                    "worker-a", admitted["queue_ref"], body, before_commit=guard
                )
            self.assertFalse(self.inbox.db.in_transaction)
            self.assertEqual(
                self.queue.action("reviewer-a", admitted["queue_ref"])[
                    "queue_revision"
                ],
                2,
            )
            (self.package / "source-a.txt").write_bytes(original)

    def test_drift_blocks_new_writes_but_key_replay_and_history_are_passive(self):
        saved = self.saved()
        body = self.admission(saved)
        admitted = self.queue.admit("reviewer-a", self.service.ref, body)
        (self.package / "source-a.txt").write_bytes(b"source drift")
        replay = self.queue.admit("reviewer-a", self.service.ref, body)
        self.assertTrue(replay["replayed"])
        with self.assertRaises(ValueError):
            self.claim(admitted)
        self.assertEqual(
            len(self.queue.history("reviewer-a", admitted["queue_ref"])), 1
        )
        self.registration_path.write_bytes(b"registration drift")
        with self.assertRaises(ValueError):
            self.claim(admitted)
        self.assertEqual(
            self.queue.action("reviewer-a", admitted["queue_ref"]), admitted
        )

    def test_append_only_tables_and_local_CLI_readback(self):
        admitted = self.admit()
        for table in ("maintenance_queue_bindings", "maintenance_queue_events"):
            for sql in [
                f"DELETE FROM {table}",
                f"UPDATE {table} SET case_ref='changed'",
            ]:
                with self.assertRaises(sqlite3.IntegrityError):
                    self.inbox.db.execute(sql)
        policy = self.root / "policy.json"
        policy.write_bytes(canonical(self.policy))
        argv = [
            "--database",
            str(self.db),
            "--package-root",
            str(self.package),
            "--registration",
            str(self.registration_path),
            "--expected-registration-sha256",
            self.registration_sha,
            "--policy",
            str(policy),
            "--expected-policy-sha256",
            sha(policy.read_bytes()),
            "--result-root",
            str(self.results),
            "action",
            "--principal",
            "reviewer-a",
            "--queue-ref",
            admitted["queue_ref"],
        ]
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(argv), 0)
        self.assertEqual(json.loads(output.getvalue()), admitted)


if __name__ == "__main__":
    unittest.main()

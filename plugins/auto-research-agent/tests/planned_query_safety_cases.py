"""Admission drift and canonical-store/working-clone boundaries, offline."""

import atlas_test_paths  # noqa: F401
from copy import deepcopy
from pathlib import Path
import time
from unittest.mock import patch

from stage1_deliverable.common import sha
from research_workspace_native.planned_queries import PlannedQueryService
from research_workspace_native.query_http import bind_query_registration
from research_workspace_native.session_api import SessionApiError
from planned_query_fixture import QueryCase, get_source_proof


class PlannedQuerySafetyTests(QueryCase):
    def test_config_drift_inside_final_admission_cannot_launch_child(self):
        def admit(event):
            if isinstance(event["phase"], dict):
                Path(self.pin["config"]["path"]).write_bytes(b'{"changed":true}')
            return True

        service = self.service(admit=admit)
        with self.no_probe(), self.fake_runner():
            service.execute(
                "secret", "case", self.request(service), deadline=time.monotonic() + 30
            )
            row = self.wait(service)
        self.assertEqual(row["status"], "execution-unknown")
        self.assertEqual(self.children, [])
        self.assertEqual(len(self.ledger.pending()), 2)
        self.assertEqual(
            service.view("secret", "case")["budget"], {"attempts": 1, "seconds": 32}
        )

    def test_runtime_byte_drift_inside_final_admission_cannot_launch_child(self):
        def admit(event):
            if isinstance(event["phase"], dict):
                Path(self.pin["argv_prefix"][0]).write_bytes(b"changed executable")
            return True

        service = self.service(admit=admit)
        with self.no_probe(), self.fake_runner():
            service.execute(
                "secret", "case", self.request(service), deadline=time.monotonic() + 30
            )
            row = self.wait(service)
        self.assertEqual(row["status"], "execution-unknown")
        self.assertEqual(self.children, [])

    def test_same_permit_cannot_reset_budget_by_switching_database(self):
        self.permit.update(max_attempts=1, max_reserved_seconds=32)
        self.write_permit()
        service = self.service()
        with self.no_probe(), self.fake_runner():
            service.execute(
                "secret", "case", self.request(service), deadline=time.monotonic() + 30
            )
            self.wait(service)
        service.close()
        with self.assertRaisesRegex(SessionApiError, "permit-store-differs"):
            PlannedQueryService(
                self.root / "second-query.sqlite3",
                registrations={"case": self.item},
                authenticate=lambda _: "researcher",
                admit=lambda _: True,
                verify_source=lambda _: get_source_proof(),
            )
        self.assertFalse((self.root / "second-query.sqlite3").exists())
        reopened = self.service()
        with self.assertRaisesRegex(SessionApiError, "budget-exhausted"):
            reopened.offer("secret", "case")
        self.assertEqual(len(self.children), 1)

    def test_missing_budget_database_with_retained_marker_does_not_reset(self):
        service = self.service()
        service.close()
        database = self.root / "query.sqlite3"
        self.assertTrue(database.with_name(database.name + ".created").exists())
        database.unlink()  # Test-owned temporary DB only, after confirmed close.
        with self.assertRaisesRegex(SessionApiError, "budget-journal-missing"):
            self.service()
        self.assertFalse(database.exists())

    def test_queued_request_or_delayed_admission_cannot_dispatch_after_http_deadline(
        self,
    ):
        expiry = time.monotonic() + 2

        def admit(event):
            clock.return_value = expiry + 1
            return True

        service = self.service(admit=admit)
        with patch(
            "research_workspace_native.planned_queries.time.monotonic",
            return_value=expiry - 1,
        ) as clock:
            service.execute("secret", "case", self.request(service), deadline=expiry)
            row = self.wait(service)
        self.assertEqual(row["outcome"], "refused-known-unsent")
        self.assertEqual(self.children, [])
        self.assertEqual(self.ledger.pending(), [])

    def test_immutable_parent_and_working_clone_remain_separate(self):
        service = self.service()
        before = sha((self.parent_ledger / "stage_events.jsonl").read_bytes())
        with self.no_probe(), self.fake_runner():
            service.execute(
                "secret", "case", self.request(service), deadline=time.monotonic() + 30
            )
            self.wait(service)
        self.assertEqual(
            before, sha((self.parent_ledger / "stage_events.jsonl").read_bytes())
        )
        self.assertNotEqual(
            before, sha((self.ledger_root / "stage_events.jsonl").read_bytes())
        )
        self.parent_ledger.joinpath("coverage_and_stop.md").write_bytes(
            b"changed parent source"
        )
        with self.assertRaisesRegex(SessionApiError, "parent-source-differs"):
            service.offer("secret", "case")
        self.assertEqual(len(self.children), 1)

    def test_source_missing_or_wrong_stage1_ledger_cannot_bind_existing_view(self):
        service = self.service()
        base = dict(
            **service.bindings()["case"],
            principals=["researcher"],
            inputs={1: None, 2: None},
        )
        for inputs in (
            {1: None, 2: None},
            {1: {"ledger_root": str(self.ledger_root)}, 2: None},
        ):
            with self.subTest(inputs=inputs):
                item = deepcopy(base)
                item["inputs"] = inputs
                with self.assertRaisesRegex(ValueError, "parent source"):
                    bind_query_registration(service, {"case": item})
        self.assertEqual(self.children, [])

    def test_wrong_clone_bytes_fail_before_budget_marker_creation(self):
        self.ledger_root.joinpath("coverage_and_stop.md").write_bytes(
            b"wrong working clone"
        )
        with self.assertRaisesRegex(SessionApiError, "clone-parent-bytes"):
            self.service()
        self.assertFalse((self.root / "query.sqlite3.created").exists())

    def test_source_provider_required_and_literal_true_before_store(self):
        for verifier in (None, lambda _: 1, lambda _: False):
            with self.subTest(verifier=verifier), self.assertRaises(SessionApiError):
                PlannedQueryService(
                    self.root / "query.sqlite3",
                    registrations={"case": self.item},
                    authenticate=lambda _: "researcher",
                    admit=lambda _: True,
                    verify_source=verifier,
                )
        self.assertFalse((self.root / "query.sqlite3").exists())
        self.assertFalse((self.root / "query.sqlite3.created").exists())

    def test_execution_source_drift_during_final_admission_is_unknown_zero_child(self):
        def admit(event):
            self.assertEqual(
                event["execution_source_sha256"], self.item["execution_source_sha256"]
            )
            if isinstance(event["phase"], dict):
                self.source_proof.write_bytes(b"changed executed source")
            return True

        service = self.service(admit=admit)
        with self.no_probe(), self.fake_runner():
            service.execute(
                "secret", "case", self.request(service), deadline=time.monotonic() + 30
            )
            row = self.wait(service)
        self.assertEqual(row["status"], "execution-unknown")
        self.assertEqual(row["error"]["code"], "query-execution-source-unobserved")
        self.assertEqual(self.children, [])
        self.assertEqual(
            service.view("secret", "case")["budget"], {"attempts": 1, "seconds": 32}
        )

    def test_windows_case_variant_uses_the_same_physical_ledger_lock(self):
        import os
        import sqlite3
        from research_workspace_native.query_storage import LedgerOwners

        if os.name != "nt":
            self.skipTest("Windows physical-path case semantics")
        first = LedgerOwners([self.ledger_root])
        try:
            with self.assertRaises(sqlite3.OperationalError):
                LedgerOwners([Path(str(self.ledger_root).swapcase())])
        finally:
            first.close()

    def test_cached_loader_or_mixed_module_origin_cannot_prepare_execution(self):
        import sys

        module = sys.modules["research_workspace_native.planned_queries"]
        for field, value in (
            ("__loader__", None),
            ("__file__", str(self.root / "different-service.py")),
        ):
            with self.subTest(field=field), patch.object(module, field, value):
                with self.assertRaisesRegex(
                    SessionApiError, "raw-loader-required|module-origin-differs"
                ):
                    self.service()
        self.assertFalse((self.root / "query.sqlite3").exists())
        self.assertEqual(self.children, [])

    def test_actual_runner_bytes_change_during_admission_blocks_spawn(self):
        import sys

        original_path = Path(sys.modules["stage1_retrieval.runner"].__file__)
        original = original_path.read_bytes()

        def admit(event):
            if isinstance(event["phase"], dict):
                original_path.write_bytes(original + b"# source drift\n")
            return True

        service = self.service(admit=admit)
        try:
            with self.no_probe(), self.fake_runner():
                service.execute(
                    "secret",
                    "case",
                    self.request(service),
                    deadline=time.monotonic() + 30,
                )
                row = self.wait(service)
            self.assertEqual(row["status"], "execution-unknown")
            self.assertEqual(self.children, [])
        finally:
            original_path.write_bytes(original)

    def test_manifest_provider_boolean_or_wrong_hash_never_writes_store(self):
        from planned_query_fixture import get_source_proof

        bad = get_source_proof()
        bad["files"][next(iter(bad["files"]))] = "0" * 64
        for proof in (True, bad):
            with (
                self.subTest(proof=type(proof).__name__),
                self.assertRaisesRegex(
                    SessionApiError, "source-unobserved|manifest-differs"
                ),
            ):
                self.service(verify_source=lambda _: proof)
        self.assertFalse((self.root / "query.sqlite3").exists())
        self.assertEqual(self.children, [])

    def test_replacement_executor_callable_cannot_bypass_pinned_runner(self):
        with self.assertRaisesRegex(SessionApiError, "runner-origin-differs"):
            self.service(executor=lambda *args, **kwargs: "unbound")
        self.assertFalse((self.root / "query.sqlite3").exists())
        self.assertEqual(self.children, [])

    def test_drive_relative_source_manifest_never_reads_external_file(self):
        import os
        from stage1_deliverable.common import canonical

        if os.name != "nt":
            self.skipTest("Windows drive-relative paths")
        proof = get_source_proof()
        proof["files"]["C:never-read-query-source.py"] = "0" * 64
        self.item["execution_source_sha256"] = sha(canonical(proof["files"]))
        self.permit["binding"]["execution_source_sha256"] = self.item[
            "execution_source_sha256"
        ]
        self.write_permit()
        with self.assertRaisesRegex(SessionApiError, "source-path-invalid"):
            self.service(verify_source=lambda _: proof)
        self.assertFalse((self.root / "query.sqlite3").exists())
        self.assertEqual(self.children, [])

    def test_admission_input_mutation_cannot_change_confirmed_query_or_budget(self):
        from stage1_deliverable.common import canonical

        state = self.ledger.coverage_state()
        alternate = self.permit["planned_ids"][1]

        def admit(event):
            event["offer"]["planned_id"] = alternate
            event["offer"]["arguments"] = state.arguments(alternate)
            event["budget"]["attempts"] = 999
            if isinstance(event["phase"], dict):
                event["phase"]["argv"].clear()
            return True

        service = self.service(admit=admit)
        confirmed = service.offer("secret", "case")
        with self.no_probe(), self.fake_runner():
            service.execute(
                "secret", "case", self.request(service), deadline=time.monotonic() + 30
            )
            row = self.wait(service)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["offer"], confirmed["document"])
        self.assertEqual(sha(canonical(row["offer"])), confirmed["offer_sha256"])
        query = self.ledger.event(row["result"]["query_id"], "ActionStarted")
        self.assertEqual(query["arguments"], confirmed["document"]["arguments"])
        self.assertEqual(
            query["arguments"]["coverage"]["planned_query_id"],
            self.permit["planned_ids"][0],
        )
        self.assertEqual(
            service.view("secret", "case")["budget"], {"attempts": 1, "seconds": 32}
        )
        self.assertEqual(len(self.children), 1)

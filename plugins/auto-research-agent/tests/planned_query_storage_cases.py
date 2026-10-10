"""Canonical budget identity and exclusive ledger ownership, offline."""

import atlas_test_paths  # noqa: F401
import sqlite3
from research_workspace_native.planned_query_contract import inspect_registration
from research_workspace_native.query_storage import budget_path, LedgerOwners
from research_workspace_native.query_execution_source import check_execution_source
from research_workspace_native.session_api import SessionApiError
from planned_query_fixture import QueryCase, get_source_proof


class PlannedQueryStorageTests(QueryCase):
    def prepared(self):
        return [("case", *inspect_registration("case", self.item, require_ready=False))]

    def test_other_database_cannot_claim_the_same_permit(self):
        with self.assertRaisesRegex(SessionApiError, "permit-store-differs"):
            budget_path(self.root / "other.sqlite3", self.prepared())
        self.assertFalse((self.root / "other.sqlite3").exists())
        self.assertFalse((self.root / "other.sqlite3.created").exists())

    def test_retained_marker_without_database_cannot_reset_budget(self):
        database = budget_path(self.root / "query.sqlite3", self.prepared())
        self.assertFalse(database.exists())
        self.assertTrue((self.root / "query.sqlite3.created").is_file())
        with self.assertRaisesRegex(SessionApiError, "budget-journal-missing"):
            budget_path(database, self.prepared())

    def test_physical_root_alias_cannot_acquire_second_ledger_owner(self):
        first = LedgerOwners([self.ledger_root])
        try:
            with self.assertRaises(sqlite3.OperationalError):
                LedgerOwners([self.ledger_root / ".." / self.ledger_root.name])
        finally:
            first.close()

    def test_boolean_or_wrong_manifest_is_not_source_attestation(self):
        bad = get_source_proof()
        bad["files"][next(iter(bad["files"]))] = "0" * 64
        for proof in (True, bad):
            with (
                self.subTest(proof=type(proof).__name__),
                self.assertRaises(SessionApiError),
            ):
                check_execution_source(
                    lambda _: proof, "case", self.item, "before-store"
                )
        self.assertEqual(self.children, [])

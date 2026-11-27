"""Selecting before the Stage2 source is registered must leave nothing behind.

The synthetic fixture never calls a model or does real research. A selection
that cannot start (no registered binding) is refused before the durable intent,
so it never becomes an unrecoverable "execution-unknown" action.
"""

# ruff: noqa: E402 -- exercise repository CLI and authored fixtures.
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parent),
]
from project_stage2_selection_fixture import Stage2SelectionFixture
from research_workspace_native.project_stage2_selection import (
    ProjectStage2SelectionService,
)
from research_workspace_native.session_api import SessionApiError


def footprint(intake, ref):
    return (
        intake.read("own", ref)["revision"],
        tuple(
            intake.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("intake_actions", "intake_events")
        ),
        sorted(path.name for path in (intake.root / ref).iterdir())
        if (intake.root / ref).exists()
        else [],
    )


class UnboundSelectionTests(Stage2SelectionFixture):
    def prepare_choice(self):
        return super().prepare_choice(ProjectStage2SelectionService)

    def unbound(self, bound):
        return ProjectStage2SelectionService(self.intake, {})

    def test_select_without_registration_is_refused_without_any_record(self):
        bound, body, _ = self.prepare_choice()
        unbound = self.unbound(bound)
        before = footprint(self.intake, self.ref)
        for key in (body["key"], "another-key"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(
                    SessionApiError, "stage2-selection-unconnected"
                ):
                    unbound.select("own", self.ref, {**body, "key": key})
                self.assertEqual(footprint(self.intake, self.ref), before)
        # Registering afterwards works with the very same request key.
        result = bound.select("own", self.ref, body)
        self.assertEqual(result["selection_status"], "recorded")
        self.assertFalse(result["execution_authorized"])

    def test_validation_is_not_relaxed_for_bound_but_wrong_requests(self):
        bound, body, _ = self.prepare_choice()
        before = footprint(self.intake, self.ref)
        for field, value, message in (
            ("delivery_manifest_sha256", "0" * 64, "stage2-selection-view-stale"),
            ("workflow_head_sha256", "0" * 64, "stage2-selection-view-stale"),
            ("snapshot_sha256", "0" * 64, "stage2-selection-view-stale"),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(SessionApiError, message):
                    bound.select("own", self.ref, {**body, field: value})
                self.assertEqual(footprint(self.intake, self.ref), before)
        with self.assertRaisesRegex(SessionApiError, "intake-source-version-differs"):
            bound.select("own", self.ref, {**body, "input_version": 2})
        self.assertEqual(footprint(self.intake, self.ref), before)

    def legacy_unconnected_record(self, body, *, error, phase):
        """Insert what the pre-fix code left behind (shape copied from a real run)."""
        project = self.intake.read("own", self.ref)
        semantic = {k: v for k, v in body.items() if k != "revision"}
        from research_workspace_native.project_intake import canonical, sha

        request_hash = sha(canonical({"kind": "stage2-select", "body": semantic}))
        receipt = {
            "error": error,
            "failure_phase": phase,
            "key": body["key"],
            "kind": "stage2-select",
            "project_ref": self.ref,
            "recorded_at": "2026-11-27T06:04:54.695612+00:00",
            "request": deepcopy(semantic),
            "request_sha256": request_hash,
            "status": "execution-unknown",
        }
        principal = self.intake._principal("own")
        self.intake.db.execute("BEGIN IMMEDIATE")
        self.intake.db.execute(
            "INSERT INTO intake_actions VALUES(?,?,?,?,?)",
            (
                principal,
                self.ref,
                body["key"],
                request_hash,
                canonical(receipt).decode(),
            ),
        )
        state = self.intake._load(principal, self.ref)
        state["revision"] += 1
        self.intake._save(state, "stage2-select-failed", receipt)
        self.intake.db.commit()
        self.assertEqual(project["revision"] + 1, state["revision"])
        return receipt

    def test_old_unconnected_record_no_longer_blocks_a_new_key(self):
        bound, body, _ = self.prepare_choice()
        stuck = {**body, "key": "stuck-key", "revision": body["revision"]}
        self.legacy_unconnected_record(
            stuck,
            error="stage2-selection-unconnected",
            phase="core-write-outcome-unobserved",
        )
        fresh = {**body, "key": "fresh-key", "revision": body["revision"] + 1}
        result = bound.select("own", self.ref, fresh)
        self.assertEqual(result["selection_status"], "recorded")
        # The original key is still refused: only a new key is the supported path.
        with self.assertRaises(SessionApiError):
            bound.select("own", self.ref, stuck)

    def test_other_unknown_records_still_block(self):
        bound, body, _ = self.prepare_choice()
        stuck = {**body, "key": "stuck-key"}
        self.legacy_unconnected_record(
            stuck,
            error="session-deadline-exceeded",
            phase="core-write-outcome-unobserved",
        )
        fresh = {**body, "key": "fresh-key", "revision": body["revision"] + 1}
        with self.assertRaisesRegex(SessionApiError, "stage2-selection-unresolved"):
            bound.select("own", self.ref, fresh)


if __name__ == "__main__":
    unittest.main()

"""Real intake durability, synthetic scheduling producers/progress; no live I/O.

The parent production adapter still must bind actual project_progress, permits,
native receipts and complete Stage1 services. This fixture does not attest them.
"""

from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1_continuation import (
    ContinuationAction,
    ContinuationBinding,
    ContinuationSnapshot,
    DurableAction,
    continue_stage1,
)
from research_workspace_native.project_stage1_progress import PHASES
from stage1_deliverable.common import sha
from stage1_ledger.journal import canonical


class ProjectStage1ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="stage1-continuation-")
        self.intake = ProjectIntakeService(
            Path(self.tmp.name),
            authenticate=lambda token: (
                "synthetic-owner" if token == "fixture" else None
            ),
        )
        created = self.intake.create(
            "fixture",
            {"key": "fixture-create", "topic": "Synthetic scheduling contract"},
        )
        self.ref = created["project_ref"]
        view = self.intake.read("fixture", self.ref)
        self.binding = ContinuationBinding(
            view["project_id"],
            self.ref,
            view["input_version"],
            view["brief_sha256"],
            "a" * 64,
            sha(canonical({"fixture": "synthetic-confirmed-settings"})),
        )
        self.now, self.writes, self.reservations, self.reads = 10.0, [], [], 0

    def tearDown(self):
        self.intake.close()
        self.tmp.cleanup()

    def state(self):
        with self.intake._lock:
            return self.intake._load("synthetic-owner", self.ref)

    def snapshot(self, *, frontier=None, actions=None, barrier=None, binding=None):
        self.reads += 1
        state = self.state()
        binding = binding or self.binding
        step = state.get("synthetic_steps", 0)
        phase = (
            "planning"
            if binding.plan_manifest_sha256 is None
            else "query"
            if step == 0
            else "screening"
        )
        progress = {
            "kind": "ProjectStage1Progress",
            "schema_version": "1.0.0",
            "binding": {
                "project_ref": binding.project_ref,
                "revision": state["revision"],
                "input_version": binding.input_version,
                "brief_sha256": binding.brief_sha256,
            },
            "phases": [
                {
                    "phase_id": phase,
                    "status": "available",
                    "reason": "synthetic-fixture",
                }
                for phase in PHASES
            ],
            "next_action": {
                "phase_id": phase,
                "target": phase,
                "reason": "synthetic-fixture",
            },
            "research_complete": False,
        }
        if actions is None:
            actions = tuple(
                DurableAction(
                    row["key"],
                    row["project_ref"],
                    row["status"],
                    row["request_sha256"],
                    sha(canonical(row)),
                )
                for row in self.intake.history("fixture", self.ref)["actions"]
            )
        return ContinuationSnapshot(
            binding,
            frontier or sha(canonical(state)),
            progress,
            actions,
            barrier or ("core-review" if step >= 2 else None),
        )

    def next_action(self, snapshot):
        step = self.state().get("synthetic_steps", 0)
        kind = ("query", "screen")[min(step, 1)]
        return ContinuationAction(
            kind, "synthetic-" + kind, snapshot.binding, snapshot.frontier_sha256
        )

    def handler(self, action, key, deadline):
        view = self.intake.read("fixture", self.ref)
        body = {
            "key": key,
            "revision": view["revision"],
            "input_version": action.binding.input_version,
            "brief_sha256": action.binding.brief_sha256,
            "continuation_binding": asdict(action.binding),
            "action_identity": action.identity,
        }

        def reserve(state, request_hash, principal):
            self.reservations.append((key, deadline, request_hash, principal))

        def work(state, request_hash, principal):
            self.writes.append((key, action.kind))
            state["synthetic_steps"] = state.get("synthetic_steps", 0) + 1
            return {"synthetic": True, "sequence": state["synthetic_steps"]}

        def check():
            if self.now >= deadline:
                raise TimeoutError("synthetic deadline exhausted")

        return self.intake._perform(
            "synthetic-owner",
            self.ref,
            "synthetic-stage1-" + action.kind,
            body,
            work,
            check_deadline=check,
            reserve=reserve,
        )

    def run_slice(self, **changes):
        options = dict(
            run_id="synthetic-run",
            binding=self.binding,
            snapshot=self.snapshot,
            next_action=self.next_action,
            handlers={"query": self.handler, "screen": self.handler},
            deadline=100.0,
            max_actions=4,
            monotonic=lambda: self.now,
        )
        options.update(changes)
        return continue_stage1(**options)

    def test_two_actual_durable_operations_and_reentry_do_not_repeat(self):
        result = self.run_slice()
        self.assertEqual(
            (result["status"], result["reason"], result["action_count"]),
            ("barrier", "core-review", 2),
        )
        self.assertEqual(
            [row["status"] for row in result["actions"]], ["saved", "saved"]
        )
        self.assertEqual([kind for _, kind in self.writes], ["query", "screen"])
        self.assertEqual(len(self.reservations), 2)
        self.assertTrue(all(row[1] == 100.0 for row in self.reservations))
        again = self.run_slice()
        self.assertEqual(
            (again["status"], again["action_count"], len(self.writes)),
            ("barrier", 0, 2),
        )
        action = ContinuationAction("query", "synthetic-query", self.binding, "b" * 64)
        replay = self.handler(action, result["actions"][0]["key"], 100.0)
        self.assertTrue(replay["replayed"])
        self.assertEqual((len(self.writes), len(self.reservations)), (2, 2))
        self.assertEqual(
            (
                result["stage1_complete"],
                result["scientific_acceptance"],
                result["stage2_started"],
            ),
            (False, False, False),
        )
        self.assertIsNone(result["tokens"])
        self.assertIsNone(result["monetary_cost"])

    def test_actual_unknown_receipt_stops_reentry_without_new_key(self):
        def unknown(action, key, deadline):
            view = self.intake.read("fixture", self.ref)
            body = {
                "key": key,
                "revision": view["revision"],
                "input_version": view["input_version"],
                "brief_sha256": view["brief_sha256"],
            }

            def work(state, request_hash, principal):
                self.writes.append((key, "unknown"))
                raise RuntimeError("synthetic Core append outcome unobserved")

            self.intake._perform(
                "synthetic-owner", self.ref, "stage1-coverage", body, work
            )

        first = self.run_slice(handlers={"query": unknown})
        second = self.run_slice(handlers={"query": unknown})
        self.assertEqual(first["actions"][0]["status"], "execution-unknown")
        self.assertEqual(
            (
                second["status"],
                second["reason"],
                second["action_count"],
                len(self.writes),
            ),
            ("held", "durable-action-execution-unknown", 0, 1),
        )

    def test_stale_complete_binding_and_action_never_dispatch(self):
        for change in (
            {"project_id": "other-project"},
            {"input_version": 2},
            {"brief_sha256": "c" * 64},
            {"plan_manifest_sha256": "c" * 64},
            {"settings_sha256": "c" * 64},
        ):
            with self.subTest(change=change):
                changed = replace(self.binding, **change)
                result = self.run_slice(snapshot=lambda: self.snapshot(binding=changed))
                self.assertEqual(
                    (result["reason"], result["action_count"]), ("binding-changed", 0)
                )
        result = self.run_slice(
            next_action=lambda s: ContinuationAction(
                "query", "stale", s.binding, "f" * 64
            )
        )
        self.assertEqual(result["reason"], "stale-action")
        self.assertEqual(self.writes, [])

    def test_exact_input_version_types_and_dictionary_context_are_rejected(self):
        for version in ("1", True, 1.0):
            with (
                self.subTest(version=version),
                self.assertRaisesRegex(ValueError, "typed-input-version"),
            ):
                replace(self.binding, input_version=version)
        raw = self.snapshot()
        progress = deepcopy(raw.progress)
        progress["binding"]["input_version"] = "1"
        with self.assertRaisesRegex(ValueError, "progress-version-invalid"):
            replace(raw, progress=progress)
        with self.assertRaisesRegex(ValueError, "typed-snapshot-required"):
            self.run_slice(snapshot=lambda: asdict(raw))
        self.assertEqual(self.writes, [])

    def test_missing_handler_and_absent_next_action_are_partial_holds(self):
        result = self.run_slice(handlers={})
        self.assertEqual(
            (result["reason"], result["action_count"]), ("handler-unconnected", 0)
        )
        result = self.run_slice(next_action=lambda s: None)
        self.assertEqual(
            (result["status"], result["reason"]), ("partial", "no-next-action")
        )

    def test_administrative_limit_does_not_create_or_reset_resource_budget(self):
        result = self.run_slice(max_actions=1)
        self.assertEqual(
            (result["reason"], result["action_count"]),
            ("administrative-limit-exhausted", 1),
        )
        self.assertEqual((len(self.writes), len(self.reservations)), (1, 1))

    def test_deadline_exhaustion_before_dispatch_and_invalid_limits(self):
        def next_expired(snapshot):
            self.now = 100.0
            return self.next_action(snapshot)

        result = self.run_slice(next_action=next_expired)
        self.assertEqual(
            (result["reason"], result["action_count"]), ("deadline-exhausted", 0)
        )
        for value in (0, -1, True, 1.0, 513):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.run_slice(max_actions=value)
        for value in (float("inf"), float("nan"), True, 9.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.run_slice(deadline=value)
        self.assertEqual(self.writes, [])

    def test_handler_dictionary_is_not_durable_completion_evidence(self):
        result = self.run_slice(
            handlers={"query": lambda *args: {"status": "saved", "verified": True}}
        )
        self.assertEqual(
            (result["reason"], result["action_count"]), ("durable-receipt-missing", 1)
        )
        self.assertEqual(self.writes, [])

    def test_saved_receipt_without_new_frontier_stops(self):
        result = self.run_slice(snapshot=lambda: self.snapshot(frontier="b" * 64))
        self.assertEqual(
            (result["reason"], result["action_count"], len(self.writes)),
            ("no-frontier-progress", 1, 1),
        )

    def test_same_action_identity_keeps_key_across_changed_frontier(self):
        def still_query():
            current = self.snapshot()
            progress = deepcopy(current.progress)
            progress["next_action"].update(phase_id="query", target="query")
            return replace(current, progress=progress)

        def repeated(snapshot):
            return ContinuationAction(
                "query", "synthetic-query", self.binding, snapshot.frontier_sha256
            )

        first = self.run_slice(snapshot=still_query, next_action=repeated)
        again = self.run_slice(snapshot=still_query, next_action=repeated)
        self.assertEqual(
            (first["reason"], first["action_count"]), ("repeated-action", 1)
        )
        self.assertEqual(
            (again["reason"], again["action_count"], len(self.writes)),
            ("repeated-action", 0, 1),
        )

    def test_pending_existing_owner_is_joined_once_then_reread(self):
        pending = DurableAction(
            "existing-owner", self.ref, "dispatched", "c" * 64, "d" * 64
        )
        joins = []
        result = self.run_slice(
            snapshot=lambda: self.snapshot(actions=(pending,)),
            wait=lambda a, d: joins.append((a.key, d)),
        )
        self.assertEqual(
            (result["status"], result["reason"], result["action_count"]),
            ("waiting", "existing-action-pending", 0),
        )
        self.assertEqual(joins, [("existing-owner", 100.0)])
        self.assertEqual(self.reads, 2)

    def test_each_successive_owned_action_is_joined_once(self):
        joined = []

        def pending_snapshot():
            current = self.snapshot()
            actions = tuple(
                replace(action, status="running", outcome=None)
                if action.key.startswith("stage1-auto-") and action.key not in joined
                else action
                for action in current.actions
            )
            return replace(current, actions=actions)

        result = self.run_slice(
            snapshot=pending_snapshot,
            wait=lambda action, deadline: joined.append(action.key),
        )
        self.assertEqual(
            (result["status"], result["reason"], result["action_count"]),
            ("barrier", "core-review", 2),
        )
        self.assertEqual(joined, [action["key"] for action in result["actions"]])
        self.assertEqual(len(set(joined)), 2)

    def test_deadline_is_checked_after_join(self):
        pending = DurableAction(
            "existing-owner", self.ref, "running", "c" * 64, "d" * 64
        )

        def wait(action, deadline):
            self.now = deadline

        result = self.run_slice(
            snapshot=lambda: self.snapshot(actions=(pending,)), wait=wait
        )
        self.assertEqual(
            (result["reason"], result["action_count"]), ("deadline-exhausted", 0)
        )

    def test_authoritative_held_progress_and_core_barrier_dispatch_nothing(self):
        current = self.snapshot()
        held = deepcopy(current.progress)
        held["phases"][2].update(status="held", reason="uncertain-action")
        result = self.run_slice(snapshot=lambda: replace(current, progress=held))
        self.assertEqual(
            (result["status"], result["reason"]), ("held", "uncertain-action")
        )
        for barrier in ("saved-delivery", "core-review", "wiki-review"):
            with self.subTest(barrier=barrier):
                result = self.run_slice(
                    snapshot=lambda: replace(current, barrier=barrier)
                )
                self.assertEqual(
                    (result["status"], result["reason"], result["action_count"]),
                    ("barrier", barrier, 0),
                )

    def test_current_phase_unknown_or_unconnected_never_selects_or_dispatches(self):
        current = self.snapshot()
        selections = []
        for status in ("unknown", "unconnected"):
            with self.subTest(status=status):
                progress = deepcopy(current.progress)
                progress["phases"][2].update(status=status)
                result = self.run_slice(
                    snapshot=lambda: replace(current, progress=progress),
                    next_action=lambda snapshot: selections.append(snapshot),
                )
                self.assertEqual(
                    (result["status"], result["reason"], result["action_count"]),
                    ("held", "phase-" + status, 0),
                )
        self.assertEqual((selections, self.writes, self.reservations), ([], [], []))

    def test_action_kind_must_match_current_progress_phase(self):
        result = self.run_slice(
            next_action=lambda snapshot: ContinuationAction(
                "screen",
                "synthetic-screen-too-early",
                snapshot.binding,
                snapshot.frontier_sha256,
            ),
        )
        self.assertEqual(
            (result["status"], result["reason"], result["action_count"]),
            ("held", "phase-action-differs", 0),
        )
        self.assertEqual((self.writes, self.reservations), ([], []))

    def test_forbidden_actions_and_completed_failure_cannot_unlock(self):
        for kind in ("stage2", "approve-core", "accept-html"):
            with (
                self.subTest(kind=kind),
                self.assertRaisesRegex(ValueError, "stage1-action"),
            ):
                ContinuationAction(kind, "forbidden", self.binding, "b" * 64)
        with self.assertRaisesRegex(ValueError, "completed-success-evidence"):
            DurableAction(
                "failed", self.ref, "completed", "c" * 64, "d" * 64, outcome="failed"
            )

    def test_changed_plan_requires_explicit_reentry(self):
        self.binding = replace(self.binding, plan_manifest_sha256=None)

        def planned(action, key, deadline):
            self.handler(action, key, deadline)
            self.binding = replace(self.binding, plan_manifest_sha256="e" * 64)

        result = self.run_slice(
            next_action=lambda s: ContinuationAction(
                "planning", "synthetic-plan", s.binding, s.frontier_sha256
            ),
            handlers={"planning": planned},
        )
        self.assertEqual(
            (result["status"], result["reason"], result["action_count"]),
            ("held", "plan-confirmation-required", 1),
        )


if __name__ == "__main__":
    unittest.main()

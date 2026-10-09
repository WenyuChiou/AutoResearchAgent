"""Synthetic input, real Harness validators/producers, and private SQLite.

No source acquisition, model call, scoring, native process, or science admission.
"""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from research_workspace_native import harness_ops as ops
from research_workspace_native.store import JournalError
from stage1_deliverable.common import DeliverableError, canonical, sha
from test_research_workspace_view import fixture_index
from test_research_workspace_literature_selection import attached_index


class HarnessOpsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="harness-ops-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.index = fixture_index()
        self.raw = canonical(self.index) + b"\n"
        self.registrations = {
            ref: dict(
                index_raw=self.raw,
                index_sha256=sha(self.raw),
                output_root=self.root / ref,
                principals=[principal],
            )
            for ref, principal in (("alpha", "a"), ("beta", "b"))
        }
        self.service = self.make()
        self.addCleanup(self.service.close)

    def make(self, registrations=None):
        return ops.HarnessOps(
            self.root / "ops.sqlite3",
            registrations=registrations or self.registrations,
            authenticate=lambda token: {"token-a": "a", "token-b": "b"}.get(token),
        )

    def request(
        self, action="validate-index", key="first", ref="alpha", token="token-a"
    ):
        view = self.service.view(token, ref)
        return dict(
            action=action,
            key=key,
            index_sha256=view["index_sha256"],
            expected_revision=view["revision"],
        )

    def run_action(self, request, token="token-a", ref="alpha", deadline=None):
        return self.service.execute(
            token, ref, request, deadline=deadline or time.monotonic() + 10
        )

    def test_real_functions_and_raw_vs_canonical_binding_keep_unknowns(self):
        before = canonical(self.index)
        result = self.run_action(self.request("derive-literature-selection"))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            result["result"]["counts"],
            dict(screened=2, pending=2, included=0, excluded=0),
        )
        self.assertEqual(result["index_sha256"], sha(self.raw))
        self.assertEqual(result["input_canonical_sha256"], sha(before))
        self.assertNotEqual(result["index_sha256"], result["input_canonical_sha256"])
        item = next(
            f for f in result["artifacts"] if f["name"] == "literature/selection.json"
        )
        selection = json.loads(
            self.service.artifact(
                "token-a", "alpha", "first", item["name"], item["sha256"]
            )
        )
        self.assertFalse(selection["research_execution"])
        self.assertFalse(selection["official_stage2_import_eligible"])
        self.assertEqual(selection["rows"][0]["reasons"], ["pending-source-review"])
        self.assertEqual(canonical(self.index), before)
        self.assertEqual(
            self.service.view("token-a", "alpha")["project_id"],
            self.index["project_id"],
        )

    def test_v3_actual_selection_excludes_broken_source_without_rewriting_claim(self):
        temporary, index = attached_index()
        self.addCleanup(temporary.cleanup)
        self.service.close()
        raw = canonical(index)
        registration = deepcopy(self.registrations["alpha"])
        registration.update(
            index_raw=raw, index_sha256=sha(raw), output_root=self.root / "v3-output"
        )
        self.service = ops.HarnessOps(
            self.root / "v3.sqlite3",
            registrations={"alpha": registration},
            authenticate=lambda _: "a",
        )
        self.addCleanup(self.service.close)
        result = self.run_action(self.request("derive-literature-selection"))
        self.assertEqual(
            result["result"]["counts"],
            dict(screened=2, included=1, excluded=1, pending=0),
        )
        self.assertEqual(index["claims"][0]["support"], "Unknown")
        self.assertEqual(canonical(index), raw)

    def test_validation_called_after_running_intent_and_exact_key_replayed(self):
        request = self.request()
        original = ops.validate_index
        observed = []

        def validate(index):
            observed.append(
                self.service.get_action("token-a", "alpha", request["key"])["status"]
            )
            return original(index)

        with patch.object(ops, "validate_index", side_effect=validate) as call:
            first = self.run_action(request)
            replay = self.run_action(request)
            self.assertEqual(call.call_count, 1)
        self.assertEqual(observed, ["running"])
        self.assertEqual(first, replay)
        self.assertEqual(self.service.get_action("token-a", "alpha", "first"), first)
        self.assertEqual(len(list((self.root / "alpha").iterdir())), 1)
        self.assertNotIn(str(self.root), json.dumps(first))

    def test_multi_project_same_key_and_payload_change_isolated(self):
        first = self.run_action(self.request())
        second = self.run_action(
            self.request(ref="beta", token="token-b"), "token-b", "beta"
        )
        self.assertNotEqual(first["output_ref"], second["output_ref"])
        self.assertEqual(self.service.view("token-a", "alpha")["history_count"], 1)
        self.assertEqual(self.service.view("token-b", "beta")["history_count"], 1)
        changed = deepcopy(first["request"])
        changed["action"] = "export-selection"
        with self.assertRaisesRegex(ops.HarnessOpsError, "idempotency-payload-differs"):
            self.run_action(changed)
        for token, ref in (("token-a", "beta"), ("bad-token", "alpha")):
            with self.assertRaisesRegex(ops.HarnessOpsError, "project-denied"):
                self.service.view(token, ref)

    def test_two_tabs_same_key_execute_real_validator_once(self):
        request = self.request()
        receipts, errors = [], []
        original = ops.validate_index
        entered, release = threading.Event(), threading.Event()

        def validate(index):
            entered.set()
            self.assertTrue(release.wait(2))
            return original(index)

        def worker():
            try:
                receipts.append(self.run_action(request))
            except Exception as error:
                errors.append(error)

        with patch.object(ops, "validate_index", side_effect=validate) as call:
            first, second = (
                threading.Thread(target=worker),
                threading.Thread(target=worker),
            )
            first.start()
            self.assertTrue(entered.wait(1))
            second.start()
            release.set()
            first.join(3)
            second.join(3)
            self.assertFalse(first.is_alive() or second.is_alive())
            self.assertEqual(call.call_count, 1)
        self.assertEqual(errors, [])
        self.assertEqual(len(receipts), 2)
        self.assertEqual(receipts[0], receipts[1])

    def test_stale_revision_index_and_caller_paths_rejected_without_output(self):
        request = self.request()
        for changed in (
            dict(request, expected_revision=True),
            dict(request, path="C:/anything"),
            dict(request, model="paid"),
            dict(request, permit=True),
        ):
            with self.assertRaisesRegex(ops.HarnessOpsError, "invalid-action-request"):
                self.run_action(changed)
        with self.assertRaisesRegex(ops.HarnessOpsError, "stale-index-binding"):
            self.run_action(dict(request, index_sha256="0" * 64))
        self.run_action(request)
        with self.assertRaisesRegex(ops.HarnessOpsError, "stale-revision"):
            self.run_action(dict(request, key="new-key"))
        self.assertEqual(len(list((self.root / "alpha").iterdir())), 1)

    def test_failure_preserved_and_not_retried_across_sqlite_reopen(self):
        request = self.request("derive-literature-selection")
        with patch.object(
            ops,
            "derive_literature_selection",
            side_effect=DeliverableError("private source failed"),
        ) as call:
            failed = self.run_action(request)
            self.assertEqual(self.run_action(request), failed)
            self.assertEqual(call.call_count, 1)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"]["type"], "DeliverableError")
        self.assertNotIn("private source", json.dumps(failed))
        self.service.close()
        self.service = self.make()
        self.addCleanup(self.service.close)
        with patch.object(
            ops,
            "derive_literature_selection",
            side_effect=AssertionError("must not retry"),
        ):
            self.assertEqual(self.run_action(request), failed)

    def test_process_loss_running_becomes_unknown_and_never_reruns(self):
        request = self.request("derive-literature-selection")
        with patch.object(
            ops,
            "derive_literature_selection",
            side_effect=KeyboardInterrupt("synthetic crash"),
        ):
            with self.assertRaises(KeyboardInterrupt):
                self.run_action(request)
        self.assertEqual(
            self.service.get_action("token-a", "alpha", "first")["status"], "running"
        )
        self.service.close()
        self.service = self.make()
        self.addCleanup(self.service.close)
        with patch.object(
            ops,
            "derive_literature_selection",
            side_effect=AssertionError("must not run"),
        ):
            unknown = self.run_action(request)
        self.assertEqual(unknown["status"], "execution-unknown")
        self.assertEqual(unknown["artifacts"], [])
        self.assertEqual(list((self.root / "alpha").iterdir()), [])

    def test_restart_completed_exact_key_get_has_no_producer_and_binding_stable(self):
        request = self.request()
        result = self.run_action(request)
        bindings = self.service.bindings()
        self.assertEqual(
            bindings["alpha"],
            dict(project_id=self.index["project_id"], index_sha256=sha(self.raw)),
        )
        self.service.close()
        self.service = self.make()
        self.addCleanup(self.service.close)
        with patch.object(
            ops,
            "validate_index",
            side_effect=AssertionError("read/replay cannot execute"),
        ):
            self.assertEqual(
                self.service.get_action("token-a", "alpha", "first"), result
            )
            self.assertEqual(self.run_action(request), result)
            self.assertEqual(self.service.bindings(), bindings)

    def test_registration_raw_hash_and_duplicate_json_keys_fail_closed(self):
        self.service.close()
        registration = deepcopy(self.registrations)
        registration["alpha"]["index_raw"] += b" "
        with self.assertRaisesRegex(ops.HarnessOpsError, "index-binding-differs"):
            self.make(registration)
        raw = b'{"schema_version":"1.0.0","schema_version":"1.0.0"}'
        registration["alpha"].update(index_raw=raw, index_sha256=sha(raw))
        with self.assertRaisesRegex(DeliverableError, "duplicate JSON key"):
            self.make(registration)

    def test_export_fixed_inventory_hashes_and_tamper_rejected(self):
        request = self.request("export-selection")
        result = self.run_action(request)
        self.assertEqual(
            {f["name"] for f in result["artifacts"]},
            ops.EXPORT_FILES | {"operation.json"},
        )
        for item in result["artifacts"]:
            raw = self.service.artifact(
                "token-a", "alpha", "first", item["name"], item["sha256"]
            )
            self.assertEqual(sha(raw), item["sha256"])
        target = next(
            f for f in result["artifacts"] if f["name"] == "literature/screening.bib"
        )
        path = self.root / "alpha" / result["output_ref"] / target["name"]
        path.write_bytes(b"x" * target["size"])
        with self.assertRaisesRegex(ops.HarnessOpsError, "artifact-bytes-differ"):
            self.service.artifact(
                "token-a", "alpha", "first", target["name"], target["sha256"]
            )
        for name in ("../operation.json", "C:/file", [], "unregistered.json"):
            with self.assertRaisesRegex(
                ops.HarnessOpsError, "invalid-artifact-request"
            ):
                self.service.artifact(
                    "token-a", "alpha", "first", name, target["sha256"]
                )

    def test_queued_deadline_expires_before_producer_or_intent(self):
        request = self.request()
        errors, checked = [], threading.Event()
        clock = [100.0]
        original = self.service._deadline

        def check(deadline):
            original(deadline)
            checked.set()  # First check succeeded, before waiting for the lock.

        def worker():
            try:
                self.run_action(request, deadline=110.0)
            except ops.HarnessOpsError as error:
                errors.append(error.code)

        with (
            patch.object(ops, "time", SimpleNamespace(monotonic=lambda: clock[0])),
            patch.object(self.service, "_deadline", side_effect=check),
            patch.object(ops, "validate_index") as producer,
        ):
            with self.service._lock:
                thread = threading.Thread(target=worker)
                thread.start()
                self.assertTrue(checked.wait(2))
                clock[0] = 111.0
            thread.join(2)
            producer.assert_not_called()
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, ["request-deadline-exceeded"])
        self.assertEqual(self.service.view("token-a", "alpha")["history_count"], 0)

    def test_inflight_deadline_failure_and_single_owner_binding(self):
        request = self.request()
        original = ops.validate_index
        clock = [100.0]

        def delayed(index):
            self.assertEqual(
                self.service.get_action("token-a", "alpha", "first")["status"],
                "running",
            )
            clock[0] = 111.0  # Expire only after durable intent and producer entry.
            return original(index)

        with (
            patch.object(ops, "time", SimpleNamespace(monotonic=lambda: clock[0])),
            patch.object(ops, "validate_index", side_effect=delayed) as producer,
        ):
            failed = self.run_action(request, deadline=110.0)
            producer.assert_called_once()
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"]["code"], "request-deadline-exceeded")
        self.assertEqual(failed["artifacts"], [])
        with self.assertRaisesRegex(JournalError, "execution owner"):
            self.make()
        self.service.close()
        changed = deepcopy(self.registrations)
        changed["alpha"]["output_root"] = self.root / "changed-root"
        with self.assertRaisesRegex(ops.HarnessOpsError, "saved-binding-differs"):
            self.make(changed)


if __name__ == "__main__":
    unittest.main()

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_fixture_helpers import write_stage2_fixture  # noqa: E402
from stage2_workflow import (  # noqa: E402
    add_snapshot,
    finish_action,
    initialize_workflow,
    inspect_workflow,
    start_action,
)


class Stage2WorkflowStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sources = self.root / "sources"
        self.packet = write_stage2_fixture(self.sources, candidate_count=2)
        self.packet_path = self.root / "packet.json"
        self.packet_path.write_text(json.dumps(self.packet), encoding="utf-8")
        self.run = self.root / "run"
        self.settings = {"model": "test-model", "reasoning": "medium"}
        self.policy = {"path": "policy.json", "sha256": "a" * 64}

    def tearDown(self):
        self.temporary.cleanup()

    def initialize(self):
        initialize_workflow(
            self.packet_path, self.sources, self.run, self.settings, self.policy
        )
        return inspect_workflow(self.run)

    @staticmethod
    def impact(packet, status="unaffected"):
        return {
            candidate_id: {
                "status": status,
                "reason": "The new evidence is conservatively queued for recheck.",
            }
            for candidate_id in sorted(
                {row["candidate_id"] for row in packet["candidates"]}
            )
        }

    def write_packet(self, packet, name="next.json"):
        path = self.root / name
        path.write_text(json.dumps(packet), encoding="utf-8")
        return path

    @staticmethod
    def rewrite_json(path, value):
        path.write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    @staticmethod
    def rehash(value, hash_field):
        value[hash_field] = canonical_hash(
            {key: item for key, item in value.items() if key != hash_field}
        )

    def test_initializes_idempotently_and_detects_source_or_head_change(self):
        state = self.initialize()
        initial_head = state["head_sha256"]
        second = initialize_workflow(
            self.packet_path, self.sources, self.run, self.settings, self.policy
        )
        self.assertEqual(second, state["manifest"])
        with self.assertRaisesRegex(Stage2Error, "head-receipt-mismatch"):
            inspect_workflow(self.run, expected_head="f" * 64)
        stored = (
            self.run / "snapshots" / "000001" / "checker" / "sources" / "source-1.txt"
        )
        stored.write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "source.*hash"):
            inspect_workflow(self.run, expected_head=initial_head)

    def test_preexisting_directory_and_concurrent_writer_fail_closed(self):
        unrelated = self.root / "unrelated"
        unrelated.mkdir()
        marker = unrelated / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "workflow-read-failed"):
            initialize_workflow(
                self.packet_path,
                self.sources,
                unrelated,
                self.settings,
                self.policy,
            )
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

        state = self.initialize()
        (self.run / ".workflow-write.lock").mkdir()
        with self.assertRaisesRegex(Stage2Error, "write-lock-conflict"):
            start_action(self.run, "locked", "search", {}, {}, state["head_sha256"])

    def test_manifest_rehash_cannot_change_settings_under_same_event_receipt(self):
        state = self.initialize()
        manifest_path = self.run / "workflow_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["settings"]["model"] = "substituted-model"
        manifest["settings_sha256"] = canonical_hash(manifest["settings"])
        self.rehash(manifest, "manifest_sha256")
        self.rewrite_json(manifest_path, manifest)
        with self.assertRaisesRegex(Stage2Error, "event-chain-invalid"):
            inspect_workflow(self.run, expected_head=state["head_sha256"])

    def test_strict_json_and_orphan_snapshot_directory_fail_closed(self):
        self.initialize()
        event_path = self.run / "events" / "000001.json"
        raw = event_path.read_text(encoding="utf-8")
        event_path.write_text(
            raw[:-1] + ',"event_type":"snapshot_added"}', encoding="utf-8"
        )
        with self.assertRaisesRegex(Stage2Error, "duplicate-json-key"):
            inspect_workflow(self.run)

        event_path.write_text(raw, encoding="utf-8")
        (self.run / "snapshots" / "000002").mkdir()
        with self.assertRaisesRegex(Stage2Error, "directory-inventory-mismatch"):
            inspect_workflow(self.run)

    def test_rehashed_action_rejects_changed_inputs_and_wrong_snapshot(self):
        state = self.initialize()
        started = start_action(
            self.run,
            "binding-1",
            "review",
            {"candidate_id": "candidate-1"},
            {"model": "declared-only"},
            state["head_sha256"],
        )
        request_path = self.run / "actions" / "binding-1" / "request.json"
        event_path = self.run / "events" / "000002.json"
        original_request = json.loads(request_path.read_text(encoding="utf-8"))
        original_event = json.loads(event_path.read_text(encoding="utf-8"))
        self.assertEqual(
            original_request["runtime"]["declared_action_settings_sha256"],
            original_request["settings_sha256"],
        )
        self.assertFalse(original_request["runtime"]["attests_model_bytes"])

        request = copy.deepcopy(original_request)
        request["inputs"]["candidate_id"] = "candidate-2"
        self.rehash(request, "request_sha256")
        event = copy.deepcopy(original_event)
        event["payload"]["request"] = request
        self.rehash(event, "event_sha256")
        self.rewrite_json(request_path, request)
        self.rewrite_json(event_path, event)
        with self.assertRaisesRegex(Stage2Error, "snapshot-input-binding-invalid"):
            inspect_workflow(self.run)

        request = copy.deepcopy(original_request)
        request["settings"]["model"] = "changed-declaration"
        self.rehash(request, "request_sha256")
        event = copy.deepcopy(original_event)
        event["payload"]["request"] = request
        self.rehash(event, "event_sha256")
        self.rewrite_json(request_path, request)
        self.rewrite_json(event_path, event)
        with self.assertRaisesRegex(Stage2Error, "snapshot-input-binding-invalid"):
            inspect_workflow(self.run)

        request = copy.deepcopy(original_request)
        request["snapshot_sequence"] = 999
        self.rehash(request, "request_sha256")
        event = copy.deepcopy(original_event)
        event["payload"]["request"] = request
        self.rehash(event, "event_sha256")
        self.rewrite_json(request_path, request)
        self.rewrite_json(event_path, event)
        with self.assertRaisesRegex(Stage2Error, "snapshot-input-binding-invalid"):
            inspect_workflow(self.run)
        self.assertNotEqual(started["event"]["event_sha256"], event["event_sha256"])

    def test_rehashed_unknown_event_and_finish_before_start_are_rejected(self):
        state = self.initialize()
        started = start_action(
            self.run, "ordered-1", "review", {}, {}, state["head_sha256"]
        )
        finished = finish_action(
            self.run,
            "ordered-1",
            "empty",
            {},
            None,
            None,
            started["event"]["event_sha256"],
        )
        second_path = self.run / "events" / "000002.json"
        third_path = self.run / "events" / "000003.json"
        started_event = json.loads(second_path.read_text(encoding="utf-8"))
        finished_event = json.loads(third_path.read_text(encoding="utf-8"))

        unknown = copy.deepcopy(finished_event)
        unknown["event_type"] = "action_magic"
        self.rehash(unknown, "event_sha256")
        self.rewrite_json(third_path, unknown)
        with self.assertRaisesRegex(Stage2Error, "event-chain-invalid"):
            inspect_workflow(self.run)

        first = json.loads(
            (self.run / "events" / "000001.json").read_text(encoding="utf-8")
        )
        out_of_order_finish = copy.deepcopy(finished_event)
        out_of_order_finish["sequence"] = 2
        out_of_order_finish["previous_sha256"] = first["event_sha256"]
        self.rehash(out_of_order_finish, "event_sha256")
        out_of_order_start = copy.deepcopy(started_event)
        out_of_order_start["sequence"] = 3
        out_of_order_start["previous_sha256"] = out_of_order_finish["event_sha256"]
        self.rehash(out_of_order_start, "event_sha256")
        self.rewrite_json(second_path, out_of_order_finish)
        self.rewrite_json(third_path, out_of_order_start)
        with self.assertRaisesRegex(Stage2Error, "finish-before-start"):
            inspect_workflow(self.run)
        self.assertNotEqual(
            finished["event_sha256"], out_of_order_start["event_sha256"]
        )

    def test_snapshot_addition_preserves_history_and_marks_every_candidate_pending(
        self,
    ):
        state = self.initialize()
        packet = copy.deepcopy(self.packet)
        raw = b"Additional exact evidence for the bounded comparison.\n"
        (self.sources / "source-3.txt").write_bytes(raw)
        packet["sources"].append(
            {
                "source_id": "src-3",
                "work_id": "work-3",
                "version_id": "v1",
                "path": "source-3.txt",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "evidence_level": "full-text",
            }
        )
        packet["evidence"].append(
            {
                "evidence_id": "ev-3",
                "source_id": "src-3",
                "work_id": "work-3",
                "version_id": "v1",
                "locator": "line 1",
                "quote": "Additional exact evidence for the bounded comparison.",
            }
        )
        event = add_snapshot(
            self.run,
            self.write_packet(packet),
            self.sources,
            "New evidence was added.",
            self.impact(packet),
            state["head_sha256"],
        )
        updated = inspect_workflow(self.run, expected_head=event["event_sha256"])
        self.assertEqual(
            updated["pending_candidate_ids"], ["candidate-1", "candidate-2"]
        )
        self.assertEqual(len(updated["snapshots"]), 2)
        self.assertEqual(
            updated["latest_snapshot"]["event"]["payload"]["parent_snapshot_sha256"],
            state["latest_snapshot"]["event"]["payload"]["snapshot_sha256"],
        )

    def test_snapshot_rejects_rehash_rollback_brief_change_and_incomplete_impact(self):
        state = self.initialize()
        for name, mutate, pattern in (
            (
                "rehash",
                lambda packet: packet["sources"][0].update(sha256="f" * 64),
                "source hash mismatch",
            ),
            (
                "rollback",
                lambda packet: packet["candidates"].pop(),
                "history-rewritten",
            ),
            (
                "brief",
                lambda packet: packet["brief"].update(original_description="changed"),
                "brief-change",
            ),
        ):
            with self.subTest(name=name):
                packet = copy.deepcopy(self.packet)
                mutate(packet)
                with self.assertRaisesRegex(Stage2Error, pattern):
                    add_snapshot(
                        self.run,
                        self.write_packet(packet, f"{name}.json"),
                        self.sources,
                        "Attempt invalid change.",
                        self.impact(packet),
                        state["head_sha256"],
                    )
        with self.assertRaisesRegex(Stage2Error, "impact-candidate-set"):
            add_snapshot(
                self.run,
                self.packet_path,
                self.sources,
                "Incomplete impact.",
                {"candidate-1": self.impact(self.packet)["candidate-1"]},
                state["head_sha256"],
            )

    def test_action_complete_reuses_only_identical_verified_artifacts(self):
        state = self.initialize()
        started = start_action(
            self.run,
            "review-1",
            "independent-review",
            {"candidate_ids": ["candidate-1"]},
            {"model": "test-model"},
            state["head_sha256"],
        )
        artifact = self.root / "review.json"
        artifact.write_bytes(b'{"verdict":"ok"}\n')
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        finished = finish_action(
            self.run,
            "review-1",
            "complete",
            {"review.json": {"path": str(artifact), "sha256": digest}},
            None,
            None,
            started["event"]["event_sha256"],
        )
        reused = start_action(
            self.run,
            "review-1",
            "independent-review",
            {"candidate_ids": ["candidate-1"]},
            {"model": "test-model"},
            finished["event_sha256"],
        )
        self.assertTrue(reused["reuse"])
        self.assertEqual(reused["request"], started["request"])
        self.assertEqual(
            reused["request"]["request_sha256"],
            reused["result"]["request_sha256"],
        )
        with self.assertRaisesRegex(Stage2Error, "input-conflict"):
            start_action(
                self.run,
                "review-1",
                "independent-review",
                {"candidate_ids": ["candidate-2"]},
                {"model": "test-model"},
                finished["event_sha256"],
            )
        stored = self.run / reused["result"]["artifacts"]["review.json"]["stored_path"]
        stored.write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "artifact-hash-mismatch"):
            inspect_workflow(self.run)

    def test_invalid_artifact_can_be_corrected_or_closed_without_partial_write(self):
        state = self.initialize()
        started = start_action(
            self.run, "bad-artifact", "review", {}, {}, state["head_sha256"]
        )
        artifact = self.root / "output.txt"
        artifact.write_bytes(b"evidence")
        with self.assertRaisesRegex(Stage2Error, "input-hash-mismatch"):
            finish_action(
                self.run,
                "bad-artifact",
                "complete",
                {"output.txt": {"path": str(artifact), "sha256": "f" * 64}},
                None,
                None,
                started["event"]["event_sha256"],
            )
        self.assertFalse((self.run / "actions/bad-artifact/artifacts").exists())
        self.assertIsNone(
            inspect_workflow(self.run)["actions"]["bad-artifact"]["result"]
        )
        finish_action(
            self.run,
            "bad-artifact",
            "interrupted",
            {},
            None,
            "Caller abandoned invalid input.",
            started["event"]["event_sha256"],
        )
        self.assertEqual(
            inspect_workflow(self.run)["actions"]["bad-artifact"]["result"]["status"],
            "interrupted",
        )

    def test_publication_crash_preserves_partial_data_and_fails_closed(self):
        state = self.initialize()
        started = start_action(
            self.run, "crash", "search", {}, {}, state["head_sha256"]
        )
        with patch("stage2_workflow.store._append_event", side_effect=OSError("crash")):
            with self.assertRaisesRegex(OSError, "crash"):
                finish_action(
                    self.run,
                    "crash",
                    "empty",
                    {},
                    None,
                    None,
                    started["event"]["event_sha256"],
                )
        self.assertTrue((self.run / "actions/crash/result.json").exists())
        with self.assertRaisesRegex(Stage2Error, "incomplete-finalization"):
            inspect_workflow(self.run)
        with self.assertRaisesRegex(Stage2Error, "incomplete-finalization"):
            start_action(
                self.run, "crash", "search", {}, {}, started["event"]["event_sha256"]
            )

    def test_started_failed_empty_and_path_escape_do_not_authorize_replay(self):
        state = self.initialize()
        started = start_action(
            self.run, "attempt-1", "generation", {}, {}, state["head_sha256"]
        )
        with self.assertRaisesRegex(Stage2Error, "replay-not-authorized"):
            start_action(
                self.run,
                "attempt-1",
                "generation",
                {},
                {},
                started["event"]["event_sha256"],
            )
        failed = finish_action(
            self.run,
            "attempt-1",
            "failed",
            {},
            None,
            "backend failed",
            started["event"]["event_sha256"],
        )
        with self.assertRaisesRegex(Stage2Error, "replay-not-authorized"):
            start_action(
                self.run,
                "attempt-1",
                "generation",
                {},
                {},
                failed["event_sha256"],
            )
        empty_started = start_action(
            self.run, "attempt-2", "search", {}, {}, failed["event_sha256"]
        )
        empty = finish_action(
            self.run,
            "attempt-2",
            "empty",
            {},
            {"usd": None, "tokens": None},
            None,
            empty_started["event"]["event_sha256"],
        )
        inspected = inspect_workflow(self.run, expected_head=empty["event_sha256"])
        self.assertEqual(
            inspected["actions"]["attempt-1"]["result"]["status"], "failed"
        )
        self.assertEqual(inspected["actions"]["attempt-2"]["result"]["status"], "empty")
        self.assertIsNone(inspected["actions"]["attempt-2"]["result"]["cost"]["usd"])
        with self.assertRaisesRegex(Stage2Error, "unsafe-action-id"):
            start_action(self.run, "../escape", "search", {}, {}, empty["event_sha256"])

    def test_terminal_status_and_cost_contracts_fail_before_writing(self):
        state = self.initialize()
        started = start_action(
            self.run, "result-contract", "search", {}, {}, state["head_sha256"]
        )
        head = started["event"]["event_sha256"]
        invalid = (
            ("complete", {}, None, None, "complete-requires-artifact"),
            ("failed", {}, None, None, "failed-requires-error"),
            ("unavailable", {}, None, "", "unavailable-requires-error"),
            ("interrupted", {}, {"tokens": -1}, "stopped", "invalid-cost"),
            ("empty", {}, {"usd": float("nan")}, None, "invalid-cost"),
            ("empty", {}, None, "not a failure", "empty-must-have-no"),
        )
        for status, artifacts, cost, error, pattern in invalid:
            with self.subTest(status=status, pattern=pattern):
                with self.assertRaisesRegex(Stage2Error, pattern):
                    finish_action(
                        self.run,
                        "result-contract",
                        status,
                        artifacts,
                        cost,
                        error,
                        head,
                    )
        self.assertIsNone(
            inspect_workflow(self.run)["actions"]["result-contract"]["result"]
        )


if __name__ == "__main__":
    unittest.main()

# ruff: noqa: E402 -- use the repository CLI.
from copy import deepcopy
import sys
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "cli"))
sys.path.insert(0, str(HERE))
from stage_pipeline_fixture_helpers import StagePipelineFixture
from research_workspace_native.stage_pipeline import StagePipeline
from stage2_common import Stage2Error
from stage2_common import canonical_hash
import hashlib
import json
from jsonschema import Draft202012Validator, ValidationError


class StagePipelineSafetyTests(StagePipelineFixture):
    def test_compact_extraction_keeps_original_payload_and_spans(self):
        self.step()
        self.step()
        task = self.pipeline.next_task()
        payload = json.loads(task["prompt"].rsplit("\n", 1)[1])
        self.assertEqual(payload["packet"], self.pipeline.packet)
        self.assertEqual(payload["generation_schema"], task["schema"])
        self.assertEqual(
            "".join(row["quote"] for row in payload["numbered_proposal_spans"]),
            self.pipeline.prose["research"]["text"],
        )

    def test_compact_assessment_schema_keeps_original_validation(self):
        self.pipeline.max_calls = 9
        for _ in range(8):
            self.step()
        task = self.pipeline.next_task()
        compact = json.loads(task["prompt"].rsplit("\n", 1)[1])
        value = self.output(task)
        for schema in (task["schema"], compact):
            validator = Draft202012Validator(schema)
            validator.validate(value)
            wrong = deepcopy(value)
            del wrong["assessment"]["checks"]["opportunity"]["rationale"]
            with self.assertRaises(ValidationError):
                validator.validate(wrong)
            wrong = deepcopy(value)
            wrong["assessment"]["checks"]["materials"]["score"] = 3
            with self.assertRaises(ValidationError):
                validator.validate(wrong)

    def test_aggregate_source_prompt_is_refused_before_intent(self):
        for index, row in enumerate(self.packet["sources"]):
            path = self.sources / row["path"]
            raw = path.read_bytes() + ("資料" * 1000).encode("utf8")
            path.write_bytes(raw)
            row["sha256"] = hashlib.sha256(raw).hexdigest()
            self.assertLess(len(raw), 9000, index)
        self.path.write_text(json.dumps(self.packet), encoding="utf8")
        pipeline = StagePipeline(
            self.path,
            self.sources,
            self.root / "oversized-pipeline",
            expected_packet_sha256=canonical_hash(self.packet),
            source_sha256="a" * 64,
            verify_receipt=self.verify,
        )
        for operation in (pipeline.next_task, lambda: pipeline.begin_task("b" * 64)):
            with self.assertRaisesRegex(Stage2Error, "pipeline-prompt-byte-bound"):
                operation()
        self.assertIsNone(pipeline.pending)
        self.assertEqual(pipeline.records, [])
        self.assertFalse(list((pipeline.root / "intents").glob("*.json")))
        self.assertEqual(self.verifications, 0)

    def test_retained_reply_cannot_expand_next_prompt_past_bound(self):
        self.step("Retained summary. " * 1000)
        before = list((self.pipeline.root / "intents").glob("*.json"))
        with self.assertRaisesRegex(Stage2Error, "pipeline-prompt-byte-bound"):
            self.pipeline.next_task()
        self.assertEqual(list((self.pipeline.root / "intents").glob("*.json")), before)
        self.assertIsNone(self.pipeline.pending)
        self.assertEqual(len(self.pipeline.records), 1)
        self.assertEqual(self.verifications, 1)

    def test_semantic_repair_includes_prior_reply_in_prompt_bound(self):
        self.step()
        self.step()
        self.step("{not JSON " * 1000)
        self.assertEqual(self.pipeline.records[-1]["status"], "invalid")
        before = list((self.pipeline.root / "intents").glob("*.json"))
        with self.assertRaisesRegex(Stage2Error, "pipeline-prompt-byte-bound"):
            self.pipeline.next_task()
        self.assertEqual(list((self.pipeline.root / "intents").glob("*.json")), before)
        self.assertIsNone(self.pipeline.pending)

    def test_multiple_candidates_are_accepted_then_require_selection(self):
        self.step()
        self.step()
        task = self.pipeline.next_task()
        extraction = self.output(task)
        second = deepcopy(extraction["candidates"][0])
        second["candidate"]["question"] = "Can another bounded measurement help?"
        extraction["candidates"].append(second)
        self.pipeline.begin_task(task["task_sha256"])
        self.pipeline.accept(
            task["task_sha256"], self.receipt(task, json.dumps(extraction))
        )
        self.assertEqual(self.pipeline.records[-1]["status"], "accepted")
        self.assertEqual(len(self.pipeline.view()["candidates"]), 2)
        reopened = self.open()
        self.assertEqual(reopened.view()["completed_steps"], 3)
        with self.assertRaisesRegex(Stage2Error, "candidate-selection-required"):
            reopened.next_task()
        self.assertEqual(len(reopened.view()["candidates"]), 2)
        self.assertIsNone(reopened.pending)

    def test_grown_native_artifact_rejected_without_recording_success(self):
        task = self.pipeline.next_task()
        self.pipeline.begin_task(task["task_sha256"])
        receipt = self.receipt(task)
        with Path(receipt["raw_artifact"]["path"]).open("r+b") as stream:
            stream.truncate(8388609)
        with self.assertRaises(Stage2Error):
            self.pipeline.accept(task["task_sha256"], receipt)
        self.assertEqual(self.pipeline.view()["status"], "execution-unknown")
        self.assertEqual(self.pipeline.records, [])

    def test_snapshot_receipt_tampering_and_stale_instance_rejected(self):
        other = self.open()
        task = self.pipeline.next_task()
        self.pipeline.begin_task(task["task_sha256"])
        with self.assertRaises(Stage2Error):
            other.begin_task(task["task_sha256"])
        self.pipeline.accept(task["task_sha256"], self.receipt(task))
        self.step()
        self.step()
        path = self.pipeline.root / "records" / "0003.json"
        record = json.loads(path.read_bytes())
        record["snapshot_after"] = "b" * 64
        path.write_text(json.dumps(record), encoding="utf8")
        with self.assertRaises(Stage2Error):
            self.open()

    def test_unknown_pending_reopen_no_new_attempt(self):
        task = self.pipeline.next_task()
        self.pipeline.begin_task(task["task_sha256"])
        reopened = self.open()
        self.assertEqual(reopened.view()["status"], "execution-unknown")
        self.assertIsNone(reopened.next_task())
        with self.assertRaises(Stage2Error):
            reopened.begin_task(task["task_sha256"])

    def test_receipt_binding_and_source_change_fail_closed(self):
        task = self.pipeline.next_task()
        self.pipeline.begin_task(task["task_sha256"])
        receipt = self.receipt(task)
        receipt["prompt_sha256"] = "b" * 64
        with self.assertRaises(Stage2Error):
            self.pipeline.accept(task["task_sha256"], receipt)
        self.assertFalse(list((self.pipeline.root / "records").glob("*.json")))
        (self.sources / "source-1.txt").write_text("changed", encoding="utf8")
        with self.assertRaises(Stage2Error):
            self.pipeline.accept(task["task_sha256"], self.receipt(task))

    def test_invalid_original_and_one_repair_remain_separate(self):
        self.step()
        self.step()
        self.step("{not json}")
        task = self.pipeline.next_task()
        self.assertEqual(task["attempt"], 1)
        self.assertIn("previous_final", task["prompt"])
        self.step("{still not json}")
        self.assertIsNone(self.pipeline.next_task())
        self.assertEqual(self.pipeline.view()["status"], "semantic-repair-exhausted")
        self.assertEqual(
            [r["status"] for r in self.pipeline.records[-2:]], ["invalid", "invalid"]
        )
        self.assertEqual(self.open().view()["status"], "semantic-repair-exhausted")

    def test_thread_isolation_and_native_raw_tampering_rejected(self):
        for _ in range(5):
            self.step()
        task = self.pipeline.next_task()
        self.pipeline.begin_task(task["task_sha256"])
        receipt = self.receipt(task)
        receipt["thread_id"] = self.pipeline.prose["challenger"]["thread_id"]
        self.pipeline.accept(task["task_sha256"], receipt)
        self.assertEqual(self.pipeline.records[-1]["status"], "invalid")
        artifact = self.pipeline.records[0]["receipt"]["raw_artifact"]["path"]
        Path(artifact).write_bytes(b"changed")
        with self.assertRaises(Stage2Error):
            self.open()


if __name__ == "__main__":
    unittest.main()

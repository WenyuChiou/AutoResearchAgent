# ruff: noqa: E402 -- exercise the repository CLI without installing the plugin.
"""Actual production context policy; no ceiling override or model execution."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "cli"))
sys.path.insert(0, str(HERE))

from research_workspace_native.stage_pipeline import (
    MAX_TASK_PROMPT_BYTES,
    PHASES,
    StagePipeline,
)
from stage_pipeline_fixture_helpers import StagePipelineFixture, digest
from stage2_common import Stage2Error, canonical_hash
from stage2_live.extraction import build_span_index, generation_schema
from stage2_workflow.store import inspect_workflow, start_action


class StagePipelinePromptBoundsTests(StagePipelineFixture):
    def inventory(self):
        return {
            str(path.relative_to(self.pipeline.root)): digest(path.read_bytes())
            for path in self.pipeline.root.rglob("*")
            if path.is_file()
        }

    def refuse(self):
        before = self.inventory()
        records = deepcopy(self.pipeline.records)
        verifications = self.verifications
        for operation in (
            self.pipeline.next_task,
            lambda: self.pipeline.begin_task("b" * 64),
        ):
            with self.assertRaisesRegex(
                Stage2Error, "^pipeline-prompt-byte-bound-exceeded$"
            ):
                operation()
            self.assertEqual(self.inventory(), before)
            self.assertEqual(self.pipeline.records, records)
            self.assertEqual(self.verifications, verifications)
            self.assertIsNone(self.pipeline.pending)

    def source_pipeline(self, extra, *, second_extra=""):
        for row, addition in zip(self.packet["sources"], (extra, second_extra)):
            path = self.sources / row["path"]
            original = path.read_bytes()
            raw = original + addition.encode("utf8")
            path.write_bytes(raw)
            row["sha256"] = digest(raw)
        self.path.write_text(json.dumps(self.packet), encoding="utf8")
        self.pipeline = StagePipeline(
            self.path,
            self.sources,
            self.root / "bounded-source-pipeline",
            expected_packet_sha256=canonical_hash(self.packet),
            source_sha256="a" * 64,
            verify_receipt=self.verify,
        )

    def seed_reply_context(self):
        """Supply validated authored phase context without dispatching any task.

        This setup is not a completed Stage2 run. The production ceiling stays
        active while testing each reply-driven phase independently.
        """
        text = self.output({"phase": "research"})
        self.pipeline.prose["research"] = {
            "text": text,
            "thread_id": "authored-research",
            "raw_artifact": {},
        }
        task = {
            "phase": "extraction",
            "unit_key": "authored-extraction",
            "schema": generation_schema(build_span_index(text), self.pipeline.packet),
        }
        self.pipeline._consume(task, {"final_text": json.dumps(self.output(task))})
        for role in ("challenger", "feasibility"):
            task = {"phase": role, "schema": None, "prompt_sha256": digest(b"")}
            receipt = self.receipt(task)
            self.pipeline._consume(task, receipt)
            self.pipeline.position = PHASES.index(role + "-extraction")
            task = self.pipeline.next_task()
            self.pipeline._consume(task, self.receipt(task))
        self.pipeline.prose["reconciliation"] = {
            "text": text,
            "thread_id": "authored-reconciliation",
            "raw_artifact": {},
        }

    def test_complete_source_at_eight_mib_refused_before_task_or_intent(self):
        original = (self.sources / "source-1.txt").read_bytes()
        self.source_pipeline("x" * (8388608 - len(original)))
        source = self.sources / "source-1.txt"
        raw = source.read_bytes()
        self.assertEqual(len(raw), 8388608)
        self.refuse()
        self.assertEqual(source.read_bytes(), raw)
        self.pipeline = StagePipeline(
            self.path,
            self.sources,
            self.pipeline.root,
            expected_packet_sha256=canonical_hash(self.packet),
            source_sha256="a" * 64,
            verify_receipt=self.verify,
        )
        self.refuse()
        self.assertEqual(self.pipeline.records, [])

    def test_aggregate_limit_applies_across_individually_small_sources(self):
        self.source_pipeline("a" * 5000, second_extra="b" * 5000)
        self.assertTrue(
            all(
                (self.sources / row["path"]).stat().st_size < MAX_TASK_PROMPT_BYTES
                for row in self.packet["sources"]
            )
        )
        self.refuse()

    def test_cached_legacy_oversized_intent_refused_on_reopen_without_rewrite(self):
        task = self.pipeline.next_task()
        prefix = task["prompt"].split("\n", 1)[0] + "\n"
        self.source_pipeline("x" * 20000)
        task["prompt"] = prefix + json.dumps(
            {
                "packet": self.pipeline.packet,
                "source_text": {
                    row["source_id"]: (self.sources / row["path"]).read_text("utf8")
                    for row in self.pipeline.packet["sources"]
                },
            },
            ensure_ascii=False,
        )
        task["prompt_sha256"] = digest(task["prompt"].encode("utf8"))
        task["snapshot_sha256"] = self.pipeline.snapshot
        task.pop("task_sha256")
        task["task_sha256"] = canonical_hash(task)
        self.assertGreater(len(task["prompt"].encode("utf8")), MAX_TASK_PROMPT_BYTES)
        intent = self.pipeline.root / "intents" / "0001.json"
        intent.parent.mkdir()
        intent.write_text(json.dumps(task), encoding="utf8")
        state = inspect_workflow(self.pipeline.run)
        start_action(
            self.pipeline.run,
            task["unit_key"],
            "native-appserver-stage-unit",
            {"task_sha256": task["task_sha256"]},
            self.pipeline.binding,
            state["head_sha256"],
        )
        before = self.inventory()
        with self.assertRaisesRegex(
            Stage2Error, "^pipeline-prompt-byte-bound-exceeded$"
        ):
            StagePipeline(
                self.path,
                self.sources,
                self.pipeline.root,
                expected_packet_sha256=canonical_hash(self.packet),
                source_sha256="a" * 64,
                verify_receipt=self.verify,
            )
        self.assertEqual(self.inventory(), before)
        self.assertEqual(json.loads(intent.read_bytes()), task)
        self.assertEqual(self.verifications, 0)

    def test_unicode_exact_ceiling_preserves_full_prompt_and_duplicate_guard(self):
        original = self.pipeline.next_task()
        room = MAX_TASK_PROMPT_BYTES - len(original["prompt"].encode("utf8"))
        suffix = "汉" * (room // 3) + "x" * (room % 3)
        self.source_pipeline(suffix)
        task = self.pipeline.next_task()
        self.assertEqual(len(task["prompt"].encode("utf8")), MAX_TASK_PROMPT_BYTES)
        self.assertIn(suffix, task["prompt"])
        self.assertEqual(task["prompt_sha256"], digest(task["prompt"].encode("utf8")))
        self.pipeline.begin_task(task["task_sha256"])
        self.assertIsNone(self.pipeline.next_task())
        with self.assertRaisesRegex(Stage2Error, "task-unavailable-or-stale"):
            self.pipeline.begin_task(task["task_sha256"])
        self.assertEqual(len(list((self.pipeline.root / "intents").glob("*.json"))), 1)
        self.assertEqual(self.verifications, 0)

    def test_one_unicode_byte_over_ceiling_refused(self):
        room = MAX_TASK_PROMPT_BYTES - len(
            self.pipeline.next_task()["prompt"].encode("utf8")
        )
        self.source_pipeline("汉" * (room // 3) + "x" * (room % 3 + 1))
        self.refuse()

    def test_retained_maximum_reply_refused_without_truncation_and_after_reopen(self):
        text = "r" * 262144
        self.step(text)
        artifact = self.pipeline.root / "units" / "0001-final.txt"
        self.assertEqual(artifact.read_bytes(), text.encode("utf8"))
        self.refuse()
        self.pipeline = self.open()
        self.refuse()
        self.assertEqual(artifact.read_bytes(), text.encode("utf8"))
        self.assertEqual(self.pipeline.records[0]["text"], text)

    def test_all_later_retained_prose_phases_count_complete_reply_bytes(self):
        self.seed_reply_context()
        for phase, role in (
            ("extraction", "research"),
            ("challenger-extraction", "challenger"),
            ("feasibility-extraction", "feasibility"),
            ("reconciliation-extraction", "reconciliation"),
        ):
            with self.subTest(phase=phase):
                original = self.pipeline.prose[role]["text"]
                text = "文" * 5000
                self.pipeline.prose[role]["text"] = text
                self.pipeline.position = PHASES.index(phase)
                self.refuse()
                self.assertEqual(self.pipeline.prose[role]["text"], text)
                self.pipeline.prose[role]["text"] = original

    def test_oversized_semantic_repair_preserves_failed_attempt(self):
        self.seed_reply_context()
        self.pipeline.position = PHASES.index("challenger-extraction")
        failed = "{" + "x" * 262143
        self.step(failed)
        self.assertEqual(self.pipeline.records[-1]["status"], "invalid")
        self.assertEqual(self.pipeline.attempt, 1)
        self.refuse()
        self.assertEqual(self.pipeline.records[-1]["text"], failed)
        self.assertEqual(
            (self.pipeline.root / "units" / "0001-final.txt").read_text(), failed
        )


if __name__ == "__main__":
    unittest.main()

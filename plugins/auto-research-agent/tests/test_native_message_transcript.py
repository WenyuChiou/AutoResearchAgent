"""Saved real SQLite frames and injected transport; no native/model invocation."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
import test_native_message_api as fixture
from research_workspace_native.store import JournalError
from stage1_deliverable.common import sha


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.MessageApiTests("runTest")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.p = self.case.project()
        self.receipt = self.case.api.message(
            "token-a", self.p.ref, self.case.body(self.p)
        )
        request = self.p.channel.messages()[0]
        self.p.channel.incoming = [
            json.dumps(
                dict(id=request["id"], result=dict(turn=dict(id="turn-one")))
            ).encode()
            + b"\n"
        ]
        self.p.controller.pump(1)

    def frame(self, method, **params):
        params = dict(threadId=self.p.thread, turnId="turn-one", **params)
        return dict(method=method, params=params)

    def save(self, message, *, raw_message=None):
        raw = json.dumps(raw_message or message, ensure_ascii=False) + "\n"
        self.p.store.ingest_frame(
            self.p.pid,
            self.p.owner,
            dict(
                connection_id=self.p.epoch,
                direction="incoming",
                kind="notification",
                message=message,
                raw_utf8=raw,
            ),
        )
        return sha(raw.encode())

    def view(self):
        before = self.p.store.events(self.p.pid)
        calls = list(self.p.channel.calls)
        view = self.case.api.view("token-a", self.p.ref)
        self.assertEqual(self.p.store.events(self.p.pid), before)
        self.assertEqual(self.p.channel.calls, calls)
        self.assertEqual(view["transcript"]["schema_version"], "1.0.0")
        self.assertEqual(
            set(view),
            {
                "project_ref",
                "index_sha256",
                "input_version",
                "revision",
                "failure",
                "requests",
                "actions",
                "operations",
                "transcript",
            },
        )
        return view["transcript"]

    def test_exact_saved_final_text_supersedes_partial_without_completing_research(
        self,
    ):
        delta = self.frame(
            "item/agentMessage/delta", itemId="agent-one", delta="Partial "
        )
        final = self.frame(
            "item/completed",
            item=dict(
                type="agentMessage",
                id="agent-one",
                text="Literal <img> 简體 source text.",
            ),
        )
        self.p.channel.incoming = [
            json.dumps(row, ensure_ascii=False).encode() + b"\n"
            for row in (delta, final)
        ]
        self.p.controller.pump(1)
        self.p.controller.pump(1)
        rows = self.view()["entries"]
        user, assistant = rows
        self.assertEqual(user["text"], "Read these recorded sources.")
        self.assertEqual(assistant["text"], final["params"]["item"]["text"])
        self.assertEqual(
            (assistant["kind"], assistant["status"]), ("assistant-final", "completed")
        )
        self.assertEqual(len(assistant["frame_refs"]), 2)
        self.assertEqual(assistant["action_ref"], self.receipt["action_ref"])
        self.assertEqual(
            self.case.api.action("token-a", self.p.ref, self.receipt["action_ref"])[
                "status"
            ],
            "dispatched",
        )
        public = json.dumps(rows)
        for private in (
            self.p.root.as_posix(),
            self.p.thread,
            self.p.epoch,
            "agent-one",
            "turn-one",
        ):
            self.assertNotIn(private, public)

    def test_partial_text_tool_failure_and_turn_failure_remain_separate(self):
        source_hash = self.save(
            self.frame(
                "item/agentMessage/delta", itemId="part", delta="Unfinished reply"
            )
        )
        self.save(
            self.frame(
                "item/completed",
                item=dict(
                    type="commandExecution",
                    id="tool-one",
                    status="completed",
                    exitCode=1,
                    command=str(self.p.root),
                    aggregatedOutput="private stderr",
                ),
            )
        )
        self.save(
            self.frame("error", error={"message": "private secret", "code": "internal"})
        )
        self.save(
            dict(
                method="turn/completed",
                params=dict(
                    threadId=self.p.thread, turn=dict(id="turn-one", status="failed")
                ),
            )
        )
        rows = self.view()["entries"]
        assistant = next(row for row in rows if row["role"] == "assistant")
        tool = next(row for row in rows if row["role"] == "tool")
        self.assertEqual(assistant["status"], "partial")
        self.assertEqual(assistant["frame_refs"][0]["raw_sha256"], source_hash)
        self.assertEqual(
            (tool["status"], tool["failure"]), ("failed", "native-tool-failed")
        )
        self.assertTrue(
            any(
                row["kind"] == "turn-terminal" and row["status"] == "failed"
                for row in rows
            )
        )
        self.assertNotIn("private stderr", json.dumps(rows))
        self.assertNotIn("private secret", json.dumps(rows))
        self.assertNotIn(self.p.root.as_posix(), json.dumps(rows))

    def test_foreign_turn_other_principal_and_unsupported_payload_are_not_borrowed(
        self,
    ):
        self.save(
            dict(
                method="item/completed",
                params=dict(
                    threadId=self.p.thread,
                    turnId="foreign",
                    item=dict(type="agentMessage", id="same", text="foreign turn"),
                ),
            )
        )
        self.save(
            self.frame(
                "item/reasoning/textDelta", itemId="hidden", delta="private reasoning"
            )
        )
        self.assertEqual([row["role"] for row in self.view()["entries"]], ["user"])
        registration = self.case.api._projects[self.p.ref]
        self.case.api._projects[self.p.ref] = (
            registration[0],
            frozenset({"principal-a", "principal-b"}),
            *registration[2:],
        )
        other = self.case.api.view("token-b", self.p.ref)["transcript"]
        self.assertEqual(other["entries"], [])
        self.assertNotIn("Read these recorded sources.", json.dumps(other))

    def test_quarantined_raw_message_is_retained_but_not_promoted_to_reply(self):
        frame = self.frame(
            "item/completed",
            item=dict(type="agentMessage", id="bad", text="do not display"),
        )
        with self.assertRaises(JournalError):
            self.save(frame, raw_message=dict(frame, method="unknown/raw-mismatch"))
        rows = self.view()["entries"]
        self.assertNotIn("do not display", json.dumps(rows))
        self.assertTrue(
            any(
                row["payload"].get("quarantine")
                for row in self.p.store.events(self.p.pid)
                if row["kind"] == "protocol-frame"
            )
        )

    def test_sqlite_reopen_preserves_observed_partial_with_zero_new_channel_io(self):
        self.save(
            self.frame(
                "item/agentMessage/delta",
                itemId="partial",
                delta="Saved before owner loss",
            )
        )
        self.case.reopen(self.p)
        transcript = self.view()
        self.assertEqual(self.p.channel.calls, [])
        self.assertEqual(
            next(row for row in transcript["entries"] if row["role"] == "assistant")[
                "text"
            ],
            "Saved before owner loss",
        )
        self.assertEqual(
            next(row for row in transcript["entries"] if row["role"] == "user")[
                "status"
            ],
            "execution-unknown",
        )

    def test_window_and_text_bounds_are_explicit_without_changing_saved_bytes(self):
        for number in range(130):
            self.save(
                self.frame(
                    "item/agentMessage/delta", itemId="stream", delta=str(number) + " "
                )
            )
        text = "字" * 8000
        self.save(
            self.frame(
                "item/completed", item=dict(type="agentMessage", id="long", text=text)
            )
        )
        transcript = self.view()
        self.assertTrue(transcript["window"]["truncated"])
        self.assertLessEqual(len(transcript["entries"]), 128)
        self.assertLessEqual(
            sum(
                len(row["text"].encode())
                for row in transcript["entries"]
                if row["text"]
            ),
            65536,
        )
        long = next(
            row for row in transcript["entries"] if row["kind"] == "assistant-final"
        )
        self.assertEqual(long["status"], "partial")
        self.assertLessEqual(len(long["text"].encode()), 16384)
        self.assertTrue(text.startswith(long["text"]))

    def test_oversize_frames_and_wrong_source_offer_do_not_promote_text(self):
        self.save(
            self.frame(
                "item/completed",
                item=dict(type="agentMessage", id="oversize", text="x" * 70000),
            )
        )
        transcript = self.view()
        self.assertTrue(transcript["window"]["truncated"])
        self.assertEqual([row["role"] for row in transcript["entries"]], ["user"])
        state = self.p.store.snapshot(self.p.pid)
        key = next(iter(state["session_api_actions"]))
        with self.p.store._edit(
            self.p.pid, self.p.owner, state["revision"], "fixture-corrupt-source", {}
        ) as changed:
            changed["session_api_actions"][key]["start_offer"]["document"][
                "input_version"
            ] = "f" * 64
        self.assertEqual(self.view()["entries"], [])

    def test_conflicting_final_item_and_later_tool_success_preserve_failure(self):
        for text in ("First saved final", "Conflicting saved final"):
            self.save(
                self.frame(
                    "item/completed",
                    item=dict(type="agentMessage", id="conflict", text=text),
                )
            )
        for status in ("failed", "completed"):
            self.save(
                self.frame(
                    "item/completed",
                    item=dict(type="fileChange", id="tool-retry", status=status),
                )
            )
        rows = self.view()["entries"]
        assistant = next(row for row in rows if row["role"] == "assistant")
        self.assertEqual(
            (assistant["kind"], assistant["status"], assistant["text"]),
            ("assistant-conflict", "unknown", None),
        )
        self.assertEqual(len(assistant["frame_refs"]), 2)
        self.assertEqual(
            [row["status"] for row in rows if row["role"] == "tool"],
            ["failed", "completed"],
        )

    def test_malformed_passive_item_fields_remain_saved_without_breaking_view(self):
        before = len(
            [
                event
                for event in self.p.store.events(self.p.pid)
                if event["kind"] == "protocol-frame"
            ]
        )
        for kind, status in (
            (["commandExecution"], "completed"),
            ("commandExecution", ["failed"]),
        ):
            self.save(
                self.frame(
                    "item/completed",
                    item=dict(type=kind, id="malformed", status=status),
                )
            )
        rows = self.view()["entries"]
        self.assertEqual([row["role"] for row in rows], ["user", "tool"])
        self.assertEqual(rows[1]["status"], "unknown")
        self.assertEqual(rows[1]["failure"], "malformed-native-tool-status")
        self.assertEqual(
            len(
                [
                    event
                    for event in self.p.store.events(self.p.pid)
                    if event["kind"] == "protocol-frame"
                ]
            ),
            before + 2,
        )


if __name__ == "__main__":
    unittest.main()

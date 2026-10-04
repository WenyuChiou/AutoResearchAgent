"""Synthetic saved-frame/write evidence; no controller, native process or model."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native.frame_journal import FrameJournal
from research_workspace_native.recording import RecordingChannel, records
from research_workspace_native.store import JournalError
from research_workspace_native.write_observation import observe_frame_write


class PartialWriter:
    def __init__(self):
        self.sent = bytearray()
        self.fail = False

    def read(self, size, timeout):
        raise AssertionError("fixture must never read")

    def write(self, data, timeout):
        if self.fail:
            raise TimeoutError("synthetic write timeout")
        count = min(7, len(data))
        self.sent.extend(data[:count])
        return count

    def close(self):
        pass


class WriteObservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.j = FrameJournal(Path(temporary.name).resolve() / "wire.sqlite3")
        self.addCleanup(self.j.close)
        self.j.bind_project("alpha", "a" * 64)
        self.owner = self.j.acquire_owner("alpha", "fixture")
        self.call("bind_thread", "thread-a")
        self.call("bind_connection", "epoch-a")
        self.fake = PartialWriter()
        self.channel = RecordingChannel(
            self.fake,
            store=self.j,
            project_id="alpha",
            owner=self.owner,
            connection_id="epoch-a",
        )
        self.addCleanup(self.channel.close)
        self.first = self.j.snapshot("alpha")["byte_channels"]["epoch-a"]["seq"]

    def call(self, name, *args):
        return getattr(self.j, name)(
            "alpha", self.owner, *args, self.j.snapshot("alpha")["revision"]
        )

    def prepare(self, padding=""):
        params = dict(threadId="thread-a", turnId="turn-a" + padding)
        self.call("record_intent", "stop", "turn/interrupt", params)
        self.call("correlate", "epoch-a", 7, "stop")
        self.call("transition_intent", "stop", "dispatching", {"fixture": True})
        self.emit(
            dict(id=7, method="turn/interrupt", params=params), "outgoing", "request"
        )

    def emit(self, message, direction, kind):
        raw = json.dumps(message, ensure_ascii=False).encode() + b"\n"
        state = self.j.ingest_frame(
            "alpha",
            self.owner,
            dict(
                connection_id="epoch-a",
                direction=direction,
                kind=kind,
                message=message,
                raw_utf8=raw.decode(),
            ),
        )
        self.outgoing = dict(raw=raw, frame_seq=state["protocol"]["frame_seq"])

    def write_all(self):
        offset, raw = 0, self.outgoing["raw"]
        while offset < len(raw):
            offset += self.channel.write(raw[offset:], 1)

    def observe(self, **changes):
        args = dict(
            project_id="alpha",
            owner=self.owner,
            index_sha256="a" * 64,
            thread_id="thread-a",
            connection_id="epoch-a",
            first_seq=self.first,
            outgoing=self.outgoing,
        )
        return observe_frame_write(self.j, **(args | changes))

    def test_partial_writes_cross_pages_and_read_preserves_store(self):
        self.prepare("x" * 400)
        self.write_all()
        before = self.j.snapshot("alpha"), self.j.events("alpha")
        proof = self.observe()
        self.assertEqual(proof["classification"], "observed-full-frame-write")
        self.assertGreater(proof["last_seq"] - self.first, 100)
        self.assertEqual(proof["observed_bytes"], len(self.fake.sent))
        self.assertEqual(self.fake.sent, self.outgoing["raw"])
        self.assertEqual(before, (self.j.snapshot("alpha"), self.j.events("alpha")))

    def test_wrong_context_frame_or_range_is_rejected(self):
        self.prepare()
        self.write_all()
        cases = [
            dict(owner="old"),
            dict(project_id="missing"),
            dict(index_sha256="b" * 64),
            dict(thread_id="other"),
            dict(connection_id="other"),
            dict(first_seq=True),
            dict(first_seq=10**30),
            dict(max_records=1),
            dict(max_records=20001),
            dict(outgoing={}),
            dict(outgoing=dict(raw=b"", frame_seq=1)),
            dict(outgoing=dict(raw=self.outgoing["raw"], frame_seq=True)),
            dict(outgoing=dict(raw=self.outgoing["raw"], frame_seq=2)),
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(JournalError):
                self.observe(**case)

    def test_incoming_frame_cannot_anchor_arbitrary_written_bytes(self):
        self.emit(
            dict(method="notice", params={"threadId": "thread-a"}),
            "incoming",
            "notification",
        )
        self.write_all()
        with self.assertRaisesRegex(JournalError, "saved outgoing frame"):
            self.observe()

    def test_detached_corrupt_receipts_fail_without_rewriting_evidence(self):
        self.prepare()
        self.write_all()
        original = records(self.j, "alpha", "epoch-a", after_seq=self.first)
        mutations = [
            lambda r: r.pop(0),
            lambda r: r.insert(1, deepcopy(r[0])),
            lambda r: r[0].update(data=b"other"),
            lambda r: r[0].update(sha256="b" * 64),
            lambda r: r[0].update(owner="other"),
            lambda r: r[1].update(intent_seq=999),
            lambda r: r[1].update(count=True),
            lambda r: r[1].update(outcome="error"),
            lambda r: r[1].update(count=99999),
            lambda r: r.pop(),
        ]
        for mutate in mutations:
            rows = deepcopy(original)
            mutate(rows)
            with (
                self.subTest(mutation=mutate),
                patch(
                    "research_workspace_native.write_observation.records",
                    return_value=rows,
                ),
                self.assertRaises(JournalError),
            ):
                self.observe()
        self.assertEqual(
            original, records(self.j, "alpha", "epoch-a", after_seq=self.first)
        )

    def test_incomplete_and_failed_writes_never_make_full_frame_receipt(self):
        self.prepare()
        self.channel.write(self.outgoing["raw"], 1)
        with self.assertRaisesRegex(JournalError, "frame write incomplete"):
            self.observe()
        self.fake.fail = True
        with self.assertRaises(TimeoutError):
            self.channel.write(self.outgoing["raw"][7:], 1)
        with self.assertRaises(JournalError):
            self.observe()


if __name__ == "__main__":
    unittest.main()

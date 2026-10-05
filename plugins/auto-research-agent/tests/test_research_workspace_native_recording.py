"""Synthetic channel/storage boundaries; no native launcher or model calls."""

from collections import deque
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native.frame_journal import FrameJournal
from research_workspace_native import recording
from research_workspace_native.recording import (
    RecordingChannel,
    RecordingError,
    records,
)
from research_workspace_native.store import JournalError
from research_workspace_native.transport import DispatchUnknown, JsonRpcTransport


class Fake:
    def __init__(self, reads=(), write_limit=None):
        self.reads = deque(reads)
        self.write_limit = write_limit
        self.calls = []
        self.sent = []
        self.closed = 0

    def read(self, size, timeout):
        self.calls.append(("read", size, timeout))
        value = self.reads.popleft()
        if isinstance(value, BaseException):
            raise value
        return value

    def write(self, data, timeout):
        self.calls.append(("write", data, timeout))
        if isinstance(self.write_limit, BaseException):
            raise self.write_limit
        count = (
            len(data) if self.write_limit is None else min(self.write_limit, len(data))
        )
        self.sent.append(data[:count])
        return count

    def close(self):
        self.closed += 1


class NativeRecordingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.j = FrameJournal(self.root / "records.sqlite3")
        self.addCleanup(self.j.close)
        self.j.bind_project("alpha", "a" * 64)
        self.owner = self.j.acquire_owner("alpha", "test")
        self.call("bind_thread", "thread-a")

    def call(self, name, *args):
        return getattr(self.j, name)(
            "alpha", self.owner, *args, self.j.snapshot("alpha")["revision"]
        )

    def wrap(self, fake, epoch="wire", **limits):
        return RecordingChannel(
            fake,
            store=self.j,
            project_id="alpha",
            owner=self.owner,
            connection_id=epoch,
            **limits,
        )

    def rows(self, epoch="wire"):
        return records(self.j, "alpha", epoch)

    def test_malformed_bytes_are_saved_before_transport_rejects_them(self):
        for i, raw in enumerate((b"\xff\n", b"{broken}\n")):
            epoch = f"bad-{i}"
            fake = Fake([raw])
            channel = self.wrap(fake, epoch)
            transport = JsonRpcTransport(
                channel,
                connection_id=epoch,
                on_event=lambda event: None,
                verify_binding=lambda: True,
            )
            with self.assertRaises(DispatchUnknown):
                transport.poll(1)
            saved = [
                r
                for r in self.rows(epoch)
                if r["operation"] == "read" and r["phase"] == "result"
            ]
            self.assertEqual(saved[0]["data"], raw)
            self.assertTrue(saved[0]["capture_complete"])
            self.assertEqual(fake.closed, 1)

    def test_partial_write_receipts_connect_to_the_existing_frame_journal(self):
        self.call("bind_connection", "wire")
        payload = {"threadId": "thread-a", "text": "neutral synthetic request"}
        self.call("record_intent", "start", "turn/start", payload)
        self.call("correlate", "wire", 7, "start")
        self.call("transition_intent", "start", "dispatching", {"pre_send": True})
        fake = Fake(
            [
                b'{"id":7,"result":{"turn":{"id":"turn-a"}}}\n'
                b'{"method":"turn/completed","params":{"threadId":"thread-a","turn":{"id":"turn-a","status":"completed"}}}\n'
            ],
            write_limit=5,
        )
        channel = self.wrap(fake)
        transport = JsonRpcTransport(
            channel,
            connection_id="wire",
            verify_binding=lambda: True,
            on_event=lambda event: self.j.ingest_frame("alpha", self.owner, event),
        )
        transport.send_request("turn/start", payload, request_id=7)
        transport.wait_response(7)
        transport.poll(1)
        self.assertEqual(
            self.j.snapshot("alpha")["intents"]["start"]["status"], "completed"
        )
        rows = self.rows()
        writes = [r for r in rows if r["operation"] == "write"]
        results = [r for r in writes if r["phase"] == "result"]
        self.assertGreater(len(results), 1)
        self.assertEqual(sum(r["count"] for r in results), len(b"".join(fake.sent)))
        self.assertTrue(all(r["capture_complete"] is None for r in results))
        self.assertEqual(writes[0]["data"], b"".join(fake.sent))
        self.assertTrue(
            all(
                r["index_sha256"] == "a" * 64 and r["thread_id"] == "thread-a"
                for r in rows
            )
        )
        transport.close()

    def test_idle_timeout_is_distinct_from_eof_and_write_timeout(self):
        fake = Fake([TimeoutError(), b"partial", b""])
        channel = self.wrap(fake)
        with self.assertRaises(TimeoutError):
            channel.read(8, 1)
        self.assertEqual(channel.read(8, 1), b"partial")
        self.assertEqual(channel.read(8, 1), b"")
        results = [
            r
            for r in self.rows()
            if r["operation"] == "read" and r["phase"] == "result"
        ]
        self.assertEqual(
            [r["outcome"] for r in results], ["timeout", "returned", "eof"]
        )
        self.assertIsNone(results[0]["data"])
        self.assertEqual(results[-1]["data"], b"")
        with self.assertRaises(RecordingError):
            channel.read(8, 1)
        self.assertEqual(len(fake.calls), 3)
        failing = Fake(write_limit=TimeoutError())
        channel2 = self.wrap(failing, "write-timeout")
        with self.assertRaises(TimeoutError):
            channel2.write(b"raw", 1)
        with self.assertRaises(RecordingError):
            channel2.write(b"raw", 1)
        self.assertEqual(len(failing.calls), 1)
        self.assertEqual(self.rows("write-timeout")[-1]["outcome"], "timeout")
        channel.close()
        channel2.close()

    def test_invalid_returns_preserve_capture_limits_and_lock_the_channel(self):
        for i, value in enumerate((b"123456", b"123456789", None)):
            epoch = f"invalid-{i}"
            fake = Fake([value])
            channel = self.wrap(fake, epoch, max_chunk_bytes=8)
            with self.assertRaises(RecordingError):
                channel.read(4, 1)
            result = self.rows(epoch)[-1]
            self.assertEqual(result["outcome"], "invalid-return")
            self.assertEqual(
                result["data"], value[:8] if isinstance(value, bytes) else None
            )
            self.assertEqual(
                result["capture_complete"], isinstance(value, bytes) and len(value) <= 8
            )
            with self.assertRaises(RecordingError):
                channel.read(4, 1)
            self.assertEqual(len(fake.calls), 1)
            channel.close()

    def test_pre_io_failure_and_budget_rejection_perform_zero_reads_or_writes(self):
        fake = Fake([b"raw"])
        channel = self.wrap(fake)
        self.j.db.execute(
            "CREATE TRIGGER reject_intent BEFORE INSERT ON native_byte_records WHEN json_extract(NEW.metadata,'$.phase')='intent' BEGIN SELECT RAISE(ABORT,'synthetic intent failure'); END"
        )
        with self.assertRaises(RecordingError):
            channel.write(b"raw", 1)
        self.assertEqual(fake.calls, [])
        with self.assertRaises(RecordingError):
            channel.close()
        self.assertEqual(fake.closed, 1)
        channel.close()
        self.assertEqual(fake.closed, 1)
        self.j.db.execute("DROP TRIGGER reject_intent")
        budget_fake = Fake()
        budget = self.wrap(budget_fake, "budget", max_records=3)
        with self.assertRaises(RecordingError):
            budget.write(b"raw", 1)
        self.assertEqual(budget_fake.calls, [])
        budget.close()
        self.assertEqual(
            [r["operation"] for r in self.rows("budget")], ["open", "close", "close"]
        )

    def test_invalid_write_and_close_returns_are_failures_not_delivery(self):
        for i, count in enumerate((-1, 0, True)):
            fake = Fake(write_limit=count)
            channel = self.wrap(fake, f"bad-write-{i}")
            with self.assertRaises(RecordingError):
                channel.write(b"bytes", 1)
            result = self.rows(f"bad-write-{i}")[-1]
            self.assertEqual(result["outcome"], "invalid-return")
            self.assertEqual(result["count"], count if type(count) is int else None)
            with self.assertRaises(RecordingError):
                channel.write(b"bytes", 1)
            self.assertEqual(len(fake.calls), 1)
            channel.close()
        fake = Fake()
        fake.close = lambda: "invalid close result"
        channel = self.wrap(fake, "bad-close")
        with self.assertRaises(RecordingError):
            channel.close()
        self.assertEqual(self.rows("bad-close")[-1]["outcome"], "close-error")

    def test_old_owner_cannot_read_or_write_after_recovery(self):
        fake = Fake([b"bytes"])
        channel = self.wrap(fake)
        self.j.release_owner("alpha", self.owner)
        self.owner = self.j.acquire_owner("alpha", "replacement")
        with self.assertRaises(RecordingError):
            channel.read(8, 1)
        with self.assertRaises(RecordingError):
            channel.write(b"bytes", 1)
        self.assertEqual(fake.calls, [])
        with self.assertRaises(RecordingError):
            channel.close()
        self.assertEqual(fake.closed, 1)

    def test_post_io_persistence_failure_keeps_unknown_intent_and_no_redispatch(self):
        fake = Fake()
        channel = self.wrap(fake)
        self.j.db.execute(
            "CREATE TRIGGER reject_result BEFORE INSERT ON native_byte_records WHEN json_extract(NEW.metadata,'$.phase')='result' BEGIN SELECT RAISE(ABORT,'synthetic result failure'); END"
        )
        with self.assertRaises(RecordingError):
            channel.write(b"original bytes", 1)
        self.assertEqual(len(fake.calls), 1)
        pending = self.j.snapshot("alpha")["byte_channels"]["wire"]["pending"]
        self.assertEqual(list(pending.values()), ["write"])
        reader = FrameJournal(self.root / "records.sqlite3")
        self.addCleanup(reader.close)
        self.assertEqual(
            reader.snapshot("alpha")["byte_channels"]["wire"]["pending"], pending
        )
        self.assertEqual(self.rows()[-1]["data"], b"original bytes")
        with self.assertRaises(RecordingError):
            channel.write(b"original bytes", 1)
        self.assertEqual(len(fake.calls), 1)
        self.j.db.execute("DROP TRIGGER reject_result")
        channel.close()
        self.assertTrue(self.j.snapshot("alpha")["byte_channels"]["wire"]["pending"])

    def test_byte_records_are_immutable_detached_and_project_isolated(self):
        channel = self.wrap(Fake([b"\x00\xff"]))
        channel.read(8, 1)
        rows = self.rows()
        rows[-1]["data"] = b"edited copy"
        self.assertEqual(self.rows()[-1]["data"], b"\x00\xff")
        for query in (
            "UPDATE native_byte_records SET data=x'00'",
            "DELETE FROM native_byte_records",
        ):
            with self.assertRaises(sqlite3.IntegrityError):
                self.j.db.execute(query)
        self.j.bind_project("beta", "b" * 64)
        self.assertEqual(records(self.j, "beta", "wire"), [])
        token = self.j.acquire_owner("beta", "other")
        with self.assertRaises(JournalError):
            RecordingChannel(
                Fake(),
                store=self.j,
                project_id="beta",
                owner=token,
                connection_id="wire",
            )
        self.assertEqual(
            records(self.j, "alpha", "wire", after_seq=rows[0]["seq"], limit=1)[0][
                "seq"
            ],
            rows[1]["seq"],
        )
        channel.close()

    def test_process_crash_preserves_unpaired_intent_and_refuses_epoch_reattachment(
        self,
    ):
        path = self.root / "crash.sqlite3"
        code = """
import os,sys
sys.path.insert(0,sys.argv[2])
import research_workspace_native
research_workspace_native.__path__.insert(0,sys.argv[3])
from research_workspace_native.store import ProjectStore
from research_workspace_native.recording import RecordingChannel
class Channel:
    def read(self,*args): return b''
    def write(self,*args): os._exit(23)
    def close(self): pass
s=ProjectStore(sys.argv[1]);s.bind_project('alpha','a'*64)
owner=s.acquire_owner('alpha','crash')
c=RecordingChannel(Channel(),store=s,project_id='alpha',owner=owner,connection_id='crashed')
c.write(b'never-claimed-delivered',1)
"""
        cli = Path(
            sys.modules["research_workspace_native.frame_journal"].__file__
        ).parents[1]
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                code,
                str(path),
                str(cli),
                str(Path(recording.__file__).parent),
            ],
            timeout=20,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 23, result.stderr)
        recovered = FrameJournal(path)
        self.addCleanup(recovered.close)
        owner = recovered.acquire_owner("alpha", "recovery")
        saved = records(recovered, "alpha", "crashed")
        self.assertEqual(saved[-1]["phase"], "intent")
        self.assertEqual(saved[-1]["data"], b"never-claimed-delivered")
        self.assertTrue(
            recovered.snapshot("alpha")["byte_channels"]["crashed"]["pending"]
        )
        with self.assertRaises(JournalError):
            RecordingChannel(
                Fake(),
                store=recovered,
                project_id="alpha",
                owner=owner,
                connection_id="crashed",
            )


if __name__ == "__main__":
    unittest.main()

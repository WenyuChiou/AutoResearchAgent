"""Neutral SQLite/channel fixtures; consumers provide the construction factory.

This mixin has no TestCase base, default event sink or native process launcher.
"""

from collections import deque
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native.frame_journal import FrameJournal


class Channel:
    def __init__(self, limit=None, writes=()):
        self.reads, self.writes = deque(), deque(writes)
        self.limit, self.sent, self.calls, self.closed = limit, [], [], 0

    def queue(self, message):
        self.reads.append(json.dumps(message).encode() + b"\n")

    def read(self, size, timeout):
        self.calls.append("read")
        value = self.reads.popleft() if self.reads else TimeoutError("idle")
        if isinstance(value, BaseException):
            raise value
        return value

    def write(self, data, timeout):
        self.calls.append("write")
        count = (
            self.writes.popleft()
            if self.writes
            else min(self.limit or len(data), len(data))
        )
        if isinstance(count, BaseException):
            raise count
        self.sent.append(data[:count])
        return count

    def close(self):
        self.closed += 1

    def messages(self):
        return [json.loads(row) for row in b"".join(self.sent).splitlines()]


class NativeSessionFixture:
    """Combine with unittest.TestCase and provide a static connection_factory."""

    def setUp(self):
        self.setup_session(self.connection_factory)

    def setup_session(self, factory):
        if not callable(factory):
            raise TypeError("connection factory required")
        self._connection_factory = factory
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = FrameJournal(Path(folder.name).resolve() / "controller.sqlite3")
        self.addCleanup(self.store.close)
        self.store.bind_project("alpha", "a" * 64)
        self.owner = self.store.acquire_owner("alpha", "test")
        self.store.bind_thread(
            "alpha", self.owner, "thread-a", self.state()["revision"]
        )
        self.channel = Channel()

    def state(self):
        return self.store.snapshot("alpha")

    def connect(self, **changes):
        options = dict(
            store=self.store,
            project_id="alpha",
            owner=self.owner,
            connection_id="epoch-a",
            index_sha256="a" * 64,
            thread_id="thread-a",
            channel=self.channel,
            verify_binding=lambda: True,
            admit_action=lambda action: True,
        )
        options.update(changes)
        controller = self._connection_factory(**options)
        self.addCleanup(controller.close)
        return controller

    def question(self, native_id=7, method="item/tool/requestUserInput"):
        return {
            "id": native_id,
            "method": method,
            "params": {
                "threadId": "thread-a",
                "turnId": "turn-a",
                "itemId": "item-a",
                "questions": [{"id": "q", "question": "Choose?"}],
            },
        }

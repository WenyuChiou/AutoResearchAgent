"""Durable observations of an injected byte channel, never native admission.

Valid read bytes are saved before returning, including invalid UTF-8/JSON. An
I/O-to-commit crash can still lose observed bytes: unmatched intents stay unknown.
Receipts observe the injected channel, not authenticated delivery or execution.
An oversized invalid read retains a marked prefix; its SHA covers that prefix.
Write results report one observed count, not full-frame delivery. Capture flags
refer to read-return bytes; write-result capture_complete is not applicable.
"""

import json
import math
import time

from stage1_deliverable.common import canonical, sha
from .store import JournalError, _require


class RecordingError(JournalError):
    """Recording failed or the connection cannot safely perform more I/O."""


def records(store, project_id, connection_id, *, after_seq=0, limit=100):
    """Read detached evidence, including old epochs, without reopening a channel."""
    _require(type(after_seq) is int and 0 <= after_seq < 2**63, "invalid cursor")
    _require(type(limit) is int and 1 <= limit <= 100, "invalid record limit")
    with store._lock:
        store._read(project_id)
        return [
            dict(json.loads(row["metadata"]), data=row["data"])
            for row in store.db.execute(
                "SELECT metadata,data FROM native_byte_records WHERE project=? "
                "AND connection=? AND seq>? ORDER BY seq LIMIT ?",
                (project_id, connection_id, after_seq, limit),
            )
        ]


class RecordingChannel:
    """Wrap deadline-aware read/write and nonblocking close; never launch or retry.

    The supplied ProjectStore owns private-path checks, SQLite durability and the
    exclusive process-held owner. Its lock spans each I/O so local owner release
    cannot race dispatch. Blocking/deadline compliance is the injected channel's
    responsibility. Each connection ID is single-use within this database.
    """

    def __init__(
        self,
        channel,
        *,
        store,
        project_id,
        owner,
        connection_id,
        max_chunk_bytes=1024 * 1024,
        max_records=20000,
        max_total_bytes=64 * 1024 * 1024,
    ):
        _require(
            isinstance(connection_id, str) and 0 < len(connection_id) <= 128,
            "connection ID required",
        )
        _require(
            all(
                type(n) is int and n > 0
                for n in (max_chunk_bytes, max_records, max_total_bytes)
            ),
            "invalid bounds",
        )
        _require(max_records >= 3, "open and close recording slots required")
        _require(
            all(
                callable(getattr(channel, name, None))
                for name in ("read", "write", "close")
            ),
            "binary channel required",
        )
        self.channel, self.store = channel, store
        self.project_id, self.owner, self.connection_id = (
            project_id,
            owner,
            connection_id,
        )
        self.max_chunk_bytes, self.max_records = max_chunk_bytes, max_records
        self.max_total_bytes = max_total_bytes
        self.failure, self.closed = None, False
        with store._edit(
            project_id,
            owner,
            None,
            "byte-channel-bound",
            {"connection_id": connection_id},
        ) as state:
            store.db.execute(
                "CREATE TABLE IF NOT EXISTS native_byte_records "
                "(project TEXT NOT NULL, connection TEXT NOT NULL, seq INTEGER NOT NULL, "
                "metadata TEXT NOT NULL, data BLOB, PRIMARY KEY(connection,seq))"
            )
            for action in ("UPDATE", "DELETE"):
                store.db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS byte_no_{action} "
                    f"BEFORE {action} ON native_byte_records BEGIN "
                    "SELECT RAISE(ABORT, 'immutable byte record'); END"
                )
            _require(
                store.db.execute(
                    "SELECT 1 FROM native_byte_records WHERE connection=?",
                    (connection_id,),
                ).fetchone()
                is None,
                "connection ID already recorded; reattachment forbidden",
            )
            channels = state.setdefault("byte_channels", {})
            _require(len(channels) < 128, "connection history bound exceeded")
            channels[connection_id] = dict(
                owner=owner,
                index_sha256=state["index_sha256"],
                seq=0,
                bytes=0,
                pending={},
                fault=None,
            )
            self._append(state, "open", "result", outcome="bound")

    def _context(self, state):
        channel = state["byte_channels"][self.connection_id]
        _require(
            channel["owner"] == self.owner
            and channel["index_sha256"] == state["index_sha256"],
            "recording owner/index differs",
        )
        return channel

    def _append(self, state, operation, phase, *, data=None, **details):
        channel = self._context(state)
        length = len(data) if data is not None else 0
        _require(
            channel["seq"] < self.max_records
            and channel["bytes"] + length <= self.max_total_bytes,
            "record budget exceeded",
        )
        channel["seq"] += 1
        channel["bytes"] += length
        record = dict(
            project_id=self.project_id,
            index_sha256=state["index_sha256"],
            thread_id=state["thread_id"],
            connection_id=self.connection_id,
            owner=self.owner,
            seq=channel["seq"],
            operation=operation,
            phase=phase,
            time_ns=time.time_ns(),
            sha256=sha(data) if data is not None else None,
            **details,
        )
        self.store.db.execute(
            "INSERT INTO native_byte_records VALUES(?,?,?,?,?)",
            (
                self.project_id,
                self.connection_id,
                channel["seq"],
                canonical(record).decode(),
                data,
            ),
        )
        return channel["seq"]

    def _begin(self, operation, *, data=None, size=None, timeout=None):
        with self.store._edit(
            self.project_id,
            self.owner,
            None,
            "byte-io-intent",
            dict(connection_id=self.connection_id, operation=operation),
        ) as state:
            channel = self._context(state)
            if operation != "close":
                _require(
                    not self.failure
                    and not self.closed
                    and not channel["fault"]
                    and not channel["pending"],
                    "recording connection unusable",
                )
            reserve = self.max_chunk_bytes if operation == "read" else len(data or b"")
            _require(
                channel["seq"] + (2 if operation == "close" else 4) <= self.max_records
                and channel["bytes"] + reserve <= self.max_total_bytes,
                "insufficient intent/result recording budget",
            )
            seq = self._append(
                state, operation, "intent", data=data, size=size, timeout=timeout
            )
            channel["pending"][str(seq)] = operation
        return seq

    def _finish(self, operation, intent_seq, *, fault=None, **details):
        try:
            with self.store._edit(
                self.project_id,
                self.owner,
                None,
                "byte-io-result",
                dict(connection_id=self.connection_id, intent_seq=intent_seq),
            ) as state:
                channel = self._context(state)
                self._append(
                    state, operation, "result", intent_seq=intent_seq, **details
                )
                if intent_seq is not None:
                    channel["pending"].pop(str(intent_seq))
                if fault:
                    channel["fault"] = fault
        except BaseException as error:
            self.failure = "result persistence failed; outcome unknown"
            raise RecordingError(self.failure) from error

    def _io(self, operation, argument, timeout):
        _require(
            type(timeout) in (int, float) and math.isfinite(timeout) and timeout >= 0,
            "finite nonnegative timeout required",
        )
        deadline = time.monotonic() + timeout
        with self.store._lock:
            try:
                seq = self._begin(
                    operation,
                    data=argument if operation == "write" else None,
                    size=argument if operation == "read" else None,
                    timeout=timeout,
                )
            except BaseException as error:
                self.failure = "intent persistence/admission failed; no I/O attempted"
                raise RecordingError(self.failure) from error
            try:
                value = getattr(self.channel, operation)(
                    argument, max(0, deadline - time.monotonic())
                )
            except BaseException as error:
                idle = operation == "read" and isinstance(error, TimeoutError)
                self.failure = None if idle else "channel failed; outcome unknown"
                self._finish(
                    operation,
                    seq,
                    outcome="timeout" if isinstance(error, TimeoutError) else "error",
                    exception_type=type(error).__name__,
                    fault=self.failure,
                )
                raise
            if operation == "read":
                valid = type(value) is bytes and len(value) <= argument
                data = value[: self.max_chunk_bytes] if type(value) is bytes else None
                count = len(value) if type(value) is bytes else None
                outcome = (
                    "eof"
                    if valid and not value
                    else "returned"
                    if valid
                    else "invalid-return"
                )
            else:
                valid = type(value) is int and 0 < value <= len(argument)
                data, count = None, value if type(value) is int else None
                outcome = "returned" if valid else "invalid-return"
            self.failure = None if valid and outcome != "eof" else outcome
            self._finish(
                operation,
                seq,
                outcome=outcome,
                data=data,
                count=count,
                returned_type=type(value).__name__,
                fault=self.failure,
                capture_complete=(data is not None and count == len(data))
                if operation == "read"
                else None,
            )
            if not valid:
                raise RecordingError("invalid channel return; connection unusable")
            return value

    def read(self, size, timeout):
        _require(
            type(size) is int and 0 < size <= self.max_chunk_bytes, "invalid read bound"
        )
        return self._io("read", size, timeout)

    def write(self, data, timeout):
        _require(
            type(data) is bytes and 0 < len(data) <= self.max_chunk_bytes,
            "invalid write bytes",
        )
        return self._io("write", data, timeout)

    def close(self):
        """Always attempt one underlying close, even when evidence storage fails."""
        with self.store._lock:
            if self.closed:
                return
            self.closed = True
            intent, errors, returned_type = None, [], None
            try:
                intent = self._begin("close")
            except BaseException as error:
                errors.append(error)
            try:
                result = self.channel.close()
                returned_type = type(result).__name__
                if result is not None:
                    errors.append(RecordingError("invalid close return"))
            except BaseException as error:
                errors.append(error)
            self.failure = "closed; unsettled outcomes remain unknown"
            try:
                self._finish(
                    "close",
                    intent,
                    outcome="close-error" if errors else "closed",
                    fault=self.failure,
                    returned_type=returned_type,
                    exception_types=[type(e).__name__ for e in errors],
                )
            except BaseException as error:
                errors.append(error)
            if errors:
                raise RecordingError(self.failure) from errors[-1]

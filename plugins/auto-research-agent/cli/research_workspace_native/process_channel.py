"""Owned bounded local child channel; observations are not process attestation.

Only explicit server-owned spawn intents can launch fixed app-server stdio argv.
Tests use real local fake children, never Codex or a model. Windows tree cleanup
remains unverified and grants no research, import, resume or model authority.
"""

from copy import deepcopy
import math
import os
import queue
import subprocess
import threading
import time

from stage1_deliverable.common import canonical, sha
from .codex_probe import _path, _file_sha, _cleanup
from .frame_journal import FrameJournal
from .store import _require
from .process_deadline import Deadline


class OwnedProcessChannel:
    def __init__(
        self,
        *,
        store,
        project_id,
        owner,
        connection_id,
        index_sha256,
        input_version,
        intent_key,
        verify_binding,
        admit_spawn,
        lifetime=60,
        max_stream_bytes=1048576,
    ):
        _require(isinstance(store, FrameJournal), "frame journal required")
        _require(
            callable(verify_binding) and callable(admit_spawn), "server gates required"
        )
        _require(
            type(lifetime) in (int, float)
            and math.isfinite(lifetime)
            and 0 < lifetime <= 600,
            "bounded process lifetime required",
        )
        _require(
            type(max_stream_bytes) is int and 1 <= max_stream_bytes <= 1048576,
            "bounded stream bytes required",
        )
        _require(
            isinstance(connection_id, str) and 0 < len(connection_id) <= 128,
            "connection ID required",
        )
        self.store, self.project_id, self.owner = store, project_id, owner
        self.connection_id, self.index_sha256 = connection_id, index_sha256
        self.input_version, self.intent_key = input_version, intent_key
        self.verify_binding, self.admit_spawn = verify_binding, admit_spawn
        self.deadline = time.monotonic() + lifetime
        self.max_stream_bytes = max_stream_bytes
        self.process, self.closed, self.failure = None, False, None
        self._lock, self._writes, self._reads = (
            threading.RLock(),
            threading.Lock(),
            threading.Lock(),
        )
        self._stdout = queue.Queue(maxsize=8)
        self._buffer, self._cleanup_result = b"", None
        self._cleanup_done = threading.Event()
        self._workers = []
        with store._lock:
            state = self._context()
            intent = state["intents"].get(intent_key, {})
            _require(
                intent.get("method") == "app-server/spawn"
                and intent.get("status") == "intent-recorded"
                and intent.get("request_identity") is None,
                "explicit unsent spawn intent required",
            )
            self.payload = deepcopy(intent["payload"])
            _require(
                set(self.payload)
                == {"executable", "executable_sha256", "cwd", "input_version"}
                and self.payload["input_version"] == input_version
                and isinstance(input_version, str)
                and len(input_version) == 64
                and all(c in "0123456789abcdef" for c in input_version),
                "spawn binding differs",
            )
            self.executable = _path(self.payload["executable"])
            self.cwd = _path(self.payload["cwd"], directory=True)
            _require(
                not state.get("process_channels")
                and not state.get("bootstrap")
                and not any(
                    not v.get("fault") for v in state.get("byte_channels", {}).values()
                ),
                "existing or historical process forbids implicit relaunch",
            )
            self._admit()
            admitted = self.store.transition_intent(
                project_id,
                owner,
                intent_key,
                "dispatching",
                {"spawn_admission": "caller-permitted"},
                state["revision"],
            )
            _require(admitted["status"] == "dispatching", "spawn transition refused")
            with store._edit(
                project_id, owner, None, "process-spawn-intent", {}
            ) as state:
                state["process_channels"] = {
                    connection_id: dict(
                        owner=owner,
                        input_version=input_version,
                        intent_key=intent_key,
                        payload_sha256=sha(canonical(self.payload)),
                        events=0,
                        authenticated_process=False,
                        process_tree_containment_verified=False,
                    )
                }
        try:
            with store._lock:
                self._admit()
                options = dict(
                    cwd=str(self.cwd),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
                if os.name == "nt":
                    options["creationflags"] = (
                        subprocess.CREATE_NO_WINDOW
                        | subprocess.CREATE_NEW_PROCESS_GROUP
                    )
                else:
                    options["start_new_session"] = True
                self.process = subprocess.Popen(
                    [str(self.executable), "app-server", "--stdio"], **options
                )

            def lease():
                if not self._cleanup_done.wait(
                    max(0, self.deadline - time.monotonic())
                ):
                    self._fault(TimeoutError("owned lifetime expired"))

            worker = threading.Thread(target=lease, daemon=True)
            self._workers.append(worker)
            worker.start()
            startup = Deadline(
                min(30, max(0, self.deadline - time.monotonic())), self.deadline
            )
            with startup.database(store):
                self._observe("process-started", deadline=startup, pid=self.process.pid)
                state = self.store.snapshot(project_id)
                startup.refresh(store)
                self.store.transition_intent(
                    project_id,
                    owner,
                    intent_key,
                    "completed",
                    {
                        "owned_pid_observed": self.process.pid,
                        "authenticated_process": False,
                    },
                    state["revision"],
                )
                startup.check()
            for name in ("stdout", "stderr"):
                worker = threading.Thread(
                    target=self._read_worker, args=(name,), daemon=True
                )
                self._workers.append(worker)
                worker.start()

        except BaseException as error:
            self._fault(error)
            raise ValueError(
                "owned process construction failed; never relaunch automatically"
            ) from error

    def _context(self):
        state = self.store.snapshot(self.project_id)
        _require(
            state["index_sha256"] == self.index_sha256
            and isinstance(state.get("owner"), dict)
            and state["owner"].get("token") == self.owner
            and self.store._owners.get(self.project_id, (None,))[0] == self.owner,
            "process owner or index expired",
        )
        return state

    def _remaining(self, timeout):
        _require(
            type(timeout) in (int, float)
            and math.isfinite(timeout)
            and 0 <= timeout <= 30,
            "bounded I/O timeout required",
        )
        remaining = min(timeout, self.deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("owned process deadline expired")
        return remaining

    def _binding(self, deadline=None, *, passive=False):
        state = self._context()
        _require(not self.closed and not self.failure, "process stopped")
        intent = state["intents"].get(self.intent_key, {})
        _require(
            canonical(intent.get("payload")) == canonical(self.payload),
            "saved payload differs",
        )

        def source():
            return (
                self.verify_binding() is True
                and _path(str(self.executable)) == self.executable
                and _path(str(self.cwd), directory=True) == self.cwd
                and _file_sha(self.executable) == self.payload["executable_sha256"]
            )

        if not passive:
            if deadline is not None:
                deadline.guard(source)
            else:
                _require(source(), "physical source binding differs")
        self._remaining(30)

    def _admit(self):
        self._binding()
        _require(
            self.admit_spawn(
                dict(
                    project_id=self.project_id,
                    index_sha256=self.index_sha256,
                    input_version=self.input_version,
                    connection_id=self.connection_id,
                    intent_key=self.intent_key,
                    payload_sha256=sha(canonical(self.payload)),
                    argv=[str(self.executable), "app-server", "--stdio"],
                )
            )
            is True,
            "literal version-bound spawn admission required",
        )
        self._binding()

    def _observe(self, event, *, deadline=None, **payload):
        if deadline is not None:
            deadline.refresh(self.store)
        with self.store._edit(
            self.project_id, self.owner, None, "owned-process-" + event, payload
        ) as state:
            row = state["process_channels"][self.connection_id]
            _require(
                row["owner"] == self.owner
                and row["input_version"] == self.input_version
                and row["payload_sha256"] == sha(canonical(self.payload))
                and row["events"] < 128,
                "process observation binding or bound differs",
            )
            row["events"] += 1
            row["last_event"] = event
        if deadline is not None:
            deadline.check()

    def _observe_now(self, event, **payload):
        if not self.store._lock.acquire(blocking=False):
            return False
        try:
            self._observe(event, **payload)
            return True
        except BaseException:
            return False
        finally:
            self.store._lock.release()

    def _read_worker(self, name):
        total = 0
        try:
            stream = getattr(self.process, name)
            while not self.closed:
                raw = stream.read(4096)
                total += len(raw)
                if total > self.max_stream_bytes:
                    raise ValueError(name + " total byte bound exceeded")
                if name == "stderr" and raw:
                    self._observe(
                        "stderr",
                        byte_count=len(raw),
                        sha256=sha(raw),
                        raw_hex=raw.hex(),
                    )
                if name == "stdout":
                    # Retry only enqueueing this same retained chunk. Source
                    # admission may delay the consumer; no extra OS read occurs.
                    # Short waits make close responsive within the total/lease cap.
                    budget = Deadline(30, self.deadline)
                    while not self.closed:
                        remaining = budget.left()
                        if not remaining:
                            raise queue.Full("stdout backpressure deadline expired")
                        try:
                            self._stdout.put(raw, timeout=min(0.1, remaining))
                            break
                        except queue.Full:
                            continue
                    if self.closed:
                        return
                if not raw:
                    self._observe(name + "-eof", byte_count=total)
                    break
        except BaseException as error:
            if not self.closed:
                self._fault(error)

    def read(self, size, timeout):
        _require(type(size) is int and 0 < size <= 262144, "bounded read size required")
        deadline = Deadline(timeout, self.deadline)
        with deadline.hold(self._reads), deadline.database(self.store):
            try:
                self._binding(deadline, passive=timeout == 0)
            except BaseException as error:
                self._fault(error)
                raise
            try:
                if not self._buffer:
                    self._buffer = (
                        self._stdout.get_nowait()
                        if timeout == 0
                        else self._stdout.get(timeout=deadline.left())
                    )
                raw = self._buffer[:size]
                self._observe(
                    "read",
                    deadline=deadline if timeout else None,
                    byte_count=len(raw),
                    sha256=sha(raw),
                )
                if timeout:
                    deadline.check()
                self._buffer = self._buffer[size:]
                return raw
            except queue.Empty as error:
                raise TimeoutError("owned read timeout") from error
            except BaseException as error:
                self._fault(error)
                raise ValueError("read bytes retained; observation unknown") from error

    def write(self, data, timeout):
        _require(
            isinstance(data, bytes) and 0 < len(data) <= 262144,
            "bounded write bytes required",
        )
        deadline = Deadline(timeout, self.deadline)
        with deadline.hold(self._writes), deadline.database(self.store):
            try:
                self._binding(deadline)
            except BaseException as error:
                self._fault(error)
                raise
            self._observe(
                "write-intent",
                deadline=deadline,
                byte_count=len(data),
                sha256=sha(data),
            )
            self._binding(deadline)
            deadline.check()
            completed = queue.Queue(maxsize=1)

            def writer():
                try:
                    if self.closed or self.failure or not deadline.left():
                        raise TimeoutError("worker write expired before dispatch")
                    count = self.process.stdin.write(data)
                    completed.put((count, None))
                    if not deadline.left():
                        self._observe_now(
                            "late-write-count", count=count, outcome="unknown"
                        )
                except BaseException as error:
                    completed.put((None, error))

            worker = threading.Thread(target=writer, daemon=True)
            self._workers.append(worker)
            worker.start()
            try:
                count, error = completed.get(timeout=deadline.left())
                if error is not None:
                    raise error
                _require(
                    type(count) is int and 0 < count <= len(data), "write count differs"
                )
                self._observe(
                    "write-returned",
                    deadline=deadline,
                    count=count,
                    partial=count < len(data),
                )
                deadline.check()
                return count
            except BaseException as error:
                self._fault(error)
                raise ValueError("write outcome unknown; never resend") from error

    def _fault(self, error):
        with self._lock:
            first = self.failure is None
            if first:
                self.failure = type(error).__name__
        self.close()
        if first:

            def record_fault():
                if not self._observe_now(
                    "fault", exception_type=type(error).__name__, outcome="unknown"
                ):
                    self.failure += "; fault persistence unobserved"

            worker = threading.Thread(target=record_fault, daemon=True)
            self._workers.append(worker)
            worker.start()

    def close(self):
        """Return without waiting; separately call reap to observe owned cleanup."""
        with self._lock:
            if self.closed:
                return
            self.closed = True
            requested_at = time.monotonic()

            def cleanup():
                try:
                    result = (
                        _cleanup(self.process)
                        if self.process is not None
                        else {"not_started": True}
                    )
                    self._cleanup_result = result
                    self._cleanup_result["journal_cleanup_observed"] = False
                    try:
                        self._observe(
                            "close-request-observed",
                            requested_monotonic=requested_at,
                            recorded_after_physical_cleanup=True,
                        )
                        self._observe("cleanup", **result)
                        self._cleanup_result["journal_cleanup_observed"] = True
                    except BaseException:
                        self.failure = (
                            self.failure or "closed"
                        ) + "; cleanup persistence unobserved"
                    if self.process is not None:
                        self.process.stderr.close()
                finally:
                    self._cleanup_done.set()

            worker = threading.Thread(target=cleanup, daemon=True)
            self._workers.append(worker)
            worker.start()

    def reap(self, timeout=10):
        _require(
            type(timeout) in (int, float)
            and math.isfinite(timeout)
            and 0 < timeout <= 10,
            "bounded reap timeout required",
        )
        _require(self.closed, "close intent required before reap")
        if not self._cleanup_done.wait(timeout):
            raise TimeoutError("owned cleanup unobserved")
        _require(self._cleanup_result is not None, "cleanup result absent")
        return deepcopy(self._cleanup_result)

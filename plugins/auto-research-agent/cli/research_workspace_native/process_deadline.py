"""Bounded lock/database waits and read-only guard results; no dispatch."""

from contextlib import contextmanager
import contextvars
import math
import queue
import sqlite3
import threading
import time

from stage1_retrieval import verification_clock

_GUARDS = threading.BoundedSemaphore(4)


class SessionLeaseExpired(TimeoutError):
    """A trusted permit reports expiry; generic timeouts retain failure status."""


class Deadline:
    def __init__(self, timeout, lease):
        if (
            type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or not 0 <= timeout <= 30
        ):
            raise ValueError("bounded I/O timeout required")
        if time.monotonic() >= lease:
            raise TimeoutError("owned process lifetime expired")
        # The I/O timeout is a business bound: metered local verification done
        # after construction extends it. The meter object is captured here, so
        # threads that did not inherit the context (process writer/reader
        # threads) read the same remaining time. The owned process lease stays
        # a hard raw-clock bound.
        self.meter = verification_clock.current()
        self.base = 0.0 if self.meter is None else self.meter.excluded()
        self.until, self.lease = time.monotonic() + timeout, lease

    def left(self):
        now = time.monotonic()
        extra = 0.0 if self.meter is None else self.meter.excluded() - self.base
        return max(0, min(self.until + extra - now, self.lease - now))

    def check(self):
        if not self.left():
            raise TimeoutError("operation deadline expired")

    @contextmanager
    def hold(self, lock):
        if not lock.acquire(timeout=self.left()):
            raise TimeoutError("owned lock deadline expired")
        try:
            yield
        finally:
            lock.release()

    @contextmanager
    def database(self, store):
        with self.hold(store._lock):
            previous = store.db.execute("PRAGMA busy_timeout").fetchone()[0]
            # Busy handlers count sleep, not elapsed time. WAL blocking locks on
            # some platforms can outlast a short budget, so refuse contention
            # immediately; never retry an operation with an unknown outcome.
            store.db.execute("PRAGMA busy_timeout=0")
            try:
                yield
            except sqlite3.OperationalError as error:
                if "locked" in str(error) or not self.left():
                    raise TimeoutError(
                        "database deadline expired; outcome unobserved"
                    ) from error
                raise
            finally:
                store.db.execute("PRAGMA busy_timeout=" + str(previous))

    def refresh(self, store):
        self.check()
        store.db.execute("PRAGMA busy_timeout=0")

    def guard(self, verify):
        """Read-only callback may finish late; late success never grants I/O.

        It must not access the caller-held journal, mutate state, or dispatch.
        At most four guard workers can exist; Python cannot forcibly cancel one.
        """
        self.check()
        if not _GUARDS.acquire(timeout=self.left()):
            raise TimeoutError("source guard worker bound exceeded")
        done = queue.Queue(maxsize=1)

        def run():
            try:
                try:
                    done.put((verify(), None))
                except BaseException as error:
                    done.put((None, error))
            finally:
                _GUARDS.release()

        # The guard thread shares this context's verification meter, so its
        # local passes extend left(); recheck it after each wait.
        context = contextvars.copy_context()
        threading.Thread(target=context.run, args=(run,), daemon=True).start()
        while True:
            try:
                result, error = done.get(timeout=self.left())
                break
            except queue.Empty as empty:
                if not self.left():
                    raise TimeoutError("source guard deadline expired") from empty
        self.check()
        if error is not None:
            raise error
        if result is not True:
            raise ValueError("literal source guard required")

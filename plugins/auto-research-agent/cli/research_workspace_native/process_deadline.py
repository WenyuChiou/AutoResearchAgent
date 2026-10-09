"""Bounded lock/database waits and read-only guard results; no dispatch."""

from contextlib import contextmanager
import math
import queue
import sqlite3
import threading
import time

_GUARDS = threading.BoundedSemaphore(4)


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
        self.until = min(time.monotonic() + timeout, lease)

    def left(self):
        return max(0, self.until - time.monotonic())

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
            store.db.execute("PRAGMA busy_timeout=" + str(int(self.left() * 1000)))
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
        store.db.execute("PRAGMA busy_timeout=" + str(int(self.left() * 1000)))

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

        threading.Thread(target=run, daemon=True).start()
        try:
            result, error = done.get(timeout=self.left())
        except queue.Empty as error:
            raise TimeoutError("source guard deadline expired") from error
        self.check()
        if error is not None:
            raise error
        if result is not True:
            raise ValueError("literal source guard required")

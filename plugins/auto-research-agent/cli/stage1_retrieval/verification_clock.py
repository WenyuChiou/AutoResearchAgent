"""Keep bounded local integrity verification out of business deadlines.

A business deadline (the 30 second bootstrap probe, a handshake step) bounds
external actions and I/O. Pure local integrity passes -- reading and hashing
pinned files that the caller already knows -- are measured separately while a
``Meter`` is active in the current context. Business clocks then subtract the
measured time, but never more than the meter's own allowance, so a stuck or
oversized verification still exhausts the business deadline and a completed
pass that exceeded the allowance fails with its own reason.

Outside an active meter every function here equals the raw clock, so code paths
that do not opt in keep their exact previous timing. Hard limits (permit
expiry, owned process lifetime) must keep using the raw clock.

Allowance constants (2026-11-27 measurements on the Windows trial machine):
warm runtime passes took 4.3-4.9 s for 13,696 files (about 0.33 ms per file);
a cold 72,436 file prewarm took 191.7 s (about 2.6 ms per file); the earlier
analysis used 3.4 ms per file. ``PER_FILE_SECONDS`` = 5 ms leaves about 1.5x
over that figure and about 2x over the cold prewarm. Cold plugin-tree outliers
(23-28 s for about 1,515 files) exceed 5 ms per file, but the allowance is
cumulative across a scope's passes, so the slack of the warm runtime passes
absorbs them.

``MAX_PASSES`` = 64: observed 17-26 passes in the bootstrap worker (two runs
on a copied data root), 24 in the planned-query worker, and 21 in a real
codex.exe handshake up to account/read (thread/start not sent).

``MAX_SECONDS`` = 600 caps one scope's whole allowance. Without it the file
formula alone allows 10 + 64 x (1 + 0.005 x 13,696) = about 4,457 s (74 min)
for the 13,696-file runtime. The slowest observed scope was 202 s of
verification (bootstrap worker while the machine also ran two test suites),
so 600 s is about 3x that; worst wall time is the business budget + 600 s.

Do not run verification and an external action in parallel under one meter:
while any verification span is open the business clock is paused for every
thread sharing the meter (union time).
"""

from contextlib import contextmanager
import contextvars
import threading
import time

BASE_SECONDS = 10.0
PASS_SECONDS = 1.0
PER_FILE_SECONDS = 0.005
MAX_PASSES = 64
MAX_SECONDS = 600.0
BUDGET_CODE = "local-verification-budget-exceeded"

_METER = contextvars.ContextVar("local_verification_meter", default=None)


class LocalVerificationBudgetExceeded(RuntimeError):
    """Local verification itself overran its separate, file-count budget.

    Deliberately not a TimeoutError: read paths treat TimeoutError as an idle
    read (transport.poll, recording) and HTTP maps it to 408, which would hide
    this distinct reason.
    """

    code = BUDGET_CODE


class Meter:
    """Union wall time of local verification spans in one business scope."""

    def __init__(
        self,
        *,
        base_seconds=None,
        pass_seconds=None,
        per_file_seconds=None,
        max_passes=None,
        max_seconds=None,
    ):
        # Module constants are read at construction so one scope keeps one budget.
        self.base_seconds = BASE_SECONDS if base_seconds is None else base_seconds
        self.pass_seconds = PASS_SECONDS if pass_seconds is None else pass_seconds
        self.per_file_seconds = (
            PER_FILE_SECONDS if per_file_seconds is None else per_file_seconds
        )
        self.max_passes = MAX_PASSES if max_passes is None else max_passes
        self.max_seconds = MAX_SECONDS if max_seconds is None else max_seconds
        self._lock = threading.Lock()
        self._closed, self._passes, self._files = 0.0, 0, 0
        self._active, self._since = 0, None

    def _allowance(self):
        return min(
            self.max_seconds,
            self.base_seconds
            + self.pass_seconds * self._passes
            + self.per_file_seconds * self._files,
        )

    def _total(self, now):
        return self._closed + (now - self._since if self._active else 0.0)

    def excluded(self):
        """Seconds a business clock may skip: measured, capped by allowance."""
        with self._lock:
            return min(self._total(time.monotonic()), self._allowance())

    def snapshot(self):
        with self._lock:
            return dict(
                seconds=self._total(time.monotonic()),
                passes=self._passes,
                files=self._files,
                allowance=self._allowance(),
            )

    def _begin(self, files):
        with self._lock:
            if self._passes >= self.max_passes:
                raise LocalVerificationBudgetExceeded(
                    BUDGET_CODE + ": pass bound exceeded"
                )
            self._passes += 1
            self._files += files
            if not self._active:
                self._since = time.monotonic()
            self._active += 1

    def _end(self):
        with self._lock:
            self._active -= 1
            if not self._active:
                self._closed += time.monotonic() - self._since
                self._since = None
            return self._total(time.monotonic()) > self._allowance()


@contextmanager
def metering(meter):
    """Activate ``meter`` for this context; helper threads must copy context."""
    if not isinstance(meter, Meter):
        raise TypeError("verification meter required")
    token = _METER.set(meter)
    try:
        yield meter
    finally:
        _METER.reset(token)


def current():
    return _METER.get()


@contextmanager
def local_verification(files):
    """Mark one pure local read/hash pass over ``files`` pinned files.

    Use only around code that reads and compares local bytes or metadata: no
    callbacks, subprocesses, network or durable writes. Without an active meter
    this is a no-op. A failing pass keeps its own error; a successful pass that
    pushed the scope past its allowance fails with ``BUDGET_CODE``.
    """
    if type(files) is not int or files < 0:
        raise ValueError("verification file count required")
    meter = _METER.get()
    if meter is None:
        yield
        return
    meter._begin(files)
    try:
        yield
    except BaseException:
        meter._end()
        raise
    if meter._end():
        raise LocalVerificationBudgetExceeded(BUDGET_CODE)


def excluded():
    """Seconds the active meter lets a business clock skip (0 without one)."""
    meter = _METER.get()
    return 0.0 if meter is None else meter.excluded()

"""Once-owned DNS child with a bounded wait and explicit cleanup observations.

This resolves names only. It grants no source/model authority, authenticates no
runtime and never connects HTTP. The parent must verify the supplied binding
and admit acquisition separately. Cleanup has a separate short allowance; an
unreaped or failed child poisons this resolver rather than being reused.
"""

from copy import deepcopy
import ipaddress
import json
import math
import multiprocessing
import re
import socket
import threading
import time

from stage1_deliverable.common import canonical

from .bounded_public_source import TypedBoundedResolver
from .session_api import SessionApiError, _check, _hash


def _dns_child(host, port, sender):
    # No URL, credentials, proxy, HTTP or fallback is accepted by this child.
    try:
        rows = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = tuple(dict.fromkeys(row[4][0] for row in rows))
        if not 1 <= len(addresses) <= 32:
            raise ValueError("resolver-address-bound")
        sender.send_bytes(canonical(dict(addresses=addresses)))
    except BaseException as error:
        sender.send_bytes(canonical(dict(error=type(error).__name__)))
    finally:
        sender.close()


def _public_addresses(values):
    _check(
        type(values) in (list, tuple) and 1 <= len(values) <= 32,
        "source-resolver-result-invalid",
    )
    addresses = []
    for value in values:
        _check(
            type(value) is str and "%" not in value, "source-resolver-result-invalid"
        )
        try:
            address = ipaddress.ip_address(value)
        except ValueError as error:
            raise SessionApiError("source-resolver-result-invalid") from error
        _check(
            address.is_global and not address.is_multicast,
            "source-resolver-private-address",
        )
        addresses.append(str(address))
    return tuple(dict.fromkeys(addresses))


class ProcessBoundedResolver(TypedBoundedResolver):
    def __init__(
        self,
        binding_sha256,
        *,
        cleanup_seconds=1.0,
        _context=None,
        _child_target=None,
        _monotonic=None,
    ):
        _check(_hash(binding_sha256), "source-resolver-binding-required")
        _check(
            type(cleanup_seconds) in (int, float)
            and math.isfinite(cleanup_seconds)
            and 0 < cleanup_seconds <= 2,
            "source-resolver-cleanup-bound-invalid",
        )
        self._binding = binding_sha256
        self._cleanup_seconds = cleanup_seconds
        self._context = _context or multiprocessing.get_context("spawn")
        # Private injection is solely for deterministic lifecycle tests.
        self._target = _child_target or _dns_child
        self._clock = _monotonic or time.monotonic
        self._lock = threading.Lock()
        self._failed = False
        self._observations = []

    @property
    def binding_sha256(self):
        return self._binding

    @property
    def observations(self):
        return deepcopy(self._observations)

    def resolve(self, host, port, absolute_monotonic_deadline):
        _check(
            type(host) is str
            and 0 < len(host) <= 253
            and "%" not in host
            and type(port) is int
            and port in (80, 443),
            "source-resolver-target-invalid",
        )
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
            _check(
                re.fullmatch(r"[A-Za-z0-9.-]+", host) is not None
                and "." in host
                and all(
                    1 <= len(label) <= 63
                    and not label.startswith("-")
                    and not label.endswith("-")
                    for label in host.rstrip(".").split(".")
                ),
                "source-resolver-target-invalid",
            )
        _check(
            type(absolute_monotonic_deadline) in (int, float)
            and math.isfinite(absolute_monotonic_deadline),
            "source-resolver-deadline-invalid",
        )

        def remaining():
            seconds = absolute_monotonic_deadline - self._clock()
            if seconds <= 0:
                raise TimeoutError("source-resolver-deadline")
            return seconds

        _check(self._lock.acquire(timeout=remaining()), "source-resolver-lock-deadline")
        try:
            _check(not self._failed, "source-resolver-unusable")
            _check(
                len(self._observations) < 128, "source-resolver-operation-bound", 429
            )
            remaining()
            if literal is not None:
                return _public_addresses((str(literal),))
            row = dict(
                kind="BoundedSourceResolverObservation",
                host=host,
                port=port,
                binding_sha256=self._binding,
                deadline_monotonic=absolute_monotonic_deadline,
                status="start-intent",
                automatic_retry=False,
                http_execution=False,
            )
            self._observations.append(row)
            receiver = sender = child = None
            started = False
            result = None
            primary = None
            try:
                receiver, sender = self._context.Pipe(duplex=False)
                child = self._context.Process(
                    target=self._target, args=(host, port, sender)
                )
                remaining()
                child.start()
                started = True
                row.update(status="waiting", pid=child.pid)
                sender.close()
                # Wait for the only writer to exit before reading any frame.
                # poll alone proves readability, not a complete message; a live
                # child could otherwise leave recv_bytes waiting indefinitely.
                # The production child never creates or hands off descendants.
                child.join(remaining())
                remaining()
                _check(
                    not child.is_alive() and child.exitcode == 0,
                    "source-resolver-child-not-complete",
                )
                if not receiver.poll(remaining()):
                    raise TimeoutError("source-resolver-deadline")
                raw = receiver.recv_bytes(8192)
                remaining()
                data = json.loads(raw)
                _check(
                    type(data) is dict and set(data) == {"addresses"},
                    "source-resolver-child-failed",
                )
                result = _public_addresses(data["addresses"])
                row.update(status="result-observed", addresses=result)
            except BaseException as error:
                primary = error
                row.update(status="failed-or-unknown", error_type=type(error).__name__)
                self._failed = True
            finally:
                cleanup_errors = []
                if child is not None and (started or child.pid is not None):
                    try:
                        cleanup_end = self._clock() + self._cleanup_seconds
                        if child.is_alive():
                            child.terminate()
                            child.join(max(0, (cleanup_end - self._clock()) / 2))
                        if child.is_alive():
                            child.kill()
                            child.join(max(0, cleanup_end - self._clock()))
                        row.update(
                            reaped=not child.is_alive(), child_exit_code=child.exitcode
                        )
                        if child.is_alive():
                            cleanup_errors.append("child-still-alive")
                        else:
                            child.close()
                    except BaseException as error:
                        cleanup_errors.append(type(error).__name__)
                elif child is not None:
                    row["reaped"] = child.pid is None
                    try:
                        child.close()
                    except BaseException as error:
                        cleanup_errors.append(type(error).__name__)
                for pipe in (receiver, sender):
                    if pipe is not None:
                        try:
                            pipe.close()
                        except BaseException as error:
                            cleanup_errors.append(type(error).__name__)
                row["cleanup_errors"] = cleanup_errors
                if cleanup_errors or row.get("reaped") is not True:
                    self._failed = True
                    if primary is None:
                        primary = SessionApiError("source-resolver-cleanup-unobserved")
                        row.update(
                            status="failed-or-unknown",
                            error_type=type(primary).__name__,
                        )
            if primary is not None:
                raise primary
            row["status"] = "completed"
            return result
        finally:
            self._lock.release()

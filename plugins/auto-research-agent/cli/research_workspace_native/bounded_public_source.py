"""Direct bounded public acquisition; independent of SDK parser receipts.

The caller owns project permission, durable intent/reservations, runtime checks
and job recovery. A resolver binding is verified configuration, not process or
identity authentication. The required resolver must enforce the supplied
absolute monotonic deadline externally; no in-process getaddrinfo fallback is
provided. This module never imports or patches the SDK, follows proxy settings,
sends cookies/credentials, retries a request, or promotes bytes to paper evidence.
"""

from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import http.client
import io
import ipaddress
import math
import os
import socket
import ssl
import stat
import time
from urllib.parse import urljoin, urlsplit

from stage1_deliverable.common import canonical, private_output, reject_links, sha

from .project_source_permit import public_source_uri
from .session_api import SessionApiError, _check, _hash

MAX_BYTES = 16 * 1024 * 1024
ERROR_CODES = {
    "deadline-exceeded",
    "http-stream-mode-invalid",
    "resolver-address-invalid",
    "resolver-address-not-public",
    "connected-peer-differs",
    "tls-verification-required",
    "content-encoding-not-supported",
    "content-length-invalid",
    "response-too-large",
    "aggregate-bound-reached",
    "reader-byte-bound-invalid",
    "body-bound-reached",
    "url-ascii-required",
    "resolver-addresses-invalid",
    "redirect-location-missing",
    "incomplete-body",
    "artifact-write-unobserved",
}
REQUEST_FIELDS = {
    "kind",
    "schema_version",
    "request_id",
    "job_binding_sha256",
    "source_uri",
    "runtime_sha256",
    "resolver_sha256",
    "deadline_utc",
    "total_timeout_seconds",
    "io_timeout_seconds",
    "max_http_attempts",
    "max_response_bytes",
    "max_aggregate_bytes",
}


class TypedBoundedResolver(ABC):
    """Trusted server resolver contract; arbitrary callbacks are not attestation.

    ``resolve`` must return only numeric addresses before its supplied absolute
    deadline and contain/reap its worker. Unknown lifecycle must refuse reuse.
    The trusted bootstrap verifies the implementation/executable and supplies
    ``binding_sha256``; a matching digest alone does not prove those checks.
    """

    @property
    @abstractmethod
    def binding_sha256(self):
        raise NotImplementedError

    @abstractmethod
    def resolve(self, host, port, absolute_monotonic_deadline):
        raise NotImplementedError


class SourceTransportError(Exception):
    """Safe fixed error code, without target/header/exception values."""


def _utc():
    return datetime.now(timezone.utc)


def _stamp(value):
    _check(
        isinstance(value, datetime) and value.tzinfo is not None,
        "source-acquisition-clock-invalid",
    )
    return value.astimezone(timezone.utc).isoformat()


def _number(value, maximum):
    return type(value) in (int, float) and math.isfinite(value) and 0 < value <= maximum


def request_binding(value):
    """Validate an exact server request without DNS, filesystem or network work."""
    _check(
        type(value) is dict and set(value) == REQUEST_FIELDS,
        "source-acquisition-request-invalid",
        400,
    )
    _check(
        value["kind"] == "BoundedPublicSourceRequest"
        and value["schema_version"] == "1.0.0",
        "source-acquisition-request-version-invalid",
        400,
    )
    identifier = value["request_id"]
    _check(
        type(identifier) is str
        and 1 <= len(identifier) <= 128
        and identifier.isascii()
        and all(c.isalnum() or c in "._-" for c in identifier),
        "source-acquisition-request-id-invalid",
        400,
    )
    _check(
        all(
            _hash(value[key])
            for key in ("job_binding_sha256", "runtime_sha256", "resolver_sha256")
        ),
        "source-acquisition-request-hash-invalid",
        400,
    )
    public_source_uri(value["source_uri"])
    # HTTP request targets are sent exactly, never silently re-encoded.
    _check(value["source_uri"].isascii(), "source-acquisition-url-ascii-required", 400)
    _check(
        _number(value["total_timeout_seconds"], 300)
        and _number(value["io_timeout_seconds"], 300)
        and value["io_timeout_seconds"] <= value["total_timeout_seconds"],
        "source-acquisition-time-limits-invalid",
        400,
    )
    _check(
        type(value["max_http_attempts"]) is int
        and 1 <= value["max_http_attempts"] <= 16
        and all(
            type(value[key]) is int and 1 <= value[key] <= MAX_BYTES
            for key in ("max_response_bytes", "max_aggregate_bytes")
        ),
        "source-acquisition-byte-attempt-limits-invalid",
        400,
    )
    try:
        deadline = datetime.fromisoformat(value["deadline_utc"].replace("Z", "+00:00"))
        _stamp(deadline)
    except (AttributeError, TypeError, ValueError) as error:
        raise SessionApiError("source-acquisition-deadline-invalid", 400) from error
    return deepcopy(value)


class _Deadline:
    def __init__(self, request, utc, monotonic):
        self.utc, self.monotonic = utc, monotonic
        self.started = utc()
        declared = datetime.fromisoformat(
            request["deadline_utc"].replace("Z", "+00:00")
        )
        left = min(
            (declared - self.started).total_seconds(), request["total_timeout_seconds"]
        )
        _check(left > 0, "source-acquisition-deadline-expired", 408)
        self.end = monotonic() + left
        self.io_timeout = request["io_timeout_seconds"]

    def remaining(self):
        remaining = self.end - self.monotonic()
        if remaining <= 0:
            raise SourceTransportError("deadline-exceeded")
        return remaining

    def timeout(self):
        return min(self.io_timeout, self.remaining())


class _DeadlineReader(io.RawIOBase):
    """Check the total deadline on every recv, including slow HTTP headers."""

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    def readable(self):
        return True

    def readinto(self, buffer):
        self.channel.socket.settimeout(self.channel.deadline.timeout())
        result = self.channel.socket.recv_into(buffer)
        return result

    def close(self):
        if not self.closed:
            try:
                super().close()
            finally:
                self.channel.reader_closed()


class _DeadlineChannel:
    def __init__(self, sock, deadline):
        self.socket, self.deadline = sock, deadline
        self.readers, self.owner_closed, self.socket_closed = 0, False, False

    def makefile(self, mode):
        if mode != "rb":
            raise SourceTransportError("http-stream-mode-invalid")
        if self.owner_closed:
            raise SourceTransportError("http-stream-mode-invalid")
        self.readers += 1
        return io.BufferedReader(_DeadlineReader(self))

    def sendall(self, value):
        self.socket.settimeout(self.deadline.timeout())
        self.socket.sendall(value)
        self.deadline.remaining()

    def close(self):
        # HTTPConnection detaches a Connection:close response before reading it.
        # Like socket.makefile, the response's reader retains the socket lifetime.
        self.owner_closed = True
        self._close_if_unused()

    def reader_closed(self):
        self.readers -= 1
        self._close_if_unused()

    def _close_if_unused(self):
        if self.owner_closed and not self.readers and not self.socket_closed:
            self.socket_closed = True
            self.socket.close()


def _numeric(value):
    if type(value) is not str or "%" in value:
        raise SourceTransportError("resolver-address-invalid")
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        raise SourceTransportError("resolver-address-invalid") from error
    if not address.is_global or address.is_multicast:
        raise SourceTransportError("resolver-address-not-public")
    return address


class _PinnedConnection(http.client.HTTPConnection):
    """Connect to one checked numeric address; Host/SNI retain the origin."""

    def __init__(self, parsed, address, deadline):
        super().__init__(
            parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
        )
        self.parsed, self.address, self.deadline = parsed, address, deadline
        self.peer_address = None

    def connect(self):
        address = _numeric(self.address)
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        current = socket.socket(family, socket.SOCK_STREAM)
        try:
            current.settimeout(self.deadline.timeout())
            target = (
                (str(address), self.port, 0, 0)
                if address.version == 6
                else (str(address), self.port)
            )
            current.connect(target)
            self.deadline.remaining()
            if ipaddress.ip_address(current.getpeername()[0]) != address:
                raise SourceTransportError("connected-peer-differs")
            if self.parsed.scheme == "https":
                context = ssl.create_default_context()
                if (
                    not context.check_hostname
                    or context.verify_mode != ssl.CERT_REQUIRED
                ):
                    raise SourceTransportError("tls-verification-required")
                current.settimeout(self.deadline.timeout())
                current = context.wrap_socket(current, server_hostname=self.host)
                self.deadline.remaining()
                if ipaddress.ip_address(current.getpeername()[0]) != address:
                    raise SourceTransportError("connected-peer-differs")
            self.peer_address = str(address)
            self.sock = _DeadlineChannel(current, self.deadline)
        except BaseException:
            current.close()
            raise


def _direct_connection(parsed, address, deadline):
    return _PinnedConnection(parsed, address, deadline)


def _safe_code(error, deadline):
    if isinstance(error, SourceTransportError):
        return str(error) if str(error) in ERROR_CODES else "network-error"
    if isinstance(error, ssl.SSLError):
        return "tls-verification-failed"
    if isinstance(error, TimeoutError):
        try:
            deadline.remaining()
        except SourceTransportError:
            return "deadline-exceeded"
        return "network-timeout"
    if isinstance(error, SessionApiError):
        return (
            "resolver-unavailable"
            if error.code.startswith("source-resolver-")
            else "unsafe-url"
        )
    return "network-error"


class _Engine:
    """Connection injection is a synthetic test seam, never a production claim."""

    def __init__(
        self,
        request,
        output_dir,
        resolver,
        utc,
        monotonic,
        connection_factory=_direct_connection,
    ):
        self.request = request_binding(request)
        _check(
            isinstance(resolver, TypedBoundedResolver),
            "source-acquisition-bounded-resolver-required",
            503,
        )
        _check(
            resolver.binding_sha256 == request["resolver_sha256"],
            "source-acquisition-resolver-binding-differs",
            409,
        )
        self.resolver = resolver
        self.deadline = _Deadline(self.request, utc, monotonic)
        self.output = private_output(output_dir)
        _check(not self.output.exists(), "source-acquisition-output-exists", 409)
        self.factory = connection_factory
        self.attempts = []
        self.aggregate = 0
        self.requests = 0
        # Internal observations bind persisted bytes to the stream we received.
        # They are not caller-supplied fields or new receipt schema assertions.
        self._body_observations = {}

    def _body(self, response, attempt):
        capacity = min(
            self.request["max_response_bytes"],
            self.request["max_aggregate_bytes"] - self.aggregate,
        )
        encoding = response.getheader("Content-Encoding", "identity").strip().lower()
        if encoding not in ("", "identity"):
            raise SourceTransportError("content-encoding-not-supported")
        declared_text = response.getheader("Content-Length")
        declared = None
        if declared_text is not None:
            if not declared_text.isascii() or not declared_text.isdecimal():
                raise SourceTransportError("content-length-invalid")
            declared = int(declared_text)
            if declared > capacity:
                raise SourceTransportError("response-too-large")
        if capacity <= 0:
            raise SourceTransportError("aggregate-bound-reached")
        relative = f"raw/{attempt['sequence']:03d}.response"
        path = self.output / relative
        digest = hashlib.sha256()
        observed = dict(body_bytes=0, raw_sha256=digest.hexdigest())
        self._body_observations[attempt["sequence"]] = observed
        with path.open("xb") as stream:
            attempt["raw_path"] = relative

            def save(data):
                if type(data) is not bytes:
                    raise SourceTransportError("reader-byte-bound-invalid")
                remaining = capacity - attempt["body_bytes"]
                prefix = data[:remaining]
                try:
                    written = stream.write(prefix)
                    if type(written) is not int or written != len(prefix):
                        raise SourceTransportError("artifact-write-unobserved")
                    stream.flush()
                except OSError as error:
                    raise SourceTransportError("artifact-write-unobserved") from error
                digest.update(prefix)
                observed.update(
                    body_bytes=observed["body_bytes"] + len(prefix),
                    raw_sha256=digest.hexdigest(),
                )
                attempt["body_bytes"] += len(prefix)
                self.aggregate += len(prefix)
                if len(data) > remaining:
                    raise SourceTransportError("reader-byte-bound-invalid")

            def complete():
                if declared is not None and attempt["body_bytes"] != declared:
                    raise SourceTransportError("incomplete-body")
                attempt["body_complete"] = True

            try:
                while attempt["body_bytes"] < capacity:
                    self.deadline.remaining()
                    available = capacity - attempt["body_bytes"]
                    try:
                        data = response.read1(min(64 * 1024, available))
                    except http.client.IncompleteRead as error:
                        save(error.partial)
                        raise SourceTransportError("incomplete-body") from error
                    if not data:
                        self.deadline.remaining()
                        complete()
                        break
                    save(data)
                    self.deadline.remaining()
                    if response.isclosed():
                        complete()
                        break
                if not attempt["body_complete"]:
                    raise SourceTransportError("body-bound-reached")
            finally:
                try:
                    stream.flush()
                    os.fsync(stream.fileno())
                except OSError as error:
                    raise SourceTransportError("artifact-write-unobserved") from error
        # The finally in _attempt also hashes partial files on an interruption.

    def _read_raw(self, path):
        """Inspect a bounded regular file without following a changed link."""
        reject_links(path)
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise SourceTransportError("artifact-file-invalid")
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            reject_links(path)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or not before.st_ino
                or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            ):
                raise SourceTransportError("artifact-file-changed")
            maximum = self.request["max_response_bytes"]
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())

        def stamp(info):
            return (
                info.st_dev,
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
                info.st_nlink,
            )

        reject_links(path)
        if (
            len(raw) > maximum
            or len(raw) != after.st_size
            or stamp(opened) != stamp(after)
        ):
            # The cap+1 probe is not a complete-file observation or a digest.
            raise SourceTransportError("artifact-read-bound")
        if stamp(path.lstat()) != stamp(after):
            raise SourceTransportError("artifact-file-changed")
        return raw

    def _attempt(self, url):
        attempt = dict(
            sequence=len(self.attempts) + 1,
            url=url,
            started_at=_stamp(self.deadline.utc()),
            finished_at=None,
            resolved_addresses=[],
            selected_address=None,
            peer_address=None,
            http_request_attempted=False,
            http_status=None,
            content_type="",
            outcome="execution-unknown",
            raw_path=None,
            raw_sha256=None,
            body_bytes=0,
            body_complete=False,
            error_code=None,
        )
        self.attempts.append(attempt)
        connection, response = None, None
        try:
            self.deadline.remaining()
            public_source_uri(url)
            if not url.isascii():
                raise SourceTransportError("url-ascii-required")
            parsed = urlsplit(url)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            addresses = self.resolver.resolve(parsed.hostname, port, self.deadline.end)
            self.deadline.remaining()
            if type(addresses) is not tuple or not 1 <= len(addresses) <= 64:
                raise SourceTransportError("resolver-addresses-invalid")
            checked = sorted({str(_numeric(value)) for value in addresses})
            attempt["resolved_addresses"] = checked
            attempt["selected_address"] = checked[0]
            connection = self.factory(parsed, checked[0], self.deadline)
            # Establish and inspect the peer before sending any HTTP request.
            connection.connect()
            self.deadline.remaining()
            if connection.peer_address != checked[0]:
                raise SourceTransportError("connected-peer-differs")
            attempt["peer_address"] = connection.peer_address
            self.requests += 1
            attempt["http_request_attempted"] = True
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            connection.request(
                "GET",
                target,
                headers={
                    "Host": parsed.netloc,
                    "Accept": "*/*",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                    "User-Agent": "ResearchHarness-PublicSource/1",
                },
            )
            response = connection.getresponse()
            attempt["http_status"] = response.status
            attempt["content_type"] = response.getheader("Content-Type", "")
            self.deadline.remaining()
            self._body(response, attempt)
            status = response.status
            if status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise SourceTransportError("redirect-location-missing")
                target = urljoin(url, location)
                public_source_uri(
                    target
                )  # Refuse before DNS and without saving secrets.
                if not target.isascii():
                    raise SourceTransportError("url-ascii-required")
                attempt["outcome"] = "redirect"
                return target
            if 200 <= status < 300:
                attempt["outcome"] = (
                    "http-body-complete" if attempt["body_bytes"] else "empty-body"
                )
            else:
                attempt["outcome"] = {
                    404: "not-found",
                    429: "rate-limited",
                    401: "inaccessible",
                    402: "inaccessible",
                    403: "inaccessible",
                }.get(status, "http-error")
            return None
        except Exception as error:
            code = _safe_code(error, self.deadline)
            attempt.update(outcome=code, error_code=code)
            return None
        except BaseException:
            attempt.update(
                outcome="execution-unknown", error_code="execution-interrupted"
            )
            raise
        finally:
            for resource in (response, connection):
                if resource is not None:
                    try:
                        resource.close()
                    except BaseException:
                        attempt.update(
                            outcome="execution-unknown",
                            error_code="connection-cleanup-unobserved",
                        )
            if attempt["raw_path"] is not None:
                try:
                    raw = self._read_raw(self.output / attempt["raw_path"])
                except BaseException:
                    attempt.update(
                        outcome="execution-unknown",
                        error_code="artifact-read-unobserved",
                        body_complete=False,
                    )
                    raise
                actual_sha = sha(raw)
                self.aggregate += len(raw) - attempt["body_bytes"]
                attempt.update(raw_sha256=actual_sha, body_bytes=len(raw))
                observed = self._body_observations.get(attempt["sequence"])
                if attempt["body_complete"] and observed != {
                    "body_bytes": len(raw),
                    "raw_sha256": actual_sha,
                }:
                    attempt.update(
                        outcome="execution-unknown",
                        error_code="raw-body-differs",
                        body_complete=False,
                    )
            # Finalizing a file or closing a response can consume the remaining
            # budget even when the last network read finished before the bound.
            try:
                self.deadline.remaining()
            except SourceTransportError:
                if attempt["outcome"] != "execution-unknown":
                    attempt.update(
                        outcome="deadline-exceeded", error_code="deadline-exceeded"
                    )
                attempt["body_complete"] = False
            attempt["finished_at"] = _stamp(self.deadline.utc())

    def _publication_failure(self, receipt_bytes):
        """Preserve an immutable receipt and bind a separate late failure."""
        observation = dict(
            kind="PublicSourceAcquisitionFailureObservation",
            schema_version="1.0.0",
            request_sha256=sha(canonical(self.request)),
            acquisition_receipt_path="public-source-acquisition.json",
            acquisition_receipt_sha256=sha(receipt_bytes),
            phase="post-receipt-publication",
            status="execution-unknown",
            outcome="deadline-exceeded",
            observed_at=_stamp(self.deadline.utc()),
        )
        with (self.output / "public-source-acquisition-failure.json").open(
            "xb"
        ) as stream:
            data = canonical(observation)
            written = stream.write(data)
            if type(written) is not int or written != len(data):
                raise SourceTransportError("artifact-write-unobserved")
            stream.flush()
            os.fsync(stream.fileno())

    def run(self):
        self.output.mkdir(parents=True, exist_ok=False)
        (self.output / "raw").mkdir()
        current = self.request["source_uri"]
        interrupted = None
        try:
            while len(self.attempts) < self.request["max_http_attempts"]:
                next_url = self._attempt(current)
                if next_url is None or self.attempts[-1]["outcome"] != "redirect":
                    break
                current = next_url
            else:
                # No extra DNS, socket or HTTP operation is performed for this hop.
                self.attempts[-1].update(
                    outcome="attempt-limit", error_code="attempt-limit"
                )
        except BaseException as error:
            interrupted = error
        last = self.attempts[-1]
        selected = last if last["outcome"] == "http-body-complete" else None
        receipt = dict(
            kind="PublicSourceAcquisitionReceipt",
            schema_version="1.0.0",
            request=deepcopy(self.request),
            request_sha256=sha(canonical(self.request)),
            output_dir=str(self.output),
            started_at=_stamp(self.deadline.started),
            finished_at=_stamp(self.deadline.utc()),
            status="interrupted"
            if interrupted is not None
            or last["outcome"]
            in ("deadline-exceeded", "execution-unknown", "artifact-write-unobserved")
            else "completed",
            outcome=last["outcome"],
            final_url=last["url"],
            http_attempts=len(self.attempts),
            http_requests_attempted=self.requests,
            aggregate_bytes=self.aggregate,
            attempts=self.attempts,
            selected_attempt_sequence=selected["sequence"] if selected else None,
            raw_path=selected["raw_path"] if selected else None,
            raw_sha256=selected["raw_sha256"] if selected else None,
            content_type=selected["content_type"] if selected else "",
            body_bytes=selected["body_bytes"] if selected else 0,
            body_complete=selected is not None,
        )
        receipt_bytes = canonical(receipt)
        with (self.output / "public-source-acquisition.json").open("xb") as stream:
            written = stream.write(receipt_bytes)
            if type(written) is not int or written != len(receipt_bytes):
                raise SourceTransportError("artifact-write-unobserved")
            stream.flush()
            os.fsync(stream.fileno())
        if receipt["status"] == "completed":
            try:
                self.deadline.remaining()
            except SourceTransportError:
                self._publication_failure(receipt_bytes)
                raise
        if interrupted is not None:
            raise interrupted
        return receipt


def acquire_public_source(
    request, output_dir, *, resolver=None, clock_utc=None, monotonic=None
):
    """Acquire one admitted server request; no default resolver or auto-retry.

    Output must be a new private directory outside Git. All bodies, including
    redirect/error/partial prefixes, retain their own hashes. Byte limits count
    saved network bodies, not this JSON receipt or later parser artifacts.
    DNS/network waits use one deadline; individual synchronous operating-system
    startup, TLS context creation and process creation cannot be preempted here.
    An outer admitted owned worker is required for a hard end-to-end wall bound.
    Raw/receipt files are flushed and fsynced, but crashes between file creation
    and receipt publication retain partial files and an unknown owning intent;
    this helper supplies no multi-store transaction or automatic recovery.
    A deadline observed after receipt publication adds a distinct failure file
    and raises; owners must not adopt that unchanged receipt as a usable result.
    This is not a source-reading, identity, claim or scientific-validity verdict.
    A production caller must verify resolver/runtime configuration and persist
    intent/permission/budget before calling. GET and imports never call this.
    """
    return _Engine(
        request, output_dir, resolver, clock_utc or _utc, monotonic or time.monotonic
    ).run()

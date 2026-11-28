"""Loopback HTTP over a supplied SessionApi; no launcher, UI or native admission."""

import hmac
import json
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer

from stage1_retrieval import verification_clock

from .session_api import SessionApi, SessionApiError
from .store import JournalError
from .transport import _decode

MAX_BODY = 256 * 1024
MAX_RESPONSE = 1024 * 1024
REF = r"[A-Za-z0-9_-]{1,128}"
ROUTE = re.compile(
    rf"/api/native/projects/({REF})(?:/(answers|interrupts|actions|offer|messages)/?({REF})?)?"
)


class RequestDeadline:
    """One request's total deadline with bounded local verification excluded.

    The 30 second cap bounds socket I/O and request work. Pure local integrity
    passes inside the request (marked with ``verification_clock``) run under
    this request's meter and push the deadline out by at most the meter's own
    allowance; the raw clock never runs past ``timeout + MAX_SECONDS``. Without
    any marked verification it equals the previous absolute deadline.

    One meter per connection; every reply closes the connection, so it is one
    meter per request. The meter starts non-enforcing: it only measures and
    caps how far the deadline may move, and never raises, so a write that
    verifies after saving its intent cannot gain a new failure point (it would
    leave execution-unknown). ``SessionHandler.parse_request`` turns enforcement
    on for GET only: a read over its budget answers 503 with its own reason. GET
    saves no intent; the only GET write is the idempotent session offer record
    (``SessionApi.offer``), saved after its verification and only compared on a
    repeat, so a budget error never leaves an unknown outcome. The allowance base is at least ``timeout``:
    verification that used to fit inside the old absolute cap can never fail
    here with the budget reason. The 600 s bound is a socket bound, not a work
    bound: as before, the handler thread runs on after the socket is closed. Code that opens its own nested meter inside a request (the
    query/bootstrap workers do) measures against that meter instead, so its
    verification does not move this deadline -- the previous behaviour.
    """

    REARM_SECONDS = 0.25

    def __init__(self, timeout):
        # A read can verify several runtimes per request (each view checks its
        # own seal); the pass bound is widened so the count alone never fails
        # a request that used to answer. The 600 s cap still bounds the time.
        self.meter = verification_clock.Meter(
            base_seconds=max(verification_clock.BASE_SECONDS, timeout),
            max_passes=4 * verification_clock.MAX_PASSES,
            enforce=False,
        )
        self.until = time.monotonic() + timeout
        self.hard = self.until + self.meter.max_seconds

    def rearm_delay(self, left):
        # While a pass is open, left() stays constant; a floor stops the timer
        # from re-arming in a tight loop. It may close up to this much late,
        # and only once verification has moved the deadline at all.
        if self.meter.excluded() <= 0:
            return left
        return max(left, min(self.REARM_SECONDS, self.hard - time.monotonic()))

    def left(self):
        now = time.monotonic()
        return min(self.until + self.meter.excluded() - now, self.hard - now)


def token_authenticator(tokens):
    """Make an in-memory constant-time token matcher for trusted server bootstrap."""
    if not isinstance(tokens, dict) or not tokens:
        raise ValueError("server token map required")
    pairs = []
    for token, principal in tokens.items():
        if (
            not isinstance(token, str)
            or not token.isascii()
            or not 32 <= len(token) <= 4096
            or any(ord(c) < 33 for c in token)
            or not isinstance(principal, str)
            or not 0 < len(principal) <= 128
        ):
            raise ValueError("invalid server token map")
        pairs.append((token.encode("ascii"), principal))

    def authenticate(token):
        if not isinstance(token, str) or len(token) > 4096:
            return None
        candidate, matched = token.encode("utf-8"), None
        for secret, principal in pairs:
            if hmac.compare_digest(candidate, secret):
                matched = principal
        return matched

    return authenticate


class SessionHttpServer(ThreadingHTTPServer):
    """Explicit loopback listener; the caller owns its start/stop and credentials."""

    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, api, *, host="127.0.0.1", port=0, timeout=5, max_connections=16):
        if not isinstance(api, SessionApi) or host != "127.0.0.1":
            raise ValueError("loopback SessionApi required")
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("invalid port")
        if type(timeout) not in (int, float) or not 0 < timeout <= 30:
            raise ValueError("bounded timeout required")
        if type(max_connections) is not int or not 1 <= max_connections <= 128:
            raise ValueError("bounded connection cap required")
        self._slots = threading.BoundedSemaphore(max_connections)
        self._deadlines, self._deadline_lock = {}, threading.Lock()
        self.api, self.timeout_seconds = api, timeout
        super().__init__((host, port), SessionHandler)
        bound_port = self.server_address[1]
        self.expected_host = (
            "127.0.0.1" if bound_port == 80 else f"127.0.0.1:{bound_port}"
        )
        self.expected_origin = "http://" + self.expected_host

    def server_bind(self):
        """Bind the validated numeric loopback without a reverse-DNS lookup."""
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def process_request(self, request, client_address):
        # Refuse excess sockets before creating a handler or deadline thread.
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        timer, registered = None, False
        try:
            deadline = RequestDeadline(self.timeout_seconds)
            timer = threading.Timer(self.timeout_seconds, self._expire, (request,))
            timer.daemon = True
            with self._deadline_lock:
                # (raw absolute deadline, current timer, extendable deadline)
                self._deadlines[request] = (deadline.until, timer, deadline)
            registered = True
            timer.start()
            super().process_request(request, client_address)
        except BaseException:
            if registered:
                self._release(request)
            else:
                try:
                    if timer is not None:
                        timer.cancel()
                finally:
                    self._slots.release()
            raise

    def _expire(self, request):
        # Re-arm while bounded local verification has pushed the deadline out;
        # otherwise close the socket exactly as the previous single timer did.
        with self._deadline_lock:
            entry = self._deadlines.get(request)
            if entry is None:
                return  # Already released.
            left = entry[2].left()
            if left > 0:
                timer = threading.Timer(
                    entry[2].rearm_delay(left), self._expire, (request,)
                )
                timer.daemon = True
                self._deadlines[request] = (entry[0], timer, entry[2])
                timer.start()
                return
        self.shutdown_request(request)

    def _release(self, request):
        with self._deadline_lock:
            entry = self._deadlines.pop(request, None)
        if entry is None:
            return  # A racing startup failure already released this request.
        try:
            entry[1].cancel()
        finally:
            self._slots.release()

    def process_request_thread(self, request, client_address):
        try:
            with self._deadline_lock:
                entry = self._deadlines.get(request)
            if entry is None:
                return super().process_request_thread(request, client_address)
            with verification_clock.metering(entry[2].meter):
                super().process_request_thread(request, client_address)
        finally:
            self._release(request)


class SessionHandler(BaseHTTPRequestHandler):
    """Same-origin JSON only; no CORS, process startup or implicit retries."""

    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        with self.server._deadline_lock:
            entry = self.server._deadlines[self.connection]
        # ``deadline`` stays the raw absolute float for callers that take one
        # (they keep their previous, conservative timing).
        self.deadline, self.request_deadline = entry[0], entry[2]
        self._remaining()

    def parse_request(self):
        parsed = super().parse_request()
        extendable = getattr(self, "request_deadline", None)
        if parsed and extendable is not None and self.command == "GET":
            extendable.meter.enforce = True  # GET saves no intent; see above.
        return parsed

    def _remaining(self):
        now = time.monotonic()
        remaining = self.deadline - now
        extendable = getattr(self, "request_deadline", None)
        if extendable is not None:
            # Bounded local verification in this request pushes the deadline
            # out; the raw clock never passes the hard bound.
            remaining = min(
                remaining + extendable.meter.excluded(), extendable.hard - now
            )
        if remaining <= 0:
            raise TimeoutError("absolute request deadline expired")
        self.connection.settimeout(remaining)
        return remaining

    def handle(self):
        try:
            super().handle()
        except OSError:
            self.close_connection = True  # Deadline shutdown may interrupt a read.

    def log_message(self, *_):
        pass  # Do not log credentials, paths, researcher answers or native output.

    def _reply(self, status, value):
        self.close_connection = True
        raw = json.dumps(value, ensure_ascii=True, allow_nan=False).encode("utf-8")
        if len(raw) > MAX_RESPONSE:
            status, raw = 413, b'{"error":"response-bound-exceeded"}'
        self.send_response(status)
        for name, content in (
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(raw))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
            ("Connection", "close"),
        ):
            self.send_header(name, content)
        try:
            self.end_headers()
            self.wfile.write(raw)
        except OSError:
            # A disconnected HTTP client never changes the durable action outcome.
            return

    def send_error(self, code, message=None, explain=None):
        self._reply(code, {"error": "http-rejected"})

    def _headers(self, method):
        for name in (
            "Host",
            "Origin",
            "Authorization",
            "Content-Length",
            "Content-Type",
            "Transfer-Encoding",
        ):
            if len(self.headers.get_all(name, [])) > 1:
                raise SessionApiError("duplicate-safety-header", 400)
        if self.headers.get("Transfer-Encoding") is not None:
            raise SessionApiError("transfer-encoding-rejected", 400)
        origin = self.headers.get("Origin")
        if self.headers.get("Host") != self.server.expected_host or (
            origin != self.server.expected_origin
            and not (method == "GET" and origin is None)
        ):
            raise SessionApiError("origin-or-host-rejected", 403)
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            raise SessionApiError("credential-required", 401)
        token = authorization[7:]
        if not token or len(token) > 4096 or any(ord(c) < 33 for c in token):
            raise SessionApiError("credential-required", 401)
        length = self.headers.get("Content-Length")
        if length is not None and not re.fullmatch(r"0|[1-9][0-9]{0,6}", length):
            raise SessionApiError("invalid-content-length", 400)
        length = int(length or "0")
        if length > MAX_BODY:
            raise SessionApiError("body-bound-exceeded", 413)
        return token, length

    def _handle(self, method):
        with self.server.api.admission_guard(self._remaining):
            self._handle_guarded(method)

    def _handle_guarded(self, method):
        try:
            credential, length = self._headers(method)
            match = ROUTE.fullmatch(self.path)
            if not match:
                raise SessionApiError("unknown-route", 404)
            project_ref, operation, action_ref = match.groups()
            if method == "GET":
                if length or (operation and operation not in {"actions", "offer"}):
                    raise SessionApiError("invalid-read-request", 400)
                if operation == "actions":
                    if not action_ref:
                        raise SessionApiError("action-ref-required", 400)
                    result = self.server.api.action(credential, project_ref, action_ref)
                elif operation == "offer":
                    if action_ref:
                        raise SessionApiError("invalid-offer-route", 400)
                    result = self.server.api.offer(credential, project_ref)
                else:
                    result = self.server.api.view(credential, project_ref)
            else:
                if operation not in {"answers", "interrupts", "messages"} or action_ref:
                    raise SessionApiError("unknown-write-route", 404)
                if self.headers.get("Content-Type", "").lower() != "application/json":
                    raise SessionApiError("json-content-type-required", 415)
                if not length:
                    raise SessionApiError("json-body-required", 400)
                self._remaining()
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise SessionApiError("partial-body", 400)
                try:
                    body = _decode(raw.decode("utf-8"))
                except (TypeError, ValueError, UnicodeError, RecursionError):
                    raise SessionApiError("invalid-json", 400) from None
                if not isinstance(body, dict):
                    raise SessionApiError("object-body-required", 400)
                handler = {
                    "answers": self.server.api.answer,
                    "interrupts": self.server.api.interrupt,
                    "messages": self.server.api.message,
                }[operation]
                self._remaining()
                result = handler(credential, project_ref, body)
            self._reply(200, result)
        except SessionApiError as error:
            value = {"error": error.code}
            if error.receipt is not None:
                value["receipt"] = error.receipt
            self._reply(error.status, value)
        except ConnectionError:
            return  # The durable action remains queryable after response loss.
        except JournalError:
            self._reply(409, {"error": "session-rejected"})
        except (socket.timeout, TimeoutError):
            self._reply(408, {"error": "request-timeout"})
        except verification_clock.LocalVerificationBudgetExceeded:
            self._reply(503, {"error": verification_clock.BUDGET_CODE})
        except Exception:
            self._reply(500, {"error": "service-failure"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_OPTIONS(self):
        self._reply(405, {"error": "method-rejected"})

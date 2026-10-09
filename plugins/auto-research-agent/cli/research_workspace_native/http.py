"""Loopback HTTP over a supplied SessionApi; no launcher, UI or native admission."""

import hmac
import json
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .session_api import SessionApi, SessionApiError
from .store import JournalError
from .transport import _decode

MAX_BODY = 256 * 1024
MAX_RESPONSE = 1024 * 1024
REF = r"[A-Za-z0-9_-]{1,128}"
ROUTE = re.compile(
    rf"/api/native/projects/({REF})(?:/(answers|interrupts|actions|offer|messages)/?({REF})?)?"
)


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
        self._deadlines = {}
        self.api, self.timeout_seconds = api, timeout
        super().__init__((host, port), SessionHandler)
        bound_port = self.server_address[1]
        self.expected_host = (
            "127.0.0.1" if bound_port == 80 else f"127.0.0.1:{bound_port}"
        )
        self.expected_origin = "http://" + self.expected_host

    def process_request(self, request, client_address):
        # Refuse excess sockets before creating a handler or deadline thread.
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        timer, registered = None, False
        try:
            timer = threading.Timer(
                self.timeout_seconds, self.shutdown_request, (request,)
            )
            timer.daemon = True
            self._deadlines[request] = (time.monotonic() + self.timeout_seconds, timer)
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

    def _release(self, request):
        entry = self._deadlines.pop(request, None)
        if entry is None:
            return  # A racing startup failure already released this request.
        try:
            entry[1].cancel()
        finally:
            self._slots.release()

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._release(request)


class SessionHandler(BaseHTTPRequestHandler):
    """Same-origin JSON only; no CORS, process startup or implicit retries."""

    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.deadline = self.server._deadlines[self.connection][0]
        self._remaining()

    def _remaining(self):
        remaining = self.deadline - time.monotonic()
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
            self._reply(error.status, {"error": error.code})
        except ConnectionError:
            return  # The durable action remains queryable after response loss.
        except JournalError:
            self._reply(409, {"error": "session-rejected"})
        except (socket.timeout, TimeoutError):
            self._reply(408, {"error": "request-timeout"})
        except Exception:
            self._reply(500, {"error": "service-failure"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_OPTIONS(self):
        self._reply(405, {"error": "method-rejected"})

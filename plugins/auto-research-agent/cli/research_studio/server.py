"""Authenticated single-owner HTTP API; place behind an HTTPS reverse proxy."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import re
from urllib.parse import parse_qs, urlsplit

from .store import StudioError, canonical
from .runtime import validate_token


def make_server(engine, token, origins, address):
    validate_token(token)
    for origin in origins:
        url = urlsplit(origin)
        if (
            url.scheme not in {"https", "http"}
            or not url.netloc
            or url.path
            or url.query
            or url.fragment
            or url.username
            or url.password
            or url.scheme == "http"
            and url.hostname not in {"localhost", "127.0.0.1", "::1"}
        ):
            raise StudioError(
                "CORS origins must be exact HTTPS origins; loopback HTTP is for development"
            )

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(10)
            super().setup()

        def log_message(self, *_args):
            pass  # Never put URLs, bearer credentials or research text in server access logs.

        def send(self, status, value, *, binary=False):
            data = value if binary else canonical(value).encode()
            self.send_response(status)
            origin = self.headers.get("Origin")
            if origin in origins:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers", "Authorization, Content-Type"
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Type",
                "application/octet-stream"
                if binary
                else "application/json; charset=utf-8",
            )
            if binary:
                self.send_header(
                    "Content-Disposition", 'attachment; filename="research-artifact"'
                )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):
            if self.headers.get("Origin") not in origins:
                self.send(403, {"error": "origin not allowed"})
            else:
                self.send(200, {})

        def do_GET(self):
            self.dispatch()

        def do_POST(self):
            self.dispatch()

        def dispatch(self):
            try:
                self.connection.settimeout(10)
                origin = self.headers.get("Origin")
                if origin is not None and origin not in origins:
                    raise StudioError("origin not allowed", 403)
                supplied = self.headers.get("Authorization", "")
                if not hmac.compare_digest(
                    supplied.encode(), ("Bearer " + token).encode()
                ):
                    raise StudioError("authentication required", 401)
                parsed = urlsplit(self.path)
                path, body = parsed.path, None
                if self.command == "POST":
                    if (
                        self.headers.get("Transfer-Encoding")
                        or self.headers.get("Content-Type", "").split(";")[0]
                        != "application/json"
                    ):
                        raise StudioError("bounded application/json body required", 400)
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 32768:
                        raise StudioError("request body must be 1 to 32768 bytes", 400)
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise StudioError("incomplete request body", 400)
                    body = json.loads(raw)
                if self.command == "GET" and path == "/api/status":
                    return self.send(200, engine.status())
                if path == "/api/runs":
                    return (
                        self.send(202, {"run": engine.submit(body)})
                        if self.command == "POST"
                        else self.send(200, {"runs": engine.store.list()})
                    )
                match = re.fullmatch(
                    r"/api/runs/([0-9a-f-]{36})(?:/(stop|artifacts/[0-9a-f]{64}))?",
                    path,
                )
                if match:
                    run_id, action = match.groups()
                    if self.command == "POST" and action == "stop" and body == {}:
                        return self.send(200, {"run": engine.stop(run_id)})
                    if self.command == "GET" and action is None:
                        after = int(parse_qs(parsed.query).get("after", ["0"])[0])
                        if not 0 <= after <= 2**63 - 1:
                            raise ValueError("invalid cursor")
                        return self.send(200, engine.store.detail(run_id, after))
                    if (
                        self.command == "GET"
                        and action
                        and action.startswith("artifacts/")
                    ):
                        return self.send(
                            200,
                            engine.artifact(run_id, action.split("/")[1]),
                            binary=True,
                        )
                raise StudioError("route not found", 404)
            except StudioError as error:
                self.send(error.status, {"error": str(error)})
            except (ValueError, TypeError, UnicodeError):
                self.send(400, {"error": "invalid request"})
            except (OSError, RuntimeError):
                self.send(
                    500, {"error": "request failed; inspect private server state"}
                )

    return ThreadingHTTPServer(address, Handler)

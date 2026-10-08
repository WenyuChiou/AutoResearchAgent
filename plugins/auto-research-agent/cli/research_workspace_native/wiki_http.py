"""Serve an immutable Wiki reference with a separate injected session overlay.

Trusted bootstrap supplies four already accepted presentation byte strings.
No private package or filesystem path is published. This does not bootstrap or
authenticate a native process. The underlying SessionApi still owns authority.
"""

import base64
import hashlib
from pathlib import Path
import re

from .http import SessionHandler, SessionHttpServer
from .session_api import SessionApiError

REFERENCE_COMMIT = "085f363179a79375fc8e3590dda9725e25eda71a"
PUBLIC_README_SHA256 = (
    "5a2830f28f8f398c53afac3cd63094132a40e04cdfc754d5419360decf50d3af"
)
REFERENCE_HASHES = {
    "prototype.html": "dfd49e7d0baf5cbf1645a08c34dafb48bba7b3db9d867adf313e91b1a810298e",
    "literature-reference.js": "73e24c4a8e1c38ee66ca259391ed5c2bd04412dd8cd7d1f97875bbde7ed81323",
    "workspace-i18n.js": "d24fadd875728abfdd9d6a1734f430d82abf80ecf4538cf959d91245ce1bc24d",
    "workspace.css": "c8be8874b682171e83463bb5c00b379eb75581dac125b275e4878f1cccbd101b",
}


class WikiSessionServer(SessionHttpServer):
    def __init__(self, api, *, reference_assets, public_readme, **options):
        if (
            not isinstance(public_readme, bytes)
            or hashlib.sha256(public_readme).hexdigest() != PUBLIC_README_SHA256
        ):
            raise ValueError("accepted public README byte binding differs")
        if not isinstance(reference_assets, dict) or set(reference_assets) != set(
            REFERENCE_HASHES
        ):
            raise ValueError("exact accepted reference assets required")
        assets = {}
        for name, expected in REFERENCE_HASHES.items():
            raw = reference_assets[name]
            if (
                not isinstance(raw, bytes)
                or hashlib.sha256(raw).hexdigest() != expected
            ):
                raise ValueError("reference byte binding differs")
            assets["/" + name] = raw
        html = assets.pop("/prototype.html").decode("utf-8")
        if html.count("</body>") != 1 or html.count("</head>") != 1:
            raise ValueError("accepted template shape differs")
        html = html.replace(
            "</head>", '<link rel="stylesheet" href="/session-panel.css">\n</head>'
        ).replace("</body>", '<script src="/session-panel.js"></script>\n</body>')
        assets["/"] = html.encode("utf-8")
        assets["/README.md"] = public_readme
        for name in ("session-panel.js", "session-panel.css"):
            assets["/" + name] = (Path(__file__).parent / "web" / name).read_bytes()
        hashes = [
            "'sha256-"
            + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
            + "'"
            for text in re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
        ]
        self._wiki_assets = assets
        self._wiki_csp = (
            "default-src 'self'; script-src 'self' "
            + " ".join(hashes)
            + "; style-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )
        super().__init__(api, **options)
        self.RequestHandlerClass = WikiSessionHandler


class WikiSessionHandler(SessionHandler):
    def do_GET(self):
        if self.path.startswith("/api/"):
            return super().do_GET()
        try:
            for name in ("Host", "Origin", "Content-Length", "Transfer-Encoding"):
                if len(self.headers.get_all(name, [])) > 1:
                    raise SessionApiError("duplicate-safety-header", 400)
            if self.headers.get("Host") != self.server.expected_host or (
                self.headers.get("Origin") not in (None, self.server.expected_origin)
            ):
                raise SessionApiError("origin-or-host-rejected", 403)
            if (
                self.headers.get("Transfer-Encoding") is not None
                or self.headers.get("Content-Length", "0") != "0"
            ):
                raise SessionApiError("invalid-read-request", 400)
            raw = self.server._wiki_assets.get(self.path)
            if raw is None:
                raise SessionApiError("unknown-static-route", 404)
            kind = (
                "text/html"
                if self.path == "/"
                else "text/plain"
                if self.path == "/README.md"
                else "text/css"
                if self.path.endswith(".css")
                else "text/javascript"
            )
            self.send_response(200)
            for name, value in (
                ("Content-Type", kind + "; charset=utf-8"),
                ("Content-Length", str(len(raw))),
                ("Content-Security-Policy", self.server._wiki_csp),
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
                ("Referrer-Policy", "no-referrer"),
                ("Connection", "close"),
            ):
                self.send_header(name, value)
            self.close_connection = True
            self.end_headers()
            self.wfile.write(raw)
        except SessionApiError as error:
            self._reply(error.status, {"error": error.code})
        except (ConnectionError, TimeoutError):
            self.close_connection = True

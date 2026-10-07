"""Loopback scope overlay routes; saved briefs do not activate native execution."""

from pathlib import Path
import re

from .http import REF
from .scope_api import ScopeApi
from .session_api import SessionApiError
from .store import JournalError
from .transport import _decode
from .wiki_http import WikiSessionHandler, WikiSessionServer

SCOPE = re.compile(
    rf"/api/native/projects/({REF})/scope(?:/(versions|reviews)(?:/([0-9a-f]{{64}}))?)?"
)


class ScopeWikiSessionServer(WikiSessionServer):
    def __init__(self, api, *, scope_api, reference_assets, **options):
        if not isinstance(scope_api, ScopeApi) or scope_api.api is not api:
            raise ValueError("same server-owned SessionApi required")
        assets = {
            "/" + name: (Path(__file__).parent / "web" / name).read_bytes()
            for name in ("session-scope.js", "session-scope.css")
        }
        super().__init__(api, reference_assets=reference_assets, **options)
        self.scope_api = scope_api
        html = self._wiki_assets["/"].decode("utf-8")
        html = html.replace(
            "</head>", '<link rel="stylesheet" href="/session-scope.css">\n</head>'
        ).replace("</body>", '<script src="/session-scope.js"></script>\n</body>')
        self._wiki_assets.update(assets, **{"/": html.encode("utf-8")})
        self.RequestHandlerClass = ScopeWikiSessionHandler


class ScopeWikiSessionHandler(WikiSessionHandler):
    def _is_scope(self):
        return re.match(rf"/api/native/projects/{REF}/scope(?:/|$)", self.path)

    def do_GET(self):
        if self._is_scope():
            return self._scope("GET")
        return super().do_GET()

    def do_POST(self):
        if self._is_scope():
            return self._scope("POST")
        return super().do_POST()

    def _scope(self, method):
        try:
            credential, length = self._headers(method)
            match = SCOPE.fullmatch(self.path)
            if not match:
                raise SessionApiError("unknown-scope-route", 404)
            project, operation, version = match.groups()
            api = self.server.scope_api
            if method == "GET":
                if length or (
                    operation is not None and (operation != "versions" or not version)
                ):
                    raise SessionApiError("invalid-scope-read", 400)
                result = (
                    api.read(credential, project, version)
                    if version
                    else api.history(credential, project)
                )
            else:
                if operation not in {"versions", "reviews"} or version:
                    raise SessionApiError("unknown-scope-write", 404)
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
                change = api.append if operation == "versions" else api.review
                self._remaining()
                result = change(
                    credential, project, body, check_deadline=self._remaining
                )
            self._reply(200, result)
        except SessionApiError as error:
            self._reply(error.status, {"error": error.code})
        except ConnectionError:
            return
        except JournalError:
            self._reply(409, {"error": "scope-rejected"})
        except TimeoutError:
            self._reply(408, {"error": "request-timeout"})
        except Exception:
            self._reply(500, {"error": "service-failure"})

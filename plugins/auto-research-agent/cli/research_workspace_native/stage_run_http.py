"""Integrated Atlas overlay for explicitly permitted real content-only stage units."""

import json
from pathlib import Path
import re

from .atlas_host import AtlasHandler, AtlasHost
from .session_api import SessionApiError
from .transport import _decode
from stage1_deliverable.common import canonical, sha

ROUTE = re.compile(
    r"/api/stage-run/projects/([A-Za-z0-9_-]{1,64})(?:/(actions|native|answers|interrupts|deliveries)(?:/([A-Za-z0-9._-]{1,120}))?)?"
)


class StageRunHost(AtlasHost):
    """Preserves the existing graph/detail UI; adds a separate real execution panel.

    A service registration does not mean a model has run. The landing and panel
    distinguish admission, actual completed output and independent assessment.
    """

    def __init__(self, files, views, *, service, credential, **options):
        super().__init__(files=files, views=views, credential=credential, **options)
        self.stage_run, self._pilot_closed = service, False
        self.RequestHandlerClass = StageRunHandler
        assets = (
            Path(__file__).resolve().parents[2] / "references/research-workspace/web"
        )
        for name in ("stage-run-panel.js", "stage-run-panel.css"):
            self._assets["/" + name] = (assets / name).read_bytes()
        self._assets["/stage-run-bootstrap.js"] = (
            "window.WORKSPACE_STAGE_RUN="
            + json.dumps(
                dict(credential=credential, project_ref=service.ref), ensure_ascii=True
            )
            + ";"
        ).encode()
        scripts = (
            '<link rel="stylesheet" href="/stage-run-panel.css">'
            '<script src="/stage-run-bootstrap.js"></script>'
            '<script src="/stage-run-panel.js"></script>'
        )
        for row in self.views:
            route = row["url"]
            self._assets[route] = self._assets[route].replace(
                b"</body>", scripts.encode() + b"</body>"
            )
        self.host_binding["stage_pilot"] = dict(
            scope="repository-saved-content-only",
            permit_sha256=service.permit_sha,
            max_calls=service.permit["max_calls"],
            max_seconds=service.permit["max_seconds"],
            automatic_execution=False,
            canonical_stage1_handoff=False,
            scientific_acceptance=False,
            status_endpoint="/api/stage-run/projects/" + service.ref,
        )
        self.host_binding["served_files"] = {
            route: sha(raw)
            for route, raw in self._assets.items()
            if route != "/host-binding.json"
        }
        self._assets["/host-binding.json"] = canonical(self.host_binding)
        self._assets["/"] = self._assets["/"].replace(
            b"Research/model execution is not enabled.",
            b"A bounded real model pilot is registered. Open a case and explicitly run each unit; no automatic execution.",
        )

    def server_close(self):
        try:
            if not self._pilot_closed:
                self._pilot_closed = True
                self.stage_run.close()
        finally:
            super().server_close()


class StageRunHandler(AtlasHandler):
    def do_GET(self):
        if self.path.startswith("/api/stage-run/"):
            return self._pilot("GET")
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/stage-run/"):
            return self._pilot("POST")
        return super().do_POST()

    def _pilot(self, method):
        try:
            credential, length = self._headers(method)
            match = ROUTE.fullmatch(self.path)
            if match is None:
                raise SessionApiError("pilot-route-not-found", 404)
            ref, operation, key = match.groups()
            service = self.server.stage_run
            # Authenticate before inspecting a model, question, or private history.
            view = service.view(credential, ref)
            if method == "GET":
                if operation == "deliveries" and key and not length:
                    raw = service.delivery(credential, ref, key)
                    self.close_connection = True
                    self.send_response(200)
                    for name, value in (
                        ("Content-Type", "text/html; charset=utf-8"),
                        (
                            "Content-Disposition",
                            'attachment; filename="stage2-native-partial.html"',
                        ),
                        ("Content-Length", str(len(raw))),
                        ("Cache-Control", "no-store"),
                        (
                            "Content-Security-Policy",
                            "default-src 'none'; style-src 'unsafe-inline'",
                        ),
                        ("X-Content-Type-Options", "nosniff"),
                        ("Connection", "close"),
                    ):
                        self.send_header(name, value)
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if length or operation not in {None, "native"}:
                    raise SessionApiError("pilot-read-invalid", 400)
                result = view if operation is None else service.model.status()
            else:
                if key or operation not in {
                    "actions",
                    "answers",
                    "interrupts",
                    "deliveries",
                }:
                    raise SessionApiError("pilot-write-invalid", 404)
                if (
                    self.headers.get("Content-Type", "").lower() != "application/json"
                    or not length
                ):
                    raise SessionApiError("pilot-json-required", 415)
                self._remaining()
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise SessionApiError("pilot-partial-body", 400)
                body = _decode(raw.decode("utf8"))
                if not isinstance(body, dict):
                    raise SessionApiError("pilot-object-required", 400)
                if operation == "actions":
                    result = service.execute(
                        credential,
                        ref,
                        body,
                        pre_dispatch=lambda: self._remaining() > 0,
                    )
                elif operation == "deliveries":
                    result = service.publish(
                        credential,
                        ref,
                        body,
                        pre_dispatch=lambda: self._remaining() > 0,
                    )
                else:
                    # The active model facade owns exact request/hash/revision checks.
                    self._remaining()
                    callback = (
                        service.model.answer
                        if operation == "answers"
                        else service.model.interrupt
                    )
                    result = callback(body, pre_admission=self._remaining)
            self._reply(200, result)
        except SessionApiError as error:
            self._reply(error.status, dict(error=error.code))
        except (TypeError, ValueError, UnicodeError, RecursionError):
            self._reply(400, dict(error="pilot-invalid-json-or-binding"))
        except (OSError, TimeoutError):
            self.close_connection = True

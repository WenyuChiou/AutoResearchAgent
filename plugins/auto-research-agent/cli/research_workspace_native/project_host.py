"""Universal project intake over the existing authenticated, bounded Atlas host.

Topic entry, confirmation and compilation are real Harness operations. Optional
model/Stage2 services are trusted objects; browser JSON cannot construct them.
This module alone supplies no native, search or source-import authority.
"""

import argparse
import json
from pathlib import Path
import re
import secrets
import webbrowser

from .atlas_host import AtlasHandler, AtlasHost, load_views
from .http import token_authenticator
from .project_intake import ProjectIntakeService
from .project_contract import project_view
from .project_stage1_delivery import ProjectStage1DeliveryService
from .session_api import SessionApiError
from .transport import _decode
from stage1_deliverable.common import canonical, sha

ROUTE = re.compile(
    r"/api/projects(?:/([A-Za-z0-9_-]{1,64})"
    r"(?:/(history|overview|contract|confirm|configure|revise|compile|models|stage1|stage2)(?:/(offers|actions|authorize|native|initialize|plan-query|execute-query|checkpoint|export|deliver)(?:/(answer|interrupt))?)?)?)?"
)
ACTION_ROUTE = re.compile(r"/api/projects/actions/([A-Za-z0-9_-]{1,128})")
OUTPUT_ROUTE = re.compile(
    r"/api/projects/([A-Za-z0-9_-]{1,64})/models/outputs/([A-Za-z0-9_-]{1,128})/([0-9]{1,7})"
)
HISTORY_ROUTE = re.compile(
    r"/api/projects/([A-Za-z0-9_-]{1,64})/models/actions/([0-9]{1,4})"
)
ASSETS = Path(__file__).parent / "web"


class ProjectHost(AtlasHost):
    """One local user's projects; each service still owns its admission checks."""

    def __init__(
        self, *, projects, credential, models=None, stage1=None, stage2=None, **options
    ):
        if not isinstance(projects, ProjectIntakeService):
            raise ValueError("trusted project intake service required")
        if projects.authenticate(credential) != "local-viewer":
            raise ValueError("same local principal required")
        for service in (models, stage1, stage2):
            if service is not None and getattr(service, "intake", None) is not projects:
                raise ValueError("same project intake binding required")
        self.projects, self.project_models, self.project_stage2 = (
            projects,
            models,
            stage2,
        )
        self.project_stage1 = stage1
        self.project_stage1_delivery = (
            None if stage1 is None else ProjectStage1DeliveryService(stage1)
        )
        # Saved package build/replay is bounded filesystem work. The generic
        # 5-second socket default can expire after work but before commit; use
        # the existing hard 30-second HTTP cap, still checked before admission
        # and before commit. This grants no native/model execution time.
        options.setdefault("timeout", 30)
        super().__init__(credential=credential, **options)
        self.RequestHandlerClass = ProjectHandler
        for filename in ("projects.html", "projects.js", "projects.css"):
            self._assets["/" + filename] = (ASSETS / filename).read_bytes()
        # Keep all saved v6 graph files unchanged. Navigation is a host overlay.
        self._assets["/"] = self._assets["/projects.html"]
        self.host_binding.update(
            project_operations="versioned-intake-and-explicit-registered-actions",
            project_model_provider=models is not None,
            project_stage1_ledger=stage1 is not None,
            project_stage2_import=stage2 is not None,
            project_execution_authority=False,
        )
        self.host_binding["served_files"] = {
            path: sha(raw)
            for path, raw in self._assets.items()
            if path != "/host-binding.json"
        }
        self._assets["/host-binding.json"] = canonical(self.host_binding)

    def overview(self, credential, ref):
        # One store lock joins matching saved revisions. Workers cannot commit
        # another input/version between the UI brief and its action offers.
        with self.projects._lock:
            project = self.projects.read(credential, ref)
            return dict(
                project=project,
                models=None
                if self.project_models is None
                else self.project_models.read(credential, ref),
                model_offers=None
                if self.project_models is None
                else self.project_models.offers(credential, ref),
                stage1=None
                if self.project_stage1 is None
                else self.stage1_view(credential, ref),
                stage2=None
                if self.project_stage2 is None
                else self.project_stage2.read(credential, ref),
            )

    def stage1_view(self, credential, ref):
        """Read saved delivery offers together with the same project revision."""
        with self.projects._lock:
            return dict(
                self.project_stage1.read(credential, ref),
                delivery=self.project_stage1_delivery.read(credential, ref),
            )


class ProjectHandler(AtlasHandler):
    def _project(self, method):
        called = None
        try:
            token, length = self._headers(method)
            if self.headers.get("Sec-Fetch-Site") not in (None, "none", "same-origin"):
                raise SessionApiError("cross-site-rejected", 403)
            if self.server.authenticate(token) is None:
                raise SessionApiError("credential-rejected", 401)
            output = OUTPUT_ROUTE.fullmatch(self.path)
            page = HISTORY_ROUTE.fullmatch(self.path)
            if output is not None or page is not None:
                if method != "GET" or length:
                    raise SessionApiError("invalid-project-read", 400)
                extension = self.server.project_models
                if extension is None:
                    raise SessionApiError("project-operation-unconnected", 409)
                result = (
                    extension.outputs(token, output[1], output[2], int(output[3]))
                    if output is not None
                    else extension.history(token, page[1], offset=int(page[2]))
                )
                self._remaining()
                return self._reply(200, result)
            recovery = ACTION_ROUTE.fullmatch(self.path)
            if recovery is not None:
                if method != "GET" or length:
                    raise SessionApiError("invalid-project-read", 400)
                result = self.server.projects.action(token, recovery.group(1))
                self._remaining()
                self._reply(200, {"action": result})
                return
            match = ROUTE.fullmatch(self.path)
            if match is None:
                raise SessionApiError("unknown-project-route", 404)
            ref, operation, action, resolution = match.groups()
            service = self.server.projects
            self._remaining()
            if method == "GET":
                if length or operation in {"confirm", "configure", "revise", "compile"}:
                    raise SessionApiError("invalid-project-read", 400)
                if operation not in {"models", "stage1", "stage2"} and (
                    action or resolution
                ):
                    raise SessionApiError("invalid-project-read", 400)
                if operation in {"models", "stage1", "stage2"}:
                    extension = (
                        self.server.project_models
                        if operation == "models"
                        else self.server.project_stage1
                        if operation == "stage1"
                        else self.server.project_stage2
                    )
                    if extension is None:
                        raise SessionApiError("project-operation-unconnected", 409)
                    if resolution or action not in {
                        None,
                        "offers",
                        "actions",
                        "native",
                    }:
                        raise SessionApiError("invalid-project-read", 400)
                    if action == "native" and operation != "models":
                        raise SessionApiError("invalid-project-read", 400)
                    result = (
                        extension.native_view(token, ref)
                        if action == "native" and operation == "models"
                        else extension.offers(token, ref)
                        if action == "offers"
                        else extension.history(token, ref)
                        if action == "actions"
                        else extension.read(token, ref)
                    )
                    if operation == "stage1" and action in {None, "offers"}:
                        result = self.server.stage1_view(token, ref)
                elif operation == "overview":
                    if action or resolution:
                        raise SessionApiError("invalid-project-read", 400)
                    result = self.server.overview(token, ref)
                elif operation == "contract":
                    with service._lock:
                        result = project_view(
                            service,
                            token,
                            ref,
                            models=self.server.project_models,
                            stage1=self.server.project_stage1,
                            stage2=self.server.project_stage2,
                            stage1_delivery=self.server.project_stage1_delivery,
                        )
                else:
                    result = (
                        service.list(token)
                        if ref is None
                        else service.history(token, ref)
                        if operation == "history"
                        else service.read(token, ref)
                    )
            else:
                if self.headers.get("Content-Type", "").lower() != "application/json":
                    raise SessionApiError("json-content-type-required", 415)
                if not 0 < length <= 65536:
                    raise SessionApiError("project-body-bound-exceeded", 413)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise SessionApiError("partial-body", 400)
                try:
                    body = _decode(raw.decode("utf8"))
                except (ValueError, UnicodeError, RecursionError):
                    raise SessionApiError("invalid-json", 400) from None
                self._remaining()
                if ref is None:
                    called = ("create", None, body)
                    result = service.create(token, body, check_deadline=self._remaining)
                elif operation == "confirm" and action is None:
                    called = ("submit", ref, body)
                    result = service.submit(
                        token, ref, body, check_deadline=self._remaining
                    )
                elif operation in {"configure", "revise"} and action is None:
                    called = (operation, ref, body)
                    result = getattr(service, operation)(
                        token, ref, body, check_deadline=self._remaining
                    )
                elif operation == "compile" and action is None:
                    called = ("compile", ref, body)
                    result = service.compile(
                        token, ref, body, check_deadline=self._remaining
                    )
                elif (
                    operation == "stage1"
                    and action
                    in {
                        "initialize",
                        "plan-query",
                        "execute-query",
                        "checkpoint",
                        "export",
                        "deliver",
                    }
                    and resolution is None
                ):
                    extension = self.server.project_stage1
                    if extension is None:
                        raise SessionApiError("project-operation-unconnected", 409)
                    called = ("stage1-" + action, ref, body)
                    if action == "deliver":
                        extension = self.server.project_stage1_delivery
                    result = getattr(extension, action.replace("-", "_"))(
                        token, ref, body, check_deadline=self._remaining
                    )
                elif operation in {"models", "stage2"} and action in {
                    "actions",
                    "authorize",
                    "native",
                }:
                    extension = (
                        self.server.project_models
                        if operation == "models"
                        else self.server.project_stage2
                    )
                    if extension is None:
                        raise SessionApiError("project-operation-unconnected", 409)
                    if (
                        operation == "models"
                        and action == "native"
                        and resolution in {"answer", "interrupt"}
                    ):
                        function = getattr(extension, resolution)
                    elif (
                        operation == "models"
                        and action == "authorize"
                        and resolution is None
                    ):
                        function = extension.authorize
                        called = ("model-authorization", ref, body)
                    elif action == "actions" and resolution is None:
                        function = (
                            extension.execute
                            if operation == "models"
                            else extension.activate
                        )
                        called = (
                            "model-operation"
                            if operation == "models"
                            else "stage2-activate",
                            ref,
                            body,
                        )
                    else:
                        raise SessionApiError("unknown-project-write", 404)
                    result = function(token, ref, body, check_deadline=self._remaining)
                else:
                    raise SessionApiError("unknown-project-write", 404)
            self._remaining()
            self._reply(200, result)
        except SessionApiError as error:
            response = {"error": error.code}
            if called is not None:
                kind, project_ref, body = called
                try:
                    response["receipt"] = self.server.projects.record_refusal(
                        token, body.get("key"), project_ref, kind, body, error.code
                    )
                except (SessionApiError, ValueError, OSError, KeyError, TypeError):
                    pass  # No evidence means unresolved, never inferred unsent.
            self._reply(error.status, response)
        except (TimeoutError, OSError):
            self.close_connection = True
        except (ValueError, UnicodeError, KeyError, TypeError):
            self._reply(400, {"error": "project-input-rejected"})
        except Exception:
            self._reply(500, {"error": "project-operation-failed"})

    def do_GET(self):
        if self.path.startswith("/api/projects"):
            return self._project("GET")
        if self.path == "/project-bootstrap.js":
            # Same-origin local bootstrap, matching the existing Atlas credential
            # boundary. No credential appears in URL, HTML, logs or storage.
            if (
                self.headers.get("Host") != self.server.expected_host
                or self.headers.get("Origin") not in (None, self.server.expected_origin)
                or self.headers.get("Sec-Fetch-Site")
                not in (None, "none", "same-origin")
                or any(
                    len(self.headers.get_all(name, [])) > 1
                    for name in (
                        "Host",
                        "Origin",
                        "Content-Length",
                        "Transfer-Encoding",
                    )
                )
                or self.headers.get("Transfer-Encoding") is not None
                or self.headers.get("Content-Length", "0") != "0"
            ):
                return self._reply(403, {"error": "origin-or-host-rejected"})
            self.server._assets[self.path] = (
                "window.RESEARCH_PROJECTS="
                + json.dumps(
                    dict(
                        credential=self.server.credential,
                        views=self.server.views,
                        models=self.server.project_models is not None,
                        stage2=self.server.project_stage2 is not None,
                        stage1=self.server.project_stage1 is not None,
                    ),
                    ensure_ascii=True,
                    allow_nan=False,
                ).replace("<", "\\u003c")
                + ";\n"
            ).encode("utf8")
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/projects"):
            return self._project("POST")
        return super().do_POST()


def main(argv=None):
    from .project_stage1 import ProjectStage1Service
    from .project_stage2 import ProjectStage2Service

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects-root", required=True, type=Path)
    parser.add_argument("--views-config", type=Path)
    parser.add_argument("--views-sha256")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args(argv)
    if bool(args.views_config) != bool(args.views_sha256):
        parser.error("saved views require their external configuration SHA256")
    files, views = (
        load_views(args.views_config, args.views_sha256)
        if args.views_config
        else ({}, [])
    )
    token = secrets.token_urlsafe(32)
    projects = ProjectIntakeService(
        args.projects_root, authenticate=token_authenticator({token: "local-viewer"})
    )
    host = None
    try:
        host = ProjectHost(
            projects=projects,
            credential=token,
            stage1=ProjectStage1Service(projects),
            stage2=ProjectStage2Service(projects),
            files=files,
            views=views,
            port=args.port,
        )
        url = host.expected_origin + "/"
        print(
            json.dumps(
                dict(
                    url=url,
                    model_execution="unconnected",
                    search_execution="unconnected",
                )
            ),
            flush=True,
        )
        if args.open:
            webbrowser.open(url)
        host.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if host is not None:
            host.server_close()
        projects.close()


if __name__ == "__main__":
    main()

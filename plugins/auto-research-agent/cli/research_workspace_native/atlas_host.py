"""Serve pinned atlas views, a cached Codex check and an optional feedback inbox.

The default host has no native registrations. Optional trusted server-owned
runtime bindings expose an existing facade; this host never starts a process,
creates/resumes threads or starts its pump. Its loopback bootstrap is for one
local user, not multi-tenant authentication.
"""

import argparse
from copy import deepcopy
import html
import json
from pathlib import Path
import re
import secrets
import webbrowser
from urllib.parse import parse_qs

from stage1_deliverable.common import canonical, private_output, safe_path, sha
from .http import SessionHandler, SessionHttpServer, token_authenticator
from .session_api import SessionApi, SessionApiError
from .transport import _decode
from .harness_host import bind_operations, handle_operations
from .harness_ops import ACTIONS
from .stage_http import bind_stages, handle_stages
from .scope_api import ScopeApi
from .scope_http import ScopeWikiSessionHandler

REF = re.compile(r"[A-Za-z0-9_-]{1,64}")
HASH = re.compile(r"[0-9a-f]{64}")
MAX_FILES, MAX_FILE, MAX_TOTAL = 2000, 32 * 1024 * 1024, 128 * 1024 * 1024
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; img-src 'none'; object-src 'none'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)


def _read(path, limit):
    if not path.is_file():
        raise ValueError("regular file required")
    with path.open("rb") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError("file bound exceeded")
    return value


def load_views(config_path, expected_sha256):
    """Snapshot only a caller-pinned manifest allowlist; no filesystem HTTP routes."""
    config_path = private_output(config_path)
    raw = _read(config_path, 256 * 1024)
    if sha(raw) != expected_sha256 or len(raw) > 256 * 1024:
        raise ValueError("host configuration binding differs")
    config = _decode(raw.decode("utf-8"))
    return _snapshot_views(config)


def _snapshot_views(config):
    if (
        not isinstance(config, dict)
        or set(config) != {"views"}
        or not isinstance(config["views"], list)
        or not 1 <= len(config["views"]) <= 16
    ):
        raise ValueError("bounded view registrations required")
    files, views, total = {}, [], 0
    for entry in config["views"]:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"ref", "label", "manifest", "sha256", "fixture"}
            or not isinstance(entry["ref"], str)
            or not REF.fullmatch(entry["ref"])
            or any(row["ref"] == entry["ref"] for row in views)
            or not isinstance(entry["label"], str)
            or not 0 < len(entry["label"]) <= 160
            or type(entry["fixture"]) is not bool
            or not isinstance(entry["sha256"], str)
            or not HASH.fullmatch(entry["sha256"])
            or not isinstance(entry["manifest"], str)
            or not Path(entry["manifest"]).is_absolute()
        ):
            raise ValueError("invalid view registration")
        path = private_output(entry["manifest"])
        manifest_raw = _read(path, 1024 * 1024)
        if len(manifest_raw) > 1024 * 1024 or sha(manifest_raw) != entry["sha256"]:
            raise ValueError("view manifest binding differs")
        manifest = _decode(manifest_raw.decode("utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("object manifest required")
        inventory = manifest.get("files")
        if (
            manifest.get("kind") != "WorkspaceReadOnlyView"
            or not isinstance(inventory, dict)
            or not 1 <= len(inventory) <= MAX_FILES
            or not {"atlas.html", "atlas-binding.json", "workspace-index.json"}
            <= inventory.keys()
        ):
            raise ValueError("atlas view manifest required")
        prefix = "/views/" + entry["ref"] + "/"
        snapshot = {}
        for name, expected in inventory.items():
            if not isinstance(expected, str) or not HASH.fullmatch(expected):
                raise ValueError("invalid file hash")
            source = safe_path(path.parent, name)
            if not source.is_file() or source.stat().st_size > MAX_FILE:
                raise ValueError("file bound exceeded")
            data = _read(source, MAX_FILE)
            total += len(data)
            if len(data) > MAX_FILE or total > MAX_TOTAL or sha(data) != expected:
                raise ValueError("view file binding differs or bound exceeded")
            snapshot[name] = data
        index_sha = sha(snapshot["workspace-index.json"])
        binding = _decode(snapshot["atlas-binding.json"].decode("utf-8"))
        index = _decode(snapshot["workspace-index.json"].decode("utf-8"))
        if (
            not isinstance(binding, dict)
            or index_sha != manifest.get("index_sha256")
            or binding.get("index_sha256") != index_sha
            or binding.get("kind") != "WorkspaceEvidenceAtlas"
            or not isinstance(index, dict)
            or not isinstance(index.get("project_id"), str)
            or not 0 < len(index["project_id"]) <= 128
            or binding.get("project_id") != index["project_id"]
            or binding.get("execution_authority") is not False
            or not isinstance(binding.get("files"), dict)
            or not {
                "atlas.html",
                "atlas.css",
                "atlas-ui.js",
                "atlas-model.js",
                "atlas-data.js",
            }
            <= binding["files"].keys()
            or any(
                name not in snapshot or sha(snapshot[name]) != expected
                for name, expected in binding["files"].items()
            )
        ):
            raise ValueError("atlas/index binding differs")
        for name, data in snapshot.items():
            files[prefix + name] = data
        files[prefix + "view-manifest.json"] = manifest_raw
        views.append(
            dict(
                ref=entry["ref"],
                label=entry["label"],
                url=prefix + "atlas.html",
                index_sha256=index_sha,
                fixture=entry["fixture"],
                manifest_sha256=entry["sha256"],
                project_id=index["project_id"],
            )
        )
    return files, views


class AtlasHost(SessionHttpServer):
    """Read-only by default; explicit runtime ownership is transferred on success."""

    def __init__(
        self,
        *,
        files,
        views,
        connection=None,
        maintenance_db=None,
        maintenance_inbox=None,
        presentation=None,
        capability_state=None,
        native_runtime=None,
        scope_api=None,
        harness_ops=None,
        stage_actions=None,
        credential=None,
        native_script=None,
        **options,
    ):
        self.credential = (
            credential if credential is not None else secrets.token_urlsafe(32)
        )
        token_authenticator({self.credential: "local-viewer"})  # Validate token syntax.
        self.authenticate = token_authenticator({self.credential: "local-viewer"})
        api = SessionApi(authenticate=self.authenticate)
        self.native_runtime, self.native_cases = native_runtime, {}
        self._native_owned = False
        self._native_closed = False
        self.native_shutdown = None
        if native_runtime is not None:
            if (
                credential is None
                or not isinstance(native_runtime.api, SessionApi)
                or not callable(native_runtime.bindings)
                or not callable(native_runtime.shutdown)
            ):
                raise ValueError("explicit server runtime and credential required")
            api = native_runtime.api
            self.authenticate = api._authenticate
            registrations = native_runtime.bindings()
            if not isinstance(registrations, dict) or not 1 <= len(registrations) <= 16:
                raise ValueError("bounded native registrations required")
            for project_ref, declared in registrations.items():
                with api._access(self.credential, project_ref) as (_, _, binding, _):
                    actual = {
                        name: binding[name]
                        for name in ("project_id", "index_sha256", "input_version")
                    }
                    if declared != actual:
                        raise ValueError("runtime registration differs")
                    matches = [
                        row
                        for row in views
                        if row["project_id"] == actual["project_id"]
                        and row["index_sha256"] == actual["index_sha256"]
                    ]
                    if not matches:
                        raise ValueError("native registration has no bound atlas view")
                    for row in matches:
                        if row["ref"] in self.native_cases:
                            raise ValueError("ambiguous native case registration")
                        self.native_cases[row["ref"]] = dict(
                            actual, project_ref=project_ref
                        )
        if scope_api is not None and (
            native_runtime is None
            or not isinstance(scope_api, ScopeApi)
            or scope_api.api is not api
        ):
            raise ValueError("scope requires the same explicit native runtime")
        self.stage_actions = stage_actions
        self.stage_cases = bind_stages(stage_actions, files, views, credential)
        self.query_cases = (
            stage_actions.planned_queries.bindings()
            if stage_actions is not None and stage_actions.planned_queries is not None
            else {}
        )
        self._stage_owned = self._stage_closed = False
        self.scope_api = scope_api
        self.harness_ops = harness_ops
        self.harness_cases = bind_operations(harness_ops, files, views, credential)
        self._harness_owned = False
        self._harness_closed = False
        self.connection_check = deepcopy(connection or {"status": "not-checked"})
        self.presentation = deepcopy(
            presentation or dict(language="en", density="comfortable")
        )
        if self.presentation.get("language") not in {
            "en",
            "zh-Hans",
            "zh-Hant",
        } or self.presentation.get("density") not in {"comfortable", "compact"}:
            raise ValueError("invalid presentation settings")
        self.capability_state = deepcopy(
            capability_state or dict(native="disabled", maintenance="disabled")
        )
        self._maintenance_owned = maintenance_db is not None
        self._assets, self.views = dict(files), deepcopy(views)
        self.maintenance = None
        assets = Path(__file__).parent / "web"
        for filename, route in (
            ("atlas-host.js", "/host-panel.js"),
            ("atlas-host.css", "/host-panel.css"),
        ):
            self._assets[route] = (assets / filename).read_bytes()
        harness_script, harness_style = "", ""
        if harness_ops is not None:
            for filename in ("harness-panel.js", "harness-panel.css"):
                self._assets["/" + filename] = _read(assets / filename, 256 * 1024)
            harness_script = '<script src="/harness-panel.js"></script>'
            harness_style = '<link rel="stylesheet" href="/harness-panel.css">'
        stage_script, stage_style = "", ""
        if stage_actions is not None:
            for filename in ("stage-panel.js", "stage-panel.css"):
                self._assets["/" + filename] = _read(assets / filename, 256 * 1024)
            stage_script = '<script src="/stage-panel.js"></script>'
            stage_style = '<link rel="stylesheet" href="/stage-panel.css">'
            if self.query_cases:
                self._assets["/stage-query-panel.js"] = (
                    assets / "stage-query-panel.js"
                ).read_bytes()
                stage_script += '<script src="/stage-query-panel.js"></script>'
        native_scripts, native_style = [], ""
        if native_script is not None:
            if (
                not isinstance(native_script, bytes)
                or not 0 < len(native_script) <= 256 * 1024
            ):
                raise ValueError("bounded trusted native script required")
            self._assets["/native-atlas-chat.js"] = native_script
            native_scripts = ["/native-atlas-chat.js"]
        elif native_runtime is not None:
            for filename in (
                "session-panel.css",
                "session-panel.js",
                "native-atlas-chat.js",
            ):
                self._assets["/" + filename] = _read(assets / filename, 256 * 1024)
            native_style = '<link rel="stylesheet" href="/session-panel.css">'
            native_scripts = ["/session-panel.js", "/native-atlas-chat.js"]
        if scope_api is not None:
            if "/session-panel.js" not in native_scripts:
                raise ValueError("scope requires the standard session panel")
            for filename in ("session-scope.js", "session-scope.css"):
                self._assets["/" + filename] = _read(assets / filename, 256 * 1024)
            native_style += '<link rel="stylesheet" href="/session-scope.css">'
            native_scripts.append("/session-scope.js")
        self.host_binding = {
            "kind": "WorkspaceAtlasHostOverlay",
            "execution_authority": False,
            "harness_operations": deepcopy(self.harness_cases),
            "stage_operations": deepcopy(self.stage_cases),
            "planned_query_operations": deepcopy(self.query_cases),
            "stage_operation_scope": "offline-saved-stage-input"
            if self.stage_cases
            else "disabled",
            "harness_operation_scope": "offline-saved-input"
            if self.harness_cases
            else "disabled",
            "harness_capabilities": list(ACTIONS) if self.harness_cases else [],
            "harness_research_execution": False,
            "harness_model_execution": False,
            "views": deepcopy(views),
            "base_files": {key: sha(raw) for key, raw in files.items()},
        }
        for row in views:
            route = row["url"]
            text = self._assets[route].decode("utf-8")
            if text.count("connect-src 'none'") != 1 or text.count("</body>") != 1:
                raise ValueError("atlas host template contract differs")
            text = text.replace("connect-src 'none'", "connect-src 'self'")
            text = text.replace(
                '<html lang="en"',
                '<html lang="'
                + self.presentation["language"]
                + '" data-atlas-density="'
                + self.presentation["density"]
                + '"',
                1,
            )
            text = text.replace('<option value="en" selected>', '<option value="en">')
            text = text.replace(
                '<option value="' + self.presentation["language"] + '"',
                '<option selected value="' + self.presentation["language"] + '"',
                1,
            )
            text = text.replace(
                "</body>",
                '<link rel="stylesheet" href="/host-panel.css">'
                + native_style
                + harness_style
                + stage_style
                + ('<script src="/host-bootstrap/' + row["ref"] + '.js"></script>')
                + harness_script
                + stage_script
                + '<script src="/host-panel.js"></script>'
                + "".join(
                    '<script src="' + route + '"></script>' for route in native_scripts
                )
                + "</body>",
            )
            self._assets[route] = text.encode("utf-8")
        self.host_binding["served_files"] = {
            key: sha(raw) for key, raw in self._assets.items()
        }
        self._assets["/host-binding.json"] = canonical(self.host_binding)
        self._assets["/"] = self._landing()
        if maintenance_db is not None and maintenance_inbox is not None:
            raise ValueError("choose one maintenance registration")
        if maintenance_inbox is not None:
            from .maintenance_inbox import MaintenanceInbox

            bindings = {
                row["ref"]: {
                    name: row[name]
                    for name in ("project_id", "index_sha256", "manifest_sha256")
                }
                for row in views
            }
            if (
                not isinstance(maintenance_inbox, MaintenanceInbox)
                or maintenance_inbox._bindings != bindings
            ):
                raise ValueError("registered inbox binding differs")
            self.maintenance = maintenance_inbox
        if maintenance_db is not None:
            from .maintenance_inbox import MaintenanceInbox

            self.maintenance = MaintenanceInbox(
                maintenance_db,
                {
                    row["ref"]: {
                        name: row[name]
                        for name in ("project_id", "index_sha256", "manifest_sha256")
                    }
                    for row in views
                },
            )
        try:
            super().__init__(api, **options)
            self._native_owned = native_runtime is not None
            self._harness_owned = harness_ops is not None
            self._stage_owned = stage_actions is not None
        except BaseException:
            if self.maintenance is not None and self._maintenance_owned:
                self.maintenance.close()
            raise
        self.RequestHandlerClass = AtlasHandler

    def _landing(self):
        cards = "".join(
            '<li><a href="'
            + row["url"]
            + '">'
            + html.escape(row["label"])
            + "</a><p>"
            + ("Repository fixture" if row["fixture"] else "Bound view")
            + " · "
            + row["index_sha256"][:16]
            + "…</p></li>"
            for row in self.views
        )
        return (
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Harness | Workspace cases</title><link rel="stylesheet" '
            'href="/host-panel.css"><body class="host-home"><main>'
            "<h1>Harness research studio</h1><p>Choose a complete bound workspace. "
            "Repository fixtures do not represent live research.</p><ul>"
            + cards
            + "</ul><p>Codex connection check: "
            + html.escape(self.connection_check["status"])
            + (
                ". A planned-query service is registered; each query still needs its separate research permit. Model research execution is not enabled."
                if self.query_cases
                else ". Research/model execution is not enabled."
            )
            + "</p></main></body></html>"
        ).encode("utf-8")

    def server_close(self):
        try:
            super().server_close()
        finally:
            try:
                if self._native_owned and not self._native_closed:
                    self._native_closed = True
                    try:
                        self.native_shutdown = self.native_runtime.shutdown(timeout=10)
                    except BaseException as error:
                        self.native_shutdown = {
                            "status": "unknown",
                            "error": type(error).__name__,
                        }
                        raise
            finally:
                try:
                    if self._harness_owned and not self._harness_closed:
                        self._harness_closed = True
                        self.harness_ops.close()
                finally:
                    try:
                        if self._stage_owned and not self._stage_closed:
                            self._stage_closed = True
                            self.stage_actions.close()
                    finally:
                        if self.maintenance is not None and self._maintenance_owned:
                            self.maintenance.close()


class AtlasHandler(SessionHandler):
    def _native(self, method):
        match = re.fullmatch(
            r"/api/native/projects/([A-Za-z0-9_-]{1,128})(?:/.*)?", self.path
        )
        allowed = {row["project_ref"] for row in self.server.native_cases.values()}
        if match is None or match.group(1) not in allowed:
            self._reply(404, {"error": "native-project-unavailable"})
        else:
            if ScopeWikiSessionHandler._is_scope(self):
                if self.server.scope_api is None:
                    self._reply(404, {"error": "scope-unavailable"})
                else:
                    ScopeWikiSessionHandler._scope(self, method)
            else:
                self._handle(method)

    def do_GET(self):
        if self.path.startswith("/api/stages/"):
            return handle_stages(self, "GET")
        if self.path.startswith("/api/harness/"):
            return handle_operations(self, "GET")
        if self.path.startswith("/api/native/"):
            return self._native("GET")
        try:
            for name in ("Host", "Origin", "Content-Length", "Transfer-Encoding"):
                if len(self.headers.get_all(name, [])) > 1:
                    raise SessionApiError("duplicate-safety-header", 400)
            if (
                self.headers.get("Host") != self.server.expected_host
                or self.headers.get("Origin") not in (None, self.server.expected_origin)
                or self.headers.get("Sec-Fetch-Site")
                not in (None, "none", "same-origin")
            ):
                raise SessionApiError("origin-or-host-rejected", 403)
            if (
                self.headers.get("Transfer-Encoding") is not None
                or self.headers.get("Content-Length", "0") != "0"
            ):
                raise SessionApiError("invalid-read-request", 400)
            if self.path == "/api/connection":
                token, _ = self._headers("GET")
                if self.server.authenticate(token) is None:
                    raise SessionApiError("credential-rejected", 401)
                return self._reply(200, self.server.connection_check)
            route, separator, query = self.path.partition("?")
            match = re.fullmatch(
                r"/api/maintenance/([A-Za-z0-9_-]{1,64})(?:/([A-Za-z0-9._:-]{1,128}))?",
                route,
            )
            if match:
                self._feedback_auth("GET")
                options = {}
                if separator:
                    if match.group(2) or not query or len(query) > 128:
                        raise SessionApiError("invalid-history-query", 400)
                    try:
                        fields = parse_qs(
                            query,
                            keep_blank_values=True,
                            strict_parsing=True,
                            max_num_fields=2,
                        )
                        if set(fields) - {"after_seq", "limit"} or any(
                            len(values) != 1
                            or re.fullmatch(r"0|[1-9][0-9]{0,18}", values[0]) is None
                            for values in fields.values()
                        ):
                            raise ValueError("invalid history query")
                        options = {
                            name: int(values[0]) for name, values in fields.items()
                        }
                    except ValueError:
                        raise SessionApiError("invalid-history-query", 400) from None
                result = (
                    self.server.maintenance.get(match.group(1), match.group(2))
                    if match.group(2)
                    else self.server.maintenance.history(match.group(1), **options)
                )
                return self._reply(200, result)
            match = re.fullmatch(
                r"/host-bootstrap/([A-Za-z0-9_-]{1,64})\.js", self.path
            )
            if match:
                ref = match.group(1)
                if not any(row["ref"] == ref for row in self.server.views):
                    raise SessionApiError("unknown-view", 404)
                raw = (
                    b"window.WORKSPACE_HOST="
                    + json.dumps(
                        dict(
                            credential=self.server.credential,
                            current_case=ref,
                            cases=self.server.views,
                            connection=self.server.connection_check,
                            maintenance_enabled=self.server.maintenance is not None,
                            capability_state=self.server.capability_state,
                        ),
                        ensure_ascii=True,
                        allow_nan=False,
                    )
                    .replace("<", "\\u003c")
                    .encode()
                    + b";\n"
                )
                native = self.server.native_cases.get(ref)
                harness = self.server.harness_cases.get(ref)
                raw += (
                    b"window.WORKSPACE_HARNESS="
                    + json.dumps(
                        dict(
                            enabled=harness is not None,
                            project_ref=ref if harness else None,
                            index_sha256=harness["index_sha256"] if harness else None,
                        ),
                        ensure_ascii=True,
                        allow_nan=False,
                    )
                    .replace("<", "\\u003c")
                    .encode()
                    + b";\n"
                )
                stage = self.server.stage_cases.get(ref)
                query = self.server.query_cases.get(ref)
                raw += (
                    b"window.WORKSPACE_PLANNED_QUERIES="
                    + json.dumps(
                        dict(
                            enabled=query is not None,
                            project_ref=ref if query else None,
                            index_sha256=query["index_sha256"] if query else None,
                            input_version=query["input_version"] if query else None,
                        ),
                        ensure_ascii=True,
                        allow_nan=False,
                    )
                    .replace("<", "\\u003c")
                    .encode()
                    + b";\n"
                )
                raw += (
                    b"window.WORKSPACE_STAGE_ACTIONS="
                    + json.dumps(
                        dict(
                            enabled=stage is not None,
                            project_ref=ref if stage else None,
                            index_sha256=stage["index_sha256"] if stage else None,
                            input_version=stage["input_version"] if stage else None,
                        ),
                        ensure_ascii=True,
                        allow_nan=False,
                    )
                    .replace("<", "\\u003c")
                    .encode()
                    + b";\n"
                )
                bootstrap = dict(
                    credential=self.server.credential,
                    current_case=ref,
                    enabled=native is not None,
                    project_ref=native["project_ref"] if native else None,
                    index_sha256=native["index_sha256"]
                    if native
                    else next(
                        row["index_sha256"]
                        for row in self.server.views
                        if row["ref"] == ref
                    ),
                    input_version=native["input_version"] if native else None,
                )
                raw += (
                    b"window.WORKSPACE_NATIVE_ATLAS="
                    + json.dumps(bootstrap, ensure_ascii=True, allow_nan=False)
                    .replace("<", "\\u003c")
                    .encode()
                    + b";\n"
                )
            else:
                raw = self.server._assets.get(self.path)
            if raw is None:
                raise SessionApiError("unknown-route", 404)
            kinds = {
                ".js": "text/javascript",
                ".css": "text/css",
                ".html": "text/html",
                ".json": "application/json",
                ".md": "text/plain",
                ".bib": "text/plain",
            }
            kind = (
                "text/html"
                if self.path == "/"
                else kinds.get(Path(self.path).suffix, "application/octet-stream")
            )
            self._remaining()
            self.send_response(200)
            for name, value in (
                ("Content-Type", kind),
                ("Content-Length", str(len(raw))),
                ("Cache-Control", "no-store"),
                ("Connection", "close"),
                ("X-Content-Type-Options", "nosniff"),
                ("Content-Security-Policy", CSP),
                ("Cross-Origin-Resource-Policy", "same-origin"),
                ("Referrer-Policy", "no-referrer"),
            ):
                self.send_header(name, value)
            self.close_connection = True
            self.end_headers()
            self.wfile.write(raw)
        except SessionApiError as error:
            self._reply(error.status, {"error": error.code})
        except ValueError:
            self._reply(400, {"error": "feedback-rejected"})
        except (TimeoutError, OSError):
            self.close_connection = True

    def _feedback_auth(self, method):
        token, length = self._headers(method)
        if self.headers.get("Sec-Fetch-Site") not in (None, "none", "same-origin"):
            raise SessionApiError("cross-site-rejected", 403)
        if self.server.authenticate(token) is None:
            raise SessionApiError("credential-rejected", 401)
        if self.server.maintenance is None:
            raise SessionApiError("feedback-not-enabled", 404)
        return length

    def do_POST(self):
        if self.path.startswith("/api/stages/"):
            return handle_stages(self, "POST")
        if self.path.startswith("/api/harness/"):
            return handle_operations(self, "POST")
        if self.path.startswith("/api/native/"):
            return self._native("POST")
        try:
            match = re.fullmatch(r"/api/maintenance/([A-Za-z0-9_-]{1,64})", self.path)
            if not match:
                raise SessionApiError("read-only-host", 405)
            length = self._feedback_auth("POST")
            if self.headers.get("Content-Type", "").lower() != "application/json":
                raise SessionApiError("json-content-type-required", 415)
            if not 0 < length <= 8192:
                raise SessionApiError("feedback-body-bound-exceeded", 413)
            self._remaining()
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise SessionApiError("partial-body", 400)
            try:
                body = _decode(raw.decode("utf-8"))
            except (ValueError, UnicodeError, RecursionError):
                raise SessionApiError("invalid-json", 400) from None
            if not isinstance(body, dict) or set(body) != {"stage", "message", "key"}:
                raise SessionApiError("feedback-fields-rejected", 400)
            self._remaining()
            result = self.server.maintenance.submit(
                match.group(1),
                body["stage"],
                body["message"],
                body["key"],
                before_commit=self._remaining,
            )
            self._reply(200, result)
        except SessionApiError as error:
            self._reply(error.status, {"error": error.code})
        except ValueError:
            self._reply(409, {"error": "feedback-rejected"})
        except (TimeoutError, OSError):
            self.close_connection = True
        except Exception:
            self._reply(500, {"error": "feedback-save-failed"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--interface-contract", type=Path)
    parser.add_argument("--interface-sha256")
    parser.add_argument("--config-schema", type=Path)
    parser.add_argument("--config-schema-sha256")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--check-codex", action="store_true")
    parser.add_argument("--codex", type=Path)
    parser.add_argument("--codex-sha256")
    parser.add_argument("--probe-root", type=Path)
    parser.add_argument("--maintenance-db", type=Path)
    parser.add_argument("--harness-operations-root", type=Path)
    parser.add_argument("--harness-operations-reuse", action="store_true")
    args = parser.parse_args()
    if args.harness_operations_reuse and args.harness_operations_root is None:
        parser.error("--harness-operations-reuse requires --harness-operations-root")
    from .host_config import load_config, create_host

    config = load_config(
        args.config,
        args.config_sha256,
        contract_path=args.interface_contract,
        expected_contract_sha256=args.interface_sha256,
        schema_path=args.config_schema,
        expected_schema_sha256=args.config_schema_sha256,
    )
    connection = None
    if args.check_codex:
        if not all((args.codex, args.codex_sha256, args.probe_root)):
            parser.error(
                "connection check needs executable/hash/new private probe root"
            )
        root = private_output(args.probe_root)
        root.mkdir()  # Exclusive new attempt; never overwrite a prior receipt.
        cwd = root / "cwd"
        cwd.mkdir()
        from .codex_probe import run_probe

        connection = run_probe(args.codex, args.codex_sha256, cwd, root / "probe.jsonl")
    credential, operations = secrets.token_urlsafe(32), None
    if args.harness_operations_root is not None:
        from .harness_host import create_harness_operations

        operations = create_harness_operations(
            config["files"],
            config["views"],
            args.harness_operations_root,
            credential,
            reuse=args.harness_operations_reuse,
        )
    try:
        server = create_host(
            config,
            connection=connection,
            port=args.port,
            maintenance_db=args.maintenance_db,
            credential=credential,
            harness_ops=operations,
        )
    except BaseException:
        if operations is not None:
            operations.close()
        raise
    url = server.expected_origin + "/"
    print(url, flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

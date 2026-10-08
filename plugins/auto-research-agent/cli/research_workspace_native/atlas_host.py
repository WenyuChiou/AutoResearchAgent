"""Serve explicitly pinned atlas views with a separate read-only Codex check.

The host never creates/resumes threads, dispatches turns or changes research data.
Its loopback bootstrap is for one local user, not multi-tenant authentication.
"""

import argparse
from copy import deepcopy
import html
import json
from pathlib import Path
import re
import secrets
import webbrowser

from stage1_deliverable.common import canonical, private_output, safe_path, sha
from .http import SessionHandler, SessionHttpServer, token_authenticator
from .session_api import SessionApi, SessionApiError
from .transport import _decode

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
        if (
            not isinstance(binding, dict)
            or index_sha != manifest.get("index_sha256")
            or binding.get("index_sha256") != index_sha
            or binding.get("kind") != "WorkspaceEvidenceAtlas"
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
            )
        )
    return files, views


class AtlasHost(SessionHttpServer):
    """Reuse accepted socket bounds with an empty, inaccessible native facade."""

    def __init__(self, *, files, views, connection=None, **options):
        self.credential = secrets.token_urlsafe(32)
        self.authenticate = token_authenticator({self.credential: "local-viewer"})
        self.connection_check = deepcopy(connection or {"status": "not-checked"})
        self._assets, self.views = dict(files), deepcopy(views)
        assets = Path(__file__).parent / "web"
        for filename, route in (
            ("atlas-host.js", "/host-panel.js"),
            ("atlas-host.css", "/host-panel.css"),
        ):
            self._assets[route] = (assets / filename).read_bytes()
        self.host_binding = {
            "kind": "WorkspaceAtlasHostOverlay",
            "execution_authority": False,
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
                "</body>",
                '<link rel="stylesheet" href="/host-panel.css">'
                '<script src="/host-bootstrap/' + row["ref"] + '.js"></script>'
                '<script src="/host-panel.js"></script></body>',
            )
            self._assets[route] = text.encode("utf-8")
        self.host_binding["served_files"] = {
            key: sha(raw) for key, raw in self._assets.items()
        }
        self._assets["/host-binding.json"] = canonical(self.host_binding)
        self._assets["/"] = self._landing()
        # No registered controller; /api/native routes are not exposed below.
        super().__init__(SessionApi(authenticate=self.authenticate), **options)
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
            + ". Research/model execution is not enabled.</p></main></body></html>"
        ).encode("utf-8")


class AtlasHandler(SessionHandler):
    def do_GET(self):
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
                        ),
                        ensure_ascii=True,
                        allow_nan=False,
                    )
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
        except (TimeoutError, OSError):
            self.close_connection = True

    def do_POST(self):
        self._reply(405, {"error": "read-only-host"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--check-codex", action="store_true")
    parser.add_argument("--codex", type=Path)
    parser.add_argument("--codex-sha256")
    parser.add_argument("--probe-root", type=Path)
    args = parser.parse_args()
    files, views = load_views(args.config, args.config_sha256)
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
    server = AtlasHost(files=files, views=views, connection=connection, port=args.port)
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

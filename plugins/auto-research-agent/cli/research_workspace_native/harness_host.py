"""Loopback routes for trusted, saved-input Harness operations; no model calls."""

from contextlib import closing
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs

from stage1_deliverable.common import private_output, safe_path, sha
from .harness_ops import HarnessOps
from .http import token_authenticator
from .session_api import SessionApiError
from .transport import _decode

ROUTE = re.compile(
    r"/api/harness/projects/([A-Za-z0-9_-]{1,64})"
    r"(?:/(actions)(?:/([A-Za-z0-9][A-Za-z0-9._-]{0,119}))?"
    r"|/artifacts/([A-Za-z0-9][A-Za-z0-9._-]{0,119})/"
    r"(operation\.json|literature/[A-Za-z0-9._-]{1,64}))?"
)


def bind_operations(service, files, views, credential):
    """Validate exact ref/project/raw-index identities before taking ownership."""
    if service is None:
        return {}
    if not isinstance(service, HarnessOps) or credential is None:
        raise ValueError("explicit HarnessOps and credential required")
    bindings = service.bindings()
    for ref, binding in bindings.items():
        matches = [row for row in views if row["ref"] == ref]
        if len(matches) != 1 or binding != {
            name: matches[0][name] for name in ("project_id", "index_sha256")
        }:
            raise ValueError("Harness operation/view binding differs")
        raw = files.get("/views/" + ref + "/workspace-index.json")
        if not isinstance(raw, bytes) or sha(raw) != binding["index_sha256"]:
            raise ValueError("Harness operation/snapshot binding differs")
        service.view(credential, ref)  # Check that the supplied token can read it.
    return bindings


def create_harness_operations(files, views, root, credential, *, reuse=False):
    """Construct from verified snapshots; explicitly reuse an unchanged journal.

    This is a trusted embedding helper, not a path/factory accepted over HTTP.
    A failed construction retains its root; never overwrite an earlier attempt.
    Reuse changes owner/credential only, not saved action or source identities.
    """
    if type(reuse) is not bool:
        raise ValueError("explicit boolean reuse required")
    authenticate = token_authenticator({credential: "local-viewer"})
    registrations = {}
    for row in views:
        ref = row["ref"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", ref) or ref in registrations:
            raise ValueError("invalid operation view ref")
        raw = files.get("/views/" + ref + "/workspace-index.json")
        if not isinstance(raw, bytes) or sha(raw) != row["index_sha256"]:
            raise ValueError("operation snapshot binding differs")
        if _decode(raw.decode("utf-8")).get("project_id") != row["project_id"]:
            raise ValueError("operation project binding differs")
        registrations[ref] = dict(
            index_raw=raw,
            index_sha256=row["index_sha256"],
            output_root=Path(root).absolute() / ref,
            principals=["local-viewer"],
        )
    root = private_output(root)
    database = root / "operations.sqlite3"
    if reuse:
        if not root.is_dir() or not private_output(database).is_file():
            raise ValueError("existing regular operations database required")
        for suffix in ("", "-wal", "-shm", "-journal"):
            safe_path(database.parent, database.name + suffix)
        expected = {
            "harness-ops-" + sha(ref.encode())[:32]: dict(
                project_ref=ref,
                index_sha256=value["index_sha256"],
                output_root=private_output(value["output_root"]).resolve().as_posix(),
            )
            for ref, value in registrations.items()
        }
        with closing(
            sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        ) as saved:
            rows = saved.execute("SELECT id,state FROM projects").fetchall()
            if {row[0] for row in rows} != set(expected):
                raise ValueError("saved Harness registration set differs")
            for project_id, raw in rows:
                state = _decode(raw)
                if (
                    state.get("harness_ops_binding") != expected[project_id]
                    or state.get("index_sha256") != expected[project_id]["index_sha256"]
                ):
                    raise ValueError("saved Harness operation binding differs")
    else:
        root.mkdir(exist_ok=False)
    return HarnessOps(
        database,
        registrations=registrations,
        authenticate=authenticate,
    )


def handle_operations(handler, method):
    """Use the existing HTTP guards and the server's accept-time deadline."""
    try:
        token, length = handler._headers(method)
        if handler.headers.get("Sec-Fetch-Site") not in (None, "none", "same-origin"):
            raise SessionApiError("cross-site-rejected", 403)
        if handler.server.authenticate(token) is None:
            raise SessionApiError("credential-rejected", 401)
        route, separator, query = handler.path.partition("?")
        match = ROUTE.fullmatch(route)
        if not match or handler.server.harness_ops is None:
            raise SessionApiError("harness-route-unavailable", 404)
        ref, actions, key, artifact_key, name = match.groups()
        if ref not in handler.server.harness_cases:
            raise SessionApiError("harness-project-unavailable", 404)
        handler._remaining()
        service = handler.server.harness_ops
        if method == "GET":
            if length:
                raise SessionApiError("invalid-read-request", 400)
            if artifact_key:
                try:
                    fields = parse_qs(
                        query,
                        keep_blank_values=True,
                        strict_parsing=True,
                        max_num_fields=1,
                    )
                    if (
                        not separator
                        or set(fields) != {"sha256"}
                        or len(fields["sha256"]) != 1
                    ):
                        raise ValueError("invalid artifact query")
                except ValueError:
                    raise SessionApiError("invalid-artifact-query", 400) from None
                raw = service.artifact(
                    token, ref, artifact_key, name, fields["sha256"][0]
                )
                handler._remaining()
                handler.send_response(200)
                kind = (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    if name.endswith(".xlsx")
                    else "application/octet-stream"
                )
                for header, value in (
                    ("Content-Type", kind),
                    ("Content-Length", str(len(raw))),
                    (
                        "Content-Disposition",
                        'attachment; filename="' + Path(name).name + '"',
                    ),
                    ("Cache-Control", "no-store"),
                    ("Connection", "close"),
                    ("X-Content-Type-Options", "nosniff"),
                    ("Cross-Origin-Resource-Policy", "same-origin"),
                    ("Content-Security-Policy", "default-src 'none'; sandbox"),
                    ("Referrer-Policy", "no-referrer"),
                ):
                    handler.send_header(header, value)
                handler.close_connection = True
                handler.end_headers()
                handler.wfile.write(raw)
                return
            if separator or (actions and not key):
                raise SessionApiError("invalid-history-route", 400)
            result = (
                service.get_action(token, ref, key) if key else service.view(token, ref)
            )
        else:
            if separator or actions != "actions" or key or artifact_key:
                raise SessionApiError("unknown-harness-write-route", 404)
            if handler.headers.get("Content-Type", "").lower() != "application/json":
                raise SessionApiError("json-content-type-required", 415)
            if not 0 < length <= 8192:
                raise SessionApiError("harness-body-bound-exceeded", 413)
            raw = handler.rfile.read(length)
            if len(raw) != length:
                raise SessionApiError("partial-body", 400)
            try:
                body = _decode(raw.decode("utf-8"))
            except (ValueError, UnicodeError, RecursionError):
                raise SessionApiError("invalid-json", 400) from None
            handler._remaining()
            result = service.execute(token, ref, body, deadline=handler.deadline)
        handler._remaining()
        handler._reply(200, result)
    except SessionApiError as error:
        result = {"error": error.code}
        if error.receipt is not None:
            result["receipt"] = error.receipt
        handler._reply(error.status, result)
    except (TimeoutError, OSError):
        handler.close_connection = True  # Saved actions remain queryable.
    except Exception:
        handler._reply(500, {"error": "harness-service-failure"})

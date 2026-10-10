"""Explicit planned-query routes inside the existing stage service/AtlasHost."""

import re
from pathlib import Path

from .planned_queries import PlannedQueryService
from .session_api import SessionApiError
from .transport import _decode
from .planned_query_contract import tree_sha

ROUTE = re.compile(
    r"/api/stages/projects/([A-Za-z0-9_-]{1,64})/queries"
    r"(?:/(offer|actions)(?:/([A-Za-z0-9][A-Za-z0-9._-]{0,119}))?)?"
)


def bind_query_registration(service, registrations):
    if not isinstance(service, PlannedQueryService):
        raise ValueError("explicit PlannedQueryService required")
    for ref, binding in service.bindings().items():
        stage = registrations.get(ref)
        if stage is None or any(binding[k] != stage[k] for k in binding):
            raise ValueError("query/stage registration differs")
        if set(service._projects[ref]["item"]["principals"]) != set(
            stage["principals"]
        ):
            raise ValueError("query/stage principals differ")
        source = stage["inputs"].get(1, stage["inputs"].get("1"))
        query = service._projects[ref]["item"]
        if (
            not source
            or Path(source["ledger_root"]).resolve().as_posix()
            != query["parent_ledger_root"]
            or tree_sha(source["ledger_root"]) != query["parent_ledger_sha256"]
        ):
            raise ValueError("query/stage parent source differs")


def bind_query_views(stages, bindings, credential):
    service = stages.planned_queries
    if service is None:
        return {}
    for ref, binding in service.bindings().items():
        if binding != bindings.get(ref):
            raise ValueError("query/stage view differs")
        service.view(credential, ref)
    return service.bindings()


def handle_queries(handler, method):
    try:
        token, length = handler._headers(method)
        if handler.headers.get("Sec-Fetch-Site") not in (None, "none", "same-origin"):
            raise SessionApiError("cross-site-rejected", 403)
        if handler.server.authenticate(token) is None:
            raise SessionApiError("credential-rejected", 401)
        match = ROUTE.fullmatch(handler.path)
        stages = handler.server.stage_actions
        service = stages.planned_queries if stages is not None else None
        if not match or service is None:
            raise SessionApiError("planned-query-unavailable", 404)
        ref, action, key = match.groups()
        if ref not in handler.server.stage_cases or ref not in service.bindings():
            raise SessionApiError("query-project-unavailable", 404)
        handler._remaining()
        if method == "GET":
            if (
                length
                or (action == "offer" and key)
                or (action == "actions" and not key)
            ):
                raise SessionApiError("invalid-query-read", 400)
            result = (
                service.offer(token, ref)
                if action == "offer"
                else service.get_action(token, ref, key)
                if key
                else service.view(token, ref)
            )
        else:
            if action != "actions" or key:
                raise SessionApiError("unknown-query-write", 404)
            if handler.headers.get("Content-Type", "").lower() != "application/json":
                raise SessionApiError("json-content-type-required", 415)
            if not 0 < length <= 8192:
                raise SessionApiError("query-body-bound-exceeded", 413)
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
        handler._reply(error.status, {"error": error.code})
    except (TimeoutError, OSError):
        handler.close_connection = True
    except Exception:
        handler._reply(500, {"error": "planned-query-service-failure"})

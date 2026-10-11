"""Bounded source controls; HTTP never owns or dispatches a source worker."""

import re

from .session_api import SessionApiError
from .transport import _decode

ROUTE = re.compile(
    r"/api/projects/([A-Za-z0-9_-]{1,64})/stage1/sources"
    r"(?:/(authorize|execute|history|works/([A-Za-z0-9_-]{1,128})))?"
)


def handle_sources(handler, method):
    """Delegate only opaque refs to the server-owned project service.

    The service enforces strict field/version/hash validation and durable
    history. A successful queued action is not an acquired/parsed/read source.
    """
    called = None
    try:
        token, length = handler._headers(method)
        if handler.headers.get("Sec-Fetch-Site") not in (None, "none", "same-origin"):
            raise SessionApiError("cross-site-rejected", 403)
        if handler.server.authenticate(token) is None:
            raise SessionApiError("credential-rejected", 401)
        match = ROUTE.fullmatch(handler.path)
        if match is None:
            raise SessionApiError("unknown-project-route", 404)
        service = handler.server.project_stage1_sources
        if service is None:
            raise SessionApiError("stage1-source-controls-unconnected", 409)
        ref, action, work_ref = match.groups()
        handler._remaining()
        if method == "GET":
            if length or action in {"authorize", "execute"}:
                raise SessionApiError("invalid-project-read", 400)
            if work_ref is not None:
                result = service.offers(token, ref, work_ref)
            elif action == "history":
                result = service.history(token, ref)
            else:
                result = service.read(token, ref)
        else:
            if action not in {"authorize", "execute"}:
                raise SessionApiError("unknown-project-write", 404)
            if handler.headers.get("Content-Type", "").lower() != "application/json":
                raise SessionApiError("json-content-type-required", 415)
            if not 0 < length <= 4096:
                raise SessionApiError("stage1-source-body-bound-exceeded", 413)
            raw = handler.rfile.read(length)
            if len(raw) != length:
                raise SessionApiError("partial-body", 400)
            try:
                body = _decode(raw.decode("utf-8"))
            except (ValueError, UnicodeError, RecursionError):
                raise SessionApiError("invalid-json", 400) from None
            handler._remaining()
            called = "stage1-source-" + action
            result = getattr(service, action)(
                token, ref, body, check_deadline=handler._remaining
            )
            dispatcher = getattr(
                handler.server, "project_stage1_source_dispatcher", None
            )
            if (
                action == "execute"
                and dispatcher is not None
                and result.get("status") == "saved"
                and result.get("job_status") == "queued"
                and result.get("replayed") is False
            ):
                result = dict(
                    result,
                    dispatch=dispatcher.submit_saved(token, ref, body["key"], result),
                )
        handler._remaining()
        handler._reply(200, result)
    except SessionApiError as error:
        response = {"error": error.code}
        if called is not None and type(body) is dict:
            try:
                response["receipt"] = handler.server.projects.record_refusal(
                    token, body.get("key"), ref, called, body, error.code
                )
            except (SessionApiError, ValueError, OSError, KeyError, TypeError):
                pass
        handler._reply(error.status, response)
    except (TimeoutError, OSError):
        handler.close_connection = True
    except (ValueError, UnicodeError, KeyError, TypeError):
        handler._reply(400, {"error": "project-input-rejected"})
    except Exception:
        handler._reply(500, {"error": "stage1-source-operation-failed"})

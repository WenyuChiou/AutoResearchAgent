"""Source-bound loopback routes for saved-input stage checks and review requests."""

import re

from stage1_deliverable.common import sha
from .stage_actions import StageActions
from .session_api import SessionApiError
from .transport import _decode

ROUTE = re.compile(
    r"/api/stages/projects/([A-Za-z0-9_-]{1,64})"
    r"(?:/(actions)(?:/([A-Za-z0-9][A-Za-z0-9._-]{0,119}))?"
    r"|/offers/([12])/(checkpoint-stage1|inspect-stage2|review-stage))?"
)


def bind_stages(service, files, views, credential):
    if service is None:
        return {}
    if not isinstance(service, StageActions) or credential is None:
        raise ValueError("explicit StageActions and credential required")
    bindings = service.bindings()
    for ref, binding in bindings.items():
        matches = [row for row in views if row["ref"] == ref]
        if len(matches) != 1 or any(
            binding[k] != matches[0][k] for k in ("project_id", "index_sha256")
        ):
            raise ValueError("stage action/view binding differs")
        raw = files.get("/views/" + ref + "/workspace-index.json")
        if not isinstance(raw, bytes) or sha(raw) != binding["index_sha256"]:
            raise ValueError("stage action/snapshot binding differs")
        service.view(credential, ref)
    return bindings


def handle_stages(handler, method):
    try:
        token, length = handler._headers(method)
        if handler.headers.get("Sec-Fetch-Site") not in (None, "none", "same-origin"):
            raise SessionApiError("cross-site-rejected", 403)
        if handler.server.authenticate(token) is None:
            raise SessionApiError("credential-rejected", 401)
        match = ROUTE.fullmatch(handler.path)
        if not match or handler.server.stage_actions is None:
            raise SessionApiError("stage-route-unavailable", 404)
        ref, actions, key, stage, action = match.groups()
        if ref not in handler.server.stage_cases:
            raise SessionApiError("stage-project-unavailable", 404)
        handler._remaining()
        service = handler.server.stage_actions
        if method == "GET":
            if length or (actions and not key):
                raise SessionApiError("invalid-stage-read", 400)
            if stage:
                result = service.offer(token, ref, int(stage), action)
            else:
                result = (
                    service.get_action(token, ref, key)
                    if key
                    else service.view(token, ref)
                )
        else:
            if actions != "actions" or key or stage:
                raise SessionApiError("unknown-stage-write", 404)
            if handler.headers.get("Content-Type", "").lower() != "application/json":
                raise SessionApiError("json-content-type-required", 415)
            if not 0 < length <= 8192:
                raise SessionApiError("stage-body-bound-exceeded", 413)
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
        handler._reply(500, {"error": "stage-service-failure"})

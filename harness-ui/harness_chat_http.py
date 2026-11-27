"""Wiki V1 chat routes on the ordinary Host; native execution never runs in HTTP threads.

Without an explicit operator grant the routes exist but only report "not configured":
no store is opened, no file is written and no Codex process can start.
"""

import re
from urllib.parse import parse_qs, urlsplit

from harness_chat_reasons import explain
from harness_chat_tools import HarnessChatTools

PREFIX = "/api/v9/chat/"
STAGE = re.compile(r"[1-6]")
POST_ROUTES = ("send", "answer", "stop", "reconcile")


class UnconfiguredChat:
    """The default service: answers status, refuses everything else, touches nothing."""

    spec = None
    running = {}

    def __init__(self, reason="operator-chat-config-required"):
        self.reason = reason

    def status(self, project, stage, principal=None):
        reason = explain(self.reason)
        return dict(
            kind="V9HarnessConversation",
            project_ref=project,
            stage=stage,
            panel_state="not-configured",
            content_hidden=True,
            panel_reason=reason,
            enabled=False,
            disabled_reason=self.reason,
            connect_check=dict(ok=False, reasons=[reason]),
            spend_check=dict(
                ok=False,
                reasons=[],
                remaining_turns=0,
                money_cap_usd=None,
                money_metering="unknown",
            ),
            can_send=False,
            codex_login="unknown-until-send",
            other_turn=None,
            read_only=True,
            execution_authorized=False,
            formal_selection=False,
            research_execution=False,
            context=dict(
                project_ref=project, stage=stage, materials=[], content_hidden=True
            ),
            binding=None,
            sessions=[],
            turns=[],
            hidden_turn_count=0,
            reserved_turns=0,
            reserved_seconds=0,
            max_turns=0,
            remaining_turns=0,
            expires_at=None,
            turn_seconds=None,
            model=None,
            effort=None,
            local_admission_ready=False,
            admission_blockers=[self.reason],
            controllable_turn_ids=[],
            live_native_connection_verified=False,
        )

    def _refuse(self, *_args, **_kwargs):
        raise ValueError(self.reason)

    start = answer = stop = reconcile = _refuse

    def close(self):
        pass


def install_chat(
    host,
    materials,
    root,
    spec=None,
    *,
    rpc_factory=None,
    stage_registry=None,
    disabled_reason=None,
):
    """Mount the chat routes on a Host. ``spec=None`` installs the inert "not configured" service."""
    from research_workspace_native.session_api import SessionApiError
    from research_workspace_native.transport import _decode

    if spec is None:
        service = UnconfiguredChat(disabled_reason or "operator-chat-config-required")
    else:
        from harness_chat import ChatService

        service = ChatService(
            root,
            HarnessChatTools(host, materials, stage_registry),
            spec,
            rpc_factory=rpc_factory,
            recover_on_start=True,
        )
    host.harness_chat = service
    parent = host.RequestHandlerClass

    class Handler(parent):
        def chat(self, method):
            try:
                credential, length = self._headers(method)
                if self.headers.get("Sec-Fetch-Site") not in (
                    None,
                    "none",
                    "same-origin",
                ):
                    raise SessionApiError("cross-site-rejected", 403)
                principal = host.authenticate(credential)
                if principal is None:
                    raise SessionApiError("credential-rejected", 401)
                if method == "GET":
                    if length:
                        raise SessionApiError("invalid-read-request", 400)
                    parsed = urlsplit(self.path)
                    query = parse_qs(parsed.query, strict_parsing=True)
                    if (
                        parsed.path != PREFIX + "state"
                        or set(query) != {"project", "stage"}
                        or any(len(x) != 1 for x in query.values())
                    ):
                        raise SessionApiError("unknown-chat-route", 404)
                    if not STAGE.fullmatch(query["stage"][0]):
                        raise ValueError("chat-stage-not-supported")
                    value = service.status(
                        query["project"][0], int(query["stage"][0]), principal
                    )
                else:
                    route = self.path[len(PREFIX) :]
                    if route not in POST_ROUTES:
                        raise SessionApiError("unknown-chat-route", 404)
                    if self.headers.get("Origin") != host.expected_origin:
                        raise SessionApiError("chat-explicit-origin-required", 403)
                    if (
                        self.headers.get("Content-Type", "").lower()
                        != "application/json"
                        or not 0 < length <= 20000
                    ):
                        raise SessionApiError("small-json-body-required", 415)
                    self._remaining()
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise SessionApiError("partial-body", 400)
                    try:
                        body = _decode(raw.decode("utf-8"))
                    except (ValueError, UnicodeError, RecursionError):
                        raise SessionApiError("invalid-json", 400) from None
                    if not isinstance(body, dict):
                        raise SessionApiError("object-required", 400)
                    if route == "send":
                        value = service.start(body, principal)
                    elif route == "answer":
                        value = service.answer(body)
                    elif set(body) == {"turn_id"}:
                        value = getattr(service, route)(body["turn_id"])
                    else:
                        raise SessionApiError("unknown-chat-route", 404)
                return self._reply(200, value)
            except SessionApiError as exc:
                return self._reply(exc.status, {"error": exc.code})
            except (ValueError, KeyError, TypeError, OSError) as exc:
                code = (
                    str(exc) if isinstance(exc, ValueError) else "chat-state-unreadable"
                )
                return self._reply(
                    409,
                    {
                        "error": code,
                        "reason": explain(code),
                        "research_execution": False,
                    },
                )

        def do_GET(self):
            if self.path.startswith(PREFIX):
                return self.chat("GET")
            return super().do_GET()

        def do_POST(self):
            if self.path.startswith(PREFIX):
                return self.chat("POST")
            return super().do_POST()

    host.RequestHandlerClass = Handler
    return service

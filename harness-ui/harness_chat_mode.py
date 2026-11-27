"""An outer HTTP write gate for an explicitly authorized chat-only host.

This adapter does not load permits, initialize native processes, start turns,
or alter budget stores. The original chat handler and continuation checks keep
ownership of authentication, payload validation, permission and reservation.
"""

from copy import deepcopy


ALLOWED_POST_PATHS = (
    "/api/v9/chat/send",
    "/api/v9/chat/answer",
    "/api/v9/chat/stop",
)
READ_ACTIONS = frozenset(
    {
        "state",
        "materials",
        "read_material",
        "read_saved_stage",
        "read_paper",
        "inspect_workflow",
        "handoff_status",
    }
)
_DISABLED_CAPABILITIES = (
    "material_registration",
    "local_review_notes",
    "offline_workflow_preparation",
    "formal_selection",
    "research_execution",
)


def install_chat_only(host):
    """Restrict a host to three exact chat POST routes and unchanged GETs.

    Install last, after all other handler adapters. This gate does not replace
    the original handler for allowed requests, so same-origin checks, local
    authentication and JSON/body limits remain in force. PUT/PATCH/DELETE are
    always rejected, including on the three allowed POST paths. No reconcile,
    material write, workflow prepare, research or cleanup route is offered.
    """
    if getattr(host, "_chat_only_installed", False):
        raise ValueError("chat-only-already-installed")
    service = host.harness_chat
    spec = getattr(service, "spec", None)
    if not isinstance(spec, dict) or spec.get("_continuation") is not True:
        raise ValueError("chat-only-continuation-config-required")
    actions = spec.get("actions")
    if (
        not isinstance(actions, list)
        or not actions
        or any(
            not isinstance(action, str) or action not in READ_ACTIONS
            for action in actions
        )
        or len(set(actions)) != len(actions)
    ):
        raise ValueError("chat-only-read-actions-required")
    allowed_actions = frozenset(actions)
    parent = host.RequestHandlerClass
    original_status = service.status

    def status(project, stage):
        original = original_status(project, stage)
        if not isinstance(original, dict) or not isinstance(
            original.get("context"), dict
        ):
            raise ValueError("chat-only-status-context-invalid")
        result = deepcopy(original)
        context = result["context"]
        supported = context.get("supported_actions", [])
        if not isinstance(supported, list):
            raise ValueError("chat-only-supported-actions-invalid")
        context["supported_actions"] = [
            action
            for action in supported
            if isinstance(action, str) and action in allowed_actions
        ]
        capabilities = context.get("capabilities", {})
        if not isinstance(capabilities, dict):
            raise ValueError("chat-only-capabilities-invalid")
        context["capabilities"] = dict(capabilities)
        for name in _DISABLED_CAPABILITIES:
            context["capabilities"][name] = False
        context["capabilities"]["stage_execution"] = "not-authorized"
        # Registered is distinct from currently enabled or admission-ready.
        # In particular, preserve disabled_reason, blockers and budget state.
        result.update(
            chat_only=True,
            connection_preparation=False,
            registered_config_activated=True,
            research_execution=False,
            formal_selection=False,
        )
        return result

    class Handler(parent):
        def chat_only_write_rejected(self):
            self.close_connection = True
            return self._reply(
                405,
                dict(
                    error="chat-only-write-not-allowed",
                    chat_only=True,
                    connection_preparation=False,
                    registered_config_activated=True,
                    formal_selection=False,
                    execution_authorized=False,
                    research_execution=False,
                ),
            )

        def do_POST(self):
            if self.path in ALLOWED_POST_PATHS:
                return super().do_POST()
            return self.chat_only_write_rejected()

        do_PUT = chat_only_write_rejected
        do_PATCH = chat_only_write_rejected
        do_DELETE = chat_only_write_rejected

    binding = dict(
        mode="chat-only",
        allowed_post_paths=list(ALLOWED_POST_PATHS),
        other_http_writes_enabled=False,
        material_writes_enabled=False,
        workflow_preparation_enabled=False,
        formal_selection=False,
        research_execution=False,
        native_started_by_install=False,
        authentication="original-authenticated-chat-handler",
        chat_message_permission="original-continuation-and-budget-checks",
        tools="continuation-read-actions-only",
    )
    service.status = status
    host.RequestHandlerClass = Handler
    host.host_binding["chat_only"] = binding
    # Do not update app assets or /host-binding.json here. The caller seals them
    # after every adapter and mode-specific report field has been installed.
    host._chat_only_installed = True
    return deepcopy(binding)

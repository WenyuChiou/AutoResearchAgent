"""Opt-in startup wiring for the Wiki V1 Codex chat on the ordinary loopback Host.

Nothing here grants permission. The operator prepares a pinned grant file (and, for a
continuation grant, a signed permit receipt) outside the page; this module only reads
them. With no ``--chat-*`` option the routes report "not configured" and cannot start
Codex. A grant that fails to load leaves the same inert service, with the reason.
"""

from pathlib import Path

from harness_chat_http import install_chat

OPTIONS = (
    "chat_config",
    "chat_config_sha256",
    "chat_root",
    "chat_permit_receipt",
    "chat_permit_receipt_sha256",
    "chat_permit_key",
)


def add_arguments(parser):
    parser.add_argument(
        "--chat-config",
        type=Path,
        help="pinned operator grant for the Codex chat (off when absent)",
    )
    parser.add_argument("--chat-config-sha256")
    parser.add_argument(
        "--chat-root",
        type=Path,
        help="private directory for conversation records (outside Git)",
    )
    parser.add_argument(
        "--chat-permit-receipt",
        type=Path,
        help="signed chat-only permit receipt (continuation grants)",
    )
    parser.add_argument("--chat-permit-receipt-sha256")
    parser.add_argument(
        "--chat-permit-key", type=Path, help="private HMAC key for the permit receipt"
    )


def validate_options(options):
    """All-or-nothing: a half-given chat setup fails at startup instead of silently opening."""
    given = {name: getattr(options, name, None) for name in OPTIONS}
    if not any(value is not None for value in given.values()):
        return
    if given["chat_config"] is None or given["chat_config_sha256"] is None:
        raise ValueError(
            "chat options require --chat-config together with --chat-config-sha256"
        )
    receipt = [
        given[k]
        for k in (
            "chat_permit_receipt",
            "chat_permit_receipt_sha256",
            "chat_permit_key",
        )
    ]
    if any(v is not None for v in receipt) and any(v is None for v in receipt):
        raise ValueError(
            "permit receipt, its SHA-256 and its key are required together"
        )


def install_wiki_chat(
    host, materials, options, *, rpc_factory=None, stage_registry=None
):
    """Mount the chat. ``rpc_factory`` is a trusted in-process test seam, never a CLI option."""
    validate_options(options)
    if getattr(options, "chat_config", None) is None:
        return install_chat(host, materials, None, None)
    from harness_chat import load_config

    verifier = None
    try:
        if options.chat_permit_receipt is not None:
            from harness_chat_permit import load_permit_verifier

            verifier = load_permit_verifier(
                options.chat_permit_receipt,
                options.chat_permit_receipt_sha256,
                options.chat_permit_key,
            )
        spec = load_config(
            options.chat_config, options.chat_config_sha256, verify_permission=verifier
        )
        root = (
            Path(spec["_owner"]).parent
            if spec.get("_continuation")
            else options.chat_root
        )
        if root is None:
            raise ValueError("chat-root-required")
        return install_chat(
            host,
            materials,
            root,
            spec,
            rpc_factory=rpc_factory,
            stage_registry=stage_registry,
        )
    except (ValueError, OSError, KeyError, TypeError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "chat-config-unreadable"
        return install_chat(host, materials, None, None, disabled_reason=reason)

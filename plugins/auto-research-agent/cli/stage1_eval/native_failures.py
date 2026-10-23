"""Classify explicit provider-incomplete events without inventing a token cap."""

import json


def incomplete_response_failure(raw):
    """Return a terminal provider failure; startup warnings are not its cause."""
    try:
        events = [json.loads(line) for line in raw.splitlines()]
    except (UnicodeDecodeError, ValueError):
        return None
    terminal = next(
        (
            event
            for event in reversed(events)
            if isinstance(event, dict)
            and event.get("type") in {"turn.completed", "turn.failed"}
        ),
        None,
    )
    if terminal is not None:
        if terminal["type"] == "turn.completed":
            return None
        candidates = [terminal]
    else:
        candidates = [
            next(
                (
                    event
                    for event in reversed(events)
                    if isinstance(event, dict) and event.get("type") == "error"
                ),
                {},
            )
        ]
    prefix = "Incomplete response returned, reason: "
    for event in candidates:
        if not isinstance(event, dict):
            continue
        if event.get("type") == "error":
            message = event.get("message")
        elif event.get("type") == "turn.failed":
            error = event.get("error")
            message = error.get("message") if isinstance(error, dict) else None
        else:
            continue
        if not isinstance(message, str) or not message.startswith(prefix):
            continue
        reason = message[len(prefix) :].strip()
        if not reason:
            continue
        category = (
            "provider-output-limit"
            if reason == "max_output_tokens"
            else "provider-incomplete"
        )
        detail = message[:512]
        if reason == "max_output_tokens":
            detail += "; actual server output-token cap unknown; not a local timeout"
        return category, detail
    return None

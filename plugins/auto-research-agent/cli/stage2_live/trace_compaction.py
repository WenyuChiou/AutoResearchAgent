"""Receipt-bound compaction attempt accounting for native trace observation."""

from .trace_files import _ref, _require
from .trace_parsing import _usage


class CompactionState:
    """Track observed request attempts without claiming execution or readiness."""

    def __init__(self):
        self.attempts = {}
        self.events = 0
        self.unverified = False
        self._scopes = {}
        self._terminals = {}

    def observe(self, row, raw):
        payload = row["payload"]
        kind = payload["type"]
        event_name = (
            payload.get("event_type", "") if kind == "protocol_event_observed" else kind
        )
        if not isinstance(event_name, str) or "compact" not in event_name.lower():
            return
        self.events += 1
        if kind == "compaction_request_started":
            self._start_native(row, payload, raw)
        elif kind in {"compaction_request_completed", "compaction_request_failed"}:
            self._finish_native(row, payload, raw, kind)
        elif kind == "compaction_started":
            self._start_legacy(row, payload)
        elif kind in {"compaction_progress", "compaction_completed"}:
            self._legacy_update(row, payload, kind)
        else:
            self.unverified = True

    def _ids(self, payload):
        compaction_id = payload.get("compaction_id")
        request_id = payload.get("compaction_request_id")
        _require(
            isinstance(compaction_id, str)
            and compaction_id
            and isinstance(request_id, str)
            and request_id,
            "compaction-request-id-invalid",
        )
        return compaction_id, request_id

    def _start_native(self, row, payload, raw):
        compaction_id, request_id = self._ids(payload)
        thread_id, turn_id = row.get("thread_id"), row.get("codex_turn_id")
        _require(
            payload.get("thread_id") == thread_id
            and payload.get("codex_turn_id") == turn_id
            and isinstance(thread_id, str)
            and thread_id
            and isinstance(turn_id, str)
            and turn_id,
            "compaction-scope-mismatch",
        )
        _, request, _ = _ref(payload, "request_payload", raw)
        _require(isinstance(request, dict), "compaction-request-invalid")
        _require(request_id not in self.attempts, "duplicate-compaction-attempt")
        self.attempts[request_id] = None
        self._scopes[request_id] = (compaction_id, thread_id, turn_id)

    def _finish_native(self, row, payload, raw, kind):
        compaction_id, request_id = self._ids(payload)
        scope = self._scopes.get(request_id)
        _require(
            scope == (compaction_id, row.get("thread_id"), row.get("codex_turn_id")),
            "compaction-scope-mismatch",
        )
        usage = None
        if kind == "compaction_request_completed":
            name, response, digest = _ref(payload, "response_payload", raw)
            _require(isinstance(response, dict), "compaction-response-invalid")
            usage = _usage(response)
            terminal = ("completed", name, digest)
        else:
            error = payload.get("error")
            _require(isinstance(error, str) and error, "compaction-error-invalid")
            terminal = ("failed", error)
        previous = self._terminals.get(request_id)
        if previous is not None:
            _require(previous == terminal, "conflicting-compaction-terminal")
            return
        self._terminals[request_id] = terminal
        self.attempts[request_id] = usage

    def _start_legacy(self, row, payload):
        attempt_id = payload.get("compaction_id")
        _require(isinstance(attempt_id, str) and attempt_id, "compaction-id-invalid")
        _require(
            all(
                isinstance(row.get(key), str) and row[key]
                for key in ("thread_id", "codex_turn_id")
            ),
            "compaction-scope-mismatch",
        )
        _require(attempt_id not in self.attempts, "duplicate-compaction-attempt")
        self.attempts[attempt_id] = None
        self._scopes[attempt_id] = (row.get("thread_id"), row.get("codex_turn_id"))

    def _legacy_update(self, row, payload, kind):
        attempt_id = payload.get("compaction_id")
        _require(isinstance(attempt_id, str) and attempt_id, "compaction-id-invalid")
        _require(attempt_id in self.attempts, "compaction-chronology-invalid")
        _require(
            self._scopes[attempt_id]
            == (row.get("thread_id"), row.get("codex_turn_id")),
            "compaction-scope-mismatch",
        )
        if kind == "compaction_completed":
            usage = _usage(payload)
            terminal = ("completed", tuple(usage.items()) if usage else None)
            previous = self._terminals.get(attempt_id)
            _require(previous in {None, terminal}, "conflicting-compaction-terminal")
            self._terminals[attempt_id] = terminal
            self.attempts[attempt_id] = usage

    def finalize(self, inference_ids):
        if set(inference_ids) & set(self.attempts):
            self.unverified = True
        return dict(self.attempts)

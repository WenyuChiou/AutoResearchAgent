"""Replay caller-attested source acquisition without authenticating scientific claims."""

from datetime import datetime

from .journal import LedgerError


def require(condition, reason):
    if not condition:
        raise LedgerError(reason)


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class SourceReads:
    def __init__(self):
        self.starts, self.finishes, self.latest = {}, {}, {}

    def check_start(self, payload, works):
        work = works.get(payload["work_id"])
        require(
            work and payload["version_id"] in work["version_ids"],
            "source-unknown-work-version",
        )
        key = (payload["work_id"], payload["version_id"])
        previous = self.latest.get(key)
        require(payload["previous_attempt_id"] == previous, "source-attempt-history")
        require(previous is None or previous in self.finishes, "source-attempt-pending")

    def check_finish(self, payload, read_ref):
        action = self.starts.get(payload["attempt_id"])
        require(
            action and payload["attempt_id"] not in self.finishes,
            "source-attempt-not-open",
        )
        require(
            timestamp(action["created_at"])
            <= timestamp(payload["observed_at"])
            <= timestamp(payload["created_at"]),
            "source-observation-time-order",
        )
        for ref in (payload["raw_ref"], payload["text_ref"]):
            if ref is not None:
                require(
                    ref["producer"] == payload["attempt_id"]
                    and ref["artifact_type"] == "raw-output",
                    "source-artifact-producer-mismatch",
                )
                read_ref(ref)
        status, outcome = payload["http_status"], payload["outcome"]
        require(
            (status == 429) == (outcome == "rate_limited"), "source-rate-limit-status"
        )
        require(
            (status in (404, 410)) == (outcome == "not_found"),
            "source-not-found-status",
        )
        if outcome == "http_error":
            require(status is not None and status >= 400, "source-http-error-status")
        if outcome == "network_error":
            require(status is None, "source-network-error-status")
        if outcome == "parse_error":
            require(status is None or 200 <= status < 300, "source-parse-error-status")
        if status is not None and status >= 400:
            require(
                outcome in {"rate_limited", "not_found", "http_error"},
                "source-http-failure-outcome",
            )
        if outcome == "available":
            require(
                (status is None or 200 <= status < 300)
                and payload["text_ref"] is not None
                and payload["extraction"] is not None,
                "source-available-needs-text",
            )
            try:
                text = read_ref(payload["text_ref"]).decode("utf-8")
            except UnicodeError as error:
                raise LedgerError("source-text-not-utf8") from error
            require(bool(text.strip()), "source-text-empty")
            if payload["extraction"]["method"] == "identity":
                require(
                    payload["raw_ref"] == payload["text_ref"],
                    "source-identity-extraction",
                )
        else:
            require(
                payload["text_ref"] is None and payload["extraction"] is None,
                "failed-source-cannot-supply-text",
            )

    def observe(self, payload, works, read_ref):
        kind = payload["kind"]
        if kind == "SourceReadStarted":
            self.check_start(payload, works)
            self.starts[payload["event_id"]] = payload
            self.latest[(payload["work_id"], payload["version_id"])] = payload[
                "event_id"
            ]
        elif kind == "SourceReadFinished":
            self.check_finish(payload, read_ref)
            self.finishes[payload["attempt_id"]] = payload

    def report(self):
        if not self.starts:
            return None
        latest_failures = [
            key
            for key in self.latest.values()
            if key in self.finishes and self.finishes[key]["outcome"] != "available"
        ]
        return dict(
            started=len(self.starts),
            completed=len(self.finishes),
            available=sum(p["outcome"] == "available" for p in self.finishes.values()),
            failed=sum(p["outcome"] != "available" for p in self.finishes.values()),
            pending=[key for key in self.starts if key not in self.finishes],
            unresolved_failure_attempt_ids=latest_failures,
            scope="caller-attested-source-acquisition; not authenticated identity or scientific verification",
        )


def replay(ledger):
    state, works = SourceReads(), {}
    for row in ledger.events():
        payload = row["payload"]
        if payload["kind"] == "CandidateRevision":
            works[payload["work_id"]] = payload
        state.observe(payload, works, ledger.read_ref)
    return state

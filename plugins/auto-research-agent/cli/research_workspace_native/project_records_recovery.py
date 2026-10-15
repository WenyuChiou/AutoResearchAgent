"""Explicit registration of committed records; never adopt an uncertain write."""

from pathlib import Path
import json

from stage1_deliverable.common import canonical, safe_path, sha
from stage1_ledger.journal import decode
from .project_intake_contract import identifier
from .project_stage1_records import ProjectStage1RecordsService
from .project_stage1_delivery import _raw, _records_match
from .session_api import SessionApiError, _check, _hash

KIND = "stage1-recover-delivery"
FIELDS = {
    "key",
    "revision",
    "input_version",
    "brief_sha256",
    "ledger_state_sha256",
    "checkpoint_event_id",
    "confirmed",
    "producer_key",
    "producer_request_sha256",
    "records_sha256",
}
HELD = {"stage1-produce-records", "stage1-register-delivery", KIND}


class ProjectRecordsRecoveryService:
    def __init__(self, records):
        _check(
            isinstance(records, ProjectStage1RecordsService),
            "saved-records-service-required",
        )
        self.records, self.intake = records, records.intake

    def _history(self, actor, ref, *, active=None):
        rows = self.intake.db.execute(
            "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=?",
            (actor, ref),
        ).fetchall()
        result = [json.loads(row["receipt"]) for row in rows]
        for row, receipt in zip(rows, result):
            _check(
                row["request_hash"]
                == receipt["request_sha256"]
                == sha(canonical(dict(kind=receipt["kind"], body=receipt["request"]))),
                "records-recovery-history-differs",
            )
        _check(
            not any(
                row["kind"] in HELD
                and row["status"] in {"intent-recorded", "execution-unknown"}
                and not (
                    active == (row["key"], row["request_sha256"])
                    and row["kind"] == KIND
                    and row["status"] == "intent-recorded"
                )
                for row in result
            ),
            "records-recovery-unresolved",
        )
        return result

    def _producer(self, context, rows, key, digest):
        actor, state, binding, _, _, report, checkpoint, *_ = context
        matches = [row for row in rows if row["key"] == key]
        _check(len(matches) == 1, "records-recovery-producer-unavailable")
        row = matches[0]
        request = row["request"]
        _check(
            row["project_ref"] == state["project_ref"]
            and row["kind"] == "stage1-produce-records"
            and row["status"] == "saved"
            and row["request_sha256"] == digest
            and request["input_version"] == binding["input_version"]
            and request["brief_sha256"] == binding["brief_sha256"]
            and request["ledger_state_sha256"] == report["state_sha256"]
            and request["checkpoint_event_id"] == checkpoint["event_id"]
            and row["write_error"] is None,
            "records-recovery-producer-stale-or-uncommitted",
        )
        events = self.intake.db.execute(
            "SELECT payload FROM intake_events WHERE project=? AND kind='stage1-produce-records-saved'",
            (state["project_ref"],),
        ).fetchall()
        _check(
            sum(json.loads(event[0]) == row for event in events) == 1,
            "records-recovery-event-differs",
        )
        entries = self.records._entries(context)
        _check(
            sha(canonical(entries)) == row["registry_sha256"],
            "records-recovery-registry-stale",
        )
        name = (
            "stage1-records-"
            + sha(
                canonical(
                    [
                        self.records._basis(context),
                        report["state_sha256"],
                        checkpoint["event_id"],
                        row["records_sha256"],
                    ]
                )
            )
            + ".json"
        )
        path = safe_path(self.records.root, name)
        _check(
            str(path) == row["records_path"]
            and Path(row["partial_path"]) == path.with_suffix(".partial"),
            "records-recovery-path-differs",
        )
        # This is the already committed file. Registration revalidates Core/source
        # semantics; it does not call the producer or rewrite any source bytes.
        records = decode(_raw(path, row["records_sha256"]), "committed records")
        from .project_stage1_delivery import _screening_library

        _records_match(
            records,
            context[4],
            path.parent,
            screening_library=_screening_library(context, records),
        )
        return row, path

    def read(self, credential, ref):
        actor = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(actor, ref)
            result = dict(
                project_ref=ref,
                revision=state["revision"],
                offers=[],
                status="no-recovery-needed",
            )
            try:
                context = self.records.delivery._context(ref)
                rows = self._history(actor, ref)
                for row in rows:
                    if (
                        row["kind"] != "stage1-produce-records"
                        or row["status"] != "saved"
                    ):
                        continue
                    try:
                        saved, _ = self._producer(
                            context, rows, row["key"], row["request_sha256"]
                        )
                    except (SessionApiError, ValueError, OSError, KeyError, TypeError):
                        continue
                    if any(
                        offer.get("records_sha256") == saved["records_sha256"]
                        and offer.get("checkpoint_event_id") == context[6]["event_id"]
                        for offer in state.get("stage1_delivery_offers", {}).values()
                    ):
                        continue
                    result["offers"].append(
                        dict(
                            producer_key=saved["key"],
                            producer_request_sha256=saved["request_sha256"],
                            records_sha256=saved["records_sha256"],
                            ledger_state_sha256=context[5]["state_sha256"],
                            checkpoint_event_id=context[6]["event_id"],
                            status="ready-for-saved-records-registration",
                        )
                    )
                if result["offers"]:
                    result["status"] = "ready-for-saved-records-registration"
            except (SessionApiError, ValueError, OSError, KeyError, TypeError) as error:
                result.update(
                    status="recovery-unavailable",
                    error=error.code
                    if isinstance(error, SessionApiError)
                    else "saved-records-verification-failed",
                )
            return result

    def recover(self, credential, ref, body, *, check_deadline=None):
        actor = self.intake._principal(credential)
        _check(
            type(body) is dict and set(body) == FIELDS and body["confirmed"] is True,
            "records-recovery-fields",
            400,
        )
        for name in ("key", "producer_key", "checkpoint_event_id"):
            identifier(body[name])
        _check(
            type(body["revision"]) is int
            and type(body["input_version"]) is int
            and all(
                _hash(body[name])
                for name in (
                    "brief_sha256",
                    "ledger_state_sha256",
                    "producer_request_sha256",
                    "records_sha256",
                )
            ),
            "records-recovery-identity",
            400,
        )
        with self.intake._lock:
            state = self.intake._load(actor, ref)
            semantic = {key: value for key, value in body.items() if key != "revision"}
            digest = sha(canonical(dict(kind=KIND, body=semantic)))
            previous = self.intake.db.execute(
                "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                (actor, ref, body["key"]),
            ).fetchone()
            if previous:
                row = json.loads(previous["receipt"])
                _check(
                    row["kind"] == KIND
                    and row["request"] == semantic
                    and previous["request_hash"] == row["request_sha256"] == digest,
                    "idempotency-payload-differs",
                )
                return self.intake._receipt(row, replayed=True)
            _check(
                body["revision"] == state["revision"]
                and body["input_version"] == state["input_version"]
                and body["brief_sha256"] == self.intake.binding(ref)["brief_sha256"],
                "records-recovery-source-version-stale",
            )
            context = self.records._context(
                ref, body["ledger_state_sha256"], require_checkpoint=True
            )
            _check(
                not any(
                    offer.get("records_sha256") == body["records_sha256"]
                    and offer.get("checkpoint_event_id") == body["checkpoint_event_id"]
                    for offer in state.get("stage1_delivery_offers", {}).values()
                ),
                "records-recovery-already-registered-read-history",
            )
            with self.records.guard(*context[3:6]) as guard:
                frontier = self.records._mutation_check(
                    ref, body["ledger_state_sha256"], guard, require_checkpoint=True
                )

                def current():
                    if check_deadline is not None:
                        check_deadline()
                    observed = frontier()
                    _check(
                        observed[6]["event_id"] == body["checkpoint_event_id"],
                        "records-recovery-checkpoint-stale",
                    )
                    row, path = self._producer(
                        observed,
                        self._history(actor, ref, active=(body["key"], digest)),
                        body["producer_key"],
                        body["producer_request_sha256"],
                    )
                    _check(
                        row["records_sha256"] == body["records_sha256"],
                        "records-recovery-bytes-differ",
                    )
                    if check_deadline is not None:
                        check_deadline()
                    return row, path

                row, path = current()
                return self.records.delivery.register_records(
                    ref,
                    records_path=path,
                    expected_records_sha256=row["records_sha256"],
                    expected_ledger_state_sha256=body["ledger_state_sha256"],
                    check_deadline=current,
                    action_body=body,
                )

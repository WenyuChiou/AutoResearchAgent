"""Explicit saved-record preparation from a current checkpoint; no research."""

import json

from stage1_deliverable.common import canonical, sha
from .project_intake_contract import identifier
from .project_stage1_records import ProjectStage1RecordsService
from .session_api import _check, _hash

FIELDS = {
    "key",
    "revision",
    "input_version",
    "brief_sha256",
    "ledger_state_sha256",
    "checkpoint_event_id",
    "confirmed",
}
KIND = "stage1-produce-records"


class ProjectRecordsPrepareService:
    def __init__(self, records):
        _check(
            isinstance(records, ProjectStage1RecordsService),
            "saved-records-service-required",
        )
        self.records, self.intake = records, records.intake

    def prepare(self, credential, ref, body, *, check_deadline=None):
        actor = self.intake._principal(credential)
        _check(
            type(body) is dict and set(body) == FIELDS and body["confirmed"] is True,
            "records-prepare-fields",
            400,
        )
        identifier(body["key"])
        identifier(body["checkpoint_event_id"])
        _check(
            type(body["revision"]) is int
            and type(body["input_version"]) is int
            and _hash(body["brief_sha256"])
            and _hash(body["ledger_state_sha256"]),
            "records-prepare-identity",
            400,
        )
        with self.intake._lock:
            state = self.intake._load(actor, ref)
            semantic = {
                name: value for name, value in body.items() if name != "revision"
            }
            request_hash = sha(canonical(dict(kind=KIND, body=semantic)))
            saved = self.intake.db.execute(
                "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                (actor, ref, body["key"]),
            ).fetchone()
            if saved:
                receipt = json.loads(saved["receipt"])
                _check(
                    receipt["kind"] == KIND
                    and receipt["request"] == semantic
                    and receipt["request_sha256"]
                    == saved["request_hash"]
                    == request_hash,
                    "idempotency-payload-differs",
                )
                return self.intake._receipt(receipt, replayed=True)
            _check(
                body["revision"] == state["revision"]
                and body["input_version"] == state["input_version"]
                and body["brief_sha256"] == self.intake.binding(ref)["brief_sha256"],
                "records-prepare-source-version-stale",
            )
            history = self.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE principal=? AND project=?",
                (actor, ref),
            ).fetchall()
            for raw in history:
                row = json.loads(raw[0])
                if row["kind"] != KIND:
                    continue
                _check(
                    row["status"] not in {"intent-recorded", "execution-unknown"},
                    "records-prepare-unresolved",
                )
                _check(
                    not (
                        row["status"] == "saved"
                        and row["request"].get("ledger_state_sha256")
                        == body["ledger_state_sha256"]
                        and row["request"].get("checkpoint_event_id")
                        == body["checkpoint_event_id"]
                    ),
                    "records-already-prepared-read-history",
                )
            if check_deadline is not None:
                check_deadline()
            return self.records.produce_records(
                ref,
                expected_ledger_state_sha256=body["ledger_state_sha256"],
                expected_checkpoint_event_id=body["checkpoint_event_id"],
                action_body=body,
                check_current=check_deadline,
            )

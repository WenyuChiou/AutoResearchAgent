"""Agent observations of provided CSV cells; no screening or evidence promotion.

The trusted caller supplies the real agent identity. Persistence uses the owned
project's existing intake action journal, never Core decisions, claims, reading
registrations or coverage. There is deliberately no HTTP/Host bootstrap here.
"""

from copy import deepcopy
import csv
import io
import json
import re

from stage1_deliverable.common import canonical, sha
from .project_intake_contract import _fields, identifier
from .session_api import _check

KIND = "stage1-local-table-observation"
FIELDS = {
    "key",
    "revision",
    "input_version",
    "brief_sha256",
    "ledger_state_sha256",
    "checkpoint_event_id",
    "work_id",
    "version_id",
    "source_ref",
    "material_sha256",
    "start_byte",
    "end_byte",
    "quote",
    "row",
    "column",
    "unit",
    "note",
}


def _text(value, maximum=512):
    _check(
        type(value) is str and 0 < len(value) <= maximum,
        "local-observation-text-invalid",
        400,
    )
    return value


def _cell(raw, body):
    """Single-line CSV records only; retain exact token bytes, not inferred prose."""
    lines = raw.splitlines(keepends=True)
    rows = list(
        csv.reader(io.StringIO(raw.decode("utf8", errors="strict"), newline=""))
    )
    row, column = body["row"], body["column"]
    _check(
        len(lines) == len(rows)
        and type(row) is int
        and 1 < row <= len(rows)
        and type(column) is int
        and 1 < column <= len(rows[0])
        and len(rows[row - 1]) == len(rows[0]),
        "local-observation-csv-locator-invalid",
        400,
    )
    line = lines[row - 1].rstrip(b"\r\n")
    offsets, start, quoted, index = [], 0, False, 0
    while index < len(line):
        byte = line[index]
        if byte == 34:
            if quoted and index + 1 < len(line) and line[index + 1] == 34:
                index += 2
                continue
            quoted = not quoted
        elif byte == 44 and not quoted:
            offsets.append((start, index))
            start = index + 1
        index += 1
    offsets.append((start, len(line)))
    _check(
        not quoted and len(offsets) == len(rows[0]),
        "local-observation-csv-shape-invalid",
    )
    begin, end = offsets[column - 1]
    prefix = sum(map(len, lines[: row - 1]))
    unit = _text(body["unit"], 128)
    _check(
        type(body["start_byte"]) is int
        and type(body["end_byte"]) is int
        and (body["start_byte"], body["end_byte"]) == (prefix + begin, prefix + end)
        and raw[prefix + begin : prefix + end] == _text(body["quote"]).encode("utf8")
        # Unit symbols are case-sensitive: g, mg and Mg are distinct. Match
        # a whole label token, never a substring of another unit or word.
        and re.search(r"(?<!\w)" + re.escape(unit) + r"(?!\w)", rows[row - 1][0])
        is not None,
        "local-observation-cell-bytes-or-unit-differs",
    )
    return dict(
        row=row,
        column=column,
        row_label=rows[row - 1][0],
        column_label=rows[0][column - 1],
        cell_text=rows[row - 1][column - 1],
        unit=unit,
        start_byte=prefix + begin,
        end_byte=prefix + end,
        quote=body["quote"],
    )


class ProjectStage1LocalObservationService:
    def __init__(self, stage1, *, agent_id):
        from .project_stage1 import ProjectStage1Service

        _check(
            isinstance(stage1, ProjectStage1Service),
            "local-observation-stage1-required",
        )
        self.stage1, self.intake = stage1, stage1.intake
        self.agent_id = _text(agent_id, 128)

    def _prepare(self, ref, state, actor, body, *, agent_id=None):
        binding = self.intake.binding(ref)
        _check(
            body["input_version"] == binding["input_version"]
            and body["brief_sha256"] == binding["brief_sha256"],
            "local-observation-input-differs",
        )
        run, ledger, report = self.stage1._ledger(state, binding)
        with ledger.writing(repair=False):
            _check(
                report["state_sha256"]
                == ledger.state_hash()
                == body["ledger_state_sha256"],
                "local-observation-ledger-stale",
            )
            checkpoint_id = run.get("last_checkpoint")
            _check(
                isinstance(checkpoint_id, str) and bool(checkpoint_id),
                "local-observation-checkpoint-required",
            )
            _check(
                checkpoint_id == body["checkpoint_event_id"],
                "local-observation-checkpoint-stale",
            )
            checkpoint = ledger.event(checkpoint_id, "Checkpoint")
            _check(
                checkpoint["state_sha256"] == report["state_sha256"],
                "local-observation-checkpoint-state-differs",
            )
            candidate = ledger.candidates().get(body["work_id"])
            matches = (
                []
                if candidate is None
                else [
                    d
                    for d in candidate["discoveries"]
                    if d["version_id"] == body["version_id"]
                    and "provided" in d
                    and d["provided"]["material_ref"] == body["source_ref"]
                ]
            )
            _check(bool(matches), "local-observation-provided-source-binding-differs")
            discovery = matches[-1]
            provided = discovery["provided"]
            _check(
                provided["original_type"].split(";")[0].strip() == "text/csv",
                "local-observation-only-csv-supported",
            )
            raw = ledger.read_ref(body["source_ref"])
            _check(
                0 < len(raw) <= 2 * 1024 * 1024 and sha(raw) == body["material_sha256"],
                "local-observation-material-hash-differs",
            )
            cell = _cell(raw, body)
            observation = dict(
                project_ref=ref,
                input_version=binding["input_version"],
                brief_sha256=binding["brief_sha256"],
                work_id=body["work_id"],
                version_id=body["version_id"],
                ledger_state_sha256=report["state_sha256"],
                checkpoint_event_id=body["checkpoint_event_id"],
                operator=dict(
                    principal=actor,
                    actor_type="agent",
                    agent_id=agent_id or self.agent_id,
                ),
                source=dict(
                    ref=deepcopy(body["source_ref"]),
                    sha256=sha(raw),
                    bytes=len(raw),
                    provided_event_id=provided["event_id"],
                    uri=provided["source_uri"],
                    original_type=provided["original_type"],
                    identity_status=provided["identity_status"],
                    candidate_identity_status=candidate["identity_status"],
                ),
                table_title=discovery["record"]["title"],
                cell=cell,
                note=_text(body["note"], 2048),
                scope="agent-local-saved-cell-only",
                human_verification=False,
                screening_decision_created=False,
                claim_evidence_created=False,
                reading_registration_complete=False,
                scientific_acceptance=False,
                grants_execution=False,
                grants_stage2_admission=False,
            )
            observation["observation_id"] = "local-observation-" + sha(
                canonical(observation)
            )
            return observation

    def record(self, credential, ref, body):
        _fields(body, FIELDS)
        identifier(body["key"])
        actor = self.intake._principal(credential)
        with self.intake._lock:
            # Replays also recheck the current project and actual source bytes.
            self._prepare(ref, self.intake._load(actor, ref), actor, body)

            def reserve(state, _digest, principal):
                self._prepare(ref, state, principal, body)

            def save(state, _digest, principal):
                return dict(
                    observation=self._prepare(ref, state, principal, body),
                    persistence="project-intake-action-journal-only",
                )

            # Server-supplied identity participates in idempotency; it is not a
            # browser/caller field, and another agent cannot reuse this write.
            request = dict(deepcopy(body), observer_agent_id=self.agent_id)
            return self.intake._perform(
                actor, ref, KIND, request, save, reserve=reserve
            )

    def read(self, credential, ref, key):
        identifier(key)
        actor = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(actor, ref)
            saved = self.intake.db.execute(
                "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                (actor, ref, key),
            ).fetchone()
            _check(saved is not None, "local-observation-not-found", 404)
            receipt = json.loads(saved["receipt"])
            _check(
                receipt["kind"] == KIND
                and receipt["status"] == "saved"
                and saved["request_hash"]
                == receipt["request_sha256"]
                == sha(canonical(dict(kind=KIND, body=receipt["request"]))),
                "local-observation-receipt-invalid",
            )
            _check(
                self._prepare(
                    ref,
                    state,
                    actor,
                    receipt["request"],
                    agent_id=_text(receipt["request"].get("observer_agent_id"), 128),
                )
                == receipt["observation"],
                "local-observation-saved-content-differs",
            )
            return self.intake._receipt(receipt)

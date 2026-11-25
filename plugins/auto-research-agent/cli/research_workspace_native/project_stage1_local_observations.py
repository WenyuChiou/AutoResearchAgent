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


def _declared_unit(label, *, column=False):
    """Return a whole unit, or no column unit for a classification/annotation.

    Rows still require exactly one explicit unit. Columns also recognize whole
    bare units, except the established bare A classification. Unknown explicit
    declarations and conflicting units fail closed on save, read and replay.
    """
    # Case matters in symbols. Prefixes are only permitted on SI-style bases;
    # in (inch) and Hg are literal atoms and must never lose their first atom.
    bases = (
        "m",
        "g",
        "s",
        "L",
        "l",
        "A",
        "K",
        "mol",
        "cd",
        "Hz",
        "N",
        "Pa",
        "J",
        "W",
        "C",
        "V",
        "F",
        "ohm",
        "Ω",
        "S",
        "Wb",
        "T",
        "H",
    )
    prefixes = (
        "",
        "p",
        "n",
        "u",
        "µ",
        "μ",
        "m",
        "c",
        "d",
        "da",
        "h",
        "k",
        "M",
        "G",
        "T",
    )
    atoms = {p + b for p in prefixes for b in bases}
    atoms.update(
        ("in", "ft", "yd", "mi", "oz", "lb", "h", "min", "d", "Hg", "%", "°C", "°F")
    )
    atom = (
        "(?:"
        + "|".join(re.escape(a) for a in sorted(atoms, key=lambda a: (-len(a), a)))
        + ")"
    )
    factor = atom + r"(?:\^[+-]?\d+|[⁻⁺⁰¹²³⁴⁵⁶⁷⁸⁹]+)?"
    expression = factor + r"(?:(?:\s*[/·*]\s*|\s+)" + factor + r")*"
    # In prose, "in" is a preposition only before these explicit count/scale
    # and currency declarations. Unknown "in ..." stays unclassified.
    words = r"(?:dollars|cents|percent|units|thousands|millions|billions)(?: of (?:dollars|units))?"
    annotations = {
        "estimated",
        "provisional",
        "preliminary",
        "seasonally adjusted",
        "not seasonally adjusted",
    }

    def literal(declared):
        if re.fullmatch(expression, declared):
            return declared
        if re.fullmatch(words, declared):
            return declared
        if declared.startswith("in ") and re.fullmatch(words, declared[3:]):
            return declared[3:]
        return None

    def bare_declaration(text):
        # A complete expression has priority: mg/L and in Hg are single
        # units, not lists of choices. Never choose an operand from a list.
        unit = literal(text)
        if unit is not None:
            return unit
        relation = re.search(
            r"\b(?:and\s*/\s*or|or|and|versus|vs|to)\b", text, re.IGNORECASE
        )
        unit_tokens = re.findall(
            r"(?<!\w)(?:" + expression + "|" + words + r")(?!\w)", text
        )
        # A choice/list is not a single declaration, even when an option is
        # outside the unit vocabulary. Do not guess whether its words mean
        # units or categories. Whole-token recognition additionally catches
        # multiple known units without relying on a particular separator.
        _check(
            len(unit_tokens) < 2
            and not relation
            and not any(c in text for c in "/·*^%()[];,|&+\\"),
            "local-observation-unit-evidence-ambiguous",
        )
        return None

    label = label.strip()
    start = label.find("(")
    if start < 0:
        _check(column, "local-observation-unit-evidence-unavailable")
        # Only A has established historical classification evidence. Explicit
        # (A) remains amperes; this exception does not cover other unit symbols.
        if label == "A":
            return None
        # A complete numeric age interval selects a population, not the
        # measurement unit of its cells. For example an income row keeps
        # dollars under an open-ended age column. Full-label matching is
        # essential: extra unit choices or declarations must still refuse.
        if re.fullmatch(
            r"(?:(?:under|over)\s+[0-9]+\s+years?"
            r"|[0-9]+(?:\s*[-–]\s*|\s+to\s+)[0-9]+\s+years?"
            r"|[0-9]+\s+years?\s+(?:and|or)\s+(?:older|younger|over|under))",
            label,
            re.IGNORECASE,
        ):
            return None
        return bare_declaration(label)

    suffix = label[start:]
    groups = re.findall(r"\(([^()]+)\)", suffix)
    remainder = re.sub(r"\([^()]+\)|\[\d+\]", "", suffix)
    _check(not remainder.strip(), "local-observation-unit-evidence-ambiguous")
    candidates = []
    prefix = label[:start].strip()
    prefix_unit = bare_declaration(prefix)
    if column:
        # A with extra syntax is not the approved bare-A exception. Do not
        # infer whether a newly ambiguous prefix means a category or amperes.
        _check(prefix != "A", "local-observation-unit-evidence-ambiguous")
        if prefix_unit is not None:
            candidates.append(prefix_unit)
    for group in groups:
        declared = group.strip()
        unit = literal(declared)
        if unit is not None:
            candidates.append(unit)
        else:
            _check(declared in annotations, "local-observation-unit-evidence-ambiguous")
    _check(
        len(candidates) == 1 or (column and not candidates),
        "local-observation-unit-evidence-ambiguous",
    )
    return candidates[0] if candidates else None


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
    declared_unit = _declared_unit(rows[row - 1][0])
    column_label = rows[0][column - 1]
    column_unit = _declared_unit(column_label, column=True)
    if column_unit is not None:
        _check(
            column_unit == declared_unit,
            "local-observation-row-column-unit-conflict",
        )
    _check(
        type(body["start_byte"]) is int
        and type(body["end_byte"]) is int
        and (body["start_byte"], body["end_byte"]) == (prefix + begin, prefix + end)
        and raw[prefix + begin : prefix + end] == _text(body["quote"]).encode("utf8")
        and unit == declared_unit,
        "local-observation-cell-bytes-or-unit-differs",
    )
    return dict(
        row=row,
        column=column,
        row_label=rows[row - 1][0],
        column_label=column_label,
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

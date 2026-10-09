"""Summarize bound, supplied timing records without reading or executing evidence."""

from datetime import datetime, timezone
import re

from stage1_deliverable.common import DeliverableError


PHASES = (
    "intake",
    "search",
    "acquisition",
    "reading-screening",
    "identity-version",
    "filing-export",
    "handoff",
    "html-acceptance",
    "engineering",
    "ci-wait",
)
RESEARCH_PHASES = frozenset(PHASES[:-2])
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)"
)


def _require(condition, message):
    if not condition:
        raise DeliverableError("run timing: " + message)


def _timestamp(value, name):
    _require(
        isinstance(value, str) and _TIMESTAMP.fullmatch(value),
        name + " must be an offset timestamp",
    )
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _require(result.utcoffset() is not None, name + " lacks an offset")
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError) as error:
        raise DeliverableError("run timing: invalid " + name) from error


def _union_seconds(intervals):
    """Return null without a completed measurement; merge overlaps otherwise."""
    if not intervals:
        return None
    ordered = sorted(intervals)
    start, end = ordered[0]
    total = 0.0
    for next_start, next_end in ordered[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += (end - start).total_seconds()
            start, end = next_start, next_end
    return total + (end - start).total_seconds()


def summarize_timing(record, *, project_id, input_version, index_sha256):
    """Return a new report of measured unions, never a completion/quality gate.

    Future means after the record's observed_at, so the function stays pure.
    Supplied evidence references are retained, not opened or authenticated.
    """
    _require(isinstance(record, dict), "record must be an object")
    fields = {
        "kind",
        "schema_version",
        "project_id",
        "input_version",
        "index_sha256",
        "started_at",
        "ended_at",
        "observed_at",
        "intervals",
    }
    _require(set(record) == fields, "record fields differ")
    _require(
        record["kind"] == "Stage1RunTiming" and record["schema_version"] == "1.0.0",
        "unsupported record version",
    )
    for name, expected in (
        ("project_id", project_id),
        ("input_version", input_version),
    ):
        valid = (type(expected) is str and bool(expected.strip())) or (
            name == "input_version" and type(expected) is int and expected > 0
        )
        _require(valid, "invalid expected " + name)
        _require(
            type(record[name]) is type(expected) and record[name] == expected,
            "stale or wrong " + name,
        )
    _require(
        isinstance(index_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", index_sha256),
        "invalid expected index hash",
    )
    _require(record["index_sha256"] == index_sha256, "stale or wrong index hash")
    started = _timestamp(record["started_at"], "started_at")
    observed = _timestamp(record["observed_at"], "observed_at")
    ended = (
        None
        if record["ended_at"] is None
        else _timestamp(record["ended_at"], "ended_at")
    )
    _require(started <= observed, "run starts after observation")
    if ended is not None:
        _require(started <= ended <= observed, "reversed or future run end")
    bound = ended if ended is not None else observed
    _require(isinstance(record["intervals"], list), "intervals must be a list")
    completed = {phase: [] for phase in PHASES}
    pending = {phase: [] for phase in PHASES}
    rows, seen = [], set()
    interval_fields = {"id", "phase", "started_at", "ended_at", "evidence_refs"}
    for interval in record["intervals"]:
        _require(
            isinstance(interval, dict) and set(interval) == interval_fields,
            "malformed interval",
        )
        identity, phase = interval["id"], interval["phase"]
        _require(
            isinstance(identity, str) and bool(identity.strip()), "invalid interval id"
        )
        _require(identity not in seen, "duplicate interval id")
        seen.add(identity)
        _require(isinstance(phase, str) and phase in completed, "unknown phase")
        refs = interval["evidence_refs"]
        _require(
            isinstance(refs, list)
            and bool(refs)
            and all(isinstance(ref, str) and bool(ref.strip()) for ref in refs),
            "evidence_refs must be nonempty strings",
        )
        start = _timestamp(interval["started_at"], "interval started_at")
        end = (
            None
            if interval["ended_at"] is None
            else _timestamp(interval["ended_at"], "interval ended_at")
        )
        _require(started <= start <= bound, "interval starts outside observed run")
        if end is not None:
            _require(start <= end <= bound, "reversed, future or out-of-run interval")
            completed[phase].append((start, end))
        else:
            pending[phase].append(identity)
        rows.append(
            {
                "id": identity,
                "phase": phase,
                "started_at": interval["started_at"],
                "ended_at": interval["ended_at"],
                "evidence_refs": list(refs),
                "status": "pending" if end is None else "measured",
                "duration_seconds": None
                if end is None
                else (end - start).total_seconds(),
            }
        )
    phases = {}
    for phase in PHASES:
        phases[phase] = {
            "status": (
                "pending"
                if pending[phase]
                else "measured"
                if completed[phase]
                else "unmeasured"
            ),
            "duration_seconds": _union_seconds(completed[phase]),
            "completed_interval_count": len(completed[phase]),
            "pending_interval_ids": list(pending[phase]),
        }
    research = [
        pair
        for phase in PHASES
        if phase in RESEARCH_PHASES
        for pair in completed[phase]
    ]
    return {
        "kind": "Stage1RunTimingReport",
        "schema_version": "1.0.0",
        "project_id": project_id,
        "input_version": input_version,
        "index_sha256": index_sha256,
        "started_at": record["started_at"],
        "ended_at": record["ended_at"],
        "observed_at": record["observed_at"],
        "wall_seconds": (bound - started).total_seconds(),
        "finished_run_seconds": None
        if ended is None
        else (ended - started).total_seconds(),
        "research_active_seconds": _union_seconds(research),
        "engineering_seconds": _union_seconds(completed["engineering"]),
        "ci_wait_seconds": _union_seconds(completed["ci-wait"]),
        "known_active_seconds_lower_bound": _union_seconds(
            research + completed["engineering"]
        ),
        "completed_interval_seconds": _union_seconds(
            [pair for phase in PHASES for pair in completed[phase]]
        ),
        "phases": phases,
        "intervals": rows,
        "attestation_limitations": [
            "Supplied timestamps and evidence references are not independently authenticated.",
            "Pending intervals and unmeasured phases have no inferred completed duration.",
            "Active lower bound merges completed research and engineering intervals, excluding CI wait.",
            "Timing establishes no budget compliance, Stage 1 completion or scientific quality.",
        ],
    }

"""Optional owner-inspected producer navigation over Stage 1 progress."""

from copy import deepcopy
import re

from .project_stage1_progress import project_progress
from .session_api import SessionApiError


QUEUE_FIELDS = {
    "kind",
    "schema_version",
    "binding",
    "ledger_state_sha256",
    "status",
    "next_action",
    "remaining_work_count",
    "blocked_work_count",
    "research_complete",
}
BINDING_FIELDS = {"project_ref", "revision", "input_version", "brief_sha256"}
ACTION_FIELDS = {"phase_id", "target", "reason"}
PRODUCER_PHASES = {"screening", "reading", "coverage"}


def _invalid():
    raise SessionApiError("stage1-producer-queue-invalid")


def _hash(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _text(value):
    return type(value) is str and 0 < len(value) <= 256 and bool(value.strip())


def _count(value):
    return type(value) is int and value >= 0


def _validated_queue(overview, queue):
    if type(queue) is not dict or set(queue) != QUEUE_FIELDS:
        _invalid()
    if (
        type(queue["kind"]) is not str
        or queue["kind"] != "ProjectStage1ProducerQueue"
        or type(queue["schema_version"]) is not str
        or queue["schema_version"] != "1.0.0"
        or type(queue["status"]) is not str
        or queue["status"] not in {"ready", "held", "idle"}
        or queue["research_complete"] is not False
        or not _count(queue["remaining_work_count"])
        or not _count(queue["blocked_work_count"])
        or not _hash(queue["ledger_state_sha256"])
    ):
        _invalid()

    project = overview.get("project") if type(overview) is dict else None
    stage = overview.get("stage1") if type(overview) is dict else None
    ledger = stage.get("ledger") if type(stage) is dict else None
    binding = queue["binding"]
    if (
        type(project) is not dict
        or type(binding) is not dict
        or set(binding) != BINDING_FIELDS
        or type(project.get("project_ref")) is not str
        or not project["project_ref"]
        or type(project.get("revision")) is not int
        or project["revision"] < 0
        or type(project.get("input_version")) is not int
        or project["input_version"] <= 0
        or not _hash(project.get("brief_sha256"))
        or any(
            type(binding[key]) is not type(project[key]) or binding[key] != project[key]
            for key in BINDING_FIELDS
        )
        or type(ledger) is not dict
        or not _hash(ledger.get("state_sha256"))
        or queue["ledger_state_sha256"] != ledger["state_sha256"]
    ):
        _invalid()

    action = queue["next_action"]
    if queue["status"] == "idle":
        if action is not None:
            _invalid()
        return queue
    if (
        type(action) is not dict
        or set(action) != ACTION_FIELDS
        or type(action["phase_id"]) is not str
        or action["phase_id"] not in PRODUCER_PHASES
        or not _text(action["target"])
        or not _text(action["reason"])
    ):
        _invalid()
    return queue


def project_producer_progress(overview, queue=None):
    """Overlay a validated navigation-only producer queue on shared progress."""
    if queue is None:
        return project_progress(overview)
    queue = _validated_queue(overview, queue)
    progress = project_progress(overview)
    if queue["status"] == "idle":
        return progress

    current = progress.get("next_action")
    phases = progress.get("phases")
    if (
        type(current) is not dict
        or current.get("phase_id") not in PRODUCER_PHASES
        or type(phases) is not list
        or any(type(row) is dict and row.get("status") == "held" for row in phases)
    ):
        return progress

    result = deepcopy(progress)
    chosen = queue["next_action"]["phase_id"]
    for row in result["phases"]:
        if row.get("phase_id") == chosen:
            row["status"] = "available" if queue["status"] == "ready" else "held"
            row["reason"] = queue["next_action"]["reason"]
            break
    result["next_action"] = deepcopy(queue["next_action"])
    return result

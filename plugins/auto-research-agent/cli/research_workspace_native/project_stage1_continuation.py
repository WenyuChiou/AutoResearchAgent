"""Bounded Python-only scheduling over existing authenticated Stage1 owners.

Trusted adapters must reopen durable receipts and obtain ``project_progress``
under their existing lock. These typed projections check shape and binding;
they do not attest native execution, grant permission, or validate research.
Handler return values never establish completion. No state is persisted here.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
import re
import time

from stage1_ledger.journal import canonical
from stage1_deliverable.common import sha
from .project_stage1_progress import PHASES

KINDS = frozenset(
    {
        "planning",
        "query",
        "screen",
        "source",
        "reading",
        "coverage",
        "records",
        "delivery",
        "atlas",
    }
)
PENDING = frozenset(
    {
        "intent-recorded",
        "queued",
        "running",
        "dispatching",
        "dispatched",
        "write-observed",
    }
)
TERMINAL = frozenset({"saved", "completed"})


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _text(value):
    return type(value) is str and 0 < len(value) <= 256


def _hash(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


@dataclass(frozen=True)
class ContinuationBinding:
    project_id: str
    project_ref: str
    input_version: int
    brief_sha256: str
    plan_manifest_sha256: str | None
    settings_sha256: str

    def __post_init__(self):
        _require(
            _text(self.project_id) and _text(self.project_ref),
            "project-binding-required",
        )
        _require(
            type(self.input_version) is int and self.input_version > 0,
            "typed-input-version-required",
        )
        _require(
            _hash(self.brief_sha256) and _hash(self.settings_sha256),
            "binding-hashes-required",
        )
        _require(
            self.plan_manifest_sha256 is None or _hash(self.plan_manifest_sha256),
            "plan-hash-required",
        )


@dataclass(frozen=True)
class ContinuationAction:
    kind: str
    identity: str
    binding: ContinuationBinding
    frontier_sha256: str

    def __post_init__(self):
        _require(
            type(self.kind) is str and self.kind in KINDS, "stage1-action-required"
        )
        _require(_text(self.identity), "action-identity-required")
        _require(
            type(self.binding) is ContinuationBinding and _hash(self.frontier_sha256),
            "action-binding-required",
        )


@dataclass(frozen=True)
class DurableAction:
    """Projection of an independently reopened existing owner's receipt."""

    key: str
    project_ref: str
    status: str
    request_sha256: str
    receipt_sha256: str
    outcome: str | None = None

    def __post_init__(self):
        _require(
            _text(self.key) and _text(self.project_ref) and _text(self.status),
            "durable-action-required",
        )
        _require(
            _hash(self.request_sha256) and _hash(self.receipt_sha256),
            "durable-receipt-hashes-required",
        )
        _require(
            self.status != "completed" or self.outcome == "succeeded",
            "completed-success-evidence-required",
        )


@dataclass(frozen=True)
class ContinuationSnapshot:
    binding: ContinuationBinding
    frontier_sha256: str
    progress: dict
    actions: tuple = ()
    barrier: str | None = None

    def __post_init__(self):
        _require(
            type(self.binding) is ContinuationBinding and _hash(self.frontier_sha256),
            "snapshot-binding-required",
        )
        p = self.progress
        _require(
            type(p) is dict
            and set(p)
            == {
                "kind",
                "schema_version",
                "binding",
                "phases",
                "next_action",
                "research_complete",
            },
            "progress-projection-required",
        )
        _require(
            p["kind"] == "ProjectStage1Progress"
            and p["schema_version"] == "1.0.0"
            and p["research_complete"] is False,
            "progress-contract-differs",
        )
        b = p["binding"]
        _require(
            type(b) is dict
            and set(b) == {"project_ref", "revision", "input_version", "brief_sha256"},
            "progress-binding-required",
        )
        _require(
            type(b["revision"]) is int
            and b["revision"] >= 0
            and type(b["input_version"]) is int,
            "progress-version-invalid",
        )
        _require(
            all(
                b[k] == getattr(self.binding, k)
                for k in ("project_ref", "input_version", "brief_sha256")
            ),
            "progress-binding-differs",
        )
        phases = p["phases"]
        _require(
            type(phases) is list and len(phases) == len(PHASES),
            "progress-phases-required",
        )
        for row, phase in zip(phases, PHASES):
            _require(
                type(row) is dict
                and set(row) == {"phase_id", "status", "reason"}
                and row["phase_id"] == phase,
                "progress-phase-invalid",
            )
            _require(
                row["status"]
                in {
                    "unknown",
                    "held",
                    "recorded",
                    "required",
                    "available",
                    "partial",
                    "unconnected",
                }
                and _text(row["reason"]),
                "progress-state-invalid",
            )
        nxt = p["next_action"]
        _require(
            nxt is None
            or type(nxt) is dict
            and set(nxt) == {"phase_id", "target", "reason"}
            and nxt["phase_id"] in PHASES
            and _text(nxt["target"])
            and _text(nxt["reason"]),
            "progress-next-action-invalid",
        )
        _require(
            self.binding.plan_manifest_sha256 is not None
            or nxt is not None
            and nxt["phase_id"] == "planning",
            "unplanned-binding-outside-planning",
        )
        _require(
            type(self.actions) is tuple
            and len(self.actions) <= 512
            and all(
                type(a) is DurableAction and a.project_ref == self.binding.project_ref
                for a in self.actions
            ),
            "snapshot-durable-actions-required",
        )
        _require(
            len({a.key for a in self.actions}) == len(self.actions),
            "duplicate-durable-action",
        )
        _require(
            self.barrier in {None, "saved-delivery", "core-review", "wiki-review"},
            "stage1-barrier-required",
        )
        object.__setattr__(self, "progress", deepcopy(p))


def continue_stage1(
    *,
    run_id,
    binding,
    snapshot,
    next_action,
    handlers,
    deadline,
    max_actions,
    wait=None,
    key_for_action=None,
    monotonic=time.monotonic,
):
    """Run a bounded slice; callbacks and limits are trusted server wiring only.

    ``snapshot()`` returns ContinuationSnapshot with relevant durable history.
    ``next_action(snapshot)`` returns ContinuationAction or None. A handler takes
    ``(action, deterministic_key, absolute_deadline)``; its result is ignored.
    ``wait(durable_action, absolute_deadline)`` may join an existing owner once.
    ``key_for_action(action)`` optionally previews the existing owner's durable
    key without granting authority or changing state; defaults retain auto keys.
    Actual owner receipts are still reopened after dispatch.
    The adapter must retain failure/unknown actions until explicitly reconciled.
    A newly compiled plan requires explicit re-entry with its confirmed binding.
    """
    _require(
        _text(run_id) and type(binding) is ContinuationBinding, "run-binding-required"
    )
    _require(
        callable(snapshot) and callable(next_action) and callable(monotonic),
        "trusted-callbacks-required",
    )
    _require(
        type(handlers) is dict
        and all(k in KINDS and callable(v) for k, v in handlers.items()),
        "stage1-handlers-required",
    )
    _require(wait is None or callable(wait), "wait-callback-invalid")
    _require(key_for_action is None or callable(key_for_action), "key-callback-invalid")
    _require(
        type(max_actions) is int and 0 < max_actions <= 512,
        "finite-action-limit-required",
    )
    _require(
        type(deadline) in {int, float} and math.isfinite(deadline),
        "finite-deadline-required",
    )
    started = datetime.now(timezone.utc).isoformat()
    begin = monotonic()
    _require(math.isfinite(begin) and deadline > begin, "positive-deadline-required")
    records, seen, frontiers = [], set(), set()
    count, waited = 0, set()

    def read():
        value = snapshot()
        _require(type(value) is ContinuationSnapshot, "typed-snapshot-required")
        return value

    def finish(status, reason):
        return dict(
            status=status,
            reason=reason,
            started_at=started,
            finished_at=datetime.now(timezone.utc).isoformat(),
            elapsed_seconds=max(0, monotonic() - begin),
            action_count=count,
            actions=records,
            monetary_cost=None,
            tokens=None,
            stage1_complete=False,
            scientific_acceptance=False,
            stage2_started=False,
        )

    current = read()
    while True:
        if current.binding != binding:
            reason = (
                "plan-confirmation-required"
                if binding.plan_manifest_sha256 is None
                else "binding-changed"
            )
            return finish("held", reason)
        if monotonic() >= deadline:
            return finish("held", "deadline-exhausted")
        unsafe = next(
            (a for a in current.actions if a.status not in TERMINAL | PENDING), None
        )
        if unsafe:
            return finish("held", "durable-action-" + unsafe.status)
        pending = next((a for a in current.actions if a.status in PENDING), None)
        if pending:
            if wait is None or pending.key in waited or len(waited) >= 512:
                return finish("waiting", "existing-action-pending")
            waited.add(pending.key)
            try:
                wait(pending, deadline)
            except Exception:
                return finish("held", "wait-failed")
            current = read()
            if monotonic() >= deadline:
                return finish("held", "deadline-exhausted")
            continue
        held = next(
            (p for p in current.progress["phases"] if p["status"] == "held"), None
        )
        if held:
            return finish("held", held["reason"])
        nxt = current.progress["next_action"]
        barrier = current.barrier or (
            "saved-delivery"
            if nxt and nxt["reason"] == "package-saved-review-required"
            else None
        )
        if barrier:
            return finish("barrier", barrier)
        if nxt is None:
            return finish("partial", "no-next-action")
        phase = next(
            p for p in current.progress["phases"] if p["phase_id"] == nxt["phase_id"]
        )
        if phase["status"] in {"unknown", "unconnected"}:
            return finish("held", "phase-" + phase["status"])
        action = next_action(current)
        if action is None:
            return finish("partial", "no-next-action")
        _require(type(action) is ContinuationAction, "typed-action-required")
        if (
            action.binding != binding
            or action.frontier_sha256 != current.frontier_sha256
        ):
            return finish("held", "stale-action")
        phase_kinds = {
            "scope": set(),
            "planning": {"planning"},
            "query": {"query"},
            "screening": {"screen"},
            "reading": {"source", "reading"},
            "coverage": {"coverage"},
            "delivery": {"records", "delivery", "atlas"},
        }
        if action.kind not in phase_kinds[nxt["phase_id"]]:
            return finish("held", "phase-action-differs")
        if binding.plan_manifest_sha256 is None and action.kind != "planning":
            return finish("held", "plan-required")
        digest = sha(
            canonical(
                dict(
                    run_id=run_id,
                    binding=asdict(binding),
                    kind=action.kind,
                    identity=action.identity,
                )
            )
        )
        key = (
            "stage1-auto-" + digest
            if key_for_action is None
            else key_for_action(action)
        )
        _require(_text(key), "durable-action-key-invalid")
        if digest in seen or any(a.key == key for a in current.actions):
            return finish("held", "repeated-action")
        if current.frontier_sha256 in frontiers:
            return finish("held", "frontier-cycle")
        if action.kind not in handlers:
            return finish("held", "handler-unconnected")
        if count >= max_actions:
            return finish("held", "administrative-limit-exhausted")
        fresh = read()
        if fresh != current:
            return finish("held", "stale-frontier")
        if monotonic() >= deadline:
            return finish("held", "deadline-exhausted")
        seen.add(digest)
        frontiers.add(current.frontier_sha256)
        count += 1
        error = None
        try:
            handlers[action.kind](action, key, deadline)
        except Exception as failure:
            error = type(failure).__name__
        current = read()
        receipt = next((a for a in current.actions if a.key == key), None)
        records.append(
            dict(
                key=key,
                action_sha256=digest,
                kind=action.kind,
                status=None if receipt is None else receipt.status,
                receipt_sha256=None if receipt is None else receipt.receipt_sha256,
                reason=error,
            )
        )
        if error:
            return finish("held", "handler-failed")
        if receipt is None:
            return finish("held", "durable-receipt-missing")
        if (
            receipt.status in TERMINAL
            and current.frontier_sha256 == action.frontier_sha256
        ):
            return finish("held", "no-frontier-progress")

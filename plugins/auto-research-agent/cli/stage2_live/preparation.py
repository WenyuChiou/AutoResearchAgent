"""Bounded, durable preparation around the existing controller, with no executor.

Only trusted host bootstrap supplies handlers: identity, admission_context and
prepare(request). Optional workspace_templates bind exact new role policies to
admission receipt files. Declarations never replace controller/preflight checks.
"""

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time

from stage1_deliverable.common import DeliverableError, reject_links
from stage2_common import Stage2Error, canonical_hash
from stage2_workflow.store import inspect_workflow
from .environment import environment_key

MAX_RECORD_BYTES = 4 * 1024 * 1024
GATES = {"needs-prior-work", "needs-workspace"}
MAPS = {"execution_policies", "execution_preflights", "execution_inventories"}


def _guard(path):
    try:
        reject_links(path)
    except DeliverableError as error:
        raise Stage2Error("controller-preparation-linked-path") from error
    return Path(path).resolve()


def _raw(path):
    path = _guard(path)
    if not stat.S_ISREG(path.stat().st_mode):
        raise Stage2Error("controller-preparation-record-bound")
    with path.open("rb") as stream:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_RECORD_BYTES:
            raise Stage2Error("controller-preparation-record-bound")
        raw = stream.read(MAX_RECORD_BYTES + 1)
    if len(raw) > MAX_RECORD_BYTES:
        raise Stage2Error("controller-preparation-record-bound")
    return raw


def _read(path):
    value = json.loads(_raw(path))
    digest = value.pop("record_sha256", None)
    if digest != canonical_hash(value):
        raise Stage2Error("controller-preparation-record-hash-mismatch")
    return value


def _write(path, value):
    raw = json.dumps(
        {**value, "record_sha256": canonical_hash(value)},
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    if len(raw) > MAX_RECORD_BYTES:
        raise Stage2Error("controller-preparation-record-bound")
    with _guard(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def implementation_pins():
    """Bind both recovery guards; reading copied bytes never executes them."""
    return {
        name: hashlib.sha256(_raw(Path(__file__).with_name(name))).hexdigest()
        for name in ("preparation.py", "execution_admission.py")
    }


def _receipts(refs):
    if not isinstance(refs, list) or not 1 <= len(refs) <= 32:
        raise Stage2Error("controller-preparation-receipts-required")
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
            raise Stage2Error("controller-preparation-receipt-shape")
        path = Path(ref["path"])
        if not path.is_absolute():
            raise Stage2Error("controller-preparation-receipt-path")
        if hashlib.sha256(_raw(path)).hexdigest() != ref["sha256"]:
            raise Stage2Error("controller-preparation-receipt-hash-mismatch")


def _admitted(context, spec, previous=None):
    required = {
        "status",
        "mode",
        "execution_policy_sha256",
        "runtime_sha256",
        "deadline_unix",
        "remaining_budget",
    }
    if not isinstance(context, dict) or not required.issubset(context):
        return False
    budget, deadline = context["remaining_budget"], context["deadline_unix"]
    if (
        context["status"] != "admitted"
        or not isinstance(context["mode"], str)
        or not context["mode"]
        or context["execution_policy_sha256"] != canonical_hash(spec["native"])
        or not isinstance(context["runtime_sha256"], str)
        or len(context["runtime_sha256"]) != 64
        or any(c not in "0123456789abcdef" for c in context["runtime_sha256"])
        or type(deadline) not in (int, float)
        or not math.isfinite(deadline)
        or deadline <= time.time()
        or not isinstance(budget, dict)
        or not budget
        or any(
            type(v) not in (int, float) or not math.isfinite(v) or v < 0
            for v in budget.values()
        )
    ):
        return False
    if previous is not None:
        stable = {k: v for k, v in context.items() if k != "remaining_budget"}
        original = {k: v for k, v in previous.items() if k != "remaining_budget"}
        if (
            stable != original
            or set(budget) != set(previous["remaining_budget"])
            or any(v > previous["remaining_budget"][k] for k, v in budget.items())
        ):
            raise Stage2Error("controller-preparation-admission-changed")
    return True


def validate_spec_update(old, new, gate, templates):
    """Allow only requested additive slots/proofs and explicit continuation."""
    mutable = MAPS | {"workspaces", "continuation_snapshot_sha256"}
    if not isinstance(new, dict) or {
        k: v for k, v in old.items() if k not in mutable
    } != {k: v for k, v in new.items() if k not in mutable}:
        raise Stage2Error("controller-preparation-immutable-spec-changed")
    before, after = old["workspaces"], new.get("workspaces", {})
    required = set(gate.get("required_workspace_keys", []))
    if (
        not isinstance(after, dict)
        or set(after) - set(before) != required
        or any(after.get(k) != v for k, v in before.items())
    ):
        raise Stage2Error("controller-preparation-workspace-change-not-requested")
    additions = {
        environment_key(after[k]["home"], after[k]["workspace"]): k for k in required
    }
    for name in MAPS:
        prior, updated = old.get(name, {}), new.get(name, {})
        if (
            not isinstance(updated, dict)
            or not set(prior).issubset(updated)
            or any(updated[k] != v for k, v in prior.items())
        ):
            raise Stage2Error("controller-preparation-existing-environment-changed")
        added = set(updated) - set(prior)
        if name == "execution_inventories":
            declared = {}
            for slot in required:
                rows = templates.get(slot, {}).get("inventories", {})
                if not isinstance(rows, dict):
                    raise Stage2Error(
                        "controller-preparation-inventory-template-invalid"
                    )
                for thread_id, inventory in rows.items():
                    if thread_id in declared and declared[thread_id] != inventory:
                        raise Stage2Error(
                            "controller-preparation-inventory-template-conflict"
                        )
                    declared[thread_id] = inventory
            if added - set(declared) or any(
                updated[key] != declared[key] for key in added
            ):
                raise Stage2Error("controller-preparation-unrequested-inventory")
        elif added - set(additions):
            raise Stage2Error("controller-preparation-unrequested-environment")
        if name == "execution_policies":
            for key in set(updated) - set(prior):
                template = templates.get(additions[key], {})
                if (
                    template.get("execution_policy") != updated[key]
                    or "receipt" not in template
                ):
                    raise Stage2Error(
                        "controller-preparation-role-template-unavailable"
                    )
                _receipts([template["receipt"]])


def _validated(response, request, state, templates, *, replay=False):
    required = {
        "status",
        "spec",
        "expected_head",
        "continuation_snapshot_sha256",
        "receipts",
    }
    if (
        not isinstance(response, dict)
        or not required.issubset(response)
        or set(response) - required - {"usage"}
    ):
        raise Stage2Error("controller-preparation-result-shape")
    heads = [event["event_sha256"] for event in state["events"]]
    head = response["expected_head"]
    if (
        head not in heads
        or request["expected_head"] not in heads
        or heads.index(head) < heads.index(request["expected_head"])
        or (not replay and head != state["head_sha256"])
    ):
        raise Stage2Error("controller-preparation-head-mismatch")
    snapshots = sum(
        e["event_type"] == "snapshot_added"
        for e in state["events"][: heads.index(head) + 1]
    )
    snapshot = state["snapshots"][snapshots - 1]["event"]["payload"]["snapshot_sha256"]
    if (
        request["gate"]["status"] == "needs-prior-work"
        and snapshot == request["snapshot_sha256"]
    ):
        raise Stage2Error("controller-preparation-no-snapshot-progress")
    validate_spec_update(request["spec"], response["spec"], request["gate"], templates)
    if response["continuation_snapshot_sha256"] != response["spec"].get(
        "continuation_snapshot_sha256"
    ):
        raise Stage2Error("controller-preparation-continuation-mismatch")
    _receipts(response["receipts"])


def _stopped(result, status, reason, usages, run_dir):
    return {
        **result,
        "workflow_head_sha256": inspect_workflow(run_dir)["head_sha256"],
        "preparation": {
            "status": status,
            "reason": reason,
            "gate_workflow_head_sha256": result["workflow_head_sha256"],
            "usage_observations": copy.deepcopy(usages),
        },
    }


def run_with_preparation(run, run_dir, controller_dir, expected_head, spec, handler):
    """At most two durable preparations; interrupted/failed work never retries.

    Admission is supplied and accounted by the trusted host, with its original
    deadline/pins preserved. Unknown callback usage stays unknown. This module
    cannot certify real native/search execution or authorize a formal run.
    """
    run_dir, destination = _guard(run_dir), _guard(controller_dir)
    workspace_paths = [
        _guard(p) for row in spec["workspaces"].values() for p in row.values()
    ]
    state = inspect_workflow(run_dir, expected_head=expected_head)
    base = spec.get("base_snapshot_sha256") if isinstance(spec, dict) else None
    if base not in {
        s["event"]["payload"]["snapshot_sha256"] for s in state["snapshots"]
    }:
        raise Stage2Error("controller-preparation-base-snapshot-invalid")
    protected = [state["root"], *(s["checker"]["root"] for s in state["snapshots"])]
    protected += workspace_paths
    if any(
        destination == Path(p)
        or destination in Path(p).parents
        or Path(p) in destination.parents
        for p in protected
    ):
        raise Stage2Error("controller-preparation-input-output-collision")
    root = _guard(destination / "preparations" / base)
    identity = getattr(handler, "identity", None)
    context = copy.deepcopy(getattr(handler, "admission_context", None))
    if (
        not isinstance(identity, str)
        or not identity
        or not callable(getattr(handler, "prepare", None))
        or not _admitted(context, spec)
    ):
        previous = sorted(root.glob("*.intent.json"))
        gate = _read(previous[-1])["gate"] if previous else run(expected_head, spec)
        return _stopped(
            gate,
            "unavailable-preparation-admission",
            "No trusted handler with current bounded admission is available.",
            [],
            run_dir,
        )
    root.mkdir(parents=True, exist_ok=True)
    lock = _guard(root / "active.lock")
    try:
        stream = lock.open("x")
    except FileExistsError as error:
        raise Stage2Error("controller-preparation-busy-needs-recovery") from error
    try:
        templates = copy.deepcopy(getattr(handler, "workspace_templates", {}))
        binding = {
            "run": str(state["root"]),
            "initial_event": state["events"][0]["event_sha256"],
            "spec": spec,
            "handler_identity": identity,
            "guard_implementations": implementation_pins(),
            "admission_context": context,
            "workspace_templates": templates,
        }
        path = root / "binding.json"
        if path.exists():
            saved = _read(path)
            if any(saved[k] != binding[k] for k in binding if k != "admission_context"):
                raise Stage2Error("controller-preparation-binding-changed")
            _admitted(context, spec, saved["admission_context"])
        else:
            _write(path, binding)
        current, usages, gate = copy.deepcopy(spec), [], None
        intents = sorted(root.glob("*.intent.json"))
        if len(intents) > 2:
            raise Stage2Error("controller-preparation-count-invalid")
        for index, path in enumerate(intents):
            request = _read(path)
            gate = request["gate"]
            if (
                path.name != f"{index:02d}.intent.json"
                or request["spec"] != current
                or request["binding_sha256"]
                != canonical_hash(_read(root / "binding.json"))
            ):
                raise Stage2Error("controller-preparation-intent-binding-mismatch")
            result_path = root / f"{index:02d}.result.json"
            if not result_path.exists():
                return _stopped(
                    request["gate"],
                    "needs-recovery",
                    "Preparation outcome is unknown; do not redispatch.",
                    usages,
                    run_dir,
                )
            record = _read(result_path)
            if record["request_sha256"] != canonical_hash(request):
                raise Stage2Error("controller-preparation-result-binding-mismatch")
            response = record["response"]
            usages.append(response.get("usage", {"status": "unknown"}))
            if response["status"] != "complete":
                return _stopped(
                    request["gate"],
                    response["status"],
                    response["reason"],
                    usages,
                    run_dir,
                )
            _validated(response, request, state, templates, replay=True)
            current = response["spec"]
            _admitted(context, spec, request["admission_context"])
        for index in range(len(intents), 3):
            if not _admitted(context, spec):
                if gate is None:
                    raise Stage2Error(
                        "controller-preparation-admission-expired-before-engine"
                    )
                return _stopped(
                    gate,
                    "unavailable-preparation-admission",
                    "Original preparation admission expired.",
                    usages,
                    run_dir,
                )
            result = run(state["head_sha256"], current)
            gate = result
            if result["status"] not in GATES:
                return {
                    **result,
                    "preparation": {"status": "complete", "usage_observations": usages},
                }
            if index == 2:
                return _stopped(
                    result,
                    "needs-recovery",
                    "Preparation bound reached; retain the unresolved gate.",
                    usages,
                    run_dir,
                )
            state = inspect_workflow(
                run_dir, expected_head=result["workflow_head_sha256"]
            )
            if not _admitted(context, spec):
                return _stopped(
                    result,
                    "unavailable-preparation-admission",
                    "Original preparation admission expired.",
                    usages,
                    run_dir,
                )
            request = {
                "spec": current,
                "expected_head": state["head_sha256"],
                "snapshot_sha256": state["latest_snapshot"]["event"]["payload"][
                    "snapshot_sha256"
                ],
                "gate": result,
                "handler_identity": identity,
                "admission_context": context,
                "execution_policy_sha256": canonical_hash(spec["native"]),
                "usage_observations": usages,
                "binding_sha256": canonical_hash(_read(root / "binding.json")),
            }
            _write(root / f"{index:02d}.intent.json", request)
            try:
                response = handler.prepare(copy.deepcopy(request))
                if not isinstance(response, dict) or response.get("status") not in {
                    "complete",
                    "unavailable",
                    "failed",
                }:
                    raise Stage2Error("controller-preparation-result-shape")
                state = inspect_workflow(run_dir)
                if response["status"] == "complete":
                    _validated(response, request, state, templates)
                elif (
                    not isinstance(response.get("reason"), str)
                    or not response["reason"].strip()
                ):
                    raise Stage2Error("controller-preparation-stop-reason-required")
            except Exception as error:
                response = {
                    "status": "failed",
                    "reason": f"{type(error).__name__}: {error}",
                }
            _write(
                root / f"{index:02d}.result.json",
                {"request_sha256": canonical_hash(request), "response": response},
            )
            usages = [*usages, response.get("usage", {"status": "unknown"})]
            if response["status"] != "complete":
                return _stopped(
                    result, response["status"], response["reason"], usages, run_dir
                )
            current = response["spec"]
    finally:
        stream.close()
        lock.unlink()

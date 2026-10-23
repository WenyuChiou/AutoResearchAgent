"""Conservative reservations under one original deadline; never an executor."""

from copy import deepcopy
from pathlib import Path
import time

from stage2_common import Stage2Error, canonical_hash
from .judges import _execution_policy
from .preparation import _admitted, _guard, _read, _write, implementation_pins


class AdmittedAdapter:
    """Reconcile saved capacity before replay; reserve only actual new calls.

    model_calls reserves no-tools attempt capacity (including allowed retries),
    not a global inference count. Native inference/tool/cost totals stay unknown.
    Synthetic test adapters dispatch no models and are explicitly excluded.
    """

    def __init__(self, adapter, handler, spec, controller_root):
        self.adapter, self.handler, self.spec = adapter, handler, spec
        self.synthetic = adapter.synthetic
        self.root = _guard(Path(controller_root) / "execution_admission")
        if not self.synthetic and _admitted(
            getattr(handler, "admission_context", None), spec
        ):
            # Replayed units bypass reserve; reconcile before the next callback.
            self._restore()

    def __getattr__(self, name):
        target = getattr(self.adapter, name)
        if name not in {"research", "extract", "review", "resolve"} or self.synthetic:
            return target

        def invoke(context):
            self.reserve(name, context)
            return target(context)

        return invoke

    def _restore(self):
        admission = self.handler.admission_context
        stable = {k: v for k, v in admission.items() if k != "remaining_budget"}
        existing = sorted(self.root.glob("*.json"))
        remaining = deepcopy(admission["remaining_budget"])
        previous = None
        if existing:
            record = _read(existing[-1])
            if record["original_admission"] != stable:
                raise Stage2Error("controller-original-admission-differs")
            if record.get("guard_implementations") != implementation_pins():
                raise Stage2Error("controller-original-guard-runtime-differs")
            saved = record["remaining_budget"]
            if saved.keys() != remaining.keys():
                raise Stage2Error("controller-original-budget-differs")
            if not _admitted({**stable, "remaining_budget": saved}, self.spec):
                raise Stage2Error("controller-original-saved-budget-invalid")
            remaining = {
                key: min(value, saved[key]) for key, value in remaining.items()
            }
            previous = canonical_hash(record)
        # The provider may have spent further capacity in its own sealed record.
        # Neither ledger can renew the lower remaining balance on reopening.
        admission["remaining_budget"] = deepcopy(remaining)
        return existing, remaining, previous

    def reserve(self, operation, context):
        admission = getattr(self.handler, "admission_context", None)
        if not _admitted(admission, self.spec):
            raise Stage2Error("controller-original-admission-expired-before-unit")
        policy = _execution_policy(self.spec["native"]["extraction_policy"])
        attempts = (1 + policy["max_semantic_corrections_per_unit"]) * (
            1 + policy["max_transient_transport_retries"]
        )
        native = int(operation in {"research", "review", "resolve"})
        models = 0 if operation == "research" else attempts
        # Do not shorten a frozen per-call policy or start work that could cross
        # the original whole-run deadline even under permitted corrections.
        maximum_seconds = (native + models) * policy["timeout_seconds"]
        if admission["deadline_unix"] - time.time() < maximum_seconds:
            raise Stage2Error("controller-original-deadline-cannot-fit-unit")
        stable = {k: v for k, v in admission.items() if k != "remaining_budget"}
        self.root.mkdir(parents=True, exist_ok=True)
        existing, remaining, previous = self._restore()
        costs = {"native_captures": native, "model_calls": models}
        if any(
            cost and (key not in remaining or remaining[key] < cost)
            for key, cost in costs.items()
        ):
            raise Stage2Error("controller-original-run-budget-exhausted")
        key = canonical_hash([operation, str(_guard(context["output"]))])
        if any(_read(path)["unit"] == key for path in existing):
            raise Stage2Error("controller-unit-reservation-outcome-unknown")
        for resource, cost in costs.items():
            if cost:
                remaining[resource] -= cost
        reservation = dict(
            kind="Stage2OriginalExecutionReservation",
            schema_version="1.0.0",
            unit=key,
            operation=operation,
            original_admission=stable,
            guard_implementations=implementation_pins(),
            previous_sha256=previous,
            capacity_reserved=costs,
            remaining_budget=remaining,
            actual_model_calls=None,
            actual_native_inferences=None,
            actual_tool_calls=None,
            actual_cost=None,
        )
        _write(self.root / f"{len(existing):06d}.json", reservation)
        admission["remaining_budget"] = deepcopy(remaining)

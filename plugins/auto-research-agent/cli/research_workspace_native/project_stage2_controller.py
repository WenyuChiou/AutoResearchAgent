"""Trusted operator composition of ProjectStage2 and the existing controller.

Bootstrap owns every path, spec and prerequisite handler. There is no browser
command, native admission provider or execution engine here. A durable intent
permits one controller entry; an absent result can only be reconciled externally.
"""

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import stat

import stage2_live.controller as controller_module

from stage1_deliverable.common import DeliverableError, reject_links
from stage2_common import Stage2Error, canonical_hash
from stage2_live.controller import run_controller, verify_controller
from stage2_live.failure_state import describe_controller_failure
from stage2_live.preparation import _admitted, implementation_pins
from stage2_workflow import inspect_workflow

from .session_api import SessionApiError, _check
from .store import identifier

_MAX_RECORD = 4 * 1024 * 1024
_MUTABLE_SPEC = {
    "workspaces",
    "execution_policies",
    "execution_preflights",
    "execution_inventories",
    "continuation_snapshot_sha256",
}


def _json(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _bytes(value):
    return json.dumps(
        _json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _guard(path):
    try:
        reject_links(path)
    except DeliverableError as error:
        raise Stage2Error("stage2-controller-linked-path") from error
    return Path(path).resolve()


def _raw(path):
    path = _guard(path)
    with path.open("rb") as stream:
        details = os.fstat(stream.fileno())
        _check(
            stat.S_ISREG(details.st_mode) and details.st_size <= _MAX_RECORD,
            "stage2-controller-record-bound",
        )
        value = stream.read(_MAX_RECORD + 1)
    _check(len(value) <= _MAX_RECORD, "stage2-controller-record-bound")
    return value


def _read(path):
    try:
        value = json.loads(_raw(path))
        _check(isinstance(value, dict), "stage2-controller-record-invalid")
        receipt = value.pop("record_sha256", None)
        _check(
            receipt == canonical_hash(value), "stage2-controller-record-hash-differs"
        )
        return value
    except Stage2Error:
        raise
    except (ValueError, TypeError, RecursionError) as error:
        raise SessionApiError("stage2-controller-record-invalid") from error


def _write(path, value):
    raw = _bytes({**value, "record_sha256": canonical_hash(value)})
    _check(len(raw) <= _MAX_RECORD, "stage2-controller-record-bound")
    _guard(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _guard(path)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _digest(path):
    with _guard(path).open("rb") as stream:
        _check(
            stat.S_ISREG(os.fstat(stream.fileno()).st_mode),
            "stage2-controller-input-not-file",
        )
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _sources(binding):
    packet = json.loads(_raw(binding["packet_path"]))
    root = Path(binding["source_root"])
    result = {"packet": _digest(binding["packet_path"])}
    for source in packet["sources"]:
        path = _guard(root / source["path"])
        _check(path.is_relative_to(root), "stage2-controller-source-path-invalid")
        result[source["path"]] = _digest(path)
    return result


class ProjectStage2ControllerDriver:
    """One server-owned controller attempt, followed only by verified reopening.

    The optional registration deadline is a trusted metadata-operation guard;
    it never replaces or extends the original handler execution deadline.
    """

    def __init__(
        self,
        service,
        *,
        spec,
        controller_dir,
        delivery_dir,
        prerequisite_handler=None,
        check_registration_deadline=None,
    ):
        self.service = service
        self.spec = json.loads(_bytes(spec))
        self.controller_dir = _guard(controller_dir)
        self.delivery_dir = _guard(delivery_dir)
        self.handler = prerequisite_handler
        _check(
            check_registration_deadline is None
            or callable(check_registration_deadline),
            "stage2-controller-registration-deadline-invalid",
        )
        self.check_registration_deadline = check_registration_deadline
        self.records = self.controller_dir / "project_stage2_driver"

    def _configuration(self):
        return dict(
            spec=self.spec,
            controller_root=str(self.controller_dir),
            delivery_root=str(self.delivery_dir),
            handler_identity=getattr(self.handler, "identity", None),
            controller_runtime_sha256=_digest(controller_module.__file__),
            driver_runtime_sha256=_digest(__file__),
            preparation_guard_sha256s=implementation_pins(),
        )

    def _identity(self, credential, project_ref):
        public = self.service.intake.read(credential, project_ref)
        identity = self.service.intake.binding(project_ref)
        _check(
            canonical_hash(
                {
                    key: public.get(key)
                    for key in ("project_id", "input_version", "brief_sha256")
                }
            )
            == canonical_hash(
                {
                    key: identity.get(key)
                    for key in ("project_id", "input_version", "brief_sha256")
                }
            ),
            "stage2-controller-binding-differs",
        )
        return _json(identity)

    def _same(self, intent, credential, project_ref, key):
        _check(
            intent["key"] == key
            and intent["project_ref"] == project_ref
            and canonical_hash(intent["configuration"])
            == canonical_hash(self._configuration())
            and canonical_hash(intent["identity"])
            == canonical_hash(self._identity(credential, project_ref)),
            "stage2-controller-binding-differs",
        )
        context = getattr(self.handler, "admission_context", None)
        original = intent["admission_context"]
        _check(
            isinstance(context, dict)
            and canonical_hash(
                {k: v for k, v in context.items() if k != "remaining_budget"}
            )
            == canonical_hash(
                {k: v for k, v in original.items() if k != "remaining_budget"}
            ),
            "stage2-controller-binding-differs",
        )
        budget = context.get("remaining_budget")
        _check(
            isinstance(budget, dict)
            and budget.keys() == original["remaining_budget"].keys()
            and all(
                type(v) in (int, float)
                and math.isfinite(v)
                and 0 <= v <= original["remaining_budget"][k]
                for k, v in budget.items()
            ),
            "stage2-controller-binding-differs",
        )
        stage = self.service.read(credential, project_ref)
        _check(
            canonical_hash(stage["activation"]) == intent["activation_sha256"]
            and _sources(intent["binding"]) == intent["sources"],
            "stage2-controller-binding-differs",
        )

    @staticmethod
    def _state(status, **extra):
        return dict(
            kind="ProjectStage2ControllerRun",
            status=status,
            execution_authorized=False,
            formal_ready=False,
            research_delivery_ready=False,
            evaluation="missing",
            human_selection="pending",
            stage3_receiver="not-started",
            **extra,
        )

    def _verify_result(self, saved, intent):
        _check(
            saved["intent_sha256"] == canonical_hash(intent),
            "stage2-controller-result-intent-differs",
        )
        result = saved["controller"]
        _check(
            result.get("kind") == "Stage2ControllerResult"
            and result.get("formal_ready") is False
            and result.get("stage3_execution_authorized") is False
            and result.get("human_selection") == "pending"
            and result.get("execution_authorized", False) is False,
            "stage2-controller-result-state-invalid",
        )
        receipt = result.get("controller_manifest_sha256")
        _check(
            isinstance(receipt, str)
            and len(receipt) == 64
            and all(c in "0123456789abcdef" for c in receipt),
            "stage2-controller-result-receipt-required",
        )
        path = self.controller_dir / "controller_manifests" / (receipt + ".json")
        raw = _raw(path)
        _check(
            hashlib.sha256(raw).hexdigest() == saved["manifest_file_sha256"],
            "stage2-controller-manifest-bytes-differ",
        )
        manifest = json.loads(raw)
        spec_path = _guard(self.controller_dir / manifest["controller_spec_path"])
        _check(
            spec_path.is_relative_to(self.controller_dir),
            "stage2-controller-spec-path-invalid",
        )
        final_spec = json.loads(_raw(spec_path))
        _check(
            canonical_hash(
                {k: v for k, v in final_spec.items() if k not in _MUTABLE_SPEC}
            )
            == canonical_hash(
                {k: v for k, v in self.spec.items() if k not in _MUTABLE_SPEC}
            ),
            "stage2-controller-model-policy-differs",
        )
        verification = verify_controller(self.controller_dir, receipt)
        gate_head = result.get("preparation", {}).get(
            "gate_workflow_head_sha256", result.get("workflow_head_sha256")
        )
        _check(
            manifest["workflow_root"] == intent["binding"]["workflow_root"]
            and manifest["delivery_root"] == str(self.delivery_dir)
            and manifest["workflow_head_sha256"] == gate_head
            and manifest["status"] == result["status"]
            and manifest["synthetic_test_only"] is result["synthetic_test_only"],
            "stage2-controller-result-manifest-differs",
        )
        state = inspect_workflow(
            intent["binding"]["workflow_root"],
            expected_head=result["workflow_head_sha256"],
        )
        _check(
            intent["binding"]["workflow_head_sha256"]
            in {event["event_sha256"] for event in state["events"]},
            "stage2-controller-original-head-missing",
        )
        return verification

    def _register(self, credential, project_ref, intent, saved, *, replayed):
        verification = self._verify_result(saved, intent)
        result = saved["controller"]
        old = intent["binding"]["workflow_head_sha256"]
        new = result["workflow_head_sha256"]
        registration = None
        if old != new:
            arguments = dict(
                key=intent["frontier_key"],
                expected_activation_sha256=intent["binding"]["activation_sha256"],
                expected_previous_head_sha256=old,
                new_workflow_head_sha256=new,
                check_deadline=self.check_registration_deadline,
            )
            try:
                try:
                    action = self.service.action(
                        credential, project_ref, intent["frontier_key"]
                    )
                except SessionApiError as error:
                    if error.code != "intake-action-unavailable":
                        raise
                    action = None
                if action is None:
                    registration = self.service.advance_frontier(
                        project_ref, **arguments
                    )
                elif action["status"] == "saved" or (
                    action["status"] == "execution-unknown"
                    and action.get("failure_phase") == "post-work-before-commit"
                ):
                    registration = self.service.recover_frontier(
                        project_ref, **arguments
                    )
                else:
                    return self._state(
                        "frontier-registration-pending",
                        controller=result,
                        replayed=replayed,
                        reason="registration-outcome-unknown",
                    )
            except SessionApiError as error:
                return self._state(
                    "frontier-registration-pending",
                    controller=result,
                    replayed=replayed,
                    reason=error.code,
                )
        binding = _json(self.service.binding(project_ref))
        expected = {
            **intent["binding"],
            "workflow_head_sha256": new,
            "frontier_sequence": intent["binding"]["frontier_sequence"] + (old != new),
        }
        _check(
            canonical_hash(binding) == canonical_hash(expected),
            "stage2-controller-binding-differs",
        )
        facts = self._state(
            "saved",
            controller=deepcopy(result),
            replayed=replayed,
            frontier_registration=registration,
            frontier_advanced=old != new,
        )
        completion = verification.get("completion") or {}
        facts["research_delivery_ready"] = bool(
            completion.get("research_delivery_ready")
            and not verification["synthetic_test_only"]
        )
        facts["evaluation"] = completion.get("assessment_status", "missing")
        return facts

    def _restore_returned_result(self, intent):
        """Recover only an actually sealed, fully reverified core result."""
        root = _guard(self.controller_dir / "controller_results")
        paths = sorted(root.glob("*.json"))
        _check(len(paths) <= 128, "stage2-controller-recovery-record-count")
        current = inspect_workflow(intent["binding"]["workflow_root"])["head_sha256"]
        matches = []
        for path in paths:
            record = _read(path)
            _check(
                set(record) == {"kind", "schema_version", "result"}
                and record["kind"] == "Stage2ControllerReturnedResult"
                and record["schema_version"] == "1.0.0",
                "stage2-controller-recovery-record-invalid",
            )
            result = record["result"]
            receipt = result.get("controller_manifest_sha256")
            _check(
                path.name == str(receipt) + ".json",
                "stage2-controller-recovery-record-name",
            )
            if result.get("workflow_head_sha256") != current:
                continue
            manifest = (
                self.controller_dir / "controller_manifests" / (receipt + ".json")
            )
            saved = dict(
                intent_sha256=canonical_hash(intent),
                controller=result,
                manifest_file_sha256=hashlib.sha256(_raw(manifest)).hexdigest(),
            )
            self._verify_result(saved, intent)
            matches.append(saved)
        _check(len(matches) <= 1, "stage2-controller-recovery-result-ambiguous")
        if not matches:
            return None
        _write(self.records / "result.json", matches[0])
        return matches[0]

    def run(self, credential, project_ref, *, key):
        """Authenticate first; a saved intent never authorizes a second entry."""
        identifier(key)
        identity = self._identity(credential, project_ref)
        path, result_path = self.records / "intent.json", self.records / "result.json"
        if _guard(path).exists():
            intent = _read(path)
            self._same(intent, credential, project_ref, key)
            if not _guard(result_path).exists():
                restored = self._restore_returned_result(intent)
                if restored is None:
                    return self._state(
                        "execution-unknown",
                        replayed=True,
                        reason="controller-result-not-retained",
                    )
                return self._register(
                    credential, project_ref, intent, restored, replayed=True
                )
            return self._register(
                credential, project_ref, intent, _read(result_path), replayed=True
            )
        binding = _json(self.service.binding(project_ref))
        context = deepcopy(getattr(self.handler, "admission_context", None))
        if (
            not callable(getattr(self.handler, "prepare", None))
            or not isinstance(getattr(self.handler, "identity", None), str)
            or not 0 < len(self.handler.identity) <= 128
            or "native" not in self.spec
            or not _admitted(context, self.spec)
        ):
            return self._state(
                "unavailable-preparation-admission",
                replayed=False,
                reason="trusted-prerequisite-handler-and-original-admission-required",
            )
        protected = [Path(binding[k]) for k in ("source_root", "workflow_root")]
        protected += [
            _guard(v)
            for row in self.spec.get("workspaces", {}).values()
            for v in row.values()
        ]
        outputs = [self.controller_dir, self.delivery_dir]
        _check(
            not any(
                a == b or a in b.parents or b in a.parents
                for a in outputs
                for b in protected
            )
            and self.controller_dir != self.delivery_dir
            and not self.controller_dir.is_relative_to(self.delivery_dir)
            and not self.delivery_dir.is_relative_to(self.controller_dir),
            "stage2-controller-path-collision",
        )
        stage = self.service.read(credential, project_ref)
        intent = dict(
            kind="ProjectStage2ControllerIntent",
            schema_version="1.0.0",
            project_ref=project_ref,
            key=key,
            identity=identity,
            binding=binding,
            activation_sha256=canonical_hash(stage["activation"]),
            sources=_sources(binding),
            spec=deepcopy(self.spec),
            configuration=self._configuration(),
            admission_context=context,
            frontier_key="stage2-controller-" + canonical_hash([project_ref, key])[:32],
        )
        try:
            _write(path, intent)
        except FileExistsError:
            return self.run(credential, project_ref, key=key)
        # Reopen the exclusive intent and binding immediately before dispatch.
        intent = _read(path)
        self._same(intent, credential, project_ref, key)
        self.service.binding(project_ref)
        if not _admitted(
            getattr(self.handler, "admission_context", None), self.spec, context
        ):
            return self._state(
                "unavailable-preparation-admission",
                replayed=False,
                reason="original-execution-admission-expired",
            )
        try:
            result = run_controller(
                Path(binding["workflow_root"]),
                self.controller_dir,
                self.delivery_dir,
                binding["workflow_head_sha256"],
                deepcopy(self.spec),
                prerequisite_handler=self.handler,
            )
        except Exception as error:
            _write(
                self.records / "failure.json",
                dict(
                    exception_type=type(error).__name__,
                    error_message=str(error)[:4096],
                    error_message_truncated=len(str(error)) > 4096,
                    failure_observation=describe_controller_failure(error),
                    reason="controller-outcome-unknown",
                    intent_sha256=canonical_hash(intent),
                ),
            )
            return self._state(
                "execution-unknown", replayed=False, reason="controller-outcome-unknown"
            )
        receipt = result.get("controller_manifest_sha256", "")
        _check(
            isinstance(receipt, str)
            and len(receipt) == 64
            and all(c in "0123456789abcdef" for c in receipt),
            "stage2-controller-result-receipt-required",
        )
        manifest = self.controller_dir / "controller_manifests" / (receipt + ".json")
        saved = dict(
            intent_sha256=canonical_hash(intent),
            controller=_json(result),
            manifest_file_sha256=hashlib.sha256(_raw(manifest)).hexdigest(),
        )
        self._verify_result(saved, intent)
        _write(result_path, saved)
        return self._register(credential, project_ref, intent, saved, replayed=False)

"""Stage3 planning jobs over the existing durable host journal; no new runner."""

import copy
import hashlib
import importlib.metadata
import math
from pathlib import Path
import sys

from .contracts import Stage3Error, digest, plan_schema_path
from .intake import admit_intake
from .planner import draft_plan
from .preparation import closed, file_binding, text
from .storage import (
    MAX_ARTIFACT_BYTES,
    decode_json,
    private_output,
    read_bytes,
    safe_path,
    write_new,
)
from .validation import check_plan
from .workflow import advance_workflow, inspect_workflow

POLICY = dict.fromkeys(
    (
        "execution_authorized",
        "evaluation_calls_authorized",
        "formal_execution_enabled",
        "external_claim_ready",
        "usable_for_formal_pairing",
    ),
    False,
)


def _ref(path):
    return {
        "path": str(safe_path(path)),
        "sha256": hashlib.sha256(read_bytes(path)).hexdigest(),
    }


def _runtime():
    folder = Path(__file__).parent
    return {
        "python": sys.version,
        "jsonschema": importlib.metadata.version("jsonschema"),
        "stage3_sources": {
            p.name: _ref(p)["sha256"] for p in sorted(folder.glob("*.py"))
        },
    }


class PlanningJobs:
    """Wrap host-owned Journal intents; the host retains authentication and ownership."""

    method = "stage3/planning"
    kind = "Stage3PlanningJob"
    namespace = "stage3-plan-"

    def __init__(self, journal, project_id, owner, root, *, project_ref=None):
        self.journal, self.project_id, self.owner = journal, project_id, owner
        self.project_ref = project_id if project_ref is None else project_ref
        text(self.project_ref, "host project reference")
        self.root = private_output(root)
        journal.snapshot(project_id)

    def _key(self, key):
        text(key, "job key")
        return self.namespace + digest(key)

    def _payload(
        self,
        key,
        checkpoint,
        configuration,
        adapter_context,
        plan_id,
        version,
        schema_version,
    ):
        closed(checkpoint, {"path", "sha256"}, "current workflow checkpoint")
        saved = inspect_workflow(
            checkpoint["path"], expected_checkpoint_sha256=checkpoint["sha256"]
        )["checkpoint"]
        if saved["status"]["next_action"] == "resolve-stage2-scientific-mapping":
            raise Stage3Error("workflow still requires the existing Stage2 mapping")
        source = saved["bindings"]["source"]
        intake = admit_intake(
            source["package"],
            source["delivery"],
            expected_manifest_sha256=source["manifest_sha256"],
        )
        origin = intake.get("input_origin", {})
        if origin.get("project_ref", self.project_ref) != self.project_ref:
            raise Stage3Error("planning source belongs to another host project")
        text(plan_id, "plan identity")
        if type(version) is not int or version < 1:
            raise Stage3Error("positive exact integer plan version required")
        closed(configuration, {"model", "reasoning"}, "host planning configuration")
        for value in configuration.values():
            text(value, "host planning configuration")
        if not isinstance(adapter_context, dict):
            raise Stage3Error("explicit host adapter context required")
        deadline = adapter_context.get("timeout_seconds")
        if (
            type(deadline) not in (int, float)
            or not math.isfinite(deadline)
            or deadline <= 0
        ):
            raise Stage3Error(
                "existing adapter must declare its finite positive deadline"
            )
        schema = plan_schema_path(schema_version)
        value = {
            "kind": self.kind,
            "schema_version": "1.0.0",
            "key": key,
            "project_id": self.project_id,
            "project_ref": self.project_ref,
            "brief_project_id": intake.get("brief", {}).get("project_id"),
            "project_index_sha256": self.journal.snapshot(self.project_id)[
                "index_sha256"
            ],
            "workflow_id": saved["workflow_id"],
            "checkpoint": checkpoint,
            "source": source,
            "intake_sha256": digest(intake),
            "selected_candidates": intake["selected_candidates"],
            "question_refs": [q["question_ref"] for q in intake["questions"]],
            "human_conditions_sha256": digest(intake["selection_conditions"]),
            "reviewer_context_sha256": digest(intake["reviewer_planning_context"])
            if "reviewer_planning_context" in intake
            else None,
            "plan": {
                "plan_id": plan_id,
                "version": version,
                "schema_version": schema_version,
                "schema_sha256": _ref(schema)["sha256"],
            },
            "configuration": configuration,
            "adapter_context": adapter_context,
            "runtime": _runtime(),
            "output": str(self.root / digest([self.project_id, self.method, key])),
            "policy": dict(POLICY),
        }
        from .contracts import canonical_bytes

        if len(canonical_bytes(value)) > MAX_ARTIFACT_BYTES:
            raise Stage3Error("job request exceeds the existing artifact bound")
        return copy.deepcopy(value)

    def prepare(
        self,
        key,
        *,
        checkpoint,
        configuration,
        adapter_context,
        plan_id,
        expected_revision,
        version=1,
        schema_version="1.0.0",
    ):
        """Record a source-bound intent without initializing a model or process."""
        payload = self._payload(
            key,
            checkpoint,
            configuration,
            adapter_context,
            plan_id,
            version,
            schema_version,
        )
        self.journal.record_intent(
            self.project_id,
            self.owner,
            self._key(key),
            self.method,
            payload,
            expected_revision,
        )
        return self.inspect(
            key, expected_request_sha256=digest(payload), current_checkpoint=checkpoint
        )

    def _item(self, key, expected_request_sha256, current_checkpoint):
        item = self.journal.snapshot(self.project_id)["intents"].get(self._key(key))
        if item is None or item["method"] != self.method:
            raise Stage3Error("unknown Stage3 planning job")
        payload = item["payload"]
        if digest(payload) != expected_request_sha256 or digest(
            payload["checkpoint"]
        ) != digest(current_checkpoint):
            raise Stage3Error("job request or current workflow differs")
        expected = self._payload(
            key,
            current_checkpoint,
            payload["configuration"],
            payload["adapter_context"],
            payload["plan"]["plan_id"],
            payload["plan"]["version"],
            payload["plan"]["schema_version"],
        )
        if digest(payload) != digest(expected):
            raise Stage3Error(
                "job source, project, selection, schema or runtime changed"
            )
        return item

    def _saved(self, payload, manifest_sha256, *, attach=False):
        root = Path(payload["output"])
        plan_root = root / "plan"
        source = payload["source"]

        def no_call(**kwargs):
            raise AssertionError("saved job inspection must never invoke an adapter")

        no_call.request_context = payload["adapter_context"]
        saved = draft_plan(
            source["package"],
            source["delivery"],
            expected_manifest_sha256=source["manifest_sha256"],
            output_dir=plan_root,
            callback=no_call,
            configuration=payload["configuration"],
            plan_id=payload["plan"]["plan_id"],
            version=payload["plan"]["version"],
            schema_version=payload["plan"]["schema_version"],
            resume_manifest_sha256=manifest_sha256,
        )
        artifacts = saved["artifacts"]
        plan = artifacts.get("plan.json")
        if plan is None:
            raise Stage3Error(
                "failed planning package cannot complete a successful job"
            )
        intake = artifacts["request.json"]["intake"]
        report = check_plan(plan, intake=intake)
        if (
            not report["structural_valid"]
            or digest(plan)
            != digest(decode_json(read_bytes(plan_root / "raw-response.json")))
            or digest(report) != digest(artifacts["validation.json"])
        ):
            raise Stage3Error("saved job differs from source-aware validation")
        plan_ref = {"package": str(plan_root), "manifest_sha256": manifest_sha256}
        checkpoint_path = root / "checkpoint.json"
        if attach and not checkpoint_path.exists():
            advance_workflow(
                payload["checkpoint"]["path"],
                expected_checkpoint_sha256=payload["checkpoint"]["sha256"],
                action="attach-plan",
                output=checkpoint_path,
                binding=plan_ref,
            )
        checkpoint_ref = _ref(checkpoint_path)
        checkpoint = inspect_workflow(
            checkpoint_ref["path"], expected_checkpoint_sha256=checkpoint_ref["sha256"]
        )["checkpoint"]
        if digest(checkpoint["parent"]) != digest(payload["checkpoint"]) or digest(
            checkpoint["bindings"]["plan"]
        ) != digest(plan_ref):
            raise Stage3Error("job output checkpoint belongs to another request")
        return {
            "outcome": "saved",
            "plan": plan_ref,
            "checkpoint": checkpoint_ref,
            "planning_status": checkpoint["status"]["planning_status"],
            "policy": dict(POLICY),
        }

    def inspect(self, key, *, expected_request_sha256, current_checkpoint):
        """Read only: neither unknown attempts nor saved results cause a new call."""
        item = self._item(key, expected_request_sha256, current_checkpoint)
        evidence = item["evidence"]
        result = None
        if item["status"] == "completed":
            if evidence["outcome"] == "saved":
                result = self._saved(item["payload"], self._result_pin(evidence))
                if digest(result) != digest(evidence):
                    raise Stage3Error("job completion evidence differs")
            else:
                self._verify_failure(evidence["failure"])
                result = evidence
        elif evidence and "failure" in evidence:
            self._verify_failure(evidence["failure"])
            result = evidence
        return {
            "key": key,
            "request_sha256": expected_request_sha256,
            "status": item["status"],
            "result": result,
            "resume_action": "no-dispatch"
            if item["status"] != "intent-recorded"
            else "prepared",
            "policy": dict(POLICY),
        }

    def _transition(self, key, status, evidence):
        self.journal.transition_intent(
            self.project_id,
            self.owner,
            self._key(key),
            status,
            evidence,
            self.journal.snapshot(self.project_id)["revision"],
        )

    def _result_pin(self, evidence):
        return evidence["plan"]["manifest_sha256"]

    def _failure_artifacts(self, payload):
        root = Path(payload["output"])
        return {
            name: _ref(root / "plan" / name)
            for name in (
                "request.json",
                "prompt.txt",
                "schema.json",
                "raw-response.json",
                "generation.json",
                "validation.json",
                "failure.json",
                "manifest.json",
            )
            if (root / "plan" / name).is_file()
        }

    def _known_failure(self, payload):
        return (Path(payload["output"]) / "plan/raw-response.json").is_file()

    def _verify_failure(self, ref):
        value = file_binding(ref["path"], ref["sha256"])
        for artifact in value.get("artifacts", {}).values():
            if _ref(artifact["path"]) != artifact:
                raise Stage3Error("saved failure artifact changed")
        for name in ("stdout", "stderr"):
            stream = value[name]
            if stream and stream["retained"]:
                if Path(stream["path"]) != Path(ref["path"]).parent / (name + ".raw"):
                    raise Stage3Error("failure stream escapes the job")
                raw = read_bytes(stream["path"])
                if (
                    hashlib.sha256(raw).hexdigest() != stream["sha256"]
                    or len(raw) != stream["size"]
                ):
                    raise Stage3Error("saved failure stream changed")

    def _failure(self, payload, error):
        root = Path(payload["output"])
        cause = error
        for _ in range(8):
            if cause.__cause__ is None:
                break
            cause = cause.__cause__
        returncode = getattr(cause, "returncode", None)
        value = {
            "error_class": type(cause).__name__,
            "message": str(cause).encode("utf-8", "backslashreplace").decode(),
            "returncode": returncode if type(returncode) is int else None,
            "policy": dict(POLICY),
            "artifacts": self._failure_artifacts(payload),
        }
        for name in ("stdout", "stderr"):
            raw = getattr(cause, name, None)
            if raw is None and name == "stdout":
                raw = getattr(cause, "output", None)
            if isinstance(raw, str):
                raw = raw.encode("utf-8", "backslashreplace")
            value[name] = None
            if isinstance(raw, bytes):
                ref = {
                    "size": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "retained": len(raw) <= MAX_ARTIFACT_BYTES,
                }
                if ref["retained"]:
                    path = root / (name + ".raw")
                    write_new(path, raw, raw=True)
                    ref["path"] = str(path)
                value[name] = ref
        path = root / "job-failure.json"
        write_new(path, value)
        return _ref(path)

    def _perform(self, payload, callback):
        saved = draft_plan(
            payload["source"]["package"],
            payload["source"]["delivery"],
            expected_manifest_sha256=payload["source"]["manifest_sha256"],
            output_dir=Path(payload["output"]) / "plan",
            callback=callback,
            configuration=payload["configuration"],
            plan_id=payload["plan"]["plan_id"],
            version=payload["plan"]["version"],
            schema_version=payload["plan"]["schema_version"],
        )
        return self._saved(payload, saved["manifest"]["manifest_sha256"], attach=True)

    def run(self, key, *, expected_request_sha256, current_checkpoint, callback):
        """One explicit host action; reuse NativePlanner rather than a process manager."""
        item = self._item(key, expected_request_sha256, current_checkpoint)
        payload = item["payload"]
        if not callable(callback) or digest(
            getattr(callback, "request_context", None)
        ) != digest(payload["adapter_context"]):
            raise Stage3Error("host adapter context differs from the prepared job")
        if item["status"] != "intent-recorded":
            return self.inspect(
                key,
                expected_request_sha256=expected_request_sha256,
                current_checkpoint=current_checkpoint,
            )
        self._transition(
            key, "dispatching", {"request_sha256": expected_request_sha256}
        )
        root = Path(payload["output"])
        try:
            root.mkdir(parents=True, exist_ok=True)
            result = self._perform(payload, callback)
        except BaseException as error:
            failure = self._failure(payload, error)
            failure_value = file_binding(failure["path"], failure["sha256"])
            known = self._known_failure(payload) or (
                type(failure_value["returncode"]) is int
                and failure_value["returncode"] != 0
            )
            self._transition(
                key,
                "completed" if known else "execution-unknown",
                {
                    "outcome": "failed" if known else "execution-unknown",
                    "failure": failure,
                    "policy": dict(POLICY),
                },
            )
        else:
            self._transition(key, "completed", result)
        return self.inspect(
            key,
            expected_request_sha256=expected_request_sha256,
            current_checkpoint=current_checkpoint,
        )

    def recover(
        self,
        key,
        *,
        expected_request_sha256,
        current_checkpoint,
        expected_plan_manifest_sha256,
    ):
        """Attach an explicitly pinned saved result; never resend an uncertain request."""
        item = self._item(key, expected_request_sha256, current_checkpoint)
        if item["status"] not in {"dispatching", "execution-unknown"}:
            return self.inspect(
                key,
                expected_request_sha256=expected_request_sha256,
                current_checkpoint=current_checkpoint,
            )
        result = self._saved(
            item["payload"], expected_plan_manifest_sha256, attach=True
        )
        self._transition(key, "completed", result)
        return self.inspect(
            key,
            expected_request_sha256=expected_request_sha256,
            current_checkpoint=current_checkpoint,
        )

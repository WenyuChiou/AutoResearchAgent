"""Conditional direction jobs reuse PlanningJobs' journal, failures and replay."""

from copy import deepcopy
import hashlib
from pathlib import Path

from jsonschema import Draft202012Validator

from .contracts import Stage3Error, digest
from .direction_intent import admit_direction_intent, build_direction_prompt
from .jobs import (
    POLICY,
    PlanningJobs,
    _bounded_job_payload,
    _check_adapter_context,
    _runtime,
)
from .preparation import closed, file_binding, text
from .storage import (
    decode_json,
    inspect_package,
    publish_manifest,
    read_bytes,
    safe_path,
    write_new,
)


SCHEMA = (
    Path(__file__).resolve().parents[2] / "schemas/stage3-direction-plan.v1.schema.json"
)
SOURCE_FIELDS = {
    "intent",
    "intent_sha256",
    "advisory_dir",
    "advisory_manifest_sha256",
    "delivery_dir",
    "delivery_manifest_sha256",
}


def direction_context(source):
    closed(source, SOURCE_FIELDS, "direction source")
    return admit_direction_intent(
        source["intent"],
        source["advisory_dir"],
        source["delivery_dir"],
        expected_intent_sha256=source["intent_sha256"],
        expected_advisory_manifest_sha256=source["advisory_manifest_sha256"],
        expected_delivery_manifest_sha256=source["delivery_manifest_sha256"],
    )


def validate_direction_result(value, context):
    errors = list(
        Draft202012Validator(decode_json(read_bytes(SCHEMA))).iter_errors(value)
    )
    if errors:
        raise Stage3Error("conditional planning result schema differs")
    actual = [row["question_ref"] for row in value["question_plans"]]
    expected = [row["question_ref"] for row in context["questions"]]
    if (
        value["intent_sha256"] != context["intent_sha256"]
        or len(actual) != len(set(actual))
        or set(actual) != set(expected)
    ):
        raise Stage3Error(
            "conditional planning result omits or changes source question identities"
        )


class DirectionPlanningJobs(PlanningJobs):
    """A typed advice job, sharing the existing durable planning state machine.

    Its checkpoint is a pinned Host direction-input document, never a selected
    workflow checkpoint. Completion cannot attach a formal plan or authorize work.
    """

    method = "stage3/direction-planning"
    kind = "Stage3DirectionPlanningJob"
    namespace = "stage3-direction-"

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
        closed(checkpoint, {"path", "sha256"}, "direction input binding")
        document = file_binding(checkpoint["path"], checkpoint["sha256"])
        closed(document, {"kind", "source"}, "direction input")
        if document["kind"] != "Stage3DirectionPlanningJobInput":
            raise Stage3Error("typed direction input required")
        context = direction_context(document["source"])
        if context["project_ref"] != self.project_ref:
            raise Stage3Error("direction source belongs to another Host project")
        closed(configuration, {"model", "reasoning"}, "configuration")
        for value in configuration.values():
            text(value, "configuration value")
        _check_adapter_context(adapter_context)
        text(key, "job key")
        text(plan_id, "plan identity")
        if type(version) is not int or version < 1 or schema_version != "1.0.0":
            raise Stage3Error("conditional plan version differs")
        prompt = build_direction_prompt(context)
        value = {
            "kind": self.kind,
            "key": key,
            "project_ref": self.project_ref,
            "project_id": self.project_id,
            "checkpoint": deepcopy(checkpoint),
            "source": deepcopy(document["source"]),
            "configuration": deepcopy(configuration),
            "adapter_context": deepcopy(adapter_context),
            "plan": {
                "plan_id": plan_id,
                "version": version,
                "schema_version": schema_version,
            },
            "output": str(
                safe_path(self.root / digest([self.project_id, self.method, key]))
            ),
            "runtime": _runtime(),
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "schema_sha256": hashlib.sha256(read_bytes(SCHEMA)).hexdigest(),
            "policy": dict(POLICY),
        }
        return _bounded_job_payload(value)

    def _request(self, payload):
        context = direction_context(payload["source"])
        prompt = build_direction_prompt(context)
        request = {
            "operation": "stage3.direction-plan.v1",
            "payload": payload,
            "context": context,
        }
        return request, context, prompt

    def _perform(self, payload, callback):
        request, context, prompt = self._request(payload)
        output = Path(payload["output"]) / "plan"
        output.mkdir()
        write_new(output / "request.json", request)
        write_new(output / "prompt.txt", prompt.encode(), raw=True)
        write_new(output / "schema.json", read_bytes(SCHEMA), raw=True)
        names = ["request.json", "prompt.txt", "schema.json"]
        try:
            response = callback(
                prompt=prompt,
                schema_path=SCHEMA,
                output_dir=output,
                configuration=deepcopy(payload["configuration"]),
            )
            closed(
                response,
                {"raw_response", "provenance"},
                "conditional planning response",
            )
            raw = response["raw_response"]
            if isinstance(raw, str):
                raw = raw.encode("utf-8")
            if not isinstance(raw, bytes):
                raise Stage3Error("conditional raw response must be bytes or text")
            write_new(output / "raw-response.json", raw, raw=True)
            names.append("raw-response.json")
            write_new(output / "generation.json", response["provenance"])
            names.append("generation.json")
            result = decode_json(raw)
            validate_direction_result(result, context)
            write_new(output / "plan.json", result)
            names.append("plan.json")
        except BaseException as error:
            write_new(
                output / "failure.json",
                {"error_class": type(error).__name__, "execution_authorized": False},
            )
            names.append("failure.json")
            publish_manifest(
                output, names, request_sha256=digest(request), state="failed"
            )
            raise
        manifest = publish_manifest(
            output,
            names,
            request_sha256=digest(request),
            state="needs-information"
            if result["planning_status"] == "needs-information"
            else "draft",
        )
        return self._saved(payload, manifest["manifest_sha256"])

    def _saved(self, payload, manifest_sha256, *, attach=False):
        saved = inspect_package(Path(payload["output"]) / "plan", manifest_sha256)
        request, context, prompt = self._request(payload)
        artifacts = saved["artifacts"]
        if artifacts.get("request.json") != request:
            raise Stage3Error("saved conditional planning request differs")
        raw = decode_json(
            read_bytes(Path(payload["output"]) / "plan/raw-response.json")
        )
        result = artifacts.get("plan.json")
        validate_direction_result(result, context)
        if (
            result != raw
            or read_bytes(Path(payload["output"]) / "plan/prompt.txt")
            != prompt.encode()
        ):
            raise Stage3Error("saved conditional planning output differs")
        return {
            "outcome": "saved",
            "mode": "direction-intent",
            "plan": {
                "package": str(Path(payload["output"]) / "plan"),
                "manifest_sha256": manifest_sha256,
            },
            "checkpoint": deepcopy(payload["checkpoint"]),
            "planning_status": result["planning_status"],
            "formal_selected_receiver": False,
            "policy": dict(POLICY),
        }

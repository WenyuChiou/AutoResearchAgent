"""Conditional direction planning on the existing Host and PlanningJobs journal."""

from contextlib import ExitStack
from copy import deepcopy

from stage3_plan.contracts import Stage3Error, digest
from stage3_plan.direction_intent import build_direction_prompt
from stage3_plan.direction_jobs import DirectionPlanningJobs, direction_context
from stage3_plan.native import NativePlanner
from stage3_plan.storage import inspect_package, read_json, safe_path, write_new

from .project_intake_contract import _fields
from .project_stage2_selection import ProjectStage2SelectionService
from .session_api import _check


DIRECTION_FIELDS = {
    "key",
    "revision",
    "input_version",
    "brief_sha256",
    "mode",
    "direction_intent_sha256",
}


def _planning_issue(context):
    try:
        build_direction_prompt(context)
    except Stage3Error as error:
        return str(error)
    return None


def _check_saved_job_binding(item, configured, source):
    payload = item["payload"]
    _check(
        item["method"] == configured["jobs"].method
        and digest(payload["source"]) == digest(source)
        and digest(payload["configuration"]) == digest(configured["configuration"])
        and digest(payload["adapter_context"]) == digest(configured["adapter_context"]),
        "stage3-saved-job-binding-differs",
    )


class ProjectStage3DirectionPlanning:
    def __init__(self, planning):
        self.planning = planning
        self.intake = planning.intake
        self.selection = ProjectStage2SelectionService(
            self.intake, planning.selection_view.bindings
        )
        self.bindings = {}
        for ref, binding in planning.bindings.items():
            original = binding["jobs"]
            callback = binding["callback"]
            self.bindings[ref] = {
                "jobs": DirectionPlanningJobs(
                    original.journal,
                    original.project_id,
                    original.owner,
                    original.root,
                    project_ref=ref,
                ),
                "callback": callback,
                "configuration": deepcopy(binding["configuration"]),
                "adapter_context": deepcopy(callback.request_context),
            }

    def _current(self, credential, ref, body=None, check_deadline=None):
        project, _, _, _, _ = self.planning._current(
            credential, ref, check_deadline=check_deadline
        )
        _check(
            hasattr(self.selection, "direction_intent_context"),
            "stage2-direction-intent-unconnected",
        )
        receipt = self.selection.read(
            credential, ref, check_deadline=check_deadline
        ).get("direction_intent")
        _check(receipt is not None, "stage3-direction-intent-required")
        pin = receipt["intent_sha256"]
        if body is not None:
            _check(
                body["mode"] == "direction-intent"
                and body["key"] == "stage3-direction-" + pin
                and body["direction_intent_sha256"] == pin
                and type(body["revision"]) is int
                and body["revision"] == project["revision"]
                and type(body["input_version"]) is type(project["input_version"])
                and body["input_version"] == project["input_version"]
                and body["brief_sha256"] == project["brief_sha256"],
                "stage3-direction-project-version-differs",
            )
        source = self.selection.direction_intent_context(
            credential, ref, expected_intent_sha256=pin, check_deadline=check_deadline
        )
        source = dict(
            source,
            advisory_dir=str(safe_path(source["advisory_dir"])),
            delivery_dir=str(safe_path(source["delivery_dir"])),
        )
        context = direction_context(source)
        _check(context["project_ref"] == ref, "stage3-direction-project-differs")
        configured = self.bindings.get(ref)
        if configured:
            _check(
                digest(configured["callback"].request_context)
                == digest(configured["adapter_context"]),
                "stage3-direction-adapter-context-differs",
            )
            callback = configured["callback"]
            if isinstance(callback, NativePlanner):
                callback = NativePlanner(
                    codex=callback.codex,
                    codex_home=callback.home,
                    capture_dir=callback.capture.with_name(
                        callback.capture.name + "-direction"
                    )
                    / digest([configured["jobs"].project_id, ref, pin]),
                    timeout_seconds=callback.timeout,
                )
                configured = dict(
                    configured,
                    callback=callback,
                    adapter_context=deepcopy(callback.request_context),
                )
        return project, source, context, configured

    @staticmethod
    def _public(ref, result):
        from .project_stage3_planning import ProjectStage3PlanningService

        return dict(
            ProjectStage3PlanningService._public(ref, result),
            kind="ProjectStage3DirectionPlanningJob",
            mode="direction-intent",
            formal_selected_receiver=False,
        )

    def read(self, credential, ref, base, check_deadline=None):
        if not hasattr(self.selection, "direction_intent_context"):
            return base
        view = self.selection.read(credential, ref, check_deadline=check_deadline)
        if not view.get("direction_intent"):
            return base
        project, source, context, configured = self._current(
            credential, ref, check_deadline=check_deadline
        )
        result = dict(
            base,
            planning_mode="direction-intent",
            direction_intent_sha256=source["intent_sha256"],
            direction_context=context,
            planning_status=context["planning_status"],
            planning_blockers=[],
            planning_target="stage3-planning-job",
            agent_conversation_connected=False,
            formal_selected_receiver=False,
            default_request=None,
            job=None,
            plan=None,
        )
        issue = _planning_issue(context)
        if issue:
            result.update(
                planning_status="needs-information",
                planning_blockers=[issue],
                dispatch_action="needs-information",
            )
            return result
        if not configured:
            result["dispatch_action"] = "unavailable"
            return result
        body = {
            "key": "stage3-direction-" + source["intent_sha256"],
            "revision": project["revision"],
            "input_version": project["input_version"],
            "brief_sha256": project["brief_sha256"],
            "mode": "direction-intent",
            "direction_intent_sha256": source["intent_sha256"],
        }
        result.update(default_request=body, dispatch_action="prepare-then-confirm-run")
        jobs = configured["jobs"]
        item = jobs.journal.snapshot(jobs.project_id)["intents"].get(
            jobs._key(body["key"])
        )
        if item:
            result["default_request"] = dict(
                body, request_sha256=digest(item["payload"])
            )
            result["job"] = self.inspect(
                credential,
                ref,
                result["default_request"],
                check_deadline=check_deadline,
            )
            if result["job"]["outcome"] == "saved":
                saved = jobs.inspect(
                    body["key"],
                    expected_request_sha256=digest(item["payload"]),
                    current_checkpoint=item["payload"]["checkpoint"],
                )["result"]
                result["plan"] = inspect_package(
                    saved["plan"]["package"], saved["plan"]["manifest_sha256"]
                )["artifacts"]["plan.json"]
        return result

    def prepare(self, credential, ref, body, *, check_deadline=None):
        _fields(body, DIRECTION_FIELDS)
        with self.intake._lock:
            _, source, context, configured = self._current(
                credential, ref, body, check_deadline
            )
            _check(configured is not None, "stage3-planning-unconfigured")
            _check(
                _planning_issue(context) is None, "stage3-direction-needs-information"
            )
            jobs = configured["jobs"]
            item = jobs.journal.snapshot(jobs.project_id)["intents"].get(
                jobs._key(body["key"])
            )
            if item is None:
                jobs.root.mkdir(parents=True, exist_ok=True)
                path = safe_path(
                    jobs.root
                    / ("host-direction-" + digest([ref, body["key"]]) + ".json")
                )
                document = {"kind": "Stage3DirectionPlanningJobInput", "source": source}
                if path.exists():
                    _check(
                        read_json(path) == document, "stage3-direction-input-differs"
                    )
                else:
                    write_new(path, document)
                from stage3_plan.jobs import _ref

                result = jobs.prepare(
                    body["key"],
                    checkpoint=_ref(path),
                    configuration=configured["configuration"],
                    adapter_context=configured["adapter_context"],
                    plan_id="direction-plan-" + digest(body["key"]),
                    expected_revision=jobs.journal.snapshot(jobs.project_id)[
                        "revision"
                    ],
                )
            else:
                _check_saved_job_binding(item, configured, source)
                result = jobs.inspect(
                    body["key"],
                    expected_request_sha256=digest(item["payload"]),
                    current_checkpoint=item["payload"]["checkpoint"],
                )
            return self._public(ref, result)

    def _saved(self, credential, ref, body, check_deadline):
        _, source, _, configured = self._current(credential, ref, body, check_deadline)
        _check(configured is not None, "stage3-planning-unconfigured")
        jobs = configured["jobs"]
        item = jobs.journal.snapshot(jobs.project_id)["intents"].get(
            jobs._key(body["key"])
        )
        _check(
            item is not None and digest(item["payload"]) == body["request_sha256"],
            "stage3-direction-request-differs",
        )
        _check_saved_job_binding(item, configured, source)
        return configured, item["payload"]["checkpoint"]

    def inspect(self, credential, ref, body, *, check_deadline=None):
        _fields(body, DIRECTION_FIELDS | {"request_sha256"})
        with self.intake._lock:
            configured, checkpoint = self._saved(credential, ref, body, check_deadline)
            return self._public(
                ref,
                configured["jobs"].inspect(
                    body["key"],
                    expected_request_sha256=body["request_sha256"],
                    current_checkpoint=checkpoint,
                ),
            )

    def run(self, credential, ref, body, *, check_deadline=None):
        _fields(body, DIRECTION_FIELDS | {"request_sha256", "confirmed"})
        _check(body["confirmed"] is True, "explicit-stage3-planning-required", 400)
        with self.intake._lock:
            configured, checkpoint = self._saved(credential, ref, body, check_deadline)
        with ExitStack() as publication:

            def callback(**request):
                with self.intake._lock:
                    self._saved(credential, ref, body, check_deadline)
                response = configured["callback"](**request)
                publication.enter_context(self.intake._lock)
                self._saved(credential, ref, body, check_deadline)
                return response

            callback.request_context = deepcopy(configured["adapter_context"])
            result = configured["jobs"].run(
                body["key"],
                expected_request_sha256=body["request_sha256"],
                current_checkpoint=checkpoint,
                callback=callback,
            )
        return self._public(ref, result)

    def recover(
        self,
        credential,
        ref,
        body,
        *,
        expected_plan_manifest_sha256,
        check_deadline=None,
    ):
        _fields(body, DIRECTION_FIELDS | {"request_sha256"})
        with self.intake._lock:
            configured, checkpoint = self._saved(credential, ref, body, check_deadline)
            return self._public(
                ref,
                configured["jobs"].recover(
                    body["key"],
                    expected_request_sha256=body["request_sha256"],
                    current_checkpoint=checkpoint,
                    expected_plan_manifest_sha256=expected_plan_manifest_sha256,
                ),
            )

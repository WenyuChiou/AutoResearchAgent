"""Authenticated selected-project bridge to the existing Stage3 planning jobs.

The trusted Host supplies existing jobs and an adapter; this module owns no
runner, Journal, owner lease, credentials, model selection or execution grant.
Preparing inputs never dispatches. Only an explicit confirmed run may call the
configured planning adapter, after the Stage2 selection transaction commits.
"""

from copy import deepcopy
from contextlib import ExitStack
import math

from stage3_plan.contracts import digest
from stage3_plan.jobs import POLICY, PlanningJobs
from stage3_plan.preparation import closed, sha256, text
from stage3_plan.storage import safe_path
from stage3_plan.workflow import source_binding, start_workflow

from .project_intake_contract import BOUND_FIELDS, _fields
from .project_selection_read_context import verified_selection_read
from .project_stage2_selection_view import ProjectStage2SelectionView
from .session_api import _check


SOURCE_FIELDS = BOUND_FIELDS | {"selection_request_sha256"}


class ProjectStage3PlanningService:
    """Server-only bindings map project refs to jobs/configuration/callback.

    The caller must finish selection registration before entering this service.
    A binding is trusted configuration, not a browser-supplied grant. Callers
    retain the existing planning-call authorization and adapter deadline policy.
    Inspect/recover accept only a saved request; neither can invoke a callback.
    """

    def __init__(self, intake, selection_view, *, bindings=None):
        _check(
            isinstance(selection_view, ProjectStage2SelectionView)
            and selection_view.intake is intake,
            "stage3-selection-service-invalid",
            400,
        )
        self.intake, self.selection_view = intake, selection_view
        self.bindings = {}
        _check(
            bindings is None or type(bindings) is dict, "stage3-bindings-invalid", 400
        )
        for ref, binding in (bindings or {}).items():
            text(ref, "host project reference")
            closed(
                binding, {"jobs", "configuration", "callback"}, "Host planning binding"
            )
            jobs, callback = binding["jobs"], binding["callback"]
            _check(
                isinstance(jobs, PlanningJobs) and jobs.project_ref == ref,
                "stage3-job-project-differs",
            )
            closed(binding["configuration"], {"model", "reasoning"}, "configuration")
            for value in binding["configuration"].values():
                text(value, "configuration value")
            _check(callable(callback), "stage3-adapter-required", 400)
            context = deepcopy(getattr(callback, "request_context", None))
            timeout = context.get("timeout_seconds") if type(context) is dict else None
            _check(
                type(timeout) in (int, float)
                and math.isfinite(timeout)
                and timeout > 0,
                "stage3-adapter-deadline-required",
                400,
            )
            digest(context)
            self.bindings[ref] = dict(
                jobs=jobs,
                configuration=deepcopy(binding["configuration"]),
                callback=callback,
                adapter_context=context,
            )
        from .project_stage3_direction_planning import ProjectStage3DirectionPlanning

        self.direction = ProjectStage3DirectionPlanning(self)

    def _current(self, credential, project_ref, body=None, check_deadline=None):
        if check_deadline:
            check_deadline()
        verified, _ = self.selection_view._current_context(credential, project_ref)
        project, binding, _, _, ack, admitted = verified
        if body is not None:
            _check(
                type(body["revision"]) is int
                and body["revision"] == project["revision"]
                and type(body["input_version"]) is type(project["input_version"])
                and body["input_version"] == project["input_version"]
                and body["brief_sha256"] == project["brief_sha256"],
                "stage3-project-version-differs",
            )
            _check(
                ack is not None
                and body["selection_request_sha256"] == ack["request_sha256"],
                "stage3-current-selection-required",
            )
        configured = self.bindings.get(project_ref)
        if configured:
            _check(
                configured["jobs"].project_id == project["project_id"],
                "stage3-job-project-differs",
            )
            _check(
                digest(getattr(configured["callback"], "request_context", None))
                == digest(configured["adapter_context"]),
                "stage3-adapter-context-differs",
            )
        if check_deadline:
            check_deadline()
        return project, binding, ack, admitted, configured

    def read(self, credential, project_ref, *, check_deadline=None):
        """Report selection and configuration without creating a job or dispatch."""
        with self.intake._lock, verified_selection_read(self.intake):
            project, _, ack, _, configured = self._current(
                credential, project_ref, check_deadline=check_deadline
            )
            result = dict(
                kind="ProjectStage3PlanningView",
                project_ref=project_ref,
                input_version=project["input_version"],
                revision=project["revision"],
                brief_sha256=project["brief_sha256"],
                selection_request_sha256=None if ack is None else ack["request_sha256"],
                selection_status="pending" if ack is None else "recorded",
                planning_configured=configured is not None,
                dispatch_action="prepare-then-confirm-run"
                if ack is not None and configured
                else "unavailable",
                **POLICY,
            )
            return (
                self.direction.read(credential, project_ref, result, check_deadline)
                if ack is None
                else result
            )

    def _job(self, current, key):
        project, binding, ack, admitted, configured = current
        _check(
            ack is not None and admitted is not None,
            "stage3-current-selection-required",
        )
        _check(configured is not None, "stage3-planning-unconfigured")
        jobs = configured["jobs"]
        package = (
            self.intake._path(project["project_ref"], ack["artifact_ref"]) / "planning"
        )
        source = source_binding(
            package, binding["delivery_root"], ack["planning_manifest_sha256"]
        )
        item = jobs.journal.snapshot(jobs.project_id)["intents"].get(jobs._key(key))
        if item is not None:
            payload = item["payload"]
            _check(
                item["method"] == jobs.method
                and digest(payload["source"]) == digest(source)
                and digest(payload["configuration"])
                == digest(configured["configuration"])
                and digest(payload["adapter_context"])
                == digest(configured["adapter_context"])
                and payload["plan"]["schema_version"] == "1.1.0",
                "stage3-saved-job-binding-differs",
            )
        return configured, source, item

    @staticmethod
    def _public(project_ref, result):
        # Browser projections contain opaque pins and statuses, never local paths.
        saved = result["result"] or {}
        return dict(
            kind="ProjectStage3PlanningJob",
            project_ref=project_ref,
            key=result["key"],
            request_sha256=result["request_sha256"],
            status=result["status"],
            resume_action=result["resume_action"],
            outcome=saved.get("outcome"),
            planning_status=saved.get("planning_status"),
            plan_manifest_sha256=saved.get("plan", {}).get("manifest_sha256"),
            **POLICY,
        )

    def prepare(self, credential, project_ref, body, *, check_deadline=None):
        """Save a genuine workflow checkpoint and opt-in 1.1 intent; zero calls."""
        if type(body) is dict and body.get("mode") == "direction-intent":
            return self.direction.prepare(
                credential, project_ref, body, check_deadline=check_deadline
            )
        _fields(body, SOURCE_FIELDS)
        with self.intake._lock:
            current = self._current(credential, project_ref, body, check_deadline)
            configured, source, item = self._job(current, body["key"])
            jobs = configured["jobs"]
            if item is None:
                # write_new in the core preserves an orphan checkpoint on failure;
                # a changed key never overwrites it or reconciles it implicitly.
                namespace = digest(
                    dict(
                        project_id=jobs.project_id, method=jobs.method, key=body["key"]
                    )
                )
                path = safe_path(jobs.root / ("host-input-" + namespace + ".json"))
                started = start_workflow(
                    source["package"],
                    source["delivery"],
                    expected_source_manifest_sha256=source["manifest_sha256"],
                    output=path,
                    workflow_id="host-plan-" + digest(body["key"]),
                )
                result = jobs.prepare(
                    body["key"],
                    checkpoint={
                        "path": str(path),
                        "sha256": started["checkpoint_sha256"],
                    },
                    configuration=configured["configuration"],
                    adapter_context=configured["adapter_context"],
                    plan_id="host-plan-" + digest(body["key"]),
                    expected_revision=jobs.journal.snapshot(jobs.project_id)[
                        "revision"
                    ],
                    schema_version="1.1.0",
                )
            else:
                result = jobs.inspect(
                    body["key"],
                    expected_request_sha256=digest(item["payload"]),
                    current_checkpoint=item["payload"]["checkpoint"],
                )
            return self._public(project_ref, result)

    def _saved(self, credential, project_ref, body, check_deadline):
        current = self._current(credential, project_ref, body, check_deadline)
        configured, _, item = self._job(current, body["key"])
        _check(item is not None, "stage3-job-not-prepared")
        sha256(body["request_sha256"])
        _check(
            digest(item["payload"]) == body["request_sha256"], "stage3-request-differs"
        )
        return configured, item["payload"]["checkpoint"]

    def inspect(self, credential, project_ref, body, *, check_deadline=None):
        if type(body) is dict and body.get("mode") == "direction-intent":
            return self.direction.inspect(
                credential, project_ref, body, check_deadline=check_deadline
            )
        _fields(body, SOURCE_FIELDS | {"request_sha256"})
        with self.intake._lock:
            configured, checkpoint = self._saved(
                credential, project_ref, body, check_deadline
            )
            result = configured["jobs"].inspect(
                body["key"],
                expected_request_sha256=body["request_sha256"],
                current_checkpoint=checkpoint,
            )
            return self._public(project_ref, result)

    def run(self, credential, project_ref, body, *, check_deadline=None):
        if type(body) is dict and body.get("mode") == "direction-intent":
            return self.direction.run(
                credential, project_ref, body, check_deadline=check_deadline
            )
        _fields(body, SOURCE_FIELDS | {"request_sha256", "confirmed"})
        _check(body["confirmed"] is True, "explicit-stage3-planning-required", 400)
        with self.intake._lock:
            configured, checkpoint = self._saved(
                credential, project_ref, body, check_deadline
            )

        # Acquire publication protection only after the actual adapter finishes.
        # Keep it through the core's write/attach/completion, without holding the
        # intake lock during the model call or adding a second store/runner.
        with ExitStack() as publication:

            def callback(**request):
                with self.intake._lock:
                    self._saved(credential, project_ref, body, check_deadline)
                response = configured["callback"](**request)
                publication.enter_context(self.intake._lock)
                self._saved(credential, project_ref, body, check_deadline)
                return response

            callback.request_context = deepcopy(configured["adapter_context"])
            result = configured["jobs"].run(
                body["key"],
                expected_request_sha256=body["request_sha256"],
                current_checkpoint=checkpoint,
                callback=callback,
            )
            with self.intake._lock:
                self._saved(credential, project_ref, body, check_deadline)
        return self._public(project_ref, result)

    def recover(
        self,
        credential,
        project_ref,
        body,
        *,
        expected_plan_manifest_sha256,
        check_deadline=None,
    ):
        """Trusted Host supplies the external saved-result pin; never redispatch."""
        if type(body) is dict and body.get("mode") == "direction-intent":
            return self.direction.recover(
                credential,
                project_ref,
                body,
                expected_plan_manifest_sha256=expected_plan_manifest_sha256,
                check_deadline=check_deadline,
            )
        _fields(body, SOURCE_FIELDS | {"request_sha256"})
        with self.intake._lock:
            configured, checkpoint = self._saved(
                credential, project_ref, body, check_deadline
            )
            result = configured["jobs"].recover(
                body["key"],
                expected_request_sha256=body["request_sha256"],
                current_checkpoint=checkpoint,
                expected_plan_manifest_sha256=expected_plan_manifest_sha256,
            )
            return self._public(project_ref, result)

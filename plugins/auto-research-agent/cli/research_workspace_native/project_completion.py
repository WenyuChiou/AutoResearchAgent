"""Read-only completion evidence from existing ProjectHost validators.

The trusted application supplies services, pins and a browser observer. JSON
evidence cannot import an adapter or establish that a real person clicked. This
module starts no jobs and grants no research execution authority.
"""

from copy import deepcopy
from dataclasses import dataclass

from .session_api import _check


@dataclass(frozen=True)
class CompletionIdentity:
    task_id: str
    version: str
    environment: str
    operation_id: str
    project_ref: str
    input_version: int | str
    delivery_manifest_sha256: str
    submission_request_sha256: str
    plan_manifest_sha256: str


def inspect_project_completion(selection, planning, credential, identity, job_request):
    """Reinspect the current submission and exact saved planning job together.

    Services validate authoritative SQL records, original submission artifacts,
    source/current-version pins and the complete saved plan package. A tentative
    preference stays distinct from formal selection. Missing or failed records
    raise through the existing validators; they never become an overall pass.
    """
    _check(planning.intake is selection.intake, "completion-host-mismatch")
    request = deepcopy(job_request)
    with selection.intake._lock:
        view = selection.read(credential, identity.project_ref)
        _check(
            view["project_ref"] == identity.project_ref
            and type(view["input_version"]) is type(identity.input_version)
            and view["input_version"] == identity.input_version
            and view["delivery_manifest_sha256"] == identity.delivery_manifest_sha256,
            "completion-source-mismatch",
        )
        direction = request.get("mode") == "direction-intent"
        receipt = view.get("direction_intent" if direction else "selection_receipt")
        _check(isinstance(receipt, dict), "completion-submission-missing")
        _check(
            receipt.get("request_sha256") == identity.submission_request_sha256,
            "completion-submission-mismatch",
        )
        if direction:
            _check(
                receipt.get("status") == "saved"
                and request.get("direction_intent_sha256")
                == receipt.get("intent_sha256")
                and view["selection_status"] != "recorded",
                "completion-direction-mismatch",
            )
        else:
            _check(
                view["selection_status"] == "recorded"
                and view["planning_status"] == "verified"
                and request.get("selection_request_sha256")
                == identity.submission_request_sha256,
                "completion-selection-mismatch",
            )
        job = planning.inspect(credential, identity.project_ref, request)
        _check(
            job.get("project_ref") == identity.project_ref
            and job.get("key") == request.get("key")
            and job.get("request_sha256") == request.get("request_sha256")
            and job.get("status") == "completed"
            and job.get("outcome") == "saved"
            and job.get("plan_manifest_sha256") == identity.plan_manifest_sha256
            and isinstance(identity.plan_manifest_sha256, str)
            and len(identity.plan_manifest_sha256) == 64,
            "completion-plan-not-saved-or-mismatch",
        )
        _check(
            view.get("execution_authorized") is False
            and job.get("execution_authorized") is False,
            "completion-execution-authority-differs",
        )
    return dict(
        kind="ProjectHostCompletionEvidence",
        schema_version="1.0.0",
        project_ref=identity.project_ref,
        input_version=identity.input_version,
        delivery_manifest_sha256=identity.delivery_manifest_sha256,
        submission_request_sha256=identity.submission_request_sha256,
        planning_request_sha256=job["request_sha256"],
        planning_key=job["key"],
        plan_manifest_sha256=job["plan_manifest_sha256"],
        planning_mode="direction-intent" if direction else "selected-plan",
        formal_selected_receiver=not direction,
        submission_origin=view["input_origin"],
        identity_authenticated=False,
        human_acceptance_verified=False,
        execution_authorized=False,
    )


def completion_event_adapter(
    selection,
    planning,
    credential,
    identity,
    job_request,
    *,
    event_factory,
    observed_events,
):
    """Bind a generic verifier to trusted browser observations and Host records.

    ``event_factory`` is the caller's loaded ``task_completion.VerifiedEvent``;
    there is no dynamic import or new runtime dependency. ``observed_events``
    must come from a trusted browser operator, not the event JSON under test.
    Each observation binds phase/target/mechanism to this operation and its
    submission request. Only automation/synthetic observations are supported:
    ProjectHost currently does not authenticate a human identity.
    """
    expected_request = deepcopy(job_request)
    observations = deepcopy(observed_events)
    expected_identity = {
        key: getattr(identity, key)
        for key in ("task_id", "version", "environment", "operation_id")
    }

    def adapter(event, requirement, contract):
        _check(
            all(contract.get(key) == value for key, value in expected_identity.items()),
            "completion-contract-mismatch",
        )
        phase = requirement.get("phase")
        _check(
            phase in {"entry", "action", "outcome", "delivery", "receiver_ack"},
            "completion-phase-unsupported",
        )
        observed = observations.get(phase)
        _check(isinstance(observed, dict), "completion-browser-observation-missing")
        _check(
            observed.get("origin") in {"automation", "synthetic"}
            and observed.get("project_ref") == identity.project_ref
            and observed.get("operation_id") == identity.operation_id
            and observed.get("submission_request_sha256")
            == identity.submission_request_sha256
            and type(observed.get("input_version")) is type(identity.input_version)
            and observed.get("input_version") == identity.input_version
            and observed.get("planning_key") == expected_request.get("key")
            and observed.get("planning_request_sha256")
            == expected_request.get("request_sha256")
            and observed.get("plan_manifest_sha256") == identity.plan_manifest_sha256
            and all(
                observed.get(key) == requirement.get(key)
                for key in ("phase", "target", "mechanism", "origin")
            ),
            "completion-browser-binding-mismatch",
        )
        if phase in {"entry", "action"}:
            _check(
                observed.get("mechanism") in {"click", "keyboard"},
                "completion-original-ui-action-required",
            )
        authoritative = inspect_project_completion(
            selection, planning, credential, identity, expected_request
        )
        _check(event == authoritative, "completion-event-source-mismatch")
        _check(
            observed.get("result") in {"passed", "failed"}, "completion-outcome-unknown"
        )
        return event_factory(
            **expected_identity,
            phase=phase,
            target=observed["target"],
            mechanism=observed["mechanism"],
            origin=observed["origin"],
            result=observed["result"],
        )

    return adapter

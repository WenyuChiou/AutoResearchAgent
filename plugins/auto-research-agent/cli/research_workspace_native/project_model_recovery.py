"""Retire a never-admitted intent without rewriting its unknown outcome.

This does not reconcile dispatched native work. Browser confirmations cannot
attest process cleanup, return budget or grant another model call.
"""

from copy import deepcopy

from stage1_deliverable.common import canonical, identifier, safe_path, sha
from .session_api import SessionApiError, _check

UNKNOWN = {"execution-unknown", "failed-or-unknown"}
FIELDS = {
    "key",
    "revision",
    "input_version",
    "brief_sha256",
    "job_ref",
    "job_request_sha256",
    "job_snapshot_sha256",
    "confirmed",
    "user_input",
}


def snapshot(job):
    return sha(canonical({k: v for k, v in job.items() if k != "retirement"}))


def retired(job):
    value = job.get("retirement")
    return (
        type(value) is dict
        and type(value.get("evidence")) is dict
        and value.get("status") == "retired-no-resend"
        and value.get("job_request_sha256") == job.get("request_sha256")
        and value.get("job_snapshot_sha256") == snapshot(job)
        and value.get("evidence_sha256") == sha(canonical(value.get("evidence")))
        and value.get("evidence", {}).get("basis") == "never-admitted-no-runtime"
        and job.get("provider_reserved") is False
    )


def public_retirement(job):
    value = deepcopy(job.get("retirement")) if retired(job) else None
    return {
        "retirement": value,
        "retirement_offer": None
        if value or job["status"] not in UNKNOWN
        else {
            "job_ref": job["key"],
            "job_request_sha256": job["request_sha256"],
            "job_snapshot_sha256": snapshot(job),
            "available": job.get("provider_reserved") is False,
            "blocked_reason": None
            if job.get("provider_reserved") is False
            else "model-dispatch-cleanup-unproven",
        },
    }


def _evidence(service, state, principal, ref, job):
    _check(
        not service._closed
        and ref in service._owners
        and service._row(state).get("owner") == service._tokens.get(ref),
        "model-owner-unavailable",
    )
    _check(
        job["status"] in UNKNOWN and job.get("provider_reserved") is False,
        "model-dispatch-cleanup-unproven",
    )
    _check(
        not any(t.is_alive() for (r, _), t in service._workers.items() if r == ref)
        and not any(r == ref for r, _ in service._providers),
        "model-retirement-worker-active",
    )
    binding = service._runtime_identity(principal, ref, job)
    _check(
        job.get("project_ref") == ref
        and job.get("project_id") == state["project_id"]
        and job.get("runtime_binding") == binding
        and job.get("runtime_dir") == service._runtime_relative(binding),
        "model-runtime-binding-differs",
    )
    folder = safe_path(service.intake.root, job["runtime_dir"])
    filesystem = "not-created"
    if folder.exists():
        _check(folder.is_dir(), "model-retirement-runtime-unproven")
        service._check_runtime_marker(folder / "binding.json", binding)
        # Even a provider request/result or an unknown child directory requires
        # lifecycle evidence. Never infer no I/O from a missing PID or file.
        _check(
            all(p.name == "binding.json" for p in folder.iterdir()),
            "model-retirement-runtime-unproven",
        )
        filesystem = "binding-only"
    return {
        "basis": "never-admitted-no-runtime",
        "runtime_binding_sha256": sha(canonical(binding)),
        "filesystem": filesystem,
        "native_dispatch_observed": False,
        "automatic_resend": False,
        "budget_refunded": False,
        "research_outcome": "Unknown",
    }


def retire(service, credential, ref, body, *, check_deadline=None):
    _check(
        type(body) is dict and set(body) == FIELDS and len(canonical(body)) <= 16384,
        "model-retirement-fields",
        400,
    )
    identifier(body["key"])
    identifier(body["job_ref"])
    _check(
        body["confirmed"] is True
        and type(body["user_input"]) is str
        and body["user_input"].strip()
        and len(body["user_input"].encode("utf8")) <= 4096,
        "model-retirement-confirmation-required",
        400,
    )
    principal = service.intake._principal(credential)

    def validate(state):
        job = service._row(state)["jobs"].get(body["job_ref"])
        _check(
            job is not None and not retired(job), "model-retirement-target-unavailable"
        )
        _check(
            job["request_sha256"] == body["job_request_sha256"]
            and snapshot(job) == body["job_snapshot_sha256"],
            "model-retirement-target-differs",
        )
        return job, _evidence(service, state, principal, ref, job)

    def reserve(state, *_):
        validate(state)

    def save(state, request_hash, _):
        job, evidence = validate(state)
        job["retirement"] = {
            "status": "retired-no-resend",
            "job_request_sha256": job["request_sha256"],
            "job_snapshot_sha256": snapshot(job),
            "evidence": evidence,
            "evidence_sha256": sha(canonical(evidence)),
            "action_key": body["key"],
            "request_sha256": request_hash,
            "user_input": body["user_input"],
            "recorded_at": service.clock(),
        }
        return {"target_key": job["key"], "retirement": deepcopy(job["retirement"])}

    try:
        return service.intake._perform(
            principal,
            ref,
            "model-retirement",
            body,
            save,
            reserve=reserve,
            check_deadline=check_deadline,
        )
    except (KeyError, TypeError) as error:
        raise SessionApiError("model-retirement-evidence-invalid") from error

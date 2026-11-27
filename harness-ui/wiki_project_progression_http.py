"""Opt-in ordinary Host route for progression under an existing Stage 1 grant."""

import re
import time

from research_workspace_native.project_stage1_run_grant import (
    ProjectStage1RunGrantService,
)
from research_workspace_native.session_api import SessionApiError, _check, _hash
from research_workspace_native.transport import _decode
from stage1_deliverable.common import canonical, sha

from wiki_project_progression import StageStep, WikiProjectProgression


ROUTE = re.compile(r"/api/projects/([A-Za-z0-9_-]{1,64})/progression")


def _stage1_step(host, issuer, limits, dispatch):
    def predecessor(credential, binding):
        ref = binding["project_ref"]
        with host.projects._lock:
            host.projects.read(credential, ref)
            current = host.projects.binding(ref)
        _check(
            all(
                current[field] == binding[field]
                for field in ("project_id", "input_version", "brief_sha256")
            )
            and sha(canonical(current["settings"])) == binding["settings_sha256"],
            "stage-progression-project-differs",
        )
        return current["plan_manifest_sha256"]

    def result(credential, binding, _upstream, _key):
        saved = host.project_stage1_delivery.read(credential, binding["project_ref"])[
            "canonical_package"
        ]
        if saved and saved["status"] == "saved-evidence-validated":
            return saved["manifest_sha256"]
        return None

    def authorized(credential, binding, upstream):
        _check(limits["seconds"] > 0, "stage-progression-budget-unavailable")
        ref = binding["project_ref"]
        pins = issuer.resolve_current(
            credential,
            ref,
            input_version=binding["input_version"],
            brief_sha256=binding["brief_sha256"],
        )
        document = issuer.inspect(
            credential, ref, pins["grant_ref"], pins["grant_sha256"]
        )
        _check(
            document["binding"]["project_id"] == binding["project_id"]
            and document["binding"]["plan_manifest_sha256"] == upstream
            and document["binding"]["settings_sha256"] == binding["settings_sha256"],
            "stage-progression-project-differs",
        )
        _check(
            all(document["budgets"][name] <= limit for name, limit in limits.items()),
            "stage-progression-budget-unavailable",
        )
        _check(dispatch is not None, "stage-progression-runtime-unconnected")
        return pins, document

    def connect(credential, binding, upstream, consent_pin):
        _check(
            _hash(consent_pin) and predecessor(credential, binding) == upstream,
            "stage-progression-predecessor-differs",
        )

    def grant(credential, binding, upstream, _key):
        return authorized(credential, binding, upstream)[0]

    def submit(credential, binding, upstream, key, pins, *, check_deadline):
        current, document = authorized(credential, binding, upstream)
        _check(current == pins, "stage-progression-grant-differs")
        remaining = min(check_deadline(), document["expires_at"] - issuer._now())
        _check(remaining > 0, "stage1-run-grant-expired")
        dispatch(
            credential,
            binding["project_ref"],
            run_id=key,
            deadline=time.monotonic() + remaining,
            max_actions=document["max_actions"],
            run_grants=issuer,
            grant_ref=pins["grant_ref"],
            grant_sha256=pins["grant_sha256"],
        )

    return StageStep(issuer.runtime_sha256, predecessor, result, connect, grant, submit)


def _expected(handler, length):
    _check(
        handler.headers.get("Content-Type", "").lower() == "application/json",
        "json-content-type-required",
        415,
    )
    _check(0 < length <= 1024, "stage-progression-body-bound-exceeded", 413)
    raw = handler.rfile.read(length)
    _check(len(raw) == length, "partial-body", 400)
    try:
        body = _decode(raw.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        raise SessionApiError("invalid-json", 400) from None
    _check(
        type(body) is dict
        and set(body) == {"input_version", "brief_sha256", "confirmed"}
        and type(body["input_version"]) is int
        and body["input_version"] > 0
        and _hash(body["brief_sha256"])
        and body["confirmed"] is True,
        "stage-progression-explicit-intent-required",
        400,
    )
    return body["input_version"], body["brief_sha256"]


def run_grant_issuer(host, runtime_sha256):
    """Return (issuer, trusted). Trusted means the Host's own run-capable issuer."""
    issuer = getattr(host.project_models, "run_grants", None)
    if issuer is None:
        # A local Host can observe existing grants while runtime lanes are offline.
        return (
            ProjectStage1RunGrantService(host.projects, runtime_sha256=runtime_sha256),
            False,
        )
    if (
        type(issuer) is ProjectStage1RunGrantService
        and issuer.intake is host.projects
        and issuer.runtime_sha256 == runtime_sha256
    ):
        return issuer, True
    raise ValueError("trusted Stage 1 run issuer binding differs")


def install_project_progression(
    host, *, read_consent, limits, runtime_sha256, dispatch=None
):
    issuer, trusted = run_grant_issuer(host, runtime_sha256)
    if trusted and dispatch is None:
        dispatch = host.continue_stage1
    step = _stage1_step(host, issuer, limits, dispatch)
    service = WikiProjectProgression(
        host, read_consent=read_consent, steps={"stage1": step}
    )
    # Read-only summaries (consent coverage) use this same checked service.
    host.wiki_project_progression = service
    inherited = host.RequestHandlerClass

    class ProgressionHandler(inherited):
        def do_GET(self):
            match = ROUTE.fullmatch(self.path)
            return self._progression("GET", match[1]) if match else super().do_GET()

        def do_POST(self):
            match = ROUTE.fullmatch(self.path)
            return self._progression("POST", match[1]) if match else super().do_POST()

        def _progression(self, method, ref):
            try:
                credential, length = self._headers(method)
                _check(
                    self.headers.get("Sec-Fetch-Site") in (None, "none", "same-origin"),
                    "cross-site-rejected",
                    403,
                )
                _check(
                    host.authenticate(credential) is not None,
                    "credential-rejected",
                    401,
                )
                if method == "GET":
                    _check(not length, "invalid-project-read", 400)
                    result = service.read(credential, ref)
                else:
                    result = service.advance(
                        credential,
                        ref,
                        expected=_expected(self, length),
                        check_deadline=self._remaining,
                    )
                self._remaining()
                return self._reply(200, result)
            except SessionApiError as error:
                return self._reply(error.status, {"error": error.code})
            except (OSError, TimeoutError):
                self.close_connection = True
            except (ValueError, TypeError, KeyError):
                return self._reply(
                    409, {"error": "stage-progression-verification-required"}
                )

    host.RequestHandlerClass = ProgressionHandler
    host.daemon_threads = False
    host.block_on_close = True

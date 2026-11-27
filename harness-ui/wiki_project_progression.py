"""Opt-in Host orchestration with trusted adapters and existing intake receipts."""

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Callable

from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.session_api import SessionApiError, _check, _hash
from stage1_deliverable.common import canonical, sha
from stage1_ledger.journal import LedgerError, decode


STAGES = ("stage1", "stage2", "stage3")
MAX_CONSENT_BYTES = 8192


@dataclass(frozen=True)
class StageStep:
    """Server-owned adapters, called with an authenticated project and one stage."""

    profile_sha256: str
    # Return a verified Stage 1 plan, Stage 2 delivery, or named Stage 2 selection.
    predecessor: Callable
    # Check the existing result against this project, predecessor and dispatch key.
    read_result: Callable
    # Register only. Each stage owns its existing validation and idempotency.
    connect: Callable
    # Load and validate the stage's separate grant and budget. None/False denies.
    spending_grant: Callable
    # Validate the grant again at execution and use the supplied idempotency key.
    submit: Callable


class WikiProjectProgression:
    """A fixed Host instance can advance explicitly; ordinary GET never advances."""

    def __init__(self, host, *, read_consent, steps, clock=None):
        if not isinstance(host.projects, ProjectIntakeService):
            raise ValueError("trusted project intake required")
        self._stages = STAGES[: len(steps)]
        if (
            not steps
            or set(steps) != set(self._stages)
            or any(
                type(step) is not StageStep or not _hash(step.profile_sha256)
                for step in steps.values()
            )
        ):
            raise ValueError("exact trusted stage adapters required")
        self.intake = host.projects
        # Return (raw bytes, a trusted saved receipt's pin), or None. The page
        # never provides raw consent, profiles, paths or grants to this service.
        self._read_consent = read_consent
        self._steps = dict(steps)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._active = set()
        self._lock = Lock()

    @staticmethod
    def _binding(project):
        return {
            "project_ref": project["project_ref"],
            "project_id": project["project_id"],
            "input_version": project["input_version"],
            "brief_sha256": project["brief_sha256"],
            "settings_sha256": sha(canonical(project["settings"])),
        }

    def _consent(self, credential, binding, stage, profile_sha256):
        source = self._read_consent(credential, binding["project_ref"])
        _check(source is not None, "stage-progression-consent-required")
        raw, pin = source
        _check(
            type(raw) is bytes
            and len(raw) <= MAX_CONSENT_BYTES
            and _hash(pin)
            and sha(raw) == pin,
            "stage-progression-consent-digest-differs",
        )
        try:
            consent = decode(raw, "saved stage progression consent")
            expires = datetime.fromisoformat(consent["expires_at"])
        except (LedgerError, KeyError, TypeError, ValueError):
            raise SessionApiError("stage-progression-consent-invalid") from None
        _check(
            type(consent) is dict
            and set(consent)
            == set(binding)
            | {"kind", "schema_version", "confirmed", "expires_at", "stages"}
            and consent["kind"] == "ProjectStageProgressionConsent"
            and consent["schema_version"] == "1.0.0"
            and consent["confirmed"] is True
            and expires.utcoffset() is not None
            and type(consent["stages"]) is dict
            and set(consent["stages"]) <= set(STAGES),
            "stage-progression-consent-invalid",
        )
        _check(
            canonical({key: consent[key] for key in binding}) == canonical(binding),
            "stage-progression-consent-binding-differs",
        )
        _check(self._clock() < expires, "stage-progression-consent-expired")
        limit = consent["stages"].get(stage)
        _check(
            type(limit) is dict
            and set(limit) == {"profile_sha256", "max_dispatches"}
            and limit["profile_sha256"] == profile_sha256
            and type(limit["max_dispatches"]) is int
            and limit["max_dispatches"] == 1,
            "stage-progression-consent-stage-not-covered",
        )
        return pin

    def _claim(
        self,
        credential,
        key,
        binding,
        stage,
        upstream,
        consent_pin,
        profile,
        check_deadline,
    ):
        project = self.intake.read(credential, binding["project_ref"])
        _check(self._binding(project) == binding, "stage-progression-project-differs")
        body = {
            "key": key,
            "revision": project["revision"],
            "input_version": binding["input_version"],
            "brief_sha256": binding["brief_sha256"],
            "stage": stage,
            "predecessor_sha256": upstream,
            "profile_sha256": profile,
            "consent_receipt_sha256": consent_pin,
            "settings_sha256": binding["settings_sha256"],
        }

        def reserve(state, _request_hash, _principal):
            _check(
                sha(canonical(state["settings"])) == binding["settings_sha256"],
                "stage-progression-project-differs",
            )

        # Reserve a durable attempt before handing off. The actual stage must run
        # outside the intake transaction because it owns its own transaction.
        return self.intake._perform(
            self.intake._principal(credential),
            binding["project_ref"],
            "stage-progression-dispatch",
            body,
            lambda *_: {
                "stage": stage,
                "dispatch_status": "reserved",
                "predecessor_sha256": upstream,
            },
            reserve=reserve,
            check_deadline=check_deadline,
        )

    def _receipt(self, credential, ref, key):
        try:
            return self.intake.action(credential, key, project_ref=ref)
        except SessionApiError as error:
            if error.code != "intake-action-unavailable":
                raise
            return None

    def _progress(
        self, credential, ref, *, advance, expected=None, check_deadline=None
    ):
        project = self.intake.read(credential, ref)
        if expected is not None:
            _check(
                type(project.get("input_version")) is int
                and (project["input_version"], project["brief_sha256"]) == expected,
                "stage-progression-project-differs",
            )
        output = {"project_ref": ref, "execution_authorized": False, "stages": {}}
        if (
            type(project.get("input_version")) is not int
            or project.get("settings") is None
            or project.get("stage1_intake_ready") is not True
        ):
            return dict(output, status="waiting-for-project-scope")
        binding = self._binding(project)
        output["input_version"] = binding["input_version"]
        for stage in self._stages:
            step = self._steps[stage]
            upstream = step.predecessor(credential, binding.copy())
            if upstream is None:
                return dict(output, status="waiting-for-predecessor", stage=stage)
            _check(_hash(upstream), "stage-progression-predecessor-invalid")
            # One dispatch slot per project, integer input version and stage.
            # Consent reissue, a changed profile, or a new upstream hash cannot
            # create a second slot. The tracker still records the exact binding.
            key = "auto-" + sha(canonical([ref, binding["input_version"], stage]))
            result = step.read_result(credential, binding.copy(), upstream, key)
            if result is not None:
                _check(_hash(result), "stage-progression-result-invalid")
                output["stages"][stage] = {"status": "saved", "result_sha256": result}
                continue
            if self._receipt(credential, ref, key) is not None:
                return dict(output, status="execution-unknown", stage=stage, key=key)
            if not advance:
                return dict(output, status="not-started", stage=stage)

            if check_deadline is not None:
                check_deadline()
            consent_pin = self._consent(credential, binding, stage, step.profile_sha256)
            step.connect(credential, binding.copy(), upstream, consent_pin)
            grant = step.spending_grant(credential, binding.copy(), upstream, key)
            if grant is None or grant is False:
                return dict(output, status="waiting-for-spending-grant", stage=stage)
            _check(
                self._consent(credential, binding, stage, step.profile_sha256)
                == consent_pin,
                "stage-progression-consent-differs",
            )
            receipt = self._claim(
                credential,
                key,
                binding,
                stage,
                upstream,
                consent_pin,
                step.profile_sha256,
                check_deadline,
            )
            if receipt["replayed"]:
                return dict(output, status="execution-unknown", stage=stage, key=key)
            current = self.intake.read(credential, ref)
            _check(
                self._binding(current) == binding, "stage-progression-project-differs"
            )
            _check(
                step.predecessor(credential, binding.copy()) == upstream,
                "stage-progression-predecessor-differs",
            )
            _check(
                self._consent(credential, binding, stage, step.profile_sha256)
                == consent_pin,
                "stage-progression-consent-differs",
            )
            if check_deadline is None:
                step.submit(credential, binding.copy(), upstream, key, grant)
            else:
                check_deadline()
                step.submit(
                    credential,
                    binding.copy(),
                    upstream,
                    key,
                    grant,
                    check_deadline=check_deadline,
                )
            result = step.read_result(credential, binding.copy(), upstream, key)
            if result is None:
                return dict(output, status="execution-unknown", stage=stage, key=key)
            _check(_hash(result), "stage-progression-result-invalid")
            output["stages"][stage] = {"status": "saved", "result_sha256": result}
        if len(self._stages) != len(STAGES):
            return dict(
                output,
                status="waiting-for-predecessor",
                stage=STAGES[len(self._stages)],
            )
        return dict(output, status="saved")

    def consent_summary(self, credential, ref):
        """Pure readback of the launch consent; never advances and never writes."""
        project = self.intake.read(credential, ref)
        out = {
            "present": False,
            "valid": False,
            "reason": "consent-not-provided",
            "expires_at": None,
            "expired": None,
            "consent_sha256": None,
            "stages": {
                stage: {
                    "covered": False,
                    "max_dispatches": None,
                    "reason": "stage-not-connected",
                }
                for stage in STAGES
            },
        }
        try:
            source = self._read_consent(credential, ref)
        except (SessionApiError, OSError, ValueError):
            return dict(out, reason="consent-unreadable")
        if source is None:
            return out
        raw, pin = source
        out.update(present=True, reason="stage-progression-consent-invalid")
        if type(raw) is not bytes or not _hash(pin) or sha(raw) != pin:
            return dict(out, reason="stage-progression-consent-digest-differs")
        out["consent_sha256"] = pin
        try:
            consent = decode(raw, "saved stage progression consent")
            expires = datetime.fromisoformat(consent["expires_at"])
            limits = consent["stages"]
        except (LedgerError, KeyError, TypeError, ValueError):
            return out
        if expires.utcoffset() is None or type(limits) is not dict:
            return out
        out.update(expires_at=expires.isoformat(), expired=self._clock() >= expires)
        if (
            type(project.get("input_version")) is not int
            or project.get("settings") is None
        ):
            return dict(out, reason="waiting-for-project-scope")
        binding = self._binding(project)
        for stage in self._stages:
            try:
                self._consent(
                    credential, binding, stage, self._steps[stage].profile_sha256
                )
            except SessionApiError as error:
                out["stages"][stage]["reason"] = error.code
            else:
                out["stages"][stage] = {
                    "covered": True,
                    "max_dispatches": limits[stage]["max_dispatches"],
                    "reason": None,
                }
        covered = out["stages"]["stage1"]
        return dict(out, valid=covered["covered"], reason=covered["reason"])

    def read(self, credential, ref):
        """Pure readback of current verified artifacts and any pending attempt."""
        return self._progress(credential, ref, advance=False)

    def advance(self, credential, ref, *, expected=None, check_deadline=None):
        """Called after a normal authorized Host write or a verified completion."""
        self.intake.read(credential, ref)
        with self._lock:
            if ref in self._active:
                return {
                    "project_ref": ref,
                    "status": "in-progress",
                    "execution_authorized": False,
                }
            self._active.add(ref)
        try:
            return self._progress(
                credential,
                ref,
                advance=True,
                expected=expected,
                check_deadline=check_deadline,
            )
        finally:
            with self._lock:
                self._active.remove(ref)

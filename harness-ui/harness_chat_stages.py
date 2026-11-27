"""Stage 1-6 chat context availability, independent of chat authorization.

The registry accepts trusted, explicitly installed *read-only* adapters. An
adapter reports evidence already verified by its owning backend; registering
one is not verification of its declarations. This module never authenticates
a human, creates a model allowance, dispatches work, or opens a budget store.
"""

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Callable


CONTRACT_KIND = "V9StageChatAvailability"
CONTRACT_VERSION = "1.0.0"
EVIDENCE_KIND = "V9StageContextEvidence"
EVIDENCE_VERSION = "1.0.0"
MAX_PROVIDER_BYTES = 32 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PROVIDER_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,119}\Z")
_READ_ONLY_ACTIONS = ("state", "materials", "read_material")
STAGE_REQUIRED_INPUTS = {
    3: [
        "strict-selected-package",
        "required-delivery-and-independent-pins",
        "trusted-seen-selected-version-binding",
        "design-and-feasibility-originals",
    ],
    4: [
        "legal-current-run-mapping",
        "configuration-code-dependency-pins",
        "run-manifest-status-logs-and-existing-outputs",
    ],
    5: [
        "same-version-stage4-results",
        "metrics-analysis-and-data-run-bindings",
        "failures-missingness-and-comparability-records",
    ],
    6: [
        "manuscript-version-and-source-files",
        "bibliography-figures-tables-evidence-links",
        "original-review-records",
    ],
}


def require_stage(stage):
    """Accept only exact integers 1-6; bool is deliberately not a stage."""
    if type(stage) is not int or not 1 <= stage <= 6:
        raise ValueError("chat-stage-not-supported")
    return stage


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _identity(context):
    if not isinstance(context, dict):
        raise ValueError("chat-stage-context-invalid")
    stage = require_stage(context.get("stage"))
    project = context.get("project_ref")
    pin = context.get("project_pin")
    if (
        not isinstance(project, str)
        or not project.strip()
        or len(project) > 200
        or any(ord(char) < 32 or ord(char) == 127 for char in project)
    ):
        raise ValueError("chat-stage-project-invalid")
    if not isinstance(pin, str) or not _SHA256.fullmatch(pin):
        raise ValueError("chat-stage-project-pin-invalid")
    return project, stage, pin


@dataclass(frozen=True)
class _Provider:
    identity: str
    implementation_sha256: str
    observe: Callable


class StageContextRegistry:
    """Explicit Stage 3-6 read-only extension seam, with no implicit fallback.

    Stage 1/2 stay owned by the established saved-stage/material adapters.
    An adapter is called with (project_ref, stage, project_pin). It must return
    exactly kind/version/project_ref/stage/project_pin/context/binding/missing.
    binding is metadata from the trusted backend and must include a manifest
    SHA. It is not a replacement for independently verifying source bytes.
    missing is a list of stable codes; an empty list means context metadata is
    available, not that selection, model messages or research are authorized.

    Callbacks must be bounded and read-only. This in-process seam is for trusted
    application code, not a sandbox for untrusted plugins or arbitrary paths.
    """

    def __init__(self):
        self._providers = {}

    def register(self, stage, provider, *, provider_id, implementation_sha256):
        require_stage(stage)
        if stage < 3:
            raise ValueError("chat-stage-established-adapter-cannot-be-replaced")
        if stage in self._providers:
            raise ValueError("chat-stage-provider-already-registered")
        if (
            not callable(provider)
            or not isinstance(provider_id, str)
            or not _PROVIDER_ID.fullmatch(provider_id)
        ):
            raise ValueError("chat-stage-provider-invalid")
        if not isinstance(implementation_sha256, str) or not _SHA256.fullmatch(
            implementation_sha256
        ):
            raise ValueError("chat-stage-provider-implementation-pin-required")
        self._providers[stage] = _Provider(provider_id, implementation_sha256, provider)

    def _observe(self, project, stage, project_pin):
        provider = self._providers.get(stage)
        if provider is None:
            return None, "chat-stage-context-provider-unregistered", None
        try:
            value = provider.observe(project, stage, project_pin)
        except Exception:
            # Raw exceptions may contain private paths or material content.
            return provider, "chat-stage-context-provider-failed", None
        expected = {
            "kind",
            "version",
            "project_ref",
            "stage",
            "project_pin",
            "context",
            "binding",
            "missing",
        }
        if not isinstance(value, dict) or set(value) != expected:
            return provider, "chat-stage-provider-output-invalid", None
        try:
            actual_identity = _identity(value)
        except ValueError:
            return provider, "chat-stage-provider-output-invalid", None
        if actual_identity != (project, stage, project_pin):
            return provider, "chat-stage-provider-binding-differs", None
        if value["kind"] != EVIDENCE_KIND or value["version"] != EVIDENCE_VERSION:
            return provider, "chat-stage-provider-version-unsupported", None
        binding, missing = value["binding"], value["missing"]
        if (
            not isinstance(binding, dict)
            or not binding
            or "manifest_sha256" not in binding
            or any(
                not isinstance(key, str)
                or not _PROVIDER_ID.fullmatch(key)
                or not isinstance(pin, str)
                or not _SHA256.fullmatch(pin)
                for key, pin in binding.items()
            )
        ):
            return provider, "chat-stage-provider-evidence-binding-required", None
        if (
            not isinstance(missing, list)
            or len(missing) > 32
            or any(
                not isinstance(code, str) or not _PROVIDER_ID.fullmatch(code)
                for code in missing
            )
            or len(set(missing)) != len(missing)
        ):
            return provider, "chat-stage-provider-missing-codes-invalid", None
        if not isinstance(value["context"], dict):
            return provider, "chat-stage-provider-context-invalid", None
        try:
            raw = _canonical(value)
            if len(raw) > MAX_PROVIDER_BYTES:
                return provider, "chat-stage-provider-context-too-large", None
            # Detach mutable/provider-owned values; reject exotic Python values
            # via a canonical JSON round trip rather than returning references.
            observed = json.loads(raw)
        except (ValueError, TypeError, RecursionError, UnicodeError):
            return provider, "chat-stage-provider-context-invalid", None
        return (
            provider,
            ("chat-stage-required-evidence-missing" if missing else None),
            observed,
        )

    def read_material(self, project, stage, project_pin, identity):
        """Optional trusted byte-reader bridge; never installs a provider itself."""
        provider = self._providers.get(require_stage(stage))
        reader = getattr(provider.observe, "read_material", None) if provider else None
        if not callable(reader):
            raise ValueError("chat-stage-material-reader-unavailable")
        require_context_available(
            stage_availability_context(project, stage, project_pin, self)
        )
        try:
            return reader(project, stage, project_pin, identity)
        except Exception:
            raise ValueError("chat-stage-material-read-failed") from None


def stage_availability_context(project, stage, project_pin, registry):
    context = dict(project_ref=project, stage=stage, project_pin=project_pin)
    return dict(context, stage_availability=stage_availability(context, registry))


def stage_availability(context, registry=None):
    """Return a serializable, non-authorizing availability envelope.

    The caller first resolves an actual project with the established Harness
    context adapter. Passing arbitrary UI input directly here is insufficient
    evidence that that project exists. Stage 1/2 retain their existing context
    and material semantics; Stage 3-6 require an explicit backend adapter.
    """
    project, stage, pin = _identity(context)
    if registry is not None and not isinstance(registry, StageContextRegistry):
        raise ValueError("chat-stage-provider-registry-invalid")
    value = dict(
        kind=CONTRACT_KIND,
        version=CONTRACT_VERSION,
        project_ref=project,
        stage=stage,
        project_pin=pin,
        context_available=stage < 3,
        context_source="existing-stage-adapter" if stage < 3 else "unconnected",
        model_messages_allowed=False,
        research_execution=False,
        formal_selection=False,
        blocked_reason=None,
        message_blocked_reason="chat-separate-message-authorization-required",
        research_blocked_reason="chat-research-execution-not-offered",
        provider=None,
        evidence_binding=None,
        observed_context=None,
        missing=[],
    )
    if stage < 3:
        return value
    value["required_inputs"] = list(STAGE_REQUIRED_INPUTS[stage])
    value["requirements_scope"] = "material-categories-not-native-contract-validation"
    value["upstream_task_url"] = (
        "https://github.com/WenyuChiou/AutoResearchAgent/issues/355"
    )
    provider, reason, observed = (registry or StageContextRegistry())._observe(
        project, stage, pin
    )
    value["blocked_reason"] = reason
    if provider is not None:
        value["provider"] = dict(
            id=provider.identity, implementation_sha256=provider.implementation_sha256
        )
    if observed is not None:
        value["evidence_binding"] = dict(observed["binding"])
        value["observed_context"] = deepcopy(observed["context"])
        value["missing"] = list(observed["missing"])
        value["observed_context_sha256"] = hashlib.sha256(
            _canonical(observed["context"])
        ).hexdigest()
    value["context_available"] = reason is None
    if reason is None:
        value["context_source"] = "explicit-read-only-stage-adapter"
    return value


def attach_stage_availability(context, registry=None):
    """Add availability without changing Stage 1/2 action/material rules.

    Future stages expose only existing read actions. A ready context does not
    enable writes, select a candidate, or grant model/research authorization.
    """
    result = deepcopy(context)
    availability = stage_availability(result, registry)
    result["stage_availability"] = availability
    if result["stage"] >= 3:
        actions = (
            _READ_ONLY_ACTIONS
            if availability["context_available"]
            else _READ_ONLY_ACTIONS[:2]
        )
        result["supported_actions"] = [
            action
            for action in result.get("supported_actions", [])
            if action in actions
        ]
        capabilities = result.setdefault("capabilities", {})
        for key in (
            "material_registration",
            "local_review_notes",
            "formal_selection",
            "research_execution",
            "saved_stage_reading",
            "offline_workflow_preparation",
        ):
            capabilities[key] = False
        capabilities["stage_execution"] = "not-authorized"
    return result


def require_context_available(context):
    """Guard a future send attempt after the context adapter has run.

    This guard only checks stage-context availability. Passing it is never a
    substitute for independent authorization, source pins and budget checks.
    """
    _identity(context)
    availability = context.get("stage_availability")
    if (
        not isinstance(availability, dict)
        or availability.get("kind") != CONTRACT_KIND
        or availability.get("version") != CONTRACT_VERSION
        or (
            availability.get("project_ref"),
            availability.get("stage"),
            availability.get("project_pin"),
        )
        != _identity(context)
    ):
        raise ValueError("chat-stage-availability-binding-required")
    if availability.get("context_available") is not True:
        raise ValueError(
            availability.get("blocked_reason") or "chat-stage-context-unavailable"
        )
    return availability

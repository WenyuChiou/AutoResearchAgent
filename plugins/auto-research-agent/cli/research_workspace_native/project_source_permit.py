"""Pure version-bound public-source offers; no fetch, DNS, probe or durable grant.

The trusted caller verifies runtime/source configuration before supplying it.
These checks bind an explicit displayed URL to actual Core discovery/screening;
they do not enforce transport limits or authenticate source/scientific evidence.
A separate service must persist approval, causal reservations and job history.
"""

from copy import deepcopy
import ipaddress
import math
import re
from urllib.parse import quote, urlsplit

from stage1_deliverable.common import DeliverableError, canonical, sha
from stage1_deliverable.records import public_uri
from stage1_ledger.source_arguments import check_source_arguments

from .planned_query_contract import tree_sha
from .project_stage1 import ProjectStage1Service, _basis
from .session_api import SessionApiError, _check, _hash

CAP_MAXIMA = {
    "max_fetches": 128,
    "max_reserved_seconds": 86400,
    "timeout_seconds": 300,
    "validity_seconds": 86400,
    "max_response_bytes": 16 * 1024 * 1024,
    "max_http_attempts": 16,
}
CONFIG_FIELDS = {"caps", "runtime_sha256", "execution_source_sha256"}
DOI = re.compile(r"10\.\d{4,9}/[^\s]+")


def public_source_uri(value):
    """Reject structural/private literal targets, without resolving a hostname.

    Public DNS, rebinding, redirect and actual connection checks remain required
    in the independently admitted transport. Passing this is not a DNS result.
    """
    _check(type(value) is str, "project-source-url-invalid", 400)
    try:
        size = len(value.encode("utf8"))
    except UnicodeError as error:
        raise SessionApiError("project-source-url-invalid", 400) from error
    _check(
        0 < size <= 4096
        and not any(ord(character) < 33 for character in value)
        and "\\" not in value,
        "project-source-url-invalid",
        400,
    )
    try:
        check_source_arguments(
            dict(
                kind="SourceReadStarted",
                source_uri=value,
                request={"public_only": True},
            )
        )
        public_uri(value)
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
        _check(
            not parsed.fragment
            and "%" not in host
            and host not in {"localhost", "localhost.localdomain"}
            and not host.endswith((".localhost", ".local", ".internal"))
            and port in (None, 443 if parsed.scheme == "https" else 80),
            "project-source-url-invalid",
            400,
        )
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            _check("." in host, "project-source-url-invalid", 400)
        else:
            _check(
                address.is_global and not address.is_multicast,
                "project-source-url-invalid",
                400,
            )
    except (DeliverableError, ValueError, UnicodeError) as error:
        raise SessionApiError("project-source-url-invalid", 400) from error
    return value


def configuration(config):
    """Validate externally verified policy bytes; never import/probe a runtime."""
    _check(
        type(config) is dict
        and CONFIG_FIELDS <= set(config) <= CONFIG_FIELDS | {"url_policy"}
        and _hash(config["runtime_sha256"])
        and _hash(config["execution_source_sha256"]),
        "project-source-configuration-invalid",
        400,
    )
    caps = config["caps"]
    _check(
        type(caps) is dict
        and set(caps) == set(CAP_MAXIMA)
        and all(
            type(caps[key]) is int and 1 <= caps[key] <= maximum
            for key, maximum in CAP_MAXIMA.items()
        ),
        "project-source-caps-invalid",
        400,
    )
    policy = config.get("url_policy", {"allow_doi_resolution": True})
    _check(
        type(policy) is dict
        and set(policy) == {"allow_doi_resolution"}
        and type(policy["allow_doi_resolution"]) is bool,
        "project-source-url-policy-invalid",
        400,
    )
    return dict(
        caps=deepcopy(caps),
        runtime_sha256=config["runtime_sha256"],
        execution_source_sha256=config["execution_source_sha256"],
        url_policy=deepcopy(policy),
    )


def configuration_sha(config):
    return sha(canonical(configuration(config)))


def _budget(state, name, fields):
    budget = state.get(name)
    if budget is None:
        return {key: 0 for key in fields}
    _check(
        type(budget) is dict
        and set(budget) == set(fields)
        and all(
            (
                (type(value) is int or type(value) is float and math.isfinite(value))
                if key == "seconds"
                else type(value) is int
            )
            and value >= 0
            for key, value in budget.items()
        ),
        "project-source-reservation-state-invalid",
    )
    return budget


def _limits(state, settings, config):
    _check(
        settings["consent"]["public_source_read"] is True,
        "project-source-consent-required",
    )
    query = _budget(state, "stage1_query_budget", ("probes", "attempts", "seconds"))
    source = _budget(state, "stage1_source_budget", ("fetches", "seconds"))
    remaining_seconds = (
        settings["budgets"]["seconds"] - query["seconds"] - source["seconds"]
    )
    remaining_fetches = settings["budgets"]["source_reads"] - source["fetches"]
    caps = config["caps"]
    seconds = min(remaining_seconds, caps["max_reserved_seconds"])
    fetches = min(remaining_fetches, caps["max_fetches"])
    _check(
        type(fetches) is int and fetches > 0 and seconds >= caps["timeout_seconds"],
        "project-source-requested-budget-insufficient",
        429,
    )
    return dict(
        max_fetches=fetches,
        max_reserved_seconds=seconds,
        **{
            key: caps[key]
            for key in (
                "timeout_seconds",
                "validity_seconds",
                "max_response_bytes",
                "max_http_attempts",
            )
        },
    )


def _selected(ledger, work_id, config):
    candidate = ledger.candidates().get(work_id)
    _check(candidate is not None, "project-source-work-unavailable", 404)
    events = [row["payload"] for row in ledger.events()]
    decision = next(
        (
            row
            for row in reversed(events)
            if row["kind"] == "DecisionEvent" and row["subject_id"] == work_id
        ),
        None,
    )
    _check(decision is not None, "project-source-current-decision-required")
    _check(
        decision["new_decision"] in {"include", "pending"},
        "project-source-current-work-excluded",
    )
    review = ledger.coverage_state().evidence.current().get(work_id)
    if review is not None:
        _check(
            review["candidate_event_id"] == candidate["event_id"]
            and review["decision_event_id"] == decision["event_id"],
            "project-source-current-review-stale",
        )
    version = (
        review["version_id"] if review else candidate["discoveries"][-1]["version_id"]
    )
    finished = {
        row["attempt_id"] for row in events if row["kind"] == "SourceReadFinished"
    }
    _check(
        not any(
            row["kind"] == "SourceReadStarted"
            and row["work_id"] == work_id
            and row["version_id"] == version
            and row["event_id"] not in finished
            for row in events
        ),
        "project-source-attempt-pending",
    )
    discovery = next(
        row
        for row in reversed(candidate["discoveries"])
        if row["version_id"] == version
    )
    # Core Record currently has no URL field. Do not widen its schema or invent
    # a saved URL: expose the exact DOI resolver proposal for explicit approval.
    doi = discovery["record"].get("doi")
    _check(
        config["url_policy"]["allow_doi_resolution"] is True,
        "project-source-doi-resolution-disabled",
    )
    _check(
        type(doi) is str and DOI.fullmatch(doi) is not None,
        "project-source-url-unavailable",
    )
    uri = public_source_uri("https://doi.org/" + quote(doi, safe="/"))
    return dict(
        work_id=work_id,
        candidate_event_id=candidate["event_id"],
        candidate_sha256=sha(canonical(candidate)),
        current_decision_event_id=decision["event_id"],
        current_decision_sha256=sha(canonical(decision)),
        current_decision=decision["new_decision"],
        version_id=version,
        current_review_event_id=review["event_id"] if review else None,
        discovery_id=discovery["discovery_id"],
        discovery_sha256=sha(canonical(discovery)),
        metadata=deepcopy(discovery["record"]),
        source_uri=uri,
        url_origin="server-proposed-resolver-for-exact-saved-doi",
    )


def proposal(intake, stage1, ref, principal, config, work_id):
    """Return a source-specific proposal over the current authenticated run."""
    _check(
        isinstance(stage1, ProjectStage1Service) and stage1.intake is intake,
        "project-source-stage1-service-required",
    )
    _check(type(work_id) is str and bool(work_id), "project-source-work-required", 400)
    verified = configuration(config)
    with intake._lock:
        state = intake._load(principal, ref)
        binding = intake.binding(ref)
        run, ledger, report = stage1._ledger(state, binding)
        limits = _limits(state, binding["settings"], verified)
        selected = _selected(ledger, work_id, verified)
        document = dict(
            kind="Stage1ProjectSourceAuthorizationOffer",
            schema_version="1.0.0",
            project_ref=ref,
            principal=principal,
            binding=dict(
                _basis(binding),
                plan_sha256=tree_sha(binding["plan_root"]),
                run_ref=run["run_ref"],
                run_id=ledger.manifest["research_run"]["run_id"],
                manifest_sha256=run["manifest_sha256"],
                ledger_state_sha256=report["state_sha256"],
                journal_sha256=sha((ledger.root / "stage_events.jsonl").read_bytes()),
                reservation_state_sha256=sha(
                    canonical(
                        {
                            name: state.get(name)
                            for name in ("stage1_query_budget", "stage1_source_budget")
                        }
                    )
                ),
            ),
            selected=selected,
            runtime_sha256=verified["runtime_sha256"],
            execution_source_sha256=verified["execution_source_sha256"],
            server_configuration_sha256=sha(canonical(verified)),
            limits=limits,
            url_policy=verified["url_policy"],
            scope=["fetch-selected-public-source"],
            allow_source_acquisition=True,
            allow_search=False,
            model_execution=False,
            automatic_retry=False,
            execution_authorized=False,
            transport_validation="not-observed; required-before-execution",
            scientific_acceptance=False,
        )
        _check(len(canonical(document)) <= 65536, "project-source-offer-too-large")
        digest = sha(canonical(document))
        return (
            binding,
            document,
            dict(
                offer_ref="project-source-" + digest[:32],
                offer_sha256=digest,
                document=deepcopy(document),
            ),
        )


def inspect(
    intake, stage1, ref, principal, config, work_id, document, expected_offer_sha256
):
    """Recompute exact current semantics; approval/history remain the caller's job."""
    _check(
        type(document) is dict
        and _hash(expected_offer_sha256)
        and sha(canonical(document)) == expected_offer_sha256,
        "project-source-offer-bytes-differ",
    )
    _, current, offer = proposal(intake, stage1, ref, principal, config, work_id)
    _check(
        document == current and expected_offer_sha256 == offer["offer_sha256"],
        "project-source-current-offer-differs",
    )
    return deepcopy(current)

"""Version-bound, content-only model operations for universal project intake.

No provider or permit is inferred from a budget declaration. Trusted bootstrap
alone registers an immutable permit and a deny-only StageUnitProvider factory.
Reads never construct that provider. Model prose does not decide ResearchBrief
scope, prove source evidence, execute a query, or complete a research stage.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
import re
import sqlite3
import threading
import time
import uuid

from stage1_brief.brief import compile_confirmed, validate_bound_plan
from stage1_deliverable.common import (
    canonical,
    identifier,
    private_output,
    safe_path,
    sha,
)
from stage1_ledger.journal import decode
from .session_api import SessionApiError, _check
from .stage_run_service import StageUnitProvider
from .transport import validate_answer
from .project_resource_budget import reserve_resource, resource_view
from .project_model_recovery import public_retirement, retired, retire
from .project_model_reading import (
    READ_OPERATION,
    READ_SCOPE,
    reading_prompt,
    saved_reading_snapshot,
    validate_reading_draft,
)

OPERATIONS = {"suggest-topic", "plan-search", READ_OPERATION}
PERMIT_FIELDS = {
    "kind",
    "schema_version",
    "permission_id",
    "principal",
    "project_id",
    "input_version",
    "brief_sha256",
    "budget_sha256",
    "operation",
    "model",
    "max_calls",
    "max_seconds",
    "expires_at",
    "allow_model_calls",
    "execution_scope",
    "external_search",
    "frozen_subjects",
}
BODY_FIELDS = {
    "key",
    "revision",
    "input_version",
    "brief_sha256",
    "offer_ref",
    "offer_sha256",
    "confirmed",
}
RUNTIME_DIGEST_HEX = 24
TERMINAL = {
    "content-review-pending",
    "plan-validated-not-executed",
    "validation-failed",
    "failed-or-unknown",
    "execution-unknown",
}


def budget_digest(binding):
    """Digest a researcher-declared resource version, never execution authority."""
    settings = binding.get("settings")
    _check(
        type(settings) is dict and type(settings.get("budgets")) is dict,
        "model-resource-request-missing",
    )
    _check(
        settings.get("brief_sha256") == binding["brief_sha256"],
        "model-resource-version-differs",
    )
    return sha(canonical(settings["budgets"]))


def _expiry(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _check(parsed.utcoffset() is not None, "model-permit-expiry-timezone")
        return parsed.timestamp()
    except (AttributeError, TypeError, ValueError) as error:
        raise SessionApiError("model-permit-expiry-invalid") from error


def _write_new(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": path.name, "sha256": sha(raw), "bytes": len(raw)}


def _preview(text):
    raw = text.encode("utf8")
    return {
        "text": raw[:512].decode("utf8", errors="ignore"),
        "truncated": len(raw) > 512,
        "sha256": sha(raw),
        "bytes": len(raw),
    }


def _output_ref(job):
    raw = job.get("raw_output")
    return (
        None
        if raw is None
        else sha(canonical([job["source_sha256"], job["key"], raw["sha256"]]))
    )


def _prompt(operation, binding, as_of):
    brief = binding["brief"]
    rules = (
        "Use only the attached researcher input. No tools, search, source access, "
        "execution, citations invented as evidence, or changes to frozen subjects. "
        "Missing literature/data/validation basis remains Unknown. Budget is not "
        "a sufficiency criterion. This output is reviewed content, not research.\n"
    )
    if operation == "suggest-topic":
        task = (
            "Suggest possible research topics/directions matching the original "
            "interest; state assumptions, unresolved scope and evidence gaps. "
            "Return prose for the researcher to review. Do not decide scope, "
            "claim recommendations have evidence, or fabricate source refs.\n"
        )
    else:
        task = (
            "Author a coverage search-plan proposal for this confirmed brief. "
            "Return exactly one JSON object with proposal and query_bindings, "
            "without markdown fences. proposal.topic must exactly equal the "
            "original_description. Proposal fields: plan_id; topic; decomposition "
            "{population,phenomenon,method,validation}; inclusion_criteria and "
            "exclusion_criteria text arrays; concepts [{concept_id,terms:[text]}]; "
            "clusters [{cluster_id,label,question,min_included_works,query_families:"
            "[{family_id,concept_ids:[id],adversarial_queries:[text]}]}]; stop_policy "
            "{max_rounds,consecutive_zero_yield_rounds,closest_min_verified,"
            "require_references:true,require_cited_by:true}. query_bindings must "
            "map every family: {family_id,need_ids:[existing need],purpose:"
            "study-evidence or transferable-method,scope_filters:{}}; only exact "
            "confirmed specified scope values may narrow study evidence. A "
            "transferable-method geography comparison requires transfer_rationale. "
            "Do not turn formal/priority counts into keywords. The real compiler "
            "will validate this; no query is executed. As-of date: " + as_of + ".\n"
        )
    text = (
        rules
        + task
        + "ResearchBrief (original text preserved):\n"
        + canonical(brief).decode()
    )
    _check(
        0 < len(text.encode("utf8")) <= 32768 and len(canonical(text)) <= 63488,
        "model-task-prompt-too-large",
    )
    return text


def _offer_record(binding, permit, permit_sha256, project_ref, snapshot=None):
    # Replay uses immutable permit bytes, never the current calendar date.
    as_of = (
        datetime.fromtimestamp(
            _expiry(permit["expires_at"]) - permit["max_seconds"], timezone.utc
        )
        .date()
        .isoformat()
    )
    prompt = (
        reading_prompt(snapshot)
        if permit["operation"] == READ_OPERATION
        else _prompt(permit["operation"], binding, as_of)
    )
    context = {
        key: deepcopy(binding[key])
        for key in ("project_id", "input_version", "brief_sha256", "brief", "settings")
    }
    context.update(
        project_ref=project_ref,
        operation=permit["operation"],
        model=permit["model"],
        budget_sha256=budget_digest(binding),
        permit_sha256=permit_sha256,
        prompt_sha256=sha(prompt.encode("utf8")),
        as_of=as_of,
        deny_only=True,
        trusted_stage_unit=True,
        max_calls=permit["max_calls"],
        max_seconds=permit["max_seconds"],
        expires_at=permit["expires_at"],
    )
    if snapshot is not None:
        context.update(
            saved_reading=deepcopy(snapshot),
            snapshot_sha256=sha(canonical(snapshot)),
            work_ref=permit["work_ref"],
        )
    context["source_sha256"] = sha(canonical(context))
    offer_hash = sha(canonical(context))
    return dict(
        context=context,
        prompt=prompt,
        offer_ref="model-offer-" + offer_hash[:32],
        offer_sha256=offer_hash,
        permit_sha256=permit_sha256,
    )


class ProjectModelService:
    """A durable no-resend broker; factories are server-only deny-only seams.

    ``provider_factory(context=..., admit=..., output_root=...)`` must construct a
    fixed-own-account, deny-only StageModel (or an explicitly synthetic test
    provider). The browser cannot supply this callback, paths, permissions, model,
    prompt, RPC, modes or limits. A callback is not authentication evidence.
    """

    def __init__(
        self,
        intake,
        *,
        provider_factory=None,
        clock=time.time,
        monotonic=time.monotonic,
        model=None,
        local_cap_seconds=600,
        reading_records=None,
    ):
        _check(
            provider_factory is None or callable(provider_factory),
            "model-provider-factory-invalid",
        )
        self.intake, self.factory = intake, provider_factory
        self.clock, self.monotonic = clock, monotonic
        _check(
            model is None
            or type(model) is str
            and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", model),
            "model-server-selection-invalid",
        )
        _check(
            type(local_cap_seconds) is int and 0 < local_cap_seconds <= 600,
            "model-local-cap-invalid",
        )
        self.model, self.local_cap_seconds = model, local_cap_seconds
        self.reading_records = None
        if reading_records is not None:
            self.attach_reading_records(reading_records)
        self._registrations, self._owners, self._workers, self._providers = (
            {},
            {},
            {},
            {},
        )
        self._tokens = {}
        self._closed = False

    def attach_reading_records(self, records):
        """Trusted host composition only; HTTP never accepts a service or path."""
        from .project_stage1_records import ProjectStage1RecordsService

        _check(
            isinstance(records, ProjectStage1RecordsService)
            and records.intake is self.intake
            and (self.reading_records is None or self.reading_records is records),
            "reading-records-composition-differs",
        )
        self.reading_records = records

    def _reading_snapshot(self, ref, work_ref, check_deadline=None):
        return saved_reading_snapshot(
            self.reading_records, ref, work_ref, check_deadline=check_deadline
        )

    def reading_offer(
        self,
        credential,
        project_ref,
        work_ref,
        *,
        expected_input_version,
        expected_ledger_state_sha256,
        check_deadline=None,
    ):
        """Read source eligibility only; no permit, owner recovery or model start."""
        principal = self.intake._principal(credential)
        with self.intake._lock:
            self.intake._load(principal, project_ref)
            result = dict(
                kind="Stage1SavedReadingOfferPreview",
                schema_version="1.0.0",
                project_ref=project_ref,
                work_ref=work_ref,
                operation=READ_OPERATION,
                available=False,
                snapshot_sha256=None,
                blocked_reason=None,
                authorization_required=True,
                execution_authorized=False,
                scientific_acceptance=False,
            )
            if (
                self.factory is None
                or self.model is None
                or self.reading_records is None
            ):
                return dict(
                    result, blocked_reason="reading-model-or-records-unconnected"
                )
            try:
                snapshot = self._reading_snapshot(project_ref, work_ref, check_deadline)
                _check(
                    snapshot["input_version"] == expected_input_version
                    and snapshot["ledger_state_sha256"] == expected_ledger_state_sha256,
                    "reading-library-snapshot-stale",
                )
                reading_prompt(snapshot)
                result.update(
                    available=True,
                    snapshot_sha256=sha(canonical(snapshot)),
                    source_count=len(snapshot["sources"]),
                    source_failures_count=len(snapshot["source_failures"]),
                    identity_statuses=sorted(
                        {row["identity_status"] for row in snapshot["sources"]}
                    ),
                    saved_text_bytes=sum(
                        row["text_bytes"] for row in snapshot["sources"]
                    ),
                    shown_excerpt_bytes=sum(
                        row["excerpt_end_byte"] for row in snapshot["sources"]
                    ),
                    entire_saved_text_shown=all(
                        row["entire_text_in_prompt"] for row in snapshot["sources"]
                    ),
                )
            except SessionApiError as error:
                result["blocked_reason"] = error.code
            except (ValueError, OSError, KeyError, TypeError, UnicodeError):
                result["blocked_reason"] = "reading-saved-source-verification-failed"
            return result

    @staticmethod
    def _row(state):
        return state.setdefault(
            "model_operations",
            {
                "calls_reserved": 0,
                "offers": {},
                "jobs": {},
                "scopes": {},
            },
        )

    def _transaction(self, principal, ref, kind, change):
        with self.intake._lock:
            self.intake.db.execute("BEGIN IMMEDIATE")
            try:
                state = self.intake._load(principal, ref)
                if kind != "model-owner-acquired":
                    _check(
                        self._row(state).get("owner") == self._tokens.get(ref)
                        and ref in self._owners,
                        "model-owner-lost",
                    )
                result = change(state)
                state["revision"] += 1
                self.intake._save(state, kind, deepcopy(result))
                self.intake.db.commit()
                return result
            except BaseException:
                self.intake.db.rollback()
                raise

    def _owner(self, principal, ref):
        if ref in self._owners:
            return
        path = self.intake._path(ref, "model-owner.sqlite")
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = sqlite3.connect(
            private_output(path),
            timeout=0,
            isolation_level=None,
            check_same_thread=False,
        )
        try:
            lock.execute("CREATE TABLE IF NOT EXISTS owner (id INTEGER PRIMARY KEY)")
            lock.execute("BEGIN IMMEDIATE")
            self._owners[ref] = lock
            self._tokens[ref] = uuid.uuid4().hex

            def recover(state):
                row = self._row(state)
                row["owner"] = self._tokens[ref]
                unknown = []
                for job in row["jobs"].values():
                    if job["status"] not in TERMINAL:
                        job["status"] = "execution-unknown"
                        job["failure"] = "owner-recovery-no-resend"
                        unknown.append(job["key"])
                for action in row.get("native_actions", {}).values():
                    if action["status"] == "intent-recorded":
                        action.update(
                            status="execution-unknown",
                            failure="owner-recovery-no-resend",
                        )
                return {"unknown_keys": unknown, "automatic_resend": False}

            self._transaction(principal, ref, "model-owner-acquired", recover)
        except BaseException:
            self._owners.pop(ref, None)
            self._tokens.pop(ref, None)
            lock.close()
            raise

    @staticmethod
    def _runtime_identity(principal, ref, job):
        """Full source identity is retained even though its directory is short."""
        return {
            "kind": "ProjectModelRuntimeBinding",
            "schema_version": "1.0.0",
            "principal": principal,
            "project_ref": ref,
            "unit_key": "project-unit-" + sha(job["key"].encode("utf8")),
            **{
                name: job[name]
                for name in (
                    "project_id",
                    "key",
                    "input_version",
                    "brief_sha256",
                    "budget_sha256",
                    "prompt_sha256",
                    "source_sha256",
                    "request_sha256",
                    "offer_ref",
                    "offer_sha256",
                    "permit_sha256",
                    "owner",
                )
            },
        }

    @staticmethod
    def _runtime_relative(binding):
        return "m/" + sha(canonical(binding))[:RUNTIME_DIGEST_HEX]

    def _runtime_folder(self, principal, ref, job, *, create=False):
        binding = self._runtime_identity(principal, ref, job)
        _check(
            job.get("runtime_binding") == binding
            and job.get("runtime_dir") == self._runtime_relative(binding),
            "model-runtime-binding-differs",
        )
        folder = safe_path(self.intake.root, job["runtime_dir"])
        marker = folder / "binding.json"
        if create:
            folder.parent.mkdir(parents=True, exist_ok=True)
            try:
                folder.mkdir(exist_ok=False)
            except FileExistsError:
                _check(marker.is_file(), "model-runtime-binding-unobserved")
                self._check_runtime_marker(marker, binding)
                raise SessionApiError("model-runtime-already-observed") from None
            _write_new(marker, canonical(binding) + b"\n")
        self._check_runtime_marker(marker, binding)
        return folder

    @staticmethod
    def _check_runtime_marker(marker, binding):
        with private_output(marker).open("rb") as stream:
            raw = stream.read(16385)
        _check(
            len(raw) <= 16384
            and raw == canonical(binding) + b"\n"
            and decode(raw, "model runtime binding") == binding,
            "model-runtime-binding-collision",
        )

    def register(self, project_ref, *, operation, permit_path, permit_sha256):
        """Trusted launcher registration; never called from a browser body."""
        _check(not self._closed and operation in OPERATIONS, "model-operation-invalid")
        identifier(project_ref)
        _check(
            type(permit_sha256) is str and re.fullmatch("[0-9a-f]{64}", permit_sha256),
            "model-permit-hash-invalid",
        )
        path = private_output(permit_path).resolve()
        raw = path.read_bytes()
        _check(
            len(raw) <= 16384 and sha(raw) == permit_sha256, "model-permit-bytes-differ"
        )
        permit = decode(raw, "project model permit")
        _check(
            type(permit) is dict
            and set(permit)
            == PERMIT_FIELDS
            | (
                {"work_ref", "snapshot_sha256"}
                if operation == READ_OPERATION
                else set()
            )
            and permit["kind"] == "ProjectModelOperationPermit"
            and permit["schema_version"] == "1.0.0",
            "model-permit-fields",
        )
        binding = self.intake.brief_binding(
            project_ref, require_confirmed=operation != "suggest-topic"
        )
        budget = budget_digest(binding)
        _check(
            permit["operation"] == operation
            and permit["project_id"] == binding["project_id"]
            and type(permit["input_version"]) is int
            and permit["input_version"] == binding["input_version"]
            and permit["brief_sha256"] == binding["brief_sha256"]
            and permit["budget_sha256"] == budget,
            "model-permit-input-differs",
        )
        _check(
            permit["allow_model_calls"] is True
            and permit["execution_scope"]
            == (
                READ_SCOPE
                if operation == READ_OPERATION
                else "project-content-planning-only"
            )
            and permit["external_search"] is False
            and permit["frozen_subjects"] is False,
            "model-permit-scope-invalid",
        )
        _check(
            all(
                type(permit[k]) is str and 0 < len(permit[k]) <= 128
                for k in ("permission_id", "principal", "model")
            )
            and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", permit["model"]),
            "model-permit-identity-invalid",
        )
        for name, budget_name in (
            ("max_calls", "model_calls"),
            ("max_seconds", "seconds"),
        ):
            _check(
                type(permit[name]) is int
                and 0 < permit[name] <= binding["settings"]["budgets"][budget_name],
                "model-permit-budget-invalid",
            )
        expires = _expiry(permit["expires_at"])
        _check(self.clock() < expires, "model-permit-expired")
        principal = permit["principal"]
        with self.intake._lock:
            self.intake._load(principal, project_ref)
        snapshot = None
        if operation == READ_OPERATION:
            snapshot = self._reading_snapshot(project_ref, permit["work_ref"])
            _check(
                permit["snapshot_sha256"] == sha(canonical(snapshot)),
                "reading-permit-snapshot-differs",
            )
        self._owner(principal, project_ref)
        record = _offer_record(binding, permit, permit_sha256, project_ref, snapshot)
        ref, offer_hash = record["offer_ref"], record["offer_sha256"]

        def save(state):
            row = self._row(state)
            existing = row["offers"].get(ref)
            _check(
                existing is None or existing == record, "model-offer-binding-differs"
            )
            _check(
                len(row["offers"]) < 128 or existing is not None,
                "model-offer-bound-exceeded",
            )
            row["offers"][ref] = record
            return {
                "offer_ref": ref,
                "offer_sha256": offer_hash,
                "operation": operation,
            }

        self._transaction(principal, project_ref, "model-offer-registered", save)
        self._registrations[ref] = dict(
            path=path,
            permit=permit,
            expires=expires,
            permit_sha256=permit_sha256,
            project_ref=project_ref,
        )
        return self._public_offer(record)

    def authorize(self, credential, project_ref, body, *, check_deadline=None):
        """Explicit local researcher authorization; never starts a model unit.

        A draft resource request alone supplies no authority. This action binds
        one content operation to a server-selected model, one call and a bounded
        expiry. The permit and opaque offer are saved together after a durable
        intent. A post-write crash/timeout remains unknown and is never re-minted.
        """
        fields = {
            "key",
            "revision",
            "input_version",
            "brief_sha256",
            "operation",
            "confirmed",
            "user_input",
        }
        if type(body) is dict and body.get("operation") == READ_OPERATION:
            fields.update({"work_ref", "snapshot_sha256"})
        _check(
            type(body) is dict
            and set(body) == fields
            and len(canonical(body)) <= 16384,
            "model-authorization-fields",
            400,
        )
        identifier(body["key"])
        _check(
            type(body["operation"]) is str
            and body["operation"] in OPERATIONS
            and body["confirmed"] is True
            and type(body["user_input"]) is str
            and body["user_input"].strip()
            and len(body["user_input"].encode("utf8")) <= 8192,
            "model-explicit-authorization-required",
            400,
        )
        principal = self.intake._principal(credential)

        def work(state, request_hash, _):
            _check(
                not self._closed
                and self.factory is not None
                and self.model is not None,
                "model-provider-unconnected",
            )
            binding = self.intake.brief_binding(
                project_ref, require_confirmed=body["operation"] != "suggest-topic"
            )
            _check(
                binding["brief_sha256"] == body["brief_sha256"]
                and binding["input_version"] == body["input_version"],
                "model-authorization-source-differs",
            )
            digest = budget_digest(binding)
            snapshot = (
                self._reading_snapshot(project_ref, body["work_ref"], check_deadline)
                if body["operation"] == READ_OPERATION
                else None
            )
            if snapshot is not None:
                _check(
                    body["snapshot_sha256"] == sha(canonical(snapshot)),
                    "reading-authorization-snapshot-differs",
                )
            row = self._row(state)
            budgets = binding["settings"]["budgets"]
            _check(
                type(budgets["model_calls"]) is int
                and budgets["model_calls"] > 0
                and type(budgets["seconds"]) is int
                and budgets["seconds"] > 0,
                "model-zero-budget",
            )
            _check(
                not any(
                    j["status"]
                    not in {
                        "content-review-pending",
                        "plan-validated-not-executed",
                        "validation-failed",
                    }
                    and not retired(j)
                    for j in row["jobs"].values()
                ),
                "model-unsettled-operation-requires-review",
            )
            scope = row["scopes"].get(str(state["input_version"]))
            resources = resource_view(self.intake, state, principal)
            _check(resources["remaining"]["model_calls"] > 0, "model-budget-exhausted")
            seconds = min(
                math.floor(resources["remaining"]["seconds"]), self.local_cap_seconds
            )
            if scope is not None:
                _check(scope["budget_sha256"] == digest, "model-budget-version-differs")
                _check(
                    scope["calls"] < budgets["model_calls"], "model-budget-exhausted"
                )
                seconds = min(seconds, math.floor(scope["deadline_at"] - self.clock()))
            _check(seconds > 0, "model-budget-exhausted")
            permit = dict(
                kind="ProjectModelOperationPermit",
                schema_version="1.0.0",
                permission_id="ui-content-" + request_hash[:40],
                principal=principal,
                project_id=binding["project_id"],
                input_version=binding["input_version"],
                brief_sha256=binding["brief_sha256"],
                budget_sha256=digest,
                operation=body["operation"],
                model=self.model,
                max_calls=1,
                max_seconds=seconds,
                expires_at=datetime.fromtimestamp(
                    self.clock() + seconds, timezone.utc
                ).isoformat(),
                allow_model_calls=True,
                execution_scope=READ_SCOPE
                if snapshot is not None
                else "project-content-planning-only",
                external_search=False,
                frozen_subjects=False,
            )
            if snapshot is not None:
                permit.update(
                    work_ref=body["work_ref"], snapshot_sha256=sha(canonical(snapshot))
                )
            raw = canonical(permit) + b"\n"
            name = "content-permit-" + request_hash + ".json"
            record = _offer_record(binding, permit, sha(raw), project_ref, snapshot)
            _check(len(row["offers"]) < 128, "model-offer-bound-exceeded")
            artifact = _write_new(self.intake._path(project_ref, name), raw)
            row["offers"][record["offer_ref"]] = record
            authorizations = row.setdefault("authorizations", {})
            authorizations[body["key"]] = dict(
                artifact=artifact,
                offer_ref=record["offer_ref"],
                offer_sha256=record["offer_sha256"],
                operation=body["operation"],
                user_input=body["user_input"],
                input_version=body["input_version"],
                brief_sha256=body["brief_sha256"],
                budget_sha256=digest,
                max_calls=1,
                max_seconds=seconds,
                expires_at=permit["expires_at"],
            )
            return {
                "authorization_status": "saved-not-executed",
                "permit_sha256": artifact["sha256"],
                "offer_ref": record["offer_ref"],
                "offer_sha256": record["offer_sha256"],
                "max_calls": 1,
                "max_seconds": seconds,
                "expires_at": permit["expires_at"],
            }

        receipt = self.intake._perform(
            principal,
            project_ref,
            "model-authorization",
            deepcopy(body),
            work,
            check_deadline=check_deadline,
        )
        if receipt["status"] != "saved":
            return receipt
        with self.intake._lock:
            state = self.intake._load(principal, project_ref)
            saved = self._row(state)["authorizations"][body["key"]]
            permit_path = self.intake._path(project_ref, saved["artifact"]["path"])
        try:
            offer = self.register(
                project_ref,
                operation=saved["operation"],
                permit_path=permit_path,
                permit_sha256=saved["artifact"]["sha256"],
            )
            return {**receipt, "offer": offer, "connected": True}
        except (ValueError, OSError, sqlite3.Error) as error:
            failure = type(error).__name__ + ": " + str(error)[:512]
            with self.intake._lock:
                self.intake.db.execute("BEGIN IMMEDIATE")
                try:
                    current = self.intake._load(principal, project_ref)
                    self._row(current)["authorizations"][body["key"]][
                        "registration_failure"
                    ] = failure
                    current["revision"] += 1
                    self.intake._save(
                        current,
                        "model-authorization-registration-failed",
                        {"key": body["key"], "failure": failure},
                    )
                    self.intake.db.commit()
                except BaseException:
                    self.intake.db.rollback()
                    raise
            return {
                **receipt,
                "connected": False,
                "registration_failure": failure,
                "automatic_resend": False,
            }

    @staticmethod
    def _public_offer(record):
        context = record["context"]
        result = {
            **{
                k: deepcopy(context[k])
                for k in (
                    "operation",
                    "input_version",
                    "brief_sha256",
                    "budget_sha256",
                    "prompt_sha256",
                    "max_calls",
                    "max_seconds",
                    "expires_at",
                )
            },
            "offer_ref": record["offer_ref"],
            "offer_sha256": record["offer_sha256"],
            "scope": "content-only; no search or source acquisition",
            "confirmation_required": True,
        }
        if context["operation"] == READ_OPERATION:
            result.update(
                work_ref=context["work_ref"],
                snapshot_sha256=context["snapshot_sha256"],
                scope=READ_SCOPE,
                core_claims_created=False,
            )
        return result

    def _guard(self, ref, offer, *, allow_expired=False):
        _check(not self._closed and ref in self._owners, "model-owner-unavailable")
        with self.intake._lock:
            saved = self.intake.db.execute(
                "SELECT state FROM intake_projects WHERE ref=?", (ref,)
            ).fetchone()
            _check(
                saved is not None
                and json.loads(saved[0]).get("model_operations", {}).get("owner")
                == self._tokens.get(ref),
                "model-owner-lost",
            )
        registration = self._registrations.get(offer["offer_ref"])
        _check(
            registration is not None and registration["project_ref"] == ref,
            "model-offer-unconnected",
        )
        _check(
            sha(registration["path"].read_bytes()) == registration["permit_sha256"],
            "model-permit-changed",
        )
        if not allow_expired:
            _check(self.clock() < registration["expires"], "model-permit-expired")
        binding = self.intake.brief_binding(
            ref, require_confirmed=offer["context"]["operation"] != "suggest-topic"
        )
        _check(
            binding["input_version"] == offer["context"]["input_version"]
            and binding["brief_sha256"] == offer["context"]["brief_sha256"]
            and budget_digest(binding) == offer["context"]["budget_sha256"]
            and binding["brief"] == offer["context"]["brief"]
            and binding["settings"] == offer["context"]["settings"],
            "model-source-version-differs",
        )
        if offer["context"]["operation"] == READ_OPERATION:
            snapshot = self._reading_snapshot(ref, offer["context"]["work_ref"])
            _check(
                snapshot == offer["context"]["saved_reading"]
                and sha(canonical(snapshot)) == offer["context"]["snapshot_sha256"],
                "reading-source-snapshot-differs",
            )
        with self.intake._lock:
            resource_view(
                self.intake,
                self.intake._load(registration["permit"]["principal"], ref),
                registration["permit"]["principal"],
            )
        return registration

    def read(self, credential, project_ref):
        principal = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(principal, project_ref)
            row = state.get("model_operations", {})
            jobs = list(row.get("jobs", {}).values())
            brief = self.intake._brief(state)[0] if state["briefs"] else None
            return {
                "project_ref": project_ref,
                "revision": state["revision"],
                "input_version": state["input_version"],
                "brief_sha256": None if brief is None else brief["sha256"],
                "connected": self.factory is not None and project_ref in self._owners,
                "status": "registered-content-provider"
                if self.factory is not None and project_ref in self._owners
                else "unconnected",
                "calls_reserved": row.get("calls_reserved", 0),
                "jobs": [self._public_job(j, project_ref) for j in jobs[-32:]],
                "job_count": len(jobs),
                "history_has_more": len(jobs) > 32,
                "active_jobs": [
                    {
                        k: j[k]
                        for k in ("key", "status", "input_version", "brief_sha256")
                    }
                    for j in jobs
                    if j["status"] not in TERMINAL
                ],
                "unknown_count": sum(
                    j["status"] in {"failed-or-unknown", "execution-unknown"}
                    for j in jobs
                ),
                "blocking_unknown_count": sum(
                    j["status"] in {"failed-or-unknown", "execution-unknown"}
                    and not retired(j)
                    for j in jobs
                ),
                "authorization_available": self.factory is not None
                and self.model is not None,
                "saved_reading_available": self.factory is not None
                and self.model is not None
                and self.reading_records is not None,
                "local_cap_seconds": self.local_cap_seconds,
                "native_authenticated": None,
                "research_execution_connected": False,
                "automatic_resend": False,
                "stage_completion": False,
            }

    view = read

    def offers(self, credential, project_ref):
        principal = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(principal, project_ref)
            result = []
            for offer in state.get("model_operations", {}).get("offers", {}).values():
                public = self._public_offer(offer)
                try:
                    self._guard(project_ref, offer)
                    reserved = sum(
                        job.get("calls_reserved", 0)
                        for job in state.get("model_operations", {})
                        .get("jobs", {})
                        .values()
                        if job.get("offer_ref") == offer["offer_ref"]
                        and job.get("offer_sha256") == offer["offer_sha256"]
                    )
                    spent = reserved >= offer["context"]["max_calls"]
                    public["available"] = self.factory is not None and not spent
                    public["blocked_reason"] = (
                        "model-provider-unconnected"
                        if self.factory is None
                        else "model-permit-call-budget-exhausted"
                        if spent
                        else None
                    )
                except (ValueError, OSError, KeyError) as error:
                    public.update(available=False, blocked_reason=str(error)[:256])
                result.append(public)
            return {
                "project_ref": project_ref,
                "revision": state["revision"],
                "offers": result,
            }

    @staticmethod
    def _public_job(job, project_ref):
        value = {
            k: deepcopy(job[k])
            for k in (
                "key",
                "request_sha256",
                "operation",
                "input_version",
                "brief_sha256",
                "budget_sha256",
                "offer_ref",
                "offer_sha256",
                "prompt_sha256",
                "source_sha256",
                "status",
                "failure",
                "raw_output",
                "verified_receipt",
                "plan_manifest_sha256",
                "calls_reserved",
                "reservation_seconds",
                "usage",
                "cost",
                "started_at",
                "finished_at",
                "close_failure",
                "work_ref",
                "snapshot_sha256",
                "reading_draft",
            )
            if k in job
        }
        value["kind"] = "model-operation"
        value["project_ref"] = job.get("project_ref", project_ref)
        for name in ("raw_output", "verified_receipt", "observed_receipt"):
            if name in job:
                value[name] = {k: job[name][k] for k in ("sha256", "bytes")}
        for name in ("usage", "cost"):
            if name in value and len(canonical(value[name])) > 512:
                value[name] = {
                    "status": "recorded-in-receipt",
                    "sha256": sha(canonical(value[name])),
                }
        for name in ("failure", "close_failure"):
            if name in value:
                value[name] = _preview(value[name])["text"]
        if job.get("raw_output") is not None:
            text = job.get("output_preview", job.get("output"))
            value.update(
                output_preview=None if text is None else _preview(text)["text"],
                output_truncated=job["raw_output"]["bytes"] > 512,
                output_sha256=job["raw_output"]["sha256"],
                output_bytes=job["raw_output"]["bytes"],
            )
        value["output_ref"] = _output_ref(job)
        value.update(public_retirement(job))
        return value

    @staticmethod
    def _public_authorization(saved):
        value = {
            k: deepcopy(v)
            for k, v in saved.items()
            if k not in {"user_input", "artifact"}
        }
        preview = _preview(saved["user_input"])
        value.update(
            user_input_preview=preview["text"],
            user_input_truncated=preview["truncated"],
            user_input_sha256=preview["sha256"],
        )
        value["permit_artifact"] = {
            k: saved["artifact"][k] for k in ("sha256", "bytes")
        }
        return value

    def history(self, credential, project_ref, offset=0):
        _check(type(offset) is int and offset >= 0, "model-history-offset-invalid", 400)
        principal = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(principal, project_ref)
            row = state.get("model_operations", {})
            jobs = list(row.get("jobs", {}).values())
            authorizations = list(row.get("authorizations", {}).items())
            total = max(len(jobs), len(authorizations))
            return {
                "project_ref": project_ref,
                "revision": state["revision"],
                "actions": [
                    self._public_job(j, project_ref) for j in jobs[offset : offset + 32]
                ],
                "authorizations": {
                    k: self._public_authorization(v)
                    for k, v in authorizations[offset : offset + 32]
                },
                "offset": offset,
                "next_offset": offset + 32 if offset + 32 < total else None,
                "order": "oldest-first",
                "job_count": len(jobs),
                "authorization_count": len(authorizations),
                "automatic_resend": False,
            }

    def output(self, credential, project_ref, output_ref, *, offset=0):
        """Historical output, in fixed <=16-KiB UTF-8 chunks; no native I/O."""
        _check(
            type(output_ref) is str
            and re.fullmatch("[0-9a-f]{64}", output_ref)
            and type(offset) is int
            and offset >= 0,
            "model-output-ref-invalid",
            400,
        )
        principal = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(principal, project_ref)
            jobs = [
                j
                for j in state.get("model_operations", {}).get("jobs", {}).values()
                if _output_ref(j) == output_ref
            ]
            _check(len(jobs) == 1, "model-output-unavailable", 404)
            job = deepcopy(jobs[0])
        if "runtime_dir" in job:
            path = safe_path(
                self._runtime_folder(principal, project_ref, job), "output.txt"
            )
        else:
            # Historical saved outputs retain their original location and hashes.
            path = self.intake._path(
                project_ref, "model-" + sha(job["key"].encode()) + "/output.txt"
            )
        raw = path.read_bytes()
        _check(
            len(raw) <= 1048576
            and len(raw) == job["raw_output"]["bytes"]
            and sha(raw) == job["raw_output"]["sha256"],
            "model-output-bytes-differ",
        )
        _check(offset <= len(raw), "model-output-offset-invalid", 400)
        try:
            tail = raw[offset:].decode("utf8")
        except UnicodeDecodeError as error:
            raise SessionApiError("model-output-offset-boundary", 400) from error
        chunk = tail.encode("utf8")[:16384].decode("utf8", errors="ignore")
        end = offset + len(chunk.encode("utf8"))
        return {
            "project_ref": project_ref,
            "output_ref": output_ref,
            "output_sha256": sha(raw),
            "total_bytes": len(raw),
            "offset": offset,
            "text": chunk,
            "next_offset": end if end < len(raw) else None,
            "complete": end == len(raw),
            "chunk_is_partial": offset != 0 or end < len(raw),
            "input_version": job["input_version"],
            "brief_sha256": job["brief_sha256"],
            "source_sha256": job["source_sha256"],
            "status": job["status"],
            "untrusted_model_content": True,
        }

    def outputs(self, credential, project_ref, output_ref, offset=0):
        return self.output(credential, project_ref, output_ref, offset=offset)

    def _active(self, credential, ref):
        principal = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(principal, ref)
            active = [
                j for j in self._row(state)["jobs"].values() if j["status"] == "running"
            ]
            _check(len(active) == 1, "model-native-session-unavailable")
            job = deepcopy(active[0])
            offer = deepcopy(self._row(state)["offers"][job["offer_ref"]])
        provider = self._providers.get((ref, job["key"]))
        _check(provider is not None, "model-native-session-unavailable")
        return principal, job, offer, provider

    def native_view(self, credential, project_ref):
        """Pure observation of the already active provider, never attachment/pump."""
        principal = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(principal, project_ref)
            actions = deepcopy(
                list(
                    state.get("model_operations", {}).get("native_actions", {}).values()
                )
            )
        try:
            _, job, _, provider = self._active(credential, project_ref)
            _check(
                callable(getattr(provider, "status", None)),
                "model-native-view-unavailable",
            )
            status = provider.status()
            view = status.get("native_view")
            _check(view is None or type(view) is dict, "model-native-view-invalid")
            return {
                "project_ref": project_ref,
                "operation_key": job["key"],
                "native_view": deepcopy(view),
                "connected": view is not None,
                "approval_policy": "decline-or-cancel-only",
                "automatic_resend": False,
                "native_actions": actions,
            }
        except Exception as error:
            return {
                "project_ref": project_ref,
                "native_view": None,
                "connected": False,
                "blocked_reason": error.code
                if isinstance(error, SessionApiError)
                else "model-native-view-unavailable",
                "automatic_resend": False,
                "native_actions": actions,
            }

    def _validate_native_target(self, ref, kind, body, provider):
        """Inspect a saved projection only; this does not call a mutation method."""
        fields = {"key", "revision", "index_sha256", "input_version"} | (
            {"request_ref", "request_sha256", "result"}
            if kind == "answer"
            else {"action_ref", "action_sha256"}
        )
        _check(set(body) == fields, "model-native-action-fields", 400)
        _check(
            type(body["revision"]) is int and 0 <= body["revision"] <= 2**63 - 1,
            "model-native-revision-invalid",
            400,
        )
        for field in ("index_sha256", "input_version"):
            _check(
                type(body[field]) is str and re.fullmatch("[0-9a-f]{64}", body[field]),
                "model-native-identity-invalid",
                400,
            )
        status = provider.status()
        view = status.get("native_view")
        _check(type(view) is dict, "model-native-view-unavailable")
        _check(
            view.get("project_ref") == ref
            and all(
                view.get(field) == body[field]
                for field in ("index_sha256", "input_version", "revision")
            ),
            "model-native-source-or-revision-differs",
        )
        _check(not view.get("failure"), "model-native-session-stopped")
        target, target_hash, records = (
            ("request_ref", "request_sha256", "requests")
            if kind == "answer"
            else ("action_ref", "action_sha256", "operations")
        )
        identifier(body[target])
        _check(
            type(body[target_hash]) is str
            and re.fullmatch("[0-9a-f]{64}", body[target_hash]),
            "model-native-target-hash-invalid",
            400,
        )
        rows = view.get(records)
        _check(type(rows) is list, "model-native-view-invalid")
        matches = [row for row in rows if row.get(target) == body[target]]
        _check(len(matches) == 1, "model-native-target-unavailable")
        saved = matches[0]
        _check(
            saved.get(target_hash) == body[target_hash], "model-native-target-differs"
        )
        if kind == "answer":
            _check(saved.get("status") == "pending", "model-native-request-not-pending")
            result = validate_answer(
                {"method": saved["method"], "params": saved["payload"]}, body["result"]
            )
            _check(
                result.get("decision") in (None, "decline", "cancel"),
                "model-tool-approval-refused",
                403,
            )
        else:
            _check(
                saved.get("can_interrupt") is True, "model-native-operation-not-active"
            )

    def _native_action(self, credential, ref, kind, body, check_deadline):
        _check(
            type(body) is dict and len(canonical(body)) <= 32768,
            "model-native-action-fields",
            400,
        )
        body = deepcopy(body)
        key = body.get("key")
        identifier(key)
        principal = self.intake._principal(credential)
        request_hash = sha(canonical({"kind": kind, "body": body}))
        target = body.get("request_ref" if kind == "answer" else "action_ref")
        identifier(target)
        with self.intake._lock:
            state = self.intake._load(principal, ref)
            prior = state.get("model_operations", {}).get("native_actions", {}).get(key)
            if prior is not None:
                _check(
                    prior["request_sha256"] == request_hash,
                    "idempotency-payload-differs",
                )
                return deepcopy(prior)
        self._owner(principal, ref)

        def record(state):
            actions = self._row(state).setdefault("native_actions", {})
            prior = actions.get(key)
            if prior is not None:
                _check(
                    prior["request_sha256"] == request_hash,
                    "idempotency-payload-differs",
                )
                return {"new": False, "observation": deepcopy(prior)}
            _check(len(actions) < 512, "model-native-action-bound-exceeded")
            actions[key] = {
                "kind": "ProjectNativeActionObservation.v1",
                "project_ref": ref,
                "key": key,
                "operation": kind,
                "target_ref": target,
                "request_sha256": request_hash,
                "status": "intent-recorded",
                "provider_invoked": False,
                "project_input_version": state["input_version"],
                "project_brief_sha256": state["briefs"][-1]["sha256"],
                "native_index_sha256": body.get("index_sha256")
                if type(body.get("index_sha256")) is str
                and re.fullmatch("[0-9a-f]{64}", body["index_sha256"])
                else None,
                "native_input_version": body.get("input_version")
                if type(body.get("input_version")) is str
                and re.fullmatch("[0-9a-f]{64}", body["input_version"])
                else None,
                "native_revision": body.get("revision")
                if type(body.get("revision")) is int
                and 0 <= body["revision"] <= 2**63 - 1
                else None,
                "recorded_at": self.clock(),
            }
            return {"new": True, "observation": deepcopy(actions[key])}

        saved = self._transaction(principal, ref, "model-native-intent", record)
        if not saved["new"]:
            return saved["observation"]
        invoked = False

        def update(status, **values):
            def change(state):
                action = self._row(state)["native_actions"][key]
                _check(
                    action["request_sha256"] == request_hash,
                    "model-native-intent-differs",
                )
                _check(
                    action["status"] == "intent-recorded", "model-native-intent-settled"
                )
                if values.get("provider_invoked") is True:
                    _check(
                        not any(
                            other["key"] != key
                            and other["target_ref"] == target
                            and other["operation"] == kind
                            and other.get("native_index_sha256") == body["index_sha256"]
                            and other.get("native_input_version")
                            == body["input_version"]
                            and other.get("provider_invoked") is True
                            for other in self._row(state)["native_actions"].values()
                        ),
                        "model-native-target-already-observed",
                    )
                action.update(status=status, **values)
                return deepcopy(action)

            return self._transaction(principal, ref, "model-native-observation", change)

        def pre_admission():
            if check_deadline is not None:
                check_deadline()
            self._guard(ref, offer)
            current = self._job(self.intake._principal(credential), ref, job["key"])
            remaining = current["deadline_at"] - self.clock()
            _check(
                current["status"] == "running" and remaining > 0,
                "model-native-action-expired",
            )
            return min(30, remaining)

        try:
            _, job, offer, provider = self._active(credential, ref)
            _check(
                callable(getattr(provider, kind, None)),
                "model-native-action-unavailable",
            )
            pre_admission()
            self._validate_native_target(ref, kind, body, provider)
            pre_admission()
            # From this durable marker onward the mutation may have been invoked.
            # A later API/schema/source refusal is conservatively unknown.
            update("intent-recorded", provider_invoked=True)
            invoked = True
            result = getattr(provider, kind)(body, pre_admission=pre_admission)
            _check(
                type(result) is dict and len(canonical(result)) <= 32768,
                "model-native-result-invalid",
            )
            return update(
                "result-observed",
                result_sha256=sha(canonical(result)),
                finished_at=self.clock(),
            )
        except BaseException as error:
            try:
                update(
                    "execution-unknown" if invoked else "known-unsent",
                    failure=(type(error).__name__ + ": " + str(error))
                    .encode("utf8")[:128]
                    .decode("utf8", errors="ignore"),
                    finished_at=self.clock(),
                )
            except BaseException:
                pass  # Unobserved persistence stays held; no guessed unsent result.
            raise

    def answer(self, credential, project_ref, body, *, check_deadline=None):
        return self._native_action(
            credential, project_ref, "answer", body, check_deadline
        )

    def interrupt(self, credential, project_ref, body, *, check_deadline=None):
        return self._native_action(
            credential, project_ref, "interrupt", body, check_deadline
        )

    def execute(self, credential, project_ref, body, *, check_deadline=None):
        _check(
            type(body) is dict
            and set(body) == BODY_FIELDS
            and len(canonical(body)) <= 8192,
            "model-action-fields-invalid",
            400,
        )
        identifier(body["key"])
        _check(
            type(body["revision"]) is int
            and type(body["input_version"]) is int
            and type(body["brief_sha256"]) is str
            and type(body["offer_ref"]) is str
            and type(body["offer_sha256"]) is str,
            "model-action-binding-invalid",
            400,
        )
        _check(body["confirmed"] is True, "model-explicit-confirmation-required", 400)
        principal = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(principal, project_ref)
            offer = deepcopy(
                state.get("model_operations", {})
                .get("offers", {})
                .get(body["offer_ref"])
            )
        _check(
            offer is not None and body["offer_sha256"] == offer["offer_sha256"],
            "model-offer-differs",
        )
        _check(
            body["input_version"] == offer["context"]["input_version"]
            and body["brief_sha256"] == offer["context"]["brief_sha256"],
            "model-action-input-differs",
        )
        key = body["key"]

        def reserve(state, request_hash, actor):
            registration = self._guard(project_ref, offer)
            _check(self.factory is not None, "model-provider-unconnected")
            row = self._row(state)
            _check(
                not any(j["status"] not in TERMINAL for j in row["jobs"].values()),
                "model-operation-active",
            )
            _check(len(row["jobs"]) < 256, "model-job-bound-exceeded")
            _check(
                not any(
                    j["status"] in {"execution-unknown", "failed-or-unknown"}
                    and not retired(j)
                    for j in row["jobs"].values()
                ),
                "model-unknown-requires-reconciliation",
            )
            permit = registration["permit"]
            budgets = offer["context"]["settings"]["budgets"]
            _check(
                type(budgets["model_calls"]) is int
                and type(budgets["seconds"]) is int
                and budgets["model_calls"] > 0
                and budgets["seconds"] > 0,
                "model-zero-budget",
            )
            version = str(state["input_version"])
            scope = deepcopy(
                row["scopes"].get(
                    version,
                    {
                        "budget_sha256": offer["context"]["budget_sha256"],
                        "calls": 0,
                        "started_at": self.clock(),
                        "deadline_at": self.clock() + budgets["seconds"],
                        "permits": {},
                    },
                )
            )
            _check(
                scope["budget_sha256"] == offer["context"]["budget_sha256"],
                "model-budget-version-differs",
            )
            pin = offer["permit_sha256"]
            lane = scope["permits"].setdefault(
                pin,
                {
                    "calls": 0,
                    "deadline_at": self.clock() + permit["max_seconds"],
                },
            )
            deadline = min(
                scope["deadline_at"], lane["deadline_at"], registration["expires"]
            )
            _check(
                self.clock() < deadline
                and lane["calls"] < permit["max_calls"]
                and scope["calls"] < budgets["model_calls"],
                "model-budget-exhausted",
            )
            started_at = self.clock()
            reserve_resource(
                self.intake,
                state,
                actor,
                lane="model",
                kind="model-operation",
                key=key,
                request_sha256=request_hash,
                seconds=deadline - started_at,
            )
            scope["calls"] += 1
            lane["calls"] += 1
            row["scopes"][version] = scope
            row["calls_reserved"] += 1
            row["jobs"][key] = dict(
                **{
                    k: deepcopy(offer["context"][k])
                    for k in (
                        "operation",
                        "input_version",
                        "brief_sha256",
                        "budget_sha256",
                        "prompt_sha256",
                        "source_sha256",
                    )
                },
                key=key,
                project_ref=project_ref,
                project_id=offer["context"]["project_id"],
                permit_sha256=offer["permit_sha256"],
                offer_ref=offer["offer_ref"],
                offer_sha256=offer["offer_sha256"],
                request_sha256=request_hash,
                status="intent-recorded",
                started_at=started_at,
                deadline_at=deadline,
                reservation_seconds=deadline - started_at,
                provider_reserved=False,
                calls_reserved=1,
                usage=None,
                cost=None,
                owner=self._tokens[project_ref],
            )
            job = row["jobs"][key]
            if offer["context"]["operation"] == READ_OPERATION:
                job.update(
                    work_ref=offer["context"]["work_ref"],
                    snapshot_sha256=offer["context"]["snapshot_sha256"],
                )
            job["runtime_binding"] = self._runtime_identity(principal, project_ref, job)
            job["runtime_dir"] = self._runtime_relative(job["runtime_binding"])

        def queued(state, _, _principal):
            job = self._row(state)["jobs"][key]
            job["status"] = "queued"
            return {
                "model_status": "queued",
                "offer_ref": offer["offer_ref"],
                "calls_reserved": 1,
            }

        receipt = self.intake._perform(
            principal,
            project_ref,
            "model-operation",
            deepcopy(body),
            queued,
            reserve=reserve,
            check_deadline=check_deadline,
        )
        if not receipt["replayed"] and receipt["status"] == "saved":
            worker = threading.Thread(
                target=self._run, args=(principal, project_ref, key, offer), daemon=True
            )
            self._workers[(project_ref, key)] = worker
            worker.start()
        return {
            **receipt,
            "job": self._public_job(
                self._job(principal, project_ref, key), project_ref
            ),
        }

    def _job(self, principal, ref, key):
        with self.intake._lock:
            return deepcopy(self._row(self.intake._load(principal, ref))["jobs"][key])

    def retire(self, credential, project_ref, body, *, check_deadline=None):
        return retire(
            self, credential, project_ref, body, check_deadline=check_deadline
        )

    def _admit(self, principal, ref, key, offer, event):
        _check(
            type(event) is dict
            and event.get("phase")
            in {"reserve", "spawn", "lifecycle", "attach", "action"},
            "model-admission-event-invalid",
        )
        _check(
            event.get("unit_key") == "project-unit-" + sha(key.encode())
            and event.get("prompt_sha256") == offer["context"]["prompt_sha256"]
            and event.get("source_sha256") == offer["context"]["source_sha256"]
            and event.get("permit_sha256") == offer["permit_sha256"],
            "model-admission-binding-differs",
        )
        self._guard(ref, offer)

        def admit(state):
            resource_view(self.intake, state, principal)
            job = self._row(state)["jobs"][key]
            _check(not retired(job), "model-retired-no-resend")
            _check(
                job["status"] == "running" and self.clock() < job["deadline_at"],
                "model-admission-expired",
            )
            if event["phase"] == "reserve":
                _check(
                    job["provider_reserved"] is False, "model-provider-reserve-repeated"
                )
                job["provider_reserved"] = True
            else:
                _check(
                    job["provider_reserved"] is True,
                    "model-provider-reservation-missing",
                )
            if event["phase"] == "action":
                action = event.get("event", {}).get("action", {})
                method, payload = action.get("method"), action.get("payload", {})
                _check(
                    method
                    in {
                        "turn/start",
                        "turn/interrupt",
                        "item/tool/requestUserInput",
                        "item/commandExecution/requestApproval",
                        "item/fileChange/requestApproval",
                    },
                    "model-native-action-refused",
                )
                if method == "turn/start":
                    _check(
                        payload.get("model") == offer["context"]["model"]
                        and payload.get("input")
                        == [
                            {
                                "type": "text",
                                "text": offer["prompt"],
                                "text_elements": [],
                            }
                        ],
                        "model-native-prompt-differs",
                    )
                elif method.endswith("requestApproval"):
                    _check(
                        payload.get("decision") in {"decline", "cancel"},
                        "model-tool-approval-refused",
                    )
            return {"key": key, "phase": event["phase"], "admitted": True}

        self._transaction(principal, ref, "model-admission", admit)
        return True

    def _run(self, principal, ref, key, offer):
        provider: StageUnitProvider | None = None
        try:
            self._guard(ref, offer)

            def running(state):
                job = self._row(state)["jobs"][key]
                _check(
                    job["status"] == "queued" and self.clock() < job["deadline_at"],
                    "model-start-expired",
                )
                job["status"] = "running"
                return {"key": key, "status": "running"}

            self._transaction(principal, ref, "model-operation-running", running)
            context = deepcopy(offer["context"])
            folder = self._runtime_folder(
                principal, ref, self._job(principal, ref, key), create=True
            )
            self._guard(ref, offer)
            provider = self.factory(
                context=context,
                admit=lambda event: self._admit(principal, ref, key, offer, event),
                output_root=folder / "n",
            )
            _check(
                callable(getattr(provider, "run", None))
                and callable(getattr(provider, "verify_receipt", None)),
                "model-provider-invalid",
            )
            self._providers[(ref, key)] = provider
            job = self._job(principal, ref, key)
            deadline = self.monotonic() + max(0, job["deadline_at"] - self.clock())
            receipt = provider.run(
                "project-unit-" + sha(key.encode()), offer["prompt"], deadline
            )
            evidence = _write_new(
                folder / "provider-receipt.json", canonical(receipt) + b"\n"
            )
            self._guard(ref, offer)
            _check(self.clock() < job["deadline_at"], "model-completion-expired")
            verified = provider.verify_receipt(
                receipt,
                expected_prompt_sha256=offer["context"]["prompt_sha256"],
                expected_source_sha256=offer["context"]["source_sha256"],
            )
            _check(
                type(verified) is dict
                and verified.get("status") == "completed"
                and verified.get("prompt_sha256") == offer["context"]["prompt_sha256"]
                and verified.get("source_sha256") == offer["context"]["source_sha256"]
                and type(verified.get("final_text")) is str,
                "model-verified-output-invalid",
            )
            text = verified["final_text"]
            raw = text.encode("utf8")
            _check(0 < len(raw) <= 1048576, "model-output-bound-exceeded")
            output = _write_new(folder / "output.txt", raw)
            result = {
                "raw_output": output,
                "verified_receipt": evidence,
                "output": text if len(raw) <= 65536 else None,
                "output_preview": _preview(text)["text"],
                "usage": deepcopy(verified.get("usage")),
                "cost": deepcopy(verified.get("cost")),
                "status": "content-review-pending",
                "finished_at": self.clock(),
            }
            if offer["context"]["operation"] == READ_OPERATION:
                try:
                    draft = validate_reading_draft(
                        raw, offer["context"]["saved_reading"]
                    )
                    artifact = _write_new(
                        folder / "reading-draft.json", canonical(draft) + b"\n"
                    )
                    result["reading_draft"] = {
                        **artifact,
                        "snapshot_sha256": draft["snapshot_sha256"],
                        "work_id": draft["work_id"],
                        "version_id": draft["version_id"],
                        "evidence_count": len(draft["draft"]["evidence"]),
                        "evidence_validation": draft["evidence_validation"],
                        "researcher_acceptance": False,
                        "core_claims_created": False,
                    }
                except (ValueError, KeyError, TypeError, UnicodeError) as error:
                    result.update(status="validation-failed", failure=str(error)[:512])
            if offer["context"]["operation"] == "plan-search":
                try:
                    request = decode(raw, "model plan proposal")
                    _check(
                        type(request) is dict
                        and set(request) == {"proposal", "query_bindings"}
                        and request["proposal"]["topic"]
                        == offer["context"]["brief"]["original_description"],
                        "model-plan-proposal-invalid",
                    )
                    binding = self.intake.brief_binding(ref, require_confirmed=True)
                    # Confirmed plans remain inside the project's existing core
                    # intake namespace; only native runtime evidence is moved.
                    plan_relative = (
                        "content-plan-"
                        + sha(
                            canonical(self._job(principal, ref, key)["runtime_binding"])
                        )[:RUNTIME_DIGEST_HEX]
                    )
                    plan = self.intake._path(ref, plan_relative)
                    compile_confirmed(
                        binding["brief_path"],
                        request,
                        plan,
                        as_of=offer["context"]["as_of"],
                        actor=principal,
                    )
                    validate_bound_plan(plan, binding["brief_path"])
                    result.update(
                        status="plan-validated-not-executed",
                        plan_relative=plan_relative,
                        plan_manifest_sha256=sha(
                            (plan / "plan_manifest.json").read_bytes()
                        ),
                    )
                except (ValueError, OSError, KeyError, TypeError) as error:
                    result.update(status="validation-failed", failure=str(error)[:512])

            def finish(state):
                self._guard(ref, offer)
                current = self._row(state)["jobs"][key]
                _check(
                    current["status"] == "running"
                    and current["provider_reserved"] is True,
                    "model-finish-state-differs",
                )
                current.update(result)
                if result["status"] == "plan-validated-not-executed":
                    state["plan"] = dict(
                        path=result["plan_relative"],
                        brief_sha256=offer["context"]["brief_sha256"],
                        manifest_sha256=result["plan_manifest_sha256"],
                        execution_status="not-executed",
                    )
                return {"key": key, **result}

            self._transaction(principal, ref, "model-operation-finished", finish)
        except BaseException as error:
            failure = type(error).__name__ + ": " + str(error)[:512]
            try:

                def failed(state):
                    job = self._row(state)["jobs"][key]
                    if job["status"] not in TERMINAL:
                        job.update(
                            status="failed-or-unknown",
                            failure=failure,
                            finished_at=self.clock(),
                        )
                    return {
                        "key": key,
                        "status": job["status"],
                        "failure": job.get("failure"),
                    }

                self._transaction(principal, ref, "model-operation-failed", failed)
            except BaseException:
                # Durable queued/running intent remains unknown on owner recovery.
                pass
        finally:
            self._providers.pop((ref, key), None)
            if provider is not None and callable(getattr(provider, "close", None)):
                try:
                    provider.close()
                except BaseException as error:
                    close_failure = type(error).__name__ + ": " + str(error)[:512]
                    try:

                        def failed_close(state):
                            self._row(state)["jobs"][key]["close_failure"] = (
                                close_failure
                            )
                            return {"key": key, "close_failure": close_failure}

                        self._transaction(
                            principal, ref, "model-provider-close-failed", failed_close
                        )
                    except BaseException:
                        # The unit producer's raw close evidence remains separately retained.
                        pass

    def close(self):
        self._closed = True
        for provider in list(self._providers.values()):
            if callable(getattr(provider, "close", None)):
                provider.close()
        for worker in list(self._workers.values()):
            worker.join(timeout=1)
        _check(
            not any(worker.is_alive() for worker in self._workers.values()),
            "model-worker-shutdown-unobserved",
        )
        for lock in self._owners.values():
            lock.close()
        self._owners.clear()

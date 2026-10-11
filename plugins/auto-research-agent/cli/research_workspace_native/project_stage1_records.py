"""Trusted saved-observation registries to canonical Stage1 records.

The injected guard must own the current run's saved-mutation frontier. This
module has no downloader, model callback, browser path intake or acceptance.
"""

from copy import deepcopy
import os

from stage1_deliverable.common import private_output, safe_path, sha
from stage1_deliverable.records import (
    CLASSIFICATION,
    FINDINGS,
    _keys,
    _text,
    validate_records,
)
from stage1_ledger.journal import canonical, decode

from .project_stage1 import _basis
from .project_stage1_delivery import (
    MAX_RECORD_BYTES,
    ProjectStage1DeliveryService,
    _raw,
    _records_match,
    _screening_library,
)
from .project_stage1_sources import describe_source, source_record
from .session_api import _check

MAX_ENTRIES = 1024
MAX_RECORDS = 256
READING_ACTION_FIELDS = {
    "key",
    "revision",
    "input_version",
    "brief_sha256",
    "ledger_state_sha256",
    "output_ref",
    "draft_sha256",
    "offer_ref",
    "offer_sha256",
    "review",
    "confirmed",
}
SOURCE_READING_ACTION_FIELDS = (
    READING_ACTION_FIELDS - {"output_ref", "draft_sha256"}
) | {"work_ref", "source_snapshot_sha256"}


class ProjectStage1RecordsService:
    """Server-owned local enrichment; registrations are append-only receipts."""

    def __init__(self, delivery, *, materials_root, mutation_guard):
        _check(
            isinstance(delivery, ProjectStage1DeliveryService),
            "stage1-delivery-service-required",
        )
        _check(callable(mutation_guard), "saved-mutation-owner-guard-required")
        self.delivery, self.intake = delivery, delivery.intake
        self.root = private_output(materials_root)
        _check(self.root.is_dir(), "saved-materials-root-required")
        self.guard = mutation_guard

    def _basis(self, context):
        _, _, binding, run, ledger, *_ = context
        return dict(
            binding=_basis(binding),
            run_ref=run["run_ref"],
            manifest_sha256=run["manifest_sha256"],
            materials_root=str(self.root),
            core_run_id=ledger.manifest["research_run"]["run_id"],
        )

    def _context(self, project_ref, expected_state, *, require_checkpoint=False):
        context = (
            self.delivery._context(project_ref)
            if require_checkpoint
            else self.delivery._saved_context(project_ref)
        )
        _check(
            context[5]["state_sha256"] == expected_state, "stage1-ledger-state-stale"
        )
        return context

    def _mutation_check(
        self, project_ref, expected_state, guard_check, *, require_checkpoint=False
    ):
        _check(
            guard_check is None or callable(guard_check),
            "saved-mutation-check-required",
        )

        def check():
            if guard_check is not None:
                guard_check()
            return self._context(
                project_ref, expected_state, require_checkpoint=require_checkpoint
            )

        return check

    def _register(
        self, project_ref, context, kind, payload, check_current, action_body=None
    ):
        principal, state, binding, *_ = context
        entry = dict(basis=self._basis(context), payload=payload)
        _check(
            len(canonical(entry)) <= 256 * 1024, "stage1-saved-registration-too-large"
        )
        digest = sha(canonical(entry))
        entry.update(ref=kind + "-" + digest, sha256=digest)
        body = dict(
            key=entry["ref"],
            revision=state["revision"],
            input_version=binding["input_version"],
            brief_sha256=binding["brief_sha256"],
            entry_sha256=digest,
        )
        if action_body is not None:
            _check(
                kind == "stage1-reading-registry"
                and type(action_body) is dict
                and "entry_sha256" not in action_body,
                "saved-reading-action-body-invalid",
                400,
            )
            fields = (
                SOURCE_READING_ACTION_FIELDS
                if "work_ref" in action_body
                else READING_ACTION_FIELDS
            )
            _keys(action_body, fields, "human saved reading action")
            _keys(
                action_body["review"],
                ("classification", "findings", "roles"),
                "human reading review",
            )
            _check(
                action_body["confirmed"] is True
                and action_body["input_version"] == binding["input_version"]
                and action_body["brief_sha256"] == binding["brief_sha256"]
                and action_body["ledger_state_sha256"] == context[5]["state_sha256"]
                and (
                    "work_ref" not in action_body
                    or action_body["work_ref"] == payload["work_id"]
                )
                and all(
                    action_body["review"][field] == payload[field]
                    for field in ("classification", "findings", "roles")
                ),
                "saved-reading-action-binding-differs",
            )
            body = deepcopy(action_body)

        def reserve(current, _, __):
            check_current()
            _check(
                entry["ref"] not in current.get("stage1_saved_registries", {}),
                "saved-reading-entry-already-registered",
            )

        def save(current, _, __):
            entries = current.setdefault("stage1_saved_registries", {})
            _check(len(entries) < MAX_ENTRIES, "stage1-saved-registry-bound-exceeded")
            entries[entry["ref"]] = entry
            return {"registry_entry": entry}

        result = self.intake._perform(
            principal,
            project_ref,
            kind,
            body,
            save,
            check_deadline=check_current,
            **({"reserve": reserve} if action_body is not None else {}),
        )
        _check(result["status"] == "saved", "stage1-saved-registration-unobserved")
        return deepcopy(result["registry_entry"])

    def _entries(self, context):
        principal, state, *_ = context
        entries = state.get("stage1_saved_registries", {})
        history = self.intake.db.execute(
            "SELECT kind,payload FROM intake_events WHERE project=? AND kind IN ('stage1-source-registry-saved','stage1-reading-registry-saved') ORDER BY id",
            (state["project_ref"],),
        ).fetchall()
        observed = []
        for kind, payload in history:
            receipt = decode(payload.encode(), "saved registry receipt")
            action = self.intake.db.execute(
                "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                (principal, state["project_ref"], receipt["key"]),
            ).fetchone()
            _check(
                action is not None
                and decode(action["receipt"].encode(), "registry action") == receipt
                and receipt["status"] == "saved"
                and kind == receipt["kind"] + "-saved"
                and action["request_hash"]
                == receipt["request_sha256"]
                == sha(
                    canonical({"kind": receipt["kind"], "body": receipt["request"]})
                ),
                "stage1-saved-registry-action-differs",
            )
            entry = receipt["registry_entry"]
            request = receipt["request"]
            if "entry_sha256" not in request:
                _keys(
                    request,
                    (
                        SOURCE_READING_ACTION_FIELDS
                        if "work_ref" in request
                        else READING_ACTION_FIELDS
                    )
                    - {"revision"},
                    "human saved reading action",
                )
                _keys(
                    request["review"],
                    ("classification", "findings", "roles"),
                    "human reading review",
                )
                _check(
                    receipt["kind"] == "stage1-reading-registry"
                    and request["confirmed"] is True
                    and request["input_version"]
                    == entry["basis"]["binding"]["input_version"]
                    and request["brief_sha256"]
                    == entry["basis"]["binding"]["brief_sha256"]
                    and (
                        "work_ref" not in request
                        or request["work_ref"] == entry["payload"]["work_id"]
                    )
                    and all(
                        request["review"][field] == entry["payload"][field]
                        for field in ("classification", "findings", "roles")
                    ),
                    "stage1-saved-registry-receipt-differs",
                )
            _check(
                entry["ref"] == receipt["kind"] + "-" + entry["sha256"]
                and (
                    "entry_sha256" not in request
                    or request["entry_sha256"] == entry["sha256"]
                ),
                "stage1-saved-registry-receipt-differs",
            )
            observed.append(entry)
        _check(
            len(observed) == len(entries) <= MAX_ENTRIES
            and len({row["ref"] for row in observed}) == len(observed),
            "stage1-saved-registry-history-ambiguous",
        )
        for key, entry in entries.items():
            _check(
                entry["ref"] == key
                and entry["sha256"]
                == sha(
                    canonical({"basis": entry["basis"], "payload": entry["payload"]})
                )
                and observed.count(entry) == 1,
                "stage1-saved-registry-receipt-differs",
            )
        _check(
            {row["ref"] for row in observed} == set(entries),
            "stage1-saved-registry-history-incomplete",
        )
        return [entry for entry in observed if entry["basis"] == self._basis(context)]

    def register_source(
        self,
        project_ref,
        *,
        source_id,
        result_path,
        expected_result_sha256,
        access_note,
        expected_ledger_state_sha256,
        check_current=None,
    ):
        _text(access_note)
        _check(
            check_current is None or callable(check_current),
            "saved-source-extra-check-required",
        )
        extra_check = check_current
        if extra_check is not None:
            extra_check()
        with self.intake._lock:
            context = self._context(project_ref, expected_ledger_state_sha256)
            with self.guard(*context[3:6]) as guard_check:
                original_check = self._mutation_check(
                    project_ref, expected_ledger_state_sha256, guard_check
                )

                def check_current():
                    if extra_check is not None:
                        extra_check()
                    fresh = original_check()
                    if extra_check is not None:
                        extra_check()
                    return fresh

                context = check_current()
                payload = describe_source(
                    context[4],
                    self.root,
                    source_id,
                    result_path,
                    expected_result_sha256,
                    access_note,
                )
                previous = [
                    entry["payload"]
                    for entry in self._entries(context)
                    if entry["ref"].startswith("stage1-source-registry-")
                    and entry["payload"]["source_id"] == source_id
                ]
                _check(
                    not previous or previous == [payload],
                    "saved-source-registration-differs",
                )
                return self._register(
                    project_ref,
                    context,
                    "stage1-source-registry",
                    payload,
                    check_current,
                )

    def _reading(self, context, value, source_entries):
        core = value.get("schema_version") == "1.1.0"
        _check(
            "schema_version" not in value or core, "saved-reading-version-unsupported"
        )
        _keys(
            value,
            (
                "work_id",
                "version_id",
                "candidate_event_id",
                "decision_event_id",
                "review_event_id",
                "source_ids",
                "classification",
                "findings",
                "roles",
                "claims",
                *(("schema_version",) if core else ()),
            ),
            "saved reading",
        )
        ledger = context[4]
        candidates = ledger.candidates()
        candidate = candidates.get(value["work_id"])
        _check(candidate is not None, "saved-reading-work-unavailable")
        events = {row["payload"]["event_id"]: row["payload"] for row in ledger.events()}
        decisions = [
            row
            for row in events.values()
            if row["kind"] == "DecisionEvent" and row["subject_id"] == value["work_id"]
        ]
        _check(bool(decisions), "saved-reading-screening-required")
        review = ledger.coverage_state().evidence.current().get(value["work_id"])
        selected = (
            review["version_id"]
            if review
            else candidate["discoveries"][-1]["version_id"]
        )
        _check(
            value["version_id"] == selected
            and value["candidate_event_id"] == candidate["event_id"]
            and value["decision_event_id"] == decisions[-1]["event_id"]
            and value["review_event_id"] == (review["event_id"] if review else None),
            "saved-reading-current-review-differs",
        )
        sources = {
            entry["source_id"]: entry
            for entry in source_entries
            if entry["work_id"] == value["work_id"] and entry["version_id"] == selected
        }
        _check(
            type(value["source_ids"]) is list
            and len(set(value["source_ids"])) == len(value["source_ids"])
            and set(value["source_ids"]) == set(sources)
            and bool(sources),
            "saved-reading-source-set-differs",
        )
        for field, keys in (("classification", CLASSIFICATION), ("findings", FINDINGS)):
            _keys(value[field], keys, "saved " + field)
            for text in value[field].values():
                _text(text)
        _check(
            type(value["claims"]) is list and type(value["roles"]) is list,
            "saved-reading-list-required",
        )
        _check(
            len(value["claims"]) <= MAX_RECORDS
            and len(value["source_ids"]) <= MAX_RECORDS,
            "saved-reading-record-bound-exceeded",
        )
        seen = set()
        for claim in value["claims"]:
            _keys(
                claim,
                ("claim_id", "source_id", "text_sha256", "start", "end", "quote"),
                "saved exact claim span",
            )
            event = events.get(claim["claim_id"])
            if core:
                self._core_span(
                    ledger, value, selected, sources, events, seen, claim, event
                )
                continue
            _check(
                event is not None
                and event["kind"] == "ClaimEvidence"
                and event["work_id"] == value["work_id"]
                and event["version_id"] == selected
                and event["relation"]
                in {"supports", "partial", "contradicts", "unverified"}
                and event["evidence_level"] in {"metadata", "abstract", "full-text"},
                "saved-reading-claim-enum-or-binding-differs",
            )
            _check(
                claim["claim_id"] not in seen and claim["source_id"] in sources,
                "saved-reading-claim-duplicate-or-source-differs",
            )
            seen.add(claim["claim_id"])
            finish = events[sources[claim["source_id"]]["finish_event_id"]]
            _check(
                finish["outcome"] == "available"
                and finish["text_ref"] == event["source_ref"],
                "saved-reading-claim-source-differs",
            )
            raw = ledger.read_ref(event["source_ref"])
            text = raw.decode("utf-8")
            _check(
                claim["text_sha256"] == sha(raw)
                and type(claim["start"]) is int
                and type(claim["end"]) is int
                and 0 <= claim["start"] < claim["end"] <= len(text)
                and text[claim["start"] : claim["end"]]
                == claim["quote"]
                == event["locator"]["quote"],
                "saved-reading-claim-span-differs",
            )
        required = {
            row["event_id"]
            for row in events.values()
            if row["kind"] == "ClaimEvidence"
            and row["work_id"] == value["work_id"]
            and row["version_id"] == selected
        }
        _check(seen == required, "saved-reading-claim-history-incomplete")
        if review:
            required = set(review["cluster_claims"].values()) | {
                claim
                for claim in review["identity_claims"].values()
                if claim is not None
            }
            _check(required <= seen, "saved-reading-review-claims-incomplete")
        roles = set()
        for role in value["roles"]:
            _keys(role, ("role", "reason", "claim_ids"), "saved literature role")
            _check(
                role["role"] in {"classic", "topic-core", "closest-work", "comparator"}
                and role["role"] not in roles
                and type(role["claim_ids"]) is list
                and bool(role["claim_ids"])
                and set(role["claim_ids"]) <= seen,
                "saved-reading-role-evidence-differs",
            )
            _text(role["reason"])
            roles.add(role["role"])
        return candidate, selected

    @staticmethod
    def _core_span(ledger, value, selected, sources, events, seen, claim, event):
        from stage1_deliverable.core_records import RELATIONS, LEVELS

        _check(
            event is not None
            and event["kind"] == "ClaimEvidence"
            and event["work_id"] == value["work_id"]
            and event["version_id"] == selected
            and event["relation"] in RELATIONS
            and event["evidence_level"] in LEVELS,
            "saved-reading-claim-enum-or-binding-differs",
        )
        _check(
            claim["claim_id"] not in seen,
            "saved-reading-claim-duplicate-or-source-differs",
        )
        seen.add(claim["claim_id"])
        source_id = claim["source_id"]
        if source_id is None:
            _check(
                event["source_ref"]["producer"] not in sources,
                "saved-reading-claim-source-differs",
            )
        else:
            _check(
                source_id in sources and event["source_ref"]["producer"] == source_id,
                "saved-reading-claim-source-differs",
            )
            finish = events[sources[source_id]["finish_event_id"]]
            _check(
                event["source_ref"] in (finish["raw_ref"], finish["text_ref"]),
                "saved-reading-claim-source-differs",
            )
        raw = ledger.read_ref(event["source_ref"])
        _check(claim["text_sha256"] == sha(raw), "saved-reading-claim-span-differs")
        if event["locator"] is None:
            _check(
                all(claim[k] is None for k in ("start", "end", "quote")),
                "saved-reading-null-locator-differs",
            )
        else:
            text = raw.decode("utf8")
            _check(
                type(claim["start"]) is int
                and type(claim["end"]) is int
                and 0 <= claim["start"] < claim["end"] <= len(text)
                and text[claim["start"] : claim["end"]]
                == claim["quote"]
                == event["locator"]["quote"],
                "saved-reading-claim-span-differs",
            )

    def _saved_claim_locators(self, context, work_id, version_id):
        """Recover exact manual spans only from matching durable Core receipts."""
        actor, state, binding, _, ledger, *_ = context
        manual = {
            row["payload"]["event_id"]: row["payload"]
            for row in ledger.events()
            if row["payload"]["kind"] == "ClaimEvidence"
            and (row["payload"]["work_id"], row["payload"]["version_id"])
            == (work_id, version_id)
            and row["payload"]["verifier"]["method"] == "explicit-saved-source-review"
        }
        rows = self.intake.db.execute(
            "SELECT key,request_hash,receipt FROM intake_actions WHERE principal=? AND project=?",
            (actor, state["project_ref"]),
        ).fetchall()
        claim_events = [
            decode(row[0].encode(), "manual claim durable event")
            for row in self.intake.db.execute(
                "SELECT payload FROM intake_events WHERE project=? AND kind IN ('stage1-claim-intent','stage1-claim-saved')",
                (state["project_ref"],),
            ).fetchall()
        ]
        locators = {}
        for row in rows:
            receipt = decode(row["receipt"].encode(), "manual claim receipt")
            if receipt["kind"] != "stage1-claim" or receipt["status"] != "saved":
                continue
            event_id = receipt.get("claim_event_id")
            if event_id not in manual:
                continue
            event = manual[event_id]
            signature, request = receipt.get("saved_source_claim"), receipt["request"]
            _keys(
                signature,
                (
                    "work_id",
                    "version_id",
                    "input_version",
                    "brief_sha256",
                    "source_id",
                    "text_sha256",
                    "start",
                    "end",
                    "quote",
                    "review",
                ),
                "saved manual claim signature",
            )
            _keys(
                signature["review"],
                (
                    "claim_text",
                    "relation",
                    "evidence_level",
                    "section",
                ),
                "saved manual claim review",
            )
            intent = {
                field: receipt[field]
                for field in (
                    "project_ref",
                    "key",
                    "kind",
                    "request_sha256",
                    "request",
                    "recorded_at",
                )
            } | {"status": "intent-recorded"}
            _check(
                receipt["key"] == row["key"]
                and receipt["project_ref"] == state["project_ref"]
                and row["request_hash"]
                == receipt["request_sha256"]
                == sha(canonical(dict(kind="stage1-claim", body=request)))
                and claim_events.count(receipt) == 1
                and claim_events.count(intent) == 1
                and event_id not in locators
                and signature["work_id"] == request["work_ref"] == work_id
                and signature["version_id"] == version_id
                and signature["input_version"]
                == request["input_version"]
                == binding["input_version"]
                and signature["brief_sha256"]
                == request["brief_sha256"]
                == binding["brief_sha256"]
                and signature["source_id"] == event["source_ref"]["producer"]
                and signature["review"] == request["review"]
                and signature["quote"] == request["quote"] == event["locator"]["quote"]
                and signature["start"] == request["start_byte"]
                and signature["end"] == request["end_byte"]
                and event["verifier"]
                == dict(
                    actor=actor,
                    actor_type="human",
                    method="explicit-saved-source-review",
                )
                and all(
                    signature["review"][field] == event[field]
                    for field in ("claim_text", "relation", "evidence_level")
                )
                and signature["review"]["section"] == event["locator"]["section"],
                "saved-reading-manual-claim-receipt-differs",
            )
            raw = ledger.read_ref(event["source_ref"])
            start, end = signature["start"], signature["end"]
            _check(
                type(start) is int
                and type(end) is int
                and 0 <= start < end <= len(raw)
                and sha(raw) == signature["text_sha256"]
                and raw[start:end] == signature["quote"].encode("utf8"),
                "saved-reading-manual-claim-span-differs",
            )
            locator = dict(
                claim_id=event_id,
                source_id=signature["source_id"],
                text_sha256=signature["text_sha256"],
                start=len(raw[:start].decode("utf8", errors="strict")),
                end=len(raw[:end].decode("utf8", errors="strict")),
                quote=signature["quote"],
            )
            _check(
                locator == receipt.get("reading_locator"),
                "saved-reading-manual-claim-locator-differs",
            )
            locators[event_id] = locator
        _check(
            set(locators) == set(manual), "saved-reading-manual-claim-receipt-required"
        )
        return locators

    def derive_reading_payload(
        self,
        project_ref,
        work_id,
        *,
        classification,
        findings,
        roles,
        expected_ledger_state_sha256,
    ):
        """Read exact current spans for an explicit human review; never save it."""
        with self.intake._lock:
            context = self._context(project_ref, expected_ledger_state_sha256)
            ledger = context[4]
            evidence = ledger.coverage_state().evidence
            candidate = ledger.candidates().get(work_id)
            _check(
                candidate is not None and work_id in evidence.decisions,
                "saved-reading-work-unavailable",
            )
            review = evidence.current().get(work_id)
            selected = (
                review["version_id"]
                if review
                else candidate["discoveries"][-1]["version_id"]
            )
            source_entries = [
                entry["payload"]
                for entry in self._entries(context)
                if entry["ref"].startswith("stage1-source-registry-")
            ]
            source_ids = [
                s["source_id"]
                for s in source_entries
                if s["work_id"] == work_id and s["version_id"] == selected
            ]
            manual_locators = self._saved_claim_locators(context, work_id, selected)
            spans = []
            for row in ledger.events():
                event = row["payload"]
                if event["kind"] != "ClaimEvidence" or (
                    event["work_id"],
                    event["version_id"],
                ) != (work_id, selected):
                    continue
                if event["event_id"] in manual_locators:
                    spans.append(deepcopy(manual_locators[event["event_id"]]))
                    continue
                raw = ledger.read_ref(event["source_ref"])
                quote = event["locator"]["quote"] if event["locator"] else None
                start = None
                if quote is not None:
                    text = raw.decode("utf8")
                    start = text.find(quote)
                    _check(
                        start >= 0 and text.find(quote, start + 1) < 0,
                        "saved-reading-claim-quote-ambiguous",
                    )
                spans.append(
                    dict(
                        claim_id=event["event_id"],
                        source_id=event["source_ref"]["producer"]
                        if event["source_ref"]["producer"] in source_ids
                        else None,
                        text_sha256=sha(raw),
                        start=start,
                        end=start + len(quote) if quote is not None else None,
                        quote=quote,
                    )
                )
            payload = dict(
                schema_version="1.1.0",
                work_id=work_id,
                version_id=selected,
                candidate_event_id=candidate["event_id"],
                decision_event_id=evidence.decisions[work_id]["event_id"],
                review_event_id=review["event_id"] if review else None,
                source_ids=source_ids,
                classification=deepcopy(classification),
                findings=deepcopy(findings),
                roles=deepcopy(roles),
                claims=spans,
            )
            self._reading(context, payload, source_entries)
            return payload

    def register_reading(
        self,
        project_ref,
        *,
        reading,
        expected_ledger_state_sha256,
        action_body=None,
        check_current=None,
    ):
        reading = deepcopy(reading)
        with self.intake._lock:
            context = self._context(project_ref, expected_ledger_state_sha256)
            with self.guard(*context[3:6]) as guard_check:
                original_check = self._mutation_check(
                    project_ref, expected_ledger_state_sha256, guard_check
                )
                extra_check = check_current

                def check_current():
                    if extra_check is not None:
                        extra_check()
                    fresh = original_check()
                    if extra_check is not None:
                        extra_check()
                    return fresh

                context = check_current()
                sources = [
                    entry["payload"]
                    for entry in self._entries(context)
                    if entry["ref"].startswith("stage1-source-registry-")
                ]
                for entry in sources:
                    source_record(context[4], self.root, entry)
                self._reading(context, reading, sources)
                return self._register(
                    project_ref,
                    context,
                    "stage1-reading-registry",
                    reading,
                    check_current,
                    action_body,
                )

    def _records(self, context, entries):
        ledger = context[4]
        sources = [
            entry["payload"]
            for entry in entries
            if entry["ref"].startswith("stage1-source-registry-")
        ]
        readings = [
            entry["payload"]
            for entry in entries
            if entry["ref"].startswith("stage1-reading-registry-")
        ]
        events = {row["payload"]["event_id"]: row["payload"] for row in ledger.events()}
        journal = {row["payload"]["event_id"]: row for row in ledger.events()}
        core = any(row.get("schema_version") == "1.1.0" for row in readings)
        candidates = ledger.candidates()
        decisions = ledger.coverage_state().evidence.decisions
        matches_by_work = {
            work: [
                reading
                for reading in readings
                if reading["work_id"] == work
                and reading["candidate_event_id"] == candidate["event_id"]
                and decisions.get(work) is not None
                and reading["decision_event_id"] == decisions[work]["event_id"]
            ]
            for work, candidate in candidates.items()
        }
        discovery_records = any(not rows for rows in matches_by_work.values())
        core = core or discovery_records
        papers, claims, source_rows = [], [], []
        _check(
            len(ledger.candidates()) <= MAX_RECORDS and len(sources) <= MAX_RECORDS,
            "stage1-saved-record-bound-exceeded",
        )
        reviews = ledger.coverage_state().evidence.current()
        for work, candidate in candidates.items():
            matches = matches_by_work[work]
            if not matches:
                version = candidate["discoveries"][-1]["version_id"]
                _check(
                    work not in reviews
                    and not any(
                        row["kind"] in {"SourceReadStarted", "ClaimEvidence"}
                        and row["work_id"] == work
                        and row["version_id"] == version
                        for row in events.values()
                    ),
                    "saved-reading-current-record-required",
                )
                metadata = candidate["discoveries"][-1]["record"]
                papers.append(
                    dict(
                        work_id=work,
                        version_id=version,
                        title=metadata["title"],
                        authors=metadata["authors"],
                        year=metadata["year"],
                        venue=metadata.get("venue") or "Unknown",
                        doi=metadata.get("doi"),
                        url=metadata.get("url"),
                        evidence_level="metadata",
                        source_ids=[],
                        claim_ids=[],
                        roles=[],
                        reading_status="discovery-only",
                        classification={key: "Unknown" for key in CLASSIFICATION},
                        findings={key: "Unknown" for key in FINDINGS},
                    )
                )
                continue
            # SQLite event order selects the latest explicit saved annotation;
            # canonical state-key order never acts as reading revision order.
            reading = matches[-1]
            _, version = self._reading(context, reading, sources)
            discovery = next(
                row
                for row in reversed(candidate["discoveries"])
                if row["version_id"] == version
            )
            metadata = discovery["record"]
            levels, urls = [], []
            for source in sources:
                if source["source_id"] in reading["source_ids"]:
                    row, receipt = source_record(ledger, self.root, source)
                    source_rows.append(row)
                    levels.append(
                        receipt["evidence_level"]
                        if receipt["status"] == "available"
                        else "metadata"
                    )
                    urls.append(receipt["source_url"] or receipt["request"]["url"])
            for span in reading["claims"]:
                event = events[span["claim_id"]]
                claims.append(
                    dict(
                        claim_id=span["claim_id"],
                        work_id=work,
                        version_id=version,
                        text=event["claim_text"],
                        source_id=span["source_id"],
                        relation=event["relation"],
                        evidence_level=event["evidence_level"],
                        locator=f"characters {span['start']}:{span['end']}"
                        if event["locator"] is not None
                        else None,
                        start=span["start"],
                        end=span["end"],
                        quote=span["quote"],
                        **(
                            {"core_event": deepcopy(journal[span["claim_id"]])}
                            if core
                            else {}
                        ),
                    )
                )
            papers.append(
                dict(
                    work_id=work,
                    version_id=version,
                    title=metadata["title"],
                    authors=metadata["authors"],
                    year=metadata["year"],
                    venue=metadata.get("venue") or "Unknown",
                    doi=metadata.get("doi"),
                    url=metadata.get("url") or urls[0],
                    evidence_level=max(
                        levels, key=("metadata", "abstract", "full-text").index
                    ),
                    source_ids=reading["source_ids"],
                    classification=reading["classification"],
                    findings=reading["findings"],
                    roles=reading["roles"],
                    claim_ids=[span["claim_id"] for span in reading["claims"]],
                    **(
                        {"reading_status": "human-reviewed"}
                        if discovery_records
                        else {}
                    ),
                )
            )
        versions = {paper["work_id"]: paper["version_id"] for paper in papers}
        screening = []
        for decision in events.values():
            if decision["kind"] != "DecisionEvent":
                continue
            candidate = ledger.candidates()[decision["subject_id"]]
            discovery = candidate["discoveries"][0]
            started = events[discovery["query_id"]]
            screening.append(
                dict(
                    decision_id=decision["event_id"],
                    work_id=decision["subject_id"],
                    version_id=versions[decision["subject_id"]],
                    status=decision["new_decision"],
                    reason=decision["rationale"],
                    query=started["arguments"].get("query")
                    or canonical(started["arguments"]).decode(),
                    discovery_path=discovery["discovery_id"],
                    observed_at=decision["created_at"],
                )
            )
        coverage = context[5]["coverage"]
        stop = context[6]["stage_result"]["next_allowed_action"] == "stop-sufficient"
        needs = [
            dict(
                need_id=cluster["cluster_id"],
                description=cluster["question"],
                work_ids=coverage["clusters"][cluster["cluster_id"]]["work_ids"],
                recent_sweep=canonical(
                    {"complete": coverage["recent_complete"]}
                ).decode(),
                closest_work_check=canonical(
                    {"verified_work_ids": coverage["closest_verified_work_ids"]}
                ).decode(),
                unresolved=canonical(coverage["blockers"]).decode(),
                stop_decision="stop" if stop else "continue",
                reason="Core checkpoint "
                + context[6]["event_id"]
                + ": "
                + context[6]["stage_result"]["next_allowed_action"],
            )
            for cluster in ledger.coverage_state().plan["proposal"]["clusters"]
        ]
        records = dict(
            kind="Stage1ResearchRecords",
            schema_version="1.2.0"
            if discovery_records
            else "1.1.0"
            if core
            else "1.0.0",
            topic=ledger.manifest["research_run"]["objective"],
            as_of=context[6]["created_at"],
            papers=papers,
            sources=source_rows,
            claims=claims,
            screening=screening,
            coverage=needs,
        )
        library = _screening_library(context) if discovery_records else None
        if discovery_records:
            from stage1_deliverable.screening_records import artifacts

            records.update(
                screening_library=library,
                screening_artifacts=artifacts(library),
                screening_journal={
                    "path": "screening_events.jsonl",
                    "sha256": library["binding"]["journal_sha256"],
                },
            )
        if core:
            from stage1_deliverable.core_records import artifact_path

            history = [
                deepcopy(row)
                for row in journal.values()
                if row["payload"]["kind"] == "ClaimEvidence"
            ]
            refs = {
                canonical(row["payload"]["source_ref"]): row["payload"]["source_ref"]
                for row in history
            }
            records.update(
                core_claim_history=history,
                core_artifacts=[
                    dict(source_ref=deepcopy(ref), artifact_path=artifact_path(ref))
                    for ref in refs.values()
                ],
            )
        validate_records(records)
        _records_match(
            records,
            ledger,
            self.root,
            check_core_archives=False,
            screening_library=library,
        )
        return records

    def produce_records(
        self,
        project_ref,
        *,
        expected_ledger_state_sha256,
        expected_checkpoint_event_id,
        action_body=None,
        check_current=None,
    ):
        _check(
            check_current is None or callable(check_current),
            "saved-producer-extra-check-required",
        )
        extra_check = check_current
        if extra_check is not None:
            extra_check()
        with self.intake._lock:
            context = self._context(
                project_ref, expected_ledger_state_sha256, require_checkpoint=True
            )
            with self.guard(*context[3:6]) as guard_check:
                check_frontier = self._mutation_check(
                    project_ref,
                    expected_ledger_state_sha256,
                    guard_check,
                    require_checkpoint=True,
                )
                context = check_frontier()
                _check(
                    context[6]["event_id"] == expected_checkpoint_event_id,
                    "stage1-checkpoint-event-differs",
                )
                entries = self._entries(context)
                records = self._records(context, entries)
                ledger = context[4]
                raw = canonical(records) + b"\n"
                _check(len(raw) <= MAX_RECORD_BYTES, "stage1-saved-records-too-large")
                digest = sha(raw)
                principal, state, binding, *_ = context
                body = dict(
                    key="stage1-records-"
                    + sha(
                        canonical(
                            [
                                self._basis(context),
                                expected_ledger_state_sha256,
                                expected_checkpoint_event_id,
                                digest,
                            ]
                        )
                    ),
                    revision=state["revision"],
                    input_version=binding["input_version"],
                    brief_sha256=binding["brief_sha256"],
                    ledger_state_sha256=expected_ledger_state_sha256,
                    checkpoint_event_id=expected_checkpoint_event_id,
                    records_sha256=digest,
                )
                path = safe_path(self.root, body["key"] + ".json")
                if action_body is not None:
                    _keys(
                        action_body,
                        (
                            "key",
                            "revision",
                            "input_version",
                            "brief_sha256",
                            "ledger_state_sha256",
                            "checkpoint_event_id",
                            "confirmed",
                        ),
                        "human records preparation",
                    )
                    _check(
                        action_body["confirmed"] is True
                        and action_body["input_version"] == binding["input_version"]
                        and action_body["brief_sha256"] == binding["brief_sha256"]
                        and action_body["ledger_state_sha256"]
                        == expected_ledger_state_sha256
                        and action_body["checkpoint_event_id"]
                        == expected_checkpoint_event_id,
                        "saved-records-action-binding-differs",
                    )
                    body = deepcopy(action_body)
                write_error = []

                def check_current():
                    if extra_check is not None:
                        extra_check()
                    if write_error:
                        raise OSError(write_error[0])
                    current = check_frontier()
                    _check(
                        current[6]["event_id"] == expected_checkpoint_event_id,
                        "stage1-checkpoint-event-differs",
                    )
                    if extra_check is not None:
                        extra_check()

                def write(current, _, __):
                    temporary = path.with_suffix(".partial")
                    try:
                        check_current()
                        if records["schema_version"] in {"1.1.0", "1.2.0"}:
                            artifacts = records["core_artifacts"] + records.get(
                                "screening_artifacts", []
                            )
                            for artifact in artifacts:
                                target = safe_path(self.root, artifact["artifact_path"])
                                target.parent.mkdir(exist_ok=True)
                                observed = ledger.read_ref(artifact["source_ref"])
                                check_current()
                                if not target.exists():
                                    with target.open("xb") as stream:
                                        _check(
                                            stream.write(observed) == len(observed),
                                            "stage1-records-partial-write",
                                        )
                                        stream.flush()
                                        os.fsync(stream.fileno())
                                _raw(target, artifact["source_ref"]["sha256"])
                            if records["schema_version"] == "1.2.0":
                                journal = records["screening_journal"]
                                observed = _raw(
                                    ledger.root / "stage_events.jsonl",
                                    journal["sha256"],
                                )
                                target = safe_path(self.root, journal["path"])
                                check_current()
                                if not target.exists():
                                    with target.open("xb") as stream:
                                        _check(
                                            stream.write(observed) == len(observed),
                                            "stage1-records-partial-write",
                                        )
                                        stream.flush()
                                        os.fsync(stream.fileno())
                                _raw(target, journal["sha256"])
                            _records_match(
                                records,
                                ledger,
                                self.root,
                                screening_library=_screening_library(context, records),
                            )
                        with temporary.open("xb") as stream:
                            _check(
                                stream.write(raw) == len(raw),
                                "stage1-records-partial-write",
                            )
                            stream.flush()
                            os.fsync(stream.fileno())
                        _raw(temporary, digest)
                        check_current()
                        # Exclusive publication cannot overwrite another name.
                        os.link(temporary, path)
                        temporary.unlink()
                        check_current()
                    except (ValueError, OSError, KeyError, TypeError) as error:
                        # Return the attempted output to the shared store first;
                        # its post-work check records unknown with observation.
                        write_error.append(str(error)[:512])
                    return dict(
                        records_sha256=digest,
                        records_path=str(path),
                        partial_path=str(temporary),
                        write_error=write_error[0] if write_error else None,
                        registry_sha256=sha(canonical(entries)),
                    )

                result = self.intake._perform(
                    principal,
                    project_ref,
                    "stage1-produce-records",
                    body,
                    write,
                    check_deadline=check_current,
                )
                _check(
                    result["status"] == "saved", "stage1-records-producer-unobserved"
                )
                _raw(path, digest)
                # A distinct durable registration reuses its own content key.
                # A partial file/action never becomes an offer or acceptance.
                check_current()
                offer = self.delivery.register_records(
                    project_ref,
                    records_path=path,
                    expected_records_sha256=digest,
                    expected_ledger_state_sha256=expected_ledger_state_sha256,
                    check_deadline=check_current,
                )
                check_current()
                return (
                    dict(result, delivery_offer=offer)
                    if action_body is not None
                    else offer
                )

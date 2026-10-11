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
)
from .project_stage1_sources import describe_source, source_record
from .session_api import _check

MAX_ENTRIES = 1024
MAX_RECORDS = 256


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

    def _context(self, project_ref, expected_state):
        context = self.delivery._context(project_ref)
        _check(
            context[5]["state_sha256"] == expected_state, "stage1-ledger-state-stale"
        )
        return context

    def _register(self, project_ref, context, kind, payload):
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

        def save(current, _, __):
            entries = current.setdefault("stage1_saved_registries", {})
            _check(len(entries) < MAX_ENTRIES, "stage1-saved-registry-bound-exceeded")
            entries[entry["ref"]] = entry
            return {"registry_entry": entry}

        result = self.intake._perform(principal, project_ref, kind, body, save)
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
            _check(
                entry["ref"] == receipt["kind"] + "-" + entry["sha256"]
                and receipt["request"]["entry_sha256"] == entry["sha256"],
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
    ):
        _text(access_note)
        with self.intake._lock:
            context = self._context(project_ref, expected_ledger_state_sha256)
            with self.guard(*context[3:6]):
                context = self._context(project_ref, expected_ledger_state_sha256)
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
                    project_ref, context, "stage1-source-registry", payload
                )

    def _reading(self, context, value, source_entries):
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

    def register_reading(self, project_ref, *, reading, expected_ledger_state_sha256):
        reading = deepcopy(reading)
        with self.intake._lock:
            context = self._context(project_ref, expected_ledger_state_sha256)
            with self.guard(*context[3:6]):
                context = self._context(project_ref, expected_ledger_state_sha256)
                sources = [
                    entry["payload"]
                    for entry in self._entries(context)
                    if entry["ref"].startswith("stage1-source-registry-")
                ]
                for entry in sources:
                    source_record(context[4], self.root, entry)
                self._reading(context, reading, sources)
                return self._register(
                    project_ref, context, "stage1-reading-registry", reading
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
        papers, claims, source_rows = [], [], []
        _check(
            len(ledger.candidates()) <= MAX_RECORDS and len(sources) <= MAX_RECORDS,
            "stage1-saved-record-bound-exceeded",
        )
        for work, candidate in ledger.candidates().items():
            matches = [
                reading
                for reading in readings
                if reading["work_id"] == work
                and reading["candidate_event_id"] == candidate["event_id"]
                and reading["decision_event_id"]
                == ledger.coverage_state().evidence.decisions[work]["event_id"]
            ]
            _check(bool(matches), "saved-reading-current-record-required")
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
                        locator=f"characters {span['start']}:{span['end']}",
                        start=span["start"],
                        end=span["end"],
                        quote=span["quote"],
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
            schema_version="1.0.0",
            topic=ledger.manifest["research_run"]["objective"],
            as_of=context[6]["created_at"],
            papers=papers,
            sources=source_rows,
            claims=claims,
            screening=screening,
            coverage=needs,
        )
        validate_records(records)
        _records_match(records, ledger, self.root)
        return records

    def produce_records(
        self, project_ref, *, expected_ledger_state_sha256, expected_checkpoint_event_id
    ):
        with self.intake._lock:
            context = self._context(project_ref, expected_ledger_state_sha256)
            with self.guard(*context[3:6]):
                context = self._context(project_ref, expected_ledger_state_sha256)
                _check(
                    context[6]["event_id"] == expected_checkpoint_event_id,
                    "stage1-checkpoint-event-differs",
                )
                entries = self._entries(context)
                records = self._records(context, entries)
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
                write_error = []

                def check_current():
                    if write_error:
                        raise OSError(write_error[0])
                    current = self._context(project_ref, expected_ledger_state_sha256)
                    _check(
                        current[6]["event_id"] == expected_checkpoint_event_id,
                        "stage1-checkpoint-event-differs",
                    )

                def write(current, _, __):
                    temporary = safe_path(self.root, body["key"] + ".partial")
                    try:
                        with temporary.open("xb") as stream:
                            _check(
                                stream.write(raw) == len(raw),
                                "stage1-records-partial-write",
                            )
                            stream.flush()
                            os.fsync(stream.fileno())
                        _raw(temporary, digest)
                        # Exclusive publication cannot overwrite another name.
                        os.link(temporary, path)
                        temporary.unlink()
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
                return self.delivery.register_records(
                    project_ref,
                    records_path=path,
                    expected_records_sha256=digest,
                    expected_ledger_state_sha256=expected_ledger_state_sha256,
                )

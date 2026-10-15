"""Human review of exact saved text, independent of model-selected excerpts."""

from copy import deepcopy
import json

from stage1_deliverable.common import canonical, sha
from stage1_ledger.bindings import claim_binding
from stage1_ledger.contracts import check_payload
from stage1_ledger.semantics import claim_check
from stage1_ledger.sources import replay

from .project_intake_contract import _text
from .project_model_reading import saved_reading_snapshot
from .project_stage1_sources import source_record
from .session_api import _check

PAGE_BYTES = 8192
FIELDS = {
    "work_ref",
    "source_ref",
    "offer_sha256",
    "start_byte",
    "end_byte",
    "quote",
    "review",
}


class ProjectSavedClaimService:
    def __init__(self, stage1, records, models=None):
        _check(
            records.delivery.stage1 is stage1 and records.intake is stage1.intake,
            "saved-claim-composition-differs",
        )
        _check(
            models is None or models.intake is stage1.intake,
            "saved-claim-model-composition-differs",
        )
        self.stage1, self.records, self.models = stage1, records, models
        self.intake = stage1.intake

    def _idle(self, credential, ref):
        if self.models is not None:
            value = self.models.read(credential, ref)
            _check(
                not value["active_jobs"] and not value["blocking_unknown_count"],
                "saved-claim-model-cleanup-unobserved",
            )

    def _context(self, ref, work, deadline):
        snapshot = saved_reading_snapshot(
            self.records, ref, work, check_deadline=deadline, excerpt_bytes=0
        )
        context = self.records.delivery._saved_context(ref)
        snapshot["source_registry_entries"] = {
            row["payload"]["source_id"]: deepcopy(row["payload"])
            for row in self.records._entries(context)
            if row["ref"].startswith("stage1-source-registry-")
        }
        return snapshot

    @staticmethod
    def _offers(snapshot):
        bound = {
            k: snapshot[k]
            for k in (
                "project_ref",
                "project_id",
                "input_version",
                "brief_sha256",
                "basis",
                "ledger_state_sha256",
                "work_id",
                "version_id",
                "candidate_event_id",
                "decision_event_id",
            )
        }
        result = []
        for source in snapshot["sources"]:
            digest = sha(canonical(dict(bound, source=source)))
            result.append(
                dict(
                    source_ref=digest,
                    offer_sha256=digest,
                    source_id=source["source_id"],
                    text_sha256=source["text_sha256"],
                    text_bytes=source["text_bytes"],
                    scope=source["source_observation_scope"],
                )
            )
        return result

    def view(
        self, credential, ref, work, source_ref=None, offset=0, *, check_deadline=None
    ):
        actor = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(actor, ref)
            self._idle(credential, ref)
            snapshot = self._context(ref, work, check_deadline)
            offers = self._offers(snapshot)
            offer = (
                next((v for v in offers if v["source_ref"] == source_ref), None)
                if source_ref
                else offers[0]
            )
            _check(offer is not None, "saved-claim-source-unavailable", 404)
            source = next(
                v for v in snapshot["sources"] if v["source_id"] == offer["source_id"]
            )
            context = self.records.delivery._saved_context(ref)
            raw = context[4].read_ref(source["text_ref"])
            _check(sha(raw) == source["text_sha256"], "saved-claim-text-differs")
            _check(
                type(offset) is int and 0 <= offset < len(raw),
                "saved-claim-page-invalid",
                400,
            )
            raw[:offset].decode("utf8", errors="strict")
            text = raw[offset : offset + PAGE_BYTES].decode("utf8", errors="ignore")
            end = offset + len(text.encode("utf8"))
            if check_deadline is not None:
                check_deadline()
            return dict(
                project_ref=ref,
                revision=state["revision"],
                input_version=snapshot["input_version"],
                brief_sha256=snapshot["brief_sha256"],
                ledger_state_sha256=snapshot["ledger_state_sha256"],
                work_ref=work,
                version_id=snapshot["version_id"],
                sources=offers,
                selected_source=offer,
                page=dict(
                    start_byte=offset,
                    end_byte=end,
                    text=text,
                    next_byte=end if end < len(raw) else None,
                ),
                stage1_complete=False,
                scientific_acceptance=False,
                model_calls=0,
            )

    def _prepare(self, actor, ref, ledger, body, snapshot):
        offered = next(
            (
                v
                for v in self._offers(snapshot)
                if v["source_ref"] == body["source_ref"]
            ),
            None,
        )
        _check(
            offered is not None
            and offered["offer_sha256"] == body["offer_sha256"]
            and snapshot["ledger_state_sha256"] == body["ledger_state_sha256"],
            "saved-claim-offer-stale",
        )
        source = next(
            v for v in snapshot["sources"] if v["source_id"] == offered["source_id"]
        )
        source_record(
            ledger,
            self.records.root,
            snapshot["source_registry_entries"][source["source_id"]],
        )
        raw = ledger.read_ref(source["text_ref"])
        start, end, quote = body["start_byte"], body["end_byte"], _text(body["quote"])
        _check(
            type(start) is int and type(end) is int and 0 <= start < end <= len(raw),
            "saved-claim-span-invalid",
            400,
        )
        _check(
            sha(raw) == source["text_sha256"]
            and raw[start:end] == quote.encode("utf8"),
            "saved-claim-span-differs",
        )
        first, last = len(raw[:start].decode("utf8")), len(raw[:end].decode("utf8"))
        review = body["review"]
        _check(
            type(review) is dict
            and set(review) == {"claim_text", "relation", "evidence_level", "section"},
            "saved-claim-review-fields",
            400,
        )
        args = dict(
            work_id=snapshot["work_id"],
            version_id=snapshot["version_id"],
            claim_text=_text(review["claim_text"]),
            relation=review["relation"],
            evidence_level=review["evidence_level"],
            locator=dict(section=_text(review["section"]), quote=quote),
            source_ref=deepcopy(source["text_ref"]),
            verifier=dict(
                actor=actor, actor_type="human", method="explicit-saved-source-review"
            ),
        )
        payload = dict(kind="ClaimEvidence", **args)
        check_payload(
            dict(
                payload,
                schema_version="1.0.0",
                event_id="e000001",
                created_at=ledger.clock(),
            )
        )
        claim_check(payload, ledger.read_ref)
        sources = replay(ledger)
        imports = {
            r["payload"]["event_id"]: r["payload"]
            for r in ledger.events()
            if r["payload"]["kind"] == "SourceImportStarted"
        }
        claim_binding(
            payload, ledger.candidates(), imports | sources.starts, sources.finishes
        )
        signature = dict(
            work_id=snapshot["work_id"],
            version_id=snapshot["version_id"],
            input_version=snapshot["input_version"],
            brief_sha256=snapshot["brief_sha256"],
            source_id=source["source_id"],
            text_sha256=source["text_sha256"],
            start=start,
            end=end,
            quote=quote,
            review=review,
        )
        rows = self.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE principal=? AND project=?",
            (actor, ref),
        ).fetchall()
        _check(
            not any(
                (r := json.loads(row[0]))["kind"] == "stage1-claim"
                and r["status"] == "saved"
                and r.get("saved_source_claim") == signature
                for row in rows
            ),
            "saved-claim-already-recorded",
        )
        return (
            args,
            signature,
            dict(
                source_id=source["source_id"],
                text_sha256=source["text_sha256"],
                start=first,
                end=last,
                quote=quote,
            ),
        )

    def claim(self, credential, ref, body, *, check_deadline=None):
        prepared = []

        def preflight(state, run, ledger, report, actor):
            self._idle(credential, ref)
            snapshot = self._context(ref, body["work_ref"], check_deadline)
            self._prepare(actor, ref, ledger, body, snapshot)
            prepared.append(snapshot)

        def producer(state, run, ledger, request_hash, actor):
            self._idle(credential, ref)
            args, signature, locator = self._prepare(
                actor, ref, ledger, body, prepared[0]
            )
            if check_deadline is not None:
                check_deadline()
            event = ledger.claim(**args)
            _check(
                all(ledger.event(event).get(k) == v for k, v in args.items()),
                "saved-claim-core-result-differs",
            )
            return dict(
                claim_event_id=event,
                saved_source_claim=signature,
                reading_locator=dict(locator, claim_id=event),
                ledger_state_sha256=ledger.state_hash(),
                stage1_complete=False,
                scientific_acceptance=False,
                reading_registration_complete=False,
            )

        return self.stage1._mutate(
            credential,
            ref,
            body,
            "stage1-claim",
            producer,
            fields=FIELDS,
            preflight=preflight,
            check_deadline=check_deadline,
        )

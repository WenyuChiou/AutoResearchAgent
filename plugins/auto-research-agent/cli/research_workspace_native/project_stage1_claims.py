"""Explicit human claim review of a saved model draft; no provider execution."""

from copy import deepcopy
import json

from stage1_deliverable.common import canonical, private_output, sha
from stage1_ledger.bindings import claim_binding
from stage1_ledger.contracts import check_payload
from stage1_ledger.journal import decode
from stage1_ledger.semantics import claim_check
from stage1_ledger.sources import replay

from .project_model import ProjectModelService, _output_ref
from .project_model_reading import saved_reading_snapshot, validate_reading_draft
from .project_intake_contract import _text
from .session_api import _check, _hash

FIELDS = {
    "output_ref",
    "draft_sha256",
    "evidence_index",
    "offer_ref",
    "offer_sha256",
    "review",
}
STABLE = {
    "principal",
    "project_ref",
    "project_id",
    "input_version",
    "brief_sha256",
    "basis",
    "work_id",
    "version_id",
    "candidate_event_id",
    "decision_event_id",
    "discovery",
    "sources",
    "source_failures",
}


class ProjectStage1ClaimService:
    def __init__(self, stage1, models, records):
        _check(
            isinstance(models, ProjectModelService)
            and records is models.reading_records
            and records.delivery.stage1 is stage1
            and stage1.intake is models.intake is records.intake,
            "stage1-claim-composition-differs",
        )
        self.stage1, self.models, self.records = stage1, models, records
        self.intake = stage1.intake

    @staticmethod
    def _raw(path, artifact):
        _check(type(artifact) is dict, "stage1-claim-artifact-unavailable")
        with private_output(path).open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        _check(
            0 < len(raw) <= 1024 * 1024
            and len(raw) == artifact["bytes"]
            and sha(raw) == artifact["sha256"],
            "stage1-claim-artifact-differs",
        )
        return raw

    def _draft(self, actor, ref, state, output_ref, check_deadline, snapshot=None):
        _check(_hash(output_ref), "stage1-claim-output-ref-invalid", 400)
        jobs = state.get("model_operations", {}).get("jobs", {}).values()
        job = next((j for j in jobs if _output_ref(j) == output_ref), None)
        _check(
            job is not None
            and job["operation"] == "read-paper"
            and job["status"] == "content-review-pending",
            "stage1-claim-reading-draft-unavailable",
        )
        offer = state["model_operations"]["offers"].get(job["offer_ref"])
        _check(
            offer is not None
            and offer["offer_sha256"] == job["offer_sha256"]
            and sha(canonical(offer["context"])) == job["offer_sha256"],
            "stage1-claim-model-offer-differs",
        )
        context = offer["context"]
        original = context["saved_reading"]
        _check(
            context["source_sha256"] == job["source_sha256"]
            and context["prompt_sha256"] == job["prompt_sha256"]
            and sha(offer["prompt"].encode("utf8")) == job["prompt_sha256"]
            and sha(canonical(original)) == job["snapshot_sha256"]
            and job["input_version"] == state["input_version"]
            and job["brief_sha256"] == self.intake.binding(ref)["brief_sha256"],
            "stage1-claim-model-binding-differs",
        )
        folder = self.models._runtime_folder(actor, ref, job)
        raw = self._raw(folder / "output.txt", job["raw_output"])
        checked = validate_reading_draft(raw, original)
        artifact = job["reading_draft"]
        saved = self._raw(folder / "reading-draft.json", artifact)
        _check(
            decode(saved, "saved reading draft") == checked
            and artifact["snapshot_sha256"] == checked["snapshot_sha256"]
            and (artifact["work_id"], artifact["version_id"])
            == (checked["work_id"], checked["version_id"]),
            "stage1-claim-draft-binding-differs",
        )
        current = (
            snapshot
            if snapshot is not None
            else saved_reading_snapshot(
                self.records, ref, checked["work_id"], check_deadline=check_deadline
            )
        )
        _check(
            all(current[name] == original[name] for name in STABLE)
            and all(
                row in current["existing_claims"] for row in original["existing_claims"]
            ),
            "stage1-claim-saved-source-stale",
        )
        return artifact, checked, current

    def _view(self, actor, ref, state, output_ref, check_deadline=None, snapshot=None):
        artifact, checked, snapshot = self._draft(
            actor, ref, state, output_ref, check_deadline, snapshot
        )
        result = dict(
            project_ref=ref,
            revision=state["revision"],
            input_version=state["input_version"],
            brief_sha256=snapshot["brief_sha256"],
            ledger_state_sha256=snapshot["ledger_state_sha256"],
            output_ref=output_ref,
            draft_sha256=artifact["sha256"],
            work_id=checked["work_id"],
            version_id=checked["version_id"],
            draft=deepcopy(checked["draft"]),
            offers=[],
            stage1_complete=False,
            scientific_acceptance=False,
            model_calls=0,
            grants_external_permission=False,
        )
        for index, span in enumerate(checked["draft"]["evidence"]):
            bound = {
                key: result[key]
                for key in (
                    "project_ref",
                    "input_version",
                    "brief_sha256",
                    "ledger_state_sha256",
                    "output_ref",
                    "draft_sha256",
                    "work_id",
                    "version_id",
                )
            }
            digest = sha(canonical(dict(bound, evidence_index=index, evidence=span)))
            result["offers"].append(
                dict(
                    evidence_index=index,
                    offer_ref="claim-" + digest[:32],
                    offer_sha256=digest,
                    source_id=span["source_id"],
                    quote=span["quote"],
                    existing_claim_id=span["claim_id"],
                )
            )
        _check(len(canonical(result)) <= 256 * 1024, "stage1-claim-view-bound-exceeded")
        return result, snapshot

    def view(self, credential, ref, output_ref, *, check_deadline=None):
        actor = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(actor, ref)
            self._idle(credential, ref)
            return self._view(actor, ref, state, output_ref, check_deadline)[0]

    def _idle(self, credential, ref):
        model = self.models.read(credential, ref)
        _check(
            not model["active_jobs"] and not model["blocking_unknown_count"],
            "stage1-claim-model-cleanup-unobserved",
        )

    def _prepare(self, actor, ref, state, ledger, body, check_deadline, snapshot=None):
        view, snapshot = self._view(
            actor, ref, state, body["output_ref"], check_deadline, snapshot
        )
        index = body["evidence_index"]
        _check(
            type(index) is int and 0 <= index < len(view["offers"]),
            "stage1-claim-index-invalid",
            400,
        )
        offered = view["offers"][index]
        _check(
            body["draft_sha256"] == view["draft_sha256"]
            and body["offer_ref"] == offered["offer_ref"]
            and body["offer_sha256"] == offered["offer_sha256"]
            and body["ledger_state_sha256"] == view["ledger_state_sha256"],
            "stage1-claim-offer-differs",
        )
        rows = self.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE principal=? AND project=?",
            (actor, ref),
        ).fetchall()
        _check(
            not any(
                (row := json.loads(raw[0]))["kind"] == "stage1-claim"
                and row["status"] == "saved"
                and row["request"]["input_version"] == body["input_version"]
                and row["request"].get("output_ref") == body["output_ref"]
                and row["request"].get("evidence_index") == index
                for raw in rows
            ),
            "stage1-claim-evidence-already-reviewed",
        )
        review = body["review"]
        _check(
            type(review) is dict
            and set(review) == {"claim_text", "relation", "evidence_level", "section"},
            "stage1-claim-review-fields",
            400,
        )
        span = view["draft"]["evidence"][index]
        source = next(
            s for s in snapshot["sources"] if s["source_id"] == span["source_id"]
        )
        raw = ledger.read_ref(source["text_ref"])
        _check(
            sha(raw) == span["text_sha256"]
            and raw[span["start_byte"] : span["end_byte"]]
            == span["quote"].encode("utf8"),
            "stage1-claim-source-span-differs",
        )
        # Validate UTF8 boundaries now; registry positions are character offsets.
        start = len(raw[: span["start_byte"]].decode("utf8"))
        end = len(raw[: span["end_byte"]].decode("utf8"))
        args = dict(
            work_id=view["work_id"],
            version_id=view["version_id"],
            claim_text=_text(review["claim_text"]),
            relation=review["relation"],
            evidence_level=review["evidence_level"],
            locator=dict(section=_text(review["section"]), quote=span["quote"]),
            source_ref=deepcopy(source["text_ref"]),
            verifier=dict(
                actor=actor, actor_type="human", method="explicit-saved-draft-review"
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
        return (
            args,
            dict(
                source_id=span["source_id"],
                text_sha256=span["text_sha256"],
                start=start,
                end=end,
                quote=span["quote"],
            ),
            snapshot,
        )

    def claim(self, credential, ref, body, *, check_deadline=None):
        prepared = []

        def preflight(state, run, ledger, report, actor):
            self._idle(credential, ref)
            prepared.append(
                self._prepare(actor, ref, state, ledger, body, check_deadline)[2]
            )

        def producer(state, run, ledger, request_hash, actor):
            # The owned writer has now reserved its durable intent. Do not read
            # its frontier recursively; reuse the checked snapshot under the same
            # intake lock, and recheck the draft/files/Core semantics before append.
            self._idle(credential, ref)
            args, locator, _ = self._prepare(
                actor, ref, state, ledger, body, check_deadline, prepared[0]
            )
            if check_deadline is not None:
                check_deadline()
            event = ledger.claim(**args)
            _check(
                all(ledger.event(event).get(k) == v for k, v in args.items()),
                "stage1-claim-core-result-differs",
            )
            return dict(
                claim_event_id=event,
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

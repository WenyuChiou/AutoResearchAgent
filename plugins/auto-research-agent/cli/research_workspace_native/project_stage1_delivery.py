"""Bind saved reading records to the real canonical Stage1 package producer.

Only trusted server code registers physical inputs. The browser selects an opaque
offer for the current project, ledger and scope; it never supplies a file path.
This is saved-evidence delivery, not source acquisition or scientific acceptance.
"""

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import os
import stat

from stage1_deliverable import package
from stage1_deliverable.common import inventory, reject_links, safe_path, sha
from stage1_deliverable.records import validate_records
from stage1_ledger.journal import canonical, decode

from .project_stage1 import _basis
from .session_api import _check, _hash

MAX_RECORD_BYTES = 16 * 1024 * 1024
MAX_OFFERS = 16


def _io_root(path):
    """Use Windows extended paths without changing portable artifact filenames.

    Natural ledger identities are full hashes. Their canonical file names can
    exceed MAX_PATH inside a versioned project. Preserve the producer and its
    historical package bytes; only the local filesystem handle is extended.
    The normal path has already passed the private-root/link guards.
    """
    path = Path(path).absolute()
    if os.name == "nt" and not str(path).startswith("\\\\?\\"):
        value = str(path)
        return Path(
            "\\\\?\\UNC\\" + value[2:]
            if value.startswith("\\\\")
            else "\\\\?\\" + value
        )
    return path


def _raw(path, expected):
    _check(_hash(expected), "stage1-records-hash-required", 400)
    path = Path(path).absolute()
    reject_links(path)
    _check(stat.S_ISREG(path.stat().st_mode), "stage1-records-not-regular")
    with path.open("rb") as stream:
        raw = stream.read(MAX_RECORD_BYTES + 1)
    _check(
        len(raw) <= MAX_RECORD_BYTES and sha(raw) == expected,
        "stage1-records-bytes-differ",
    )
    return raw


def _checkpoint(ledger, report):
    checkpoints = [
        row["payload"]
        for row in ledger.events()
        if row["payload"]["kind"] == "Checkpoint"
    ]
    _check(bool(checkpoints), "stage1-current-checkpoint-required")
    checkpoint = checkpoints[-1]
    _check(
        checkpoint["state_sha256"] == report["state_sha256"],
        "stage1-checkpoint-stale",
    )
    ref = checkpoint["stage_result"]["outputs"][-1]
    raw = ledger.read_ref(ref)
    handoff = decode(raw, "stage1 handoff")
    _check(
        handoff["kind"] == "Stage1Handoff"
        and handoff["source_state_sha256"] == report["state_sha256"]
        and handoff["source_run_id"] == ledger.manifest["research_run"]["run_id"],
        "stage1-handoff-binding-differs",
    )
    return checkpoint, ref, handoff


def _records_match(records, ledger, root):
    """Enrichment must refer to saved observations, never invent their history."""
    validate_records(records)
    _check(
        records["topic"] == ledger.manifest["research_run"]["objective"],
        "stage1-records-topic-differs",
    )
    papers = {row["work_id"]: row for row in records["papers"]}
    candidates = ledger.candidates()
    _check(set(papers) == set(candidates), "stage1-records-work-set-differs")
    events = {row["payload"]["event_id"]: row["payload"] for row in ledger.events()}
    reviews = {
        row["work_id"]: row
        for row in events.values()
        if row["kind"] == "CoverageWorkReview"
    }
    decisions = [row for row in events.values() if row["kind"] == "DecisionEvent"]
    recorded = {row["decision_id"]: row for row in records["screening"]}
    _check(
        set(recorded) == {row["event_id"] for row in decisions},
        "stage1-screening-history-differs",
    )
    for row in decisions:
        decision = recorded[row["event_id"]]
        _check(
            decision["work_id"] == row["subject_id"]
            and decision["status"] == row["new_decision"]
            and decision["reason"] == row["rationale"]
            and decision["observed_at"] == row["created_at"],
            "stage1-screening-decision-differs",
        )
    for work, paper in papers.items():
        candidate = candidates[work]
        review = reviews.get(work)
        latest_decision = next(
            row for row in reversed(decisions) if row["subject_id"] == work
        )
        if review is not None:
            _check(
                review["candidate_event_id"] == candidate["event_id"]
                and review["decision_event_id"] == latest_decision["event_id"],
                "stage1-records-review-stale",
            )
        selected = (
            review["version_id"]
            if review
            else candidate["discoveries"][-1]["version_id"]
        )
        discovery = next(
            row
            for row in reversed(candidate["discoveries"])
            if row["version_id"] == selected
        )
        record = discovery["record"]
        _check(
            paper["version_id"] == selected
            and paper["title"] == record["title"]
            and paper["authors"] == record["authors"]
            and paper["year"] == record["year"],
            "stage1-records-work-version-differs",
        )
    source_receipts = {}
    for source in records["sources"]:
        event = events.get(source["source_id"])
        _check(
            event is not None
            and event["kind"] == "SourceReadStarted"
            and event["work_id"] == source["work_id"]
            and event["version_id"] == source["version_id"],
            "stage1-source-attempt-binding-differs",
        )
        _check(
            any(
                row["kind"] == "SourceReadFinished"
                and row["attempt_id"] == event["event_id"]
                for row in events.values()
            ),
            "stage1-source-attempt-incomplete",
        )
        receipt_raw = _raw(
            safe_path(root, source["result_path"]), source["result_sha256"]
        )
        receipt = decode(receipt_raw, "source receipt")
        package.sources.validate_receipt_shape(receipt)
        finish = next(
            row
            for row in events.values()
            if row["kind"] == "SourceReadFinished"
            and row["attempt_id"] == event["event_id"]
        )
        _check(
            finish["outcome"] == _source_outcome(receipt)
            and event["source_uri"]
            == (receipt["request"]["url"] or receipt["source_url"])
            and finish["resolved_uri"] == receipt["final_url"]
            and finish["http_status"] == receipt["attempts"][-1]["http_status"]
            and datetime.fromisoformat(finish["observed_at"].replace("Z", "+00:00"))
            == datetime.fromisoformat(receipt["retrieved_at"].replace("Z", "+00:00")),
            "stage1-source-observation-differs",
        )
        if finish["text_ref"] is not None:
            _check(
                receipt["extracted_text_sha256"]
                == sha(ledger.read_ref(finish["text_ref"])),
                "stage1-source-text-bytes-differ",
            )
        if finish["raw_ref"] is not None:
            raw_hash = receipt["raw_sha256"] or receipt["attempts"][-1]["raw_sha256"]
            _check(
                (
                    raw_hash == sha(ledger.read_ref(finish["raw_ref"]))
                    if raw_hash is not None
                    else finish["outcome"] != "available"
                    and ledger.read_ref(finish["raw_ref"]) == receipt_raw
                ),
                "stage1-source-raw-bytes-differ",
            )
        source_receipts[source["source_id"]] = receipt
    selected_sources = {
        row["event_id"]
        for row in events.values()
        if row["kind"] == "SourceReadStarted"
        and row["work_id"] in papers
        and row["version_id"] == papers[row["work_id"]]["version_id"]
    }
    _check(set(source_receipts) == selected_sources, "stage1-source-history-differs")
    for claim in records["claims"]:
        event = events.get(claim["claim_id"])
        _check(
            event is not None
            and event["kind"] == "ClaimEvidence"
            and all(
                event[key] == claim[key]
                for key in ("work_id", "version_id", "relation", "evidence_level")
            )
            and event["claim_text"] == claim["text"]
            and event["locator"]["quote"] == claim["quote"],
            "stage1-claim-history-differs",
        )
        source = events[claim["source_id"]]
        finish = next(
            row
            for row in events.values()
            if row["kind"] == "SourceReadFinished"
            and row["attempt_id"] == source["event_id"]
        )
        _check(
            finish["outcome"] == "available"
            and finish["text_ref"] == event["source_ref"],
            "stage1-claim-source-bytes-differ",
        )
        text = ledger.read_ref(event["source_ref"]).decode("utf-8")
        _check(
            text[claim["start"] : claim["end"]] == claim["quote"],
            "stage1-claim-span-differs",
        )


def _source_outcome(receipt):
    """Explicit boundary between the fetcher's observations and ledger enums."""
    if receipt["status"] == "available":
        return "available"
    attempt = receipt["attempts"][-1]
    status, outcome = attempt["http_status"], attempt["outcome"]
    if status == 429:
        return "rate_limited"
    if status in (404, 410):
        return "not_found"
    if status is not None and status >= 400:
        return "http_error"
    if outcome in {"parse-error", "response-too-large"}:
        return "parse_error"
    if outcome in {"network-error", "timeout", "redirect-error", "unsafe-url"}:
        return "network_error" if status is None else "unavailable"
    return "unavailable"


def _public(offer):
    return {
        key: deepcopy(offer[key])
        for key in (
            "offer_ref",
            "offer_sha256",
            "binding",
            "run_ref",
            "ledger_state_sha256",
            "records_sha256",
            "checkpoint_event_id",
            "handoff_sha256",
            "eligible_for_stage2",
            "status",
        )
    }


class ProjectStage1DeliveryService:
    """Canonical producer over the existing intake and actual Stage1 journal."""

    def __init__(self, stage1):
        from .project_stage1 import ProjectStage1Service

        _check(isinstance(stage1, ProjectStage1Service), "stage1-service-required")
        self.stage1, self.intake = stage1, stage1.intake

    def _context(self, project_ref):
        row = self.intake.db.execute(
            "SELECT principal FROM intake_projects WHERE ref=?", (project_ref,)
        ).fetchone()
        _check(row is not None, "project-unavailable", 404)
        state = self.intake._load(row[0], project_ref)
        binding = self.intake.binding(project_ref)
        run, ledger, report = self.stage1._ledger(state, binding)
        checkpoint, ref, handoff = _checkpoint(ledger, report)
        return row[0], state, binding, run, ledger, report, checkpoint, ref, handoff

    def _check_offer(self, offer, context):
        _, _, binding, run, ledger, report, checkpoint, ref, handoff = context
        basis = {
            key: offer[key]
            for key in (
                "binding",
                "run_ref",
                "ledger_state_sha256",
                "records_sha256",
                "checkpoint_event_id",
                "handoff_sha256",
                "eligible_for_stage2",
            )
        }
        digest = sha(canonical(basis))
        _check(
            offer["offer_sha256"] == digest
            and offer["offer_ref"] == "stage1-delivery-" + digest[:32]
            and offer["eligible_for_stage2"] is handoff["eligible_for_stage2"],
            "stage1-delivery-offer-hash-differs",
        )
        _check(
            offer["binding"] == _basis(binding)
            and offer["run_ref"] == run["run_ref"]
            and offer["ledger_state_sha256"] == report["state_sha256"]
            and offer["checkpoint_event_id"] == checkpoint["event_id"]
            and offer["handoff_sha256"] == sha(ledger.read_ref(ref)),
            "stage1-delivery-offer-stale",
        )
        records = decode(
            _raw(offer["records_path"], offer["records_sha256"]), "stage1 records"
        )
        _records_match(records, ledger, Path(offer["records_path"]).parent)
        _check(
            not any(row["stop_decision"] == "stop" for row in records["coverage"])
            or checkpoint["stage_result"]["next_allowed_action"] == "stop-sufficient",
            "stage1-records-stop-gate-differs",
        )
        return records

    def register_records(
        self,
        project_ref,
        *,
        records_path,
        expected_records_sha256,
        expected_ledger_state_sha256,
    ):
        """Trusted local producer registration, without search/import authority."""
        with self.intake._lock:
            context = self._context(project_ref)
            principal, state, binding, run, ledger, report, checkpoint, ref, handoff = (
                context
            )
            _check(
                report["state_sha256"] == expected_ledger_state_sha256,
                "stage1-ledger-state-stale",
            )
            path = Path(records_path).absolute()
            records = decode(_raw(path, expected_records_sha256), "stage1 records")
            _records_match(records, ledger, path.parent)
            _check(
                not any(row["stop_decision"] == "stop" for row in records["coverage"])
                or checkpoint["stage_result"]["next_allowed_action"]
                == "stop-sufficient",
                "stage1-records-stop-gate-differs",
            )
            basis = dict(
                binding=_basis(binding),
                run_ref=run["run_ref"],
                ledger_state_sha256=report["state_sha256"],
                records_sha256=expected_records_sha256,
                checkpoint_event_id=checkpoint["event_id"],
                handoff_sha256=sha(ledger.read_ref(ref)),
                eligible_for_stage2=handoff["eligible_for_stage2"],
            )
            digest = sha(canonical(basis))
            offer = dict(
                basis,
                offer_ref="stage1-delivery-" + digest[:32],
                offer_sha256=digest,
                records_path=str(path),
                status="ready-for-saved-evidence-delivery",
            )
            body = dict(
                key="delivery-offer-" + digest,
                revision=state["revision"],
                input_version=binding["input_version"],
                brief_sha256=binding["brief_sha256"],
                offer_sha256=digest,
            )

            def work(current, _, __):
                saved = current.setdefault("stage1_delivery_offers", {})
                _check(len(saved) < MAX_OFFERS, "stage1-delivery-offer-bound-exceeded")
                saved[offer["offer_ref"]] = offer
                return {"offer": _public(offer)}

            result = self.intake._perform(
                principal, project_ref, "stage1-register-delivery", body, work
            )
            _check(
                result["status"] == "saved", "stage1-delivery-registration-unobserved"
            )
            return deepcopy(result["offer"])

    def _saved_artifact(self, principal, state, artifact, context):
        """Bind mutable display state to the durable successful action event.

        This is local record consistency, not multi-tenant authentication or a
        signature over a database writable by its owner.
        """
        project_ref = state["project_ref"]
        events = self.intake.db.execute(
            "SELECT payload FROM intake_events WHERE project=? AND kind='stage1-deliver-saved' ORDER BY id",
            (project_ref,),
        ).fetchall()
        receipts = [
            decode(row[0].encode("utf-8"), "delivery receipt") for row in events
        ]
        matched = [
            row
            for row in receipts
            if row.get("artifact_ref") == artifact["artifact_ref"]
        ]
        _check(len(matched) == 1, "stage1-delivery-saved-receipt-required")
        receipt = matched[0]
        action = self.intake.db.execute(
            "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
            (principal, project_ref, receipt["key"]),
        ).fetchone()
        _check(
            action is not None
            and decode(action["receipt"].encode("utf-8"), "delivery action") == receipt
            and receipt["status"] == "saved"
            and receipt["kind"] == "stage1-deliver"
            and action["request_hash"]
            == receipt["request_sha256"]
            == sha(canonical({"kind": receipt["kind"], "body": receipt["request"]})),
            "stage1-delivery-action-receipt-differs",
        )
        expected = {
            key: value
            for key, value in receipt.items()
            if key
            not in {
                "project_ref",
                "key",
                "kind",
                "request_sha256",
                "request",
                "status",
                "recorded_at",
                "delivery_status",
            }
        } | {"status": receipt["delivery_status"]}
        _check(artifact == expected, "stage1-delivery-artifact-receipt-differs")
        offer = state["stage1_delivery_offers"][artifact["offer_ref"]]
        self._check_offer(offer, context)
        _check(
            all(
                artifact[key] == offer[key]
                for key in (
                    "binding",
                    "run_ref",
                    "ledger_state_sha256",
                    "records_sha256",
                    "checkpoint_event_id",
                    "handoff_sha256",
                    "eligible_for_stage2",
                )
            )
            and receipt["request"]["offer_ref"] == offer["offer_ref"]
            and receipt["request"]["offer_sha256"] == offer["offer_sha256"]
            and artifact["source_mode"] == context[4].manifest["mode"]
            and artifact["artifact_ref"]
            == "stage1-canonical-" + receipt["request_sha256"][:32],
            "stage1-delivery-artifact-offer-differs",
        )
        relative = "s1d-" + receipt["request_sha256"][:24]
        stored = state["stage1_canonical_packages"][artifact["artifact_ref"]]
        _check(
            stored == dict(artifact, path=relative),
            "stage1-delivery-stored-artifact-differs",
        )
        return _io_root(self.intake._path(project_ref, relative))

    def read(self, credential, project_ref):
        principal = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(principal, project_ref)
            current = self.intake.read(credential, project_ref)
            offers = [
                _public(row) for row in state.get("stage1_delivery_offers", {}).values()
            ]
            ledger = self.stage1.read(credential, project_ref)
            for offer in offers:
                if (
                    offer["binding"]["input_version"] != current["input_version"]
                    or offer["binding"]["brief_sha256"] != current["brief_sha256"]
                    or not ledger["ledger"]
                    or offer["ledger_state_sha256"] != ledger["ledger"]["state_sha256"]
                    or not ledger["checkpoint"]
                    or not ledger["checkpoint"]["current"]
                    or offer["checkpoint_event_id"] != ledger["checkpoint"]["event_id"]
                ):
                    offer["status"] = "stale-input"
                else:
                    try:
                        self._check_offer(
                            state["stage1_delivery_offers"][offer["offer_ref"]],
                            self._context(project_ref),
                        )
                    except (ValueError, OSError, KeyError, TypeError):
                        offer["status"] = "source-binding-failed"
            saved = deepcopy(state.get("stage1_canonical_package"))
            if saved is not None:
                if not any(
                    row["offer_ref"] == saved["offer_ref"]
                    and row["status"] == "ready-for-saved-evidence-delivery"
                    for row in offers
                ):
                    saved["status"] = "stale-input"
                else:
                    try:
                        root = self._saved_artifact(
                            principal, state, saved, self._context(project_ref)
                        )
                        manifest = decode(
                            _raw(
                                root / "provenance_manifest.json",
                                saved["manifest_sha256"],
                            ),
                            "stage1 package manifest",
                        )
                        _check(
                            inventory(root) == manifest["files"]
                            and manifest["counts"] == saved["counts"],
                            "stage1-package-bytes-differ",
                        )
                    except (ValueError, OSError, KeyError, TypeError):
                        saved["status"] = "source-binding-failed"
            return dict(
                project_ref=project_ref,
                offers=offers,
                canonical_package=saved,
                stage1_complete=False,
                scientific_quality_scored=False,
                acquisition_connected=False,
                automatic_resend=False,
                passive_read="hashes-only-no-source-replay",
            )

    def deliver(self, credential, project_ref, body, *, check_deadline=None):
        def producer(state, _, __, request_hash, ___):
            context = self._context(project_ref)
            offer = state.get("stage1_delivery_offers", {}).get(body["offer_ref"])
            _check(
                offer is not None and offer["offer_sha256"] == body["offer_sha256"],
                "stage1-delivery-offer-unavailable",
            )
            self._check_offer(offer, context)
            _check(
                not any(
                    row["offer_ref"] == offer["offer_ref"]
                    for row in state.get("stage1_canonical_packages", {}).values()
                ),
                "stage1-delivery-already-produced",
            )
            relative = "s1d-" + request_hash[:24]
            output = self.stage1._output(project_ref, relative)
            _check(
                not output.exists(), "stage1-delivery-output-requires-reconciliation"
            )
            if check_deadline is not None:
                check_deadline()
            output = _io_root(output)
            result = package.build(
                offer["records_path"], output, offer["records_sha256"]
            )
            verified = package.validate(output, result["manifest_sha256"])
            _check(verified["status"] == "passed", "stage1-delivery-replay-failed")
            self._check_offer(offer, self._context(project_ref))
            digest = result["manifest_sha256"]
            artifact = dict(
                # Equal package bytes can occur in distinct current offers.
                # Attempts keep separate identities even when hashes agree.
                artifact_ref="stage1-canonical-" + request_hash[:32],
                offer_ref=offer["offer_ref"],
                artifact_kind="Stage1ResearchDeliverable",
                manifest_sha256=digest,
                records_sha256=offer["records_sha256"],
                binding=deepcopy(offer["binding"]),
                run_ref=offer["run_ref"],
                ledger_state_sha256=offer["ledger_state_sha256"],
                handoff_sha256=offer["handoff_sha256"],
                checkpoint_event_id=offer["checkpoint_event_id"],
                eligible_for_stage2=offer["eligible_for_stage2"],
                counts=deepcopy(verified["counts"]),
                source_mode=context[4].manifest["mode"],
                status="saved-evidence-validated",
                stage1_complete=False,
                scientific_quality_scored=False,
            )
            state.setdefault("stage1_canonical_packages", {})[
                artifact["artifact_ref"]
            ] = dict(artifact, path=relative)
            state["stage1_canonical_package"] = artifact
            return {
                key: value for key, value in artifact.items() if key != "status"
            } | {"delivery_status": artifact["status"]}

        _check(
            type(body) is dict and _hash(body.get("offer_sha256")),
            "stage1-delivery-offer-hash-required",
            400,
        )
        return self.stage1._mutate(
            credential,
            project_ref,
            body,
            "stage1-deliver",
            producer,
            fields={"offer_ref", "offer_sha256"},
            check_deadline=check_deadline,
        )

    def binding(self, project_ref):
        """Trusted current package/handoff lookup, without Stage2 authority."""
        with self.intake._lock:
            context = self._context(project_ref)
            principal, state, _, _, ledger, _, _, ref, _ = context
            artifact = state.get("stage1_canonical_package")
            _check(artifact is not None, "stage1-canonical-package-unavailable")
            root = self._saved_artifact(principal, state, artifact, context)
            package.validate(root, artifact["manifest_sha256"])
            return dict(
                **deepcopy(artifact),
                deliverable_dir=root,
                handoff_path=safe_path(ledger.root, ref["path"]),
                project_ref=project_ref,
            )

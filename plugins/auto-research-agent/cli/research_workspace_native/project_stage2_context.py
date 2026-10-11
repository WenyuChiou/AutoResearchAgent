"""Lossless upstream input review, separate from Stage 2 packet consumption.

The saved package remains authoritative. This descriptor does not convert Core
claims into citable evidence, activate a workflow, or grant execution permission.
"""

from copy import deepcopy

from stage1_deliverable.common import canonical, sha
from stage1_deliverable.records import validate_records
from research_workspace.json_bytes import decode_json

from .project_intake_contract import BOUND_FIELDS, MAX_ACTIONS, _fields, _text
from .session_api import _check, _hash


def verify_review_history(intake, principal, state):
    expected = []
    for row in intake.db.execute(
        "SELECT payload FROM intake_events WHERE project=? AND kind=? ORDER BY id",
        (state["project_ref"], "stage1-review-stage2-input-saved"),
    ):
        receipt = decode_json(row[0])
        request = receipt["request"]
        request_hash = sha(canonical({"kind": receipt["kind"], "body": request}))
        action = intake.db.execute(
            "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
            (principal, state["project_ref"], receipt["key"]),
        ).fetchone()
        _check(
            action is not None
            and action["request_hash"] == request_hash
            and decode_json(action["receipt"]) == receipt
            and receipt["status"] == "saved"
            and receipt["kind"] == "stage1-review-stage2-input"
            and receipt["project_ref"] == state["project_ref"]
            and receipt["request_sha256"] == request_hash
            and receipt["review_ref"] == "stage2-input-review-" + request_hash[:32]
            and receipt["execution_authorized"] is False
            and all(
                receipt[key] == request[key]
                for key in (
                    "artifact_ref",
                    "manifest_sha256",
                    "context_sha256",
                    "decision",
                    "user_input",
                )
            ),
            "stage2-input-review-history-differs",
        )
        expected.append(
            {
                key: deepcopy(receipt[key])
                for key in (
                    "review_ref",
                    "context_sha256",
                    "artifact_ref",
                    "manifest_sha256",
                    "decision",
                    "user_input",
                    "execution_authorized",
                )
            }
        )
        _check(len(expected) <= MAX_ACTIONS, "stage2-input-review-history-bound")
    _check(
        state.get("stage2_input_reviews", []) == expected,
        "stage2-input-review-history-differs",
    )


def input_context(source, state, index_sha256):
    manifest = decode_json(source["provenance_manifest.json"])
    records = validate_records(manifest["canonical_records"])
    artifact = state["stage1_canonical_package"]
    version = records["schema_version"]
    issues = []
    if not artifact["eligible_for_stage2"]:
        issues.append("stage1-handoff-not-eligible")
    if version in {"1.1.0", "1.2.0"}:
        issues.append("stage2-canonical-consumer-unconnected")
    works = []
    for paper in records["papers"]:
        decisions = [
            row for row in records["screening"] if row["work_id"] == paper["work_id"]
        ]
        reasons = []
        if not paper["source_ids"]:
            reasons.append("source-unavailable")
        if paper.get("reading_status") not in {None, "human-reviewed"}:
            reasons.append("reading-not-registered")
        claims = [
            row for row in records["claims"] if row["claim_id"] in paper["claim_ids"]
        ]
        if any(
            not row["source_id"] or not row["locator"] or not row["quote"]
            for row in claims
        ):
            reasons.append("claim-source-or-location-unavailable")
        if any(
            row["evidence_level"] not in {"metadata", "abstract", "full-text"}
            for row in claims
        ):
            reasons.append("claim-level-needs-versioned-consumer")
        works.append(
            {
                "work_id": paper["work_id"],
                "version_id": paper["version_id"],
                "title": paper["title"],
                "screening_status": decisions[-1]["status"]
                if decisions
                else "not-screened",
                "source_ids": deepcopy(paper["source_ids"]),
                "claim_ids": deepcopy(paper["claim_ids"]),
                "reading_status": paper.get("reading_status"),
                "limitations": reasons,
            }
        )
    # Hash every retained file without returning physical paths or raw archives.
    # The manifest/index bind the full screening/claim journal, including excluded
    # and unread candidates; only the rows above are a compact review summary.
    basis = {
        "schema": "ProjectStage2InputContext/1",
        "project_ref": state["project_ref"],
        "input_version": state["input_version"],
        "brief_sha256": state["briefs"][-1]["sha256"],
        "settings_sha256": sha(canonical(state["settings"])),
        "artifact_ref": artifact["artifact_ref"],
        "manifest_sha256": artifact["manifest_sha256"],
        "index_sha256": index_sha256,
        "records_sha256": artifact["records_sha256"],
        "handoff_sha256": artifact["handoff_sha256"],
        "checkpoint_event_id": artifact["checkpoint_event_id"],
        "ledger_state_sha256": artifact["ledger_state_sha256"],
        "retained_inventory_sha256": sha(canonical(manifest["files"])),
        "retained_file_count": len(manifest["files"]),
        "records_version": version,
        "eligible_for_stage2": artifact["eligible_for_stage2"],
        "consumer_status": "unconnected" if version != "1.0.0" else "existing-contract",
        "limitations": issues,
        "works": works,
        "execution_authorized": False,
        "stage2_complete": False,
    }
    result = dict(basis, context_sha256=sha(canonical(basis)))
    result["review"] = None
    if state.get("stage2_input_reviews"):
        saved = state["stage2_input_reviews"][-1]
        result["review"] = dict(
            deepcopy(saved), stale=saved["context_sha256"] != result["context_sha256"]
        )
    return result


class ProjectStage2InputReviewService:
    """Persist researcher intent against a current pure Atlas snapshot."""

    def __init__(self, atlas):
        self.atlas, self.intake = atlas, atlas.intake

    def review(self, credential, ref, body, *, check_deadline=None):
        _fields(
            body,
            BOUND_FIELDS
            | {
                "artifact_ref",
                "manifest_sha256",
                "context_sha256",
                "decision",
                "user_input",
                "confirmed",
            },
        )
        _check(
            body["confirmed"] is True
            and type(body["decision"]) is str
            and body["decision"] in {"request-stage2", "keep-stage1", "hold"}
            and _hash(body["manifest_sha256"])
            and _hash(body["context_sha256"]),
            "stage2-input-review-invalid",
            400,
        )
        _text(body["user_input"], 4096)
        principal = self.intake._principal(credential)

        def verify(state):
            view = self.atlas.read(
                credential,
                ref,
                input_version=state["input_version"],
                revision=state["revision"],
                artifact_ref=body["artifact_ref"],
                manifest_sha256=body["manifest_sha256"],
                check_deadline=check_deadline,
            )["stage2_input"]
            _check(
                view["context_sha256"] == body["context_sha256"],
                "stage2-input-context-differs",
            )
            return view

        def reserve(state, *_):
            verify(state)

        def work(state, request_hash, _):
            view = verify(state)
            record = {
                "review_ref": "stage2-input-review-" + request_hash[:32],
                "context_sha256": view["context_sha256"],
                "artifact_ref": view["artifact_ref"],
                "manifest_sha256": view["manifest_sha256"],
                "decision": body["decision"],
                "user_input": body["user_input"],
                "execution_authorized": False,
            }
            state.setdefault("stage2_input_reviews", []).append(record)
            return dict(record, stage2_status="not-started")

        return self.intake._perform(
            principal,
            ref,
            "stage1-review-stage2-input",
            deepcopy(body),
            work,
            reserve=reserve,
            check_deadline=check_deadline,
        )

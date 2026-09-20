"""Freeze known-paper inputs; do not perform or authorize Stage 2 research."""

import json

from .journal import LedgerError, canonical

CONTRACT = "https://github.com/WenyuChiou/research-hub/blob/bb00775822bf856333cba8388631f16be3831ea4/skills/literature-triage-matrix/SKILL.md"
DIMENSIONS = [
    "Citation",
    "Question",
    "Method",
    "Data / study area",
    "Main claim",
    "Evidence",
    "Limitation",
    "Relevance",
    "Use as",
]


def snapshots(manifest, state, events):
    base = dict(
        schema_version="1.0.0",
        source_run_id=manifest["research_run"]["run_id"],
        source_state_sha256=state,
    )
    candidates = {p["work_id"]: p for p in events if p["kind"] == "CandidateRevision"}
    return [
        dict(base, kind="CandidateSnapshot", rows=list(candidates.values())),
        dict(
            base,
            kind="ClaimSnapshot",
            rows=[p for p in events if p["kind"] == "ClaimEvidence"],
        ),
        dict(
            base,
            kind="DecisionSnapshot",
            rows=[p for p in events if p["kind"] == "DecisionEvent"],
        ),
    ]


def handoff(manifest, state, events, refs, gate, action):
    papers = []
    candidates, _, decisions = snapshots(manifest, state, events)
    latest = {p["subject_id"]: p for p in decisions["rows"]}
    reviews = {p["work_id"]: p for p in events if p["kind"] == "CoverageWorkReview"}
    for candidate in candidates["rows"]:
        work_id = candidate["work_id"]
        decision = latest.get(work_id)
        if not decision or decision["new_decision"] != "include":
            continue
        review = reviews.get(work_id)
        if review and (
            review["candidate_event_id"] != candidate["event_id"]
            or review["decision_event_id"] != decision["event_id"]
        ):
            review = None
        discovery = next(
            d
            for d in reversed(candidate["discoveries"])
            if not review or d["version_id"] == review["version_id"]
        )
        record = discovery["record"]
        identifier = next(
            (
                f"{key}:{record[key]}"
                for key in ("doi", "arxiv", "pmid")
                if record.get(key)
            ),
            None,
        )
        papers.append(
            dict(
                work_id=work_id,
                candidate_event_id=candidate["event_id"],
                decision_event_id=decision["event_id"],
                title=record["title"],
                identifier=identifier,
                listed_version_id=discovery["version_id"],
                reviewed_version_id=review["version_id"] if review else None,
                metadata_identity=candidate["identity_status"],
                identity_review=review["identity_status"] if review else "not-assessed",
                source_ref=discovery["source_ref"],
            )
        )
    # Quoted data stays one line per known paper; no comparison cells are invented.
    manual = "\n".join(
        "- "
        + json.dumps(" ".join(p["title"].split()), ensure_ascii=False)
        + " — "
        + (p["identifier"] or p["work_id"])
        for p in papers
    )
    return dict(
        kind="Stage1Handoff",
        schema_version="1.0.0",
        source_run_id=manifest["research_run"]["run_id"],
        source_state_sha256=state,
        source_mode=manifest["mode"],
        input_refs=refs,
        reuse_contract=CONTRACT,
        input_format="manual-paper-list",
        comparison_dimensions=DIMENSIONS,
        papers=papers,
        manual_paper_list=manual,
        stage1_gate=gate,
        eligible_for_stage2=action == "stop-sufficient",
        stage2=dict(status="not-started", execution_authorized=False),
    )


def save_outputs(ledger, report, gate, action):
    from .contracts import check

    events = [row["payload"] for row in ledger.events()]
    outputs = []
    for value in snapshots(ledger.manifest, report["state_sha256"], events):
        check(value, value["kind"])
        outputs.append(
            ledger._save(
                canonical(value),
                producer="stage1-checkpoint",
                artifact_type="checkpoint-output",
            )
        )
    value = handoff(
        ledger.manifest, report["state_sha256"], events, outputs.copy(), gate, action
    )
    check(value, "Stage1Handoff")
    outputs.append(
        ledger._save(
            canonical(value),
            producer="stage1-checkpoint",
            artifact_type="checkpoint-output",
        )
    )
    return outputs


def validate_outputs(manifest, state, events, result, read_ref):
    from .contracts import check

    refs = result["outputs"]
    if not refs and "checkpoint_output_contract" not in manifest:
        return  # Existing version-1 runs remain readable.
    if len(refs) != 4 or any(r["artifact_type"] != "checkpoint-output" for r in refs):
        raise LedgerError("handoff-output-set")
    expected = snapshots(manifest, state, events)
    expected.append(
        handoff(
            manifest,
            state,
            events,
            refs[:3],
            result["gate"],
            result["next_allowed_action"],
        )
    )
    for ref, value in zip(refs, expected):
        check(value, value["kind"])
        if read_ref(ref) != canonical(value):
            raise LedgerError("handoff-output-replay: " + ref["path"])

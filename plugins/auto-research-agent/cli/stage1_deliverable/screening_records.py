"""Output-only canonical 1.2: saved discovery is not reading evidence."""

import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from stage1_ledger.contracts import check, check_payload
from stage1_ledger.journal import canonical, decode

from .common import DeliverableError, read_json, safe_path, sha
from .records import CLASSIFICATION, FINDINGS, _keys, _text, timestamp

VERSION = "1.2.0"
FAILURES = {
    "unavailable",
    "not_found",
    "rate_limited",
    "http_error",
    "network_error",
    "parse_error",
    "interrupted",
}


def extended(records):
    return records.get("schema_version") == VERSION


def _require(condition, message):
    if not condition:
        raise DeliverableError("screening library: " + message)


@lru_cache(maxsize=1)
def _ref_validator():
    schema = read_json(
        Path(__file__).resolve().parents[2] / "schemas/stage-contracts.v1.schema.json"
    )
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _refs(value):
    if isinstance(value, dict):
        if value.get("kind") == "ArtifactRef":
            _keys(
                value,
                (
                    "kind",
                    "schema_version",
                    "artifact_id",
                    "artifact_type",
                    "path",
                    "sha256",
                    "producer",
                    "created_at",
                ),
                "screening ref",
            )
            _require(value["schema_version"] == "1.0.0", "ref version differs")
            for field in ("artifact_id", "artifact_type", "producer"):
                _text(value[field])
            _require(
                isinstance(value["sha256"], str)
                and re.fullmatch(r"[a-f0-9]{64}", value["sha256"]),
                "ref hash invalid",
            )
            # The shared Core schema validates safe relative paths and time.
            _ref_validator().validate(value)
            timestamp(value["created_at"])
            yield value
        else:
            for item in value.values():
                yield from _refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _refs(item)


def artifacts(library):
    """Archive every saved ref, including failed queries and old source versions."""
    refs = {canonical(ref): ref for ref in _refs(library)}
    return [
        {
            "source_ref": refs[key],
            "artifact_path": "screening_artifacts/" + refs[key]["sha256"] + ".bin",
        }
        for key in sorted(refs)
    ]


def _queries(queries):
    _require(type(queries) is list, "query history requires list")
    output = {}
    for row in queries:
        _keys(row, ("started", "result", "backend_attempts"), "query history")
        started, result = row["started"], row["result"]
        check_payload(started)
        _require(
            started["kind"] == "ActionStarted" and started["operation"] == "search",
            "query start differs",
        )
        key = started["event_id"]
        _require(key not in output, "duplicate query")
        if result is not None:
            check_payload(result)
            _require(
                result["kind"] == "QueryEvent" and result["query_id"] == key,
                "query result differs",
            )
        _require(type(row["backend_attempts"]) is list, "backend history requires list")
        ids = set()
        for attempt in row["backend_attempts"]:
            _keys(attempt, ("started", "finished"), "backend history")
            start, finish = attempt["started"], attempt["finished"]
            check_payload(start)
            _require(
                start["kind"] == "ActionStarted"
                and start["operation"] == "backend"
                and start["parent_id"] == key
                and start["event_id"] not in ids,
                "backend start binding differs",
            )
            ids.add(start["event_id"])
            if finish is not None:
                check_payload(finish)
                _require(
                    finish["kind"] == "ActionFinished"
                    and finish["attempt_id"] == start["event_id"],
                    "backend finish differs",
                )
        output[key] = row
    return output


def _snapshots(library):
    _require(
        type(library["snapshots"]) is list and len(library["snapshots"]) == 3,
        "three complete Core snapshots required",
    )
    result = {}
    for row, kind in zip(
        library["snapshots"], ("CandidateSnapshot", "ClaimSnapshot", "DecisionSnapshot")
    ):
        _keys(
            row,
            (
                "kind",
                "schema_version",
                "source_run_id",
                "source_state_sha256",
                "rows",
                "sha256",
                "persisted_refs",
                "origin",
            ),
            "screening snapshot",
        )
        original = {
            k: v
            for k, v in row.items()
            if k not in {"sha256", "persisted_refs", "origin"}
        }
        check(original, kind)
        _require(
            row["kind"] == kind
            and row["origin"] == "core-snapshot-read-only"
            and row["sha256"] == sha(canonical(original))
            and row["source_run_id"] == library["binding"]["run_id"]
            and row["source_state_sha256"] == library["binding"]["ledger_state_sha256"],
            "snapshot binding differs",
        )
        _require(
            type(row["persisted_refs"]) is list and len(row["persisted_refs"]) <= 1,
            "snapshot refs differ",
        )
        _require(
            all(ref["sha256"] == row["sha256"] for ref in row["persisted_refs"]),
            "snapshot ref hash differs",
        )
        result[kind] = row["rows"]
    return result


def _row(row, candidate, claims, decisions, queries, ranks):
    _keys(
        row,
        (
            "work_id",
            "candidate_event_id",
            "candidate_revision",
            "canonical_key",
            "identity_status",
            "metadata_evidence_level",
            "selected_version_id",
            "metadata",
            "versions",
            "discoveries",
            "query_history",
            "current_decision",
            "screening_status",
            "decision_history",
            "source_attempts",
            "source_imports",
            "source_status",
            "claims",
            "current_review",
            "relevance",
            "reading",
            "counts",
            "first_candidate_discovery_order_in_run",
        ),
        "screening row",
    )
    work, selected = candidate["work_id"], row["selected_version_id"]
    _require(
        all(
            row[k] == candidate[source]
            for k, source in (
                ("work_id", "work_id"),
                ("candidate_event_id", "event_id"),
                ("candidate_revision", "revision"),
                ("canonical_key", "canonical_key"),
                ("identity_status", "identity_status"),
                ("metadata_evidence_level", "evidence_level"),
            )
        ),
        "candidate projection differs",
    )
    expected = [d for d in candidate["discoveries"] if d["version_id"] == selected]
    _require(
        bool(expected) and row["metadata"] == expected[-1]["record"],
        "selected discovery metadata differs",
    )
    _require(
        row["versions"]
        == [
            {
                "version_id": v,
                "discovery_ids": [
                    d["discovery_id"]
                    for d in candidate["discoveries"]
                    if d["version_id"] == v
                ],
            }
            for v in candidate["version_ids"]
        ],
        "version history differs",
    )
    _require(
        len(row["discoveries"]) == len(candidate["discoveries"]),
        "discovery history incomplete",
    )
    for observed, discovery in zip(row["discoveries"], candidate["discoveries"]):
        _require(
            set(observed)
            == set(discovery)
            | {
                "candidate_discovery_order_in_run",
                "result_position",
                "completion_created_at",
                "round_number",
            }
            and all(observed[k] == v for k, v in discovery.items()),
            "discovery observation rewritten",
        )
        query = queries.get(discovery["query_id"])
        _require(query is not None, "discovery query omitted")
        attempt = next(
            (
                a
                for a in query["backend_attempts"]
                if a["started"]["event_id"] == discovery["attempt_id"]
            ),
            None,
        )
        _require(
            attempt is not None
            and attempt["finished"] is not None
            and attempt["finished"]["event_id"] == discovery["completion_id"]
            and attempt["finished"]["records"] == discovery["source_ref"],
            "discovery completion binding differs",
        )
        _require(
            observed["candidate_discovery_order_in_run"]
            == ranks[discovery["discovery_id"]]
            and observed["result_position"] == discovery["record_index"] + 1
            and observed["completion_created_at"] == attempt["finished"]["created_at"]
            and observed["round_number"]
            == query["started"]["arguments"].get("coverage", {}).get("round_number"),
            "discovery order differs",
        )
    history = [d for d in decisions if d["subject_id"] == work]
    work_claims = [c for c in claims if c["work_id"] == work]
    query_ids = {d["query_id"] for d in candidate["discoveries"]}
    _require(
        row["decision_history"] == history
        and row["current_decision"] == (history[-1] if history else None)
        and row["screening_status"]
        == (history[-1]["new_decision"] if history else "not-screened")
        and row["claims"] == work_claims
        and row["query_history"]
        == [queries[q] for q in sorted(query_ids, key=lambda value: int(value[1:]))],
        "decision, claim or query history differs",
    )
    if row["current_review"] is not None:
        check_payload(row["current_review"])
        review = row["current_review"]
        _require(
            review["kind"] == "CoverageWorkReview"
            and review["work_id"] == work
            and review["version_id"] == selected
            and review["candidate_event_id"] == candidate["event_id"]
            and history
            and review["decision_event_id"] == history[-1]["event_id"],
            "current review binding differs",
        )
    else:
        _require(
            selected == candidate["discoveries"][-1]["version_id"],
            "unreviewed selected version differs",
        )
    seen = set()
    for attempt in row["source_attempts"]:
        _keys(attempt, ("started", "finished"), "source history")
        start, finish = attempt["started"], attempt["finished"]
        check_payload(start)
        _require(
            start["kind"] == "SourceReadStarted"
            and start["work_id"] == work
            and start["version_id"] in candidate["version_ids"]
            and start["event_id"] not in seen,
            "source start differs",
        )
        seen.add(start["event_id"])
        if finish is not None:
            check_payload(finish)
            _require(
                finish["kind"] == "SourceReadFinished"
                and finish["attempt_id"] == start["event_id"],
                "source finish differs",
            )
    for item in row["source_imports"]:
        _keys(item, ("started", "artifacts"), "source import history")
        check_payload(item["started"])
        _require(
            item["started"]["kind"] == "SourceImportStarted"
            and item["started"]["work_id"] == work
            and item["started"]["version_id"] in candidate["version_ids"]
            and type(item["artifacts"]) is list
            and all(
                ref["producer"] == item["started"]["event_id"]
                for ref in item["artifacts"]
            ),
            "source import differs",
        )
    latest_source = next(
        (
            a
            for a in reversed(row["source_attempts"])
            if a["started"]["version_id"] == selected
        ),
        None,
    )
    imports = [
        i for i in row["source_imports"] if i["started"]["version_id"] == selected
    ]
    status = (
        (
            "not-acquired"
            if not imports
            else "saved-import-bytes-recorded"
            if any(i["artifacts"] for i in imports)
            else "saved-import-intent-recorded"
        )
        if latest_source is None
        else (
            "pending"
            if latest_source["finished"] is None
            else latest_source["finished"]["outcome"]
        )
    )
    _require(row["source_status"] == status, "source status promoted")
    rounds = {
        d["round_number"] for d in row["discoveries"] if d["round_number"] is not None
    }
    _require(
        row["counts"]
        == {
            "discoveries": len(row["discoveries"]),
            "distinct_queries": len(query_ids),
            "discovery_producing_backend_attempts": len(
                {d["attempt_id"] for d in row["discoveries"]}
            ),
            "query_backend_attempts": sum(
                len(queries[q]["backend_attempts"]) for q in query_ids
            ),
            "recorded_rounds": len(rounds),
            "round_ids_known": all(
                d["round_number"] is not None for d in row["discoveries"]
            ),
            "decisions": len(history),
            "reversals": sum(d["reverses_event_id"] is not None for d in history),
            "source_attempts": len(row["source_attempts"]),
            "claims": len(work_claims),
        },
        "row counts differ",
    )
    selected_claims = [c for c in work_claims if c["version_id"] == selected]
    _require(
        row["reading"]
        == {
            "status": "claim-evidence-recorded"
            if selected_claims
            else "no-reading-evidence-recorded",
            "selected_version_claim_count": len(selected_claims),
            "model_execution": "Unknown",
            "complete_body_reading": "Unknown",
        }
        and row["relevance"]
        == {
            "score": None,
            "status": "Unknown",
            "basis": "no-relevance-assessment-in-core-snapshot",
        },
        "reading or relevance promoted",
    )
    _require(
        row["first_candidate_discovery_order_in_run"]
        == min(ranks[d["discovery_id"]] for d in row["discoveries"]),
        "first discovery order differs",
    )


def validate_extension(records):
    """Validate output-only discovery history and forbid dropping observed evidence."""
    library = records["screening_library"]
    _keys(
        library,
        (
            "kind",
            "schema_version",
            "binding",
            "snapshots",
            "rows",
            "query_history",
            "counts",
            "coverage",
            "checkpoint",
            "status",
            "stage1_complete",
            "canonical_package",
            "execution_authorized",
            "evaluation_status",
        ),
        "screening library",
    )
    _require(
        library["kind"] == "Stage1ScreeningLibrary"
        and library["schema_version"] == "1.0.0"
        and library["status"] == "partial-saved-screening"
        and library["stage1_complete"] is False
        and library["canonical_package"] is None
        and library["execution_authorized"] is False
        and library["evaluation_status"] == "not-scored",
        "library status promoted",
    )
    binding = library["binding"]
    _keys(records["screening_journal"], ("path", "sha256"), "screening journal")
    _require(
        records["screening_journal"]
        == {"path": "screening_events.jsonl", "sha256": binding["journal_sha256"]},
        "journal binding differs",
    )
    _keys(
        binding,
        (
            "project_id",
            "input_version",
            "brief_sha256",
            "plan_manifest_sha256",
            "settings_sha256",
            "project_ref",
            "run_ref",
            "run_id",
            "manifest_sha256",
            "ledger_state_sha256",
            "journal_sha256",
        ),
        "screening binding",
    )
    _require(
        type(binding["input_version"]) is int and binding["input_version"] > 0,
        "input version invalid",
    )
    for key, value in binding.items():
        if key.endswith("sha256"):
            _require(
                isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value),
                "binding hash invalid",
            )
        elif key != "input_version":
            _text(value)
    core = _snapshots(library)
    candidates = {c["work_id"]: c for c in core["CandidateSnapshot"]}
    _require(len(candidates) == len(core["CandidateSnapshot"]), "duplicate candidates")
    queries = _queries(library["query_history"])
    discoveries = sorted(
        (d for c in candidates.values() for d in c["discoveries"]),
        key=lambda d: (int(d["completion_id"][1:]), d["record_index"]),
    )
    ranks = {d["discovery_id"]: i for i, d in enumerate(discoveries, 1)}
    _require(len(ranks) == len(discoveries), "duplicate discoveries")
    rows = {r["work_id"]: r for r in library["rows"]}
    papers = {p["work_id"]: p for p in records["papers"]}
    _require(
        len(rows) == len(library["rows"])
        and set(rows) == set(candidates) == set(papers),
        "complete candidate set differs",
    )
    _require(
        [r["work_id"] for r in library["rows"]]
        == sorted(
            rows,
            key=lambda work: min(
                ranks[d["discovery_id"]] for d in candidates[work]["discoveries"]
            ),
        ),
        "candidate order differs",
    )
    _require(
        [r["payload"] for r in records["core_claim_history"]] == core["ClaimSnapshot"],
        "Core claim history incomplete",
    )
    decisions = core["DecisionSnapshot"]
    projected = {d["decision_id"]: d for d in records["screening"]}
    _require(
        len(projected) == len(decisions)
        and set(projected) == {d["event_id"] for d in decisions},
        "screening history incomplete",
    )
    for decision in decisions:
        item = projected[decision["event_id"]]
        _require(
            (item["work_id"], item["status"], item["reason"], item["observed_at"])
            == (
                decision["subject_id"],
                decision["new_decision"],
                decision["rationale"],
                decision["created_at"],
            ),
            "screening decision rewritten",
        )
    for work, row in rows.items():
        _row(row, candidates[work], core["ClaimSnapshot"], decisions, queries, ranks)
        paper = papers[work]
        _require(
            paper["version_id"] == row["selected_version_id"]
            and all(
                paper[k] == row["metadata"].get(k) for k in ("title", "authors", "year")
            ),
            "paper metadata differs",
        )
        selected_sources = [
            a["started"]["event_id"]
            for a in row["source_attempts"]
            if a["started"]["version_id"] == paper["version_id"]
        ]
        selected_claims = [
            c["event_id"]
            for c in row["claims"]
            if c["version_id"] == paper["version_id"]
        ]
        _require(
            set(paper["source_ids"]) == set(selected_sources)
            and set(paper["claim_ids"]) == set(selected_claims),
            "selected source or claim observations omitted",
        )
        if paper["reading_status"] == "discovery-only":
            _require(
                not selected_sources
                and not selected_claims
                and row["current_review"] is None
                and not paper["roles"]
                and paper["evidence_level"] == "metadata"
                and paper["classification"] == dict.fromkeys(CLASSIFICATION, "Unknown")
                and paper["findings"] == dict.fromkeys(FINDINGS, "Unknown")
                and paper["url"] == (row["metadata"].get("url") or None),
                "discovery-only promoted or observed evidence dropped",
            )
            _require(
                paper["doi"] == row["metadata"].get("doi")
                and paper["venue"] == (row["metadata"].get("venue") or "Unknown"),
                "discovery DOI or venue differs",
            )
        else:
            _require(
                paper["reading_status"] == "human-reviewed" and bool(selected_sources),
                "saved annotation requires actual source",
            )
    expected_counts = dict(
        total_candidates=len(rows),
        query_intents=len(queries),
        completed_queries=sum(q["result"] is not None for q in queries.values()),
        **{
            key: sum(r["screening_status"] == value for r in rows.values())
            for key, value in (
                ("include", "include"),
                ("exclude", "exclude"),
                ("pending", "pending"),
                ("not_screened", "not-screened"),
            )
        },
        source_attempts=sum(len(r["source_attempts"]) for r in rows.values()),
        source_pending=sum(
            a["finished"] is None for r in rows.values() for a in r["source_attempts"]
        ),
        source_failures=sum(
            a["finished"] is not None and a["finished"]["outcome"] in FAILURES
            for r in rows.values()
            for a in r["source_attempts"]
        ),
    )
    _keys(library["counts"], ("core", *expected_counts), "screening counts")
    _require(
        all(library["counts"][k] == v for k, v in expected_counts.items()),
        "library counts differ",
    )
    finishes = [
        a["finished"]
        for q in queries.values()
        for a in q["backend_attempts"]
        if a["finished"] is not None
    ]
    from stage1_ledger.semantics import SUCCESS

    _require(
        library["counts"]["core"]
        == {
            "queries": expected_counts["completed_queries"],
            "backend_attempts": sum(
                len(q["backend_attempts"]) for q in queries.values()
            ),
            "backend_failures": sum(f["outcome"] not in SUCCESS for f in finishes),
            "success_empty": sum(f["outcome"] == "success_empty" for f in finishes),
            "discoveries": len(discoveries),
            "works": len(candidates),
            "candidate_revisions": sum(c["revision"] for c in candidates.values()),
            "decisions": len(decisions),
            "claims": len(core["ClaimSnapshot"]),
        },
        "Core counts differ",
    )
    _require(
        records["screening_artifacts"] == artifacts(library),
        "artifact history incomplete or rewritten",
    )
    return library


def journal_rows(records, raw):
    """Check the exact saved full journal before using its typed observations."""
    _require(
        sha(raw) == records["screening_journal"]["sha256"]
        and (not raw or raw.endswith(b"\n")),
        "journal hash differs or tail incomplete",
    )
    rows, previous, previous_time = [], "0" * 64, None
    for number, line in enumerate(raw.splitlines(), 1):
        row = decode(line, "screening journal")
        _keys(
            row,
            (
                "schema_version",
                "sequence",
                "previous_sha256",
                "event_sha256",
                "payload",
            ),
            "screening journal row",
        )
        unsigned = {k: v for k, v in row.items() if k != "event_sha256"}
        _require(
            row["schema_version"] == "1.0.0"
            and type(row["sequence"]) is int
            and row["sequence"] == number
            and row["previous_sha256"] == previous
            and row["event_sha256"] == sha(canonical(unsigned)),
            "journal chain differs",
        )
        event = row["payload"]
        check_payload(event)
        stamp = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
        _require(
            event["event_id"] == f"e{number:06d}"
            and event["created_at"].endswith("Z")
            and (previous_time is None or stamp >= previous_time),
            "journal identity or time differs",
        )
        previous, previous_time = row["event_sha256"], stamp
        rows.append(row)
    library = records["screening_library"]
    events = [row["payload"] for row in rows]
    candidates = {p["work_id"]: p for p in events if p["kind"] == "CandidateRevision"}
    expected = (
        list(candidates.values()),
        [p for p in events if p["kind"] == "ClaimEvidence"],
        [p for p in events if p["kind"] == "DecisionEvent"],
    )
    _require(
        all(
            snapshot["rows"] == value
            for snapshot, value in zip(library["snapshots"], expected)
        ),
        "journal Core snapshot history differs",
    )
    _require(
        records["core_claim_history"]
        == [row for row in rows if row["payload"]["kind"] == "ClaimEvidence"],
        "journal claim archive history differs",
    )
    finishes = {p["attempt_id"]: p for p in events if p["kind"] == "ActionFinished"}
    results = {p["query_id"]: p for p in events if p["kind"] == "QueryEvent"}
    queries = [
        {
            "started": q,
            "result": results.get(q["event_id"]),
            "backend_attempts": [
                {"started": p, "finished": finishes.get(p["event_id"])}
                for p in events
                if p["kind"] == "ActionStarted"
                and p["operation"] == "backend"
                and p["parent_id"] == q["event_id"]
            ],
        }
        for q in events
        if q["kind"] == "ActionStarted" and q["operation"] == "search"
    ]
    _require(
        queries == library["query_history"], "journal query/backend history differs"
    )
    source_finishes = {
        p["attempt_id"]: p for p in events if p["kind"] == "SourceReadFinished"
    }
    decisions = {p["subject_id"]: p for p in expected[2]}
    reviews = {p["work_id"]: p for p in events if p["kind"] == "CoverageWorkReview"}
    for row in library["rows"]:
        work = row["work_id"]
        sources = [
            {"started": p, "finished": source_finishes.get(p["event_id"])}
            for p in events
            if p["kind"] == "SourceReadStarted" and p["work_id"] == work
        ]
        imports = [
            {
                "started": p,
                "artifacts": [
                    a["ref"]
                    for a in events
                    if a["kind"] == "ArtifactStored"
                    and a["ref"]["producer"] == p["event_id"]
                ],
            }
            for p in events
            if p["kind"] == "SourceImportStarted" and p["work_id"] == work
        ]
        review = reviews.get(work)
        decision = decisions.get(work)
        if review is not None and (
            candidates[work]["event_id"] != review["candidate_event_id"]
            or decision is None
            or decision["event_id"] != review["decision_event_id"]
            or decision["new_decision"] != "include"
        ):
            review = None
        _require(
            row["source_attempts"] == sources
            and row["source_imports"] == imports
            and row["current_review"] == review,
            "journal source/import/review history differs",
        )
    checkpoints = [p for p in events if p["kind"] == "Checkpoint"]
    checkpoint = checkpoints[-1] if checkpoints else None
    expected_checkpoint = (
        None
        if checkpoint is None
        else {
            "event_id": checkpoint["event_id"],
            "current": checkpoint["state_sha256"]
            == library["binding"]["ledger_state_sha256"],
            "outputs": checkpoint["stage_result"]["outputs"],
        }
    )
    _require(library["checkpoint"] == expected_checkpoint, "journal checkpoint differs")
    return rows


def validate_artifacts(records, read):
    library = validate_extension(records)
    journal_rows(records, read(records["screening_journal"]["path"]))
    raw = {}
    for item in records["screening_artifacts"]:
        data = read(item["artifact_path"])
        _require(
            sha(data) == item["source_ref"]["sha256"], "saved raw artifact hash differs"
        )
        raw[canonical(item["source_ref"])] = data
    for snapshot in library["snapshots"]:
        for ref in snapshot["persisted_refs"]:
            original = {
                k: v
                for k, v in snapshot.items()
                if k not in {"sha256", "persisted_refs", "origin"}
            }
            _require(
                raw[canonical(ref)] == canonical(original),
                "saved snapshot bytes differ",
            )
    for row in library["rows"]:
        for discovery in row["discoveries"]:
            values = decode(
                raw[canonical(discovery["source_ref"])], "saved discovery records"
            )
            _require(
                type(values) is list
                and discovery["record_index"] < len(values)
                and values[discovery["record_index"]] == discovery["record"],
                "saved discovery raw record differs",
            )
    return raw


def read_artifacts(records, root):
    return validate_artifacts(records, lambda path: safe_path(root, path).read_bytes())

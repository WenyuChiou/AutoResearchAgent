"""Opt-in, externally pinned recorded-run prefixes; never new search execution."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import sys

from stage1_deliverable.common import DeliverableError, canonical, sha
from stage1_deliverable.screening_records import journal_rows, validate_extension
from stage1_ledger.semantics import SUCCESS, query_fields

from .json_bytes import decode_json
from .projection import validate_index
from .retrieval_trace import work_trace

CONTRACT = "S1-RETRIEVAL-TRACE-1.1.0"
MAX_BYTES = 64 * 1024 * 1024


def _check(condition, message):
    if not condition:
        raise DeliverableError("retrieval-prefix: " + message)


def _history(rows):
    """Check parent/completion order as well as the existing journal chain."""
    starts, finishes, results = {}, {}, {}
    for row in rows:
        event = row["payload"]
        kind, key = event["kind"], event["event_id"]
        if kind == "ActionStarted":
            parent = event["parent_id"]
            if event["operation"] == "backend":
                _check(
                    parent in starts
                    and starts[parent]["operation"] == "search"
                    and parent not in results,
                    "backend parent missing or closed",
                )
            else:
                _check(
                    parent is None and event["backend"] is None,
                    "query backend or parent differs",
                )
            starts[key] = event
        elif kind == "ActionFinished":
            parent = event["attempt_id"]
            _check(
                parent in starts
                and starts[parent]["operation"] == "backend"
                and parent not in finishes,
                "backend completion missing start or duplicated",
            )
            finishes[parent] = event
        elif kind == "QueryEvent":
            parent = event["query_id"]
            children = [p for p in starts.values() if p["parent_id"] == parent]
            _check(
                parent in starts
                and starts[parent]["operation"] == "search"
                and parent not in results
                and children
                and all(p["event_id"] in finishes for p in children),
                "query completion missing starts or backend completions",
            )
            expected = query_fields(
                starts[parent],
                children,
                [
                    p
                    for p in finishes.values()
                    if p["attempt_id"] in {c["event_id"] for c in children}
                ],
            )
            _check(
                all(event[k] == v for k, v in expected.items()),
                "query completion differs",
            )
            results[parent] = event


def derive_retrieval_prefix(
    index_raw, journal_raw, *, trusted_index_sha256, project_id, input_version, run_id
):
    """Derive only the prefix in these externally accepted index/journal bytes.

    The trusted hash is an out-of-band caller input, not a self-issued acceptance.
    It does not authenticate unrecorded activity, human decisions or execution.
    """
    _check(
        type(index_raw) is bytes and len(index_raw) <= MAX_BYTES,
        "index bytes missing or oversized",
    )
    _check(
        isinstance(trusted_index_sha256, str)
        and re.fullmatch(r"[a-f0-9]{64}", trusted_index_sha256)
        and sha(index_raw) == trusted_index_sha256,
        "external index hash differs",
    )
    _check(
        all(type(v) is str and v.strip() for v in (project_id, run_id))
        and type(input_version) is int
        and input_version > 0,
        "expected project/input/run required",
    )
    index = decode_json(index_raw)
    canonical(index)  # Reject nonfinite JSON, without reopening the input.
    validate_index(index)
    _check(index["project_id"] == project_id, "project differs")
    requested = dict(project_id=project_id, input_version=input_version, run_id=run_id)
    library = index.get("screening_library")
    binding, rows = None, None
    if library is not None:
        validate_extension(index)
        binding = library["binding"]
        _check(
            all(binding[k] == v for k, v in requested.items()),
            "recorded project/input/run differs",
        )
        if journal_raw is not None:
            _check(
                type(journal_raw) is bytes and len(journal_raw) <= MAX_BYTES,
                "journal bytes invalid or oversized",
            )
            rows = journal_rows(index, journal_raw)
            _history(rows)
    elif journal_raw is not None:
        raise DeliverableError("retrieval-prefix: journal without bound library")

    positions = (
        {}
        if rows is None
        else {row["payload"]["event_id"]: row["sequence"] for row in rows}
    )

    def reference(event):
        return dict(
            path=index["screening_journal"]["path"],
            sha256=binding["journal_sha256"],
            jsonl_line=positions[event["event_id"]],
            pointer="/payload",
            event_id=event["event_id"],
        )

    output = []
    for paper in index["papers"]:
        trace = work_trace(index, paper["work_id"])
        trace["contract_version"] = CONTRACT
        if rows is None:
            trace["unknown_reasons"].append(
                "complete-recorded-run-journal-not-supplied"
                if library
                else "no-bound-recorded-run-library"
            )
            output.append(trace)
            continue
        number, work = next(
            (n, r)
            for n, r in enumerate(library["rows"])
            if r["work_id"] == paper["work_id"]
        )
        first = min(
            work["discoveries"],
            key=lambda d: (positions[d["completion_id"]], d["record_index"]),
        )
        cutoff = positions[first["completion_id"]]
        events = [r["payload"] for r in rows[:cutoff]]
        finished = {p["attempt_id"]: p for p in events if p["kind"] == "ActionFinished"}
        completed = {p["query_id"]: p for p in events if p["kind"] == "QueryEvent"}
        queries = []
        for query_number, query in enumerate(library["query_history"]):
            start = query["started"]
            if positions[start["event_id"]] > cutoff:
                continue
            attempts = []
            for attempt in query["backend_attempts"]:
                begun = attempt["started"]
                if positions[begun["event_id"]] <= cutoff:
                    end = finished.get(begun["event_id"])
                    attempts.append(
                        dict(
                            attempt_id=begun["event_id"],
                            backend=begun["backend"],
                            started=reference(begun),
                            finished=None if end is None else reference(end),
                            outcome=None if end is None else end["outcome"],
                            status="pending-at-cutoff" if end is None else "completed",
                        )
                    )
            result = completed.get(start["event_id"])
            queries.append(
                dict(
                    query_id=start["event_id"],
                    index_pointer=f"/screening_library/query_history/{query_number}",
                    arguments=deepcopy(start["arguments"]),
                    started=reference(start),
                    completed=None if result is None else reference(result),
                    backend_attempts=attempts,
                )
            )
        attempts = [a for q in queries for a in q["backend_attempts"]]
        trace["search_attempts_until_first_discovery"] = dict(
            status="recorded-prefix",
            scope="bound-recorded-run-input",
            discovery_basis="earliest recorded CandidateSnapshot discovery completion across recorded versions; unextracted raw results are not searched",
            denominator="ActionStarted ids through inclusive first recorded backend completion; completions are counted separately",
            cutoff_inclusive=reference(rows[cutoff - 1]["payload"]),
            first_version_id=first["version_id"],
            round_number=first["round_number"],
            discovery_pointer=f"/screening_library/rows/{number}/discoveries/"
            + str(work["discoveries"].index(first)),
            source_ref=deepcopy(first["source_ref"]),
            source_artifact_bytes_replayed=False,
            counts=dict(
                query_starts=len(queries),
                backend_attempt_starts=len(attempts),
                query_completions=len(completed),
                backend_attempt_completions=len(finished),
                backend_failures=sum(
                    a["outcome"] is not None and a["outcome"] not in SUCCESS
                    for a in attempts
                ),
                success_empty=sum(a["outcome"] == "success_empty" for a in attempts),
            ),
            queries=queries,
        )
        trace["unknown_reasons"] = [
            r
            for r in trace["unknown_reasons"]
            if r != "work-query-history-is-not-all-searches-before-discovery"
        ]
        trace["unknown_reasons"].append("unrecorded-real-world-searches-unknown")
        output.append(trace)
    return dict(
        kind="Stage1RetrievalPrefix",
        contract_version=CONTRACT,
        input_sha256=sha(index_raw),
        requested_binding=requested,
        binding=deepcopy(binding),
        rows=output,
        scope_note="Complete prefix of the pinned recorded run only. Starts and completions have different denominators. Original four work-level counts remain separate. Self-consistent hashes do not establish unrecorded real-world history or authenticate acceptance.",
        research_execution=False,
        execution_authorized=False,
        Core_acceptance=False,
        formal_Stage2_import=False,
        scientific_assessment=False,
    )


def _read(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    _check(len(raw) <= MAX_BYTES, "file bound exceeded")
    return raw


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index")
    parser.add_argument("--journal")
    parser.add_argument("--trusted-index-sha256", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--input-version", type=int, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        value = derive_retrieval_prefix(
            _read(args.index),
            None if args.journal is None else _read(args.journal),
            trusted_index_sha256=args.trusted_index_sha256,
            project_id=args.project_id,
            input_version=args.input_version,
            run_id=args.run_id,
        )
        print(json.dumps(value, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps(dict(error=str(error)), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

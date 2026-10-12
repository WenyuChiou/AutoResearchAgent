"""Bounded read-only transport for the complete saved screening projection."""

from copy import deepcopy
import re

from .session_api import _check

PAGE_SIZE = 20
PAGE_ROUTE = re.compile(
    r"/api/projects/([A-Za-z0-9_-]{1,64})/stage1/screening/"
    r"([1-9][0-9]{0,6})/([a-f0-9]{64})/(0|[1-9][0-9]{0,6})"
    r"(?:/([a-f0-9]{64}))?"
)
DETAIL_ROUTE = re.compile(
    r"/api/projects/([A-Za-z0-9_-]{1,64})/stage1/screening-detail/"
    r"([1-9][0-9]{0,6})/([a-f0-9]{64})/([a-f0-9]{64})/"
    r"(0|[1-9][0-9]{0,6})"
)


def descriptor(stage):
    ledger = stage.get("ledger")
    return dict(
        available=ledger is not None,
        project_ref=stage["project_ref"],
        input_version=stage["input_version"],
        ledger_state_sha256=None if ledger is None else ledger["state_sha256"],
        status=stage["stage1_status"],
        page_size=PAGE_SIZE,
    )


def read_page(service, credential, match, *, detail=False):
    """Never persist, initialize a ledger, acquire a source or restore an owner."""
    _check(service is not None, "project-operation-unconnected")
    if detail:
        ref, version, state, expected, position = match.groups()
    else:
        ref, version, state, position, expected = match.groups()
    index = int(position)
    _check(
        detail or index == 0 or expected is not None,
        "stage1-library-page-projection-required",
        400,
    )
    envelope = service.read(
        credential,
        ref,
        expected_input_version=int(version),
        expected_ledger_state_sha256=state,
        expected_projection_sha256=expected,
    )
    projection = envelope["projection"]
    rows = projection["rows"]
    base = dict(
        kind="Stage1ScreeningDetail" if detail else "Stage1ScreeningPage",
        schema_version="1.0.0",
        project_ref=ref,
        input_version=envelope["input_version"],
        projection_sha256=envelope["projection_sha256"],
        binding=deepcopy(projection["binding"]),
        total=len(rows),
        stage1_complete=False,
        canonical_package=None,
        execution_authorized=False,
        status=projection["status"],
    )
    if detail:
        _check(index < len(rows), "stage1-library-detail-out-of-range", 404)
        return dict(base, index=index, row=deepcopy(rows[index]))
    _check(index == 0 or index < len(rows), "stage1-library-page-out-of-range", 404)
    _check(index % PAGE_SIZE == 0, "stage1-library-page-offset-invalid", 400)
    selected = []
    for offset, row in enumerate(rows[index : index + PAGE_SIZE], index):
        selected.append(
            dict(
                index=offset,
                work_id=row["work_id"],
                selected_version_id=row["selected_version_id"],
                title=row["metadata"].get("title"),
                authors=deepcopy(row["metadata"].get("authors")),
                year=row["metadata"].get("year"),
                screening_status=row["screening_status"],
                source_status=row["source_status"],
                reading=deepcopy(row["reading"]),
                relevance=deepcopy(row["relevance"]),
                counts=deepcopy(row["counts"]),
                first_candidate_discovery_order_in_run=row[
                    "first_candidate_discovery_order_in_run"
                ],
                current_decision=deepcopy(row["current_decision"]),
            )
        )
    next_offset = index + len(selected)
    return dict(
        base,
        offset=index,
        next_offset=next_offset if next_offset < len(rows) else None,
        rows=selected,
        counts=deepcopy(projection["counts"]),
        snapshot_hashes=[
            dict(kind=value["kind"], sha256=value["sha256"])
            for value in projection["snapshots"]
        ],
    )

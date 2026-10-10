"""Trusted Stage1 query registration; byte/schema checks never start a process."""

from copy import deepcopy
import math
from pathlib import Path
import re
import time

from stage1_brief.brief import validate_bound_plan, validate_brief
from stage1_deliverable.common import canonical, private_output, reject_links, sha
from stage1_ledger.journal import decode
from stage1_coverage.run import CoverageLedger
from stage1_retrieval.receipt import check_pin
from stage1_retrieval.runtime_identity import verify_identity
from research_workspace_native.session_api import SessionApiError
from research_workspace_native.stage_inputs import snapshot_inputs, source_digest

REF = re.compile(r"[A-Za-z0-9_-]{1,64}")
KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
HASH = re.compile(r"[a-f0-9]{64}")
BACKENDS = {"openalex", "crossref", "semantic-scholar", "arxiv", "pubmed"}
PROBE_TIMEOUT_SECONDS = 30  # Existing isolated Python import-path probe limit.
FIELDS = {
    "project_id",
    "index_sha256",
    "input_version",
    "brief_path",
    "brief_sha256",
    "plan_root",
    "plan_sha256",
    "ledger_root",
    "ledger_manifest_sha256",
    "runtime_sha256",
    "execution_source_sha256",
    "execution_source_root",
    "permit_path",
    "permit_sha256",
    "principals",
    "control_store_path",
    "parent_ledger_root",
    "parent_ledger_sha256",
}


def require(value, code, status=409):
    if not value:
        raise SessionApiError(code, status)


def path(value, *, directory=False):
    p = Path(value)
    require(p.is_absolute(), "absolute-query-path-required", 400)
    reject_links(p)
    p = private_output(p).resolve()
    require(p.is_dir() if directory else p.is_file(), "query-input-missing")
    return p


def raw_file(value, expected, maximum=65536):
    p = path(value)
    require(
        isinstance(expected, str) and HASH.fullmatch(expected), "query-pin-required"
    )
    with p.open("rb") as stream:
        raw = stream.read(maximum + 1)
    require(
        0 < len(raw) <= maximum and sha(raw) == expected, "query-input-bytes-differ"
    )
    return raw


def tree_sha(root):
    return source_digest(snapshot_inputs({1: {"ledger_root": str(root)}, 2: None}))


def inspect_registration(ref, item, *, require_ready=True):
    require(
        isinstance(ref, str) and REF.fullmatch(ref), "query-project-ref-invalid", 400
    )
    require(
        isinstance(item, dict) and set(item) == FIELDS, "query-registration-fields", 400
    )
    item = deepcopy(item)
    require(
        isinstance(item["project_id"], str)
        and 0 < len(item["project_id"]) <= 128
        and isinstance(item["principals"], list)
        and 1 <= len(item["principals"]) <= 16
        and all(isinstance(p, str) and 0 < len(p) <= 128 for p in item["principals"])
        and len(set(item["principals"])) == len(item["principals"]),
        "query-principals-required",
        400,
    )
    for name in (
        "index_sha256",
        "input_version",
        "runtime_sha256",
        "execution_source_sha256",
    ):
        require(
            isinstance(item[name], str) and HASH.fullmatch(item[name]),
            "query-pin-required",
        )
    for name in (
        "brief_path",
        "permit_path",
        "plan_root",
        "ledger_root",
        "parent_ledger_root",
    ):
        item[name] = path(item[name], directory=name.endswith("_root")).as_posix()
    source_root = Path(item["execution_source_root"])
    require(
        source_root.is_absolute() and source_root.is_dir(),
        "query-execution-source-root-required",
    )
    reject_links(source_root)
    item["execution_source_root"] = source_root.resolve().as_posix()
    store = Path(item["control_store_path"])
    require(store.is_absolute(), "absolute-query-store-required", 400)
    item["control_store_path"] = private_output(store).resolve().as_posix()
    require(
        tree_sha(item["parent_ledger_root"]) == item["parent_ledger_sha256"],
        "query-parent-source-differs",
    )
    brief = decode(raw_file(item["brief_path"], item["brief_sha256"]), "query brief")
    validate_brief(brief, require_confirmed=True)
    require(brief["schema_version"] == "1.1.0", "query-version-bound-intake-required")
    require(
        brief["project_id"] == item["project_id"]
        and brief["input_version"] == item["input_version"],
        "query-intake-project-differs",
    )
    require(
        tree_sha(item["plan_root"]) == item["plan_sha256"], "query-plan-bytes-differ"
    )
    validate_bound_plan(item["plan_root"], item["brief_path"])
    manifest_raw = raw_file(
        Path(item["ledger_root"]) / "run_manifest.json", item["ledger_manifest_sha256"]
    )
    manifest = decode(manifest_raw, "query ledger manifest")
    require(manifest["mode"] == "research-hub-cli", "query-live-runtime-required")
    pin = manifest["research_hub_pin"]
    check_pin(pin)
    require(pin["status"] == "merged", "query-merged-runtime-required")
    require(sha(canonical(pin)) == item["runtime_sha256"], "query-runtime-pin-differs")
    verify_identity(
        pin
    )  # Pure saved-byte check; probe=True belongs to the admitted worker.
    raw_file(pin["config"]["path"], pin["config"]["sha256"], maximum=1024 * 1024)
    state = CoverageLedger(item["ledger_root"]).coverage_state()
    require(
        state.plan is not None and state.active is not None,
        "query-bound-open-plan-required",
    )
    bound_plan = decode(
        (Path(item["plan_root"]) / "coverage_plan.json").read_bytes(), "plan"
    )
    require(state.plan == bound_plan, "query-ledger-plan-differs")
    permit = decode(
        raw_file(item["permit_path"], item["permit_sha256"]), "query permit"
    )
    identity = {
        k: item[k]
        for k in (
            "project_id",
            "index_sha256",
            "input_version",
            "brief_sha256",
            "plan_sha256",
            "ledger_manifest_sha256",
            "runtime_sha256",
            "execution_source_sha256",
            "execution_source_root",
            "control_store_path",
            "parent_ledger_sha256",
        )
    }
    require(
        isinstance(permit, dict)
        and set(permit)
        == {
            "kind",
            "schema_version",
            "project_ref",
            "binding",
            "principals",
            "planned_ids",
            "backends",
            "max_attempts",
            "max_reserved_seconds",
            "max_results",
            "timeout_seconds",
            "expires_at_unix",
            "allow_search",
        }
        and permit["kind"] == "Stage1PlannedQueryPermit"
        and permit["schema_version"] == "1.0.0"
        and permit["project_ref"] == ref
        and permit["binding"] == identity
        and permit["principals"] == item["principals"]
        and permit["allow_search"] is True,
        "query-research-permit-differs",
    )
    require(
        isinstance(permit["planned_ids"], list)
        and 1 <= len(permit["planned_ids"]) <= 128
        and all(isinstance(q, str) for q in permit["planned_ids"])
        and len(set(permit["planned_ids"])) == len(permit["planned_ids"])
        and set(permit["planned_ids"]).issubset(state.queries)
        and isinstance(permit["backends"], list)
        and 1 <= len(permit["backends"]) <= 5
        and all(isinstance(b, str) for b in permit["backends"])
        and len(set(permit["backends"])) == len(permit["backends"])
        and set(permit["backends"]).issubset(BACKENDS)
        and set(permit["backends"]).issubset(state.binding["backends"]),
        "query-permit-targets-differ",
    )
    require(
        all(
            type(permit[k]) is int and 1 <= permit[k] <= maximum
            for k, maximum in (
                ("max_attempts", 128),
                ("max_reserved_seconds", 86400),
                ("max_results", 1000),
                ("timeout_seconds", 600),
            )
        )
        and type(permit["expires_at_unix"]) is int
        and (
            not require_ready
            or time.time() + pin["timeout_seconds"] + PROBE_TIMEOUT_SECONDS
            < permit["expires_at_unix"]
        )
        and math.isfinite(pin["timeout_seconds"])
        and pin["timeout_seconds"] <= permit["timeout_seconds"]
        and state.binding["limit"] <= permit["max_results"],
        "query-permit-budget-or-expiry",
    )
    return item, permit, state, pin


def next_target(state, permit):
    for planned in permit["planned_ids"]:
        matches = [
            p
            for p in state.starts.values()
            if p["operation"] == "search"
            and p["arguments"].get("coverage", {}).get("round_number") == state.active
            and p["arguments"].get("coverage", {}).get("planned_query_id") == planned
        ]
        require(len(matches) <= 1, "query-ambiguous-planned-action")
        query_id = matches[0]["event_id"] if matches else None
        used = (
            {
                p["backend"]
                for p in state.starts.values()
                if p.get("parent_id") == query_id
            }
            if query_id
            else set()
        )
        for backend in permit["backends"]:
            if backend not in used:
                return dict(
                    planned_id=planned,
                    query_id=query_id,
                    backend=backend,
                    arguments=state.arguments(planned),
                )
    raise SessionApiError("query-permit-targets-exhausted", 409)

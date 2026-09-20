"""Compile an authored decomposition into immutable, unexecuted obligations."""

from datetime import date
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from stage1_ledger.journal import (
    LedgerError,
    canonical,
    contained,
    decode,
    digest,
    write_new,
    utc_now,
)


@lru_cache(maxsize=None)
def schema_validator(name):
    path = (
        Path(__file__).resolve().parents[2]
        / "schemas/stage1-coverage-plan.v1.schema.json"
    )
    schema = decode(path.read_bytes(), str(path))
    shared = decode(
        (path.parent / "stage-contracts.v1.schema.json").read_bytes(),
        "shared contracts",
    )
    registry = Registry().with_resources(
        [
            (shared["$id"], Resource.from_contents(shared)),
            (schema["$id"], Resource.from_contents(schema)),
        ]
    )
    return Draft202012Validator(
        {"$ref": schema["$id"] + "#/$defs/" + name},
        registry=registry,
        format_checker=FormatChecker(),
    )


def check(value, name):
    errors = list(schema_validator(name).iter_errors(value))
    if errors:
        raise LedgerError(f"coverage-schema:{name}: {errors[0].message}")


def unique(items, label):
    if len(items) != len(set(items)):
        raise LedgerError(f"duplicate-{label}")


def validate_proposal(proposal):
    check(proposal, "Proposal")
    concept_ids = [c["concept_id"] for c in proposal["concepts"]]
    unique(concept_ids, "concept-id")
    unique([c["cluster_id"] for c in proposal["clusters"]], "cluster-id")
    families = []
    for concept in proposal["concepts"]:
        unique([term.casefold().strip() for term in concept["terms"]], "synonym")
    for cluster in proposal["clusters"]:
        for family in cluster["query_families"]:
            families.append(family["family_id"])
            if set(family["concept_ids"]) - set(concept_ids):
                raise LedgerError("unknown-query-concept")
    unique(families, "family-id")


def quote(term):
    return '"' + term.replace("\\", "\\\\").replace('"', '\\"') + '"'


def derive(proposal, *, as_of, actor):
    validate_proposal(proposal)
    cutoff = date.fromisoformat(as_of)
    window = {"from_year": cutoff.year - 2, "through_year": cutoff.year}
    plan = dict(
        kind="CoveragePlan",
        schema_version="1.0.0",
        proposal=proposal,
        as_of=as_of,
        actor=actor,
        recent_window=window,
    )
    check(plan, "CoveragePlan")
    concepts = {c["concept_id"]: c["terms"] for c in proposal["concepts"]}
    queries = []
    for cluster in proposal["clusters"]:
        for family in cluster["query_families"]:
            base = " AND ".join(
                "(" + " OR ".join(quote(t) for t in concepts[key]) + ")"
                for key in family["concept_ids"]
            )
            variants = [("topical", base, None, None)]
            variants += [
                ("adversarial", q, None, None) for q in family["adversarial_queries"]
            ]
            variants.append(
                (
                    "recent",
                    base,
                    f"{window['from_year']}-{window['through_year']}",
                    "year",
                )
            )
            for index, (purpose, query, year, rank_by) in enumerate(variants):
                identity = [
                    proposal["plan_id"],
                    cluster["cluster_id"],
                    family["family_id"],
                    purpose,
                    index,
                    query,
                    year,
                    as_of,
                ]
                row = dict(
                    kind="PlannedQuery",
                    schema_version="1.0.0",
                    query_id="planned-" + digest(canonical(identity)),
                    plan_id=proposal["plan_id"],
                    cluster_id=cluster["cluster_id"],
                    family_id=family["family_id"],
                    purpose=purpose,
                    query=query,
                    year=year,
                    rank_by=rank_by,
                    execution_status="not-executed",
                )
                check(row, "PlannedQuery")
                queries.append(row)
    return plan, queries


def compile_plan(proposal, output, *, as_of, actor, clock=utc_now):
    plan, queries = derive(proposal, as_of=as_of, actor=actor)
    root = Path(output)
    data = {
        "coverage_plan.json": canonical(plan) + b"\n",
        "query_plan.jsonl": b"".join(canonical(q) + b"\n" for q in queries),
    }
    refs = []
    created = clock()
    for name, raw in data.items():
        ref = dict(
            kind="ArtifactRef",
            schema_version="1.0.0",
            artifact_id="artifact-" + digest(raw),
            artifact_type="coverage-plan"
            if name == "coverage_plan.json"
            else "query-plan",
            path=name,
            sha256=digest(raw),
            producer=proposal["plan_id"],
            created_at=created,
        )
        refs.append(dict(ref=ref, bytes=len(raw)))
    manifest = dict(
        kind="CoveragePlanManifest",
        schema_version="1.0.0",
        plan_id=proposal["plan_id"],
        proposal_sha256=digest(canonical(proposal)),
        artifacts=refs,
        execution_status="not-executed",
    )
    check(manifest, "CoveragePlanManifest")
    # Validate every interface before creating output; preserve partial I/O failures.
    root.mkdir(parents=True, exist_ok=False)
    for name, raw in data.items():
        write_new(root / name, raw)
    write_new(root / "plan_manifest.json", canonical(manifest) + b"\n")
    return dict(
        plan_id=proposal["plan_id"],
        execution_status="not-executed",
        counts=dict(
            clusters=len(proposal["clusters"]),
            families=sum(len(c["query_families"]) for c in proposal["clusters"]),
            planned_queries=len(queries),
        ),
        artifacts=refs,
    )


def validate_bundle(directory):
    root = Path(directory).resolve()
    try:
        manifest = decode(
            contained(root, "plan_manifest.json").read_bytes(), "plan_manifest.json"
        )
        check(manifest, "CoveragePlanManifest")
        if [r["ref"]["path"] for r in manifest["artifacts"]] != [
            "coverage_plan.json",
            "query_plan.jsonl",
        ]:
            raise LedgerError("plan-artifact-set-mismatch")
        for entry in manifest["artifacts"]:
            ref = entry["ref"]
            data = contained(root, ref["path"]).read_bytes()
            if len(data) != entry["bytes"] or digest(data) != ref["sha256"]:
                raise LedgerError("plan-artifact-hash: " + ref["path"])
            if (
                ref["producer"] != manifest["plan_id"]
                or ref["artifact_id"] != "artifact-" + ref["sha256"]
                or ref["artifact_type"]
                != (
                    "coverage-plan"
                    if ref["path"] == "coverage_plan.json"
                    else "query-plan"
                )
            ):
                raise LedgerError("plan-artifact-identity")
        plan = decode(
            contained(root, "coverage_plan.json").read_bytes(), "coverage_plan.json"
        )
        check(plan, "CoveragePlan")
        expected_plan, expected_queries = derive(
            plan["proposal"], as_of=plan["as_of"], actor=plan["actor"]
        )
        if plan != expected_plan or manifest["plan_id"] != plan["proposal"]["plan_id"]:
            raise LedgerError("plan-replay-mismatch")
        if manifest["proposal_sha256"] != digest(canonical(plan["proposal"])):
            raise LedgerError("proposal-hash-mismatch")
        if contained(root, "query_plan.jsonl").read_bytes() != b"".join(
            canonical(q) + b"\n" for q in expected_queries
        ):
            raise LedgerError("query-plan-replay-mismatch")
        return dict(valid=True, errors=[], execution_status="not-executed")
    except (LedgerError, OSError, ValueError, KeyError, TypeError) as error:
        return dict(valid=False, errors=[str(error)], execution_status="not-executed")

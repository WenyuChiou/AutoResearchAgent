"""Read-only discovery summaries; saved batches never become research rounds."""

from copy import deepcopy

from stage1_deliverable.common import DeliverableError, canonical, sha

CONTRACT = "S1-RETRIEVAL-TRACE-1.0.0"


def work_trace(index, work_id):
    """Summarize an already validated index, preserving the recorded scope."""
    library = index.get("screening_library")
    base = dict(
        contract_version=CONTRACT,
        work_id=work_id,
        identity_scope="work-all-recorded-versions",
        first_discovery=None,
        search_attempts_until_first_discovery=None,
        saved_observation_count=None,
        distinct_saved_batch_count=None,
        first_saved_batch_by_inventory_order=None,
        source_pointers=[],
    )
    if library:
        number, row = next(
            (n, r) for n, r in enumerate(library["rows"]) if r["work_id"] == work_id
        )
        first = min(
            row["discoveries"], key=lambda d: d["candidate_discovery_order_in_run"]
        )
        base.update(
            mode="bound-run-discoveries",
            status="recorded",
            count_scope="bound-run-work-all-versions",
            query_history_scope="discovery-producing-queries-for-work",
            counts={
                key: row["counts"][key]
                for key in (
                    "discoveries",
                    "distinct_queries",
                    "discovery_producing_backend_attempts",
                    "query_backend_attempts",
                    "recorded_rounds",
                    "round_ids_known",
                )
            },
            first_discovery={
                key: first[key]
                for key in (
                    "discovery_id",
                    "version_id",
                    "query_id",
                    "attempt_id",
                    "round_number",
                    "completion_created_at",
                    "candidate_discovery_order_in_run",
                )
            },
            source_pointers=[f"/screening_library/rows/{number}"],
            unknown_reasons=["work-query-history-is-not-all-searches-before-discovery"],
            scope_note="Counts retain all recorded versions in the bound run. Query history contains only queries that returned this work, including those queries' failed backend attempts. These counts are not searches until first discovery.",
        )
        if first["round_number"] is None:
            base["unknown_reasons"].append(
                "first-recorded-discovery-round-not-recorded"
            )
        return base

    cohort = (
        index.get("original_record_recovery", {})
        .get("payload", {})
        .get("new_candidate_screening", {})
    )
    observations = cohort.get("observations", [])
    reviews = {
        r["observation_ref"]: (n, r)
        for n, r in enumerate(cohort.get("value", {}).get("rows", []))
    }
    originals = {o["observation_ref"]: o for o in observations}
    pairs = {(p["work_id"], p["version_id"]) for p in index.get("papers", [])}

    mapping_cache = {}

    def linked_review(key):
        trail = []
        seen = set()
        while key not in mapping_cache:
            if key in seen:
                raise DeliverableError("retrieval-trace: circular duplicate mapping")
            seen.add(key)
            trail.append(key)
            number, review = reviews.get(key, (None, {}))
            if review.get("decision") == "include":
                if (
                    review.get("linked_work_id"),
                    review.get("linked_version_id"),
                ) not in pairs:
                    raise DeliverableError(
                        "retrieval-trace: included work/version differs"
                    )
                mapping_cache[key] = (number, review)
                break
            if review.get("decision") != "duplicate":
                mapping_cache[key] = (None, {})
                break
            prior = review.get("repeat_of")
            if prior not in originals or originals[key].get(
                "url_observed"
            ) != originals[prior].get("url_observed"):
                raise DeliverableError("retrieval-trace: duplicate URL differs")
            key = prior
        anchor = mapping_cache[key]
        for item in trail:
            mapping_cache[item] = anchor
        return anchor

    matches = []
    saved_ledger = (
        index.get("original_record_recovery", {})
        .get("payload", {})
        .get("saved_search_ledger")
    )
    batch_contexts = (
        {row["batch_ref"]: row for row in saved_ledger["batches"]}
        if saved_ledger
        else {}
    )
    for number, observation in enumerate(observations):
        key = observation["observation_ref"]
        review_number, _ = reviews.get(key, (None, {}))
        anchor_number, review = linked_review(key)
        if review.get("linked_work_id") == work_id:
            matches.append(
                dict(
                    observation=deepcopy(observation),
                    linked_version_id=review.get("linked_version_id"),
                    mapping_basis=review.get("mapping_basis"),
                    observation_pointer=f"/original_record_recovery/payload/new_candidate_screening/observations/{number}",
                    mapping_pointer=f"/original_record_recovery/payload/new_candidate_screening/value/rows/{anchor_number}",
                    observation_review_pointer=f"/original_record_recovery/payload/new_candidate_screening/value/rows/{review_number}",
                )
            )
            if saved_ledger:
                matches[-1]["batch_context"] = deepcopy(
                    batch_contexts[observation["batch_ref"]]
                )
    batches = list(dict.fromkeys(m["observation"]["batch_ref"] for m in matches))
    base.update(
        mode="saved-observations-only",
        status="recorded-in-saved-scope" if matches else "not-recorded",
        count_scope="recovered-saved-observations-only",
        query_history_scope="not-recorded",
        counts=None,
        saved_observation_count=len(matches) if matches else None,
        distinct_saved_batch_count=len(batches) if matches else None,
        saved_batch_refs=batches,
        first_saved_batch_by_inventory_order=batches[0] if batches else None,
        observations=matches,
        source_pointers=[m["mapping_pointer"] for m in matches],
        unknown_reasons=[
            "actual-search-rounds-not-recorded",
            "query-to-work-assignment-not-recorded",
            "search-backend-attempts-not-recorded",
            "complete-historical-search-order-not-recorded",
        ]
        + ([] if matches else ["no-linked-observation-in-recovered-saved-scope"]),
        scope_note="Saved appearances and inventory order are not search rounds, chronological first discovery, API retries or full historical search counts. A saved header links a work, not an authenticated historical edition. No linked observation means not recorded, never zero searches.",
    )
    if saved_ledger:
        base["batch_context_contract_version"] = saved_ledger["contract_version"]
        base["scope_note"] += (
            " Independently pinned batch context supplies recorded batch timestamps and query parameters only; it does not assign a query or discovery time to this work. Original observations and their review hashes are unchanged."
        )
    return base


def derive_retrieval_trace(index):
    from .projection import validate_index

    validate_index(index)
    return dict(
        kind="Stage1RetrievalTrace",
        contract_version=CONTRACT,
        input_canonical_sha256=sha(canonical(index)),
        records_sha256=index["provenance"]["records_sha256"],
        rows=[work_trace(index, p["work_id"]) for p in index["papers"]],
        research_execution=False,
        scientific_assessment=False,
    )

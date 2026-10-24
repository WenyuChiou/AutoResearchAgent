"""Descriptive ordinal, base-case summaries; never a formal paired decision."""

from collections import Counter, defaultdict

from .campaign import POLICY, inspect_campaign, pinned
from .campaign_records import inspect_receipt
from .contracts import Stage3Error
from .preparation import CRITERIA, closed


def summarize_campaign(root, *, expected_sha256, index, expected_index_sha256):
    manifest = inspect_campaign(root, expected_sha256=expected_sha256)["manifest"]
    value = pinned({"path": str(index), "sha256": expected_index_sha256})
    closed(
        value,
        {
            "kind",
            "schema_version",
            "campaign_sha256",
            "receipts",
            "human_interventions",
        },
        "campaign index",
    )
    if (
        value["kind"] != "Stage3CampaignIndex"
        or value["schema_version"] != "1.0.0"
        or value["campaign_sha256"] != expected_sha256
        or not isinstance(value["receipts"], list)
    ):
        raise Stage3Error("campaign index version/binding mismatch")
    if value["human_interventions"] is not None and (
        type(value["human_interventions"]) is not int
        or value["human_interventions"] < 0
    ):
        raise Stage3Error("human interventions must be a nonnegative count or null")
    records, receipts = {}, {}
    for ref in value["receipts"]:
        receipt, record = inspect_receipt(ref, manifest, expected_sha256)
        key = receipt["unit_id"]
        if key in receipts:
            raise Stage3Error("duplicate indexed unit")
        receipts[key], records[key] = receipt, record
    grouped = defaultdict(dict)
    counts = defaultdict(Counter)
    criterion_counts = defaultdict(lambda: defaultdict(Counter))
    for unit in manifest["units"]:
        receipt, record = receipts.get(unit["unit_id"]), records.get(unit["unit_id"])
        state = receipt["status"] if receipt else "not-run"
        counts[unit["role"]][state] += 1
        if record and record["record_status"] == "recorded":
            for dimension, row in record["score_vector"].items():
                criterion_counts[unit["role"]][dimension][row["status"]] += 1
        grouped[(unit["case_id"], unit["repeat"], unit["arm"])][unit["role"]] = (
            unit,
            record,
        )
    subjects, audit_pending = {}, 0
    for key, roles in grouped.items():
        unit = roles["R1"][0]
        rows = {
            role: record
            for role, (_, record) in roles.items()
            if record and record["record_status"] == "recorded"
        }
        disagreement = (
            "R1" in rows
            and "R2" in rows
            and rows["R1"]["score_vector"] != rows["R2"]["score_vector"]
        )
        selected = (
            rows.get("ADJ")
            if disagreement
            else rows.get("R1")
            if "R2" in rows
            else None
        )
        unexpected = not disagreement and "ADJ" in rows
        if unexpected:
            selected = None
        scores = (
            selected["score_vector"]
            if selected
            else {d: {"status": "not-run", "score": None} for d in CRITERIA}
        )
        pending = set()
        for trigger in manifest["definition"]["analysis"]["audit_triggers"]:
            if trigger == "disagreement" and disagreement:
                pending.add(trigger)
            for record in rows.values():
                if any(
                    (trigger == row["status"])
                    or (trigger == "score-zero" and row["score"] == 0)
                    for row in record["score_vector"].values()
                ):
                    pending.add(trigger)
        audit_pending += bool(pending)
        subjects[key] = {
            "case_id": key[0],
            "repeat": key[1],
            "arm": key[2],
            "source_scope": unit["source_scope"],
            "subject_status": "failed"
            if unit["failure"]
            else "saved"
            if unit["request"]
            else "not-run",
            "score_vector": scores,
            "roles_recorded": sorted(rows),
            "disagreement": disagreement,
            "adjudication": "unexpected"
            if unexpected
            else "recorded"
            if disagreement and "ADJ" in rows
            else "pending"
            if disagreement
            else "not-required",
            "audit_pending": sorted(pending),
            "independence": "unverified",
        }
    dimensions = {}
    definition = manifest["definition"]
    for dimension in CRITERIA:
        pair_counts, by_base = Counter(), defaultdict(list)
        for case in definition["cases"]:
            for repeat in range(1, definition["repetitions"] + 1):
                pair = [
                    subjects[(case["case_id"], repeat, arm)]["score_vector"][dimension]
                    for arm in ("A", "B")
                ]
                if any(
                    row["status"] != "scored" or row["score"] is None for row in pair
                ):
                    outcome = "incomplete"
                else:
                    a, b = (row["score"] for row in pair)
                    outcome = "win" if b > a else "loss" if b < a else "tie"
                pair_counts[outcome] += 1
                by_base[case["base_case_id"]].append(outcome)
        base_counts = Counter()
        for outcomes in by_base.values():
            kinds = set(outcomes)
            outcome = (
                "incomplete"
                if "incomplete" in kinds
                else "mixed"
                if {"win", "loss"} <= kinds
                else "win"
                if "win" in kinds
                else "loss"
                if "loss" in kinds
                else "tie"
            )
            base_counts[outcome] += 1
        dimensions[dimension] = {
            "planned_pairs": sum(pair_counts.values()),
            "observed_scored_pairs": sum(
                pair_counts[k] for k in ("win", "loss", "tie")
            ),
            "pair_outcomes": dict(pair_counts),
            "planned_independent_base_cases": len(by_base),
            "base_case_outcomes": dict(base_counts),
        }
    return {
        "kind": "Stage3CampaignSummary",
        "schema_version": "1.0.0",
        "campaign_sha256": expected_sha256,
        "index_sha256": expected_index_sha256,
        "dimensions": dimensions,
        "subjects": list(subjects.values()),
        "role_record_states": {k: dict(v) for k, v in counts.items()},
        "criterion_record_states": {
            role: {
                dimension: dict(criterion_counts[role][dimension])
                for dimension in CRITERIA
            }
            for role in definition["roles"]
        },
        "failed_receipts": [
            {"unit_id": r["unit_id"], "raw": r["raw"], "error": r["error"]}
            for r in receipts.values()
            if r["status"] == "failed"
        ],
        "receipt_bindings": value["receipts"],
        "subject_failures": sum(
            s["subject_status"] == "failed" for s in subjects.values()
        ),
        "subject_not_run": sum(
            s["subject_status"] == "not-run" for s in subjects.values()
        ),
        "audit_pending_subjects": audit_pending,
        "human_interventions": value["human_interventions"],
        "tokens": None,
        "cost": None,
        "calibration": "not-run",
        "usable_for_formal_pairing": False,
        "policy": POLICY,
    }

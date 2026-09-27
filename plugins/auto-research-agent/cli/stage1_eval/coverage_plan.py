"""Lossless, bounded routing obligations; planning is not completed judging."""

import argparse
import json
from pathlib import Path

from .common import EvaluationError, canonical, load_rubric, read_json, sha, write_json
from .judging import CONTENT_IDS, PROCESS_IDS
from .spans import index_evidence

KIND = "Stage1CriterionCoveragePlan.v1"
SIZED_KIND = "Stage1CriterionCoveragePlan.v2"
MAX_UNIT_BYTES = 60_000
CONTEXT_SPANS = 1


def _unit_rows(index, assigned, context):
    return {key: index[key] for key in [*context, *assigned]}


def _partition(index, budget):
    """Account for serialized bindings as well as text, without top-k selection."""
    ordered = sorted(
        index,
        key=lambda key: (
            index[key]["evidence_id"],
            index[key]["view"],
            index[key]["start"],
            key,
        ),
    )
    units = []
    assigned, context = [], []
    for key in ordered:
        proposed = [*assigned, key]
        if len(canonical(_unit_rows(index, proposed, context))) > budget:
            if not assigned:
                raise EvaluationError(
                    "coverage: a span plus context exceeds unit budget"
                )
            units.append((assigned, context))
            previous = assigned[-CONTEXT_SPANS:]
            # Neighbour context is meaningful only within the same located view.
            context = [
                span
                for span in previous
                if (index[span]["evidence_id"], index[span]["view"])
                == (index[key]["evidence_id"], index[key]["view"])
            ]
            assigned = []
            if len(canonical(_unit_rows(index, [key], context))) > budget:
                raise EvaluationError(
                    "coverage: a span plus context exceeds unit budget"
                )
        assigned.append(key)
    if assigned:
        units.append((assigned, context))
    return units


def build_coverage_plan(
    packet, phase, *, max_unit_bytes=MAX_UNIT_BYTES, span_characters=900
):
    """Every phase span has exactly one primary unit, including raw envelopes.

    No condition label or path heuristic decides relevance. Decoded output is an
    additional view: it cannot replace raw native arguments, status or failures.
    """
    if phase not in {"content", "process"}:
        raise EvaluationError("coverage: invalid phase")
    if type(max_unit_bytes) is not int or not 4_000 <= max_unit_bytes <= MAX_UNIT_BYTES:
        raise EvaluationError("coverage: invalid serialized-evidence budget")
    if type(span_characters) is not int or not 100 <= span_characters <= 900:
        raise EvaluationError("coverage: invalid span character limit")
    index = index_evidence(packet[phase + "_evidence"], span_characters=span_characters)
    criteria = sorted(CONTENT_IDS if phase == "content" else PROCESS_IDS)
    _, rubric_sha = load_rubric()
    units = []
    for assigned, context in _partition(index, max_unit_bytes):
        binding = {
            "phase": phase,
            "criterion_ids": criteria,
            "assigned_span_ids": assigned,
            "context_span_ids": context,
            "input_sha256": sha(canonical(_unit_rows(index, assigned, context))),
        }
        units.append({"unit_id": "coverage-" + sha(canonical(binding)), **binding})
    expected = [row["unit_id"] for row in units]
    plan = {
        "kind": KIND,
        "schema_version": "1.0.0",
        "phase": phase,
        "rubric_sha256": rubric_sha,
        "span_index_sha256": sha(canonical(index)),
        "max_unit_bytes": max_unit_bytes,
        "context_spans": CONTEXT_SPANS,
        "units": units,
        "criteria": {
            criterion: {"expected_unit_ids": expected.copy()} for criterion in criteria
        },
        "span_count": len(index),
        "excluded_spans": [],
        "scope": "Routing only; no model submissions, semantic judgments or scores.",
    }
    if span_characters != 900:
        plan.update(
            kind=SIZED_KIND, schema_version="2.0.0", span_characters=span_characters
        )
    return index, plan


def verify_coverage_plan(packet, plan):
    """Reconstruct from authoritative packet bytes, not author-written totals."""
    if not isinstance(plan, dict) or plan.get("kind") not in {KIND, SIZED_KIND}:
        raise EvaluationError("coverage: unsupported plan contract")
    index, expected = build_coverage_plan(
        packet,
        plan.get("phase"),
        max_unit_bytes=plan.get("max_unit_bytes"),
        span_characters=plan.get("span_characters", 900),
    )
    if canonical(plan) != canonical(expected):
        raise EvaluationError(
            "coverage: plan differs from full reconstructed obligations"
        )
    return index


def pending_manifest(packet, plan):
    """A planned route must never be reported as actual completed model reading."""
    verify_coverage_plan(packet, plan)
    return {
        "kind": "Stage1CriterionCoverageManifest.v1",
        "schema_version": "1.0.0",
        "plan_sha256": sha(canonical(plan)),
        "status": "pending",
        "criteria": {
            key: {
                **value,
                "completed_unit_ids": [],
                "pending_unit_ids": value["expected_unit_ids"].copy(),
                "error_unit_ids": [],
            }
            for key, value in plan["criteria"].items()
        },
        "scope": "Planned units only; all actual submissions and validated outputs remain pending.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--phase", choices=("content", "process"), required=True)
    args = parser.parse_args(argv)
    try:
        packet = read_json(args.packet)
        index, plan = build_coverage_plan(packet, args.phase)
        pending = pending_manifest(packet, plan)
        # A diagnosis cannot overwrite an earlier plan or pretend to resume calls.
        args.output.mkdir(parents=True, exist_ok=False)
        write_json(args.output / "span-index.json", index)
        write_json(args.output / "coverage-plan.json", plan)
        write_json(args.output / "coverage-manifest.json", pending)
        print(
            json.dumps(
                {"status": "pending", "spans": len(index), "units": len(plan["units"])}
            )
        )
        return 0
    except (EvaluationError, OSError, KeyError, TypeError, ValueError) as error:
        print(json.dumps({"status": "evaluator-error", "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Complete content submissions, complete P3 execution and separate issue review.

Content units receive every content span. Oversized inputs are evaluator errors,
never a hidden top-k view or subject omission. Native calls own offline replay.
"""

from copy import deepcopy
from pathlib import Path

from .common import EvaluationError, canonical, sha
from .judging import CONTENT_IDS, _signature
from .judging_v31 import (
    _audit_signature,
    _prompt,
    check_grounding,
    unit_schema,
    unknown_criteria,
)
from .spans import index_evidence, model_span_aliases, restore_passages
from .source_audit_views import _audit_manifest, _observations
from .units import run_unit

MAX_COMPLETE_PROMPT_BYTES = 240_000
MAX_CORE_ASSESSMENT_BYTES = 4_000
MAX_REVIEW_BYTES = 30_000
PREFLIGHT_CORE_SERIALIZATION_MARGIN = 3_000
PREFLIGHT_REVIEW_SERIALIZATION_MARGIN = 20_000
CONCLUSION_CODES = {
    None: "unverifiable",
    0: "does-not-meet-anchor",
    1: "partially-meets-anchor",
    2: "meets-anchor",
}
MISSING_CODES = [
    "source-unavailable",
    "platform-field-unavailable",
    "subject-omission",
    "identity-ambiguous",
    "extraction-incomplete",
    "other-specified",
]


def _view(packet, phase):
    index = index_evidence(packet[phase + "_evidence"])
    aliases, binding = model_span_aliases(index)
    manifest = {
        "kind": "Stage1CompleteJudgeView.v1",
        "phase": phase,
        "span_index_sha256": sha(canonical(index)),
        "expected_span_ids": sorted(index),
        "planned_span_ids": sorted(index),
        "omitted_span_ids": [],
        "truncated": False,
        "alias_bindings": binding,
    }
    return aliases, manifest


def _maximum_core_assessment(work_id):
    """Build a prompt-only row at the accepted per-assessment byte ceiling."""
    row = {
        "work_id": work_id,
        "topic_core": "unverifiable",
        "classic": "unverifiable",
        "closest": "supported",
        "requirement_ids": [],
        "roles": [],
        "contribution": "",
        "decision_effect": "",
        "omission_consequence": "",
        "substitute_rationale": "",
        "passages": [],
        "uncertainty": "",
    }
    planned_bytes = MAX_CORE_ASSESSMENT_BYTES + PREFLIGHT_CORE_SERIALIZATION_MARGIN
    padding = planned_bytes - len(canonical(row))
    if padding < 0:
        raise EvaluationError("work identity exceeds complete judge core budget")
    row["uncertainty"] = "X" * padding
    while len(canonical(row)) > planned_bytes:
        row["uncertainty"] = row["uncertainty"][:-1]
    return row


def _maximum_review():
    """Build a prompt-only envelope larger than any accepted issue review."""
    return {
        "omission_assessments": [],
        "major_issues": [],
        "preflight_padding": "X"
        * (MAX_REVIEW_BYTES + PREFLIGHT_REVIEW_SERIALIZATION_MARGIN),
    }


def _prepare_call(
    packet,
    phase,
    kind,
    core,
    prior,
    audits,
    *,
    criterion=None,
    review=None,
    role="r1",
):
    index, manifest = _view(packet, phase)
    supplied = _observations(
        audits,
        {w["work_id"] for w in packet["extraction"]["works"]}
        if kind == "core"
        else None,
    )
    audit_manifest = _audit_manifest(audits, supplied, role, phase, prior)
    manifest["source_audit_view_manifest"] = audit_manifest
    schema = unit_schema("core" if kind == "core" else phase, index)
    schema["properties"]["criteria"].update(
        minItems=1 if criterion else 0, maxItems=1 if criterion else 0
    )
    if criterion:
        properties = schema["properties"]["criteria"]["items"]
        properties["required"] += ["conclusion_code", "missing_evidence_codes"]
        properties["properties"].update(
            conclusion_code={
                "type": "string",
                "enum": [*CONCLUSION_CODES.values(), "not-applicable"],
            },
            missing_evidence_codes={
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "enum": MISSING_CODES},
            },
        )
    needs = sorted(row["need_id"] for row in packet["spec"]["draft"]["needs"])
    if criterion and criterion.startswith("P2"):
        schema["required"].append("addressed_need_ids")
        schema["properties"]["addressed_need_ids"] = {
            "type": "array",
            "uniqueItems": True,
            "minItems": len(needs),
            "maxItems": len(needs),
            "items": {"type": "string", "enum": needs or ["no-applicable-needs"]},
        }
    prompt = _prompt(
        packet,
        phase,
        {
            key: {
                field: row.get(field)
                for field in (
                    "text",
                    "origin",
                    "view",
                    "work_id",
                    "evidence_id",
                    "source_version",
                    "locator",
                )
            }
            for key, row in index.items()
        },
        {
            "phase": phase,
            "span_count": len(index),
            "omitted_span_count": 0,
            "truncated": False,
            "source_audit_view_manifest": audit_manifest,
        },
        kind,
        core,
        prior,
        supplied,
        criterion_id=criterion,
        review=review,
    )
    return {
        "index": index,
        "manifest": manifest,
        "audit_manifest": audit_manifest,
        "schema": schema,
        "needs": needs,
        "prompt": prompt,
        "prompt_bytes": len(prompt.encode("utf-8")),
    }


def _call(
    packet,
    phase,
    kind,
    core,
    prior,
    audits,
    root,
    label,
    options,
    replay_only,
    *,
    criterion=None,
    review=None,
    role="r1",
):
    from .pipeline_v31 import persist

    prepared = _prepare_call(
        packet,
        phase,
        kind,
        core,
        prior,
        audits,
        criterion=criterion,
        review=review,
        role=role,
    )
    index = prepared["index"]
    manifest = prepared["manifest"]
    audit_manifest = prepared["audit_manifest"]
    schema = prepared["schema"]
    needs = prepared["needs"]
    prompt = prepared["prompt"]
    if prepared["prompt_bytes"] > MAX_COMPLETE_PROMPT_BYTES:
        raise EvaluationError(
            "complete judge input exceeds frozen prompt budget; no evidence was omitted"
        )
    path = root / (label + ".schema.json")
    persist(path, schema, replay_only=replay_only)
    persist(root / (label + ".view.json"), manifest, replay_only=replay_only)

    def normalize(raw):
        value = restore_passages(deepcopy(raw), index)
        addressed = value.pop("addressed_need_ids", None)
        if (
            criterion
            and criterion.startswith("P2")
            and (addressed is None or sorted(addressed) != needs)
        ):
            raise EvaluationError(
                "complete criterion did not address every frozen need"
            )
        if kind == "core":
            if (
                value["criteria"]
                or value["omission_assessments"]
                or value["major_issues"]
            ):
                raise EvaluationError("core unit contains unrelated judgments")
            value["criteria"] = unknown_criteria("content")
            rows = check_grounding(value, packet, "content")["core_assessments"]
            if any(len(canonical(row)) > MAX_CORE_ASSESSMENT_BYTES for row in rows):
                raise EvaluationError("complete core assessment exceeds byte budget")
            return rows
        if value["core_assessments"]:
            raise EvaluationError(
                "complete unit cannot replace assigned core assessments"
            )
        value["core_assessments"] = deepcopy(core)
        if criterion:
            if [r["criterion_id"] for r in value["criteria"]] != [criterion]:
                raise EvaluationError("complete unit returned a different criterion")
            if value["major_issues"] or value["omission_assessments"]:
                raise EvaluationError("criterion cannot replace assigned issue review")
            row = value["criteria"][0]
            conclusion = row.pop("conclusion_code")
            missing = row.pop("missing_evidence_codes")
            expected = (
                "not-applicable"
                if row["status"] == "not-applicable"
                else CONCLUSION_CODES[row["score"]]
            )
            if conclusion != expected or bool(missing) != bool(row["missing_evidence"]):
                raise EvaluationError(
                    "criterion conclusion or missingness codes contradict verdict"
                )
            value["criteria"] = [
                row if r["criterion_id"] == criterion else r
                for r in unknown_criteria(phase)
            ]
            value.update(deepcopy(review))
            check_grounding(value, packet, phase)
            return {
                "criterion": row,
                "conclusion_code": conclusion,
                "missing_evidence_codes": sorted(missing),
                "addressed_need_ids": addressed,
            }
        if value["criteria"]:
            raise EvaluationError("issue review cannot award criterion scores")
        value["criteria"] = unknown_criteria(phase)
        check_grounding(value, packet, phase)
        review_value = {
            key: value[key] for key in ("omission_assessments", "major_issues")
        }
        if len(canonical(review_value)) > MAX_REVIEW_BYTES:
            raise EvaluationError("complete issue review exceeds byte budget")
        return review_value

    value, native = run_unit(
        prompt,
        path,
        root / "model-logs",
        label,
        options,
        normalize,
        replay_only=replay_only,
        max_prompt_bytes=MAX_COMPLETE_PROMPT_BYTES,
    )
    record = {
        "view": manifest,
        "source_audit_view_manifest": audit_manifest,
        "native": native,
        "value": value,
        "prompt_sha256": sha(prompt.encode("utf-8")),
        "coverage": {
            "status": "complete",
            "submitted_span_ids": manifest["planned_span_ids"],
            "omitted_span_ids": [],
        },
    }
    persist(root / (label + ".result.json"), record, replay_only=replay_only)
    return value, record


def _content_batches(packet):
    works = packet["extraction"]["works"]
    for offset in range(0, len(works), 4):
        subpacket = deepcopy(packet)
        subpacket["extraction"]["works"] = works[offset : offset + 4]
        ids = {w["work_id"] for w in subpacket["extraction"]["works"]}
        subpacket["extraction"]["central_claims"] = [
            claim
            for claim in packet["extraction"]["central_claims"]
            if ids.intersection(claim["cited_work_ids"])
        ]
        yield offset // 4 + 1, subpacket


def _preflight_content_role(packet, root, audits, role, prior, replay_only):
    """Validate a whole role before its first native call and persist the plan."""
    from .pipeline_v31 import persist

    plans = []
    maximum_core = []
    for number, subpacket in _content_batches(packet):
        label = f"content-{role}-core-{number:03d}"
        prepared = _prepare_call(
            subpacket, "content", "core", [], prior, audits, role=role
        )
        maximum_core.extend(
            _maximum_core_assessment(row["work_id"])
            for row in subpacket["extraction"]["works"]
        )
        plans.append((label, prepared))
    prepared_review = _prepare_call(
        packet, "content", "review", maximum_core, prior, audits, role=role
    )
    plans.append((f"content-{role}-review", prepared_review))
    maximum_review = _maximum_review()
    for criterion in sorted(CONTENT_IDS):
        prepared = _prepare_call(
            packet,
            "content",
            "content",
            maximum_core,
            prior,
            audits,
            criterion=criterion,
            review=maximum_review,
            role=role,
        )
        plans.append((f"content-{role}-{criterion}", prepared))
    receipt_plans = [
        {
            "label": label,
            "prompt_bytes_upper_bound": prepared["prompt_bytes"],
            "prompt_upper_bound_sha256": sha(prepared["prompt"].encode("utf-8")),
            "schema_sha256": sha(canonical(prepared["schema"])),
            "view_sha256": sha(canonical(prepared["manifest"])),
            "source_audit_view_sha256": prepared["audit_manifest"][
                "supplied_view_sha256"
            ],
        }
        for label, prepared in plans
    ]
    oversize = [
        row["label"]
        for row in receipt_plans
        if row["prompt_bytes_upper_bound"] > MAX_COMPLETE_PROMPT_BYTES
    ]
    receipt = {
        "kind": "Stage1CompleteJudgeRolePreflight.v1",
        "role": role.upper(),
        "status": "failed" if oversize else "passed",
        "prompt_byte_limit": MAX_COMPLETE_PROMPT_BYTES,
        "accepted_intermediate_byte_limits": {
            "core_assessment": MAX_CORE_ASSESSMENT_BYTES,
            "issue_review": MAX_REVIEW_BYTES,
        },
        "serialization_margins": {
            "per_core_assessment": PREFLIGHT_CORE_SERIALIZATION_MARGIN,
            "issue_review": PREFLIGHT_REVIEW_SERIALIZATION_MARGIN,
        },
        "plans": receipt_plans,
        "oversize_unit_ids": oversize,
        "error_code": "complete-role-prompt-budget-exceeded" if oversize else None,
        "score_awarded": False,
    }
    persist(root / f"content-{role}-preflight.json", receipt, replay_only=replay_only)
    if oversize:
        raise EvaluationError(
            "complete judge role exceeds frozen prompt budget before native calls; "
            "no evidence was omitted"
        )
    return receipt


def _content(packet, root, options, audits, replay_only):
    roles, records, semantics = {}, {}, {}
    for role in ("r1", "r2", "adj"):
        if role == "adj" and (
            _signature(roles["r1"]) == _signature(roles["r2"])
            and _audit_signature(audits["r1"]) == _audit_signature(audits["r2"])
            and semantics["r1"] == semantics["r2"]
        ):
            break
        prior = (
            {
                name: {**value, "semantic_conclusions": semantics[name]}
                for name, value in roles.items()
            }
            if role == "adj"
            else None
        )
        audit = audits if role == "adj" else {role: audits[role]}
        _preflight_content_role(packet, root, audit, role, prior, replay_only)
        core = []
        for number, subpacket in _content_batches(packet):
            label = f"content-{role}-core-{number:03d}"
            value, records[label] = _call(
                subpacket,
                "content",
                "core",
                [],
                prior,
                audit,
                root,
                label,
                options,
                replay_only,
                role=role,
            )
            core.extend(value)
        label = f"content-{role}-review"
        review, records[label] = _call(
            packet,
            "content",
            "review",
            core,
            prior,
            audit,
            root,
            label,
            options,
            replay_only,
            role=role,
        )
        criteria = []
        semantics[role] = {}
        for key in sorted(CONTENT_IDS):
            label = f"content-{role}-{key}"
            row, records[label] = _call(
                packet,
                "content",
                "content",
                core,
                prior,
                audit,
                root,
                label,
                options,
                replay_only,
                criterion=key,
                review=review,
                role=role,
            )
            criteria.append(row["criterion"])
            semantics[role][key] = (
                row["conclusion_code"],
                row["missing_evidence_codes"],
            )
        roles[role] = check_grounding(
            {"criteria": criteria, "core_assessments": core, **review},
            packet,
            "content",
        )
    return roles.get("adj", roles["r1"]), records, "adj" in roles


def _process(packet, root, options, replay_only):
    from .criterion_execution import judge_process_complete

    complete = judge_process_complete(
        packet, root / "criteria", options, replay_only=replay_only
    )
    rows = []
    for key, result in complete.items():
        chosen = result["roles"][result["selected_role"]]
        passages = {}
        for node in chosen["nodes"].values():
            for observation in node["value"]["observations"]:
                if observation["disposition"] != "irrelevant":
                    span = observation["passage"]
                    passage = {
                        "evidence_id": span["evidence_id"],
                        "exact_quote": span["text"],
                    }
                    passages[sha(canonical(passage))] = passage
        verdict = chosen["verdict"]
        rows.append(
            {
                "criterion_id": key,
                **{
                    k: verdict[k]
                    for k in ("status", "score", "reason", "missing_evidence")
                },
                "passages": list(passages.values()),
            }
        )
    roles, records = {}, {"complete_criteria": complete}
    for role in ("r1", "r2", "adj"):
        if role == "adj" and _signature(roles["r1"]) == _signature(roles["r2"]):
            break
        label = "process-" + role + "-review"
        review, records[label] = _call(
            packet,
            "process",
            "review",
            [],
            roles if role == "adj" else None,
            None,
            root,
            label,
            options,
            replay_only,
            role=role,
        )
        roles[role] = {"criteria": deepcopy(rows), "core_assessments": [], **review}
    selected = check_grounding(roles.get("adj", roles["r1"]), packet, "process")
    return (
        selected,
        records,
        "adj" in roles or any(r["selected_role"] == "adj" for r in complete.values()),
    )


def judge_packet_complete(
    packet, output_dir, model_options, *, replay_only=False, source_audits
):
    from .pipeline_v31 import persist

    if set(source_audits) != {"r1", "r2"}:
        raise EvaluationError("complete judging needs both independent source audits")
    root = Path(output_dir)
    selected, provenance, adjudicated = {}, {}, []
    for phase, execute in (("content", _content), ("process", _process)):
        args = (source_audits, replay_only) if phase == "content" else (replay_only,)
        value, records, did_adjudicate = execute(
            packet, root / phase, model_options, *args
        )
        selected[phase], provenance[phase] = value, records
        if did_adjudicate:
            adjudicated.append(phase)
    result = {
        "selected": selected,
        "provenance": provenance,
        "adjudicated_phases": adjudicated,
    }
    persist(root / "result.json", result, replay_only=replay_only)
    return result

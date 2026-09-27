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
    _audit_view,
    _prompt,
    check_grounding,
    unit_schema,
    unknown_criteria,
)
from .spans import index_evidence, model_span_aliases, restore_passages
from .units import run_unit

MAX_COMPLETE_PROMPT_BYTES = 240_000
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


def _observations(audits, work_ids=None):
    """Omit transport receipts, never audit conclusions or original source text."""
    selected = _audit_view(audits, work_ids)
    if selected is None:
        return None
    for audit in selected.values():
        audit["summaries"] = [
            {key: row[key] for key in ("target", "verdict", "unknown_reason")}
            for row in audit["summaries"]
        ]
        for leaf in audit["leaves"]:
            value = leaf["value"]
            leaf["value"] = {
                "verdict": value["verdict"],
                "reason": value["reason"],
                "passages": [
                    {
                        key: row.get(key)
                        for key in (
                            "evidence_id",
                            "view",
                            "start",
                            "end",
                            "source_level",
                        )
                    }
                    for row in value["passages"]
                ],
            }
    return selected


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
):
    from .pipeline_v31 import persist

    index, manifest = _view(packet, phase)
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
        },
        kind,
        core,
        prior,
        audits,
        criterion_id=criterion,
        review=review,
    )
    if len(prompt.encode("utf-8")) > MAX_COMPLETE_PROMPT_BYTES:
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
            return check_grounding(value, packet, "content")["core_assessments"]
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
        return {key: value[key] for key in ("omission_assessments", "major_issues")}

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
        core = []
        works = packet["extraction"]["works"]
        for offset in range(0, len(works), 4):
            subpacket = deepcopy(packet)
            subpacket["extraction"]["works"] = works[offset : offset + 4]
            ids = {w["work_id"] for w in subpacket["extraction"]["works"]}
            subpacket["extraction"]["central_claims"] = [
                c
                for c in packet["extraction"]["central_claims"]
                if ids.intersection(c["cited_work_ids"])
            ]
            label = f"content-{role}-core-{offset // 4 + 1:03d}"
            value, records[label] = _call(
                subpacket,
                "content",
                "core",
                [],
                prior,
                _observations(audit, ids),
                root,
                label,
                options,
                replay_only,
            )
            core.extend(value)
        label = f"content-{role}-review"
        review, records[label] = _call(
            packet,
            "content",
            "review",
            core,
            prior,
            _observations(audit),
            root,
            label,
            options,
            replay_only,
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
                _observations(audit),
                root,
                label,
                options,
                replay_only,
                criterion=key,
                review=review,
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

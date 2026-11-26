"""Read-only, plan-bound C11 cells and mechanical specificity notices.

Pointers display the actual plan text; they neither verify real data nor judge
whether the method is scientifically adequate. Old plans are never upgraded.
"""

import re

from .contracts import Stage3Error, validate_plan


INDEX = r"(?:0|[1-9][0-9]*)"
GENERIC = {
    "use a method suited to the stated question",
    "prepare the evidence and design",
    "produce the bounded analysis artifacts",
    "todo",
    "待补",
}


def _cell(plan, pointer, pattern):
    if re.fullmatch(pattern, pointer) is None:
        raise Stage3Error("step pointer has the wrong role or noncanonical index")
    value = plan
    try:
        for token in pointer[1:].split("/"):
            value = value[int(token)] if isinstance(value, list) else value[token]
    except (KeyError, IndexError, ValueError, TypeError) as error:
        raise Stage3Error("step pointer does not exist in this plan") from error
    if not isinstance(value, str) or not value.strip():
        raise Stage3Error("step pointer must locate nonempty plan text")
    return {"location": pointer, "text": value}


def _design_scope(plan, milestone):
    by_id = {row["milestone_id"]: row for row in plan["milestones"]}
    pending = [milestone["milestone_id"]]
    seen, designs = set(), set()
    while pending:
        identity = pending.pop()
        if identity in seen or identity not in by_id:
            continue  # Complete graph errors are reported by check_plan.
        seen.add(identity)
        row = by_id[identity]
        designs.update(row["design_ids"])
        pending.extend(row["depends_on"])
    return designs


def _in_scope(plan, pointer, designs):
    collection, index, *_ = pointer[1:].split("/")
    row = plan[collection][int(index)]
    if collection == "designs":
        return row["design_id"] in designs
    if collection == "analyses":
        return bool(row["design_ids"]) and set(row["design_ids"]) <= designs
    if collection == "results":
        analyses = {a["analysis_id"]: a for a in plan["analyses"]}
        return bool(row["analysis_ids"]) and all(
            identity in analyses
            and bool(analyses[identity]["design_ids"])
            and set(analyses[identity]["design_ids"]) <= designs
            for identity in row["analysis_ids"]
        )
    questions = {
        q
        for d in plan["designs"]
        if d["design_id"] in designs
        for q in d["question_refs"]
    }
    if collection == "question_plans":
        return row["question_ref"] in questions
    if collection == "resources":
        return any(
            q["question_ref"] in questions
            and any(
                use["resource_id"] == row["resource_id"] for use in q["resource_uses"]
            )
            for q in plan["question_plans"]
        )
    return True  # Milestone fields are checked against their exact role below.


def step_diagnostics(plan):
    """Project validated plan cells; errors reject v1.2, warnings remain notices.

    Legacy plans expose absent cells as null, never guessed from generic prose.
    Call check_plan as well for the complete source, graph and condition contract.
    """
    validate_plan(plan)
    issues, warnings, steps = [], [], []
    for index, milestone in enumerate(plan["milestones"]):
        path = f"/milestones/{index}/step"
        row = {
            "milestone_id": milestone["milestone_id"],
            "depends_on": list(milestone["depends_on"]),
            "plan_location": path,
        }
        if plan["schema_version"] != "1.2.0":
            row.update(
                {
                    key: None
                    for key in (
                        "inputs",
                        "operation",
                        "outputs",
                        "success_criteria",
                        "named_entities",
                    )
                }
            )
            warnings.append(
                {
                    "code": "legacy-step-content-unrecorded",
                    "path": path,
                    "message": "Old plan has no four-cell step record; do not infer it.",
                }
            )
            steps.append(row)
            continue
        step = milestone["step"]
        designs = _design_scope(plan, milestone)
        patterns = {
            "inputs": rf"/(?:resources/{INDEX}/(?:minimum|standard|access_conditions|fitness)|milestones/{INDEX}/deliverable)",
            "operation": rf"/(?:designs/{INDEX}/procedure|analyses/{INDEX}/method|question_plans/{INDEX}/measurement|milestones/{index}/description)",
            "outputs": rf"/(?:results/{INDEX}/artifact|milestones/{index}/deliverable)",
            "success_criteria": rf"/(?:analyses/{INDEX}/criteria/{INDEX}|designs/{INDEX}/credibility_checks/{INDEX})",
        }
        cells = {}
        for field, pattern in patterns.items():
            values = [step[field]] if field == "operation" else step[field]
            resolved = []
            for pointer in values:
                try:
                    cell = _cell(plan, pointer, pattern)
                    if not _in_scope(plan, pointer, designs):
                        raise Stage3Error(
                            "step reference is outside this milestone design/dependency scope"
                        )
                    if field == "inputs" and pointer.startswith("/milestones/"):
                        predecessor = plan["milestones"][int(pointer.split("/")[2])]
                        if predecessor["milestone_id"] not in milestone["depends_on"]:
                            raise Stage3Error(
                                "step input is not a declared direct predecessor"
                            )
                    cells[pointer] = cell["text"]
                    resolved.append(cell)
                except Stage3Error as error:
                    issues.append(
                        {
                            "code": "step-reference-invalid",
                            "path": path + "/" + field,
                            "message": str(error),
                        }
                    )
            row[field] = (
                (resolved[0] if resolved else None)
                if field == "operation"
                else resolved
            )
        row["named_entities"] = [dict(entity) for entity in step["named_entities"]]
        for entity in step["named_entities"]:
            if (
                not entity["name"].strip()
                or entity["location"] not in cells
                or entity["name"] not in cells[entity["location"]]
            ):
                issues.append(
                    {
                        "code": "step-entity-unbound",
                        "path": path + "/named_entities",
                        "message": "Named entity must occur literally in a referenced step cell.",
                    }
                )
        if not step["named_entities"]:
            warnings.append(
                {
                    "code": "step-no-named-entity",
                    "path": path,
                    "message": "No file, dataset or metric is named; specificity needs review.",
                }
            )
        if (
            row["operation"]
            and row["operation"]["text"].strip().rstrip(".。").casefold() in GENERIC
        ):
            warnings.append(
                {
                    "code": "step-unspecific-operation",
                    "path": step["operation"],
                    "message": "Generic operation: state what to do with the actual input.",
                }
            )
        steps.append(row)
    return {
        "issues": issues,
        "warnings": warnings,
        "steps": steps,
        "execution_authorized": False,
        "scientific_quality": "not-assessed",
    }

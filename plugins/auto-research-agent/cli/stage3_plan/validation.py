"""Cross-reference and source-traceability checks for Stage 3 plans."""

from .contracts import Stage3Error, validate_plan


def _path(*parts):
    return "/" + "/".join(str(part) for part in parts)


def _issue(issues, code, path, message):
    issues.append({"code": code, "path": path, "message": message})


def _index(rows, key, label, issues, base_path):
    indexed = {}
    for position, row in enumerate(rows):
        value = row[key]
        if value in indexed:
            _issue(
                issues,
                "duplicate-id",
                _path(base_path, position, key),
                f"duplicate {label}: {value}",
            )
        else:
            indexed[value] = row
    return indexed


def _check_ref_list(rows, field, targets, target_label, issues, base_path):
    for position, row in enumerate(rows):
        for ref_position, reference in enumerate(row[field]):
            if reference not in targets:
                _issue(
                    issues,
                    "missing-reference",
                    _path(base_path, position, field, ref_position),
                    f"unknown {target_label}: {reference}",
                )


def _check_bidirectional(
    rows,
    row_id,
    row_refs,
    question_plans,
    plan_refs,
    issues,
    base_path,
):
    for position, row in enumerate(rows):
        identity = row[row_id]
        for ref_position, question_ref in enumerate(row[row_refs]):
            question_plan = question_plans.get(question_ref)
            if question_plan is not None and identity not in question_plan[plan_refs]:
                _issue(
                    issues,
                    "asymmetric-reference",
                    _path(base_path, position, row_refs, ref_position),
                    f"{identity} names {question_ref}, but its question plan does not name {identity}",
                )
    for question_ref, question_plan in question_plans.items():
        by_id = {row[row_id]: row for row in rows}
        for ref_position, identity in enumerate(question_plan[plan_refs]):
            row = by_id.get(identity)
            if row is not None and question_ref not in row[row_refs]:
                _issue(
                    issues,
                    "asymmetric-reference",
                    _path("question_plans", question_ref, plan_refs, ref_position),
                    f"{question_ref} names {identity}, but {identity} does not name the question",
                )


def _check_milestone_dag(milestones, milestone_by_id, issues):
    state = {}

    def visit(milestone_id, trail):
        if state.get(milestone_id) == "done":
            return
        if state.get(milestone_id) == "visiting":
            cycle = " -> ".join([*trail, milestone_id])
            _issue(
                issues,
                "milestone-cycle",
                "/milestones",
                f"milestone dependency cycle: {cycle}",
            )
            return
        state[milestone_id] = "visiting"
        for dependency in milestone_by_id[milestone_id]["depends_on"]:
            if dependency in milestone_by_id:
                visit(dependency, [*trail, milestone_id])
        state[milestone_id] = "done"

    for milestone in milestones:
        visit(milestone["milestone_id"], [])


def _intake_resources(intake):
    resources = {}
    for row in intake.get("resources", []):
        if not isinstance(row, dict):
            continue
        key = (
            row.get("candidate_id"),
            row.get("candidate_version"),
            row.get("resource_id"),
        )
        if all(value is not None for value in key):
            resources[key] = row
    return resources


def _intake_question_resource_fit(intake):
    fit = {}
    for entry in intake.get("scientific_arguments", []):
        candidate_id = entry.get("candidate_id")
        candidate_version = entry.get("candidate_version")
        argument = entry.get("argument", {})
        for resource_ref in argument.get("resource_refs", []):
            resource_id = resource_ref.get("resource_id")
            for question_id in resource_ref.get("question_ids", []):
                question_ref = f"{candidate_id}@{candidate_version}/{question_id}"
                fit.setdefault(question_ref, set()).add(resource_id)
    return fit


def _check_intake(
    plan,
    intake,
    questions,
    question_plans,
    resources,
    issues,
):
    if plan["source_manifest_sha256"] != intake.get("source_manifest_sha256"):
        _issue(
            issues,
            "source-mismatch",
            "/source_manifest_sha256",
            "plan source manifest does not match the admitted intake",
        )

    intake_selected = {
        (row.get("candidate_id"), row.get("candidate_version"))
        for row in intake.get("selected_candidates", [])
        if isinstance(row, dict)
    }
    plan_selected = {
        (row["candidate_id"], row["candidate_version"])
        for row in plan["selected_candidates"]
    }
    if plan_selected != intake_selected:
        _issue(
            issues,
            "source-mismatch",
            "/selected_candidates",
            "selected candidates differ from the admitted intake",
        )

    intake_questions = {
        row.get("question_ref"): row
        for row in intake.get("questions", [])
        if isinstance(row, dict) and isinstance(row.get("question_ref"), str)
    }
    immutable = (
        "candidate_id",
        "candidate_version",
        "question_id",
        "text",
        "priority",
        "gap_ids",
        "intended_claim",
    )
    if set(questions) != set(intake_questions):
        _issue(
            issues,
            "source-mismatch",
            "/questions",
            "question identities differ from the admitted intake",
        )
    for question_ref in set(questions) & set(intake_questions):
        source = intake_questions[question_ref]
        for field in immutable:
            if questions[question_ref][field] != source.get(field):
                _issue(
                    issues,
                    "immutable-question",
                    _path("questions", question_ref, field),
                    f"{question_ref} changes immutable source field {field}",
                )

    intake_resources = _intake_resources(intake)
    for resource_id, resource in resources.items():
        if resource["origin"] == "proposed":
            continue
        admitted = [
            row
            for (
                candidate_id,
                candidate_version,
                source_id,
            ), row in intake_resources.items()
            if source_id == resource_id
            and (candidate_id, candidate_version) in plan_selected
        ]
        if not admitted:
            _issue(
                issues,
                "source-resource-mismatch",
                _path("resources", resource_id),
                f"Stage 2 resource is absent from selected intake versions: {resource_id}",
            )
        elif resource["availability"] == "available" and any(
            row.get("status") != "available" for row in admitted
        ):
            _issue(
                issues,
                "resource-availability-promotion",
                _path("resources", resource_id, "availability"),
                f"Stage 3 cannot promote non-available Stage 2 resource {resource_id}",
            )

    fit = _intake_question_resource_fit(intake)
    for question_ref, question_plan in question_plans.items():
        allowed = fit.get(question_ref, set())
        for use_position, resource_use in enumerate(question_plan["resource_uses"]):
            resource_id = resource_use["resource_id"]
            resource = resources.get(resource_id)
            if resource is None or resource["origin"] == "proposed":
                continue
            question = questions.get(question_ref)
            source = (
                intake_resources.get(
                    (
                        question["candidate_id"],
                        question["candidate_version"],
                        resource_id,
                    )
                )
                if question is not None
                else None
            )
            if source is None:
                _issue(
                    issues,
                    "source-resource-mismatch",
                    _path(
                        "question_plans",
                        question_ref,
                        "resource_uses",
                        use_position,
                        "resource_id",
                    ),
                    f"resource {resource_id} is not admitted for {question_ref}",
                )
            if resource_id not in allowed:
                _issue(
                    issues,
                    "resource-question-fit",
                    _path(
                        "question_plans",
                        question_ref,
                        "resource_uses",
                        use_position,
                        "resource_id",
                    ),
                    f"intake does not bind {resource_id} to {question_ref}",
                )
            if (
                resource_use["status"] == "available"
                and source is not None
                and source.get("status") != "available"
            ):
                _issue(
                    issues,
                    "resource-availability-promotion",
                    _path(
                        "question_plans",
                        question_ref,
                        "resource_uses",
                        use_position,
                        "status",
                    ),
                    f"resource use cannot promote Stage 2 status {source.get('status')!r}",
                )


def _graph_issues(plan, intake=None):
    issues = []
    selected = set()
    for position, candidate in enumerate(plan["selected_candidates"]):
        key = (candidate["candidate_id"], candidate["candidate_version"])
        if key in selected:
            _issue(
                issues,
                "duplicate-id",
                _path("selected_candidates", position),
                f"duplicate selected candidate: {key[0]}@{key[1]}",
            )
        selected.add(key)

    questions = _index(
        plan["questions"], "question_ref", "question_ref", issues, "questions"
    )
    question_plans = _index(
        plan["question_plans"],
        "question_ref",
        "question plan",
        issues,
        "question_plans",
    )
    designs = _index(plan["designs"], "design_id", "design_id", issues, "designs")
    analyses = _index(
        plan["analyses"], "analysis_id", "analysis_id", issues, "analyses"
    )
    results = _index(plan["results"], "result_id", "result_id", issues, "results")
    resources = _index(
        plan["resources"], "resource_id", "resource_id", issues, "resources"
    )
    milestones = _index(
        plan["milestones"],
        "milestone_id",
        "milestone_id",
        issues,
        "milestones",
    )

    candidate_core_counts = {candidate: 0 for candidate in selected}
    for position, question in enumerate(plan["questions"]):
        candidate = (question["candidate_id"], question["candidate_version"])
        expected_ref = (
            f"{question['candidate_id']}@{question['candidate_version']}/"
            f"{question['question_id']}"
        )
        if question["question_ref"] != expected_ref:
            _issue(
                issues,
                "question-ref-mismatch",
                _path("questions", position, "question_ref"),
                f"question_ref must be {expected_ref}",
            )
        if candidate not in selected:
            _issue(
                issues,
                "unselected-candidate",
                _path("questions", position),
                f"question belongs to unselected candidate {candidate[0]}@{candidate[1]}",
            )
        elif question["priority"] == "core":
            candidate_core_counts[candidate] += 1
    for candidate, count in candidate_core_counts.items():
        if count == 0:
            _issue(
                issues,
                "missing-core-question",
                "/questions",
                f"selected candidate {candidate[0]}@{candidate[1]} has no core question",
            )

    if set(questions) != set(question_plans):
        for question_ref in sorted(set(questions) - set(question_plans)):
            _issue(
                issues,
                "missing-question-plan",
                "/question_plans",
                f"question has no plan: {question_ref}",
            )
        for question_ref in sorted(set(question_plans) - set(questions)):
            _issue(
                issues,
                "orphan-question-plan",
                _path("question_plans", question_ref),
                f"question plan has no question: {question_ref}",
            )

    _check_ref_list(
        plan["designs"], "question_refs", questions, "question", issues, "designs"
    )
    _check_ref_list(
        plan["analyses"], "question_refs", questions, "question", issues, "analyses"
    )
    _check_ref_list(
        plan["analyses"], "design_ids", designs, "design", issues, "analyses"
    )
    _check_ref_list(
        plan["results"], "question_refs", questions, "question", issues, "results"
    )
    _check_ref_list(
        plan["results"], "analysis_ids", analyses, "analysis", issues, "results"
    )
    _check_ref_list(
        plan["milestones"], "depends_on", milestones, "milestone", issues, "milestones"
    )
    _check_ref_list(
        plan["milestones"], "design_ids", designs, "design", issues, "milestones"
    )
    _check_ref_list(
        plan["unknowns"], "question_refs", questions, "question", issues, "unknowns"
    )

    _check_bidirectional(
        plan["designs"],
        "design_id",
        "question_refs",
        question_plans,
        "design_ids",
        issues,
        "designs",
    )
    _check_bidirectional(
        plan["analyses"],
        "analysis_id",
        "question_refs",
        question_plans,
        "analysis_ids",
        issues,
        "analyses",
    )
    _check_bidirectional(
        plan["results"],
        "result_id",
        "question_refs",
        question_plans,
        "result_ids",
        issues,
        "results",
    )

    blocking_question_refs = {
        question_plan["question_ref"]
        for question_plan in plan["question_plans"]
        if question_plan["blockers"]
    }
    for unknown in plan["unknowns"]:
        if unknown["blocking"]:
            blocking_question_refs.update(unknown["question_refs"])

    for question_ref, question_plan in question_plans.items():
        for field, index in (
            ("design_ids", designs),
            ("analysis_ids", analyses),
            ("result_ids", results),
        ):
            for target_id in question_plan[field]:
                if target_id not in index:
                    _issue(
                        issues,
                        "missing-reference",
                        _path("question_plans", question_ref, field),
                        f"unknown target: {target_id}",
                    )
        for use_position, resource_use in enumerate(question_plan["resource_uses"]):
            resource = resources.get(resource_use["resource_id"])
            if resource is None:
                _issue(
                    issues,
                    "missing-reference",
                    _path(
                        "question_plans",
                        question_ref,
                        "resource_uses",
                        use_position,
                        "resource_id",
                    ),
                    f"unknown resource: {resource_use['resource_id']}",
                )
            elif resource["origin"] == "proposed":
                if resource_use["status"] != "unknown":
                    _issue(
                        issues,
                        "proposed-resource-state",
                        _path(
                            "question_plans",
                            question_ref,
                            "resource_uses",
                            use_position,
                            "status",
                        ),
                        "proposed resource uses must remain unknown",
                    )
                if question_ref not in blocking_question_refs:
                    _issue(
                        issues,
                        "proposed-resource-unblocked",
                        _path("question_plans", question_ref, "blockers"),
                        "a proposed resource must block its affected question",
                    )

        blocked = bool(question_plan["blockers"])
        if not blocked and question_ref in questions:
            for field in ("design_ids", "analysis_ids", "result_ids"):
                if not question_plan[field]:
                    _issue(
                        issues,
                        "incomplete-question-path",
                        _path("question_plans", question_ref, field),
                        f"unblocked question requires at least one {field[:-4]}",
                    )

        for analysis_id in question_plan["analysis_ids"]:
            analysis = analyses.get(analysis_id)
            if analysis is None:
                continue
            linked_designs = [
                design_id
                for design_id in analysis["design_ids"]
                if design_id in question_plan["design_ids"]
                and question_ref in designs.get(design_id, {}).get("question_refs", [])
            ]
            if not linked_designs:
                _issue(
                    issues,
                    "broken-question-path",
                    _path("question_plans", question_ref, "analysis_ids"),
                    f"analysis {analysis_id} has no linked design for {question_ref}",
                )
        for result_id in question_plan["result_ids"]:
            result = results.get(result_id)
            if result is None:
                continue
            linked_analyses = [
                analysis_id
                for analysis_id in result["analysis_ids"]
                if analysis_id in question_plan["analysis_ids"]
                and question_ref
                in analyses.get(analysis_id, {}).get("question_refs", [])
            ]
            if not linked_analyses:
                _issue(
                    issues,
                    "broken-question-path",
                    _path("question_plans", question_ref, "result_ids"),
                    f"result {result_id} has no linked analysis for {question_ref}",
                )

    for position, analysis in enumerate(plan["analyses"]):
        for design_id in analysis["design_ids"]:
            design_questions = designs.get(design_id, {}).get("question_refs", [])
            if design_questions and not set(design_questions) & set(
                analysis["question_refs"]
            ):
                _issue(
                    issues,
                    "wrong-analysis-link",
                    _path("analyses", position, "design_ids"),
                    f"analysis links unrelated design {design_id}",
                )
        for question_ref in analysis["question_refs"]:
            if not any(
                question_ref in designs.get(design_id, {}).get("question_refs", [])
                for design_id in analysis["design_ids"]
            ):
                _issue(
                    issues,
                    "broken-analysis-link",
                    _path("analyses", position, "design_ids"),
                    f"analysis has no design for {question_ref}",
                )
    for position, result in enumerate(plan["results"]):
        for analysis_id in result["analysis_ids"]:
            analysis_questions = analyses.get(analysis_id, {}).get("question_refs", [])
            if analysis_questions and not set(analysis_questions) & set(
                result["question_refs"]
            ):
                _issue(
                    issues,
                    "wrong-result-link",
                    _path("results", position, "analysis_ids"),
                    f"result links unrelated analysis {analysis_id}",
                )
        for question_ref in result["question_refs"]:
            if not any(
                question_ref in analyses.get(analysis_id, {}).get("question_refs", [])
                for analysis_id in result["analysis_ids"]
            ):
                _issue(
                    issues,
                    "broken-result-link",
                    _path("results", position, "analysis_ids"),
                    f"result has no analysis for {question_ref}",
                )

    _check_milestone_dag(plan["milestones"], milestones, issues)
    if intake is not None:
        _check_intake(
            plan,
            intake,
            questions,
            question_plans,
            resources,
            issues,
        )
    return issues


def check_plan(plan, *, intake=None):
    """Return deterministic diagnostics without authorizing execution."""

    try:
        validate_plan(plan)
    except Stage3Error as error:
        return {
            "structural_valid": False,
            "issues": [{"code": "schema-invalid", "path": "$", "message": str(error)}],
            "blocked_questions": [],
            "execution_authorized": False,
        }

    issues = _graph_issues(plan, intake=intake)
    blocked = {
        question_plan["question_ref"]
        for question_plan in plan["question_plans"]
        if question_plan["blockers"]
        or any(use["status"] != "available" for use in question_plan["resource_uses"])
    }
    for unknown in plan["unknowns"]:
        if unknown["blocking"]:
            blocked.update(unknown["question_refs"])
    return {
        "structural_valid": not issues,
        "issues": issues,
        "blocked_questions": sorted(blocked),
        "execution_authorized": False,
    }

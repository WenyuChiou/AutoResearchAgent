"""Read-only per-stage "Harness record" counts for the Wiki.

Every number is copied from a saved record that an existing read-only view
already returns (Stage 1 ledger counts, delivery counts, coverage, checkpoint,
Stage 2 views, Stage 3 planning view, saved action history). Nothing is
computed by a model, nothing is written, no lease is taken and no cache file is
created. A value that is not saved is returned as ``None`` with a ``missing``
sentence, never as a made-up number. One stage failing to read never fails the
whole answer.
"""

import sqlite3

from .session_api import SessionApiError

KIND = "HarnessRecordSummary"
SCHEMA_VERSION = "1.0.0"
CATEGORIES = (
    ("failed-check", "没通过的检查"),
    ("wrong-project", "错项目"),
    ("stale-version", "旧版本"),
    ("duplicate-click", "重复点击"),
    ("over-limit", "超额度"),
)
BLOCKED_SCOPE = (
    "只数已保存的失败记录；在写入之前就被拒绝的请求不会留下记录，所以不在这些次数里"
)
REOPEN = {
    "available": False,
    "missing": "后台没有保存关掉重开前后的作业计数，这里不给数字",
}
TIMELINE = {
    "available": False,
    "missing": "后台没有保存每一步的开始和结束时间、模型调用次数和花费，这里不给数字",
}
# A request-deadline TimeoutError is an OSError: it is re-raised before these are
# consulted so a timeout is reported as a timeout, never as "stage unavailable".
_READ_ERRORS = (
    SessionApiError,
    sqlite3.Error,
    OSError,
    ValueError,
    KeyError,
    TypeError,
    RecursionError,
)
TEMPORARY_FILES = (
    "While reading, Stage 1 verification may create and remove a .writer-lock file "
    "inside the Stage 1 ledger folder; no other file is created and nothing remains."
)


def _row(key, label, value, view, path, *, missing=None, detail=None, sha=None):
    return {
        "key": key,
        "label": label,
        "value": value,
        "detail": detail,
        "missing": missing,
        "source": {"view": view, "path": path, "state_sha256": sha},
    }


def _get(value, *path):
    for part in path:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _stage(status, reason, rows, *, records=None, checks=None, passed=None):
    return {
        "status": status,
        "reason": reason,
        "summary": {
            "records": records,
            "rows_with_data": checks,
            "checkpoint_passed": passed,
        },
        "rows": rows,
    }


def _not_run(reason):
    return _stage("not-run", reason, [])


def _unavailable(error):
    code = getattr(error, "code", type(error).__name__)
    return _stage("unavailable", code, [])


def _classify(error):
    """Whole-word (dash separated) matching of the saved error code, never substrings.

    wrong-project: project-unavailable, project-differs
    stale-version: any code with the word stale, or version-differs
    duplicate-click: idempotency-*, *-already-* (already-recorded, already-published)
    over-limit: bound-exceeded, budget, limit, quota
    anything else (including unknown and timeout texts): failed-check
    """
    code = str(error or "")
    words = set(code.split("-"))
    if code == "project-unavailable" or {"project", "differs"} <= words:
        return "wrong-project"
    if "stale" in words or {"version", "differs"} <= words:
        return "stale-version"
    if "idempotency" in words or "already" in words:
        return "duplicate-click"
    if words & {"budget", "limit", "quota"} or {"bound", "exceeded"} <= words:
        return "over-limit"
    return "failed-check"


def _stage_of(kind):
    kind = str(kind)
    if kind.startswith("stage3"):
        return "3"
    if kind.startswith("stage2"):
        return "2"
    return "1"


def _blocked(history):
    """Five fixed categories per stage from saved failed action records."""
    table = {
        stage: {name: {"count": 0, "reasons": []} for name, _ in CATEGORIES}
        for stage in ("1", "2", "3")
    }
    for action in history.get("actions", []) if isinstance(history, dict) else []:
        if action.get("status") not in {"failed", "execution-unknown"}:
            continue
        cell = table[_stage_of(action.get("kind"))][_classify(action.get("error"))]
        cell["count"] += 1
        reason = str(action.get("error") or action.get("status"))[:160]
        if reason not in cell["reasons"] and len(cell["reasons"]) < 5:
            cell["reasons"].append(reason)
    return {
        stage: [
            {"category": name, "label": label, **cells[name]}
            for name, label in CATEGORIES
        ]
        for stage, cells in table.items()
    }


def _stage1(view):
    if view is None:
        return _not_run("stage1-unconnected")
    ledger = view.get("ledger")
    if not isinstance(ledger, dict):
        return _not_run("no-ledger-saved")
    sha = ledger.get("state_sha256")
    counts = ledger.get("counts") or {}
    package = _get(view, "delivery", "canonical_package") or {}
    pcounts = package.get("counts") or {}
    gate = ledger.get("gate") or {}
    coverage = ledger.get("coverage") or {}
    checkpoint = view.get("checkpoint")
    rows = [
        _row(
            "search",
            "检索记录",
            {
                key: counts.get(key)
                for key in (
                    "queries",
                    "backend_attempts",
                    "backend_failures",
                    "success_empty",
                    "discoveries",
                )
            },
            "stage1",
            "ledger.counts",
            sha=sha,
        ),
        _row(
            "screening",
            "筛选决定",
            {"decisions": counts.get("decisions"), "works": counts.get("works")},
            "stage1",
            "ledger.counts",
            missing="没有保存纳入、排除各多少和逐篇理由的分项计数",
            sha=sha,
        ),
        _row(
            "evidence",
            "证据出处",
            {"claims": counts.get("claims")},
            "stage1",
            "ledger.counts.claims",
            missing="没有保存「有页码章节」的分项计数",
            sha=sha,
        ),
        _row(
            "source-check",
            "出处核对",
            pcounts.get("source_bindings") if "source_bindings" in pcounts else None,
            "stage1",
            "delivery.canonical_package.counts.source_bindings",
            missing=None
            if "source_bindings" in pcounts
            else "这一段还没有交付包，没有出处核对计数",
            sha=sha,
        ),
        _row(
            "source-acquisition",
            "原文获取",
            {
                key: pcounts.get(key)
                for key in (
                    "source_attempts",
                    "acquired_full_text",
                    "full_text_acquisition_fraction",
                    "access_state_counts",
                )
            }
            if pcounts
            else None,
            "stage1",
            "delivery.canonical_package.counts",
            missing=None if pcounts else "这一段还没有交付包，没有原文获取计数",
            sha=sha,
        ),
        _row(
            "coverage-stop",
            "覆盖和停止",
            {
                "rounds": len(coverage.get("rounds") or []),
                "recent_complete": coverage.get("recent_complete"),
                "consecutive_zero_yield_rounds": coverage.get(
                    "consecutive_complete_zero_yield_rounds"
                ),
                "budget_exhausted": coverage.get("budget_exhausted"),
                "blockers": len(coverage.get("blockers") or []),
                "next_allowed_action": ledger.get("next_allowed_action"),
            },
            "stage1",
            "ledger.coverage",
            sha=sha,
        ),
        _row(
            "checkpoint",
            "交付检查点",
            None
            if not isinstance(checkpoint, dict)
            else {
                "event_id": checkpoint.get("event_id"),
                "current": checkpoint.get("current"),
                "status": _get(checkpoint, "stage_result", "status"),
                "gate": gate.get("outcome"),
                "blocking_items": len(gate.get("blocking_items") or []),
            },
            "stage1",
            "checkpoint",
            missing=None if isinstance(checkpoint, dict) else "还没有保存交付检查点",
            sha=sha,
        ),
    ]
    records = sum(
        counts.get(key) or 0
        for key in ("queries", "decisions", "claims", "candidate_revisions", "works")
    )
    return _stage(
        "recorded",
        None,
        rows,
        records=records,
        checks=sum(1 for row in rows if row["value"] is not None),
        passed=None if gate.get("outcome") is None else gate.get("outcome") == "pass",
    )


def _stage2(stage2, selection, selection_error=None):
    if stage2 is None and selection is None:
        return _not_run("stage2-unconnected")
    activation = _get(stage2, "activation")
    cards = _get(selection, "cards")
    if activation is None and not cards:
        return _not_run("stage2-not-started")
    receipt = _get(selection, "selection_receipt")
    rows = [
        _row(
            "candidates",
            "候选",
            None if cards is None else {"candidates": len(cards)},
            "stage2-selection",
            "cards",
            missing=None
            if cards is not None
            else (
                "选案读取失败：" + selection_error if selection_error else "还没有候选"
            ),
        ),
        _row(
            "same-conditions",
            "同一套条件",
            None,
            "stage2-selection",
            "cards",
            missing="后台没有保存「每个候选是否填了同样几项」的计数",
        ),
        _row(
            "input-origin",
            "证据来自本课题吗",
            None
            if _get(stage2, "current_evidence") is None
            else {
                "status": _get(stage2, "current_evidence", "status"),
                "reason": _get(stage2, "current_evidence", "reason"),
            },
            "stage2",
            "current_evidence",
            missing="没有核实候选引用的证据是否都能在本课题 Stage 1 找到",
        ),
        _row(
            "advice-only",
            "只建议不替你选",
            None,
            "stage2-selection",
            "eligible",
            missing="后台没有保存「系统建议几个、页面有没有预选」的计数",
        ),
        _row(
            "selection-receipt",
            "你的选择回执",
            None
            if selection is None
            else {
                "selection_status": _get(selection, "selection_status"),
                "receipt_saved": receipt is not None,
                "planning_status": _get(selection, "planning_status"),
            },
            "stage2-selection",
            "selection_receipt",
            missing=None if selection is not None else "还没有选择视图",
        ),
    ]
    return _stage(
        "recorded",
        None,
        rows,
        records=1 if receipt else 0,
        checks=sum(1 for row in rows if row["value"] is not None),
        passed=None,
    )


def _stage3(view):
    if view is None:
        return _not_run("stage3-unconnected")
    if not _get(view, "planning_configured"):
        return _not_run("stage3-not-registered")
    plan = _get(view, "plan")
    job = _get(view, "job")
    rows = [
        _row(
            "registration",
            "规划登记",
            {"configured": True, "selection_status": _get(view, "selection_status")},
            "stage3",
            "planning_configured",
        ),
        _row(
            "plan",
            "计划",
            None if plan is None else {"saved": True},
            "stage3",
            "plan",
            missing=None if plan is not None else "还没有保存的计划",
        ),
        _row(
            "job",
            "规划作业",
            None if job is None else {"status": _get(job, "status")},
            "stage3",
            "job",
            missing=None if job is not None else "还没有规划作业",
        ),
        _row(
            "step-completeness",
            "每一步四项齐不齐",
            None,
            "stage3",
            "plan",
            missing="后台没有按「步数 × 4」保存缺项计数",
        ),
        _row(
            "independent-review",
            "独立评审",
            None,
            "stage3",
            "plan",
            missing="还没有运行或没有保存评审维度计数",
        ),
        _row(
            "execution",
            "实际执行",
            None,
            "stage3",
            "job",
            missing="没有执行记录；执行未被授权",
        ),
    ]
    return _stage(
        "recorded",
        None,
        rows,
        records=(1 if plan is not None else 0) + (1 if job is not None else 0),
        checks=sum(1 for row in rows if row["value"] is not None),
        passed=None,
    )


def harness_record(server, credential, ref, *, stage=None, check_deadline=None):
    """Compose the summary from the same read-only views the pages already use.

    ``stage`` ("1", "2" or "3") reads only that stage so a page can fetch the three
    stages separately; with ``stage=None`` all three are read in one request, which
    can approach the request deadline on a fully connected project (the deadline is
    then reported as a timeout, never as an empty stage).
    """
    if stage not in (None, "1", "2", "3"):
        raise SessionApiError("invalid-project-read", 400)
    projects = server.projects
    project = projects.read(credential, ref)
    stage1 = stage2 = selection = planning = None
    errors = {}
    selection_error = None
    if stage in (None, "1", "2") and server.project_stage1 is not None:
        direct = (
            project.get("input_origin") == "stage2-direct-request"
            and project.get("receiving_only") is True
        )
        if not direct:
            try:
                stage1 = server.stage1_view(credential, ref, automatic=True)
            except TimeoutError:
                raise
            except _READ_ERRORS as error:
                errors["1"] = error
    if stage in (None, "2") and server.project_stage2 is not None:
        try:
            stage2 = server.stage2_view(
                credential,
                ref,
                project=project,
                stage1=stage1,
                check_deadline=check_deadline,
            )
        except TimeoutError:
            raise
        except _READ_ERRORS as error:
            errors["2"] = error
        extension = getattr(server, "project_stage2_selection", None)
        if extension is not None and "2" not in errors:
            try:
                selection = extension.read(
                    credential, ref, check_deadline=check_deadline
                )
            except TimeoutError:
                raise
            except _READ_ERRORS as error:
                selection_error = getattr(error, "code", type(error).__name__)
    if stage in (None, "3"):
        http = getattr(server, "project_stage3_http", None)
        if http is not None:
            try:
                planning = http.view(credential, ref, check_deadline=check_deadline)
            except TimeoutError:
                raise
            except _READ_ERRORS as error:
                errors["3"] = error
    try:
        history = projects.history(credential, ref)
    except TimeoutError:
        raise
    except _READ_ERRORS:
        history = {}
    blocked = _blocked(history)
    stages = {}
    wanted = ("1", "2", "3") if stage is None else (stage,)
    for number in wanted:
        if number in errors:
            value = _unavailable(errors[number])
        elif number == "1":
            value = _stage1(stage1)
        elif number == "2":
            value = _stage2(stage2, selection, selection_error)
        else:
            value = _stage3(planning)
        value["blocked"] = blocked[number]
        value["blocked_scope"] = BLOCKED_SCOPE
        value["blocked_total"] = sum(cell["count"] for cell in blocked[number])
        value["reopen"] = dict(REOPEN)
        value["timeline"] = dict(TIMELINE)
        stages[number] = value
    return {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "project_ref": ref,
        "input_version": project.get("input_version"),
        "revision": project.get("revision"),
        "read_only": True,
        "execution_authorized": False,
        "temporary_files": TEMPORARY_FILES,
        "stages": stages,
    }

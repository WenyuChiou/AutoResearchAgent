"""Wiki routes to create and read a Stage 1 run grant on the ordinary loopback Host.

Creating wraps ProjectStage1RunGrantService.authorize; no grant logic lives here.
The route only adds gates: the researcher's own words and an explicit confirmation,
the launch --run-limits as a ceiling, and exact project / version / scope / plan
binding. Reading never writes (the service's inspect() updates a lease file, so it
is deliberately not used for reading).
"""

from contextlib import closing
import re
import sqlite3

from research_workspace_native.project_resource_budget import resource_view
from research_workspace_native.project_stage1_run_grant import (
    SCOPE,
    STORE,
)
from research_workspace_native.project_stage1_run_lease import RunLease
from research_workspace_native.session_api import SessionApiError, _check, _hash
from research_workspace_native.transport import _decode
from stage1_ledger.journal import decode

from wiki_project_progression_http import run_grant_issuer


ROUTE = re.compile(r"/api/projects/([A-Za-z0-9_-]{1,64})/stage1-run-grant")
CODE = re.compile(r"[a-z0-9][a-z0-9-]{0,127}")
LIMIT_KEYS = ("model_calls", "seconds", "search_calls", "source_reads", "rounds")
MAX_BODY = 24576  # 8192 user bytes plus JSON escaping; the grant service re-bounds it
CREATE_FIELDS = {
    "key",
    "input_version",
    "brief_sha256",
    "plan_manifest_sha256",
    "user_input",
    "confirmed",
    "operations",
    "max_seconds",
    "max_actions",
}
REASONS = {
    "stage1-run-grant-zero-limits": "这次启动的运行上限是 0（或没有可用秒数），Wiki 不会创建运行许可。要真实运行，需带非零的 --run-limits 重新启动。",
    "stage1-run-grant-not-enabled": "这次启动没有开启整轮运行（--enable-stage1-run，需要内容模型和公开来源），所以不能创建运行许可。",
    "stage1-run-grant-fields-invalid": "请求字段不对：必须恰好带 key、input_version、brief_sha256、plan_manifest_sha256、user_input、confirmed、operations、max_seconds、max_actions。",
    "stage1-run-user-words-required": "需要研究者自己写的授权理由（user_input），不能为空。",
    "stage1-run-confirmation-required": "需要明确确认（confirmed 必须是 true）。",
    "stage1-run-grant-over-launch-limits": "许可的额度超过了这次启动时 --run-limits 给的上限。",
    "stage1-run-grant-scope-not-ready": "这个课题还没有确认范围或检索计划，不能创建运行许可。",
    "stage1-run-grant-project-differs": "输入版本或范围说明哈希和课题当前保存的不一致，请重新读取课题后再提交。",
    "stage1-run-grant-plan-differs": "检索计划哈希和课题当前保存的不一致，请重新读取课题后再提交。",
    "stage1-run-grant-execution-unknown": "这次创建的结果不确定，请读取运行许可摘要确认，不要换新请求键重复提交。",
    "stage1-run-grant-verification-required": "保存的记录没通过核对，没有创建运行许可。",
    "stage1-run-explicit-user-consent-required": "需要研究者的原话和明确确认，范围必须是 Stage 1 整轮。",
    "stage1-run-operation-invalid": "operations 必须是非空、不重复、且都在允许范围内的列表。",
    "stage1-run-limits-invalid": "max_seconds 或 max_actions 超出允许范围（秒数最长 3 小时，动作数最多 512）。",
    "stage1-run-budget-exceeded": "max_seconds 超过了课题保存的秒数额度。",
    "stage1-run-lane-not-consented": "选中的操作需要课题里已经勾选的同意项和大于 0 的额度（检索、取原文、模型阅读）。",
    "stage1-run-grant-renewal-refused": "这个课题当前版本已经有运行许可，不会续期或重复创建。",
    "idempotency-payload-differs": "这个请求键已经用过，且内容不同；不会改动原许可。",
    "stale-revision": "课题刚被改动，请重新读取后再提交。",
    "intake-source-version-differs": "输入版本或范围说明哈希和课题当前保存的不一致。",
    "imported-intake-is-read-only": "导入的课题是只读的，不能创建运行许可。",
    "project-unavailable": "找不到这个课题。",
    "cross-site-rejected": "只接受本页面同源的请求。",
    "credential-rejected": "凭据不对。",
    "stage1-run-grant-unavailable": "没有可用的运行许可。",
}


def _launch_limits(limits):
    if (
        type(limits) is not dict
        or set(limits) != set(LIMIT_KEYS)
        or any(type(v) is not int or v < 0 for v in limits.values())
    ):
        raise ValueError("launch run limits required")
    return dict(limits)


def _reason(code):
    return REASONS.get(code, "被现有安全检查拒绝：" + code)


class Stage1RunGrantApi:
    def __init__(self, host, *, limits, runtime_sha256):
        self.intake = host.projects
        self.limits = _launch_limits(limits)
        self.issuer, self.trusted = run_grant_issuer(host, runtime_sha256)
        self._host = host

    @property
    def zero_limits(self):
        # A grant can never be used without seconds, and an all-zero launch is the
        # engineering "no research" configuration.
        return self.limits["seconds"] <= 0 or not any(self.limits.values())

    def _request(self, body):
        _check(
            type(body) is dict and "user_input" in body,
            "stage1-run-user-words-required",
            400,
        )
        _check(
            type(body["user_input"]) is str and bool(body["user_input"].strip()),
            "stage1-run-user-words-required",
            400,
        )
        _check(body.get("confirmed") is True, "stage1-run-confirmation-required", 400)
        _check(set(body) == CREATE_FIELDS, "stage1-run-grant-fields-invalid", 400)
        _check(
            type(body["input_version"]) is int
            and body["input_version"] > 0
            and _hash(body["brief_sha256"])
            and _hash(body["plan_manifest_sha256"])
            and type(body["max_seconds"]) is int
            and body["max_seconds"] > 0
            and type(body["max_actions"]) is int
            and body["max_actions"] > 0,
            "stage1-run-grant-fields-invalid",
            400,
        )
        return body

    def _replay(self, credential, ref, key):
        try:
            saved = self.intake.action(credential, key, project_ref=ref)
        except SessionApiError as error:
            if error.code != "intake-action-unavailable":
                raise
            return False
        return saved.get("kind") == "stage1-run-authorize"

    def create(self, credential, ref, body):
        # Zero-limit launches never reach the body, the project or the intake store.
        _check(not self.zero_limits, "stage1-run-grant-zero-limits", 409)
        _check(self.trusted, "stage1-run-grant-not-enabled", 409)
        request = self._request(body)
        _check(
            request["max_seconds"] <= self.limits["seconds"],
            "stage1-run-grant-over-launch-limits",
            409,
        )
        if not self._replay(credential, ref, request["key"]):
            project = self.intake.read(credential, ref)
            _check(
                type(project.get("input_version")) is int
                and project.get("settings") is not None
                and project.get("plan") is not None
                and project.get("stage1_intake_ready") is True,
                "stage1-run-grant-scope-not-ready",
            )
            _check(
                request["input_version"] == project["input_version"]
                and request["brief_sha256"] == project["brief_sha256"],
                "stage1-run-grant-project-differs",
            )
            _check(
                request["plan_manifest_sha256"] == project["plan"]["manifest_sha256"],
                "stage1-run-grant-plan-differs",
            )
            budgets = project["settings"]["budgets"]
            _check(
                all(budgets[name] <= limit for name, limit in self.limits.items()),
                "stage1-run-grant-over-launch-limits",
            )
            # The service re-checks this inside its transaction (and would keep a
            # failed record); refuse the plain case first so nothing is written.
            _check(
                request["max_seconds"] <= budgets["seconds"],
                "stage1-run-budget-exceeded",
            )
            revision = project["revision"]
        else:
            revision = 0  # Replays return the saved receipt before any revision check.
        try:
            receipt = self.issuer.authorize(
                credential,
                ref,
                {
                    "key": request["key"],
                    "revision": revision,
                    "input_version": request["input_version"],
                    "brief_sha256": request["brief_sha256"],
                    "confirmed": True,
                    "user_input": request["user_input"],
                    "scope": SCOPE,
                    "operations": request["operations"],
                    "max_seconds": request["max_seconds"],
                    "max_actions": request["max_actions"],
                },
            )
        except SessionApiError as error:
            # The service keeps a failed record for a refusal inside its transaction
            # and reports it generically; hand the researcher the recorded reason.
            saved = error.receipt or {}
            detail = str(saved.get("error"))
            if error.code == "intake-operation-failed" and CODE.fullmatch(detail):
                refusal = SessionApiError(detail, 409)
                refusal.recorded = True
                raise refusal from error
            raise
        if receipt["status"] == "failed":
            detail = str(receipt.get("error"))
            refusal = SessionApiError(
                detail if CODE.fullmatch(detail) else "intake-operation-failed", 409
            )
            refusal.recorded = True
            raise refusal
        _check(receipt["status"] == "saved", "stage1-run-grant-execution-unknown", 409)
        return 200 if receipt["replayed"] else 201, {
            "status": "saved",
            "replayed": receipt["replayed"],
            "project_ref": ref,
            "grant_ref": receipt["grant_ref"],
            "grant_sha256": receipt["grant_sha256"],
            "expires_at": receipt["expires_at"],
            "execution_authorized": False,
            "creates_lane_permits": False,
            "resets_resources": False,
        }

    def _lease(self, ref, document, pin):
        """Open the lease read-only; the service's own check() would write to it."""
        try:
            path = RunLease(self.intake, ref, document, pin).path
            with closing(
                sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
            ) as db:
                row = db.execute("SELECT body FROM lease WHERE id=1").fetchone()
            body = decode(row[0].encode(), "Stage1 run lease")
            return {"state": body["blocked"] or "open"}
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
            return {"state": "unreadable"}

    def _grant_summary(self, principal, ref, state):
        grants = state.get(STORE, {})
        if type(grants) is not dict or not grants:
            return {"status": "none"}
        binding = self.issuer._binding(state)
        matches = []
        for grant_ref, row in grants.items():
            try:
                _, document = self.issuer._document(
                    principal, ref, grant_ref, row.get("sha256")
                )
            except SessionApiError as error:
                if error.code == "stage1-run-grant-revoked":
                    return {"status": "revoked", "grant_ref": grant_ref}
                return {"status": "invalid", "reason": error.code}
            if document["binding"] == binding:
                matches.append((grant_ref, row["sha256"], document))
        if not matches:
            return {"status": "stale", "stale_count": len(grants)}
        if len(matches) != 1:
            return {"status": "invalid", "reason": "stage1-run-grant-ambiguous"}
        grant_ref, pin, document = matches[0]
        now = self.issuer._now()
        lease = self._lease(ref, document, pin)
        remaining = max(0, document["expires_at"] - now)
        status = "active"
        if lease["state"] in ("expired", "revoked", "clock-regressed"):
            status = lease["state"]
        elif lease["state"] == "unreadable":
            status = "invalid"
        elif remaining <= 0:
            status = "expired"
        used = 0
        for (receipt,) in self.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE principal=? AND project=?",
            (principal, ref),
        ).fetchall():
            action = decode(receipt.encode(), "run action")
            if (
                action["kind"] == "stage1-run-derive"
                and action["request"].get("grant_ref") == grant_ref
            ):
                used += 1
        try:
            view = resource_view(self.intake, state, principal)
            resources = {
                "status": "available",
                "declared": view["declared"],
                "reserved": view["reserved"],
                "remaining": view["remaining"],
                "usage_status": view["usage_status"],
                "automatic_refund": view["automatic_refund"],
            }
        except SessionApiError as error:
            resources = {"status": "unavailable", "reason": error.code}
        return {
            "status": status,
            "grant_ref": grant_ref,
            "grant_sha256": pin,
            "scope": document["scope"],
            "user_input": document["user_input"],
            "operations": document["operations"],
            "limits": {name: document["budgets"][name] for name in LIMIT_KEYS},
            "max_actions": document["max_actions"],
            "actions_used": used,
            "issued_at": document["issued_at"],
            "expires_at": document["expires_at"],
            "remaining_seconds": remaining,
            "binding": {
                key: document["binding"][key]
                for key in ("input_version", "brief_sha256", "plan_manifest_sha256")
            },
            "lease": lease,
            "resources": resources,
        }

    def summary(self, credential, ref):
        project = self.intake.read(credential, ref)
        principal = self.intake._principal(credential)
        progression = getattr(self._host, "wiki_project_progression", None)
        ready = (
            type(project.get("input_version")) is int
            and project.get("settings") is not None
            and project.get("stage1_intake_ready") is True
        )
        creation = "available"
        if self.zero_limits:
            creation = "stage1-run-grant-zero-limits"
        elif not self.trusted:
            creation = "stage1-run-grant-not-enabled"
        elif not ready:
            creation = "stage1-run-grant-scope-not-ready"
        out = {
            "project_ref": ref,
            "input_version": project.get("input_version"),
            "execution_authorized": False,
            "launch_limits": dict(self.limits),
            "grant_creation": {
                "available": creation == "available",
                "reason": None if creation == "available" else creation,
                "max_seconds": min(
                    self.issuer.max_seconds,
                    self.limits["seconds"],
                    project["settings"]["budgets"]["seconds"]
                    if ready
                    else self.limits["seconds"],
                ),
            },
            "consent": (
                progression.consent_summary(credential, ref)
                if progression is not None
                else {
                    "present": False,
                    "valid": False,
                    "reason": "consent-not-provided",
                    "expires_at": None,
                    "expired": None,
                    "consent_sha256": None,
                    "stages": {
                        stage: {
                            "covered": False,
                            "max_dispatches": None,
                            "reason": "consent-not-provided",
                        }
                        for stage in ("stage1", "stage2", "stage3")
                    },
                }
            ),
            "run_grant": {"status": "none"},
        }
        if not ready:
            return out
        with self.intake._lock:
            state = self.intake._load(principal, ref)
            out["run_grant"] = self._grant_summary(principal, ref, state)
        return out


def install_stage1_run_grant(host, *, limits, runtime_sha256):
    api = Stage1RunGrantApi(host, limits=limits, runtime_sha256=runtime_sha256)
    inherited = host.RequestHandlerClass

    class RunGrantHandler(inherited):
        def do_GET(self):
            match = ROUTE.fullmatch(self.path)
            return self._run_grant("GET", match[1]) if match else super().do_GET()

        def do_POST(self):
            match = ROUTE.fullmatch(self.path)
            return self._run_grant("POST", match[1]) if match else super().do_POST()

        def _body(self, length):
            _check(
                self.headers.get("Content-Type", "").lower() == "application/json",
                "json-content-type-required",
                415,
            )
            _check(0 < length <= MAX_BODY, "stage1-run-grant-body-bound-exceeded", 413)
            raw = self.rfile.read(length)
            _check(len(raw) == length, "partial-body", 400)
            try:
                return _decode(raw.decode("utf-8"))
            except (ValueError, UnicodeError, RecursionError):
                raise SessionApiError("invalid-json", 400) from None

        def _run_grant(self, method, ref):
            try:
                credential, length = self._headers(method)
                _check(
                    self.headers.get("Sec-Fetch-Site") in (None, "none", "same-origin"),
                    "cross-site-rejected",
                    403,
                )
                _check(
                    host.authenticate(credential) is not None,
                    "credential-rejected",
                    401,
                )
                if method == "GET":
                    _check(not length, "invalid-project-read", 400)
                    status, result = 200, api.summary(credential, ref)
                else:
                    status, result = api.create(credential, ref, self._body(length))
                self._remaining()
                return self._reply(status, result)
            except SessionApiError as error:
                body = {"error": error.code, "reason": _reason(error.code)}
                if getattr(error, "recorded", False):
                    body["recorded_as_failed"] = True
                    body["reason"] += (
                        "（这次尝试已作为失败记录保存；重试请换新的请求键。）"
                    )
                return self._reply(error.status, body)
            except (OSError, TimeoutError):
                self.close_connection = True
            except (ValueError, TypeError, KeyError):
                code = "stage1-run-grant-verification-required"
                return self._reply(409, {"error": code, "reason": _reason(code)})

    host.RequestHandlerClass = RunGrantHandler
    # A grant write must finish even if the browser disconnects.
    host.daemon_threads = False
    host.block_on_close = True
    return api

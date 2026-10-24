"""Fixed trusted dispatch into existing Stage 1 services under one saved run grant."""

from copy import deepcopy
from functools import partial
import time

from stage1_deliverable.common import sha
from stage1_ledger.journal import canonical, decode

from .project_agent_analysis import ProjectStage1AnalysisService
from .project_agent_coverage import ProjectAgentCoverageService
from .project_agent_pending import initialize_pending
from .project_agent_rounds import record_round
from .project_source_dispatcher import ProjectSourceDispatcher
from .project_run_authority import action_identity
from .project_stage1_continuation import ContinuationAction
from .project_stage1_run_grant import ProjectStage1RunGrantService, derived_action_key
from .session_api import _check


class ProjectStage1RunActions:
    """No browser callbacks, new producers, resource resets, or receipt aliases."""

    def __init__(self, driver, issuer, grant_ref, grant_sha256):
        from .project_stage1_auto import ProjectStage1AutoDriver

        _check(
            type(driver) is ProjectStage1AutoDriver
            and type(issuer) is ProjectStage1RunGrantService
            and issuer.intake is driver.intake,
            "stage1-auto-run-owner-differs",
        )
        self.driver, self.issuer = driver, issuer
        self.intake, self.host = driver.intake, driver.host
        self.credential, self.ref = driver.credential, driver.ref
        self.grant_ref, self.grant_sha256 = grant_ref, grant_sha256
        self.stage1 = self.host.project_stage1
        self.models = self.host.project_models
        self.records = self.host.project_stage1_records
        self.analysis = (
            None
            if self.models is None or self.records is None
            else ProjectStage1AnalysisService(self.stage1, self.models, self.records)
        )
        self.coverage = (
            None
            if self.analysis is None
            else ProjectAgentCoverageService(self.analysis)
        )
        self.steps = {}
        self.document()

    def document(self):
        return self.issuer.inspect(
            self.credential, self.ref, self.grant_ref, self.grant_sha256
        )

    def _method(self, operation):
        query = self.driver.queries
        sources = self.host.project_stage1_sources
        table = {
            "initialize-pending": (
                "screen",
                "agent-adoption",
                "stage1-agent-pending",
                partial(initialize_pending, self.stage1),
                True,
            ),
            "analysis-adopt": (
                "reading",
                "agent-adoption",
                "stage1-agent-analysis",
                None if self.analysis is None else self.analysis.adopt,
                True,
            ),
            "coverage-review": (
                "coverage",
                "agent-adoption",
                "stage1-agent-coverage",
                None if self.coverage is None else self.coverage.review,
                True,
            ),
            "register-analysis": (
                "reading",
                "records",
                "stage1-agent-reading",
                None if self.analysis is None else self.analysis.register,
                True,
            ),
            "register-coverage": (
                "reading",
                "records",
                "stage1-agent-reading",
                None if self.coverage is None else self.coverage.register,
                True,
            ),
            "round": (
                "coverage",
                "agent-adoption",
                "stage1-coverage",
                partial(record_round, self.stage1),
                True,
            ),
            "source-authorize": (
                "source",
                "source",
                "source-authorize",
                None if sources is None else sources.authorize,
                False,
            ),
            "source-execute": (
                "source",
                "source",
                "source-execute",
                None if sources is None else sources.execute,
                False,
            ),
            "model-authorize": (
                "reading",
                "analyze-full-paper",
                "model-authorize",
                None if self.models is None else self.models.authorize,
                False,
            ),
            "model-execute": (
                "reading",
                "analyze-full-paper",
                "model-execute",
                None if self.models is None else self.models.execute,
                False,
            ),
            "query-authorize": (
                "query",
                "query",
                "query-authorize",
                None if query is None else query.authorize,
                False,
            ),
            "query-bootstrap": (
                "query",
                "query",
                "query-bootstrap",
                None if query is None else query.bootstrap,
                False,
            ),
            "query-execute": (
                "query",
                "query",
                "query-execute",
                None if query is None else query.execute,
                False,
            ),
            "checkpoint": (
                "records",
                "records",
                "stage1-checkpoint",
                self.stage1.checkpoint,
                True,
            ),
            "records": (
                "records",
                "records",
                "stage1-produce-records",
                None
                if self.host.project_records_prepare is None
                else self.host.project_records_prepare.prepare,
                True,
            ),
            "delivery": (
                "delivery",
                "delivery",
                "stage1-deliver",
                self.host.project_stage1_delivery.deliver,
                True,
            ),
        }
        _check(
            type(operation) is str and operation in table,
            "stage1-auto-operation-invalid",
        )
        kind, lane, action, method, ledger = table[operation]
        _check(method is not None, "stage1-auto-producer-unconnected")
        for prefix, service in (
            ("query-", query),
            ("source-", sources),
            ("model-", self.models),
        ):
            if operation.startswith(prefix):
                _check(
                    service.run_grants is self.issuer,
                    "stage1-auto-run-issuer-unconnected",
                )
        if operation == "source-execute":
            dispatcher = getattr(self.host, "project_stage1_source_dispatcher", None)
            _check(
                type(dispatcher) is ProjectSourceDispatcher
                and dispatcher.service is sources,
                "stage1-auto-source-dispatcher-unconnected",
            )
        return kind, lane, action, method, ledger

    def _registry_key(self, body):
        row = self.intake.db.execute(
            "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
            (self.driver.principal, self.ref, body["adoption_key"]),
        ).fetchone()
        _check(
            row is not None and row[0] == body["adoption_request_sha256"],
            "stage1-auto-adoption-missing",
        )
        saved = decode(row[1].encode(), "auto saved adoption")
        _check(
            saved["status"] == "saved"
            and saved["reading_sha256"]
            == body["reading_sha256"]
            == sha(canonical(saved["reading"])),
            "stage1-auto-adoption-reading-differs",
        )
        context = self.records._context(self.ref, body["ledger_state_sha256"])
        # This is the original _register content key, not a new alias receipt.
        return "stage1-reading-registry-" + sha(
            canonical(self.records._entry(context, saved["reading"]))
        )

    def prepare(self, snapshot, operation, extra):
        _check(type(extra) is dict, "stage1-auto-action-body-invalid")
        with self.intake._lock:
            doc = self.document()
            kind, lane, action, method, needs_ledger = self._method(operation)
            _check(lane in doc["operations"], "stage1-run-operation-not-authorized")
            project = self.intake.read(self.credential, self.ref)
            reserved = {
                "key",
                "revision",
                "input_version",
                "brief_sha256",
                "confirmed",
                "run_authority",
                "run_user_input",
                "user_input",
                "ledger_state_sha256",
            }
            _check(not set(extra) & reserved, "stage1-auto-transport-fields-forbidden")
            body = {
                key: project[key]
                for key in ("revision", "input_version", "brief_sha256")
            }
            body.update(confirmed=False, **deepcopy(extra))
            if needs_ledger:
                body["ledger_state_sha256"] = self.stage1.read(
                    self.credential, self.ref
                )["ledger"]["state_sha256"]
            if operation in {"query-authorize", "model-authorize"}:
                body["user_input"] = doc["user_input"]
            identity = action_identity(action, body)
            token_key = derived_action_key(self.grant_sha256, lane, identity)
            key = (
                self._registry_key(body)
                if operation in {"register-analysis", "register-coverage"}
                else token_key + "-work"
            )
            self.steps[identity] = dict(
                operation=operation,
                lane=lane,
                action=action,
                method=method,
                body=body,
                key=key,
            )
            return ContinuationAction(
                kind, identity, snapshot.binding, snapshot.frontier_sha256
            )

    def key_for(self, action):
        _check(action.identity in self.steps, "stage1-auto-action-unprepared")
        return self.steps[action.identity]["key"]

    def dispatch(self, action, key, deadline):
        _check(time.monotonic() < deadline, "stage1-auto-deadline-exhausted", 408)
        _check(key == self.key_for(action), "stage1-auto-durable-key-differs")
        step = self.steps.pop(action.identity)
        with self.intake._lock:
            self.document()
            token = self.issuer.derive(
                self.credential,
                self.ref,
                grant_ref=self.grant_ref,
                grant_sha256=self.grant_sha256,
                operation=step["lane"],
                identity=action.identity,
            )
            body = dict(
                step["body"],
                key=token.key + "-work",
                revision=self.intake.read(self.credential, self.ref)["revision"],
            )

            def check():
                _check(
                    time.monotonic() < deadline, "stage1-auto-deadline-exhausted", 408
                )
                self.document()

            check()
            # Existing producers validate the token, current offer and body again.
            result = step["method"](
                self.credential,
                self.ref,
                body,
                run_authorization=token,
                check_deadline=check,
            )
            if step["operation"] == "source-execute":
                self.host.project_stage1_source_dispatcher.submit_saved(
                    self.credential,
                    self.ref,
                    body["key"],
                    result,
                )
            return result

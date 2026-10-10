"""One explicit planned-query attempt; HTTP disconnect/reopen never dispatches."""

from copy import deepcopy
from pathlib import Path
import sqlite3
import json
import math
import threading
import time

from stage1_deliverable.common import canonical, sha
from stage1_coverage.run import CoverageLedger
from stage1_retrieval.runner import execute as execute_backend
from stage1_retrieval.receipt import command
from research_workspace_native.planned_query_contract import (
    KEY,
    PROBE_TIMEOUT_SECONDS,
    inspect_registration,
    next_target,
    require,
    tree_sha,
)
from research_workspace_native.store import ProjectStore
from research_workspace_native.query_storage import (
    budget_path,
    LedgerOwners,
    check_mutable_storage,
    check_writer_paths,
)
from research_workspace_native.query_execution_source import check_execution_source


class PlannedQueryService:
    def __init__(
        self,
        store_path,
        *,
        registrations,
        authenticate,
        admit,
        verify_source,
        executor=execute_backend,
    ):
        require(
            callable(authenticate)
            and callable(admit)
            and callable(verify_source)
            and callable(executor),
            "query-gates-required",
            400,
        )
        require(
            isinstance(registrations, dict) and 1 <= len(registrations) <= 16,
            "query-registration-bound",
            400,
        )
        self._auth, self._admit, self._execute = authenticate, admit, executor
        self._verify_source = verify_source
        self._lock, self._closed, self._workers, self._projects = (
            threading.RLock(),
            False,
            {},
            {},
        )
        self._closing = False
        prepared = [
            (ref, *inspect_registration(ref, item, require_ready=False))
            for ref, item in registrations.items()
        ]
        for ref, item, _, _, _ in prepared:
            check_execution_source(verify_source, ref, item, "before-store", executor)
        roots = [Path(item["ledger_root"]) for _, item, _, _, _ in prepared]
        require(len(set(roots)) == len(roots), "query-ledger-shared-across-projects")
        database = budget_path(store_path, prepared)
        if database.exists():
            old = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
            try:
                for ref, item, _, _, _ in prepared:
                    row = old.execute(
                        "SELECT state FROM projects WHERE id=?", (self._pid(ref),)
                    ).fetchone()
                    if row:
                        require(
                            json.loads(row[0]).get("query_binding") == item,
                            "query-saved-binding-differs",
                        )
            finally:
                old.close()
        self.ledger_owners = LedgerOwners(roots)
        self.store = ProjectStore.__new__(ProjectStore)
        try:
            self.store.__init__(database)
            for ref, item, permit, _, pin in prepared:
                pid = self._pid(ref)
                saved = self.store.bind_project(pid, item["index_sha256"])
                require(
                    saved.get("query_binding", item) == item,
                    "query-saved-binding-differs",
                )
                owner = self.store.acquire_owner(pid, "planned-query-owner")
                with self.store._edit(
                    pid, owner, None, "query-service-bound", item
                ) as state:
                    state["query_binding"] = item
                    state.setdefault("query_budget", {"attempts": 0, "seconds": 0})
                    state.setdefault(
                        "query_ledger_sha256", tree_sha(item["ledger_root"])
                    )
                self._projects[ref] = dict(
                    item=item, permit=permit, pin=pin, pid=pid, owner=owner
                )
        except BaseException:
            if hasattr(self.store, "db"):
                self.store.db.close()
            for _, connection in getattr(self.store, "_owners", {}).values():
                connection.close()
            self.ledger_owners.close()
            self._closed = True
            raise

    @staticmethod
    def _pid(ref):
        return "planned-query-" + sha(ref.encode())[:32]

    def _access(self, token, ref):
        require(not self._closed, "query-service-closed", 503)
        try:
            principal = self._auth(token)
        except Exception:
            principal = None
        p = self._projects.get(ref)
        require(
            p is not None and principal in p["item"]["principals"],
            "query-project-denied",
            403,
        )
        return p, principal

    def bindings(self):
        return {
            ref: {
                k: p["item"][k] for k in ("project_id", "index_sha256", "input_version")
            }
            for ref, p in self._projects.items()
        }

    def view(self, token, ref):
        with self._lock:
            p, principal = self._access(token, ref)
            state = self.store.snapshot(p["pid"])
            return dict(
                project_ref=ref,
                **self.bindings()[ref],
                revision=state["revision"],
                budget=deepcopy(state["query_budget"]),
                history=[
                    deepcopy(row)
                    for row in state["intents"].values()
                    if row["principal"] == principal
                ],
                operation_scope="explicit-planned-query",
                model_execution=False,
                automatic_retry=False,
                unproven_resource_limits=[
                    "provider-requests",
                    "network-bytes",
                    "billing",
                    "process-tree-containment",
                ],
            )

    def get_action(self, token, ref, key):
        with self._lock:
            p, principal = self._access(token, ref)
            require(
                isinstance(key, str) and KEY.fullmatch(key), "query-key-invalid", 400
            )
            row = self.store.snapshot(p["pid"])["intents"].get(
                sha(canonical([principal, key]))
            )
            require(
                row is not None and row["principal"] == principal,
                "query-action-not-found",
                404,
            )
            return deepcopy(row)

    def _check_storage(self):
        check_mutable_storage(
            [Path(p["item"]["ledger_root"]) for p in self._projects.values()],
            self.store.path,
            [p["pid"] for p in self._projects.values()],
        )

    def _check_control(self):
        check_writer_paths(
            [Path(p["item"]["ledger_root"]) for p in self._projects.values()],
            self.store.path,
            [p["pid"] for p in self._projects.values()],
        )

    def _inspect(self, ref, p, saved):
        self._check_storage()
        item, permit, state, pin = inspect_registration(ref, p["item"])
        require(
            tree_sha(item["ledger_root"]) == saved["query_ledger_sha256"],
            "query-ledger-changed",
        )
        require(
            not any(row["status"] != "completed" for row in saved["intents"].values()),
            "query-unreconciled-action",
        )
        ledger = CoverageLedger(item["ledger_root"])
        require(
            not any(
                ledger.event(k)["operation"] == "backend" for k in ledger.pending()
            ),
            "query-pending-backend",
        )
        require(
            saved["query_budget"]["attempts"] < permit["max_attempts"]
            and saved["query_budget"]["seconds"]
            + pin["timeout_seconds"]
            + PROBE_TIMEOUT_SECONDS
            <= permit["max_reserved_seconds"],
            "query-budget-exhausted",
            429,
        )
        return item, permit, state, pin

    def offer(self, token, ref):
        with self._lock:
            p, principal = self._access(token, ref)
            saved = self.store.snapshot(p["pid"])
            item, permit, state, pin = self._inspect(ref, p, saved)
            target = next_target(state, permit)
            document = dict(
                project_ref=ref,
                principal=principal,
                **{
                    k: item[k]
                    for k in (
                        "index_sha256",
                        "input_version",
                        "brief_sha256",
                        "plan_sha256",
                        "runtime_sha256",
                        "execution_source_sha256",
                        "permit_sha256",
                    )
                },
                round_number=state.active,
                **target,
                timeout_seconds=pin["timeout_seconds"],
                probe_timeout_seconds=PROBE_TIMEOUT_SECONDS,
                reserved_seconds=pin["timeout_seconds"] + PROBE_TIMEOUT_SECONDS,
                max_results=permit["max_results"],
                budget=deepcopy(saved["query_budget"]),
                execution_authority="separate-research-permit",
            )
            digest = sha(canonical(document))
            return dict(
                offer_ref=digest,
                offer_sha256=digest,
                revision=saved["revision"],
                document=document,
            )

    def execute(self, token, ref, request, *, deadline):
        with self._lock:
            require(not self._closing, "query-service-closing", 503)
            p, principal = self._access(token, ref)
            require(
                isinstance(request, dict)
                and set(request)
                == {
                    "key",
                    "revision",
                    "index_sha256",
                    "input_version",
                    "offer_ref",
                    "offer_sha256",
                    "confirmed",
                },
                "query-request-fields",
                400,
            )
            require(
                isinstance(request["key"], str)
                and KEY.fullmatch(request["key"])
                and type(request["revision"]) is int
                and 0 <= request["revision"] < 2**63
                and request["confirmed"] is True,
                "query-explicit-request-required",
                400,
            )
            require(
                all(
                    request[k] == p["item"][k]
                    for k in ("index_sha256", "input_version")
                ),
                "query-request-binding-differs",
            )
            digest = sha(
                canonical({k: v for k, v in request.items() if k != "revision"})
            )
            key = sha(canonical([principal, request["key"]]))
            saved = self.store.snapshot(p["pid"])
            old = saved["intents"].get(key)
            if old is not None:
                require(
                    old["request_sha256"] == digest, "query-idempotency-payload-differs"
                )
                return deepcopy(old)
            offer = self.offer(token, ref)
            require(
                request["offer_ref"] == offer["offer_ref"]
                and request["offer_sha256"] == offer["offer_sha256"],
                "query-offer-differs",
            )
            require(request["revision"] == saved["revision"], "query-stale-revision")
            require(
                type(deadline) in (int, float)
                and math.isfinite(deadline)
                and time.monotonic() < deadline,
                "query-request-expired",
                408,
            )
            row = dict(
                client_key=request["key"],
                principal=principal,
                method="stage1/planned-query",
                status="dispatch-unobserved",
                request=deepcopy(request),
                request_sha256=digest,
                offer=offer["document"],
                model_execution=False,
                automatic_retry=False,
            )
            self._check_storage()
            with self.store._edit(
                p["pid"],
                p["owner"],
                saved["revision"],
                "query-intent-budget-reserved",
                row,
            ) as state:
                state["intents"][key] = deepcopy(row)
                state["query_budget"]["attempts"] += 1
                state["query_budget"]["seconds"] += offer["document"][
                    "reserved_seconds"
                ]
            worker = threading.Thread(
                target=self._run, args=(ref, p, key, deadline), daemon=True
            )
            self._workers[ref] = worker
            try:
                worker.start()
            except BaseException:
                self._check_control()
                with self.store._edit(
                    p["pid"], p["owner"], None, "query-worker-start-unobserved", {}
                ) as state:
                    state["intents"][key]["status"] = "execution-unknown"
                raise
            return deepcopy(row)

    def _run(self, ref, p, key, deadline):
        with self._lock:
            row = deepcopy(self.store.snapshot(p["pid"])["intents"][key])
            self._check_control()
        entered = False
        try:
            with self._lock:
                self._check_storage()
                with self.store._edit(
                    p["pid"], p["owner"], None, "query-worker-dispatching", {}
                ) as state:
                    state["intents"][key]["status"] = "dispatching"
            target = row["offer"]

            def gate(event):
                require(
                    time.monotonic() < deadline, "query-admission-deadline-expired", 408
                )
                self._check_storage()
                item, permit, _, pin = inspect_registration(ref, p["item"])
                check_execution_source(
                    self._verify_source, ref, item, event, self._execute
                )
                with self._lock:
                    require(not self._closing, "query-service-closing", 503)
                    current = self.store.snapshot(p["pid"])
                    require(current["owner"]["token"] == p["owner"], "query-owner-lost")
                if event == "before-runner":
                    require(
                        tree_sha(item["ledger_root"]) == current["query_ledger_sha256"],
                        "query-ledger-changed",
                    )
                else:
                    require(
                        isinstance(event, dict)
                        and set(event)
                        == {"query_id", "backend", "argv", "runtime_sha256"}
                        and event["query_id"] == query
                        and event["backend"] == target["backend"]
                        and event["runtime_sha256"] == item["runtime_sha256"]
                        and event["argv"]
                        == command(
                            pin,
                            "search",
                            target["arguments"],
                            target["backend"],
                            event["argv"][event["argv"].index("--audit-output") + 1],
                        ),
                        "query-spawn-binding-differs",
                    )
                before = tree_sha(item["ledger_root"])
                require(
                    self._admit(
                        deepcopy(
                            dict(
                                project_ref=ref,
                                principal=row["principal"],
                                permit_sha256=item["permit_sha256"],
                                execution_source_sha256=item["execution_source_sha256"],
                                offer=target,
                                client_key=row["client_key"],
                                budget=current["query_budget"],
                                phase=event,
                            )
                        )
                    )
                    is True,
                    "query-admission-refused",
                    403,
                )
                # A provider return cannot cache runtime/config or source guards.
                self._check_storage()
                item, permit, _, pin = inspect_registration(ref, p["item"])
                check_execution_source(
                    self._verify_source, ref, item, event, self._execute
                )
                require(
                    tree_sha(item["ledger_root"]) == before,
                    "query-source-changed-during-admission",
                )
                with self._lock:
                    require(not self._closing, "query-service-closing", 503)
                    require(
                        self.store.snapshot(p["pid"])["owner"]["token"] == p["owner"],
                        "query-owner-lost",
                    )
                require(
                    time.monotonic() < deadline, "query-admission-deadline-expired", 408
                )
                require(
                    time.time() + pin["timeout_seconds"] < permit["expires_at_unix"],
                    "query-permit-expired-during-admission",
                )
                return True

            gate("before-runner")  # Covers the runner's isolated Python probe as well.
            ledger = CoverageLedger(p["item"]["ledger_root"])
            # Any uncertain ledger mutation preserves an unknown attempt.
            entered = True
            query = target["query_id"] or ledger.start_planned(target["planned_id"])
            require(
                ledger.event(query, "ActionStarted")["arguments"]
                == target["arguments"],
                "query-exact-arguments-differ",
            )
            result = self._execute(
                ledger.root, query, target["backend"], before_spawn=gate
            )
            finished = ledger.event(result, "ActionFinished")
            attempt = ledger.event(finished["attempt_id"], "ActionStarted")
            require(
                attempt["parent_id"] == query
                and attempt["backend"] == target["backend"],
                "query-completion-binding-differs",
            )
            state = ledger.coverage_state()
            children = [s for s in state.starts.values() if s.get("parent_id") == query]
            completed = set(state.binding["backends"]) == {
                s["backend"] for s in children
            } and not any(s["event_id"] in ledger.pending() for s in children)
            query_result = ledger.complete_query(query) if completed else None
            if completed:
                ledger.extract()
            row.update(
                status="completed",
                result=dict(
                    query_id=query,
                    backend_result_id=result,
                    backend_outcome=finished["outcome"],
                    query_result_id=query_result,
                    execution_ref=finished.get("execution_ref"),
                    stage_complete=False,
                ),
                outcome="observed",
            )
        except Exception as error:
            row.update(
                status="execution-unknown" if entered else "completed",
                outcome="unknown" if entered else "refused-known-unsent",
                error=dict(
                    code=getattr(error, "code", "query-operation-failed"),
                    type=type(error).__name__,
                ),
            )
        with self._lock:
            self._check_control()
            with self.store._edit(
                p["pid"], p["owner"], None, "query-worker-observation", row
            ) as state:
                state["intents"][key] = row
                state["query_ledger_sha256"] = tree_sha(p["item"]["ledger_root"])

    def close(self):
        with self._lock:
            self._closing = True
        for worker in tuple(self._workers.values()):
            if worker.ident is not None:
                worker.join(2)
        require(
            not any(w.is_alive() for w in self._workers.values()),
            "query-worker-cleanup-unobserved",
            503,
        )
        with self._lock:
            if not self._closed:
                self._check_control()
                self.store.close()
                self.ledger_owners.close()
                self._closed = True

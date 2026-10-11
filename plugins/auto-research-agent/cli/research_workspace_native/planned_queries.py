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
from stage1_ledger.validation import validate_run
from stage1_retrieval.runner import execute as execute_backend
from stage1_retrieval.receipt import command
from research_workspace_native.planned_query_contract import (
    KEY,
    HASH,
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


SAVED_OPERATIONS = {
    "stage1-claim",
    "stage1-coverage",
    "stage1-screen",
    "stage1-plan-query",
    "stage1-checkpoint",
    "stage1-export",
    "stage1-import-saved",
}


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
        check_resources=None,
    ):
        require(
            callable(authenticate)
            and callable(admit)
            and callable(verify_source)
            and callable(executor)
            and (check_resources is None or callable(check_resources)),
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
        self._check_resources = check_resources
        self._lock, self._closed, self._workers, self._projects = (
            threading.RLock(),
            False,
            {},
            {},
        )
        self._closing = False
        prepared = [
            (
                ref,
                *inspect_registration(
                    ref, item, require_ready=False, allow_closed=True
                ),
            )
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
        pending = [ledger.event(key) for key in ledger.pending()]
        require(
            not any(row.get("operation") == "backend" for row in pending),
            "query-pending-backend",
        )
        require(
            all(
                row.get("kind") == "ActionStarted" and row.get("operation") == "search"
                for row in pending
            ),
            "query-pending-source",
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

    def _saved_owner(self, p, saved):
        require(not self._closing, "query-service-closing", 503)
        require(
            (saved.get("owner") or {}).get("token") == p["owner"]
            and self.store._owners.get(p["pid"], (None,))[0] == p["owner"],
            "query-owner-lost",
        )
        try:
            held = (
                self.store._owners[p["pid"]][1].in_transaction
                and len(self.ledger_owners.connections) == len(self._projects)
                and all(
                    connection.in_transaction
                    for connection in self.ledger_owners.connections
                )
            )
        except sqlite3.Error:
            held = False
        require(held, "query-ledger-owner-lost")
        require(saved.get("query_binding") == p["item"], "query-saved-binding-differs")
        history = self.store.events(p["pid"])
        require(
            history
            and history[-1]["revision"] == saved["revision"]
            and history[-1]["state_sha256"] == sha(canonical(saved)),
            "query-saved-state-history-differs",
        )
        marker = Path(str(self.store.path) + ".created")
        expected = canonical(
            dict(
                kind="Stage1QueryBudgetJournal",
                schema_version="1.0.0",
                registrations={
                    ref: entry["item"] for ref, entry in self._projects.items()
                },
            )
        )
        require(
            self.store.path.is_file()
            and marker.is_file()
            and marker.stat().st_size == len(expected)
            and marker.read_bytes() == expected,
            "query-budget-marker-differs",
        )

    def _saved_frontier(self, ref, p, saved):
        self._check_storage()
        self._saved_owner(p, saved)
        item, _, _, _ = inspect_registration(
            ref, p["item"], require_ready=False, allow_closed=True
        )
        require(
            not any(row["status"] != "completed" for row in saved["intents"].values()),
            "query-unreconciled-action",
        )
        ledger = CoverageLedger(item["ledger_root"])
        # An unexecuted planned search is not a pending external write. Backend
        # and source attempts, including imported-source writes, must be settled.
        require(
            all(
                ledger.event(key).get("kind") == "ActionStarted"
                and ledger.event(key).get("operation") == "search"
                for key in ledger.pending()
            ),
            "query-pending-write",
        )
        report = validate_run(ledger.root)
        require(report["valid"], "query-saved-ledger-invalid")
        events = ledger.events()
        current = tree_sha(ledger.root)
        require(current == saved["query_ledger_sha256"], "query-ledger-changed")
        return (
            ledger,
            events,
            dict(
                tree_sha256=current,
                state_sha256=report["state_sha256"],
                ledger_state_sha256=report["state_sha256"],
                journal_sequence=len(events),
                journal_head_sha256=events[-1]["event_sha256"] if events else "0" * 64,
            ),
        )

    @staticmethod
    def _saved_observation(ledger, before):
        report = validate_run(ledger.root)
        after = ledger.events()
        require(after[: len(before)] == before, "query-saved-history-differs")
        return dict(
            valid=report["valid"],
            core_events=deepcopy(after[len(before) :]),
            tree_sha256=tree_sha(ledger.root),
            state_sha256=report["state_sha256"],
            journal_sequence=len(after),
            journal_head_sha256=after[-1]["event_sha256"] if after else "0" * 64,
        )

    def inspect_saved(self, token, ref):
        """Read an owned saved frontier without offering or admitting a search.

        No source verifier/admission callback runs under this lock. A project
        adapter must check its current intake binding before taking the query lock.
        """
        with self._lock:
            p, _ = self._access(token, ref)
            saved = self.store.snapshot(p["pid"])
            _, _, frontier = self._saved_frontier(ref, p, saved)
            return dict(
                project_ref=ref,
                revision=saved["revision"],
                **frontier,
                budget=deepcopy(saved["query_budget"]),
                operation_scope="saved-ledger-only",
                execution_authorized=False,
            )

    def mutate_saved(
        self, token, ref, key, request_sha256, expected_tree_sha256, operation, producer
    ):
        """Trusted local adapter only; producer(ledger) grants no external I/O.

        There is no browser route. The adapter supplies an already-authorized
        local Core producer after checking/reserving its intake action. Replay is
        history-only; the existing ledger owner and lock serialize fresh writes.
        """
        with self._lock:
            p, principal = self._access(token, ref)
            require(
                isinstance(key, str) and KEY.fullmatch(key), "query-key-invalid", 400
            )
            require(
                isinstance(operation, str) and operation in SAVED_OPERATIONS,
                "query-saved-operation-invalid",
                400,
            )
            require(
                all(
                    isinstance(value, str) and HASH.fullmatch(value)
                    for value in (request_sha256, expected_tree_sha256)
                ),
                "query-saved-hash-required",
                400,
            )
            identity = dict(
                operation=operation,
                request_sha256=request_sha256,
                expected_tree_sha256=expected_tree_sha256,
            )
            intent_key = sha(canonical([principal, key]))
            saved = self.store.snapshot(p["pid"])
            old = saved["intents"].get(intent_key)
            if old is not None:
                require(
                    old.get("method") == "stage1/saved-ledger"
                    and old.get("request") == identity,
                    "query-idempotency-payload-differs",
                )
                return deepcopy(old)
            require(callable(producer), "query-saved-producer-required", 400)
            require(len(saved["intents"]) < 256, "query-saved-action-bound", 429)
            ledger, before, frontier = self._saved_frontier(ref, p, saved)
            require(
                frontier["tree_sha256"] == expected_tree_sha256,
                "query-saved-frontier-stale",
            )
            row = dict(
                client_key=key,
                principal=principal,
                method="stage1/saved-ledger",
                status="dispatch-unobserved",
                request=identity,
                request_sha256=request_sha256,
                previous_frontier=frontier,
                model_execution=False,
                external_execution=False,
                automatic_retry=False,
            )
            with self.store._edit(
                p["pid"], p["owner"], saved["revision"], "saved-ledger-intent", row
            ) as state:
                state["intents"][intent_key] = deepcopy(row)
            # This transaction has committed before the producer can touch Core.
            try:
                output = producer(ledger)
                output = json.loads(canonical(output))
                self._check_storage()
                current = self.store.snapshot(p["pid"])
                self._saved_owner(p, current)
                require(
                    current["query_budget"] == saved["query_budget"]
                    and current["query_ledger_sha256"] == expected_tree_sha256
                    and current["intents"].get(intent_key, {}).get("request")
                    == identity,
                    "query-saved-control-differs",
                )
                inspect_registration(
                    ref, p["item"], require_ready=False, allow_closed=True
                )
                require(
                    all(
                        ledger.event(key).get("kind") == "ActionStarted"
                        and ledger.event(key).get("operation") == "search"
                        for key in ledger.pending()
                    ),
                    "query-pending-write",
                )
                observation = self._saved_observation(ledger, before)
                row["core_observation"] = observation
                require(observation["valid"], "query-saved-ledger-invalid")
                new_tree = observation["tree_sha256"]
                row.update(
                    status="completed",
                    outcome="observed",
                    result=output,
                )
                with self.store._edit(
                    p["pid"], p["owner"], None, "saved-ledger-observation", row
                ) as state:
                    state["intents"][intent_key] = deepcopy(row)
                    state["query_ledger_sha256"] = new_tree
            except BaseException as error:
                output = row.pop("result", None)
                row.update(
                    status="execution-unknown",
                    outcome="unknown",
                    error=dict(
                        code="query-saved-operation-failed", type=type(error).__name__
                    ),
                )
                if output is not None:
                    row["output_observation"] = output
                if "core_observation" not in row:
                    try:
                        row["core_observation"] = self._saved_observation(
                            ledger, before
                        )
                    except (
                        ValueError,
                        OSError,
                        KeyError,
                        TypeError,
                    ) as observation_error:
                        row["observation_error"] = type(observation_error).__name__
                self._check_control()
                with self.store._edit(
                    p["pid"], p["owner"], None, "saved-ledger-unknown", row
                ) as state:
                    state["intents"][intent_key] = deepcopy(row)
                if not isinstance(error, Exception):
                    raise
            return deepcopy(row)

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
                # No service lock is held here: project resources use the
                # intake->service order elsewhere. This checker has no source
                # callback, so the last verifier cannot cache resource state.
                if self._check_resources is not None:
                    require(
                        self._check_resources(
                            dict(
                                project_ref=ref,
                                principal=row["principal"],
                                offer=deepcopy(target),
                                client_key=row["client_key"],
                                phase=deepcopy(event),
                            )
                        )
                        is True,
                        "query-final-resource-check-refused",
                        403,
                    )
                # The resource checker can wait on local SQLite/files. Its
                # return cannot cache ownership, shutdown or either deadline.
                # Only callback-free checks remain, with no intake lock here.
                with self._lock:
                    require(not self._closing, "query-service-closing", 503)
                    self._check_storage()
                    require(
                        (self.store.snapshot(p["pid"])["owner"] or {}).get("token")
                        == p["owner"],
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

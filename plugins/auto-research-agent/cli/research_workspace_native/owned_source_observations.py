"""Owned local source observations, separate from any external acquisition job.

Generic query/saved writers still refuse pending source reads. This trusted
adapter recognizes only the exact source start it previously committed under
the same owner, preserves unknown local writes, and never dispatches a reader.
An independent source permit and bounded transport are still required for I/O.
"""

from copy import deepcopy
import json

from stage1_coverage.run import CoverageLedger
from stage1_ledger.validation import validate_run
from stage1_ledger.source_arguments import check_source_arguments
from stage1_deliverable.common import canonical, sha

from .planned_queries import PlannedQueryService
from .planned_query_contract import HASH, KEY, inspect_registration, require, tree_sha


class OwnedSourceObservations:
    def __init__(self, service):
        require(isinstance(service, PlannedQueryService), "source-query-owner-required")
        self.service = service

    def _frontier(self, ref, project, saved):
        service = self.service
        service._check_storage()
        service._saved_owner(project, saved)
        item, _, _, _ = inspect_registration(ref, project["item"], require_ready=False)
        require(
            not any(row["status"] != "completed" for row in saved["intents"].values()),
            "source-unreconciled-local-action",
        )
        ledger = CoverageLedger(item["ledger_root"])
        require(
            tree_sha(ledger.root) == saved["query_ledger_sha256"],
            "source-ledger-changed",
        )
        report, events = validate_run(ledger.root), ledger.events()
        require(report["valid"], "source-ledger-invalid")
        readings = saved.get("source_read_observations", {})
        pending = []
        for key in ledger.pending():
            event = ledger.event(key)
            if (
                event.get("kind") == "ActionStarted"
                and event.get("operation") == "search"
            ):
                continue
            observation = readings.get(key)
            require(
                event.get("kind") == "SourceReadStarted"
                and observation is not None
                and observation["start"] == event
                and observation["start_sha256"] == sha(canonical(event)),
                "source-pending-attempt-unowned",
            )
            intent = saved["intents"].get(observation["intent_key"])
            require(
                intent is not None
                and intent["method"] == "stage1/source-observation"
                and intent["status"] == "completed"
                and intent["request"]["operation"] == "start"
                and intent["result"]["source_id"] == key
                and intent["request_sha256"] == observation["request_sha256"]
                and intent["principal"] == observation["principal"],
                "source-start-owner-history-differs",
            )
            pending.append(key)
        require(len(pending) <= 1, "source-pending-attempt-bound")
        return (
            ledger,
            events,
            dict(
                tree_sha256=saved["query_ledger_sha256"],
                ledger_state_sha256=report["state_sha256"],
                pending_source_ids=pending,
                operation_scope="local-source-observations-only",
                external_execution=False,
                automatic_retry=False,
            ),
        )

    def read(self, token, ref):
        """No restore, source verification, admission, fetch, or Core write."""
        with self.service._lock:
            project, _ = self.service._access(token, ref)
            saved = self.service.store.snapshot(project["pid"])
            return deepcopy(self._frontier(ref, project, saved)[2])

    def _mutate(
        self, token, ref, key, digest, expected_tree, operation, payload, producer
    ):
        service = self.service
        require(
            isinstance(key, str)
            and KEY.fullmatch(key)
            and isinstance(digest, str)
            and HASH.fullmatch(digest)
            and isinstance(expected_tree, str)
            and HASH.fullmatch(expected_tree),
            "source-local-binding-required",
            400,
        )
        identity = dict(
            operation=operation,
            payload=deepcopy(payload),
            expected_tree_sha256=expected_tree,
        )
        require(
            len(canonical(identity)) <= 65536, "source-local-request-too-large", 400
        )
        with service._lock:
            project, principal = service._access(token, ref)
            intent_key = sha(canonical([principal, key]))
            saved = service.store.snapshot(project["pid"])
            old = saved["intents"].get(intent_key)
            if old is not None:
                require(
                    old.get("method") == "stage1/source-observation"
                    and old.get("request") == identity
                    and old.get("request_sha256") == digest,
                    "source-idempotency-payload-differs",
                )
                return deepcopy(old)  # Including unknown: never rerun the producer.
            require(len(saved["intents"]) < 256, "source-local-action-bound", 429)
            ledger, before, frontier = self._frontier(ref, project, saved)
            require(
                frontier["tree_sha256"] == expected_tree, "source-local-frontier-stale"
            )
            if operation == "start":
                require(
                    not frontier["pending_source_ids"], "source-attempt-already-pending"
                )
            else:
                require(
                    frontier["pending_source_ids"] == [payload["source_id"]],
                    "source-finish-owned-start-required",
                )
                require(
                    saved["source_read_observations"][payload["source_id"]]["principal"]
                    == principal,
                    "source-finish-principal-differs",
                )

            def check_owner():
                service._check_storage()
                service._saved_owner(project, service.store.snapshot(project["pid"]))

            row = dict(
                client_key=key,
                principal=principal,
                method="stage1/source-observation",
                status="dispatch-unobserved",
                request=identity,
                request_sha256=digest,
                previous_frontier=frontier,
                external_execution=False,
                model_execution=False,
                automatic_retry=False,
            )
            with service.store._edit(
                project["pid"],
                project["owner"],
                saved["revision"],
                "source-observation-intent",
                row,
                check_current=check_owner,
            ) as current:
                current["intents"][intent_key] = deepcopy(row)
            try:
                check_owner()
                result = json.loads(canonical(producer(ledger)))
                require(
                    len(canonical(result)) <= 256 * 1024,
                    "source-local-result-too-large",
                )
                row["output_observation"] = deepcopy(result)
                service._check_storage()
                current = service.store.snapshot(project["pid"])
                service._saved_owner(project, current)
                require(
                    current["query_budget"] == saved["query_budget"]
                    and current["query_ledger_sha256"] == expected_tree
                    and current["intents"][intent_key]["request"] == identity,
                    "source-local-control-differs",
                )
                inspect_registration(ref, project["item"], require_ready=False)
                observation = service._saved_observation(ledger, before)
                row["core_observation"] = observation
                require(observation["valid"], "source-local-write-invalid")
                changed = [event["payload"] for event in ledger.events()[len(before) :]]
                source_id = result["source_id"]
                start = ledger.event(source_id, "SourceReadStarted")
                if operation == "start":
                    require(
                        changed == [start]
                        and all(
                            key == source_id
                            or (
                                ledger.event(key)["kind"] == "ActionStarted"
                                and ledger.event(key)["operation"] == "search"
                            )
                            for key in ledger.pending()
                        ),
                        "source-start-event-differs",
                    )
                    require(
                        all(start[name] == value for name, value in payload.items()),
                        "source-start-request-differs",
                    )
                else:
                    finish = ledger.event(
                        result["finish_event_id"], "SourceReadFinished"
                    )
                    require(
                        source_id == payload["source_id"]
                        and finish["attempt_id"] == source_id
                        and changed[-1] == finish
                        and all(
                            event["kind"] == "ArtifactStored"
                            and event["ref"]["producer"] == source_id
                            for event in changed[:-1]
                        ),
                        "source-finish-event-differs",
                    )
                    require(
                        not any(
                            ledger.event(key)["kind"] == "SourceReadStarted"
                            for key in ledger.pending()
                        ),
                        "source-finish-still-pending",
                    )
                row.update(status="completed", outcome="observed", result=result)

                with service.store._edit(
                    project["pid"],
                    project["owner"],
                    None,
                    "source-observation-finished",
                    row,
                    check_current=check_owner,
                ) as state:
                    state["intents"][intent_key] = deepcopy(row)
                    state["query_ledger_sha256"] = observation["tree_sha256"]
                    readings = state.setdefault("source_read_observations", {})
                    if operation == "start":
                        readings[source_id] = dict(
                            start=deepcopy(start),
                            start_sha256=sha(canonical(start)),
                            intent_key=intent_key,
                            request_sha256=digest,
                            principal=principal,
                        )
                    else:
                        readings[source_id]["finish_event_id"] = result[
                            "finish_event_id"
                        ]
            except BaseException as error:
                output = row.pop("result", None)
                row.update(
                    status="execution-unknown",
                    outcome="unknown",
                    error=dict(
                        code="source-local-operation-failed", type=type(error).__name__
                    ),
                )
                if output is not None:
                    row["output_observation"] = output
                if "core_observation" not in row:
                    try:
                        row["core_observation"] = service._saved_observation(
                            ledger, before
                        )
                    except (ValueError, OSError, KeyError, TypeError) as failure:
                        row["observation_error"] = type(failure).__name__
                service._check_control()
                with service.store._edit(
                    project["pid"],
                    project["owner"],
                    None,
                    "source-observation-unknown",
                    row,
                ) as state:
                    state["intents"][intent_key] = deepcopy(row)
                if not isinstance(error, Exception):
                    raise
            return deepcopy(row)

    def start(self, token, ref, key, request_sha256, expected_tree_sha256, arguments):
        require(
            type(arguments) is dict
            and set(arguments)
            == {
                "work_id",
                "version_id",
                "source_uri",
                "tool",
                "request",
                "actor",
                "reason",
            },
            "source-start-arguments-differ",
            400,
        )
        # Reject recognizable credentials before persisting a local intent.
        check_source_arguments(dict(kind="SourceReadStarted", **arguments))
        return self._mutate(
            token,
            ref,
            key,
            request_sha256,
            expected_tree_sha256,
            "start",
            arguments,
            lambda ledger: dict(source_id=ledger.start_source(**arguments)),
        )

    def finish(
        self, token, ref, key, request_sha256, expected_tree_sha256, source_id, producer
    ):
        require(callable(producer), "source-local-producer-required", 400)
        return self._mutate(
            token,
            ref,
            key,
            request_sha256,
            expected_tree_sha256,
            "finish",
            dict(source_id=source_id),
            producer,
        )

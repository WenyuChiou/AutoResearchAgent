"""Explicit fixed-byte engineering replay, never a live search permission.

Only a trusted launcher can select this service. Browser requests retain the
ordinary project/revision/confirmation/journal contract and select a planned
query, never paths, responses, permissions or executable callbacks. No network,
subprocess, runtime probe, model, screening or review is performed here.
"""

import json
from pathlib import Path

from stage1_ledger.contracts import check_record
from stage1_ledger.journal import canonical
from .planned_query_contract import raw_file, require
from .project_intake_contract import _fields
from .project_stage1 import BODY_FIELDS, ProjectStage1Service
from .session_api import _check, _hash


class FixedReplayInputs:
    def __init__(self, path, expected_sha256):
        self.path = Path(path)
        self.sha256 = expected_sha256
        self.load()

    def load(self):
        def pairs(items):
            value = {}
            for key, item in items:
                require(key not in value, "fixed-replay-duplicate-field")
                value[key] = item
            return value

        value = json.loads(
            raw_file(self.path, self.sha256, 262144), object_pairs_hook=pairs
        )
        require(
            type(value) is dict
            and set(value)
            == {
                "kind",
                "schema_version",
                "scope",
                "project_ref",
                "input_version",
                "brief_sha256",
                "plan_manifest_sha256",
                "responses",
            },
            "fixed-replay-fields",
        )
        require(
            value["kind"] == "Stage1FixedOfflineReplay"
            and value["schema_version"] == "1.0.0"
            and value["scope"] == "authored-engineering-only",
            "fixed-replay-scope",
        )
        require(
            type(value["input_version"]) is int and value["input_version"] > 0,
            "fixed-replay-integer-input-required",
        )
        require(
            type(value["responses"]) is list and 0 < len(value["responses"]) <= 256,
            "fixed-replay-responses-required",
        )
        seen = set()
        for row in value["responses"]:
            require(
                type(row) is dict
                and set(row)
                == {
                    "query",
                    "purpose",
                    "year",
                    "backend",
                    "records_path",
                    "records_sha256",
                    "http_status",
                },
                "fixed-replay-response-fields",
            )
            require(
                all(
                    type(row[k]) is str and 0 < len(row[k]) <= 8192
                    for k in ("query", "purpose", "backend", "records_path")
                )
                and (row["year"] is None or type(row["year"]) is str)
                and type(row["http_status"]) is int
                and 200 <= row["http_status"] < 300,
                "fixed-replay-response-invalid",
            )
            key = (row["query"], row["purpose"], row["year"], row["backend"])
            require(key not in seen, "fixed-replay-response-ambiguous")
            seen.add(key)
            relative = Path(row["records_path"])
            require(
                not relative.is_absolute()
                and not relative.drive
                and ".." not in relative.parts,
                "fixed-replay-relative-input-required",
            )
            path = self.path.parent / relative
            raw = raw_file(path, row["records_sha256"], 1024 * 1024)
            records = json.loads(raw, object_pairs_hook=pairs)
            require(
                type(records) is list and len(records) <= 100,
                "fixed-replay-record-bound",
            )
            for record in records:
                check_record(record)
            row["_raw"], row["_count"] = raw, len(records)
        return value


class FixedReplayStage1Service(ProjectStage1Service):
    def __init__(self, intake, *, fixed_inputs):
        require(type(fixed_inputs) is FixedReplayInputs, "fixed-replay-inputs-required")
        super().__init__(intake)
        self.fixed_inputs = fixed_inputs
        require(
            not fixed_inputs.path.resolve().is_relative_to(intake.root.resolve())
            and not intake.root.resolve().is_relative_to(
                fixed_inputs.path.parent.resolve()
            ),
            "fixed-replay-storage-overlap",
        )

    def _selected(self, ref, binding, run, ledger, query, config=None, coverage=None):
        config = self.fixed_inputs.load() if config is None else config
        require(
            config["project_ref"] == ref
            and all(
                type(config[k]) is type(binding[k]) and config[k] == binding[k]
                for k in ("input_version", "brief_sha256", "plan_manifest_sha256")
            ),
            "fixed-replay-project-input-differs",
        )
        settings = binding["settings"]
        require(
            not any(settings["consent"].values())
            and all(v == 0 for v in settings["budgets"].values()),
            "fixed-replay-zero-research-envelope-required",
        )
        require(
            not run.get("query_owned") and ledger.manifest["mode"] == "offline-import",
            "fixed-replay-offline-ledger-required",
        )
        require(
            (coverage or ledger.coverage_state()).active == 1,
            "fixed-replay-first-round-only",
        )
        require(query is not None, "stage1-query-offer-differs")
        matches = [
            row
            for row in config["responses"]
            if all(row[k] == query[k] for k in ("query", "purpose", "year"))
        ]
        require(
            {row["backend"] for row in matches} == set(self.backends)
            and len(matches) == len(self.backends),
            "fixed-replay-template-missing",
        )
        return matches

    def _history(self, ref, binding, run, ledger, queries, config):
        """Attribute immutable attempts, not merely completed planned query IDs.

        Original receipts already pin the complete config (including project,
        typed version, brief and plan) and response bytes. Those are sufficient
        for legacy attribution; an unpinned attempt is Unknown, never upgraded.
        validate_run in _ledger verifies the saved artifact bytes and query links.
        """
        events = [event["payload"] for event in ledger.events()]
        coverage = ledger.coverage_state()
        completed = {e["query_id"] for e in events if e["kind"] == "QueryEvent"}
        finishes = {e["attempt_id"]: e for e in events if e["kind"] == "ActionFinished"}
        attributed_ids = {qid for q in queries for qid in q["recorded_query_ids"]}
        reason = (
            "fixed-replay-history-unattributed"
            if any(
                e["kind"] == "ActionStarted"
                and e["operation"] == "search"
                and e["event_id"] not in attributed_ids
                for e in events
            )
            else None
        )
        for query in queries:
            inputs = self._selected(ref, binding, run, ledger, query, config, coverage)
            expected = {row["backend"]: row for row in inputs}
            states, pins = [], set()
            for query_id in query["recorded_query_ids"]:
                attempts = [
                    e
                    for e in events
                    if e["kind"] == "ActionStarted"
                    and e["operation"] == "backend"
                    and e["parent_id"] == query_id
                ]
                state = "current"
                if not attempts:
                    state = "unknown"
                for attempt in attempts:
                    args = attempt["arguments"]
                    pin = args.get("config_sha256")
                    if isinstance(pin, str):
                        pins.add(pin)
                    row = expected.get(attempt["backend"])
                    if not pin or args.get("mode") != "fixed-offline-engineering":
                        state = "unknown"
                    elif pin != self.fixed_inputs.sha256:
                        state = "different"
                    elif (
                        row is None
                        or args.get("records_sha256") != row["records_sha256"]
                        or args.get("network") is not False
                        or args.get("model") is not False
                    ):
                        state = "unknown"
                    finish = finishes.get(attempt["event_id"])
                    if pin == self.fixed_inputs.sha256 and finish is not None:
                        if (
                            row is None
                            or finish.get("records", {}).get("sha256")
                            != row["records_sha256"]
                            or finish.get("http_status") != row["http_status"]
                            or finish.get("result_count") != row["_count"]
                        ):
                            state = "unknown"
                if state == "current" and (
                    query_id not in completed
                    or sorted(a["backend"] for a in attempts) != sorted(expected)
                ):
                    state = "incomplete"
                states.append(state)
            query["historical_config_sha256"] = sorted(pins)
            if "different" in states:
                query["status"] = "fixed-replay-history-config-differs"
                reason = query["status"]
            elif "unknown" in states:
                query["status"] = "fixed-replay-history-unattributed"
                reason = reason or query["status"]
            elif states and all(s == "current" for s in states):
                query["status"] = "fixed-replay-recorded"
            # Incomplete current attempts retain the ordinary unknown-write barrier.
        return reason

    def read(self, credential, project_ref):
        with self.intake._lock:
            result = super().read(credential, project_ref)
            status = dict(
                mode="fixed-offline-engineering",
                config_sha256=self.fixed_inputs.sha256,
                network=False,
                model=False,
                research_authorized=False,
                reason=None,
                completed_queries=0,
            )
            result["fixed_replay"] = status
            if result["ledger"] is None:
                return result
            state = self.intake._load(self.intake._principal(credential), project_ref)
            binding = self.intake.binding(project_ref)
            run, ledger, _ = self._ledger(state, binding)
            try:
                config = self.fixed_inputs.load()
            except Exception as error:
                status["reason"] = getattr(error, "code", "fixed-replay-input-invalid")
                return result
            try:
                status["reason"] = self._history(
                    project_ref, binding, run, ledger, result["queries"], config
                )
            except Exception as error:
                status["reason"] = getattr(error, "code", "fixed-replay-input-invalid")
                return result
            if result.get("coverage_actions", {}).get("held"):
                status["reason"] = (
                    status["reason"] or "stage1-coverage-write-outcome-unobserved"
                )
            for query in result["queries"]:
                query["execution_available"] = (
                    status["reason"] is None and query["status"] == "not-executed"
                )
            status["completed_queries"] = sum(
                q["status"] == "fixed-replay-recorded" for q in result["queries"]
            )
            status["planned_queries"] = len(result["queries"])
            return result

    def execute_query(self, credential, project_ref, body, *, check_deadline=None):
        # Match _mutate's public envelope checks before history/config reads or
        # the idempotency-key lookup. Attribution never accepts unchecked JSON.
        _fields(
            body,
            BODY_FIELDS | {"ledger_state_sha256", "query_ref", "query_sha256"},
        )
        _check(
            body["confirmed"] is True and _hash(body["ledger_state_sha256"]),
            "stage1-action-binding-invalid",
            400,
        )

        def selected(state, run, ledger, report, actor):
            binding = self.intake.binding(project_ref)
            query = next(
                (
                    q
                    for q in self._queries(run, ledger)
                    if q["query_ref"] == body["query_ref"]
                    and q["query_sha256"] == body["query_sha256"]
                ),
                None,
            )
            inputs = self._selected(project_ref, binding, run, ledger, query)
            require(
                query["status"] == "not-executed", "fixed-replay-query-already-recorded"
            )
            return query, inputs

        def produce(state, run, ledger, request_hash, actor):
            query, inputs = selected(state, run, ledger, None, actor)
            query_id = ledger.start_planned(query["planned_query_id"])
            for row in inputs:
                attempt = ledger.start(
                    "backend",
                    dict(
                        mode="fixed-offline-engineering",
                        config_sha256=self.fixed_inputs.sha256,
                        records_sha256=row["records_sha256"],
                        network=False,
                        model=False,
                    ),
                    backend=row["backend"],
                    parent_id=query_id,
                )
                raw = ledger.save_bytes(row["_raw"], producer=attempt)
                note = ledger.save_bytes(
                    canonical(
                        dict(
                            scope="fixed response replay, not live search",
                            actor=actor,
                            request_sha256=request_hash,
                        )
                    ),
                    producer=attempt,
                )
                ledger.finish(
                    attempt,
                    outcome="success_nonempty" if row["_count"] else "success_empty",
                    http_status=row["http_status"],
                    exit_code=0,
                    stdout=raw,
                    stderr=note,
                    records=raw,
                )
            completed = ledger.complete_query(query_id)
            extracted = ledger.extract()
            return dict(
                query_ref=query["query_ref"],
                query_event_id=query_id,
                completion_event_id=completed,
                mode="fixed-offline-engineering",
                config_sha256=self.fixed_inputs.sha256,
                extracted=extracted,
                execution_authorized=False,
                stage1_complete=False,
                canonical_package=None,
                ledger_state_sha256=ledger.state_hash(),
            )

        # _perform returns saved keys before reserve/preflight. Recheck the trusted
        # current input and historical attribution even for that read-only path.
        # Do not change legacy request hashes or overwrite their saved receipts.
        with self.intake._lock:
            principal = self.intake._principal(credential)
            state = self.intake._load(principal, project_ref)
            binding = self.intake.binding(project_ref)
            require(
                type(body.get("input_version")) is type(binding["input_version"])
                and body.get("input_version") == binding["input_version"]
                and body.get("brief_sha256") == binding["brief_sha256"],
                "fixed-replay-project-input-differs",
            )
            run, ledger, _ = self._ledger(state, binding)
            queries = self._queries(run, ledger)
            reason = self._history(
                project_ref,
                binding,
                run,
                ledger,
                queries,
                self.fixed_inputs.load(),
            )
            require(reason is None, reason or "fixed-replay-history-unattributed")
            saved = self.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                (principal, project_ref, body.get("key")),
            ).fetchone()
            if saved is not None:
                receipt = json.loads(saved["receipt"])
                pin = receipt.get("config_sha256")
                require(
                    pin is None or pin == self.fixed_inputs.sha256,
                    "fixed-replay-history-config-differs",
                )
                # Unknown outcomes may predate any attributable backend event.
                # They remain available through action history, not as a replay
                # under whichever trusted configuration happens to be loaded.
                require(
                    pin is not None
                    or any(
                        q["query_ref"] == body.get("query_ref")
                        and q["historical_config_sha256"] == [self.fixed_inputs.sha256]
                        for q in queries
                    ),
                    "fixed-replay-saved-action-unattributed",
                )
            return self._mutate(
                credential,
                project_ref,
                body,
                "stage1-execute-query",
                produce,
                fields={"query_ref", "query_sha256"},
                preflight=selected,
                check_deadline=check_deadline,
            )

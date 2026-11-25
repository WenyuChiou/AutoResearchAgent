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
from .project_stage1 import ProjectStage1Service


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

    def _selected(self, ref, binding, run, ledger, query, config=None):
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
        require(ledger.coverage_state().active == 1, "fixed-replay-first-round-only")
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
            if result.get("coverage_actions", {}).get("held"):
                status["reason"] = "stage1-coverage-write-outcome-unobserved"
                return result
            completed = {
                e["payload"]["query_id"]
                for e in ledger.events()
                if e["payload"]["kind"] == "QueryEvent"
            }
            for query in result["queries"]:
                if query["recorded_query_ids"] and all(
                    q in completed for q in query["recorded_query_ids"]
                ):
                    query["status"] = "fixed-replay-recorded"
                try:
                    self._selected(project_ref, binding, run, ledger, query, config)
                    query["execution_available"] = query["status"] == "not-executed"
                except Exception as error:
                    query["execution_available"] = False
                    status["reason"] = getattr(
                        error, "code", "fixed-replay-input-invalid"
                    )
            status["completed_queries"] = sum(
                q["status"] == "fixed-replay-recorded" for q in result["queries"]
            )
            status["planned_queries"] = len(result["queries"])
            return result

    def execute_query(self, credential, project_ref, body, *, check_deadline=None):
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

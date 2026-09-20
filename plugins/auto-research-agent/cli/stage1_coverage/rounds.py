"""Replay frozen plans, exact query bindings and complete-round receipts."""

from stage1_ledger.journal import LedgerError, decode, canonical, digest
from stage1_ledger.semantics import SUCCESS
from .plan import derive


def require(condition, message):
    if not condition:
        raise LedgerError(message)


class CoverageReplay:
    def __init__(self, manifest, read_ref):
        from .evidence import EvidenceReplay

        self.manifest, self.read_ref = manifest, read_ref
        self.plan = self.plan_ref = self.binding = self.active = None
        self.queries, self.starts, self.completed, self.receipts = {}, {}, {}, {}
        self.works, self.baseline = set(), set()
        self.closed = []
        self.evidence = EvidenceReplay()
        self.round_yields, self.human_actions, self.material = [], [], []

    def expansion_arguments(self, operation, work_id, version_id):
        require(self.active is not None, "coverage-round-not-open")
        require(operation in {"references", "cited-by"}, "unknown-expansion-operation")
        work = self.evidence.candidates.get(work_id)
        require(
            work and version_id in work["version_ids"],
            "expansion-needs-discovered-version",
        )
        return dict(
            operation=operation,
            limit=self.binding["limit"],
            coverage=dict(
                plan_event_id=self.binding["event_id"],
                round_number=self.active,
                seed_work_id=work_id,
                seed_version_id=version_id,
            ),
        )

    def arguments(self, planned_id):
        require(self.active is not None, "coverage-round-not-open")
        require(planned_id in self.queries, "unknown-planned-query")
        query = self.queries[planned_id]
        return dict(
            query=query["query"],
            year=query["year"],
            rank_by=query["rank_by"],
            limit=self.binding["limit"],
            coverage=dict(
                plan_event_id=self.binding["event_id"],
                round_number=self.active,
                planned_query_id=planned_id,
            ),
        )

    def check_start(self, payload):
        if self.plan is None:
            return
        if payload["operation"] == "search":
            arguments = payload["arguments"]
            require(
                isinstance(arguments.get("coverage"), dict), "coverage-query-binding"
            )
            if "seed_work_id" in arguments.get("coverage", {}):
                seed = arguments["coverage"]
                require(
                    arguments
                    == self.expansion_arguments(
                        arguments.get("operation"),
                        seed["seed_work_id"],
                        seed.get("seed_version_id"),
                    ),
                    "coverage-expansion-binding",
                )
                return
            planned = arguments.get("coverage", {}).get("planned_query_id")
            require(planned in self.queries, "coverage-query-binding")
            require(arguments == self.arguments(planned), "coverage-query-binding")
        else:
            require(payload["backend"] in self.binding["backends"], "unplanned-backend")

    def summary(self):
        require(self.active is not None, "coverage-round-not-open")
        starts = {
            i: p
            for i, p in self.starts.items()
            if p["operation"] == "search"
            and p["arguments"].get("coverage", {}).get("round_number") == self.active
        }
        results = [p for p in self.completed.values() if p["query_id"] in starts]
        require(len(results) == len(starts), "round-has-pending-actions")
        attempted = {
            p["arguments"]["coverage"].get("planned_query_id") for p in results
        }
        missing = [i for i in self.queries if i not in attempted]
        failed, truncated = [], []
        for result in results:
            event_id = result["event_id"]
            if result["outcome"] not in SUCCESS or set(
                result["attempted_backends"]
            ) != set(self.binding["backends"]):
                failed.append(event_id)
            receipt = self.receipts.get(event_id)
            # At the cap, absence of an explicit provider continuation record cannot
            # establish exhaustiveness. Even a false caller flag cannot bypass it.
            if (
                receipt is None
                or receipt["truncated"] is not False
                or result["result_count"] >= self.binding["limit"]
            ):
                truncated.append(event_id)
        return dict(
            complete=not (missing or failed or truncated),
            query_event_ids=[p["event_id"] for p in results],
            missing_planned_ids=missing,
            failed_query_ids=failed,
            truncated_query_ids=truncated,
            new_discovered_work_ids=sorted(self.works - self.baseline),
        )

    def observe(self, payload):
        kind = payload["kind"]
        if kind == "CoveragePlanBound":
            require(self.plan is None, "plan-already-bound")
            require(not self.starts, "plan-must-precede-search")
            plan = decode(self.read_ref(payload["plan_ref"]), "bound plan")
            expected, queries = derive(
                plan["proposal"], as_of=plan["as_of"], actor=plan["actor"]
            )
            require(plan == expected, "bound-plan-replay")
            require(
                plan["proposal"]["topic"] == self.manifest["research_run"]["objective"],
                "plan-topic-mismatch",
            )
            self.plan, self.binding, self.plan_ref = plan, payload, payload["plan_ref"]
            self.queries = {q["query_id"]: q for q in queries}
        elif kind == "CoverageRoundOpened":
            require(self.plan is not None, "coverage-plan-required")
            require(self.active is None, "round-already-open")
            number = len(self.closed) + 1
            require(
                number <= self.plan["proposal"]["stop_policy"]["max_rounds"],
                "round-budget-exhausted",
            )
            require(payload["round_number"] == number, "round-sequence")
            self.active, self.baseline = number, self.works.copy()
        elif kind == "ActionStarted":
            self.check_start(payload)
            self.starts[payload["event_id"]] = payload
        elif kind == "QueryEvent":
            self.completed[payload["event_id"]] = payload
        elif kind == "CandidateRevision":
            self.works.add(payload["work_id"])
        elif kind == "CoverageReceipt":
            result = self.completed.get(payload["query_event_id"])
            require(
                self.active is not None
                and result
                and result["arguments"].get("coverage", {}).get("round_number")
                == self.active,
                "receipt-requires-current-query",
            )
            previous = self.receipts.get(payload["query_event_id"])
            require(
                payload["replaces_event_id"]
                == (previous["event_id"] if previous else None),
                "receipt-history-mismatch",
            )
            self.receipts[payload["query_event_id"]] = payload
        elif kind == "CoverageRoundClosed":
            from .policy import record_round

            require(payload["round_number"] == self.active, "round-sequence")
            require(payload["summary"] == self.summary(), "coverage-round-replay")
            self.closed.append(payload)
            record_round(self, payload)
            self.active = None
        elif kind == "CoverageHumanAction":
            require(self.plan is not None, "coverage-plan-required")
            expected_hash = digest(
                canonical(dict(manifest=self.manifest, events=self.material))
            )
            require(
                payload["reviewed_state_sha256"] == expected_hash,
                "stale-human-authorization",
            )
            clusters = {c["cluster_id"] for c in self.plan["proposal"]["clusters"]}
            require(
                (
                    payload["action"] == "request-cluster"
                    and payload["cluster_id"] in clusters
                )
                or (
                    payload["action"] == "accept-stop" and payload["cluster_id"] is None
                ),
                "human-action-cluster",
            )
            self.human_actions.append(payload)
        self.evidence.observe(payload, self.plan)
        if kind != "Checkpoint" and not (
            kind == "ArtifactStored"
            and payload["ref"]["artifact_type"] == "validator-report"
        ):
            self.material.append(payload)

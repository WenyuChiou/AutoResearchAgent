"""Record local observations. Network execution belongs to a future pinned adapter."""

from pathlib import Path

from .identity import candidate_revision, work_key
from .journal import (
    Journal,
    LedgerError,
    STREAMS,
    canonical,
    decode,
    digest,
    mutation,
    utc_now,
    write_new,
    contained,
)
from .semantics import SUCCESS, claim_check, completion_count, query_fields
from .readiness import coverage_text


class Ledger(Journal):
    def read_ref(self, ref):
        if not any(
            row["payload"]["kind"] == "ArtifactStored" and row["payload"]["ref"] == ref
            for row in self.events()
        ):
            raise LedgerError("unregistered-or-altered-artifact")
        return super().read_ref(ref)

    @classmethod
    def create(cls, root, *, run_id, objective, clock=utc_now):
        from .contracts import check_manifest

        root = Path(root)
        created = clock()
        manifest = dict(
            kind="Stage1Manifest",
            schema_version="1.0.0",
            research_run=dict(
                kind="ResearchRun",
                schema_version="1.0.0",
                run_id=run_id,
                objective=objective,
                created_at=created,
                current_stage=1,
                constraints=["saved material only; no automatic network retry"],
                versions={"ledger": "1.0.0"},
                input_refs=[],
            ),
            mode="offline-import",
            research_hub_pin=None,
            max_artifact_bytes=16 * 1024 * 1024,
            closest_work_status="unverified",
        )
        check_manifest(manifest)
        root.mkdir(parents=True, exist_ok=False)
        write_new(root / "run_manifest.json", canonical(manifest) + b"\n")
        for name in ["stage_events.jsonl", *STREAMS.values()]:
            write_new(root / name, b"")
        (root / "raw").mkdir()
        write_new(
            root / "coverage_and_stop.md",
            coverage_text().encode("utf-8"),
        )
        return cls(root, clock=clock)

    @mutation
    def start(self, operation, arguments, *, backend=None, parent_id=None):
        if operation == "search" and (parent_id is not None or backend is not None):
            raise LedgerError("search-has-backend-parent")
        if parent_id is not None:
            parent = self.event(parent_id, "ActionStarted")
            if parent["operation"] != "search" or parent_id not in self.pending():
                raise LedgerError("invalid-parent: backend requires an open query")
        if (operation == "backend") != (backend is not None and parent_id is not None):
            raise LedgerError("backend-parent-required")
        event = self.append(
            dict(
                kind="ActionStarted",
                operation=operation,
                arguments=arguments,
                backend=backend,
                parent_id=parent_id,
            )
        )
        return event["event_id"]

    def _save(self, data, *, producer, artifact_type="raw-output"):
        if len(data) > self.manifest["max_artifact_bytes"]:
            raise LedgerError("artifact-size-limit: no data saved")
        sha = digest(data)
        relative = f"raw/{sha}.bin"
        path = contained(self.root, relative)
        for event in self.events():
            payload = event["payload"]
            if (
                payload["kind"] == "ArtifactStored"
                and payload["ref"]["path"] == relative
            ):
                self.read_ref(payload["ref"])
                return payload["ref"]
        if path.exists():
            if path.read_bytes() != data:
                raise LedgerError(f"artifact-conflict: {relative}")
            # A crash may leave bytes before their journal registration.
        else:
            write_new(path, data)
        ref = dict(
            kind="ArtifactRef",
            schema_version="1.0.0",
            artifact_id="artifact-" + sha,
            artifact_type=artifact_type,
            path=relative,
            sha256=sha,
            producer=producer,
            created_at=self.clock(),
        )
        self.append(dict(kind="ArtifactStored", ref=ref, bytes=len(data)))
        return ref

    @mutation
    def save_bytes(self, data, *, producer):
        self.event(producer, "ActionStarted")
        return self._save(data, producer=producer)

    @mutation
    def finish(
        self,
        attempt_id,
        *,
        outcome,
        http_status,
        exit_code,
        stdout,
        stderr,
        records=None,
    ):
        attempt = self.event(attempt_id, "ActionStarted")
        if attempt["operation"] != "backend" or attempt_id not in self.pending():
            raise LedgerError("attempt-not-open")
        for ref in [stdout, stderr] + ([records] if records else []):
            self.read_ref(ref)
        value = dict(
            kind="ActionFinished",
            attempt_id=attempt_id,
            outcome=outcome,
            http_status=http_status,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            records=records,
        )
        value["result_count"] = completion_count(value, self.read_ref)
        return self.append(value)["event_id"]

    @mutation
    def complete_query(self, query_id):
        query = self.event(query_id, "ActionStarted")
        if query["operation"] != "search" or query_id not in self.pending():
            raise LedgerError("query-not-open")
        payloads = [e["payload"] for e in self.events()]
        children = [
            p
            for p in payloads
            if p["kind"] == "ActionStarted" and p["parent_id"] == query_id
        ]
        if not children or any(c["event_id"] in self.pending() for c in children):
            raise LedgerError(
                "incomplete-backends: close or record interruption before completing query"
            )
        ids = {c["event_id"] for c in children}
        finished = [
            p
            for p in payloads
            if p["kind"] == "ActionFinished" and p["attempt_id"] in ids
        ]
        return self.append(
            dict(kind="QueryEvent", **query_fields(query, children, finished))
        )["event_id"]

    def candidates(self):
        return {row["work_id"]: row for row in self.records("candidates.jsonl")}

    @mutation
    def extract(self):
        from .contracts import check_record

        latest = self.candidates()
        seen = {d["discovery_id"] for c in latest.values() for d in c["discoveries"]}
        failed = {
            f"{p['completion_id']}:{p['record_index']}"
            for e in self.events()
            if (p := e["payload"])["kind"] == "ExtractionFailure"
        }
        added = 0
        for query in self.records("query_events.jsonl"):
            for completion_id in query["completion_ids"]:
                completion = self.event(completion_id, "ActionFinished")
                if completion["outcome"] not in SUCCESS:
                    continue
                for index, record in enumerate(
                    decode(
                        self.read_ref(completion["records"]),
                        completion["records"]["path"],
                    )
                ):
                    discovery = f"{completion_id}:{index}"
                    if discovery in seen or discovery in failed:
                        continue
                    try:
                        check_record(record)
                        work = "work-" + digest(work_key(record).encode())
                    except LedgerError as error:
                        self.append(
                            dict(
                                kind="ExtractionFailure",
                                completion_id=completion_id,
                                record_index=index,
                                source_ref=completion["records"],
                                error=str(error),
                            )
                        )
                        failed.add(discovery)
                        continue
                    value = candidate_revision(
                        latest.get(work),
                        record=record,
                        completion=completion,
                        query_id=query["query_id"],
                        index=index,
                    )
                    latest[work] = self.append(value)
                    seen.add(discovery)
                    added += 1
        return {
            "new_discoveries": added,
            "works": len(latest),
            "extraction_failures": len(failed),
        }

    @mutation
    def decide(
        self,
        work_id,
        decision,
        *,
        reason,
        rationale,
        evidence_refs,
        actor="agent",
        authorization=None,
    ):
        from .validation import validate_run

        if work_id not in self.candidates():
            raise LedgerError("unknown-work")
        if not evidence_refs:
            raise LedgerError("decision-evidence-required")
        for ref in evidence_refs:
            self.read_ref(ref)
        if authorization is not None:
            if actor == "agent":
                raise LedgerError("human-actor-required")
            if authorization["state_sha256"] != self.state_hash():
                raise LedgerError("stale-human-authorization")
            if not validate_run(self.root)["valid"]:
                raise LedgerError("invalid-reviewed-state")
        previous = [
            d
            for d in self.records("decision_events.jsonl")
            if d["subject_id"] == work_id
        ]
        prior = previous[-1] if previous else None
        return self.append(
            dict(
                kind="DecisionEvent",
                run_id=self.manifest["research_run"]["run_id"],
                stage_run_id="stage1",
                sequence=len(self.events()) + 1,
                actor=actor,
                actor_type="human" if authorization else "agent",
                subject_id=work_id,
                prior_decision=prior["new_decision"] if prior else None,
                new_decision=decision,
                reason_code=reason,
                rationale=rationale,
                evidence_refs=evidence_refs,
                reverses_event_id=prior["event_id"] if prior else None,
                authorization=authorization,
            )
        )["event_id"]

    @mutation
    def claim(
        self,
        *,
        work_id,
        version_id,
        claim_text,
        relation,
        evidence_level,
        locator,
        source_ref,
        verifier,
    ):
        candidate = self.candidates().get(work_id)
        if not candidate or version_id not in candidate["version_ids"]:
            raise LedgerError("unknown-source-version")
        value = dict(
            kind="ClaimEvidence",
            work_id=work_id,
            version_id=version_id,
            claim_text=claim_text,
            relation=relation,
            evidence_level=evidence_level,
            locator=locator,
            source_ref=source_ref,
            verifier=verifier,
        )
        claim_check(value, self.read_ref)
        return self.append(value)["event_id"]

    @mutation
    def compare_identity(
        self,
        *,
        target_work_id,
        target_discovery_id,
        reference_discovery_id=None,
        resolver_ref=None,
        assessor,
    ):
        from .verification import comparison

        events = [row["payload"] for row in self.events()]
        starts = {p["event_id"]: p for p in events if p["kind"] == "ActionStarted"}
        history = {
            (p["target_work_id"], p["target_version_id"]): p
            for p in events
            if p["kind"] == "IdentityComparison"
        }
        payload = comparison(
            self.candidates(),
            starts,
            history,
            self.read_ref,
            target_work_id=target_work_id,
            target_discovery_id=target_discovery_id,
            reference_discovery_id=reference_discovery_id,
            resolver_ref=resolver_ref,
            assessor=assessor,
        )
        return self.append(payload)["event_id"]

    def identity_status(self):
        from .validation import validate_run
        from .verification import current_comparisons

        report = validate_run(self.root)
        if not report["valid"]:
            raise LedgerError("invalid-identity-state: " + "; ".join(report["errors"]))
        return current_comparisons(
            self.candidates(), [row["payload"] for row in self.events()]
        )

    @mutation
    def checkpoint(self):
        from .validation import validate_run
        from .readiness import readiness

        report = validate_run(self.root)
        gate, action = readiness(report)
        ref = self._save(
            canonical(report),
            producer="stage1-validator",
            artifact_type="validator-report",
        )
        if not report["valid"]:
            raise LedgerError("validator-failed: saved report " + ref["path"])
        result = dict(
            kind="StageResult",
            schema_version="1.0.0",
            stage_run_id="stage1",
            status="human-review" if action == "human-review" else "running",
            outputs=[],
            validator_report=ref,
            metrics=report["counts"],
            gate=gate,
            next_allowed_action=action,
        )
        event = self.append(
            dict(kind="Checkpoint", state_sha256=self.state_hash(), stage_result=result)
        )
        # This is an explicitly derived current view; immutable reports remain in raw/.
        contained(self.root, "coverage_and_stop.md").write_text(
            coverage_text(event), encoding="utf-8", newline="\n"
        )
        return event

"""Automatic Stage1 production through the existing project owners.

Trusted bootstrap supplies a hash-pinned delegation, the original source owner
and the existing deny-only model broker. This adapter cannot create consent,
reset resources, infer human review or start Stage2. All model I/O continues to
use ProjectModelService's durable reservations, native admission and no-resend
recovery. Completed jobs and saved source bytes are reopened before local writes.
"""

from copy import deepcopy
import json
from pathlib import Path

from stage1_deliverable.common import canonical, private_output, reject_links, sha
from stage1_deliverable.records import CLASSIFICATION, FINDINGS
from stage1_ledger.journal import decode
from .project_model import ProjectModelService, PERMIT_FIELDS, budget_digest, _expiry
from .project_stage1 import ProjectStage1Service, _basis
from .project_stage1_records import ProjectStage1RecordsService
from .project_stage1_sources import source_record
from .project_resource_budget import resource_view
from .project_stage1_review_units import (
    IDENTITY,
    OPERATION,
    SCOPE,
    child_context,
    full_note,
    prompt,
    segments,
    semantic_context,
    task_ref,
    validate_result,
)
from .session_api import SessionApiError, _check

STORE = "stage1_automatic_production"
MAX_WORKS = 512
PERMIT_FIELDS_AUTO = {
    "kind",
    "schema_version",
    "permission_id",
    "principal",
    "project_id",
    "input_version",
    "brief_sha256",
    "plan_manifest_sha256",
    "budget_sha256",
    "model",
    "max_calls",
    "max_seconds",
    "expires_at",
    "allow_model_calls",
    "allow_source_acquisition",
    "allow_query_expansions",
    "automatic_screening",
    "execution_scope",
    "external_search",
    "frozen_subjects",
    "stage2_execution",
    "executor_sha256",
    "review_units_sha256",
}


class ProjectStage1ExecutionService:
    """One opt-in producer; no listener, credential or default permit is created."""

    def __init__(
        self, stage1, models, records, *, permit_path, permit_sha256, output_root
    ):
        _check(
            isinstance(stage1, ProjectStage1Service)
            and isinstance(models, ProjectModelService)
            and isinstance(records, ProjectStage1RecordsService)
            and stage1.intake is models.intake is records.intake
            and records.delivery.stage1 is stage1,
            "automatic-stage1-same-owners-required",
        )
        self.stage1, self.models, self.records = stage1, models, records
        self.intake = stage1.intake
        self.path = private_output(permit_path).resolve()
        reject_links(self.path)
        raw = self.path.read_bytes()
        _check(
            len(raw) <= 16384 and sha(raw) == permit_sha256,
            "automatic-stage1-permit-bytes",
        )
        value = decode(raw, "automatic Stage1 delegation")
        _check(
            type(value) is dict
            and set(value) == PERMIT_FIELDS_AUTO
            and value["kind"] == "Stage1AutomaticProductionPermit"
            and value["schema_version"] == "1.0.0",
            "automatic-stage1-permit-fields",
        )
        _check(
            value["allow_model_calls"] is True
            and value["automatic_screening"] is True
            and type(value["allow_source_acquisition"]) is bool
            and type(value["allow_query_expansions"]) is bool
            and value["execution_scope"] == SCOPE
            and value["external_search"] is False
            and value["frozen_subjects"] is False
            and value["stage2_execution"] is False,
            "automatic-stage1-permit-scope",
        )
        _check(
            all(
                type(value[k]) is str and bool(value[k])
                for k in ("permission_id", "principal", "project_id", "model")
            )
            and type(value["input_version"]) is int
            and value["input_version"] > 0
            and type(value["max_calls"]) is int
            and 0 < value["max_calls"] <= 256
            and type(value["max_seconds"]) is int
            and 0 < value["max_seconds"] <= 86400,
            "automatic-stage1-permit-identity-budget",
        )
        self.permit, self.permit_sha256 = value, permit_sha256
        self.root = private_output(output_root).resolve()
        _check(self.root.is_dir(), "automatic-stage1-output-root-required")
        _check(
            not self.root.is_relative_to(self.intake.root)
            and not self.intake.root.is_relative_to(self.root),
            "automatic-stage1-storage-overlap",
        )
        existing = getattr(models, "automatic_stage1", None)
        _check(existing is None, "automatic-stage1-owner-already-attached")
        models.automatic_stage1 = self
        self._technical = {}

    def _permit(self, ref, *, expired=False):
        reject_links(self.path)
        raw = self.path.read_bytes()
        _check(
            sha(raw) == self.permit_sha256
            and decode(raw, "automatic Stage1 delegation") == self.permit,
            "automatic-stage1-parent-changed",
        )
        binding = self.intake.binding(ref)
        p = self.permit
        _check(
            sha(Path(__file__).read_bytes()) == p["executor_sha256"]
            and sha(
                Path(__file__).with_name("project_stage1_review_units.py").read_bytes()
            )
            == p["review_units_sha256"],
            "automatic-stage1-runtime-differs",
        )
        _check(
            type(binding["input_version"]) is type(p["input_version"])
            and all(
                binding[k] == p[k]
                for k in (
                    "project_id",
                    "input_version",
                    "brief_sha256",
                    "plan_manifest_sha256",
                )
            )
            and budget_digest(binding) == p["budget_sha256"],
            "automatic-stage1-parent-binding",
        )
        with self.intake._lock:
            self.intake._load(p["principal"], ref)
        _check(
            p["max_calls"] <= binding["settings"]["budgets"]["model_calls"]
            and p["max_seconds"] <= binding["settings"]["budgets"]["seconds"],
            "automatic-stage1-parent-budget",
        )
        if not expired:
            _check(
                self.models.clock() < _expiry(p["expires_at"]),
                "automatic-stage1-parent-expired",
            )
        return binding

    def _model_jobs(self, ref):
        state = self.intake._load(self.permit["principal"], ref)
        operations = state.get("model_operations", {})
        offers = operations.get("offers", {})
        return [
            j
            for j in operations.get("jobs", {}).values()
            if offers.get(j["offer_ref"], {})
            .get("context", {})
            .get("automatic_parent_sha256")
            == self.permit_sha256
        ]

    def check_reservation(self, ref, *, seconds=None):
        self._permit(ref)
        jobs = self._model_jobs(ref)
        _check(
            sum(j["calls_reserved"] for j in jobs) < self.permit["max_calls"],
            "automatic-stage1-parent-budget-exhausted",
            429,
        )
        if seconds is not None:
            _check(
                sum(j["reservation_seconds"] for j in jobs) + seconds
                <= self.permit["max_seconds"],
                "automatic-stage1-parent-seconds-exhausted",
                429,
            )

    def _results(self, ref):
        """Reopen verified raw outputs and independently replay unit validation."""
        state = self.intake._load(self.permit["principal"], ref)
        offers = state.get("model_operations", {}).get("offers", {})
        results, snapshots, jobs = {}, {}, {}
        for job in self._model_jobs(ref):
            task = job["task_ref"]
            _check(task not in jobs, "automatic-stage1-duplicate-model-task")
            jobs[task] = job
            context = offers[job["offer_ref"]]["context"]
            _check(
                context["operation"] == OPERATION
                and context["snapshot_sha256"]
                == sha(canonical(context["saved_reading"])),
                "automatic-stage1-saved-snapshot-differs",
            )
            snapshots[task] = context["saved_reading"]
            if job["status"] != "content-review-pending":
                continue
            _check(
                job.get("provider_reserved") is True
                and job.get("automatic_review") is not None,
                "automatic-stage1-verified-review-required",
            )
            folder = self.models._runtime_folder(self.permit["principal"], ref, job)
            for name in ("raw_output", "automatic_review", "verified_receipt"):
                artifact = job[name]
                path = folder / artifact["path"]
                reject_links(path)
                raw = path.read_bytes()
                _check(
                    len(raw) == artifact["bytes"] and sha(raw) == artifact["sha256"],
                    "automatic-stage1-job-bytes-differ",
                )
            raw = (folder / job["raw_output"]["path"]).read_bytes()
            replayed = validate_result(raw, context["saved_reading"])
            _check(
                decode(
                    (folder / job["automatic_review"]["path"]).read_bytes(),
                    "automatic review",
                )
                == replayed,
                "automatic-stage1-review-replay-differs",
            )
            results[task] = replayed
        return results, snapshots, jobs

    def _context(self, ref):
        binding = self._permit(ref, expired=True)
        context = self.records.delivery._saved_context(ref)
        _check(
            context[0] == self.permit["principal"] and context[2] == binding,
            "automatic-stage1-record-owner-differs",
        )
        return context

    def _work(self, ref, work, context, results, *, build_tasks=True):
        actor, state, binding, run, ledger, report = context
        candidate = ledger.candidates()[work]
        version = candidate["discoveries"][-1]["version_id"]
        decision = ledger.coverage_state().evidence.decisions.get(work)
        entries = [
            r["payload"]
            for r in self.records._entries(context)
            if r["ref"].startswith("stage1-source-registry-")
            and (r["payload"]["work_id"], r["payload"]["version_id"]) == (work, version)
        ]
        sources, unavailable = [], []
        for entry in entries:
            _, receipt = source_record(ledger, self.records.root, entry)
            finish = ledger.event(entry["finish_event_id"])
            if (
                receipt["status"] != "available"
                or finish["text_ref"] is None
                or receipt["identity_status"] == "mismatch"
            ):
                unavailable.append(
                    dict(
                        source_id=entry["source_id"],
                        outcome=finish["outcome"],
                        identity_status=receipt["identity_status"],
                    )
                )
                continue
            raw = ledger.read_ref(finish["text_ref"])
            sources.append(
                (
                    dict(
                        source_id=entry["source_id"],
                        text_sha256=sha(raw),
                        text_bytes=len(raw),
                        text_ref=deepcopy(finish["text_ref"]),
                        identity_status=receipt["identity_status"],
                        raw_sha256=receipt["raw_sha256"],
                        evidence_level=receipt["evidence_level"],
                    ),
                    raw,
                )
            )
        _check(
            len(entries) <= 8
            and sum(len(raw) for _, raw in sources) <= 2 * 1024 * 1024,
            "automatic-stage1-work-source-bound",
        )
        source_basis = sha(
            canonical(
                dict(
                    candidate_event_id=candidate["event_id"],
                    version_id=version,
                    sources=[s for s, _ in sources],
                    unavailable=unavailable,
                )
            )
        )
        if (
            decision is not None
            and decision["new_decision"] == "exclude"
            and not entries
        ):
            return dict(
                work_id=work,
                status="excluded-existing",
                decision_event_id=decision["event_id"],
            )
        applied = state.get(STORE, {}).get("applied", {}).get(work)
        if (
            applied is not None
            and applied["source_basis_sha256"] == source_basis
            and decision is not None
            and applied["decision_event_id"] == decision["event_id"]
        ):
            registered = any(
                e["ref"].startswith("stage1-reading-registry-")
                and all(
                    e["payload"].get(k) == applied[k]
                    for k in (
                        "work_id",
                        "version_id",
                        "candidate_event_id",
                        "decision_event_id",
                        "review_event_id",
                    )
                )
                for e in self.records._entries(context)
            )
            return dict(
                work_id=work,
                status="done" if registered else "register",
                applied=applied,
                source_basis_sha256=source_basis,
            )
        brief = binding.get("brief") or self.intake.brief_binding(ref)["brief"]
        meaning = semantic_context(brief, ledger.coverage_state().plan)
        base = dict(
            kind="Stage1AutomaticReviewInput",
            schema_version="1.1.0",
            project_ref=ref,
            **_basis(binding),
            work_id=work,
            version_id=version,
            candidate_event_id=candidate["event_id"],
            decision_event_id=None if decision is None else decision["event_id"],
            source_basis_sha256=source_basis,
            metadata=candidate["discoveries"][-1]["record"],
            topic=brief["original_description"],
            semantic_context=meaning,
            cluster_ids=[
                c["cluster_id"]
                for c in ledger.coverage_state().plan["proposal"]["clusters"]
            ],
            requested_fields=dict(
                classification=list(CLASSIFICATION), findings=list(FINDINGS)
            ),
            scientific_acceptance=False,
            human_acceptance=False,
        )
        tasks, level = {}, []
        for source, raw in sources if build_tasks else []:
            for part in segments(raw):
                document = dict(base, unit="segment", source=source, segment=part)
                task = task_ref(document)
                document["task_ref"] = task
                tasks[task] = document
                level.append(task)
        # A deterministic binary tree covers every leaf without presenting an
        # unbounded corpus to a single call. The final root is always synthesis.
        if level:
            while len(level) > 1 or tasks[level[0]]["unit"] == "segment":
                following = []
                for offset in range(0, len(level), 2):
                    children = level[offset : offset + 2]
                    identity = dict(base, unit="synthesis", child_task_refs=children)
                    task = task_ref(identity)
                    tasks[task] = dict(identity, task_ref=task)
                    if all(child in results for child in children):
                        tasks[task]["children"] = [
                            child_context(child, results[child]) for child in children
                        ]
                    following.append(task)
                level = following
        root_task = level[0] if level else None
        pending = next(
            (
                task
                for task, doc in tasks.items()
                if task not in results
                and (doc["unit"] == "segment" or "children" in doc)
            ),
            None,
        )
        return dict(
            work_id=work,
            version_id=version,
            source_basis_sha256=source_basis,
            status="source"
            if not entries
            else "source-unavailable"
            if not sources
            else "apply"
            if root_task in results
            else "review",
            tasks=tasks,
            next_task=pending,
            root_task=root_task,
            source_failures=unavailable,
            sources={s["source_id"]: s for s, _ in sources},
            candidate=candidate,
            decision=decision,
        )

    def work_items(self, ref):
        with self.intake._lock:
            context = self._context(ref)
            results, _, _ = self._results(ref)
            candidates = context[4].candidates()
            _check(len(candidates) <= MAX_WORKS, "automatic-stage1-work-bound")
            items, expanded = [], False
            for work in sorted(candidates):
                item = self._work(ref, work, context, results, build_tasks=not expanded)
                if item["status"] in {"review", "apply"}:
                    expanded = True
                items.append(item)
            return items

    def snapshot(self, ref, task):
        with self.intake._lock:
            for work in self.work_items(ref):
                if task in work.get("tasks", {}):
                    value = work["tasks"][task]
                    _check(
                        value["unit"] == "segment" or "children" in value,
                        "automatic-stage1-child-review-required",
                    )
                    return deepcopy(value)
        _check(False, "automatic-stage1-task-stale")

    def guard(self, ref, context):
        self._permit(ref)
        snapshot = context["saved_reading"]
        with self.intake._lock:
            current = self._context(ref)
            results, _, _ = self._results(ref)
            work = self._work(
                ref, snapshot["work_id"], current, results, build_tasks=False
            )
            candidate = current[4].candidates()[snapshot["work_id"]]
            decision = (
                current[4].coverage_state().evidence.decisions.get(snapshot["work_id"])
            )
            _check(
                context["automatic_parent_sha256"] == self.permit_sha256
                and snapshot["source_basis_sha256"] == work["source_basis_sha256"]
                and snapshot["candidate_event_id"] == candidate["event_id"]
                and snapshot["decision_event_id"]
                == (None if decision is None else decision["event_id"])
                and snapshot["metadata"] == candidate["discoveries"][-1]["record"],
                "automatic-stage1-task-binding-differs",
            )
            if snapshot.get("schema_version") == "1.1.0":
                _check(
                    snapshot["semantic_context"]
                    == semantic_context(
                        current[2].get("brief")
                        or self.intake.brief_binding(ref)["brief"],
                        current[4].coverage_state().plan,
                    ),
                    "automatic-stage1-confirmed-context-differs",
                )
            identity = {
                k: v for k, v in snapshot.items() if k not in {"task_ref", "children"}
            }
            _check(
                task_ref(identity) == context["task_ref"],
                "automatic-stage1-task-identity-differs",
            )
            if snapshot["unit"] == "segment":
                source, part = snapshot["source"], snapshot["segment"]
                _check(
                    source == work["sources"].get(source["source_id"]),
                    "automatic-stage1-source-context-differs",
                )
                raw = current[4].read_ref(source["text_ref"])
                _check(
                    raw[part["start_byte"] : part["end_byte"]]
                    == part["text"].encode("utf8")
                    and sha(part["text"].encode("utf8")) == part["sha256"],
                    "automatic-stage1-segment-bytes-differ",
                )
            else:
                _check(
                    snapshot["children"]
                    == [
                        child_context(t, results[t])
                        for t in snapshot["child_task_refs"]
                    ],
                    "automatic-stage1-child-bytes-differ",
                )

    def register_task(self, ref, task):
        """Derive one child only from this externally pinned delegation."""
        with self.intake._lock:
            self.check_reservation(ref)
            snapshot = self.snapshot(ref, task)
            # A passive saved-progress read never needs to serialize a prompt.
            # Refuse an oversized confirmed context before any child permit or
            # model reservation, without shortening accepted user constraints.
            prompt(snapshot)
            binding = self.intake.binding(ref)
            state = self.intake._load(self.permit["principal"], ref)
            existing = next(
                (
                    o
                    for o in state.get("model_operations", {})
                    .get("offers", {})
                    .values()
                    if o["context"].get("task_ref") == task
                    and o["context"].get("automatic_parent_sha256")
                    == self.permit_sha256
                ),
                None,
            )
            if existing is not None:
                if existing["offer_ref"] not in self.models._registrations:
                    path = self.root / (task + ".permit.json")
                    self.models.register(
                        ref,
                        operation=OPERATION,
                        permit_path=path,
                        permit_sha256=existing["permit_sha256"],
                    )
                return self.models._public_offer(existing)
            permit = {
                k: deepcopy(self.permit[k]) for k in PERMIT_FIELDS if k in self.permit
            }
            reserved = sum(j["reservation_seconds"] for j in self._model_jobs(ref))
            remaining = int(self.permit["max_seconds"] - reserved)
            _check(remaining > 0, "automatic-stage1-parent-seconds-exhausted", 429)
            permit.update(
                kind="ProjectModelOperationPermit",
                schema_version="1.0.0",
                operation=OPERATION,
                permission_id=self.permit["permission_id"][:40] + ":" + task[-64:],
                max_calls=1,
                max_seconds=min(
                    remaining,
                    self.models.local_cap_seconds,
                    binding["settings"]["budgets"]["seconds"],
                ),
                task_ref=task,
                snapshot_sha256=sha(canonical(snapshot)),
                automatic_parent_sha256=self.permit_sha256,
            )
            raw = canonical(permit) + b"\n"
            path = self.root / (task + ".permit.json")
            if path.exists():
                reject_links(path)
                _check(
                    path.read_bytes() == raw, "automatic-stage1-child-permit-differs"
                )
            else:
                with path.open("xb") as stream:
                    stream.write(raw)
            return self.models.register(
                ref, operation=OPERATION, permit_path=path, permit_sha256=sha(raw)
            )

    def apply(self, credential, ref, body, *, check_deadline=None):
        """Append AI decisions/located claims; never call human review endpoints."""
        actor = self.intake._principal(credential)
        _check(actor == self.permit["principal"], "automatic-stage1-principal-differs")
        with self.intake._lock:
            items = self.work_items(ref)
            item = next((w for w in items if w["work_id"] == body["work_ref"]), None)
            _check(
                item is not None and item["status"] in {"apply", "source-unavailable"},
                "automatic-stage1-apply-unready",
            )
            results, snapshots, _ = self._results(ref)
            if item["status"] == "apply":
                root_review = results[item["root_task"]]
                value = root_review["review"]
            else:
                value = dict(
                    summary="No eligible saved full source. Automatic source follow-up remains.",
                    classification={k: "Unknown" for k in CLASSIFICATION},
                    findings={k: "Unknown" for k in FINDINGS},
                    limitations=[
                        "Saved source unavailable; no semantic reading performed."
                    ],
                    claims=[],
                    decision="pending",
                    rationale="Automatic source acquisition/identity produced no readable same-version full text; retain technical follow-up.",
                    cluster_claims={},
                    identity_status="unverifiable",
                    identity_claims={k: None for k in IDENTITY},
                    closest=False,
                    questions=[],
                )
            note = full_note(item.get("tasks", {}), results)
            if item["status"] == "source-unavailable":
                note += (
                    value["summary"]
                    + "\n"
                    + json.dumps(item["source_failures"], ensure_ascii=False)
                ).encode("utf8")
            note_path = self.root / (
                "note-"
                + sha(canonical([ref, item["source_basis_sha256"], value]))
                + ".md"
            )
            if not note_path.exists():
                with note_path.open("xb") as stream:
                    stream.write(note)
            reject_links(note_path)
            _check(note_path.read_bytes() == note, "automatic-stage1-note-differs")
            expected = item["source_basis_sha256"]

        def preflight(state, run, ledger, report, principal):
            self._permit(ref)
            _check(
                self._work(
                    ref, body["work_ref"], self._context(ref), self._results(ref)[0]
                )["source_basis_sha256"]
                == expected,
                "automatic-stage1-apply-source-stale",
            )

        def producer(state, run, ledger, digest, principal):
            claims, spans = [], {}
            for claim in value["claims"]:
                source = item["sources"][claim["source_id"]]
                raw = ledger.read_ref(source["text_ref"])
                start, end = claim["start_byte"], claim["end_byte"]
                _check(
                    raw[start:end] == claim["quote"].encode("utf8"),
                    "automatic-stage1-apply-quote-differs",
                )
                cid = ledger.claim(
                    work_id=item["work_id"],
                    version_id=item["version_id"],
                    claim_text=claim["text"],
                    relation=claim["relation"],
                    evidence_level=source["evidence_level"],
                    locator=dict(
                        section=f"UTF-8 bytes {start}:{end}", quote=claim["quote"]
                    ),
                    source_ref=source["text_ref"],
                    verifier=dict(
                        actor=self.permit["model"],
                        actor_type="agent",
                        method="automatic-source-review; exact-quote-checked",
                    ),
                    assessment=deepcopy(claim.get("assessment")),
                )
                claims.append(cid)
                spans[cid] = dict(
                    claim_id=cid,
                    source_id=claim["source_id"],
                    text_sha256=sha(raw),
                    start=len(raw[:start].decode("utf8")),
                    end=len(raw[:end].decode("utf8")),
                    quote=claim["quote"],
                )
            old = item["decision"]
            decision = (
                old["new_decision"]
                if old and old["new_decision"] in {"include", "exclude"}
                else value["decision"]
            )
            did = ledger.decide(
                item["work_id"],
                decision,
                reason="automatic-source-review"
                if item["status"] == "apply"
                else "automatic-source-unavailable",
                rationale=value["rationale"],
                evidence_refs=[item["candidate"]["discoveries"][-1]["source_ref"]],
                actor="ai:" + self.permit["model"],
                authorization=None,
            )
            review_id = None
            if decision == "include" and value["cluster_claims"]:
                prior = ledger.coverage_state().evidence.current().get(item["work_id"])
                reviewed = ledger.review_work(
                    work_id=item["work_id"],
                    version_id=item["version_id"],
                    cluster_claims={
                        k: claims[i] for k, i in value["cluster_claims"].items()
                    },
                    identity_status=value["identity_status"],
                    identity_claims={
                        k: None if i is None else claims[i]
                        for k, i in value["identity_claims"].items()
                    },
                    closest=value["closest"],
                    assessor="ai:" + self.permit["model"],
                    rationale=value["rationale"],
                )
                review_id = reviewed["event_id"] if type(reviewed) is dict else reviewed
            else:
                prior = ledger.coverage_state().evidence.current().get(item["work_id"])
                review_id = None if prior is None else prior["event_id"]
            applied = dict(
                work_id=item["work_id"],
                version_id=item["version_id"],
                candidate_event_id=item["candidate"]["event_id"],
                decision_event_id=did,
                review_event_id=review_id,
                source_basis_sha256=expected,
                root_task=item["root_task"],
                note_path=str(note_path),
                note_sha256=sha(note),
                review=deepcopy(value),
                exact_spans=spans,
                reviewer_type="ai",
                human_acceptance=False,
                scientific_acceptance=False,
                entire_extracted_text_reviewed=item["status"] == "apply",
                semantic_projection_complete=item["status"] == "apply"
                and root_review.get("semantic_projection_complete", True),
                paper_figures_verified=False,
                source_failures=deepcopy(item["source_failures"]),
            )
            state.setdefault(STORE, dict(applied={}))["applied"][item["work_id"]] = (
                applied
            )
            return dict(
                automatic_reading={
                    k: deepcopy(v)
                    for k, v in applied.items()
                    if k not in {"note_path", "review", "exact_spans"}
                },
                ledger_state_sha256=ledger.state_hash(),
                stage1_complete=False,
            )

        return self.stage1._mutate(
            credential,
            ref,
            body,
            "stage1-claim",
            producer,
            fields={"work_ref"},
            preflight=preflight,
            check_deadline=check_deadline,
        )

    def register_reading(self, credential, ref, body, *, check_deadline=None):
        with self.intake._lock:
            self._permit(ref)
            item = next(
                w for w in self.work_items(ref) if w["work_id"] == body["work_ref"]
            )
            _check(
                item["status"] == "register", "automatic-stage1-registration-unready"
            )
            applied = item["applied"]
            path = Path(applied["note_path"])
            reject_links(path)
            _check(
                sha(path.read_bytes()) == applied["note_sha256"],
                "automatic-stage1-note-bytes-differ",
            )
            reading = self.records.derive_reading_payload(
                ref,
                body["work_ref"],
                classification=applied["review"]["classification"],
                findings=applied["review"]["findings"],
                roles=[],
                expected_ledger_state_sha256=body["ledger_state_sha256"],
                exact_spans=applied["exact_spans"],
            )
            self.records.register_reading(
                ref,
                reading=reading,
                expected_ledger_state_sha256=body["ledger_state_sha256"],
                registration_key=body["key"],
                check_current=check_deadline,
            )
            return self.intake.action(credential, body["key"], project_ref=ref)

    def execute_source(self, credential, ref, body, *, check_deadline=None):
        """Execute one already admitted source grant through its original owner."""
        self._permit(ref)
        _check(
            self.permit["allow_source_acquisition"] is True,
            "automatic-stage1-source-not-delegated",
        )
        service = self._source_service
        result = service.execute(credential, ref, body, check_deadline=check_deadline)
        if result["status"] == "saved" and not result["replayed"]:
            if check_deadline is not None:
                check_deadline()
            self._permit(ref)
            service.dispatch_pending(credential, ref, body["key"])
        return result

    def authorize_source(self, credential, ref, body, *, check_deadline=None):
        self._permit(ref)
        _check(
            self.permit["allow_source_acquisition"] is True,
            "automatic-stage1-source-not-delegated",
        )
        return self._source_service.authorize(
            credential, ref, body, check_deadline=check_deadline
        )

    def prepare_candidate(self, credential, ref, body, *, check_deadline=None):
        """Record unassessed query candidates as pending, without a human choice."""
        self._permit(ref)
        _check(
            self.intake._principal(credential) == self.permit["principal"],
            "automatic-stage1-principal-differs",
        )

        def check(state, run, ledger, report, actor):
            self._permit(ref)
            _check(
                body["work_ref"] in ledger.candidates()
                and body["work_ref"] not in ledger.coverage_state().evidence.decisions,
                "automatic-stage1-candidate-already-screened",
            )

        def produce(state, run, ledger, digest, actor):
            candidate = ledger.candidates()[body["work_ref"]]
            event = ledger.decide(
                body["work_ref"],
                "pending",
                reason="automatic-await-source-review",
                rationale="New query candidate awaits automatic identity/source/complete-text review; no academic decision or researcher-only question is established.",
                evidence_refs=[candidate["discoveries"][-1]["source_ref"]],
                actor="ai:" + self.permit["model"],
                authorization=None,
            )
            return dict(
                decision_event_id=event,
                decision="pending",
                automatic_work_remains=True,
                human_acceptance=False,
                scientific_acceptance=False,
                ledger_state_sha256=ledger.state_hash(),
            )

        return self.stage1._mutate(
            credential,
            ref,
            body,
            "stage1-claim",
            produce,
            fields={"work_ref"},
            preflight=check,
            check_deadline=check_deadline,
        )

    def execute_review(self, credential, ref, body, *, check_deadline=None):
        """Register the delegated child then use the ordinary durable model API."""
        self._permit(ref)
        _check(
            self.intake._principal(credential) == self.permit["principal"],
            "automatic-stage1-principal-differs",
        )
        with self.intake._lock:
            state = self.intake._load(self.permit["principal"], ref)
            _check(
                state["revision"] == body["revision"], "automatic-stage1-revision-stale"
            )
            offer = self.register_task(ref, body["task_ref"])
            current = self.intake.read(credential, ref)
            request = dict(
                key=body["key"],
                confirmed=True,
                **{
                    k: current[k] for k in ("revision", "input_version", "brief_sha256")
                },
                offer_ref=offer["offer_ref"],
                offer_sha256=offer["offer_sha256"],
            )
            return self.models.execute(
                credential, ref, request, check_deadline=check_deadline
            )

    def next_step(self, host, credential, ref, overview):
        """Select real producer operations, leaving their existing guards intact."""
        self._permit(ref)
        self._technical = {}
        _check(
            host.project_stage1 is self.stage1
            and host.projects is self.intake
            and host.project_models is self.models
            and host.project_stage1_records is self.records,
            "automatic-stage1-host-composition-differs",
        )
        stage = overview.get("stage1") or {}
        if stage.get("ledger") is None:
            return None
        current = overview["project"]
        common = {k: current[k] for k in ("revision", "input_version", "brief_sha256")}
        common["confirmed"] = True
        ledger_hash = stage["ledger"]["state_sha256"]

        def step(phase, kind, method, fields):
            return dict(
                phase=phase, kind=kind, method=method, body={**common, **fields}
            )

        self._source_service = getattr(host, "project_stage1_sources", None)
        source_view = stage.get("source_execution") or {}
        for item in self.work_items(ref):
            work = item["work_id"]
            if item["status"] in {"done", "excluded-existing"}:
                continue
            if item["status"] == "source":
                if item["decision"] is None:
                    return step(
                        "screening",
                        "screen",
                        self.prepare_candidate,
                        dict(work_ref=work, ledger_state_sha256=ledger_hash),
                    )
                if (
                    self._source_service is None
                    or not self.permit["allow_source_acquisition"]
                ):
                    self._technical[work] = "source-owner-or-delegation-unavailable"
                    continue
                previous = [
                    j
                    for j in source_view.get("jobs", {}).values()
                    if j["work_ref"] == work
                ]
                # A known failure is automatic retry work. Never silently create
                # another grant or repeat an uncertain/failed existing request.
                if previous:
                    continue
                grants = [
                    g
                    for g in source_view.get("grants", {}).values()
                    if g["work_ref"] == work and g["status"] == "authorized"
                ]
                if grants:
                    grant = grants[0]
                    return step(
                        "reading",
                        "source",
                        self.execute_source,
                        {k: grant[k] for k in ("grant_ref", "grant_sha256")},
                    )
                try:
                    offer = self._source_service.offers(credential, ref, work)
                except SessionApiError as refused:
                    self._technical[work] = refused.code
                    continue
                return step(
                    "reading",
                    "source",
                    self.authorize_source,
                    dict(
                        work_ref=work,
                        offer_ref=offer["offer_ref"],
                        offer_sha256=offer["offer_sha256"],
                    ),
                )
            if item["status"] == "review":
                task = item["next_task"]
                if task is None:
                    continue
                return step(
                    "reading", "reading", self.execute_review, dict(task_ref=task)
                )
            if item["status"] in {"apply", "source-unavailable"}:
                return step(
                    "screening",
                    "screen",
                    self.apply,
                    dict(work_ref=work, ledger_state_sha256=ledger_hash),
                )
            if item["status"] == "register":
                return step(
                    "reading",
                    "reading",
                    self.register_reading,
                    dict(work_ref=work, ledger_state_sha256=ledger_hash),
                )
        # The query owner already enforces the actual sealed runtime/permit and
        # cumulative query/seconds budget. No new permission is manufactured.
        query_view = stage.get("query_execution") or {}
        query = getattr(self.stage1, "query_service", None)
        if query is not None and query_view.get("execution_authorized") is True:
            offer = query_view.get("query_offer")
            if offer is not None:
                return step(
                    "query",
                    "query",
                    query.execute,
                    {k: offer[k] for k in ("offer_ref", "offer_sha256")},
                )
        expansion = getattr(host, "project_expansions", None)
        expansion_view = stage.get("expansion_execution") or {}
        if expansion is not None:
            for name, method in (
                ("execution_offers", expansion.execute),
                ("authorization_offers", expansion.authorize),
            ):
                if expansion_view.get(name):
                    offer = expansion_view[name][0]
                    if (
                        name == "authorization_offers"
                        and not self.permit["allow_query_expansions"]
                    ):
                        continue
                    return step(
                        "query",
                        "query",
                        method,
                        {
                            **{k: offer[k] for k in ("offer_ref", "offer_sha256")},
                            **(
                                {
                                    "user_input": "Automatic delegated expansion under parent "
                                    + self.permit_sha256
                                    + "; not a new human message."
                                }
                                if name == "authorization_offers"
                                else {}
                            ),
                        },
                    )
        coverage = stage.get("coverage_actions") or {}
        for offer in coverage.get("offers", []):
            operation, document = offer["operation"], offer["document"]
            review = {}
            if operation == "receipt" and document["current_receipt"] is None:
                # Missing truncation evidence remains null. This may prevent a
                # sufficient stop; it must never be replaced with false.
                review = dict(
                    truncated=None,
                    note="Automatic saved-query projection; truncation not established by this record.",
                )
            elif operation == "close-round":
                pass
            elif operation == "open-round":
                with self.intake._lock:
                    state = self.intake._load(self.permit["principal"], ref)
                    resources = resource_view(
                        self.intake, state, self.permit["principal"]
                    )
                if resources["remaining"]["search_calls"] <= 0:
                    continue
            else:
                continue
            return step(
                "coverage",
                "coverage",
                self.stage1.coverage,
                dict(
                    ledger_state_sha256=ledger_hash,
                    operation=operation,
                    review=review,
                    offer_ref=offer["offer_ref"],
                    offer_sha256=offer["offer_sha256"],
                ),
            )
        # A partial package keeps unresolved work and the actual stop reason.
        # The existing records/package validators decide whether it can build.
        if all(
            item["status"] in {"done", "excluded-existing"}
            for item in self.work_items(ref)
        ):
            return dict(phase="delivery", kind=None)
        return None

    def project_view(self, credential, ref):
        """Expose this producer only to its matching authenticated project/run."""
        actor = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(actor, ref)
            if (
                actor != self.permit["principal"]
                or state["project_id"] != self.permit["project_id"]
                or type(state["input_version"])
                is not type(self.permit["input_version"])
                or state["input_version"] != self.permit["input_version"]
                or state["plan"] is None
                or state["settings"] is None
            ):
                return None
            binding = self.intake.binding(ref)
            if (
                any(
                    binding[k] != self.permit[k]
                    for k in (
                        "project_id",
                        "input_version",
                        "brief_sha256",
                        "plan_manifest_sha256",
                    )
                )
                or self.stage1.read(credential, ref)["ledger"] is None
            ):
                return None
            return self.read(credential, ref)

    def read(self, credential, ref):
        """Read current work/technical/human groups without creating a task."""
        actor = self.intake._principal(credential)
        _check(actor == self.permit["principal"], "automatic-stage1-principal-differs")
        with self.intake._lock:
            items = self.work_items(ref)
            results, _, jobs = self._results(ref)
            context = self._context(ref)
            questions, unresolved, recorded, resolved, technical, notes = (
                {},
                [],
                [],
                [],
                [],
                [],
            )
            decisions = context[4].coverage_state().evidence.decisions
            for item in items:
                if item["status"] == "excluded-existing":
                    continue
                if item["status"] == "done":
                    applied = item["applied"]
                    digest = applied["note_sha256"]
                    notes.append(
                        dict(
                            work_id=item["work_id"],
                            version_id=applied["version_id"],
                            sha256=digest,
                            url=f"/api/projects/{ref}/stage1/automatic-notes/{digest}",
                        )
                    )
                    review = applied["review"]
                    decision = decisions[item["work_id"]]
                    row = dict(
                        work_id=item["work_id"],
                        version_id=applied["version_id"],
                        decision=decision["new_decision"],
                        decision_event_id=applied["decision_event_id"],
                        review_event_id=applied["review_event_id"],
                        model_decision=review["decision"],
                        identity_status=review["identity_status"],
                        rationale=review["rationale"],
                        source_basis_sha256=applied["source_basis_sha256"],
                        note_sha256=applied["note_sha256"],
                        entire_extracted_text_reviewed=applied[
                            "entire_extracted_text_reviewed"
                        ],
                        semantic_projection_complete=applied.get(
                            "semantic_projection_complete", True
                        ),
                        source_failures=applied["source_failures"],
                    )
                    reasons = []
                    if not row["semantic_projection_complete"]:
                        reasons.append("synthesis-evidence-projection-incomplete")
                    if review["decision"] == "pending":
                        reasons.append("semantic-decision-pending")
                    if review["identity_status"] != "verified":
                        reasons.append("source-identity-unverified")
                    if row["decision"] not in {"include", "exclude"}:
                        reasons.append("recorded-decision-pending")
                    elif row["decision"] != review["decision"]:
                        reasons.append("retained-decision-differs-from-model")
                    if not applied["entire_extracted_text_reviewed"]:
                        row["processing_status"] = "technical-blocked"
                        technical.append(
                            dict(
                                row,
                                reason="source-retry-or-identity-required",
                                attempted=applied["source_failures"],
                                automatic=True,
                            )
                        )
                    elif reasons:
                        row["processing_status"] = "automatic-pending"
                        unresolved.append(
                            dict(
                                row,
                                next_step="source-identity-or-screening-follow-up",
                                reason_codes=reasons,
                                automatic=True,
                            )
                        )
                    elif review["questions"]:
                        row["processing_status"] = "researcher-question"
                    else:
                        row["processing_status"] = "automatic-resolved"
                        resolved.append(row)
                    recorded.append(row)
                    for question in applied["review"]["questions"]:
                        key = sha(
                            canonical(
                                [
                                    question["category"],
                                    " ".join(question["question"].casefold().split()),
                                    [
                                        " ".join(option.casefold().split())
                                        for option in question["options"]
                                    ],
                                ]
                            )
                        )
                        questions.setdefault(
                            key, dict(question=question, works=[], contexts=[])
                        )["works"].append(item["work_id"])
                        questions[key]["contexts"].append(
                            dict(work_id=item["work_id"], original=deepcopy(question))
                        )
                else:
                    unresolved.append(
                        dict(
                            work_id=item["work_id"],
                            next_step=item["status"],
                            automatic=True,
                        )
                    )
            technical += [
                dict(
                    work_id=work,
                    reason=reason,
                    automatic=True,
                    observed_by="current-source-offer",
                )
                for work, reason in self._technical.items()
            ]
            return dict(
                kind="Stage1AutomaticProductionProgress",
                schema_version="1.0.1",
                project_ref=ref,
                binding=_basis(context[2]),
                run_ref=context[3]["run_ref"],
                ledger_state_sha256=context[5]["state_sha256"],
                permit_sha256=self.permit_sha256,
                automatically_recorded=recorded,
                automatic_resolved=resolved,
                automatic_pending=unresolved,
                technical_blocked=technical,
                researcher_questions=list(questions.values()),
                notes=notes,
                model_calls_reserved=len(jobs),
                model_units_completed=len(results),
                failed_or_unobserved=[
                    dict(task_ref=t, status=j["status"])
                    for t, j in jobs.items()
                    if j["status"] != "content-review-pending"
                ],
                stage1_complete=False,
                scientific_acceptance=False,
                stage2_started=False,
            )

    def note_by_hash(self, credential, ref, digest):
        """Resolve an opaque hash against current notes, never a client path."""
        with self.intake._lock:
            progress = self.project_view(credential, ref)
            _check(progress is not None, "automatic-stage1-project-unconnected", 409)
            row = next((n for n in progress["notes"] if n["sha256"] == digest), None)
            _check(row is not None, "automatic-stage1-current-note-unavailable", 404)
            note = self.note(credential, ref, row["work_id"])
            _check(note["sha256"] == digest, "automatic-stage1-note-changed", 409)
            return dict(
                note,
                binding=progress["binding"],
                run_ref=progress["run_ref"],
                ledger_state_sha256=progress["ledger_state_sha256"],
            )

    def note(self, credential, ref, work_ref):
        """Read a current full-note artifact without revealing its private path."""
        _check(
            self.intake._principal(credential) == self.permit["principal"],
            "automatic-stage1-principal-differs",
        )
        with self.intake._lock:
            item = next(
                (w for w in self.work_items(ref) if w["work_id"] == work_ref), None
            )
            _check(
                item is not None and item["status"] == "done",
                "automatic-stage1-current-note-unavailable",
            )
            applied = item["applied"]
            path = Path(applied["note_path"])
            _check(path.is_relative_to(self.root), "automatic-stage1-note-outside-root")
            reject_links(path)
            _check(
                path.stat().st_size <= 16 * 1024 * 1024, "automatic-stage1-note-bound"
            )
            raw = path.read_bytes()
            _check(
                sha(raw) == applied["note_sha256"], "automatic-stage1-note-bytes-differ"
            )
            return dict(
                work_id=work_ref,
                version_id=applied["version_id"],
                note_ref="automatic-note-" + sha(raw),
                text=raw.decode("utf8"),
                sha256=sha(raw),
                bytes=len(raw),
                source_basis_sha256=applied["source_basis_sha256"],
                entire_extracted_text_reviewed=applied[
                    "entire_extracted_text_reviewed"
                ],
                paper_figures_verified=False,
                human_acceptance=False,
                scientific_acceptance=False,
            )

    def export_notes(self, credential, ref, output):
        """Bind every generated full note as a companion to the existing package."""
        output = private_output(output).resolve()
        _check(
            not output.exists() and output.parent.is_dir(),
            "automatic-stage1-fresh-note-output-required",
        )
        with self.intake._lock:
            progress = self.read(credential, ref)
            context = self._context(ref)
            notes = [
                self.note(credential, ref, row["work_id"])
                for row in progress["automatically_recorded"]
            ]
            output.mkdir()
            rows = []
            for number, note in enumerate(notes):
                filename = f"note-{number:04}.md"
                raw = note.pop("text").encode("utf8")
                with (output / filename).open("xb") as stream:
                    stream.write(raw)
                rows.append(dict(note, path=filename))
            manifest = dict(
                kind="Stage1AutomaticFullNotesCompanion",
                schema_version="1.0.0",
                binding=_basis(context[2]),
                run_ref=context[3]["run_ref"],
                ledger_state_sha256=context[5]["state_sha256"],
                permit_sha256=self.permit_sha256,
                notes=rows,
                progress=progress,
                human_acceptance=False,
                scientific_acceptance=False,
                stage1_complete=False,
                stage2_started=False,
            )
            raw = canonical(manifest) + b"\n"
            with (output / "manifest.json").open("xb") as stream:
                stream.write(raw)
            return dict(
                manifest_sha256=sha(raw),
                note_count=len(rows),
                bytes=sum(n["bytes"] for n in rows),
                stage2_started=False,
            )

    def delivery_notes(self, credential, ref):
        """Idempotently close the full-note companion at the delivery barrier."""
        with self.intake._lock:
            package = self.records.delivery.read(credential, ref).get(
                "canonical_package"
            )
            _check(
                package is not None and package["status"] == "saved-evidence-validated",
                "automatic-stage1-package-required",
            )
            output = self.root / ("delivery-notes-" + package["manifest_sha256"])
            if not output.exists():
                result = self.export_notes(credential, ref, output)
            else:
                reject_links(output)
                path = output / "manifest.json"
                reject_links(path)
                _check(
                    path.stat().st_size <= 4 * 1024 * 1024,
                    "automatic-stage1-note-manifest-bound",
                )
                raw = path.read_bytes()
                manifest = decode(raw, "automatic notes companion")
                context = self._context(ref)
                progress = self.read(credential, ref)
                _check(
                    manifest["binding"] == _basis(context[2])
                    and manifest["ledger_state_sha256"] == context[5]["state_sha256"]
                    and manifest["permit_sha256"] == self.permit_sha256
                    and manifest["progress"] == progress,
                    "automatic-stage1-note-manifest-stale",
                )
                notes = [
                    self.note(credential, ref, row["work_id"])
                    for row in progress["automatically_recorded"]
                ]
                expected = []
                for number, note in enumerate(notes):
                    filename = f"note-{number:04}.md"
                    text = note.pop("text").encode("utf8")
                    file = output / filename
                    reject_links(file)
                    _check(
                        file.read_bytes() == text,
                        "automatic-stage1-exported-note-differs",
                    )
                    expected.append(dict(note, path=filename))
                _check(
                    manifest["notes"] == expected
                    and {p.name for p in output.iterdir()}
                    == {"manifest.json"} | {r["path"] for r in expected},
                    "automatic-stage1-note-inventory-differs",
                )
                _check(
                    manifest
                    == dict(
                        kind="Stage1AutomaticFullNotesCompanion",
                        schema_version="1.0.0",
                        binding=_basis(context[2]),
                        run_ref=context[3]["run_ref"],
                        ledger_state_sha256=context[5]["state_sha256"],
                        permit_sha256=self.permit_sha256,
                        notes=expected,
                        progress=progress,
                        human_acceptance=False,
                        scientific_acceptance=False,
                        stage1_complete=False,
                        stage2_started=False,
                    ),
                    "automatic-stage1-note-manifest-replay-differs",
                )
                result = dict(
                    manifest_sha256=sha(raw),
                    note_count=len(expected),
                    bytes=sum(r["bytes"] for r in expected),
                    stage2_started=False,
                )
            return dict(
                result,
                manifest_ref="automatic-notes-" + result["manifest_sha256"],
                canonical_manifest_sha256=package["manifest_sha256"],
            )

"""Receipt-fed Stage 2 workflow; this module never launches a model or tool.

The case corpus may be synthetic. Model execution and scientific assessment are
separate evidence. A verified app-server reply is not a production Controller
capture or formal isolation certificate. Missing daily_v3 assessment stays open.
"""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from stage2_check.contracts import decode_json, latest_candidates
from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage2_ideation import build_research_task
from stage2_ideation.integration import build_next_packet
from stage2_live.extraction import (
    _prompt,
    build_span_index,
    expand_span_ids,
    generation_schema,
)
from stage2_live.judge_schemas import _object, _text
from stage2_live.review_models import (
    _assessment,
    _resolution_prompt,
    _review_prompt,
    _schema,
    reconciliation_task,
)
from stage2_workflow.delivery import build_delivery
from stage2_workflow.orchestration import prepare_review_batch
from stage2_workflow.reviews import reconcile_reviews, validate_review
from stage2_workflow.store import (
    add_snapshot,
    finish_action,
    initialize_workflow,
    inspect_workflow,
    start_action,
)

PHASES = (
    "source-review",
    "research",
    "extraction",
    "challenger",
    "challenger-extraction",
    "feasibility",
    "feasibility-extraction",
    "reconciliation",
    "reconciliation-extraction",
)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise Stage2Error("pipeline-artifact-not-regular")
    if path.stat().st_size > 8388608:
        raise Stage2Error("pipeline-artifact-byte-bound-exceeded")
    with path.open("rb") as stream:
        raw = stream.read(8388609)
    if len(raw) > 8388608:
        raise Stage2Error("pipeline-artifact-byte-bound-exceeded")
    return raw


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
    return {"path": str(path), "sha256": _sha(raw)}


class StagePipeline:
    """One server-owned, source-bound sequence with explicit dispatch admission.

    ``verify_receipt`` is the trusted StageModel.verify_receipt method. It must
    independently reopen native evidence. A caller-supplied dictionary alone is
    insufficient. ``next_task`` and ``view`` never execute or admit a model call.
    Reopening verifies retained receipts, and never creates a fresh attempt.
    """

    def __init__(
        self,
        packet_path,
        source_root,
        output_root,
        *,
        expected_packet_sha256,
        source_sha256,
        verify_receipt,
        max_calls=8,
        content_provenance="repository-synthetic-corpus",
    ):
        if (
            not callable(verify_receipt)
            or type(max_calls) is not int
            or not 1 <= max_calls <= 16
        ):
            raise Stage2Error("pipeline-verifier-or-budget-required")
        if not isinstance(source_sha256, str) or len(source_sha256) != 64:
            raise Stage2Error("pipeline-source-binding-required")
        self.packet_path, self.sources = (
            Path(packet_path).resolve(),
            Path(source_root).resolve(),
        )
        self.root = Path(output_root).resolve()
        if (
            self.sources == self.root
            or self.sources in self.root.parents
            or self.root in self.sources.parents
        ):
            raise Stage2Error("pipeline-input-output-overlap")
        self.verify_receipt, self.max_calls = verify_receipt, max_calls
        self.source_sha = source_sha256
        raw = _read(self.packet_path)
        self.initial = decode_json(raw, "pipeline-packet")
        if (
            canonical_hash(self.initial) != expected_packet_sha256
            or self.initial["candidates"]
        ):
            raise Stage2Error("pipeline-empty-bound-seed-required")
        validate_packet(self.initial, self.sources)
        self.binding = dict(
            kind="StagePipelineBinding",
            schema_version="1.0.0",
            packet_sha256=expected_packet_sha256,
            packet_bytes_sha256=_sha(raw),
            source_sha256=source_sha256,
            max_calls=max_calls,
            content_provenance=content_provenance,
            sources={row["path"]: row["sha256"] for row in self.initial["sources"]},
        )
        self.root.mkdir(parents=True, exist_ok=True)
        binding_path = self.root / "binding.json"
        if binding_path.exists():
            if decode_json(_read(binding_path), "pipeline-binding") != self.binding:
                raise Stage2Error("pipeline-reopen-binding-differs")
        else:
            _write(binding_path, self.binding)
        self.run = self.root / "workflow"
        initialize_workflow(
            self.packet_path,
            self.sources,
            self.run,
            {"pipeline_binding": canonical_hash(self.binding)},
            {"execution": "externally-admitted-receipt-fed", "search": False},
            expected_packet_sha256,
        )
        self.packet, self.reviews, self.resolutions = deepcopy(self.initial), [], []
        self.position, self.attempt, self.records, self.pending = 0, 0, [], None
        self.prose, self.batch, self.failure = {}, None, None
        state = inspect_workflow(self.run)
        self.snapshot = state["snapshots"][0]["event"]["payload"]["snapshot_sha256"]
        self._guard()
        self._reopen()

    @contextmanager
    def _lock(self):
        path = self.root / "pipeline.lock"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError as error:
            raise Stage2Error("pipeline-owner-or-crash-lock-present") from error
        try:
            yield
        finally:
            os.close(fd)
            path.unlink()

    def _guard(self):
        if _sha(_read(self.packet_path)) != self.binding["packet_bytes_sha256"]:
            raise Stage2Error("pipeline-seed-bytes-changed")
        for relative, digest in self.binding["sources"].items():
            path = self.sources / relative
            if (
                not path.resolve().is_relative_to(self.sources)
                or _sha(_read(path)) != digest
            ):
                raise Stage2Error("pipeline-source-bytes-changed")
        validate_packet(self.packet, self.sources)
        for row in self.records:
            ref = row["verified_raw_artifact"]
            if _sha(_read(ref["path"])) != ref["sha256"]:
                raise Stage2Error("pipeline-retained-native-bytes-changed")

    def _candidate(self):
        _, latest = latest_candidates(self.packet, [])
        if len(latest) != 1:
            raise Stage2Error("pipeline-explicit-candidate-selection-required")
        return next(iter(latest.values()))

    def _view_version(self):
        if self.packet["schema_version"] == "2.4.0":
            return "1.2.0"
        return (
            "1.1.0" if self.packet["schema_version"] in {"2.2.0", "2.3.0"} else "1.0.0"
        )

    def _prepare_batch(self):
        _, latest = latest_candidates(self.packet, [])
        self.batch = prepare_review_batch(
            self.packet,
            self.snapshot,
            [
                dict(
                    candidate_id=row["candidate_id"],
                    candidate_version=row["version"],
                    included=True,
                    distance=0,
                    reason="Include all pilot ideas; no exclusion score inferred.",
                )
                for row in latest.values()
            ],
            canonical_hash(self.binding),
            review_view_version=self._view_version(),
        )

    def _review_view(self, role):
        candidate = self._candidate()
        if self.batch is None:
            self._prepare_batch()
        return next(
            row["view"]
            for row in self.batch["assignments"]
            if row["candidate_id"] == candidate["candidate_id"] and row["role"] == role
        )

    def _task(self):
        self._guard()
        if self.position >= len(PHASES) or self.failure:
            return None
        phase, schema = PHASES[self.position], None
        if phase == "source-review":
            prompt = (
                "Read only the supplied repository synthetic source corpus. Give a concise "
                "source-by-source evidence summary with exact existing work/version/source IDs "
                "and evidence IDs. Separate stated facts, uncertainty and proposed follow-up. "
                "Do not claim a literature search, canonical Stage1 completion or source access "
                "beyond these saved bytes. No tools, search, file changes or new sources.\n"
                + json.dumps(
                    {
                        "packet": self.packet,
                        "source_text": {
                            row["source_id"]: _read(self.sources / row["path"]).decode(
                                "utf8"
                            )
                            for row in self.packet["sources"]
                        },
                    },
                    ensure_ascii=False,
                )
            )
        elif phase == "research":
            prompt = build_research_task(self.packet, self.snapshot)["prompt"]
            prompt += (
                "\nThis independently authorized pilot is limited to the saved repository "
                "synthetic corpus and supplied quotes; all tools/search/file writes are disabled. "
                "Provide the complete natural-prose comparison and ideas in the final reply. "
                "Do not fabricate a candidate quota or missing evidence.\n"
                + json.dumps({"source_review": self.prose["source-review"]["text"]})
            )
        elif phase == "extraction":
            raw = self.prose["research"]["text"]
            spans = build_span_index(raw)
            schema = generation_schema(spans, self.packet)
            from stage2_ideation import build_extraction_task

            prompt = _prompt(
                build_extraction_task(raw, self.packet, self.snapshot),
                self.packet,
                spans,
                schema,
            )
        elif phase in {"challenger", "feasibility"}:
            prompt = json.dumps(self._review_view(phase), ensure_ascii=False)
            prompt += (
                "\nReview the exact saved input independently in natural prose. No tools or "
                "search. Explain five-axis assessments, assumptions, strongest alternative "
                "and change conditions; preserve unknowns. Do not see or infer peer reviews."
            )
        elif phase.endswith("-extraction") and phase != "reconciliation-extraction":
            role = phase.removesuffix("-extraction")
            schema = _object(
                {
                    "assessment": _schema(self.packet),
                    "assumptions": {"type": "array", "items": _text()},
                    "strongest_alternative": _text(),
                    "change_conditions": {"type": "array", "items": _text()},
                }
            )
            prompt = _review_prompt(self._review_view(role), self.prose[role]["text"])
        else:
            task = reconciliation_task(
                self.packet,
                self._candidate()["candidate_id"],
                self.snapshot,
                self.reviews,
                review_view_version=self._view_version(),
            )
            if phase == "reconciliation":
                prompt = json.dumps(task, ensure_ascii=False)
                prompt += "\nNo tools or search. Preserve factual uncertainty; do not force a resolution."
            else:
                schema = _object(
                    {
                        "assessment": _schema(self.packet),
                        "method": {
                            "type": "string",
                            "enum": [
                                "source-verification",
                                "evidence-debate",
                                "synthesis",
                            ],
                        },
                        "reason": _text(),
                        "evidence_ids": {"type": "array", "items": _text()},
                        "addressed": {"type": "array", "items": _text()},
                        "substantive_disagreements": {
                            "type": "array",
                            "items": _text(),
                        },
                        "changed_judgment_reason": {"type": ["string", "null"]},
                    }
                )
                prompt = _resolution_prompt(task, self.prose["reconciliation"]["text"])
        if schema is not None and phase != "extraction":
            prompt += (
                "\nReturn exactly one final JSON object matching this schema:\n"
                + json.dumps(schema)
            )
        if self.attempt:
            previous = self.records[-1]
            prompt += (
                "\nOne bounded semantic repair of the retained failed attempt; no new "
                "research or evidence. Correct structure/provenance only.\n"
                + json.dumps(
                    {
                        "error": previous["validation_error"],
                        "previous_final": previous["text"],
                    }
                )
            )
        task = dict(
            unit_key=f"pipeline-{self.position + 1:02d}-{self.attempt + 1:02d}",
            phase=phase,
            attempt=self.attempt,
            prompt=prompt,
            schema=schema,
            prompt_sha256=_sha(prompt.encode()),
            source_sha256=self.source_sha,
            snapshot_sha256=self.snapshot,
            tools_policy="none",
        )
        task["task_sha256"] = canonical_hash(task)
        return task

    def next_task(self):
        if self.pending or self.failure or len(self.records) >= self.max_calls:
            return None
        return deepcopy(self._task())

    def begin_task(self, task_sha256):
        with self._lock():
            task = self.next_task()
            if task is None or task["task_sha256"] != task_sha256:
                raise Stage2Error("pipeline-task-unavailable-or-stale")
            if len(list((self.root / "intents").glob("*.json"))) != len(self.records):
                raise Stage2Error("pipeline-stale-instance-or-unobserved-intent")
            self.pending = task
            _write(self.root / "intents" / f"{len(self.records) + 1:04d}.json", task)
            state = inspect_workflow(self.run)
            start_action(
                self.run,
                task["unit_key"],
                "native-appserver-stage-unit",
                {"task_sha256": task_sha256},
                self.binding,
                state["head_sha256"],
            )
            return deepcopy(task)

    def _verified(self, receipt, task):
        result = self.verify_receipt(
            receipt,
            expected_prompt_sha256=task["prompt_sha256"],
            expected_source_sha256=self.source_sha,
        )
        if not isinstance(result, dict) or result.get("status") != "completed":
            raise Stage2Error("pipeline-completed-native-evidence-required")
        for name in ("model", "thread_id", "turn_id", "final_text"):
            if not isinstance(result.get(name), str) or not result[name].strip():
                raise Stage2Error("pipeline-native-unit-shape")
        if (
            result.get("prompt_sha256") != task["prompt_sha256"]
            or result.get("source_sha256") != self.source_sha
            or result.get("observed_tool_items") != []
            or len(result["final_text"].encode("utf8")) > 262144
        ):
            raise Stage2Error("pipeline-native-unit-binding-or-tool-policy")
        ref = result.get("raw_artifact")
        if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
            raise Stage2Error("pipeline-native-artifact-required")
        raw = _read(ref["path"])
        if len(raw) > 8388608 or _sha(raw) != ref["sha256"]:
            raise Stage2Error("pipeline-native-artifact-changed")
        return result

    def _consume(self, task, result, *, snapshot_after=None):
        phase, text = task["phase"], result["final_text"]
        if task["schema"] is None:
            if phase in {"challenger", "feasibility"} and any(
                self.prose[role]["thread_id"] == result["thread_id"]
                for role in ("challenger", "feasibility")
                if role in self.prose
            ):
                raise Stage2Error("pipeline-review-thread-isolation-required")
            self.prose[phase] = dict(
                text=text,
                thread_id=result["thread_id"],
                raw_artifact=deepcopy(result["raw_artifact"]),
            )
            return
        value = decode_json(text, "pipeline-model-json")
        Draft202012Validator(task["schema"]).validate(value)
        if phase == "extraction":
            raw = self.prose["research"]["text"]
            extraction = expand_span_ids(value, raw, build_span_index(raw), self.packet)
            proposed = build_next_packet(
                self.packet, self.sources, raw, extraction, self.snapshot
            )["packet"]
            if snapshot_after is None:
                path = self.root / "packets" / (canonical_hash(proposed) + ".json")
                if not path.exists():
                    _write(path, proposed)
                state = inspect_workflow(self.run)
                add_snapshot(
                    self.run,
                    path,
                    self.sources,
                    "Verified reply extracted; independent review pending.",
                    {
                        row["candidate_id"]: {
                            "status": "affected",
                            "reason": "New native ideation.",
                        }
                        for row in proposed["candidates"]
                    },
                    state["head_sha256"],
                )
                snapshot_after = inspect_workflow(self.run)["latest_snapshot"]["event"][
                    "payload"
                ]["snapshot_sha256"]
            self.packet, self.snapshot = proposed, snapshot_after
        elif phase in {"challenger-extraction", "feasibility-extraction"}:
            role = phase.removesuffix("-extraction")
            view, captured = self._review_view(role), self.prose[role]
            review = dict(
                role=role,
                view_sha256=canonical_hash(view),
                snapshot_sha256=self.snapshot,
                candidate_id=view["candidate"]["candidate_id"],
                candidate_version=view["candidate"]["version"],
                assessment=_assessment(
                    value["assessment"],
                    self.packet,
                    view["candidate"]["candidate_id"],
                    task["unit_key"],
                ),
                session_id=captured["thread_id"],
                native_artifact=captured["raw_artifact"],
                initial=True,
                assumptions=value["assumptions"],
                strongest_alternative=value["strongest_alternative"],
                change_conditions=value["change_conditions"],
            )
            validate_review(review, view, self.packet)
            self.reviews.append(review)
        else:
            candidate_id = self._candidate()["candidate_id"]
            resolution = {
                **value,
                "review_sha256s": [canonical_hash(row) for row in self.reviews],
            }
            resolution["assessment"] = _assessment(
                value["assessment"], self.packet, candidate_id, task["unit_key"]
            )
            reconcile_reviews(
                self.packet,
                candidate_id,
                self.snapshot,
                self.reviews,
                resolution,
                review_view_version=self._view_version(),
            )
            self.resolutions.append(
                dict(candidate_id=candidate_id, resolution=resolution)
            )

    def accept(self, task_sha256, receipt):
        with self._lock():
            task = self.pending
            if task is None or task["task_sha256"] != task_sha256:
                raise Stage2Error("pipeline-no-matching-pending-unit")
            result = self._verified(receipt, task)
            self._guard()
            index = len(self.records) + 1
            ref = _write(self.root / "units" / f"{index:04d}-receipt.json", receipt)
            raw_path = self.root / "units" / f"{index:04d}-final.txt"
            with raw_path.open("xb") as stream:
                stream.write(result["final_text"].encode("utf8"))
            status, error = "accepted", None
            try:
                self._consume(task, result)
            except (ValueError, KeyError, TypeError, ValidationError) as failure:
                status, error = "invalid", str(failure)[:600]
            artifacts = {
                "receipt.json": ref,
                "final.txt": {"path": str(raw_path), "sha256": _sha(_read(raw_path))},
            }
            state = inspect_workflow(self.run)
            finish_action(
                self.run,
                task["unit_key"],
                "complete" if status == "accepted" else "failed",
                artifacts,
                None,
                None if status == "accepted" else "structured-output-invalid",
                state["head_sha256"],
            )
            record = dict(
                task=task,
                receipt=receipt,
                verified_raw_artifact=deepcopy(result["raw_artifact"]),
                status=status,
                text=result["final_text"],
                validation_error=error,
                snapshot_after=self.snapshot,
            )
            _write(self.root / "records" / f"{index:04d}.json", record)
            self.records.append(record)
            self.pending = None
            if status == "accepted":
                self.position, self.attempt = self.position + 1, 0
            elif self.attempt == 0:
                self.attempt = 1
            else:
                self.failure = "semantic-repair-exhausted"
            return self.view()

    def _reopen(self):
        paths = sorted((self.root / "records").glob("*.json"))
        for index, path in enumerate(paths, 1):
            if path.name != f"{index:04d}.json":
                raise Stage2Error("pipeline-record-sequence-invalid")
            record = decode_json(_read(path), "pipeline-record")
            task = self._task()
            intent = decode_json(
                _read(self.root / "intents" / path.name), "pipeline-intent"
            )
            if task != record["task"] or intent != task:
                raise Stage2Error("pipeline-retained-task-differs")
            result = self._verified(record["receipt"], task)
            if (
                record["text"] != result["final_text"]
                or record["verified_raw_artifact"] != result["raw_artifact"]
            ):
                raise Stage2Error("pipeline-retained-final-differs")
            status, error = "accepted", None
            try:
                self._consume(task, result, snapshot_after=record["snapshot_after"])
            except (ValueError, KeyError, TypeError, ValidationError) as failure:
                status, error = "invalid", str(failure)[:600]
            if status != record["status"] or error != record["validation_error"]:
                raise Stage2Error("pipeline-retained-validation-differs")
            self.records.append(record)
            if status == "accepted":
                self.position, self.attempt = self.position + 1, 0
            elif self.attempt == 0:
                self.attempt = 1
            else:
                self.failure = "semantic-repair-exhausted"
        intents = sorted((self.root / "intents").glob("*.json"))
        if len(intents) == len(paths) + 1:
            self.pending = decode_json(_read(intents[-1]), "pipeline-pending")
            if self.pending != self._task():
                raise Stage2Error("pipeline-pending-task-differs")
        elif len(intents) != len(paths):
            raise Stage2Error("pipeline-intent-sequence-invalid")
        state = inspect_workflow(self.run)
        for record in self.records:
            task = record["task"]
            action = state["actions"].get(task["unit_key"])
            expected_status = "complete" if record["status"] == "accepted" else "failed"
            if (
                action is None
                or action["request"]["inputs"] != {"task_sha256": task["task_sha256"]}
                or action["result"] is None
                or action["result"]["status"] != expected_status
                or action["result"]["artifacts"]["final.txt"]["sha256"]
                != _sha(record["text"].encode())
            ):
                raise Stage2Error("pipeline-workflow-receipt-differs")
        if (
            canonical_hash(state["latest_snapshot"]["packet"])
            != canonical_hash(self.packet)
            or state["latest_snapshot"]["event"]["payload"]["snapshot_sha256"]
            != self.snapshot
        ):
            raise Stage2Error("pipeline-workflow-recovery-unobserved")

    def view(self):
        self._guard()
        _, current = latest_candidates(self.packet, [])
        return dict(
            phase=PHASES[self.position] if self.position < len(PHASES) else "delivery",
            status="execution-unknown"
            if self.pending
            else self.failure
            or (
                "budget-pending"
                if len(self.records) >= self.max_calls and self.position < len(PHASES)
                else "incomplete-assessment"
                if self.position == len(PHASES)
                else "ready"
            ),
            completed_steps=self.position,
            model_units_observed=len(self.records),
            max_calls=self.max_calls,
            planned_steps=len(PHASES),
            history=[
                dict(
                    phase=row["task"]["phase"],
                    attempt=row["task"]["attempt"],
                    status=row["status"],
                )
                for row in self.records
            ],
            daily_v3_status="pending-independent-content-first-R1-R2-and-necessary-ADJ",
            stage3_execution_authorized=False,
            scientific_improvement="not-yet-demonstrated",
            content_provenance=self.binding["content_provenance"],
            packet_schema_version=self.packet["schema_version"],
            candidates=deepcopy(list(current.values())),
            source_count=len(self.packet["sources"]),
        )

    def publish(self, output_dir):
        """Explicitly publish a source-bound incomplete assessment; no model I/O."""
        with self._lock():
            self._guard()
            if self.batch is None:
                self._prepare_batch()
            rows = [
                dict(
                    candidate_id=row["candidate_id"],
                    candidate_version=row["candidate_version"],
                    role=row["role"],
                    status="complete",
                    review=row,
                    error=None,
                )
                for row in self.reviews
            ]
            resolution = dict(
                candidate_resolutions=self.resolutions,
                next_step="Complete independent daily_v3 assessment before scientific completion.",
            )
            state = inspect_workflow(self.run)
            manifest = build_delivery(
                self.run,
                self.batch,
                rows,
                resolution,
                output_dir,
                state["head_sha256"],
                record_registered_history=True,
            )
            _write(Path(output_dir) / "pipeline-assessment-status.json", self.view())
            return manifest

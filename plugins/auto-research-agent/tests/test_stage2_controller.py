# ruff: noqa: E402 -- import the repository CLI without installing a package.
"""Sequential Stage 2 controller regression tests with a strict synthetic adapter."""

import copy
import hashlib
import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
sys.path.insert(0, str(PLUGIN / "cli"))
sys.path.insert(0, str(HERE))

from stage1_eval.common import canonical
from stage1_eval.model import _api_schema
from stage1_eval.model_calls import (
    MODEL_CALL_ARCHIVE_VERSION,
    _attempt_files,
    _command,
    _normalize_policy,
    _request_record,
    replay_native_model_call_archive,
)
from stage2_common import Stage2Error, canonical_hash
from stage2_fixture_helpers import write_stage2_fixture
from stage2_live.controller import (
    _ProductionAdapter,
    _native_binding_bytes,
    _replay_model_config,
    _require_saved_unit,
    _run_controller,
    _saved_resolution_unit_label,
    _validate_spec,
    _verify_action_environments,
    apply_revision,
    verify_controller,
)
from stage2_live.extraction import (
    _prompt,
    _request,
    build_span_index,
    expand_span_ids,
    generation_schema,
)
from stage2_live.judges import _execution_policy
from stage2_live.replay import verify_extraction
from stage2_workflow import initialize_workflow, inspect_workflow
from test_stage2_checker import assessment
from test_stage2_ideation import valid_extraction
from test_stage2_readonly_replay import POLICY, SNAPSHOT, digest, write_json


def _write_faithful_model_archive(root, label, prompt, schema, value, config, policy):
    archive = root / f"{label}.model-call"
    archive.mkdir(parents=True)
    schema_raw = canonical(schema) + b"\n"
    generation_raw = canonical(_api_schema(schema, preserve_constraints=True))
    normalized_policy = _normalize_policy(policy, None)
    request = _request_record(
        prompt, schema_raw, generation_raw, config, normalized_policy, label
    )
    (archive / "request.json").write_bytes(canonical(request) + b"\n")
    (archive / "prompt.txt").write_bytes(prompt.encode("utf-8"))
    (archive / "schema.json").write_bytes(schema_raw)
    (archive / "generation-schema.json").write_bytes(generation_raw)
    files = _attempt_files(archive, 1)
    stdout = b"\n".join(
        [
            canonical(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": json.dumps(value, ensure_ascii=False),
                    },
                }
            ),
            canonical({"type": "turn.completed"}),
        ]
    )
    files["stdout"].write_bytes(stdout)
    files["stderr"].write_bytes(b"")
    files["output"].write_bytes(canonical(value))
    record = {
        "archive_version": MODEL_CALL_ARCHIVE_VERSION,
        "attempt": 1,
        "request_fingerprint_sha256": request["request_fingerprint_sha256"],
        "command": _command(
            config["codex"],
            config["model"],
            config["reasoning"],
            archive / "generation-schema.json",
            files["output"],
        ),
        "config": config,
        "execution_policy": normalized_policy,
        "timeout_seconds": normalized_policy["timeout_seconds"],
        "returncode": 0,
        "timed_out": False,
        "status": "completed",
        "generation_status": "completed",
        "semantic_status": "accepted",
        "failure_class": None,
        "files": {
            key: {
                "path": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for key, path in files.items()
            if key != "record"
        },
    }
    files["record"].write_bytes(canonical(record) + b"\n")
    return replay_native_model_call_archive(
        archive,
        expected_prompt=prompt,
        expected_schema=root / f"{label}.schema.json",
        expected_config=config,
        expected_policy=policy,
    )[1]


class SyntheticAdapter:
    synthetic = True
    identity = "strict-controller-test-adapter-v1"

    def __init__(self, *, fail_role=None, blocking=False):
        self.fail_role = fail_role
        self.blocking = blocking
        self.calls = []
        self.review_inputs = []

    def research(self, context):
        self.calls.append("research")
        return {
            "raw_proposal": "A bounded synthetic comparison and one retained idea.",
            "record_sha256_receipt": "1" * 64,
            "capture_evidence_class": "synthetic-test-only",
            "synthetic": True,
        }

    def extract(self, context):
        self.calls.append("extract")
        packet = copy.deepcopy(context["packet"])
        packet["packet_id"] = "controller-extracted-packet"
        return {
            "status": "passed",
            "next_packet": {
                "packet": packet,
                "review_required": True,
                "native_execution_verified": False,
                "scientific_quality_verified": False,
            },
            "adapter_mode": "injected-test",
        }

    def review(self, context):
        role = context["role"]
        self.calls.append(f"review:{role}")
        self.review_inputs.append(copy.deepcopy(context))
        if role == self.fail_role:
            raise RuntimeError(f"synthetic {role} interruption")
        value = assessment(
            context["packet"],
            event_id=f"synthetic-{role}",
            disposition="recommend",
        )
        if self.blocking:
            value["checks"]["materials"] = {
                "status": "unknown",
                "score": None,
                "rationale": "The prerequisite material is not recorded.",
                "evidence_ids": [],
                "blocking": True,
                "next_check": "Acquire the missing prerequisite measurement.",
            }
            value["disposition"] = "park"
            value["next_step"] = "Acquire prerequisite evidence."
        return {
            "review": {
                "role": role,
                "view_sha256": canonical_hash(context["view"]),
                "snapshot_sha256": context["snapshot_sha256"],
                "candidate_id": context["candidate_id"],
                "candidate_version": 1,
                "assessment": value,
                "session_id": f"session-{role}",
                "native_artifact": {
                    "path": f"synthetic-{role}.jsonl",
                    "sha256": ("2" if role == "challenger" else "3") * 64,
                },
                "initial": True,
                "assumptions": ["The bounded observations are comparable."],
                "strongest_alternative": "A bounded alternative explanation.",
                "change_conditions": ["New contradictory evidence."],
            },
            "adapter_mode": "injected-test",
        }

    def resolve(self, context):
        self.calls.append("resolve")
        value = copy.deepcopy(context["reviews"][0]["assessment"])
        return {
            "resolution": {
                "review_sha256s": [canonical_hash(row) for row in context["reviews"]],
                "method": "synthesis",
                "reason": "The independent categorical judgments agree.",
                "evidence_ids": ["ev-1"],
                "addressed": [],
                "assessment": value,
                "substantive_disagreements": [],
                "changed_judgment_reason": None,
            },
            "adapter_mode": "injected-test",
        }


class Stage2ControllerTests(unittest.TestCase):
    def test_copied_bundle_checks_all_external_captures_with_retained_receipts(self):
        copied = self.root / "copied-controller" / "native" / "extraction"
        copied.mkdir(parents=True)
        (copied / "result.json").write_text("{}", encoding="utf-8")
        kinds = (
            "stage2-ideation-native",
            "stage2-independent-review",
            "stage2-review-reconciliation",
        )
        values, actions, expected = {}, {}, []
        for index, kind in enumerate(kinds):
            capture = self.root / "original-captures" / str(index)
            capture.mkdir(parents=True)
            (capture / "run.json").write_text("{}", encoding="utf-8")
            receipt = str(index + 1) * 64
            artifact = {"path": str(capture / "run.json")}
            value = (
                {"capture_dir": capture, "record_sha256_receipt": receipt}
                if index == 0
                else {
                    "review": {"native_artifact": artifact},
                    "native_receipt": receipt,
                }
                if index == 1
                else {"native_artifact": artifact, "native_receipt": receipt}
            )
            actions[str(index)] = {"request": {"action_kind": kind}}
            values[str(index)] = value
            expected.append((capture, receipt))
        self.assertEqual(list(copied.parent.rglob("run.json")), [])
        record = {
            "stable_request_binding": {
                "codex_home": "saved-home",
                "workspace": "saved-workspace",
            },
            "event_summary": {"thread_id": "saved-thread"},
        }
        inventory, preflight = {"entries": {}}, {"receipt": "saved"}
        spec = {"execution_inventories": {"saved-thread": inventory}}
        with (
            patch(
                "stage2_live.controller.verify_capture", return_value=(record, "")
            ) as capture_verifier,
            patch(
                "stage2_live.controller.preflight_for_environment",
                return_value=preflight,
            ),
            patch(
                "stage2_live.controller.verify_environment_capture"
            ) as environment_verifier,
        ):
            _verify_action_environments(spec, {"actions": actions}, values)
            self.assertEqual(
                [c.args for c in capture_verifier.call_args_list], expected
            )
            self.assertEqual(
                [c.args for c in environment_verifier.call_args_list],
                [(*item, preflight, inventory) for item in expected],
            )
            for index in range(3):
                with self.subTest(missing_environment_for=kinds[index]):
                    environment_verifier.side_effect = [None] * index + [
                        Stage2Error("execution-inventory-not-captured")
                    ]
                    with self.assertRaisesRegex(
                        Stage2Error, "execution-inventory-not-captured"
                    ):
                        _verify_action_environments(spec, {"actions": actions}, values)

    def test_native_capture_uses_extractor_contract_keys_and_allows_git_root(self):
        for key in ("review_view", "reconciliation_task"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                workspace, home, sources = (
                    root / "workspace",
                    root / "home",
                    root / "sources",
                )
                for p in (workspace, home, sources):
                    p.mkdir()
                (workspace / ".git").mkdir()
                (sources / "source.txt").write_text("public source", encoding="utf-8")
                native = {
                    "codex": "fixture",
                    "model": "gpt-test",
                    "reasoning": "high",
                    "config_bindings": {},
                    "policy_bindings": {},
                }
                with (
                    patch(
                        "stage2_live.controller.preflight_for_environment",
                        return_value={},
                    ),
                    patch("stage2_live.controller.verify_environment_start"),
                    patch("stage2_live.controller.verify_environment_capture"),
                    patch(
                        "stage2_live.controller.capture_native",
                        return_value={
                            "status": "complete",
                            "record_sha256_receipt": "a" * 64,
                            "event_summary": {"thread_id": "synthetic"},
                        },
                    ) as capture,
                ):
                    _ProductionAdapter._capture(
                        {"prompt": "bounded task"},
                        sources,
                        {"workspace": workspace, "home": home},
                        {"native": native},
                        root / "out",
                        binding_key=key,
                    )
                self.assertEqual(
                    set(capture.call_args.kwargs["input_bindings"]), {key, "sources"}
                )

    def test_read_only_verification_refuses_missing_unit_without_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(Stage2Error, "read-only-artifact"):
                _require_saved_unit(
                    root,
                    "extraction",
                    "result.json",
                    {
                        "result_sha256": "a" * 64,
                        "unit_receipts": {"extraction": "b" * 64},
                    },
                )
            self.assertEqual(list(root.iterdir()), [])

    def test_resolution_unit_label_is_explicit_receipt_bound_and_read_only(self):
        def saved(label):
            root = self.root / f"saved-{label}"
            (root / f"{label}.model-call").mkdir(parents=True, exist_ok=True)
            (root / f"{label}.model-call" / "request.json").write_text(
                "{}", encoding="utf-8"
            )
            (root / f"{label}.schema.json").write_text("{}", encoding="utf-8")
            unit = root / f"{label}.unit.json"
            unit.write_text('{"accepted":true}', encoding="utf-8")
            envelope = root / "resolution.json"
            envelope.write_text('{"resolution":"saved"}', encoding="utf-8")
            receipt = {
                "result_sha256": digest(envelope),
                "unit_receipts": {label: digest(unit)},
            }
            return root, receipt

        for label, metadata in (
            ("resolution", {}),
            (
                "resolution-extraction",
                {"extraction_unit_label": "resolution-extraction"},
            ),
        ):
            with self.subTest(label=label):
                root, receipt = saved(label)
                value = {**metadata, "replay_receipt": receipt}
                before = {
                    path: path.read_bytes()
                    for path in root.rglob("*")
                    if path.is_file()
                }
                chosen = _saved_resolution_unit_label(value)
                _require_saved_unit(root, chosen, "resolution.json", receipt)
                after = {
                    path: path.read_bytes()
                    for path in root.rglob("*")
                    if path.is_file()
                }
                self.assertEqual(chosen, label)
                self.assertEqual(after, before)

        _, legacy_receipt = saved("resolution")
        for bad in ("../resolution", "resolution.json", "other"):
            with (
                self.subTest(bad_label=bad),
                self.assertRaisesRegex(Stage2Error, "unit-label-invalid"),
            ):
                _saved_resolution_unit_label(
                    {
                        "extraction_unit_label": bad,
                        "replay_receipt": legacy_receipt,
                    }
                )
        with self.assertRaisesRegex(Stage2Error, "unit-label-receipt-mismatch"):
            _saved_resolution_unit_label(
                {
                    "extraction_unit_label": "resolution-extraction",
                    "replay_receipt": legacy_receipt,
                }
            )
        with self.assertRaisesRegex(Stage2Error, "unit-label-receipt-mismatch"):
            _saved_resolution_unit_label(
                {
                    "extraction_unit_label": "resolution-extraction",
                    "replay_receipt": {
                        "result_sha256": "a" * 64,
                        "unit_receipts": {
                            "resolution": "b" * 64,
                            "resolution-extraction": "c" * 64,
                        },
                    },
                }
            )

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.sources = self.root / "sources"
        self.packet = write_stage2_fixture(self.sources, candidate_count=1)
        self.packet_path = self.root / "packet.json"
        self.packet_path.write_text(json.dumps(self.packet), encoding="utf-8")
        self.run = self.root / "workflow"
        initialize_workflow(
            self.packet_path,
            self.sources,
            self.run,
            {"model": "synthetic-model", "reasoning": "medium"},
            {"path": "policy.json", "sha256": "a" * 64},
        )
        self.initial = inspect_workflow(self.run)
        self.base = self.initial["latest_snapshot"]["event"]["payload"][
            "snapshot_sha256"
        ]
        self.controller = self.root / "controller"
        self.delivery = self.root / "delivery"
        self.spec = self._spec()

    def _spec(self):
        names = [
            "research",
            "extractor",
            "review:candidate-1:challenger",
            "review:candidate-1:feasibility",
            "resolution:candidate-1",
        ]
        workspaces = {}
        for index, name in enumerate(names):
            workspaces[name] = {
                "workspace": str(self.root / f"subject-{index}"),
                "home": str(self.root / f"home-{index}"),
            }
        return {
            "confirmed_brief_sha256": canonical_hash(self.packet["brief"]),
            "base_snapshot_sha256": self.base,
            "seed": "fixed-controller-seed",
            "native": {
                "codex": "synthetic-codex",
                "model": "synthetic-model",
                "reasoning": "medium",
                "extraction_policy": {
                    "schema_version": "3.1.0",
                    "evaluator_bundle_sha256": "b" * 64,
                    "timeout_seconds": 600,
                    "max_transient_transport_retries": 1,
                    "max_semantic_corrections_per_unit": 1,
                    "retry_timeouts": False,
                },
                "config_bindings": {},
                "policy_bindings": {
                    "sandbox": "workspace-write",
                    "network_access": True,
                },
            },
            "preflight": {"synthetic": True},
            "workspaces": workspaces,
        }

    def run_controller(self, adapter, *, expected_head=None, spec=None):
        return _run_controller(
            self.run,
            self.controller,
            self.delivery,
            expected_head or inspect_workflow(self.run)["head_sha256"],
            spec or self.spec,
            adapter,
        )

    def test_complete_pipeline_replays_without_new_calls_and_awaits_human(self):
        adapter = SyntheticAdapter()
        first = self.run_controller(adapter, expected_head=self.initial["head_sha256"])
        self.assertEqual(first["status"], "awaiting-human")
        self.assertEqual(
            (first["human_selection"], first["stage3_execution_authorized"]),
            ("pending", False),
        )
        self.assertFalse(first["formal_ready"])
        self.assertTrue(first["selection_ready"])
        self.assertFalse(first["pilot_executable"])
        self.assertEqual(first["delivery_manifest"]["human_selection"], "pending")
        verified = verify_controller(
            self.controller, first["controller_manifest_sha256"]
        )
        self.assertTrue(verified["synthetic_test_only"])
        self.assertFalse(verified["authentic_native_execution"])
        self.assertEqual(
            verified["model_call_verification"], "synthetic-not-authenticatable"
        )
        self.assertFalse(verified["pilot_executable"])
        self.assertFalse(verified["formal_ready"])
        with self.assertRaisesRegex(Stage2Error, "manifest-invalid"):
            verify_controller(self.controller, "f" * 64)
        calls = list(adapter.calls)

        replay = self.run_controller(
            adapter, expected_head=first["workflow_head_sha256"]
        )
        self.assertEqual(replay["status"], "awaiting-human")
        self.assertEqual(adapter.calls, calls)
        self.assertTrue(all(unit["replayed"] for unit in replay["units"]))

    def test_versioned_manifests_preserve_needs_workspace_then_progress(self):
        adapter = SyntheticAdapter()
        partial_spec = copy.deepcopy(self.spec)
        partial_spec["workspaces"] = {
            key: value
            for key, value in partial_spec["workspaces"].items()
            if key in {"research", "extractor"}
        }
        partial = self.run_controller(
            adapter,
            expected_head=self.initial["head_sha256"],
            spec=partial_spec,
        )
        self.assertEqual(partial["status"], "needs-workspace")
        self.assertEqual(
            partial["required_workspace_keys"],
            [
                "resolution-slot:0",
                "review-slot:0:challenger",
                "review-slot:0:feasibility",
            ],
        )
        self.assertEqual(adapter.calls, ["research", "extract"])

        progressed_spec = copy.deepcopy(partial_spec)
        for index, key in enumerate(partial["required_workspace_keys"], 20):
            progressed_spec["workspaces"][key] = {
                "workspace": str(self.root / f"slot-subject-{index}"),
                "home": str(self.root / f"slot-home-{index}"),
            }
        progressed = self.run_controller(
            adapter,
            expected_head=partial["workflow_head_sha256"],
            spec=progressed_spec,
        )
        self.assertEqual(progressed["status"], "awaiting-human")
        self.assertNotEqual(
            partial["controller_manifest_sha256"],
            progressed["controller_manifest_sha256"],
        )
        self.assertEqual(
            verify_controller(self.controller, partial["controller_manifest_sha256"])[
                "manifest"
            ]["status"],
            "needs-workspace",
        )
        self.assertEqual(
            verify_controller(
                self.controller, progressed["controller_manifest_sha256"]
            )["manifest"]["status"],
            "awaiting-human",
        )

    def test_indexed_slots_cover_generated_candidate_ids(self):
        class GeneratedCandidateAdapter(SyntheticAdapter):
            def extract(self, context):
                result = super().extract(context)
                generated = copy.deepcopy(
                    result["next_packet"]["packet"]["candidates"][0]
                )
                generated.update(
                    candidate_id="generated-after-research",
                    question="Can the generated candidate answer the bounded question?",
                )
                result["next_packet"]["packet"]["candidates"].append(generated)
                return result

            def review(self, context):
                result = super().review(context)
                result["review"]["assessment"]["candidate_id"] = context["candidate_id"]
                result["review"]["assessment"]["event_id"] = (
                    f"synthetic-{context['candidate_id']}-{context['role']}"
                )
                return result

        spec = copy.deepcopy(self.spec)
        spec["workspaces"] = {
            key: value
            for key, value in spec["workspaces"].items()
            if key in {"research", "extractor"}
        }
        for index in range(2):
            for suffix in ("challenger", "feasibility"):
                key = f"review-slot:{index}:{suffix}"
                spec["workspaces"][key] = {
                    "workspace": str(self.root / f"{key}-workspace"),
                    "home": str(self.root / f"{key}-home"),
                }
            key = f"resolution-slot:{index}"
            spec["workspaces"][key] = {
                "workspace": str(self.root / f"{key}-workspace"),
                "home": str(self.root / f"{key}-home"),
            }
        result = self.run_controller(
            GeneratedCandidateAdapter(),
            expected_head=self.initial["head_sha256"],
            spec=spec,
        )
        self.assertEqual(result["status"], "awaiting-human")
        self.assertEqual(
            sorted(row["candidate_id"] for row in result["batch"]["assignments"]),
            [
                "candidate-1",
                "candidate-1",
                "generated-after-research",
                "generated-after-research",
            ],
        )

    def test_missing_unit_precheck_never_dispatches_resume_entrypoints(self):
        with (
            patch("stage2_live.controller.run_live_extraction") as extraction,
            patch("stage2_live.controller.extract_review") as review,
            patch("stage2_live.controller.extract_resolution") as resolution,
        ):
            with self.assertRaisesRegex(Stage2Error, "read-only-artifact"):
                _require_saved_unit(
                    self.root / "missing",
                    "initial-review",
                    "review.json",
                    {
                        "result_sha256": "a" * 64,
                        "unit_receipts": {"initial-review": "b" * 64},
                    },
                )
        extraction.assert_not_called()
        review.assert_not_called()
        resolution.assert_not_called()

    def test_controller_verifier_has_no_execution_entrypoint(self):
        source = inspect.getsource(verify_controller)
        for forbidden in (
            "run_live_extraction(",
            "extract_review(",
            "extract_resolution(",
        ):
            self.assertNotIn(forbidden, source)

    def test_reconstructed_config_authenticates_faithful_extraction_archive(self):
        sources = self.root / "archive-sources"
        packet = write_stage2_fixture(sources, candidate_count=0)
        raw = (
            "The monthly and annual outcomes are not directly comparable. "
            "Both reports reuse the same survey frame. "
            "Improve the existing measure with a prespecified alignment rule. "
            "A new concept uses disagreement as the measured signal."
        )
        generated = valid_extraction(raw)
        span_id = build_span_index(raw)["spans"][0]["span_id"]
        for row in generated["comparison_rows"]:
            row["spans"] = [{"span_id": span_id}]
        for row in generated["candidates"]:
            row["spans"] = [{"span_id": span_id}]
            for key in ("candidate_id", "version", "parent_version"):
                row["candidate"].pop(key)
            row["existing_candidate_id"] = None

        output = self.root / "faithful-extraction"
        output.mkdir()
        codex = self.root / "archive-codex.exe"
        codex.write_bytes(b"faithful synthetic runtime")
        home = self.root / "archive-home"
        home.mkdir()
        config = {
            "codex": str(codex.resolve()),
            "codex_executable_sha256": digest(codex),
            "evaluator_home": str(home.resolve()),
            "model": "test-model",
            "reasoning": "high",
        }
        task = __import__(
            "stage2_ideation", fromlist=["build_extraction_task"]
        ).build_extraction_task(raw, packet, SNAPSHOT)
        spans = build_span_index(raw)
        schema = generation_schema(spans, packet)
        prompt = _prompt(task, packet, spans, schema)
        write_json(output / "extraction.schema.json", schema)
        replayed = _write_faithful_model_archive(
            output, "extraction", prompt, schema, generated, config, POLICY
        )
        unit = {
            "label": "extraction",
            "value": generated,
            "provenance": {"initial": replayed, "correction": None},
        }
        unit_path = write_json(output / "extraction.unit.json", unit)
        expanded = expand_span_ids(generated, raw, spans, packet)
        validate_extraction = __import__(
            "stage2_ideation", fromlist=["validate_extraction"]
        ).validate_extraction
        validated = validate_extraction(raw, expanded, packet, SNAPSHOT)
        next_packet = __import__(
            "stage2_ideation.integration", fromlist=["build_next_packet"]
        ).build_next_packet(packet, sources, raw, validated, SNAPSHOT)
        policy = _execution_policy(POLICY)
        request = _request(
            task,
            packet,
            sources,
            spans,
            schema,
            prompt,
            config["codex"],
            config["evaluator_home"],
            config["model"],
            config["reasoning"],
            policy,
            "native",
        )
        write_json(output / "request.json", request)
        (output / "raw-proposal.bin").write_bytes(raw.encode())
        write_json(output / "input-packet.json", packet)
        write_json(output / "span-index.json", spans)
        write_json(
            output / "normalization-receipt.json",
            {
                "kind": "Stage2ExtractionNormalizationReceipt",
                "schema_version": "1.0.0",
                "input_encoding": "utf-8",
                "normalization_applied": False,
                "raw_before_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "raw_after_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "packet_canonical_sha256": canonical_hash(packet),
                "source_bindings": request["source_bindings"],
            },
        )
        result = {
            "kind": "Stage2LiveExtractionResult",
            "schema_version": "1.0.0",
            "status": "passed",
            "request_sha256": canonical_hash(request),
            "extraction": validated,
            "next_packet": next_packet,
            "model_call_provenance": unit["provenance"],
            "native_execution_verified": True,
            "scientific_approval": None,
            "usage": None,
            "cost": None,
            "unit_receipts": {"extraction": digest(unit_path)},
        }
        result_path = write_json(output / "result.json", result)
        receipt = {
            "result_sha256": digest(result_path),
            "unit_receipts": {"extraction": digest(unit_path)},
        }

        reconstructed = _replay_model_config(request)
        self.assertEqual(reconstructed, config)
        with patch(
            "stage1_eval.model_calls.call_model_v31",
            side_effect=AssertionError("model dispatch forbidden"),
        ) as dispatch:
            verified = verify_extraction(
                output,
                receipt,
                raw_proposal=raw,
                packet=packet,
                source_root=sources,
                snapshot_sha256=SNAPSHOT,
                expected_config=reconstructed,
                expected_policy=POLICY,
            )
        dispatch.assert_not_called()
        self.assertEqual(verified["result"], result)

    def test_authentic_preflight_binds_inventory_model_runtime_and_config_bytes(self):
        codex = self.root / "codex.exe"
        codex.write_bytes(b"standalone synthetic executable bytes")
        config = self.root / "dependency.lock"
        config.write_bytes(b"dependency=v1\n")
        spec = copy.deepcopy(self.spec)
        spec["native"]["codex"] = str(codex)
        spec["native"]["config_bindings"] = {"dependency": str(config)}
        inventory = {
            "kind": "Stage2RuntimeInventoryReceipt",
            "schema_version": "1.0.0",
            "entries": {},
        }
        spec["preflight"] = {
            "report": {"bound": "report"},
            "capture_dir": str(self.root / "preflight-capture"),
            "receipt": "9" * 64,
            "probe_spec": {
                "kind": "Stage2RuntimeProbeSpec",
                "schema_version": "1.0.0",
            },
            "inventory_receipt": inventory,
        }
        verified = {
            "kind": "Stage2RuntimePreflight",
            "runtime_gate": True,
            "status": "passed",
            "formal_ready": False,
            "actual_runtime": {
                "model": "synthetic-model",
                "reasoning": "medium",
            },
            "requested_runtime": {
                "model": "synthetic-model",
                "reasoning": "medium",
            },
        }
        config_binding = {
            "path": str(config.resolve()),
            **_native_binding_bytes(config),
        }
        record = {
            "stable_request_binding": {
                "codex_runtime_sha256": hashlib.sha256(codex.read_bytes()).hexdigest(),
                "policy_bindings": spec["native"]["policy_bindings"],
                "config_bindings": {"dependency": config_binding},
            }
        }
        with (
            patch(
                "stage2_live.controller.verify_preflight", return_value=verified
            ) as preflight,
            patch("stage2_live.controller.verify_capture", return_value=(record, "")),
        ):
            _validate_spec(spec, self.packet, self.base, synthetic=False)
            self.assertIs(preflight.call_args.kwargs["inventory_receipt"], inventory)

            production_spec = copy.deepcopy(spec)
            production_spec["preflight"]["probe_spec"]["kind"] = (
                "Stage2ProductionRuntimeProbeSpec"
            )
            production_verified = copy.deepcopy(verified)
            production_verified.update(
                {
                    "kind": "Stage2ProductionRuntimePreflight",
                    "validation_scope": "production-single",
                    "filesystem_read_isolation": "not-assessed",
                    "quality_improvement": "not-established",
                }
            )
            preflight.return_value = production_verified
            _validate_spec(production_spec, self.packet, self.base, synthetic=False)

            preflight.return_value = verified
            with self.assertRaisesRegex(ValueError, "report/probe contract mismatch"):
                _validate_spec(production_spec, self.packet, self.base, synthetic=False)

            wrong_model = copy.deepcopy(verified)
            wrong_model["actual_runtime"]["model"] = "other-model"
            preflight.return_value = wrong_model
            with self.assertRaisesRegex(
                Stage2Error, "preflight-model-reasoning-mismatch"
            ):
                _validate_spec(spec, self.packet, self.base, synthetic=False)

            preflight.return_value = verified
            config.write_bytes(b"dependency=v2\n")
            with self.assertRaisesRegex(
                Stage2Error, "preflight-config-binding-mismatch"
            ):
                _validate_spec(spec, self.packet, self.base, synthetic=False)

    def test_changed_dependency_is_rejected_instead_of_rerun(self):
        adapter = SyntheticAdapter()
        self.run_controller(adapter, expected_head=self.initial["head_sha256"])
        changed = copy.deepcopy(self.spec)
        changed["native"]["reasoning"] = "high"
        with self.assertRaisesRegex(Stage2Error, "action-binding-changed"):
            self.run_controller(adapter, spec=changed)
        self.assertEqual(adapter.calls.count("research"), 1)

    def test_missing_reviewer_is_blocked_and_retained_without_duplicate_launch(self):
        adapter = SyntheticAdapter(fail_role="feasibility")
        result = self.run_controller(adapter, expected_head=self.initial["head_sha256"])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reconciliation"]["review_counts"]["failed"], 1)
        self.assertFalse(self.delivery.exists())
        calls = list(adapter.calls)
        resumed = self.run_controller(
            adapter, expected_head=result["workflow_head_sha256"]
        )
        self.assertEqual(resumed["status"], "blocked")
        self.assertEqual(adapter.calls, calls)

    def test_initial_review_workspaces_and_views_never_contain_peer_review(self):
        adapter = SyntheticAdapter()
        self.run_controller(adapter, expected_head=self.initial["head_sha256"])
        self.assertEqual(len(adapter.review_inputs), 2)
        challenger, feasibility = adapter.review_inputs
        self.assertEqual(challenger["view"]["role"], "challenger")
        self.assertEqual(feasibility["view"]["role"], "feasibility")
        self.assertNotEqual(challenger["paths"], feasibility["paths"])
        self.assertNotIn("reviews", challenger["view"])
        self.assertNotIn("reviews", feasibility["view"])

    def test_blocking_unknown_returns_bound_followup_without_delivery(self):
        result = self.run_controller(
            SyntheticAdapter(blocking=True),
            expected_head=self.initial["head_sha256"],
        )
        self.assertEqual(result["status"], "follow-up-needed")
        self.assertEqual(
            result["followups"],
            [
                {
                    "candidate_id": "candidate-1",
                    "candidate_version": 1,
                    "missing_evidence": [
                        "Acquire the missing prerequisite measurement."
                    ],
                    "decision_affected": "A source-bound semantic assessor recorded this bounded judgment.",
                    "scope_change_requested": False,
                }
            ],
        )
        self.assertFalse(self.delivery.exists())

    def test_v3_controller_returns_reconstructable_research_task(self):
        from test_stage2_research_followups import POLICY as research_policy
        from stage2_live.research_followups import validate_research_followup_task

        spec = copy.deepcopy(self.spec)
        spec["followup_policy"] = {
            "kind": "Stage2FollowupPolicy",
            "schema_version": "3.0.0",
            "investigate_material_partial": True,
            "research_task_policy": research_policy,
        }
        result = self.run_controller(
            SyntheticAdapter(blocking=True),
            expected_head=self.initial["head_sha256"],
            spec=spec,
        )
        self.assertEqual(result["status"], "follow-up-needed")
        snapshot = inspect_workflow(self.run)["latest_snapshot"]
        task = result["research_followup_task"]
        self.assertEqual(
            validate_research_followup_task(
                task,
                snapshot["packet"],
                snapshot["event"]["payload"]["snapshot_sha256"],
                research_policy,
                expected_followups=result["followups"],
            ),
            task,
        )
        self.assertFalse(result["formal_ready"])
        self.assertFalse(self.delivery.exists())

    def test_external_revision_forces_new_snapshot_and_cannot_carry_old_review(self):
        first = self.run_controller(
            SyntheticAdapter(), expected_head=self.initial["head_sha256"]
        )
        state = inspect_workflow(self.run, expected_head=first["workflow_head_sha256"])
        revised = copy.deepcopy(state["latest_snapshot"]["packet"])
        current = copy.deepcopy(revised["candidates"][-1])
        current.update(version=2, parent_version=1)
        current["opportunity"] = "A revised externally supplied opportunity."
        revised["candidates"].append(current)
        revised["packet_id"] = "external-revision"
        revision_path = self.root / "revision.json"
        revision_path.write_text(json.dumps(revised), encoding="utf-8")
        revision = apply_revision(
            self.run,
            revision_path,
            self.sources,
            {
                "candidate-1": {
                    "status": "affected",
                    "reason": "The external revision changes the current candidate.",
                }
            },
            "Externally acquired evidence produced a validated revision.",
            state["head_sha256"],
        )
        self.assertEqual(revision["affected_candidate_ids"], ["candidate-1"])
        self.assertFalse(revision["prior_reviews_carried_forward"])
        updated = inspect_workflow(
            self.run, expected_head=revision["workflow_head_sha256"]
        )
        old_review_snapshots = {
            row["request"]["snapshot_sha256"]
            for action_id, row in updated["actions"].items()
            if action_id.startswith("review-")
        }
        self.assertNotIn(revision["snapshot_sha256"], old_review_snapshots)
        self.assertEqual(updated["pending_candidate_ids"], ["candidate-1"])

    def test_output_collision_and_interrupted_unit_fail_closed(self):
        with self.assertRaisesRegex(Stage2Error, "input-output-collision"):
            _run_controller(
                self.run,
                self.run,
                self.delivery,
                self.initial["head_sha256"],
                self.spec,
                SyntheticAdapter(),
            )
        partial = self.root / "partial-delivery"
        partial.mkdir()
        (partial / "diagnostic.txt").write_text("retain me", encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "partial-needs-recovery"):
            _run_controller(
                self.run,
                self.controller,
                partial,
                self.initial["head_sha256"],
                self.spec,
                SyntheticAdapter(),
            )
        self.assertEqual(
            (partial / "diagnostic.txt").read_text(encoding="utf-8"), "retain me"
        )


if __name__ == "__main__":
    unittest.main()

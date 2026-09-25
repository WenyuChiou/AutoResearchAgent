"""No-answer-key formal lock, capture binding, and paired decision tests."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from stage1_ab import general, runner, sequence  # noqa: E402
from stage1_eval.common import EVAL_ROOT, EvaluationError, canonical, load_rubric, sha  # noqa: E402
from stage1_eval.adapter import adapt_subject, extraction_prompt  # noqa: E402
from stage1_eval.formal import (  # noqa: E402
    attach_workspace,
    bind_capture,
    verify_hub_receipts,
)
from stage1_eval.score import aggregate  # noqa: E402
from stage1_eval.judging import _schema_for_phase, make_packet, phase_prompt  # noqa: E402
from stage1_eval.model import _api_schema  # noqa: E402


def runs():
    return [
        {
            "repeat": repeat,
            "order": order,
            "baseline": {"run_id": f"a-{repeat}", "subject_id": f"anon-a-{repeat}"},
            "treatment": {"run_id": f"b-{repeat}", "subject_id": f"anon-b-{repeat}"},
        }
        for repeat, order in enumerate(
            (
                ["baseline", "treatment"],
                ["treatment", "baseline"],
                ["baseline", "treatment"],
            ),
            1,
        )
    ]


class GeneralABV3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_freeze_v3_has_no_answer_key_and_binds_task(self):
        codex = self.root / "codex.exe"
        codex.write_bytes(b"codex-runtime")
        task = self.root / "task.txt"
        task.write_bytes(b"Explore aging and consumption\n")
        spec = {
            "task_sha256": sha(task.read_bytes()),
            "rubric_sha256": "a" * 64,
            "topic_id": "topic-aging",
            "generation": {"prompt_sha256": "e" * 64},
        }
        spec_path = self.write("spec.json", spec)
        background = self.write(
            "background.json",
            {
                "kind": "Stage1BackgroundEvidence",
                "receipts": [
                    {
                        "command": [sys.executable, "-m", "research_hub", "search"],
                        "executable_sha256": sha(Path(sys.executable).read_bytes()),
                        "research_hub_package_sha256": "f" * 64,
                        "status": "results",
                    }
                ],
                "sources": [{"source_id": "src-verified"}],
            },
        )
        probe = self.write(
            "probe.json",
            {
                "model": "gpt-5.6-sol",
                "reasoning": "high",
                "codex_version": "codex-cli 0.153.3",
                "native_web_search": True,
                "native_capabilities": {"webSearch": True},
                "native_capabilities_sha256": sha(
                    json.dumps({"webSearch": True}, sort_keys=True).encode()
                ),
            },
        )
        pins = [self.write(f"pin-{index}.json", {}) for index in range(3)]
        output = self.root / "lock.json"
        with (
            patch.object(general, "check_spec"),
            patch.object(general, "_verify_background"),
            patch.object(general, "_evaluator_bundle_sha", return_value="b" * 64),
            patch.object(
                general,
                "verify_installed_from_commit",
                return_value={"python_source_sha256": "f" * 64},
            ),
            patch.object(
                runner,
                "_runtime_pin",
                side_effect=lambda path: ({}, sha(Path(path).read_bytes())),
            ),
            patch.object(runner, "tree_sha", return_value="c" * 64),
            patch.object(
                general.subprocess,
                "run",
                return_value=SimpleNamespace(stdout=runner.RESEARCH_HUB_SHA),
            ),
        ):
            unavailable = self.write(
                "unavailable-background.json",
                {"receipts": [{"status": "backend-failure"}], "sources": []},
            )
            with self.assertRaisesRegex(
                runner.ExecutionBlocked, "unavailable or ambiguous challenge search"
            ):
                general.freeze_v3(
                    codex,
                    task,
                    spec_path,
                    unavailable,
                    task,
                    probe,
                    self.root,
                    pins,
                    self.root / "unavailable-lock.json",
                )
            partly_ambiguous = self.write(
                "partly-ambiguous-background.json",
                {
                    "receipts": [
                        {"status": "results"},
                        {"status": "ambiguous-empty"},
                    ],
                    "sources": [{"source_id": "src-verified"}],
                },
            )
            with self.assertRaisesRegex(
                runner.ExecutionBlocked, "unavailable or ambiguous challenge search"
            ):
                general.freeze_v3(
                    codex,
                    task,
                    spec_path,
                    partly_ambiguous,
                    task,
                    probe,
                    self.root,
                    pins,
                    self.root / "partly-ambiguous-lock.json",
                )
            lock = general.freeze_v3(
                codex, task, spec_path, background, task, probe, self.root, pins, output
            )
        self.assertEqual(lock["kind"], "Stage1ABPublicLockV3")
        self.assertEqual(len(sequence.expected_runs(lock)), 6)
        self.assertNotIn("holdout_sha256", lock)
        self.assertNotIn("answer_key", lock)
        self.assertEqual(lock["spec_sha256"], sha(canonical(spec)))
        self.assertEqual(
            lock["evaluator_runtime"], {"model": "gpt-5.6-sol", "reasoning": "high"}
        )
        recovered = dict(spec, generation={"prompt_sha256": None, "recovery": "saved"})
        recovered_path = self.write("recovered-spec.json", recovered)
        with patch.object(general, "check_spec"):
            with self.assertRaisesRegex(runner.ExecutionBlocked, "non-recovered"):
                general.freeze_v3(
                    codex,
                    task,
                    recovered_path,
                    background,
                    task,
                    probe,
                    self.root,
                    pins,
                    self.root / "recovered-lock.json",
                )
        task.write_bytes(b"changed\n")
        with (
            patch.object(general, "check_spec"),
            patch.object(general, "_verify_background"),
        ):
            with self.assertRaisesRegex(runner.ExecutionBlocked, "differ"):
                general.freeze_v3(
                    codex,
                    task,
                    spec_path,
                    background,
                    task,
                    probe,
                    self.root,
                    pins,
                    self.root / "second-lock.json",
                )

    def test_formal_binding_rejects_selected_answer_and_attaches_process_only(self):
        codex = self.root / "codex.exe"
        codex.write_bytes(b"codex-runtime")
        task = self.root / "task.txt"
        task.write_bytes(b"prompt\n")
        background = self.root / "background.json"
        background.write_bytes(b"{}")
        spec = {
            "task_sha256": sha(task.read_bytes()),
            "rubric_sha256": "a" * 64,
            "topic_id": "topic-aging",
        }
        lock = {
            "kind": "Stage1ABPublicLockV3",
            "execution_class": "formal",
            "paired_repeats": runs(),
            "task_sha256": spec["task_sha256"],
            "spec_sha256": sha(canonical(spec)),
            "rubric_sha256": spec["rubric_sha256"],
            "topic_id": spec["topic_id"],
            "evaluator_bundle_sha256": "b" * 64,
            "evaluator_runtime": {"model": "gpt-5.6-sol", "reasoning": "high"},
            "background_sha256": sha(background.read_bytes()),
            "prompt_sha256": sha(task.read_bytes()),
            "runtime": {"app_version": "codex-cli 0.153.3"},
            "research_hub_sha": runner.RESEARCH_HUB_SHA,
            "background_receipts_sha256": sha(canonical([])),
            "research_hub_repo_path": str(self.root),
            "research_hub_package_sha256": "f" * 64,
            "hub_executable_sha256": sha(Path(sys.executable).read_bytes()),
            "hub_command_prefix": [sys.executable, "-m", "research_hub"],
            "codex_runtime_sha256": runner.codex_runtime_sha(codex),
        }
        lock_path = self.write("lock.json", lock)
        capture = self.root / "capture"
        snapshot = capture / "workspace" / "01"
        snapshot.mkdir(parents=True)
        (snapshot / "ledger.jsonl").write_text(
            '{"decision":"include"}\n', encoding="utf-8"
        )
        (snapshot / "review.md").write_text("Evidence review", encoding="utf-8")
        answer = capture / "attempt-01.final.txt"
        answer.write_text("literature answer", encoding="utf-8")
        transcript = capture / "attempt-01.jsonl"
        transcript.write_text('{"type":"turn.completed"}\n', encoding="utf-8")
        (capture / "run.json").write_text("{}", encoding="utf-8")
        record = {
            "status": "complete",
            "lock_kind": "Stage1ABPublicLockV3",
            "run_id": "a-1",
            "condition": "baseline",
            "repeat": 1,
            "series_id": "series-1",
            "lock_sha256": sha(lock_path.read_bytes()),
            "profile_probe": {"codex_version": "codex-cli 0.153.3"},
            "attempts": [
                {
                    "files": {
                        answer.name: sha(answer.read_bytes()),
                        transcript.name: sha(transcript.read_bytes()),
                    }
                }
            ],
        }
        args = SimpleNamespace(
            lock=str(lock_path),
            capture=str(capture),
            mode="evidence-audited",
            resume_pilot=False,
            saved_extraction=None,
            artifact=[],
            subject_status="complete",
            background=str(background),
            task=str(task),
            answer=str(answer),
            transcript=str(transcript),
            model="gpt-5.6-sol",
            reasoning="high",
            codex=str(codex),
            hub=None,
            hub_command_json=json.dumps(["@python", "-m", "research_hub"]),
        )
        with (
            patch.object(runner, "verify_capture", return_value=record),
            patch(
                "stage1_eval.formal.verify_installed_from_commit",
                return_value={"python_source_sha256": "f" * 64},
            ),
        ):
            binding = bind_capture(args, spec, "b" * 64)
            with self.assertRaisesRegex(EvaluationError, "unfrozen"):
                verify_hub_receipts(
                    [
                        {
                            "command": [sys.executable, "-m", "research_hub", "enrich"],
                            "executable_sha256": binding["hub_executable_sha256"],
                            "research_hub_package_sha256": "0" * 64,
                        }
                    ],
                    binding,
                )
            subject = attach_workspace({"evidence": {}}, binding)
            self.assertEqual(
                subject["evidence"]["workspace-1"]["origin"],
                "subject-captured-process-artifact",
            )
            delivered = attach_workspace(
                {"evidence": {"answer": {"text": "Read ledger.jsonl"}}}, binding
            )
            self.assertEqual(
                delivered["evidence"]["workspace-1"]["origin"],
                "subject-captured-process-artifact",
            )
            with_review = attach_workspace(
                {"evidence": {"answer": {"text": "See review.md"}}}, binding
            )
            self.assertEqual(
                with_review["evidence"]["workspace-2"]["origin"],
                "subject-delivered-artifact",
            )
            codex.write_bytes(b"changed-runtime")
            with self.assertRaisesRegex(EvaluationError, "differs"):
                bind_capture(args, spec, "b" * 64)
            codex.write_bytes(b"codex-runtime")
            args.hub_command_json = json.dumps(["@python", "-m", "wrong_hub"])
            with self.assertRaisesRegex(EvaluationError, "frozen research-hub command"):
                bind_capture(args, spec, "b" * 64)
            args.hub_command_json = json.dumps(["@python", "-m", "research_hub"])
            args.answer = str(self.root / "operator-selected.txt")
            with self.assertRaisesRegex(EvaluationError, "captured native files"):
                bind_capture(args, spec, "b" * 64)

    def test_paired_v3_improves_only_with_complete_three_pair_evidence(self):
        rubric, rubric_sha = load_rubric()
        background = self.write("background.json", {"sources": [], "receipts": []})
        lock = {
            "kind": "Stage1ABPublicLockV3",
            "execution_class": "formal",
            "plugin_tree_sha256": runner.tree_sha(runner.PLUGIN_ROOT),
            "paired_repeats": runs(),
            "rubric_sha256": rubric_sha,
            "spec_sha256": "b" * 64,
            "evaluator_bundle_sha256": "c" * 64,
            "evaluator_code_sha256": general._code_sha(),
            "evaluator_runtime": {"model": "gpt-5.6-sol", "reasoning": "high"},
            "codex_runtime_sha256": "d" * 64,
            "codex_executable_sha256": "e" * 64,
            "research_hub_sha": runner.RESEARCH_HUB_SHA,
            "research_hub_package_sha256": "f" * 64,
            "background_receipts_sha256": sha(canonical([])),
            "background_sha256": sha(background.read_bytes()),
        }
        lock_path = self.write("lock.json", lock)
        result_paths = []
        captures = []
        records = {}
        for row in sequence.expected_runs(lock):
            run_id = row["run_id"]
            condition = row["condition"]
            repeat = row["repeat"]
            capture = self.root / run_id
            capture.mkdir()
            (capture / "run.json").write_text("{}", encoding="utf-8")
            answer = capture / "attempt-01.final.txt"
            answer.write_bytes(run_id.encode())
            transcript = capture / "attempt-01.jsonl"
            transcript.write_bytes(b"{}\n")
            captures.append(capture)
            records[str(capture)] = {
                "status": "complete",
                "lock_kind": "Stage1ABPublicLockV3",
                "run_id": run_id,
                "condition": condition,
                "repeat": repeat,
                "series_id": "series-1",
                "attempts": [{}],
            }
            if condition == "treatment":
                records[str(capture)]["stage1_receipt"] = {"valid": True}
            better = condition == "treatment" and repeat < 3
            dimensions = {}
            for metric in ("P1", "P2", "P3"):
                criteria = [
                    row for row in rubric["criteria"] if row["dimension"] == metric
                ]
                scores = [1] * len(criteria)
                if better and metric == "P2":
                    scores[:2] = [2, 2]
                if better and metric == "P3":
                    scores[:2] = [2, 2]
                dimensions[metric] = {
                    "criteria": [
                        {"criterion_id": row["id"], "status": "scored", "score": score}
                        for row, score in zip(criteria, scores)
                    ],
                    "applicable_count": len(criteria),
                    "scored_count": len(criteria),
                    "unknown_count": 0,
                    "not_applicable_count": 0,
                    "observed_score_100": round(
                        100 * sum(scores) / (2 * len(scores)), 2
                    ),
                    "assessed_fraction": 1,
                    "lower_bound_100": round(100 * sum(scores) / (2 * len(scores)), 2),
                    "upper_bound_100": round(100 * sum(scores) / (2 * len(scores)), 2),
                    "confirmed_major_issue_ids": [],
                    "unresolved_major_issue_ids": [],
                }
            result = {
                "formal_capture": {
                    "run_id": run_id,
                    "condition": condition,
                    "repeat": repeat,
                    "series_id": "series-1",
                    "lock_sha256": sha(lock_path.read_bytes()),
                    "capture_run_sha256": sha((capture / "run.json").read_bytes()),
                    "answer_sha256": sha(answer.read_bytes()),
                    "transcript_sha256": sha(transcript.read_bytes()),
                },
                "rubric_sha256": lock["rubric_sha256"],
                "spec_sha256": lock["spec_sha256"],
                "evaluator_identity": {
                    "evaluator_bundle_sha256": lock["evaluator_bundle_sha256"],
                    "model": "gpt-5.6-sol",
                    "reasoning": "high",
                    "codex_runtime_sha256": "d" * 64,
                    "codex_executable_sha256": "e" * 64,
                    "evaluator_code_sha256": lock["evaluator_code_sha256"],
                    "research_hub_commit": runner.RESEARCH_HUB_SHA,
                    "research_hub_package_sha256": "f" * 64,
                },
                "evidence_mode": "evidence-audited",
                "subject_sha256": sha(answer.read_bytes()),
                "subject_status": "complete",
                "extraction_status": "complete",
                "evaluator_status": "complete",
                "scientific_readiness_status": "evidence-assessed",
                "major_issues": [],
                "dimensions": dimensions,
            }
            result_paths.append(self.write(f"{run_id}.json", result))
        with (
            patch.object(
                runner,
                "verify_capture",
                side_effect=lambda path, **_: records[str(path)],
            ),
            patch.object(general, "validate_schema"),
            patch.object(general, "_evaluator_bundle_sha", return_value="c" * 64),
            patch.object(general, "_verify_result_bundle"),
        ):
            decision = general.paired_v3(
                lock_path,
                background,
                list(reversed(result_paths)),
                list(reversed(captures)),
                self.root / "decision.json",
            )
            self.assertEqual(decision["decision"], "improved")
            self.assertEqual(decision["summary"]["P2"]["pair_deltas"], [25, 25, 0])
            original = result_paths[0].read_bytes()
            for field in (
                "codex_executable_sha256",
                "research_hub_package_sha256",
                "evaluator_code_sha256",
            ):
                tampered = json.loads(original)
                tampered["evaluator_identity"][field] = "0" * 64
                result_paths[0].write_text(json.dumps(tampered), encoding="utf-8")
                with self.assertRaisesRegex(runner.ExecutionBlocked, "not bound"):
                    general.paired_v3(
                        lock_path,
                        background,
                        result_paths,
                        captures,
                        self.root / f"tampered-{field}.json",
                    )
            result_paths[0].write_bytes(original)
            b1_record = records[str(captures[1])]
            saved_receipt = b1_record.pop("stage1_receipt")
            with self.assertRaisesRegex(runner.ExecutionBlocked, "not bound"):
                general.paired_v3(
                    lock_path,
                    background,
                    result_paths,
                    captures,
                    self.root / "no-receipt.json",
                )
            b1_record["stage1_receipt"] = saved_receipt
            saved_kind = b1_record.pop("lock_kind")
            with self.assertRaisesRegex(runner.ExecutionBlocked, "not bound"):
                general.paired_v3(
                    lock_path,
                    background,
                    result_paths,
                    captures,
                    self.root / "no-kind.json",
                )
            b1_record["lock_kind"] = saved_kind
            b1_original = result_paths[1].read_bytes()
            b1 = json.loads(b1_original)
            b1["major_issues"] = [
                {"issue_id": "issue-1", "dimension": "P1", "status": "confirmed"}
            ]
            b1["dimensions"]["P1"]["confirmed_major_issue_ids"] = ["issue-1"]
            b1["scientific_readiness_status"] = "fail-confirmed-major-issue"
            result_paths[1].write_text(json.dumps(b1), encoding="utf-8")
            major = general.paired_v3(
                lock_path, background, result_paths, captures, self.root / "major.json"
            )
            self.assertEqual(major["decision"], "not-improved")
            result_paths[1].write_bytes(b1_original)
            b1 = json.loads(b1_original)
            b1["dimensions"]["P1"]["criteria"][0]["score"] = 0
            for key in ("observed_score_100", "lower_bound_100", "upper_bound_100"):
                b1["dimensions"]["P1"][key] = 33.33
            result_paths[1].write_text(json.dumps(b1), encoding="utf-8")
            regression = general.paired_v3(
                lock_path,
                background,
                result_paths,
                captures,
                self.root / "regression.json",
            )
            self.assertEqual(regression["decision"], "not-improved")
            result_paths[1].write_bytes(b1_original)
            changed = json.loads(result_paths[3].read_text(encoding="utf-8"))
            p2 = changed["dimensions"]["P2"]
            p2["criteria"][0].update(status="unverifiable", score=None)
            p2.update(
                scored_count=3,
                unknown_count=1,
                assessed_fraction=0.75,
                lower_bound_100=37.5,
                upper_bound_100=62.5,
            )
            changed["scientific_readiness_status"] = "inconclusive"
            result_paths[3].write_text(json.dumps(changed), encoding="utf-8")
            unknown = general.paired_v3(
                lock_path,
                background,
                result_paths,
                captures,
                self.root / "unknown.json",
            )
            self.assertEqual(unknown["decision"], "inconclusive")
            changed["dimensions"]["P2"]["observed_score_100"] = 100
            result_paths[3].write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(runner.ExecutionBlocked, "score changed"):
                general.paired_v3(
                    lock_path,
                    background,
                    result_paths,
                    captures,
                    self.root / "tamper.json",
                )

    def test_formal_bundle_rebuild_rejects_edited_atomic_judgment(self):
        capture = self.root / "capture"
        capture.mkdir()
        (capture / "workspace" / "01").mkdir(parents=True)
        answer = capture / "attempt-01.final.txt"
        answer.write_text("Literature review", encoding="utf-8")
        trace = capture / "attempt-01.jsonl"
        trace.write_text('{"type":"turn.completed"}\n', encoding="utf-8")
        subject = adapt_subject(answer, trace, max_trace_bytes=2_000_000)
        attach_workspace(subject, {"snapshot_path": str(capture / "workspace" / "01")})
        root = self.root / "evaluator"
        spec = {"topic_id": "topic-aging", "draft": {"needs": [], "roles": []}}
        extraction = {
            "works": [],
            "central_claims": [],
            "extraction_complete": True,
            "unextracted_reason": None,
        }
        background = self.write(
            "background.json",
            {
                "kind": "Stage1BackgroundEvidence",
                "spec_sha256": sha(canonical(spec)),
                "sources": [],
                "receipts": [],
            },
        )
        source_result = {"receipts": [], "sources": []}
        packet = make_packet(
            "Explore aging",
            spec,
            subject,
            extraction,
            json.loads(background.read_text(encoding="utf-8")),
            source_result,
            mode="evidence-audited",
        )
        rubric, rubric_sha = load_rubric()
        all_rows = [
            {
                "criterion_id": row["id"],
                "status": "unverifiable",
                "score": None,
                "passages": [],
                "reason": "Evidence was unavailable.",
                "missing_evidence": ["No source evidence"],
            }
            for row in rubric["criteria"]
        ]

        def phase(rows):
            return {
                "criteria": rows,
                "major_issues": [],
                "core_assessments": [],
                "omission_assessments": [],
            }

        content = phase(all_rows[:7])
        process = phase(all_rows[7:])
        executable = self.root / "codex.exe"
        executable.write_bytes(b"test-runtime")
        lock = {
            "task_sha256": sha(b"Explore aging"),
            "spec_sha256": sha(canonical(spec)),
            "background_receipts_sha256": sha(canonical([])),
            "hub_command_prefix": [sys.executable, "-m", "research_hub"],
            "hub_executable_sha256": "a" * 64,
            "research_hub_package_sha256": "b" * 64,
            "evaluator_runtime": {"model": "test-model", "reasoning": "high"},
            "codex_executable_sha256": sha(executable.read_bytes()),
        }

        def save_model(log_dir, name, output, prompt, schema):
            log_dir.mkdir(parents=True, exist_ok=True)
            response = log_dir / f"{name}.json"
            response.write_text(json.dumps(output), encoding="utf-8")
            event = log_dir / f"{name}.jsonl"
            event.write_text(
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": json.dumps(output)},
                    }
                )
                + "\n"
                + json.dumps({"type": "turn.completed"})
                + "\n",
                encoding="utf-8",
            )
            stderr = log_dir / f"{name}.stderr.txt"
            stderr.write_bytes(b"")
            generation = log_dir / f"{name}.generation-schema.json"
            generation.write_text(
                json.dumps(
                    _api_schema(json.loads(schema.read_text(encoding="utf-8"))),
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            return {
                "output_sha256": sha(response.read_bytes()),
                "stdout_sha256": sha(event.read_bytes()),
                "stderr_sha256": sha(stderr.read_bytes()),
                "schema_sha256": sha(schema.read_bytes()),
                "generation_schema_sha256": sha(generation.read_bytes()),
                "prompt_sha256": sha(prompt.encode("utf-8")),
                "codex_executable_sha256": lock["codex_executable_sha256"],
                "model": "test-model",
                "reasoning": "high",
            }

        extraction_schema = EVAL_ROOT / "schemas/subject-extraction.v3.schema.json"
        extraction_meta = save_model(
            root / "model-logs",
            "subject-extraction",
            extraction,
            extraction_prompt(subject),
            extraction_schema,
        )
        self.write("evaluator/extraction-provenance.json", extraction_meta)
        provenance = {}
        for name, output in (
            ("content-r1", content),
            ("content-r2", content),
            ("process-r1", process),
            ("process-r2", process),
        ):
            phase_name = name.split("-")[0]
            schema = _schema_for_phase(root / "judging", phase_name)
            provenance[name] = save_model(
                root / "judging" / "model-logs",
                name,
                output,
                phase_prompt(packet, phase_name, rubric, rubric_sha),
                schema,
            )
        judgment = {
            "selected": {"content": content, "process": process},
            "provenance": provenance,
            "adjudicated_phases": [],
        }
        self.write("evaluator/subject-observation.json", subject)
        self.write("evaluator/subject-extraction.json", extraction)
        self.write("evaluator/subject-sources.json", source_result)
        self.write("evaluator/evidence-packet.json", packet)
        self.write("evaluator/judgments.json", judgment)
        result = aggregate(packet, judgment, evaluator_identity={"model": "test"})
        result_path = self.write("evaluator/result.json", result)
        with (
            patch.object(general, "_verify_source_receipts"),
            patch.object(general, "_verify_background"),
        ):
            general._verify_result_bundle(
                result_path,
                result,
                lock,
                json.loads(background.read_text()),
                background,
                capture,
                1,
            )
            edited = json.loads(result_path.read_text(encoding="utf-8"))
            edited["dimensions"]["P2"]["criteria"][0]["score"] = 2
            with self.assertRaisesRegex(runner.ExecutionBlocked, "saved judgments"):
                general._verify_result_bundle(
                    result_path,
                    edited,
                    lock,
                    json.loads(background.read_text()),
                    background,
                    capture,
                    1,
                )
            altered = dict(
                packet, extraction=dict(extraction, extraction_complete=False)
            )
            self.write("evaluator/evidence-packet.json", altered)
            forged = dict(result, packet_sha256=sha(canonical(altered)))
            with self.assertRaisesRegex(runner.ExecutionBlocked, "packet differs"):
                general._verify_result_bundle(
                    result_path,
                    forged,
                    lock,
                    json.loads(background.read_text()),
                    background,
                    capture,
                    1,
                )
            self.write("evaluator/evidence-packet.json", packet)
            altered = dict(
                packet, source_origins={"invented-source": ["evaluator-challenge"]}
            )
            self.write("evaluator/evidence-packet.json", altered)
            forged = dict(result, packet_sha256=sha(canonical(altered)))
            with self.assertRaisesRegex(runner.ExecutionBlocked, "packet differs"):
                general._verify_result_bundle(
                    result_path,
                    forged,
                    lock,
                    json.loads(background.read_text()),
                    background,
                    capture,
                    1,
                )
            self.write("evaluator/evidence-packet.json", packet)
            changed_extraction = dict(
                extraction,
                extraction_complete=False,
                unextracted_reason="Model did not finish.",
            )
            self.write("evaluator/subject-extraction.json", changed_extraction)
            altered = dict(packet, extraction=changed_extraction)
            self.write("evaluator/evidence-packet.json", altered)
            forged = dict(result, packet_sha256=sha(canonical(altered)))
            with self.assertRaisesRegex(runner.ExecutionBlocked, "extraction differs"):
                general._verify_result_bundle(
                    result_path,
                    forged,
                    lock,
                    json.loads(background.read_text()),
                    background,
                    capture,
                    1,
                )
            self.write("evaluator/subject-extraction.json", extraction)
            self.write("evaluator/evidence-packet.json", packet)
            judge_path = root / "judging" / "model-logs" / "content-r1.json"
            changed_judge = json.loads(judge_path.read_text(encoding="utf-8"))
            changed_judge["criteria"][0]["reason"] = "Forged score explanation"
            judge_path.write_text(json.dumps(changed_judge), encoding="utf-8")
            judgment["provenance"]["content-r1"]["output_sha256"] = sha(
                judge_path.read_bytes()
            )
            self.write("evaluator/judgments.json", judgment)
            with self.assertRaisesRegex(
                runner.ExecutionBlocked, "model output differs"
            ):
                general._verify_result_bundle(
                    result_path,
                    result,
                    lock,
                    json.loads(background.read_text()),
                    background,
                    capture,
                    1,
                )


if __name__ == "__main__":
    unittest.main()

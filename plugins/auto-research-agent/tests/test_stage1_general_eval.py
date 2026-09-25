"""Contract and metamorphic checks for the general evidence evaluator."""

import copy
import sys
import sys as python_sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))
# ruff: noqa: E402 -- load the repository CLI without installing it.
from stage1_eval.__main__ import _evaluator_bundle_sha, _verify_background, evaluate
from stage1_eval.adapter import adapt_subject, validate_extraction
from stage1_eval.collector import (
    _matches_subject_work,
    _run_hub,
    collect_subject_sources,
    rebuild_background_sources,
    rebuild_subject_sources,
)
from stage1_eval.common import (
    RUBRIC_PATH,
    EvaluationError,
    canonical,
    check_spec,
    sha,
    validate_schema,
)
from stage1_eval.judging import (
    CONTENT_IDS,
    PROCESS_IDS,
    _signature,
    _is_cited_candidate,
    judge_packet,
    make_packet,
    validate_judgment,
)
from stage1_eval.model import _api_schema, require_tool_free_events
from stage1_eval.runtime import executable_sha256, python_tree_sha256, require_expected
from stage1_eval.score import aggregate


def spec(question="How do aging households choose consumption categories?"):
    return {
        "kind": "TopicEvaluationSpec",
        "schema_version": "3.0.0",
        "topic_id": "topic-a",
        "task_sha256": "1" * 64,
        "rubric_id": "stage1-general-v3",
        "rubric_sha256": sha(RUBRIC_PATH.read_bytes()),
        "as_of": "2026-09-01",
        "frozen_at": "2026-08-30T10:00:00+00:00",
        "generation": {"model": "test"},
        "criterion_applicability": {
            "P2V3.BOUNDARIES": {
                "applicability": "applicable",
                "reason": "Limitations matter to this question.",
            }
        },
        "draft": {
            "question": question,
            "research_mode": "exploratory",
            "needs": [
                {
                    "need_id": "need-topic",
                    "question": "What directly addresses the topic?",
                    "why_needed": "It establishes relevant evidence.",
                    "critical": True,
                },
                {
                    "need_id": "need-method",
                    "question": "How are methods validated?",
                    "why_needed": "It distinguishes reliable methods.",
                    "critical": True,
                },
            ],
            "roles": [
                {
                    "role": "foundation",
                    "applicability": "applicable",
                    "reason": "Concept origin matters.",
                },
                {
                    "role": "closest-work",
                    "applicability": "applicable",
                    "reason": "Near work matters.",
                },
                {
                    "role": "boundary-or-challenge",
                    "applicability": "applicable",
                    "reason": "Limits matter.",
                },
                {
                    "role": "method-or-resource",
                    "applicability": "unresolved",
                    "reason": "Method is not chosen.",
                },
            ],
            "search_policy": {
                "recent_years": 4,
                "backend": "openalex",
                "max_results_per_query": 2,
                "challenge_queries": [
                    {
                        "query_id": "query-foundation",
                        "query": "aging consumption foundations",
                        "purpose": "foundation",
                        "need_ids": ["need-topic"],
                    },
                    {
                        "query_id": "query-closest",
                        "query": "aging household consumption agents",
                        "purpose": "closest",
                        "need_ids": ["need-method"],
                    },
                ],
            },
        },
    }


def packet(mode="packet-only", trace=False):
    text = "A recent agent method studies household consumption."
    subject = {
        "status": "complete",
        "evidence": {
            "answer": {
                "text": text,
                "sha256": sha(text.encode()),
                "origin": "subject-answer",
            }
        },
    }
    if trace:
        subject["evidence"]["trace-1"] = {
            "text": "native search query returned 2 results",
            "sha256": "2" * 64,
            "origin": "subject-native-trace",
        }
    extraction = {
        "works": [],
        "central_claims": [],
        "extraction_complete": True,
        "unextracted_reason": None,
    }
    sources = {"sources": [], "receipts": []}
    background = (
        {
            "sources": [],
            "receipts": [
                {"status": "results", "query_id": "query-foundation"},
                {"status": "zero-results", "query_id": "query-closest"},
            ],
        }
        if mode == "evidence-audited"
        else None
    )
    return make_packet(
        "Explore household behavior.",
        spec(),
        subject,
        extraction,
        background,
        sources,
        mode=mode,
    )


def judgment(phase, *, score=1, status="scored", passage=None):
    ids = sorted(CONTENT_IDS if phase == "content" else PROCESS_IDS)
    passage = passage or {
        "evidence_id": "answer",
        "exact_quote": "household consumption",
    }
    return {
        "criteria": [
            {
                "criterion_id": key,
                "status": status,
                "score": score if status == "scored" else None,
                "passages": [passage] if status == "scored" else [],
                "reason": "The observed material partly addresses the criterion.",
                "missing_evidence": ["source inaccessible"]
                if status == "unverifiable"
                else [],
            }
            for key in ids
        ],
        "core_assessments": [],
        "omission_assessments": [],
        "major_issues": [],
    }


class GeneralEvaluationTests(unittest.TestCase):
    def test_formal_v3_fails_closed_without_pre_subject_attestation(self):
        with self.assertRaisesRegex(
            EvaluationError, "formal v3 requires pre-subject lock"
        ):
            evaluate(SimpleNamespace(output="unused", execution_class="formal"))

    def test_enrich_hit_must_match_cited_identity(self):
        work = {
            "work_id": "work-01",
            "title": "Aging and household consumption",
            "identifier": "https://doi.org/10.1234/right",
        }
        self.assertFalse(
            _matches_subject_work(
                {"title": work["title"], "doi": "10.1234/wrong"}, work
            )
        )
        self.assertFalse(
            _matches_subject_work(
                {"title": "Different paper", "doi": "10.1234/right"}, work
            )
        )
        self.assertTrue(
            _matches_subject_work(
                {"title": work["title"], "doi": "10.1234/right"}, work
            )
        )
        with tempfile.TemporaryDirectory() as scratch:
            raw = Path(scratch)
            raw_bytes = canonical(
                [{"title": work["title"], "doi": "10.1234/wrong", "year": 2020}]
            )
            (raw / "work-01.stdout.json").write_bytes(raw_bytes)
            receipt = {
                "work_id": "work-01",
                "command": [
                    "hub",
                    "enrich",
                    work["identifier"],
                    "--backend",
                    "openalex",
                    "--json",
                ],
                "status": "results",
                "stdout_path": "work-01.stdout.json",
            }
            self.assertEqual(
                rebuild_subject_sources({"works": [work]}, spec(), [receipt], raw),
                [],
            )

    def test_crossref_title_search_preserves_strict_cited_identity(self):
        work = {
            "work_id": "work-01",
            "title": "Population aging and household consumption",
            "identifier": "https://doi.org/10.1234/right",
        }
        crossref_spec = spec()
        crossref_spec["draft"]["search_policy"]["backend"] = "crossref"
        args = [
            "search",
            work["title"],
            "--limit",
            "5",
            "--backend",
            "crossref",
            "--json",
        ]
        with tempfile.TemporaryDirectory() as scratch:
            raw = Path(scratch) / "raw"
            raw.mkdir()
            (raw / "work-01.stdout.json").write_bytes(
                canonical(
                    [
                        {"title": work["title"], "doi": "10.1234/wrong", "year": 2020},
                        {"title": work["title"], "doi": "10.1234/right", "year": 2020},
                    ]
                )
            )
            receipt = {
                "work_id": "work-01",
                "command": ["hub", *args],
                "status": "results",
                "stdout_path": "work-01.stdout.json",
            }
            sources = rebuild_subject_sources(
                {"works": [work]}, crossref_spec, [receipt], raw
            )
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0]["doi"], "10.1234/right")
            with patch(
                "stage1_eval.collector._run_hub", return_value=([], receipt)
            ) as run:
                with patch(
                    "stage1_eval.collector.rebuild_subject_sources", return_value=[]
                ):
                    collect_subject_sources(
                        {"works": [work]},
                        crossref_spec,
                        Path(scratch) / "capture",
                        ["hub"],
                    )
                self.assertEqual(run.call_args.args[0], args)

    def test_cited_work_cannot_be_counted_as_omission(self):
        value = packet(mode="evidence-audited")
        value["extraction"]["works"] = [
            {
                "work_id": "work-01",
                "title": "Aging and household consumption",
                "identifier": "10.1234/right",
            }
        ]
        self.assertTrue(
            _is_cited_candidate(
                {
                    "title": "Different title",
                    "doi": "10.1234/right",
                    "work_key": "doi:10.1234/right",
                },
                value,
            )
        )
        self.assertFalse(
            _is_cited_candidate(
                {
                    "title": "Other study",
                    "doi": "10.1234/other",
                    "work_key": "doi:10.1234/other",
                },
                value,
            )
        )
        self.assertFalse(
            _is_cited_candidate(
                {
                    "title": "Aging and household consumption",
                    "doi": "10.1234/other-version",
                    "work_key": "doi:10.1234/other-version",
                },
                value,
            )
        )

    def test_recent_window_binds_frontier_query_and_full_score(self):
        frozen = spec()
        frozen["draft"]["search_policy"]["challenge_queries"] = [
            {
                "query_id": "query-frontier",
                "query": "recent aging consumption evidence",
                "purpose": "frontier",
                "need_ids": ["need-topic"],
            }
        ]
        with tempfile.TemporaryDirectory() as scratch:
            raw = Path(scratch)
            (raw / "query-frontier.stdout.json").write_bytes(b"[]")
            receipt = {
                "query_id": "query-frontier",
                "purpose": "frontier",
                "need_ids": ["need-topic"],
                "command": [
                    "hub",
                    "search",
                    "recent aging consumption evidence",
                    "--limit",
                    "2",
                    "--backend",
                    "openalex",
                    "--year",
                    "2023-2026",
                    "--json",
                ],
                "status": "zero-results",
                "stdout_path": "query-frontier.stdout.json",
            }
            self.assertEqual(rebuild_background_sources(frozen, [receipt], raw), [])
            receipt["command"][-2] = "-2026"
            with self.assertRaisesRegex(EvaluationError, "frozen query"):
                rebuild_background_sources(frozen, [receipt], raw)
        value = judgment("content")
        next(
            row
            for row in value["criteria"]
            if row["criterion_id"] == "P2V3.CLOSEST_FRONTIER"
        )["score"] = 2
        with self.assertRaisesRegex(EvaluationError, "recent frontier search"):
            validate_judgment(value, packet(mode="evidence-audited"), "content")

    def test_v3_no_legacy_holdout_import(self):
        root = CLI / "stage1_eval"
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in root.glob("*.py")
            if path.name != "formal.py"
        )
        self.assertNotIn("stage1_ab", source)
        self.assertNotIn("from validators.holdout_manifest", source)
        self.assertNotIn(
            "from validators.holdout_manifest",
            (root / "formal.py").read_text(encoding="utf-8"),
        )

    def test_tool_free_judge_rejects_tool_event(self):
        raw = b'{"type":"item.completed","item":{"type":"command_execution"}}\n{"type":"turn.completed"}\n'
        with self.assertRaisesRegex(EvaluationError, "tool or error"):
            require_tool_free_events(raw)

    def test_runtime_bytes_bound(self):
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / "evaluator.exe"
            target.write_bytes(b"runtime version one")
            first = executable_sha256(target)
            target.write_bytes(b"runtime version two")
            self.assertNotEqual(first, executable_sha256(target))
            with self.assertRaisesRegex(EvaluationError, "frozen expected"):
                require_expected(executable_sha256(target), first, "Codex")

    def test_evaluator_bundle_hash_changes_with_rubric_bytes(self):
        with tempfile.TemporaryDirectory() as scratch:
            plugin = Path(scratch) / "plugin"
            cli = plugin / "cli/stage1_eval"
            evals = plugin / "evals"
            (evals / "schemas").mkdir(parents=True)
            (evals / "rubrics").mkdir()
            cli.mkdir(parents=True)
            (cli / "main.py").write_text("pass\n", encoding="utf-8")
            rubric = evals / "rubrics/stage1-general.v3.json"
            rubric.write_text('{"version":1}\n', encoding="utf-8")
            with (
                patch("stage1_eval.__main__.ROOT", cli),
                patch("stage1_eval.__main__.EVAL_ROOT", evals),
            ):
                first = _evaluator_bundle_sha()
                rubric.write_text('{"version":2}\n', encoding="utf-8")
                self.assertNotEqual(first, _evaluator_bundle_sha())

    def test_dependency_sha_bound(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            (root / "module.py").write_text("VERSION = 1", encoding="utf-8")
            first = python_tree_sha256(root)
            (root / "module.py").write_text("VERSION = 2", encoding="utf-8")
            self.assertNotEqual(first, python_tree_sha256(root))
            with self.assertRaisesRegex(EvaluationError, "frozen expected"):
                require_expected(python_tree_sha256(root), first, "research-hub")

    def test_rehash_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            raw = root / "raw"
            raw.mkdir()
            frozen = spec()
            receipts = []
            for query in frozen["draft"]["search_policy"]["challenge_queries"]:
                name = query["query_id"]
                (raw / f"{name}.stdout.json").write_bytes(b"[]")
                (raw / f"{name}.stderr.txt").write_bytes(b"")
                receipts.append(
                    {
                        "query_id": name,
                        "purpose": query["purpose"],
                        "need_ids": query["need_ids"],
                        "command": [
                            "hub",
                            "search",
                            query["query"],
                            "--limit",
                            "2",
                            "--backend",
                            "openalex",
                            "--year",
                            "-2026",
                            "--json",
                        ],
                        "status": "zero-results",
                        "stdout_path": f"{name}.stdout.json",
                        "stdout_sha256": sha(b"[]"),
                        "stderr_path": f"{name}.stderr.txt",
                        "stderr_sha256": sha(b""),
                    }
                )
            background = {
                "kind": "Stage1BackgroundEvidence",
                "spec_sha256": sha(canonical(frozen)),
                "sources": [],
                "receipts": receipts,
            }
            _verify_background(background, root / "background.json", frozen)
            background["sources"] = [{"source_id": "fabricated"}]
            with self.assertRaisesRegex(EvaluationError, "differ from raw"):
                _verify_background(background, root / "background.json", frozen)
            background["sources"] = []
            (raw / "query-foundation.stdout.json").write_bytes(b"[{}]")
            with self.assertRaisesRegex(EvaluationError, "changed"):
                _verify_background(background, root / "background.json", frozen)

    def test_resume_no_reexecution(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            logs = root / "model-logs"
            logs.mkdir()
            for phase in ("content", "process"):
                for role in ("r1", "r2"):
                    label = f"{phase}-{role}"
                    (logs / f"{label}.json").write_text(
                        __import__("json").dumps(judgment(phase)), encoding="utf-8"
                    )
                    (logs / f"{label}.jsonl").write_text(
                        '{"type":"turn.completed"}\n', encoding="utf-8"
                    )
            with patch(
                "stage1_eval.judging.call_model",
                side_effect=AssertionError("reexecuted"),
            ):
                result = judge_packet(packet(), root, {}, reuse_completed=True)
            self.assertEqual(result["adjudicated_phases"], [])

    def test_generation_schema_keeps_fields_named_like_schema_keywords(self):
        value = {
            "type": "object",
            "title": "metadata label",
            "properties": {"title": {"type": "string", "minLength": 1}},
            "required": ["title"],
        }
        result = _api_schema(value)
        self.assertNotIn("title", result)
        self.assertIn("title", result["properties"])
        self.assertEqual(result["required"], ["title"])

    def test_extraction_ids_are_normalized_but_quotes_are_not_repaired(self):
        subject = adapt_subject(self._answer_file("A result in Paper A."))
        value = {
            "works": [
                {
                    "work_id": "W1",
                    "exact_reference": "Paper A",
                    "title": "Paper A",
                    "identifier": "",
                    "nominated_core": True,
                }
            ],
            "central_claims": [
                {"claim_id": "C1", "exact_text": "A result", "cited_work_ids": ["W1"]}
            ],
            "extraction_complete": True,
            "unextracted_reason": None,
        }
        normalized = validate_extraction(value, subject)
        self.assertEqual(normalized["works"][0]["work_id"], "work-01")
        self.assertEqual(normalized["central_claims"][0]["cited_work_ids"], ["work-01"])
        value["central_claims"][0]["exact_text"] = "invented claim"
        with self.assertRaisesRegex(EvaluationError, "absent"):
            validate_extraction(value, subject)

    def _answer_file(self, text):
        # The temporary directory is cleaned by the test method's fixture.
        if not hasattr(self, "_scratch"):
            self._scratch = tempfile.TemporaryDirectory()
            self.addCleanup(self._scratch.cleanup)
        path = Path(self._scratch.name) / "answer.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def test_theory_topic_and_unspecified_method_do_not_require_population(self):
        value = spec("What is the theoretical convergence of a graph algorithm?")
        value["draft"]["research_mode"] = "theory"
        self.assertEqual(check_spec(value)["research_mode"], "theory")

    def test_gold_or_duplicate_search_path_rejected(self):
        value = spec()
        value["gold_set"] = []
        with self.assertRaisesRegex(EvaluationError, "answer-key"):
            check_spec(value)
        value = spec()
        value["draft"]["search_policy"]["challenge_queries"][1]["query"] = (
            "aging consumption foundations"
        )
        with self.assertRaisesRegex(EvaluationError, "distinct search paths"):
            check_spec(value)

    def test_v3_rubric_hash_bound(self):
        value = spec()
        value["rubric_sha256"] = "0" * 64
        with self.assertRaisesRegex(EvaluationError, "rubric binding"):
            check_spec(value)

    def test_content_packet_is_identical_when_only_native_trace_changes(self):
        without, with_trace = packet(trace=False), packet(trace=True)
        self.assertEqual(without["content_evidence"], with_trace["content_evidence"])
        self.assertNotEqual(without["process_evidence"], with_trace["process_evidence"])

    def test_fake_passage_and_unknown_as_partial_rejected(self):
        value = judgment("content")
        value["criteria"][0]["passages"][0]["exact_quote"] = "invented text"
        with self.assertRaisesRegex(EvaluationError, "invented exact passage"):
            validate_judgment(value, packet(), "content")
        value = judgment("content", status="unverifiable", score=1)
        value["criteria"][0]["score"] = 1
        with self.assertRaisesRegex(EvaluationError, "null score"):
            validate_judgment(value, packet(), "content")

    def test_packet_only_cannot_award_full_coverage(self):
        value = judgment("content", score=1)
        next(row for row in value["criteria"] if row["criterion_id"] == "P2V3.SCOPE")[
            "score"
        ] = 2
        with self.assertRaisesRegex(EvaluationError, "completed bounded challenge"):
            validate_judgment(value, packet(), "content")

    def test_honest_incompleteness_is_not_a_confirmed_major_error(self):
        value = judgment("content")
        value["major_issues"] = [
            {
                "issue_id": "missing-section",
                "violation_type": "materially-false-coverage-or-absence",
                "status": "confirmed",
                "dimension": "P2",
                "passages": [
                    {"evidence_id": "answer", "exact_quote": "household consumption"}
                ],
                "reason": "The answer omits a section but does not misrepresent completeness.",
            }
        ]
        with self.assertRaisesRegex(EvaluationError, "contrary source evidence"):
            validate_judgment(value, packet(), "content")

    def test_v3_omission_must_be_independent(self):
        value = packet(mode="evidence-audited")
        value["sources"]["src-own"] = {"source_id": "src-own", "work_key": "doi:own"}
        value["source_origins"]["src-own"] = ["evaluator-reference-check"]
        value["content_evidence"]["src-own"] = {
            "text": "A paper about the topic.",
            "origin": "evaluator-reference-check",
            "sha256": sha(b"A paper about the topic."),
        }
        judged = judgment("content")
        judged["omission_assessments"] = [
            {
                "source_id": "src-own",
                "need_id": "need-topic",
                "status": "material",
                "materiality_reason": "The review omitted an independently relevant work.",
                "substitute_rationale": "No direct substitute was listed.",
                "passages": [
                    {
                        "evidence_id": "src-own",
                        "exact_quote": "A paper about the topic.",
                    }
                ],
            }
        ]
        with self.assertRaisesRegex(EvaluationError, "independent challenge"):
            validate_judgment(judged, value, "content")

    def test_full_identity_needs_a_bound_reference_source(self):
        value = judgment("content", score=1)
        next(
            row for row in value["criteria"] if row["criterion_id"] == "P1V3.IDENTITY"
        )["score"] = 2
        with self.assertRaisesRegex(EvaluationError, "bound source"):
            validate_judgment(value, packet(), "content")

    def test_same_dimension_total_different_criterion_triggers_adjudication(self):
        first = judgment("process")
        second = copy.deepcopy(first)
        second["criteria"][0]["score"] = 0
        second["criteria"][1]["score"] = 2
        self.assertEqual(
            sum(r["score"] for r in first["criteria"]),
            sum(r["score"] for r in second["criteria"]),
        )
        self.assertNotEqual(_signature(first), _signature(second))
        # Passage wording alone does not trigger substantive disagreement.
        second = copy.deepcopy(first)
        second["criteria"][0]["passages"][0]["exact_quote"] = "recent agent method"
        self.assertEqual(_signature(first), _signature(second))

    def test_unknown_bounds_and_major_issue_are_separate(self):
        content = judgment("content")
        process = judgment("process", status="unverifiable")
        combined = {
            "selected": {"content": content, "process": process},
            "adjudicated_phases": [],
        }
        outcome = aggregate(
            packet(),
            combined,
            evaluator_identity={
                "model": "test",
                "reasoning": "low",
                "evaluator_code_sha256": "1" * 64,
            },
        )
        self.assertIsNone(outcome["dimensions"]["P3"]["observed_score_100"])
        self.assertEqual(outcome["dimensions"]["P3"]["lower_bound_100"], 0)
        self.assertEqual(outcome["dimensions"]["P3"]["upper_bound_100"], 100)
        self.assertEqual(outcome["scientific_readiness_status"], "inconclusive")
        content["major_issues"] = [
            {
                "issue_id": "fabricated-source",
                "status": "confirmed",
                "dimension": "P1",
                "passages": [],
                "reason": "A central source was fabricated.",
            }
        ]
        outcome = aggregate(
            packet(),
            combined,
            evaluator_identity={
                "model": "test",
                "reasoning": "low",
                "evaluator_code_sha256": "1" * 64,
            },
        )
        self.assertEqual(
            outcome["scientific_readiness_status"], "fail-confirmed-major-issue"
        )
        self.assertEqual(
            outcome["dimensions"]["P1"]["confirmed_major_issue_ids"],
            ["fabricated-source"],
        )
        validate_schema(outcome, "stage-evaluation-result.v3.schema.json")

    def test_corrupt_native_capture_is_evaluator_failure_not_subject_zero(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            (root / "answer.txt").write_text("A result.", encoding="utf-8")
            (root / "trace.jsonl").write_text("not json\n", encoding="utf-8")
            with self.assertRaisesRegex(EvaluationError, "corrupt"):
                adapt_subject(root / "answer.txt", root / "trace.jsonl")

    def test_backend_failure_is_distinct_from_ambiguous_empty(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            _, failed = _run_hub(
                [],
                root,
                "failed",
                [python_sys.executable, "-c", "raise SystemExit(42)"],
            )
            _, empty = _run_hub(
                [], root, "empty", [python_sys.executable, "-c", "print('[]')"]
            )
            self.assertEqual(failed["status"], "backend-failure")
            self.assertEqual(empty["status"], "ambiguous-empty")
            self.assertNotEqual(failed["stderr_sha256"], "")

    def test_swallowed_429_empty_response_does_not_claim_zero_results(self):
        with tempfile.TemporaryDirectory() as scratch:
            # The pinned hub backend can swallow an HTTP 429 and emit [] with
            # exit 0. The evaluator must keep that observation unresolved.
            completed = SimpleNamespace(returncode=0, stdout=b"[]\n", stderr=b"")
            with patch("stage1_eval.collector.subprocess.run", return_value=completed):
                rows, receipt = _run_hub(
                    ["search", "aging", "--backend", "crossref", "--json"],
                    Path(scratch),
                    "swallowed-429",
                    [python_sys.executable],
                )
            self.assertEqual(rows, [])
            self.assertEqual(receipt["status"], "ambiguous-empty")
            self.assertEqual(receipt["stdout_sha256"], sha(b"[]\n"))


if __name__ == "__main__":
    unittest.main()

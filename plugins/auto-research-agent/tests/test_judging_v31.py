"""v3.1 judge grounding, bounded views, and orchestration tests."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from stage1_eval.common import EvaluationError, sha  # noqa: E402
from stage1_eval.judge_views_v31 import (  # noqa: E402
    MAX_VIEW_CHARS,
    MAX_WORK_CHARS,
    bounded_judge_view,
    judge_span_index,
)
from stage1_eval.judging import CONTENT_IDS, PROCESS_IDS  # noqa: E402
from stage1_eval.judging_v31 import check_grounding, judge_packet_v31  # noqa: E402
from stage1_eval.spans import index_evidence, restore_passages  # noqa: E402


def _evidence(text, *, origin="subject-answer", work_id=None, level=None):
    row = {"text": text, "sha256": sha(text.encode()), "origin": origin}
    if work_id:
        row["subject_work_id"] = work_id
    if level:
        row["source_level"] = level
    return row


def _packet(evidence=None, works=None, claims=None):
    evidence = evidence or {"answer": _evidence("ordinary subject answer")}
    return {
        "task": "Assess a topic.",
        "spec": {"draft": {"needs": [], "roles": []}},
        "extraction": {
            "works": works or [],
            "central_claims": claims or [],
            "extraction_complete": True,
            "unextracted_reason": None,
        },
        "mode": "packet-only",
        "subject_status": "complete",
        "content_evidence": evidence,
        "process_evidence": evidence,
        "sources": {},
        "source_origins": {},
        "challenge_receipts": [],
        "subject_source_receipts": [],
    }


def _core(work_id, verdict="supported", evidence_id="source"):
    return {
        "work_id": work_id,
        "topic_core": verdict,
        "classic": "not-assessed",
        "closest": "candidate",
        "requirement_ids": [],
        "roles": [],
        "contribution": "Contribution described.",
        "decision_effect": "Decision described.",
        "omission_consequence": "Consequence described.",
        "substitute_rationale": "No substitute identified.",
        "passages": [{"evidence_id": evidence_id, "exact_quote": "quoted"}],
        "uncertainty": "None stated.",
    }


class GroundingTests(unittest.TestCase):
    def test_truncation_does_not_automatically_penalize_long_native_records(self):
        value = {
            "core_assessments": [],
            "criteria": [
                {
                    "criterion_id": "P3V3.SEARCH_TRACE",
                    "status": "scored",
                    "score": 2,
                }
            ],
        }
        with patch("stage1_eval.judging_v31.validate_judgment", return_value=value):
            checked = check_grounding(value, _packet(), "process", {"truncated": True})
        self.assertEqual(checked["criteria"][0]["score"], 2)

    def test_each_positive_core_label_needs_same_work_source_text(self):
        for field in ("topic_core", "closest", "classic"):
            packet = _packet()
            packet["sources"] = {
                "source": {
                    "subject_work_id": "work-1",
                    "source_level": "metadata",
                }
            }
            row = _core("work-1", verdict="candidate")
            row[field] = "supported"
            value = {"core_assessments": [row], "criteria": []}
            with (
                self.subTest(field=field),
                patch("stage1_eval.judging_v31.validate_judgment", return_value=value),
                self.assertRaisesRegex(
                    EvaluationError, "metadata does not substantiate"
                ),
            ):
                check_grounding(value, packet, "content")

    def test_claim_support_rejects_metadata_only(self):
        packet = _packet()
        packet["sources"] = {"meta": {"source_level": "metadata"}}
        value = {
            "core_assessments": [],
            "criteria": [
                {
                    "criterion_id": "P1V3.CLAIM_SUPPORT",
                    "status": "scored",
                    "passages": [{"evidence_id": "meta", "exact_quote": "title"}],
                }
            ],
        }
        with (
            patch("stage1_eval.judging_v31.validate_judgment", return_value=value),
            self.assertRaisesRegex(EvaluationError, "no source text"),
        ):
            check_grounding(value, packet, "content")

    def test_stale_version_and_wrong_file_span_are_rejected(self):
        evidence = {
            "a": _evidence("alpha source", work_id="work-a"),
            "b": _evidence("beta source", work_id="work-b"),
        }
        index = index_evidence(evidence)
        wrong = next(key for key, row in index.items() if row["evidence_id"] == "b")
        restored = restore_passages(
            {"criteria": [], "core_assessments": [{"passages": [{"span_id": wrong}]}]},
            index,
        )
        self.assertEqual(
            restored["core_assessments"][0]["passages"][0]["evidence_id"], "b"
        )
        packet = _packet()
        packet["sources"] = {
            "b": {"subject_work_id": "work-b", "source_level": "full-text"}
        }
        value = {"criteria": [], "core_assessments": [_core("work-a", evidence_id="b")]}
        with (
            patch("stage1_eval.judging_v31.validate_judgment", return_value=value),
            self.assertRaisesRegex(EvaluationError, "metadata does not substantiate"),
        ):
            check_grounding(value, packet, "content")
        changed = dict(evidence)
        changed["b"] = _evidence("beta source changed", work_id="work-b")
        with self.assertRaisesRegex(EvaluationError, "unknown span_id"):
            restore_passages(
                {
                    "criteria": [],
                    "core_assessments": [{"passages": [{"span_id": wrong}]}],
                },
                index_evidence(changed),
            )


class JudgeViewTests(unittest.TestCase):
    def test_many_native_events_keep_bound_excerpts_from_every_file(self):
        evidence = {
            f"event-{number}": _evidence(
                f"query {number}: " + "search details " * 100,
                origin="subject-native-trace",
            )
            for number in range(280)
        }
        index = judge_span_index(evidence, "process")
        view, manifest = bounded_judge_view(_packet(evidence), "process", index)
        self.assertEqual(manifest["selected_evidence_file_count"], 280)
        self.assertLessEqual(manifest["selected_text_chars"], MAX_VIEW_CHARS)
        self.assertTrue(manifest["truncated"])
        for row in view.values():
            self.assertEqual(
                row["text"],
                evidence[row["evidence_id"]]["text"][row["start"] : row["end"]],
            )
        # The complete index still covers each file, including its tail.
        for key, item in evidence.items():
            self.assertEqual(
                "".join(
                    row["text"] for row in index.values() if row["evidence_id"] == key
                ),
                item["text"],
            )

    def test_view_is_bounded_fair_and_records_truncation(self):
        evidence = {
            f"work-{number}": _evidence(
                (f"begin {number}\n" + "claim mechanism " * 1600 + f"\nend {number}"),
                origin="evaluator-reference-check",
                work_id=f"work-{number}",
            )
            for number in range(1, 7)
        }
        works = [
            {"work_id": f"work-{number}", "title": f"claim mechanism {number}"}
            for number in range(1, 7)
        ]
        packet = _packet(evidence, works)
        view, manifest = bounded_judge_view(packet, "content", index_evidence(evidence))
        self.assertLessEqual(
            sum(len(row["text"]) for row in view.values()), MAX_VIEW_CHARS
        )
        for work_id in {row["work_id"] for row in view.values()}:
            self.assertLessEqual(
                sum(
                    len(row["text"])
                    for row in view.values()
                    if row["work_id"] == work_id
                ),
                MAX_WORK_CHARS,
            )
        self.assertEqual(manifest["selected_evidence_file_count"], len(evidence))
        self.assertTrue(manifest["truncated"])
        self.assertGreater(manifest["omitted_span_count"], 0)

    def test_process_prefers_decoded_output_over_duplicate_native_json(self):
        raw = json.dumps({"item": {"aggregated_output": "decoded output"}})
        evidence = {"trace": _evidence(raw, origin="subject-native-trace")}
        view, manifest = bounded_judge_view(
            _packet(evidence), "process", index_evidence(evidence)
        )
        self.assertEqual(
            {row["view"] for row in view.values()}, {"item.aggregated_output"}
        )
        self.assertEqual(manifest["duplicate_native_json_spans_omitted"], 1)


class JudgeFlowTests(unittest.TestCase):
    def test_adjudication_prior_is_scoped_to_each_work_unit(self):
        works = [{"work_id": f"work-{i}", "title": f"Study {i}"} for i in range(5)]
        packet = _packet({"answer": _evidence("quoted")}, works)
        adj_units = []

        def fake_run_unit(prompt, schema, output, label, options, normalize, **kwargs):
            payload = json.loads(prompt[prompt.index('{"unit_kind"') :])
            data = payload["packet"]
            span_id = next(iter(data["spans"]))
            raw = {
                "criteria": [],
                "core_assessments": [],
                "omission_assessments": [],
                "major_issues": [],
            }
            if payload["unit_kind"] == "core":
                assigned = data["assigned_work_ids"]
                if "-adj-" in label:
                    adj_units.append(assigned)
                    for prior in data["prior_judgments"].values():
                        self.assertEqual(set(prior), {"core_assessments"})
                        self.assertEqual(
                            {row["work_id"] for row in prior["core_assessments"]},
                            set(assigned),
                        )
                else:
                    self.assertNotIn("prior_judgments", data)
                for work_id in assigned:
                    verdict = "unverifiable" if "-r2-" in label else "candidate"
                    row = _core(work_id, verdict)
                    row["passages"] = [{"span_id": span_id}]
                    raw["core_assessments"].append(row)
                # Extra, missing, or duplicate assessments must remain errors,
                # with the assigned IDs available to the bounded correction.
                for invalid in (
                    raw["core_assessments"] + [_core("foreign", "candidate")],
                    raw["core_assessments"][:-1],
                    raw["core_assessments"] + raw["core_assessments"][:1],
                ):
                    invalid = [
                        dict(row, passages=[{"span_id": span_id}]) for row in invalid
                    ]
                    with self.assertRaisesRegex(
                        EvaluationError, "expected=.*received="
                    ):
                        normalize(dict(raw, core_assessments=invalid))
            else:
                phase = "process" if label.startswith("process") else "content"
                ids = sorted(PROCESS_IDS if phase == "process" else CONTENT_IDS)
                raw["criteria"] = [
                    {
                        "criterion_id": criterion,
                        "status": "unverifiable",
                        "score": None,
                        "passages": [],
                        "reason": "Source remains unavailable.",
                        "missing_evidence": ["Source text"],
                    }
                    for criterion in ids
                ]
            return normalize(raw), {}

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("stage1_eval.judging_v31.run_unit", side_effect=fake_run_unit),
        ):
            result = judge_packet_v31(packet, directory, {})
        self.assertEqual(adj_units, [[f"work-{i}" for i in range(4)], ["work-4"]])
        self.assertEqual(len(result["selected"]["content"]["core_assessments"]), 5)
        self.assertEqual(result["adjudicated_phases"], ["content"])

    def test_independent_reviewers_adjudicate_only_disagreement_and_replay(self):
        packet = _packet()
        calls = []

        def fake_run_unit(
            prompt, schema, output, label, options, normalize, *, replay_only
        ):
            calls.append((label, replay_only))
            payload = json.loads(prompt[prompt.index('{"unit_kind"') :])
            phase = "process" if label.startswith("process") else "content"
            ids = sorted(PROCESS_IDS if phase == "process" else CONTENT_IDS)
            spans = payload["packet"]["spans"]
            span_id = next(iter(spans))
            rows = []
            for criterion_id in ids:
                disagrees = (
                    phase == "content"
                    and label == "content-r2-criteria"
                    and criterion_id == "P2V3.BOUNDARIES"
                )
                rows.append(
                    {
                        "criterion_id": criterion_id,
                        "status": "scored" if disagrees else "unverifiable",
                        "score": 1 if disagrees else None,
                        "passages": [{"span_id": span_id}] if disagrees else [],
                        "reason": "Sufficient bounded reason.",
                        "missing_evidence": [] if disagrees else ["Unavailable"],
                    }
                )
            raw = {
                "criteria": rows,
                "core_assessments": [],
                "omission_assessments": [],
                "major_issues": [],
            }
            return normalize(raw), {
                "execution_status": "reused" if replay_only else "executed"
            }

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("stage1_eval.judging_v31.run_unit", side_effect=fake_run_unit),
            patch(
                "stage1_eval.judging_v31.check_grounding",
                side_effect=lambda value, *_: value,
            ),
        ):
            judge_packet_v31(packet, directory, {}, replay_only=False)
            calls.clear()
            result = judge_packet_v31(packet, directory, {}, replay_only=True)
        labels = [label for label, _ in calls]
        self.assertEqual(labels.count("content-adj-criteria"), 1)
        self.assertNotIn("process-adj-criteria", labels)
        self.assertEqual(result["adjudicated_phases"], ["content"])
        self.assertTrue(all(replay for _, replay in calls))
        self.assertEqual(
            result["provenance"]["content-r1"]["content-r1-criteria"]["model"][
                "execution_status"
            ],
            "reused",
        )

    def test_completed_judge_units_replay_from_verified_archives(self):
        packet = _packet()

        def subprocess_result(command, **_kwargs):
            output_path = Path(command[command.index("-o") + 1])
            phase = "process" if "process-" in str(output_path) else "content"
            ids = sorted(PROCESS_IDS if phase == "process" else CONTENT_IDS)
            value = {
                "criteria": [
                    {
                        "criterion_id": criterion_id,
                        "status": "unverifiable",
                        "score": None,
                        "passages": [],
                        "reason": "Evidence remains unavailable.",
                        "missing_evidence": ["Unavailable"],
                    }
                    for criterion_id in ids
                ],
                "core_assessments": [],
                "omission_assessments": [],
                "major_issues": [],
            }
            output_path.write_text(json.dumps(value), encoding="utf-8")
            events = [
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": json.dumps(value)},
                },
                {"type": "turn.completed"},
            ]
            stdout = ("\n".join(json.dumps(row) for row in events) + "\n").encode()
            return SimpleNamespace(returncode=0, stdout=stdout, stderr=b"")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = root / "codex"
            codex.write_bytes(b"fake codex")
            home = root / "home"
            home.mkdir()
            options = {
                "codex": codex,
                "evaluator_home": home,
                "model": "test-model",
                "reasoning": "high",
                "execution_policy": {
                    "schema_version": "3.1.0",
                    "evaluator_bundle_sha256": "a" * 64,
                    "timeout_seconds": 600,
                    "max_transient_transport_retries": 1,
                },
            }
            with (
                patch(
                    "stage1_eval.model_calls.subprocess.run",
                    side_effect=subprocess_result,
                ) as execute,
                patch(
                    "stage1_eval.judging_v31.check_grounding",
                    side_effect=lambda value, *_: value,
                ),
            ):
                first = judge_packet_v31(packet, root / "judge", options)
            self.assertEqual(execute.call_count, 4)
            with (
                patch("stage1_eval.model_calls.subprocess.run") as execute,
                patch(
                    "stage1_eval.judging_v31.check_grounding",
                    side_effect=lambda value, *_: value,
                ),
            ):
                replay = judge_packet_v31(
                    packet, root / "judge", options, replay_only=True
                )
            execute.assert_not_called()
            self.assertEqual(replay["selected"], first["selected"])


if __name__ == "__main__":
    unittest.main()

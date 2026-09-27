import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))

from stage1_eval.common import EvaluationError, canonical, read_json, sha  # noqa: E402
from stage1_eval.source_audit_units import audit_sources, audit_targets  # noqa: E402


class SourceAuditUnitTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        codex = self.root / "codex"
        codex.write_bytes(b"synthetic executable")
        home = self.root / "home"
        home.mkdir()
        self.options = {
            "codex": codex,
            "evaluator_home": home,
            "model": "test-model",
            "reasoning": "high",
            "execution_policy": {
                "schema_version": "3.1.0",
                "evaluator_bundle_sha256": "b" * 64,
                "timeout_seconds": 600,
                "max_transient_transport_retries": 1,
            },
        }
        self.record = {
            "source_id": "source",
            "subject_work_id": "work",
            "source_level": "abstract",
            "version_id": "metadata-v1",
            "title": "Synthetic consumption study",
            "authors": ["Synthetic Author"],
            "year": 2025,
            "doi": "10.1000/example",
            "raw_sha256": "a" * 64,
            "date_status": "within-year-cutoff",
            "abstract": "A consumption effect was observed. " * 200
            + "\r\nNo consumption effect in the held-out group.",
        }
        self.packet = {
            "sources": {
                "source": {k: v for k, v in self.record.items() if k != "abstract"}
            },
            "source_origins": {"source": ["evaluator-reference-check"]},
            "content_evidence": {
                "source": {
                    "text": self.record["abstract"][:2000],
                    "origin": "evaluator-reference-check",
                    "sha256": sha(self.record["abstract"][:2000].encode()),
                }
            },
        }
        self.extraction = {
            "works": [
                {
                    "work_id": "work",
                    "title": self.record["title"],
                    "identifier": self.record["doi"],
                    "exact_reference": "Synthetic Author (2025), Synthetic consumption study.",
                }
            ],
            "central_claims": [
                {
                    "claim_id": "claim",
                    "exact_text": "All groups had a consumption effect.",
                    "cited_work_ids": ["work"],
                },
                {
                    "claim_id": "uncited",
                    "exact_text": "An uncited claim.",
                    "cited_work_ids": [],
                },
            ],
        }

    def invoke(self, **kwargs):
        return audit_sources(
            self.packet,
            [self.record],
            self.extraction,
            self.root / "audit",
            self.options,
            **kwargs,
        )

    @staticmethod
    def respond(command, **kwargs):
        prompt = kwargs["input"].decode()
        data = json.loads(prompt.split("\n", 1)[1])
        aliases = list(data["sources"])
        contrary = [
            key
            for key, row in data["sources"].items()
            if "No consumption effect" in row["text"]
        ]
        verdict = (
            "contradicted"
            if contrary and data["target"]["kind"] == "claim"
            else "supported"
        )
        value = {
            "verdict": verdict,
            "reason": "Synthetic test response only.",
            "addressed": aliases,
            "passages": contrary or aliases[:1],
        }
        Path(command[command.index("-o") + 1]).write_bytes(canonical(value))
        events = [
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": json.dumps(value)},
            },
            {"type": "turn.completed"},
        ]
        return SimpleNamespace(
            returncode=0,
            stdout=b"\n".join(canonical(row) for row in events) + b"\n",
            stderr=b"",
        )

    def test_all_targets_complete_native_units_tail_and_zero_call_replay(self):
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=self.respond
        ) as run:
            result = self.invoke()
        self.assertEqual(len(result["summaries"]), 7)
        self.assertGreater(run.call_count, 4)
        claim = next(
            row for row in result["summaries"] if row["target"]["id"] == "claim"
        )
        self.assertEqual(claim["verdict"], "unverifiable")
        self.assertEqual(claim["unknown_reason"], "conflicting-evidence")
        self.assertTrue(claim["contrary_leaf_ids"])
        self.assertEqual(claim["expected_unit_ids"], claim["completed_unit_ids"])
        proof = [
            p
            for row in result["leaves"]
            if row["unit_id"] in claim["contrary_leaf_ids"]
            for p in row["value"]["passages"]
        ]
        self.assertTrue(any("No consumption effect" in row["text"] for row in proof))
        self.assertTrue(
            all(
                row["source_version"] == "metadata-v1" and row["work_id"] == "work"
                for row in proof
            )
        )
        self.assertTrue(all(row["raw_source_sha256"] == "a" * 64 for row in proof))
        plan = read_json(self.root / "audit/plan.json")
        claim_plan = next(row for row in plan["plan"] if row["target"]["id"] == "claim")
        routed = [span for window in claim_plan["windows"] for span in window.values()]
        self.assertEqual(
            "".join(
                row["text"] for row in sorted(routed, key=lambda row: row["start"])
            ),
            self.record["abstract"],
        )
        self.assertEqual(
            len({(row["start"], row["end"]) for row in routed}), len(routed)
        )
        self.assertFalse(result["score_awarded"])
        with mock.patch("stage1_eval.model_calls.subprocess.run") as replay:
            self.assertEqual(self.invoke(replay_only=True), result)
        replay.assert_not_called()

    def test_missing_originals_and_uncited_claim_stay_unknown(self):
        targets = audit_targets(self.extraction)
        self.assertEqual(len(targets), 7)
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=self.respond
        ):
            result = self.invoke()
        missing = {
            row["target"]["id"]: row
            for row in result["summaries"]
            if row["unknown_reason"] == "missing-original-field"
        }
        self.assertEqual(set(missing), {"work:authors", "work:year", "work:version"})
        uncited = next(
            row for row in result["summaries"] if row["target"]["id"] == "uncited"
        )
        self.assertEqual(uncited["unknown_reason"], "unlinked-claim")
        self.assertEqual(uncited["completed_unit_ids"], [])

    def test_metadata_cannot_support_findings(self):
        self.record["source_level"] = "metadata"
        self.packet["sources"]["source"]["source_level"] = "metadata"
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=self.respond
        ):
            result = self.invoke()
        claim = next(
            row for row in result["summaries"] if row["target"]["id"] == "claim"
        )
        self.assertEqual(
            (claim["verdict"], claim["unknown_reason"]),
            ("unverifiable", "metadata-only"),
        )

    def test_timeout_keeps_error_pending_and_blocks_blind_resume(self):
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                "codex", 600, output=b"partial", stderr=b"timeout"
            ),
        ) as run:
            with self.assertRaises(EvaluationError):
                self.invoke()
        self.assertEqual(run.call_count, 1)
        error_path = next((self.root / "audit").glob("*.coverage-error.json"))
        before = error_path.read_bytes()
        error = read_json(error_path)
        self.assertEqual(len(error["error_unit_ids"]), 1)
        self.assertTrue(error["pending_unit_ids"])
        self.assertFalse((self.root / "audit/result.json").exists())
        with mock.patch("stage1_eval.model_calls.subprocess.run") as replay:
            with self.assertRaises(EvaluationError):
                self.invoke()
        replay.assert_not_called()
        self.assertEqual(error_path.read_bytes(), before)

    def test_rehashed_summary_tamper_rejected_without_calls(self):
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=self.respond
        ):
            self.invoke()
        path = self.root / "audit/result.json"
        result = read_json(path)
        result["summaries"][-1]["verdict"] = "supported"
        path.write_bytes(canonical(result))
        with mock.patch("stage1_eval.model_calls.subprocess.run") as replay:
            with self.assertRaisesRegex(EvaluationError, "saved binding changed"):
                self.invoke(replay_only=True)
        replay.assert_not_called()

    def test_source_dictionary_order_does_not_change_replay_windows(self):
        other = {**self.record, "source_id": "z-source"}
        packet = {
            **self.packet,
            "sources": {
                "z-source": {k: v for k, v in other.items() if k != "abstract"},
                **self.packet["sources"],
            },
            "content_evidence": {
                "z-source": self.packet["content_evidence"]["source"],
                **self.packet["content_evidence"],
            },
            "source_origins": {
                "z-source": ["evaluator-reference-check"],
                **self.packet["source_origins"],
            },
        }
        args = (
            packet,
            [other, self.record],
            self.extraction,
            self.root / "order",
            self.options,
        )
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=self.respond
        ):
            result = audit_sources(*args)
        reordered = json.loads(canonical(packet))
        with mock.patch("stage1_eval.model_calls.subprocess.run") as replay:
            self.assertEqual(
                audit_sources(reordered, *args[1:], replay_only=True), result
            )
        replay.assert_not_called()

    def test_oversize_original_is_not_truncated_or_sent(self):
        self.extraction["works"][0]["exact_reference"] = "测" * 4000
        with mock.patch("stage1_eval.model_calls.subprocess.run") as run:
            with self.assertRaisesRegex(EvaluationError, "exceeds byte limit"):
                self.invoke()
        run.assert_not_called()
        self.assertFalse((self.root / "audit/result.json").exists())


if __name__ == "__main__":
    unittest.main()

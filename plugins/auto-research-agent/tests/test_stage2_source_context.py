# ruff: noqa: E402 -- load repository CLI and fixture helpers without installation.
"""Source context is explicit, byte-bound, bounded, and opt-in."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parent),
]

from stage1_eval.common import EvaluationError
from stage2_common import Stage2Error, canonical_hash
from stage2_eval.source_context import build_source_context
from stage2_live.daily_v3 import run_daily_evaluation_v3
from stage2_fixture_helpers import write_stage2_fixture


class SourceContextTests(unittest.TestCase):
    def test_malformed_identifiers_and_enums_fail_with_contextual_error(self):
        for key in ("evidence_id", "source_id", "semantic_role", "claim_type"):
            with self.subTest(key=key), self.assertRaises(Stage2Error):
                build_source_context(
                    self.packet, self.sources, self.policy(**{key: []})
                )

    def test_aggregate_context_bound_includes_duplicate_quote_and_metadata(self):
        self.replace_source("# Synthetic study\n\n" + "a" * 6000, "a" * 2000)
        policy = self.policy()
        policy["max_characters_per_context"] = 8000
        with self.assertRaisesRegex(Stage2Error, "aggregate context"):
            build_source_context(self.packet, self.sources, policy)

    def test_semantic_hints_do_not_attest_source_truth(self):
        from stage2_eval.source_context import source_context_prompt_suffix

        record = build_source_context(self.packet, self.sources, self.policy())
        self.assertEqual(
            record["contexts"][0]["declaration_status"],
            "unverified-source-context-hints",
        )
        self.assertIn("not established facts", source_context_prompt_suffix(record))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.sources = self.root / "sources"
        self.packet = write_stage2_fixture(self.sources, candidate_count=1)
        self.entry = {
            "evidence_id": "ev-1",
            "source_id": "src-1",
            "work_id": "work-1",
            "version_id": "v1",
            "source_sha256": self.packet["sources"][0]["sha256"],
            "quote_start": 0,
            "semantic_role": "current-study",
            "claim_type": "finding",
            "checked_scope": None,
            "policy_exceptions": [],
        }

    def policy(self, **entry_changes):
        entry = {**self.entry, **entry_changes}
        return {
            "kind": "Stage2SourceContextPolicy",
            "schema_version": "1.0.0",
            "max_adjacent_paragraphs": 1,
            "max_characters_per_context": 2000,
            "entries": [entry],
        }

    def replace_source(self, text, quote):
        raw = text.encode("utf-8")
        (self.sources / "source-1.txt").write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        self.packet["sources"][0]["sha256"] = digest
        self.packet["evidence"][0]["quote"] = quote
        self.entry["source_sha256"] = digest
        self.entry["quote_start"] = text.index(quote)

    def daily(self, name, source_context_policy=None, resume=False):
        selection = {"evaluation_packet": self.packet, "action_record": {}}
        homes = {role: self.root / role.lower() for role in ("R1", "R2", "ADJ")}
        with (
            patch("stage2_live.daily_v3.validate_action_record"),
            patch("stage2_live.daily_v3.codex_runtime_sha", return_value="a" * 64),
            patch("stage2_live.daily_v3._unique_homes", return_value=homes),
            patch("stage2_live.daily_v3._resume_receipts", return_value={}),
            patch(
                "stage2_live.daily_v3._run_unit", side_effect=Stage2Error("stop")
            ) as unit,
        ):
            result = run_daily_evaluation_v3(
                selection,
                self.sources,
                codex="codex",
                r1_home="r1",
                r2_home="r2",
                adj_home="adj",
                model="m",
                reasoning="high",
                execution_policy={},
                output_dir=self.root / name,
                call_adapter=lambda: None,
                source_context_policy=source_context_policy,
                resume=resume,
            )
        request = json.loads((self.root / name / "request.json").read_bytes())
        return result, request, unit.call_args.kwargs["prompt"]

    def test_crlf_exact_span_and_adjacent_table_are_preserved(self):
        text = (
            "# Results\r\n\r\nPrior work used Java and Android.\r\n\r\n"
            "The current Python study reports the contingency table.\r\n"
            "| outcome | yes | no |\r\n| kept | 75 | 38 |\r\n"
            "| dropped | 13 | 11 |\r\n\r\n# Limits\r\n\r\nNo population claim.\r\n"
        )
        quote = "The current Python study reports the contingency table."
        self.replace_source(text, quote)
        record = build_source_context(self.packet, self.sources, self.policy())
        row = record["contexts"][0]
        self.assertEqual(
            row["exact_excerpt"],
            {
                "start": text.index(quote),
                "end": text.index(quote) + len(quote),
                "text": quote,
            },
        )
        self.assertIn(
            "| kept | 75 | 38 |\r\n| dropped | 13 | 11 |", row["context"]["text"]
        )
        self.assertEqual(row["context"]["section_labels"], ["Results"])
        self.assertEqual(row["semantic_role"], "current-study")

    def test_foreign_identity_version_hash_and_tamper_fail_closed(self):
        for field, value, message in (
            ("source_id", "src-2", "source identity"),
            ("work_id", "other-work", "work/version"),
            ("version_id", "v2", "work/version"),
            ("source_sha256", "0" * 64, "source hash"),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(Stage2Error, message):
                    build_source_context(
                        self.packet, self.sources, self.policy(**{field: value})
                    )
        (self.sources / "source-1.txt").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "source hash mismatch"):
            build_source_context(self.packet, self.sources, self.policy())

    def test_absence_requires_declared_checked_scope(self):
        with self.assertRaisesRegex(Stage2Error, "absence.*checked scope"):
            build_source_context(
                self.packet, self.sources, self.policy(claim_type="absence")
            )
        scope = {
            "description": "The complete synthetic source",
            "start": 0,
            "end": len((self.sources / "source-1.txt").read_text()),
        }
        record = build_source_context(
            self.packet,
            self.sources,
            self.policy(claim_type="absence", checked_scope=scope),
        )
        self.assertEqual(record["contexts"][0]["checked_scope"], scope)

    def test_title_only_abstract_and_policy_exception_are_explicit(self):
        self.packet["sources"][0]["evidence_level"] = "abstract"
        record = build_source_context(
            self.packet,
            self.sources,
            self.policy(
                semantic_role="cited-work",
                claim_type="title-only",
                policy_exceptions=[
                    "Aggregate derived summaries are allowed; person-level AI use is prohibited."
                ],
            ),
        )
        row = record["contexts"][0]
        self.assertEqual(
            (row["semantic_role"], row["claim_type"], row["evidence_level"]),
            ("cited-work", "title-only", "abstract"),
        )
        self.assertIn("Aggregate derived summaries", row["policy_exceptions"][0])

    def test_legacy_daily_prompt_and_result_have_no_context_fields(self):
        result, request, prompt = self.daily("legacy")
        self.assertNotIn("source_context", result)
        self.assertNotIn("source_context_policy_sha256", request)
        self.assertNotIn("source_context", prompt)

    def test_opt_in_binds_request_output_and_resume_to_context_policy(self):
        _, legacy_request, _ = self.daily("control")
        result, request, prompt = self.daily("run", self.policy())
        self.assertEqual(result["source_context"]["contexts"][0]["source_id"], "src-1")
        self.assertEqual(
            request["source_context_sha256"], canonical_hash(result["source_context"])
        )
        self.assertIn("source_context", prompt)
        self.assertNotEqual(request["code_sha256"], legacy_request["code_sha256"])
        changed = copy.deepcopy(self.policy())
        changed["entries"][0]["semantic_role"] = "cited-work"
        with self.assertRaisesRegex(EvaluationError, "unchanged science and settings"):
            self.daily("run", changed, resume=True)


if __name__ == "__main__":
    unittest.main()

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jsonschema import Draft202012Validator

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))

from stage1_eval.common import EvaluationError, canonical, sha  # noqa: E402
from stage1_eval.extraction_v31 import (  # noqa: E402
    CLAIM_SCHEMA,
    WORK_SCHEMA,
    _aggregate_works,
    _normalize_works,
    extract_subject_v31,
)
from stage1_eval.spans import CHUNK_CHARS, extraction_chunks  # noqa: E402


def evidence(text, *, version="v1", origin="subject-answer"):
    return {
        "text": text,
        "sha256": sha(text.encode()),
        "origin": origin,
        "source_version": version,
        "locator": "synthetic",
    }


def subject(text, **kwargs):
    return {"evidence": {"answer": evidence(text, **kwargs)}}


def complete_works(rows=()):
    return {
        "works": list(rows),
        "mentions": [],
        "extraction_complete": True,
        "unextracted_reason": None,
    }


def complete_claims(rows=()):
    return {
        "central_claims": list(rows),
        "extraction_complete": True,
        "unextracted_reason": None,
    }


class ExtractionV31Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_with(self, value, responder, *, replay_only=False):
        calls = []

        def fake(prompt, schema, output, label, options, normalize, **kwargs):
            calls.append((prompt, schema, label, options, kwargs))
            return normalize(responder(label, prompt)), {"unit": label}

        with mock.patch("stage1_eval.extraction_v31._run_unit", side_effect=fake):
            result, provenance = extract_subject_v31(
                value,
                self.output,
                {"model": "mock"},
                replay_only=replay_only,
            )
        return result, provenance, calls

    def test_every_chunk_has_separate_work_and_claim_pass_and_tail_coverage(self):
        text = "A" * 12_300 + " FINAL TAIL CLAIM"
        value = subject(text)
        index, chunks = extraction_chunks(value)
        self.assertGreater(len(chunks), 1)

        result, provenance, calls = self.run_with(
            value,
            lambda label, _prompt: (
                complete_works() if "works" in label else complete_claims()
            ),
            replay_only=True,
        )
        labels = [row[2] for row in calls]
        count = len(chunks)
        self.assertEqual(
            labels,
            [f"subject-works-{number:03d}" for number in range(1, count + 1)]
            + [f"subject-claims-{number:03d}" for number in range(1, count + 1)],
        )
        self.assertIn("FINAL TAIL CLAIM", calls[count - 1][0])
        self.assertTrue(all(row[4]["replay_only"] for row in calls))
        self.assertEqual(
            {span for row in provenance["chunks"] for span in row["primary_span_ids"]},
            set(index),
        )
        self.assertTrue(result["extraction_complete"])

    def test_overlap_context_stays_inside_visible_text_limit(self):
        value = subject("0123456789" * 5_000)
        index, _chunks = extraction_chunks(value)
        _result, provenance, _calls = self.run_with(
            value,
            lambda label, _prompt: (
                complete_works() if "works" in label else complete_claims()
            ),
        )
        self.assertGreater(provenance["chunk_count"], 2)
        visible_sizes = [
            sum(len(index[span_id]["text"]) for span_id in row["visible_span_ids"])
            for row in provenance["chunks"]
        ]
        self.assertTrue(all(size <= CHUNK_CHARS for size in visible_sizes))
        self.assertTrue(any(row["context_span_ids"] for row in provenance["chunks"]))

    def test_boundary_overlap_restores_one_same_file_reference(self):
        title = "BOUNDARY TITLE"
        text = "A" * 10_195 + title + " citation remainder" + " Z" * 1_500
        value = subject(text)
        index, chunks = extraction_chunks(value, max_characters=CHUNK_CHARS - 1_800)
        self.assertEqual(len(chunks), 2)
        crossing = [list(chunks[0])[-1], list(chunks[1])[0]]
        work = {
            "span_ids": crossing,
            "title": title,
            "identifier": "",
            "nominated_core": True,
        }

        def responder(label, _prompt):
            if label == "subject-works-001":
                return complete_works([work])
            return complete_works() if "works" in label else complete_claims()

        result, provenance, _calls = self.run_with(value, responder)
        self.assertEqual(len(result["works"]), 1)
        self.assertIn(title, result["works"][0]["exact_reference"])
        self.assertIn(crossing[1], provenance["chunks"][0]["context_span_ids"])
        self.assertEqual(
            provenance["work_source_map"][result["works"][0]["work_id"]][0]["span_ids"],
            crossing,
        )

    def test_cross_file_selection_is_rejected(self):
        value = {
            "evidence": {
                "answer": evidence("First Visible Title"),
                "artifact": evidence(
                    "Second Visible Title", origin="subject-delivered-artifact"
                ),
            }
        }
        index, _chunks = extraction_chunks(value)
        ids = list(index)

        def responder(label, _prompt):
            if "works" in label:
                return complete_works(
                    [
                        {
                            "span_ids": ids,
                            "title": "First Visible Title",
                            "identifier": "",
                            "nominated_core": False,
                        }
                    ]
                )
            return complete_claims()

        with self.assertRaisesRegex(EvaluationError, "crosses evidence files"):
            self.run_with(value, responder)

    def test_unknown_span_and_changed_version_fail_closed(self):
        original = subject("Visible Title", version="v1")
        old_id = next(iter(extraction_chunks(original)[0]))
        changed = subject("Visible Title", version="v2")

        def responder(label, _prompt):
            if "works" in label:
                return complete_works(
                    [
                        {
                            "span_ids": [old_id],
                            "title": "Visible Title",
                            "identifier": "",
                            "nominated_core": False,
                        }
                    ]
                )
            return complete_claims()

        with self.assertRaisesRegex(EvaluationError, "outside its chunk"):
            self.run_with(changed, responder)

    def test_invented_work_reference_is_rejected(self):
        value = subject("A central claim with no citation.")
        span_id = next(iter(extraction_chunks(value)[0]))

        def responder(label, _prompt):
            if "works" in label:
                return complete_works()
            return complete_claims(
                [
                    {
                        "span_ids": [span_id],
                        "cited_work_ids": ["work-0000000000000000"],
                    }
                ]
            )

        with self.assertRaisesRegex(EvaluationError, "unknown cited work ID"):
            self.run_with(value, responder)

    def test_exact_duplicates_merge_but_ambiguous_identity_remains(self):
        text = "Visible Study DOI-A and alternate DOI-B"
        value = subject(text)
        span_id = next(iter(extraction_chunks(value)[0]))
        rows = [
            {
                "span_ids": [span_id],
                "title": "Visible Study",
                "identifier": "DOI-A",
                "nominated_core": False,
            },
            {
                "span_ids": [span_id],
                "title": "Visible Study",
                "identifier": "DOI-A",
                "nominated_core": True,
            },
            {
                "span_ids": [span_id],
                "title": "Visible Study",
                "identifier": "DOI-B",
                "nominated_core": False,
            },
        ]
        work_a = (
            "work-"
            + sha(canonical({"identifier": "DOI-A", "title": "Visible Study"}))[:16]
        )

        def responder(label, _prompt):
            if "works" in label:
                return complete_works(rows)
            return complete_claims(
                [
                    {"span_ids": [span_id], "cited_work_ids": [work_a]},
                    {"span_ids": [span_id], "cited_work_ids": [work_a]},
                ]
            )

        result, provenance, _calls = self.run_with(value, responder)
        self.assertEqual(len(result["works"]), 2)
        self.assertEqual(len(result["central_claims"]), 1)
        by_identifier = {row["identifier"]: row for row in result["works"]}
        self.assertTrue(by_identifier["DOI-A"]["nominated_core"])
        self.assertEqual(len(provenance["work_source_map"][work_a]), 2)

    def test_incomplete_reasons_are_preserved(self):
        value = subject("Unclear bibliography and an uncertain claim")

        def responder(label, _prompt):
            if "works" in label:
                return {
                    "works": [],
                    "mentions": [],
                    "extraction_complete": False,
                    "unextracted_reason": "bibliography truncated",
                }
            return {
                "central_claims": [],
                "extraction_complete": False,
                "unextracted_reason": "claim meaning unknown",
            }

        result, _provenance, _calls = self.run_with(value, responder)
        self.assertFalse(result["extraction_complete"])
        self.assertEqual(
            result["unextracted_reason"],
            "works chunk 1: bibliography truncated; claims chunk 1: claim meaning unknown",
        )

    def test_schemas_are_strict(self):
        work_schema = json.loads(WORK_SCHEMA.read_text(encoding="utf-8"))
        claim_schema = json.loads(CLAIM_SCHEMA.read_text(encoding="utf-8"))
        work = complete_works()
        work["extra"] = True
        claim = complete_claims(
            [
                {
                    "span_ids": ["span-" + "a" * 64],
                    "cited_work_ids": [],
                    "quote": "made up",
                }
            ]
        )
        self.assertTrue(list(Draft202012Validator(work_schema).iter_errors(work)))
        self.assertTrue(list(Draft202012Validator(claim_schema).iter_errors(claim)))

    def test_missing_identifier_error_identifies_the_actual_row_and_raw_format(self):
        text = (
            "Visible Study. *Example Working Paper* 2022-2. https://example.org/paper"
        )
        value = subject(text)
        index, _ = extraction_chunks(value)
        ids = list(index)
        row = {
            "span_ids": ids,
            "title": "Visible Study",
            "identifier": "Example Working Paper 2022-2",
            "nominated_core": False,
        }
        with self.assertRaisesRegex(
            EvaluationError, r"row 1.*Example Working Paper 2022-2.*absent"
        ):
            _normalize_works(complete_works([row]), index, set(ids))
        # A visible literal URL repairs the label, without altering the quotation.
        row["identifier"] = "https://example.org/paper"
        accepted = _normalize_works(complete_works([row]), index, set(ids))
        self.assertEqual(accepted["works"][0]["exact_reference"], text)

    def test_summary_mentions_preserve_sources_without_becoming_extra_papers(self):
        value = subject("Smith et al. and the validation review support this point.")
        ids = list(extraction_chunks(value)[0])

        def responder(label, _prompt):
            if "works" in label:
                result = complete_works()
                result["mentions"] = [{"span_ids": ids, "reason": "shorthand"}]
                return result
            return complete_claims()

        result, provenance, _ = self.run_with(value, responder)
        self.assertEqual(result["works"], [])
        self.assertEqual(len(provenance["mention_sources"]), 1)
        self.assertIn(
            "Smith et al.", provenance["mention_sources"][0]["exact_reference"]
        )

    def test_grouped_mentions_restore_separate_passages_not_a_cross_file_quote(self):
        value = {
            "evidence": {"one": evidence("Smith et al."), "two": evidence("the review")}
        }
        index, _ = extraction_chunks(value)
        ids = list(index)
        raw = complete_works()
        raw["mentions"] = [{"span_ids": ids[::-1], "reason": "shorthand"}]
        normalized = _normalize_works(raw, index, set(ids))
        self.assertEqual(
            [row["exact_reference"] for row in normalized["mentions"]],
            ["the review", "Smith et al."],
        )
        self.assertEqual(
            [row["evidence_id"] for row in normalized["mentions"]], ["two", "one"]
        )
        with self.assertRaisesRegex(EvaluationError, "outside its chunk"):
            _normalize_works(raw, index, {ids[0]})

    def test_doi_spelling_and_terminal_title_period_merge_but_conflicting_title_does_not(
        self,
    ):
        rows = []
        for title, identifier in [
            ("Visible Study.", "https://doi.org/10.1234/study"),
            ("Visible Study", "10.1234/study"),
            ("Different Study", "10.1234/study"),
        ]:
            rows.append(
                {
                    "title": title,
                    "identifier": identifier,
                    "nominated_core": False,
                    "span_ids": ["test"],
                    "evidence_id": "test",
                    "exact_reference": title,
                }
            )
        works, sources = _aggregate_works([complete_works(rows)])
        self.assertEqual(len(works), 2)
        self.assertEqual(sorted(len(v) for v in sources.values()), [1, 2])


if __name__ == "__main__":
    unittest.main()

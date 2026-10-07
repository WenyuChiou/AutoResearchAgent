import json
import re
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import test_source_audit_units as fixtures

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage1_eval.common import EvaluationError, canonical, read_json, sha  # noqa: E402
from stage1_eval.original_fields import (
    FIELDS,
    audit_subject_sources,
    extract_original_fields,
)  # noqa: E402
from stage1_eval.source_audit_units import audit_targets  # noqa: E402
from stage1_eval.spans import extraction_chunks  # noqa: E402


class OriginalFieldTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SourceAuditUnitTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.extraction = deepcopy(self.fixture.extraction)
        citation = (
            "Élodie Example (2019). Synthetic consumption study. 10.1000/example. v1.\n"
        )
        text = (
            "x" * (900 - len("Élodie "))
            + citation
            + "Context. " * 110
            + citation.replace("2019", "2020").replace("v1", "v2")
        )
        self.subject = {
            "evidence": {
                "answer": {
                    "text": text,
                    "sha256": sha(text.encode()),
                    "origin": "subject-answer",
                }
            }
        }
        index, _ = extraction_chunks(self.subject)
        sources = [
            {"evidence_id": "answer", "span_ids": [key]}
            for key, span in index.items()
            if "Synthetic consumption study" in span["text"]
        ]
        self.provenance = {
            "span_index_sha256": sha(canonical(index)),
            "work_source_map": {"work": sources},
        }
        self.output = self.fixture.root / "originals"

    @staticmethod
    def complete(command, value):
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

    def respond(self, command, **kwargs):
        data, _ = json.JSONDecoder().raw_decode(
            kwargs["input"].decode().split("\n", 1)[1]
        )
        if "target" in data:
            if data["target"].get("field") == "year":
                proof = [
                    key
                    for key, row in data["sources"].items()
                    if row["level"] == "metadata" and "2025" in row["text"]
                ]
                return self.complete(
                    command,
                    {
                        "verdict": "contradicted" if proof else "unverifiable",
                        "reason": "Synthetic metadata year differs from the original, or is absent in this window.",
                        "addressed": list(data["sources"]),
                        "passages": proof,
                    },
                )
            return self.fixture.respond(command, **kwargs)
        literals = {
            "title": ["Synthetic consumption study"],
            "authors": ["Élodie Example"],
            "year": ["2019", "2020"],
            "identifier": ["10.1000/example"],
            "version": ["v1", "v2"],
        }
        fields = {field: [] for field in FIELDS}
        text = "".join(data["spans"].values())
        for field, values in literals.items():
            for literal in values:
                for match in re.finditer(re.escape(literal), text):
                    offset, parts = 0, []
                    for alias, span in data["spans"].items():
                        start, end = (
                            max(match.start() - offset, 0),
                            min(match.end() - offset, len(span)),
                        )
                        if start < end:
                            part = span[start:end]
                            occurrence = sum(
                                m.start() < start
                                for m in re.finditer(re.escape(part), span)
                            )
                            parts.append(
                                {
                                    "span_id": alias,
                                    "literal": part,
                                    "occurrence": occurrence,
                                }
                            )
                        offset += len(span)
                    fields[field].append({"parts": parts})
        result = {
            "addressed": list(data["spans"]),
            "fields": fields,
            "missing": {
                field: None if rows else "Absent from this original context."
                for field, rows in fields.items()
            },
        }
        return self.complete(command, result)

    def invoke(self, **kwargs):
        return extract_original_fields(
            self.subject,
            self.extraction,
            self.provenance,
            self.output,
            self.fixture.options,
            **kwargs,
        )

    def test_original_values_conflicts_cross_span_unicode_and_zero_call_replay(self):
        before = deepcopy(self.extraction)
        with mock.patch(
            "stage1_eval.model_calls._execute_bound_process", side_effect=self.respond
        ):
            enriched, receipt = self.invoke()
        fields = enriched["works"][0]["original_fields"]
        self.assertEqual({row["raw_value"] for row in fields["year"]}, {"2019", "2020"})
        self.assertEqual(
            {row["raw_value"] for row in fields["authors"]}, {"Élodie Example"}
        )
        self.assertTrue(any(len(row["passages"]) == 2 for row in fields["authors"]))
        self.assertEqual(self.extraction, before)
        self.assertEqual(enriched["central_claims"], before["central_claims"])
        self.assertFalse(receipt["semantic_identity_verified"])
        year_targets = [
            row for row in audit_targets(enriched) if row.get("field") == "year"
        ]
        self.assertEqual(len(year_targets), 2)
        self.assertEqual(len({row["id"] for row in year_targets}), 2)
        for row in year_targets:
            part = row["original_field_passages"][0]
            self.assertEqual(
                self.subject["evidence"]["answer"]["text"][part["start"] : part["end"]],
                row["original_value"],
            )
        with mock.patch("stage1_eval.model_calls._execute_bound_process") as replay:
            self.assertEqual(self.invoke(replay_only=True), (enriched, receipt))
        replay.assert_not_called()

    def test_connected_source_audit_uses_original_year_not_external_year(self):
        with mock.patch(
            "stage1_eval.model_calls._execute_bound_process", side_effect=self.respond
        ):
            result = audit_subject_sources(
                self.subject,
                self.extraction,
                self.provenance,
                self.fixture.packet,
                [self.fixture.record],
                self.fixture.root / "combined",
                self.fixture.options,
            )
        targets = [row["target"] for row in result["source_audits"]["summaries"]]
        self.assertEqual(
            {row["original_value"] for row in targets if row.get("field") == "year"},
            {"2019", "2020"},
        )
        self.assertNotIn(
            str(self.fixture.record["year"]),
            {row["original_value"] for row in targets if row.get("field") == "year"},
        )
        self.assertEqual(
            {row["id"] for row in targets if row["kind"] == "claim"},
            {"claim", "uncited"},
        )
        self.assertFalse(result["score_awarded"])
        self.assertTrue(
            all(
                row["verdict"] == "contradicted"
                for row in result["source_audits"]["summaries"]
                if row["target"].get("field") == "year"
            )
        )

    def test_absent_original_version_is_not_filled_from_source_version(self):
        evidence = self.subject["evidence"]["answer"]
        evidence["text"] = evidence["text"].replace("v1", "").replace("v2", "")
        evidence["sha256"] = sha(evidence["text"].encode())
        index, _ = extraction_chunks(self.subject)
        self.provenance = {
            "span_index_sha256": sha(canonical(index)),
            "work_source_map": {
                "work": [
                    {"evidence_id": "answer", "span_ids": [key]}
                    for key, row in index.items()
                    if "Synthetic consumption study" in row["text"]
                ]
            },
        }
        with mock.patch(
            "stage1_eval.model_calls._execute_bound_process", side_effect=self.respond
        ):
            enriched, _ = self.invoke()
        self.assertEqual(enriched["works"][0]["original_fields"]["version"], [])
        version = [
            row for row in audit_targets(enriched) if row.get("field") == "version"
        ]
        self.assertEqual(len(version), 1)
        self.assertIsNone(version[0]["original_value"])

    def test_wrong_work_provenance_and_changed_subject_reject_before_model(self):
        with mock.patch("stage1_eval.model_calls._execute_bound_process") as run:
            self.provenance["work_source_map"]["work"][0]["evidence_id"] = "wrong-file"
            with self.assertRaisesRegex(EvaluationError, "wrong citation evidence"):
                self.invoke()
            self.subject["evidence"]["answer"]["text"] += "changed"
            with self.assertRaisesRegex(EvaluationError, "span index changed"):
                self.invoke()
        run.assert_not_called()

    def test_invented_literal_preserves_two_failed_generations_and_error(self):
        def wrong(command, **kwargs):
            self.respond(command, **kwargs)
            path = Path(command[command.index("-o") + 1])
            value = read_json(path)
            value["fields"]["year"][0]["parts"][0]["literal"] = "invented year"
            return self.complete(command, value)

        with mock.patch(
            "stage1_eval.model_calls._execute_bound_process", side_effect=wrong
        ) as run:
            with self.assertRaisesRegex(EvaluationError, "literal is absent"):
                self.invoke()
        self.assertEqual(run.call_count, 2)
        self.assertEqual(len(list(self.output.glob("*.model-call"))), 2)
        self.assertEqual(len(list(self.output.glob("*.error.json"))), 1)
        self.assertFalse((self.output / "result.json").exists())

    def test_rehashed_original_result_tamper_is_rejected_without_calls(self):
        with mock.patch(
            "stage1_eval.model_calls._execute_bound_process", side_effect=self.respond
        ):
            self.invoke()
        path = self.output / "result.json"
        result = read_json(path)
        result["extraction"]["works"][0]["original_fields"]["year"][0]["raw_value"] = (
            "9999"
        )
        path.write_bytes(canonical(result))
        with mock.patch("stage1_eval.model_calls._execute_bound_process") as replay:
            with self.assertRaisesRegex(
                EvaluationError, "saved evaluator artifact changed"
            ):
                self.invoke(replay_only=True)
        replay.assert_not_called()


if __name__ == "__main__":
    unittest.main()

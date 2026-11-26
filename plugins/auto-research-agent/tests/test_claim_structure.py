"""C1/C2 fixed public synthetic text; no research or network execution."""

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
import json
import subprocess
from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from test_stage1_ledger import SYNTHETIC, add_query
from stage1_ledger.store import Ledger
from stage1_ledger.journal import LedgerError
from stage1_ledger.validation import validate_run
from stage1_deliverable import views
from stage1_ledger.claim_structure import split_hint
from test_stage1_ledger import rewrite_for_tamper_test

TEXT = "The sample contains 24 recordings in 2024. Accuracy increased. Latency decreased. Cost decreased."
COMPOUND = "Accuracy increased; latency decreased; cost decreased."


class ClaimStructureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Ledger.create(
            Path(self.tmp.name) / "run",
            run_id="c1-c2",
            objective="Public synthetic engineering fixture",
        )
        add_query(self.ledger, [SYNTHETIC])
        self.ledger.extract()
        work = next(iter(self.ledger.candidates().values()))
        self.work, self.version = work["work_id"], work["version_ids"][0]
        start = self.ledger.start_source_import(
            work_id=self.work,
            version_id=self.version,
            source_uri="https://example.invalid/c1-c2",
            actor="fixture-agent",
            reason="Authored public test text",
        )
        self.ref = self.ledger.save_bytes(TEXT.encode(), producer=start)

    def request(self, text, **extra):
        result = dict(
            work_id=self.work,
            version_id=self.version,
            claim_text=text,
            relation="unverifiable",
            evidence_level="full_text",
            source_ref=self.ref,
            locator=dict(section="Synthetic observations", quote=text),
            verifier=dict(
                actor="fixture-agent",
                actor_type="agent",
                method="fixed-text engineering check",
            ),
        )
        result.update(extra)
        return result

    def test_legacy_report_displays_unclassified_and_compound_warning(self):
        event_id = self.ledger.claim(
            **self.request(
                COMPOUND,
                locator=dict(
                    section="Synthetic observations", quote="Accuracy increased."
                ),
            )
        )
        event = self.ledger.event(event_id)
        records = dict(
            topic="Public synthetic C1/C2",
            as_of="2026-01-01T00:00:00Z",
            schema_version="1.1.0",
            papers=[],
            core_claim_history=[],
            claims=[
                dict(
                    claim_id=event_id,
                    work_id=self.work,
                    version_id=self.version,
                    text=COMPOUND,
                    relation=event["relation"],
                    evidence_level=event["evidence_level"],
                    core_event=dict(payload=event),
                )
            ],
        )
        rendered = "\n".join(views.review_lines(records))
        self.assertIn("Unclassified", rendered)
        self.assertIn("split", rendered.lower())

    def test_typed_source_and_interpretation_reopen_with_basis(self):
        basis = self.ledger.claim(
            **self.request(
                "Accuracy increased.", claim_type="source_statement", basis_claim_ids=[]
            )
        )
        request = self.request(
            "This motivates a project accuracy check.",
            claim_type="project_interpretation",
            basis_claim_ids=[basis],
        )
        request["locator"]["quote"] = "Accuracy increased."
        target = self.ledger.claim(**request)
        reopened = Ledger(self.ledger.root)
        self.assertEqual(reopened.event(target)["basis_claim_ids"], [basis])
        self.assertEqual(reopened.event(target)["schema_version"], "1.2.0")
        report = validate_run(self.ledger.root)
        self.assertTrue(report["valid"], report)

    def test_date_and_value_are_one_fact_not_numeric_count_warning(self):
        text = "The sample contains 24 recordings in 2024."
        event = self.ledger.claim(
            **self.request(text, claim_type="source_statement", basis_claim_ids=[])
        )
        self.assertIsNone(split_hint(text))
        self.assertEqual(
            Ledger(self.ledger.root).event(event)["locator"]["quote"], text
        )
        for single in (
            "On 2024-01-01 the value was 3.14.",
            "2024年样本含24条记录。",
            "Accuracy increased from 42 to 48 percent.",
        ):
            with self.subTest(single=single):
                self.assertIsNone(split_hint(single))

    def test_compound_warning_is_advisory_not_rejection(self):
        for text in (
            COMPOUND,
            "Accuracy increased. Latency decreased. Cost decreased.",
            "Accuracy increases and cost decreases.",
            "准确率提高；延迟降低；成本减少。",
        ):
            with self.subTest(text=text):
                self.assertIsNotNone(split_hint(text))
                self.ledger.claim(
                    **self.request(
                        text,
                        locator=dict(
                            section="observations", quote="Accuracy increased."
                        ),
                        claim_type="source_statement",
                        basis_claim_ids=[],
                    )
                )
        self.assertTrue(validate_run(self.ledger.root)["valid"])

    def test_split_claims_retain_their_own_original_sentence(self):
        sentences = ["Accuracy increased.", "Latency decreased.", "Cost decreased."]
        ids = [
            self.ledger.claim(
                **self.request(text, claim_type="source_statement", basis_claim_ids=[])
            )
            for text in sentences
        ]
        reopened = Ledger(self.ledger.root)
        self.assertEqual(
            [reopened.event(key)["locator"]["quote"] for key in ids], sentences
        )
        self.assertTrue(
            all(
                reopened.read_ref(reopened.event(key)["source_ref"]).decode() == TEXT
                for key in ids
            )
        )

    def test_missing_invalid_and_untyped_basis_rejected_without_writes(self):
        old = self.ledger.claim(**self.request("Accuracy increased."))
        for basis in ([], [old], ["e999999"], [old, old], "e000001", None):
            with self.subTest(basis=basis):
                before = self.ledger.events()
                with self.assertRaises(LedgerError):
                    self.ledger.claim(
                        **self.request(
                            "Accuracy increased.",
                            claim_type="project_interpretation",
                            basis_claim_ids=basis,
                        )
                    )
                self.assertEqual(self.ledger.events(), before)

    def test_source_type_is_explicit_and_requires_location(self):
        for extra in (
            dict(claim_type="unknown", basis_claim_ids=[]),
            dict(claim_type=[], basis_claim_ids=[]),
            dict(claim_type="source_statement", basis_claim_ids=[], locator=None),
            dict(claim_type="source_statement", basis_claim_ids=["e000001"]),
        ):
            with self.subTest(extra=extra):
                before = self.ledger.events()
                with self.assertRaises(LedgerError):
                    self.ledger.claim(**self.request("Accuracy increased.", **extra))
                self.assertEqual(self.ledger.events(), before)

    def test_other_work_or_version_basis_rejected(self):
        basis = self.ledger.claim(
            **self.request(
                "Accuracy increased.", claim_type="source_statement", basis_claim_ids=[]
            )
        )
        add_query(
            self.ledger,
            [
                dict(SYNTHETIC, doi="10.5555/other"),
                dict(SYNTHETIC, version="record-v2"),
            ],
        )
        self.ledger.extract()
        original = self.request(
            "Accuracy increased.",
            claim_type="project_interpretation",
            basis_claim_ids=[basis],
        )
        for work in self.ledger.candidates().values():
            for version in work["version_ids"]:
                if (work["work_id"], version) == (self.work, self.version):
                    continue
                before = self.ledger.events()
                with self.assertRaisesRegex(
                    LedgerError, "basis-not-prior-same-work-version"
                ):
                    self.ledger.claim(
                        **dict(original, work_id=work["work_id"], version_id=version)
                    )
                self.assertEqual(self.ledger.events(), before)

    def test_interpretation_is_not_another_interpretations_source(self):
        basis = self.ledger.claim(
            **self.request(
                "Accuracy increased.", claim_type="source_statement", basis_claim_ids=[]
            )
        )
        interpreted = self.ledger.claim(
            **self.request(
                "Accuracy increased.",
                claim_type="project_interpretation",
                basis_claim_ids=[basis],
            )
        )
        with self.assertRaisesRegex(LedgerError, "basis-not-prior"):
            self.ledger.claim(
                **self.request(
                    "Accuracy increased.",
                    claim_type="project_interpretation",
                    basis_claim_ids=[interpreted],
                )
            )

    def test_rehashed_broken_basis_is_rejected_on_replay(self):
        basis = self.ledger.claim(
            **self.request(
                "Accuracy increased.", claim_type="source_statement", basis_claim_ids=[]
            )
        )
        self.ledger.claim(
            **self.request(
                "Accuracy increased.",
                claim_type="project_interpretation",
                basis_claim_ids=[basis],
            )
        )
        rewrite_for_tamper_test(
            self.ledger,
            lambda rows: rows[-1]["payload"].update(basis_claim_ids=["e999999"]),
        )
        result = validate_run(self.ledger.root)
        self.assertFalse(result["valid"])
        self.assertIn(
            "interpretation-basis-not-prior-same-work-version-source",
            str(result["errors"]),
        )

    def test_public_cli_accepts_typed_request_and_fresh_process_validates(self):
        request = Path(self.tmp.name) / "claim.json"
        request.write_text(
            json.dumps(
                self.request(
                    "Accuracy increased.",
                    claim_type="source_statement",
                    basis_claim_ids=[],
                )
            ),
            encoding="utf8",
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "stage1_ledger",
                "--run",
                str(self.ledger.root),
                "claim",
                "--request",
                str(request),
            ],
            capture_output=True,
            text=True,
            encoding="utf8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["event_id"])
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "stage1_ledger",
                "--run",
                str(self.ledger.root),
                "validate",
            ],
            capture_output=True,
            text=True,
            encoding="utf8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["valid"])

    def test_normal_producer_package_word_markdown_and_new_process_validation(self):
        from test_project_stage1_records import saved_stage1_case
        from test_stage1_core_records import produced
        from stage1_deliverable.package import build
        from stage1_deliverable.common import sha
        from stage1_deliverable.core_records import validate_extension

        with saved_stage1_case() as (case, fixture):
            ledger = fixture["ledger"]
            paper = fixture["records"]["papers"][0]
            old = ledger.event(paper["claim_ids"][0])
            request = {
                key: deepcopy(old[key])
                for key in (
                    "work_id",
                    "version_id",
                    "claim_text",
                    "relation",
                    "evidence_level",
                    "locator",
                    "source_ref",
                    "verifier",
                )
            }
            request.update(
                claim_type="source_statement",
                basis_claim_ids=[],
                relation="unverifiable",
                verifier=dict(
                    actor="fixture-agent",
                    actor_type="agent",
                    method="literal synthetic source check",
                ),
            )
            basis = ledger.claim(**request)
            interpretation = ledger.claim(
                **dict(
                    request,
                    claim_text="Project interpretation: this motivates an engineering comparison.",
                    claim_type="project_interpretation",
                    basis_claim_ids=[basis],
                )
            )
            fixture["checkpoint"] = ledger.checkpoint()
            for original, _ in fixture["pairs"]:
                target = original["papers"][0]
                reading = case.producer.derive_reading_payload(
                    fixture["ref"],
                    target["work_id"],
                    classification=target["classification"],
                    findings=target["findings"],
                    roles=[],
                    expected_ledger_state_sha256=ledger.state_hash(),
                )
                case.producer.register_reading(
                    fixture["ref"],
                    reading=reading,
                    expected_ledger_state_sha256=ledger.state_hash(),
                )
            _, path, records = produced(case, fixture)
            validate_extension(records)
            output = case.fixture_root / "c1-c2-package"
            receipt = build(path, output, sha(path.read_bytes()))
            self.assertEqual(receipt["status"], "passed", receipt)
            original_events = ledger.events()
            markdown = (output / "literature_review.md").read_text(encoding="utf8")
            word = "\n".join(
                p.text for p in Document(output / "literature_review.docx").paragraphs
            )
            for text in (markdown, word):
                for label in (
                    "Source statement",
                    "Project interpretation",
                    "Unclassified",
                    "Basis " + basis,
                    old["locator"]["quote"],
                ):
                    self.assertIn(label, text)
            projection = json.loads((output / "claim_structure.json").read_bytes())
            item = next(
                row for row in projection["claims"] if row["claim_id"] == interpretation
            )
            self.assertEqual(item["basis_claim_ids"], [basis])
            self.assertFalse(item["atomicity_verified"])
            self.assertIn(
                "basis_claim_ids",
                (output / "claims_and_evidence.csv").read_text(encoding="utf8"),
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "stage1_deliverable",
                    "validate",
                    str(output),
                    "--expected-sha256",
                    receipt["manifest_sha256"],
                ],
                capture_output=True,
                text=True,
                encoding="utf8",
            )
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            self.assertEqual(ledger.events(), original_events)
            # Rehashed canonical input still cannot invent a missing basis.
            altered = deepcopy(records)
            for row in altered["core_claim_history"]:
                if row["payload"]["event_id"] == interpretation:
                    row["payload"]["basis_claim_ids"] = ["e999999"]
            with self.assertRaisesRegex(LedgerError, "basis-not-prior"):
                validate_extension(altered)


if __name__ == "__main__":
    unittest.main()

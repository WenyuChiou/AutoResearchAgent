"""Private original-record recovery never creates a scientific assessment."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_research_workspace_view import fixture_index
from research_workspace.delivery_review import (
    CONTRACT,
    LEGACY_CONTRACT,
    delivery_review_files,
)
from research_workspace.original_record_recovery import attach_original_records, _spans
from research_workspace.projection import validate_index
from stage1_deliverable.common import DeliverableError, canonical, sha


def recovery_case(root):
    index = fixture_index()
    source = b"Prefix. Saved exact passage."
    claim = dict(
        claim_id="old-claim",
        work_id="fixture-0",
        version_id="version-0",
        source_id="source-0",
        relation="unverified",
        text="A source-reported statement",
        quote="Saved exact passage",
        start=8,
        end=27,
        locator="characters 8:27",
        evidence_level="full-text",
    )
    index["claims"] = [claim]
    index["sources"] = [
        dict(
            source_id="source-0",
            work_id="fixture-0",
            version_id="version-0",
            receipt=dict(extracted_text_sha256=sha(source)),
        )
    ]
    docs = {
        "source.txt": source,
        "note.json": canonical(
            dict(
                statement=claim["text"],
                evidence=[dict(start=0, end=19, quote=claim["quote"])],
            )
        ),
        "prior.json": canonical(
            dict(
                claim=claim,
                reason="Only one clause has a bound passage; the other remains unresolved.",
            )
        ),
    }

    def ref(path, pointer=""):
        return dict(path=path, pointer=pointer)

    spec = dict(
        project_id=index["project_id"],
        input_canonical_sha256=sha(canonical(index)),
        records_sha256=index["provenance"]["records_sha256"],
        claims=[
            dict(
                claim_id=claim["claim_id"],
                original_claim_sha256=sha(canonical(claim)),
                source_path="source.txt",
                notes=[ref("note.json")],
                reason=ref("prior.json", "/reason"),
                reason_claim=ref("prior.json", "/claim"),
                missing=["No final semantic re-review disposition"],
            )
        ],
        works=[
            dict(
                work_id="fixture-0",
                version_id="version-0",
                context=[ref("note.json")],
                missing=["Historical screening event not delivered"],
            )
        ],
        historical_documents=[
            dict(
                scope="separate-old-run",
                meaning="Does not change current run counts",
                source=ref("prior.json"),
            )
        ],
        missing_originals=[],
    )
    docs["recovery.json"] = canonical(spec)
    for name, content in docs.items():
        (root / name).write_bytes(content)
    raw = canonical(
        dict(
            kind="Stage1OriginalRecordRecovery",
            schema_version="1.0.0",
            files={n: sha(v) for n, v in docs.items()},
        )
    )
    (root / "manifest.json").write_bytes(raw)
    return index, sha(raw)


class OriginalRecordRecoveryTests(unittest.TestCase):
    def test_layout_bundle_replays_and_exports_original_and_current_span(self):
        with tempfile.TemporaryDirectory(
            dir=Path(tempfile.gettempdir()).resolve()
        ) as folder:
            root = Path(folder)
            index, _ = recovery_case(root)
            index["sources"][0]["receipt"]["raw_sha256"] = "a" * 64
            claim = index["claims"][0]
            note = json.loads((root / "note.json").read_bytes())
            note["evidence"][0]["quote"] = "passage exact Saved"
            (root / "note.json").write_bytes(canonical(note))
            literal = dict(
                **{
                    k: claim[k]
                    for k in ("claim_id", "work_id", "version_id", "source_id")
                },
                current_source_sha256=sha((root / "source.txt").read_bytes()),
                raw_pdf_sha256="a" * 64,
                reviewer_type="ai",
                method="saved-source-layout-review",
                original_support_purpose_reestablished=False,
                semantic_support_verdict=None,
                claim_relation_changed=False,
                original_note=dict(
                    sha256=sha(canonical(note)),
                    field_pointer="/evidence/0",
                    original_span=note["evidence"][0],
                ),
                proposed_append_only_literal_revision=dict(
                    start=claim["start"],
                    end=claim["end"],
                    quote=claim["quote"],
                    quote_sha256=sha(claim["quote"].encode("utf-8")),
                ),
            )
            (root / "literal.json").write_bytes(canonical(literal))
            spec = json.loads((root / "recovery.json").read_bytes())
            spec["input_canonical_sha256"] = sha(canonical(index))
            spec["claims"][0]["literal_revisions"] = [
                dict(path="literal.json", pointer="")
            ]
            (root / "recovery.json").write_bytes(canonical(spec))
            manifest = json.loads((root / "manifest.json").read_bytes())
            for name in ("note.json", "recovery.json", "literal.json"):
                manifest["files"][name] = sha((root / name).read_bytes())
            raw = canonical(manifest)
            (root / "manifest.json").write_bytes(raw)
            recovered = attach_original_records(index, root, sha(raw))
            validate_index(recovered)
            files = delivery_review_files(recovered)
            row = json.loads(files["literature/claim_verification.json"])["rows"][0]
            check = row["historical_recovery"]["span_checks"][0]
            self.assertEqual(check["state"], "layout-reviewed-literal")
            self.assertEqual(check["original"], note["evidence"][0])
            self.assertEqual(check["current"]["quote"], claim["quote"])
            self.assertEqual(row["original_claim"], claim)
            self.assertIn(
                "original-note-citation-purpose-not-reestablished",
                json.loads(files["literature/delivery_review.json"])["repair_required"],
            )

    def test_source_rerun_validation_retains_recovery_input_binding(self):
        from test_research_workspace_literature_selection import attached_index
        from research_workspace.source_rerun import validate_rerun_index

        original, index = attached_index()
        self.addCleanup(original.cleanup)
        with tempfile.TemporaryDirectory(
            dir=Path(tempfile.gettempdir()).resolve()
        ) as folder:
            root = Path(folder)
            recovery_case(root)
            spec = json.loads((root / "recovery.json").read_bytes())
            spec.update(
                project_id=index["project_id"],
                input_canonical_sha256=sha(canonical(index)),
                records_sha256=index["provenance"]["records_sha256"],
                claims=[],
                works=[],
            )
            (root / "recovery.json").write_bytes(canonical(spec))
            manifest = json.loads((root / "manifest.json").read_bytes())
            manifest["files"]["recovery.json"] = sha(canonical(spec))
            (root / "manifest.json").write_bytes(canonical(manifest))
            recovered = attach_original_records(index, root, sha(canonical(manifest)))
            validate_rerun_index(recovered)
            self.assertIn("original_record_recovery", recovered)

    def test_layout_revision_is_exact_bound_and_never_restores_citation_purpose(self):
        from research_workspace.literal_revisions import apply_literal_revisions

        claim = dict(
            claim_id="claim", work_id="work", version_id="version", source_id="source"
        )
        original = dict(start=0, end=4, quote="drow")
        checks = [
            dict(
                note_path="note",
                note_pointer="/fields/x",
                pointer="/evidence/0",
                original=original,
                state="quote-not-found",
                current=None,
            )
        ]
        review = dict(
            **claim,
            current_source_sha256=sha(b"word"),
            raw_pdf_sha256="a" * 64,
            reviewer_type="ai",
            method="saved-source-layout-review",
            original_support_purpose_reestablished=False,
            semantic_support_verdict=None,
            claim_relation_changed=False,
            original_note=dict(
                sha256="b" * 64,
                field_pointer="/fields/x/evidence/0",
                original_span=original,
            ),
            proposed_append_only_literal_revision=dict(
                start=0, end=4, quote="word", quote_sha256=sha(b"word")
            ),
        )
        result = apply_literal_revisions(
            claim, checks, [dict(value=review)], dict(note="b" * 64), "word", "a" * 64
        )
        self.assertEqual(result[0]["state"], "layout-reviewed-literal")
        self.assertEqual(result[0]["original"], original)
        self.assertFalse(result[0]["original_support_purpose_reestablished"])
        self.assertIsNone(checks[0]["current"])
        for key, value in [
            ("work_id", "wrong"),
            ("raw_pdf_sha256", "c" * 64),
            ("semantic_support_verdict", "supported"),
        ]:
            changed = {**review, key: value}
            with self.assertRaises(DeliverableError):
                apply_literal_revisions(
                    claim,
                    checks,
                    [dict(value=changed)],
                    dict(note="b" * 64),
                    "word",
                    "a" * 64,
                )

    def test_authenticated_http_export_preserves_recovered_records(self):
        from test_research_workspace_harness_host import HarnessHostTests

        with tempfile.TemporaryDirectory(
            dir=Path(tempfile.gettempdir()).resolve()
        ) as folder:
            index, pin = recovery_case(Path(folder))
            index = attach_original_records(index, folder, pin)
            value = dict(index=index, index_sha256=sha(canonical(index)), note_paths=[])
            case = HarnessHostTests(
                "test_exports_bearer_fixed_names_exact_hash_and_changed_file_rejected"
            )
            with patch(
                "test_research_workspace_harness_host.payload", return_value=value
            ):
                case.setUp()
            try:
                status, _, raw = case.post(case.request("export-selection"))
                self.assertEqual(status, 200)
                result = json.loads(raw)
                item = next(
                    r
                    for r in result["artifacts"]
                    if r["name"] == "literature/claim_verification.json"
                )
                path = (
                    "/api/harness/projects/alpha/artifacts/one/"
                    + item["name"]
                    + "?sha256="
                    + item["sha256"]
                )
                status, _, raw = case.call(path)
                self.assertEqual(status, 200)
                self.assertEqual(sha(raw), item["sha256"])
                self.assertEqual(
                    json.loads(raw)["rows"][0]["reason_state"], "recovered-record"
                )
            finally:
                case.doCleanups()

    def test_selected_note_rejects_explicit_identity_conflict(self):
        with tempfile.TemporaryDirectory(
            dir=Path(tempfile.gettempdir()).resolve()
        ) as folder:
            root = Path(folder)
            index, _ = recovery_case(root)
            note = json.loads((root / "note.json").read_bytes())
            note["work_id"] = "different-work"
            (root / "note.json").write_bytes(canonical(dict(notes=[note])))
            spec = json.loads((root / "recovery.json").read_bytes())
            spec["claims"][0]["notes"][0]["pointer"] = "/notes/0"
            (root / "recovery.json").write_bytes(canonical(spec))
            manifest = json.loads((root / "manifest.json").read_bytes())
            for name in ("note.json", "recovery.json"):
                manifest["files"][name] = sha((root / name).read_bytes())
            raw = canonical(manifest)
            (root / "manifest.json").write_bytes(raw)
            with self.assertRaisesRegex(DeliverableError, "note identity differs"):
                attach_original_records(index, root, sha(raw))

    def test_actual_export_preserves_claim_and_recovers_specific_reason_and_span(self):
        with tempfile.TemporaryDirectory(
            dir=Path(tempfile.gettempdir()).resolve()
        ) as folder:
            index, pin = recovery_case(Path(folder))
            before = deepcopy(index)
            attached = attach_original_records(index, folder, pin)
            validate_index(attached)
            files = delivery_review_files(attached)
            self.assertEqual(
                files, delivery_review_files(json.loads(canonical(attached)))
            )
            row = json.loads(files["literature/claim_verification.json"])["rows"][0]
            self.assertEqual(row["original_claim"], index["claims"][0])
            self.assertEqual(row["relation"], "unverified")
            self.assertEqual(row["reason_state"], "recovered-record")
            span = row["historical_recovery"]["span_checks"][0]
            self.assertEqual(span["state"], "relocated-exact")
            self.assertEqual(
                (span["original"]["start"], span["current"]["start"]), (0, 8)
            )
            self.assertEqual(index, before)
            self.assertIn("literature/original_record_recovery.json", files)
            self.assertEqual(
                json.loads(files["literature/delivery_review.json"])[
                    "contract_version"
                ],
                CONTRACT,
            )
            changed = deepcopy(attached)
            changed["claims"][0]["text"] += " changed"
            with self.assertRaises(DeliverableError):
                validate_index(changed)
            forged = deepcopy(attached)
            attachment = forged["original_record_recovery"]
            attachment["payload"]["claims"][0]["historical_reason"]["value"] = (
                "Invented reason"
            )
            attachment["payload_sha256"] = sha(canonical(attachment["payload"]))
            with self.assertRaises(DeliverableError):
                validate_index(forged)
            del attachment["manifest_utf8"]
            with self.assertRaises(DeliverableError):
                validate_index(forged)

    def test_manifest_pin_file_tamper_wrong_input_and_reference_escape_rejected(self):
        with tempfile.TemporaryDirectory(
            dir=Path(tempfile.gettempdir()).resolve()
        ) as folder:
            root = Path(folder)
            index, pin = recovery_case(root)
            with self.assertRaises(DeliverableError):
                attach_original_records(index, root, "0" * 64)
            wrong = deepcopy(index)
            wrong["project_id"] = "wrong-project"
            with self.assertRaises(DeliverableError):
                attach_original_records(wrong, root, pin)
            (root / "note.json").write_bytes(b"{}")
            with self.assertRaises(DeliverableError):
                attach_original_records(index, root, pin)
            index, _ = recovery_case(root)
            manifest = json.loads((root / "manifest.json").read_bytes())
            manifest["files"]["../escape.json"] = "0" * 64
            raw = canonical(manifest)
            (root / "manifest.json").write_bytes(raw)
            with self.assertRaises((DeliverableError, OSError)):
                attach_original_records(index, root, sha(raw))

    def test_no_exact_or_ambiguous_span_is_never_relocated(self):
        for text, state in [
            ("not present", "quote-not-found"),
            ("word word", "ambiguous"),
        ]:
            row = _spans(dict(start=1, end=5, quote="word"), text, "a" * 64)[0]
            self.assertEqual(row["state"], state)
            self.assertIsNone(row["current"])

    def test_legacy_review_contract_keeps_seven_file_shape(self):
        index = fixture_index()
        files = delivery_review_files(index, contract=LEGACY_CONTRACT)
        self.assertEqual(len(files), 7)
        self.assertEqual(
            json.loads(files["literature/delivery_review.json"])["contract_version"],
            LEGACY_CONTRACT,
        )

    def test_mixed_current_and_unmatched_history_exports_to_csv_and_workbook(self):
        from test_workspace_academic_screening import decision

        index = fixture_index()
        index["screening"] = [decision(1), {**decision(2), "work_id": "outside"}]
        files = delivery_review_files(index)
        self.assertIn(
            b"outside-current-index", files["literature/academic_screening_history.csv"]
        )
        self.assertGreater(len(files["literature/academic_screening.xlsx"]), 0)


if __name__ == "__main__":
    unittest.main()

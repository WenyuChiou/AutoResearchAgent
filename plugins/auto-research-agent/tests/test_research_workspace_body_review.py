"""Authored synthetic byte bundles; no PDFs, readers or research are executed."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))

from research_workspace.body_review import SCOPE, verify_body_review
from stage1_deliverable.common import DeliverableError, canonical, sha


def seal(row, artifacts, manifest, acceptance, execution=True):
    if execution:
        receipt = {"kind": "IndependentPDFReaderExecution", "schema_version": "1.0.0",
                   "binding": manifest["binding"], "outcome": "completed",
                   "parser_receipt_sha256": manifest["parser_receipt"]["sha256"],
                   "program_sha256": manifest["program"]["sha256"], "runtime_sha256": manifest["runtime"]["sha256"],
                   "pages_sha256": sha(canonical(manifest["pages"])), "discrepancies_sha256": sha(canonical(manifest["discrepancies"]))}
        artifacts["evidence/execution.json"] = canonical(receipt)
        manifest["reader_receipt"] = {"path": "evidence/execution.json", "sha256": sha(canonical(receipt))}
    raw = canonical(manifest)
    artifacts["evidence/manifest.json"] = raw
    acceptance["manifest_sha256"] = sha(raw)
    artifacts["evidence/acceptance.json"] = canonical(acceptance)
    expected = sha(artifacts["evidence/acceptance.json"])
    row["body_review"] = {"manifest_path": "evidence/manifest.json", "manifest_sha256": sha(raw), "acceptance_path": "evidence/acceptance.json", "acceptance_sha256": expected}
    return expected


def fixture(geometry=False, blank=False):
    artifacts = {}
    def ref(path, raw):
        artifacts[path] = raw
        return {"path": path, "sha256": sha(raw)}
    chunks = ["Synthetic title.", " " if blank else "Words, in order."]
    text = "\n\n".join(chunks)
    locators = [{"type": "pdf-page", "value": 1, "start": 0, "end": len(chunks[0])}, {"type": "pdf-page", "value": 2, "start": len(chunks[0]) + 2, "end": len(text)}]
    raw = ref("sources/raw.pdf", b"%PDF-1.7\nAuthored byte-binding fixture, not a parser probe.\n%%EOF")
    extracted = ref("sources/text.txt", text.encode())
    reading = {"status": "extracted", "evidence_level": "full-text", "identity_status": "unverified", "text_sha256": extracted["sha256"],
               "characters": len(text), "locators": locators, "diagnostics": {"pages_total": 2, "readable_pages": [1, 2], "omitted_pages": [], "blank_pages": [], "extraction_fidelity": "automatic fidelity pending"}}
    if geometry:
        reading["diagnostics"]["geometry_fallback_pages"] = [1]
    row = {"work_id": "synthetic-work", "source_id": "synthetic-source", "version_id": "synthetic-v1", "source_version": "sha256:" + raw["sha256"], "attempt_id": sha(b"projection attempt"),
           "raw_sha256": raw["sha256"], "raw_path": raw["path"], "extracted_path": extracted["path"], "reading": reading}
    binding = {key: row[key] for key in ("work_id", "source_id", "version_id", "source_version", "attempt_id", "raw_sha256")}
    binding.update(reading_sha256=sha(canonical(reading)), text_sha256=reading["text_sha256"])
    parser_program = ref("code/parser.py", b"synthetic original parser bytes")
    parser = {key: binding[key] for key in ("work_id", "source_id", "version_id", "source_version", "raw_sha256")}
    parser.update(reading=deepcopy(reading), runtime={"parser_sha256": parser_program["sha256"]})
    row["parser_receipt"] = ref("evidence/parser.json", canonical(parser))
    row["automatic_reading"] = deepcopy(reading)
    program = ref("code/reader.py", b"synthetic separate independent reader bytes")
    runtime = {"kind": "IndependentPDFReaderRuntime", "schema_version": "1.0.0", "python_version": "synthetic-python-v1", "reader_name": "synthetic-reader", "reader_version": "v1", "program_sha256": program["sha256"],
               "executable": ref("runtime/executable.bin", b"authored executable bytes"),
               "module": ref("runtime/module.py", b"authored module bytes"), "native_library": ref("runtime/native.bin", b"authored native bytes")}
    pages = []
    for locator, chunk in zip(locators, chunks):
        pages.append({"page": locator["value"], "start": locator["start"], "end": locator["end"], "saved_text_sha256": sha(chunk.encode()),
                      "reader_text": ref(f"pages/{locator['value']}.txt", chunk.encode()), "quotations": [{"start": locator["start"], "end": locator["end"], "text": chunk, "sha256": sha(chunk.encode())}], "comparison": "exact"})
    manifest = {"kind": "IndependentPDFBodyReview", "schema_version": "1.0.0", "scope": SCOPE, "producer": "synthetic-producer", "binding": binding, "parser_receipt": deepcopy(row["parser_receipt"]), "parser_program": parser_program,
                "reader_receipt": {}, "program": program, "runtime": ref("runtime/receipt.json", canonical(runtime)),
                "pages": pages, "coverage": dict.fromkeys(("text_availability", "order", "punctuation", "word_boundaries"), True), "cover_geometry_review": None, "discrepancies": [], "residual_failures": []}
    acceptance = {"kind": "IndependentPDFBodyReviewAcceptance", "schema_version": "1.0.0", "scope": SCOPE, "manifest_sha256": "", "reviewer": "synthetic-reviewer", "producer": manifest["producer"],
                  "decision": "reviewed-engineering-evidence", "cover_geometry_decision": "not-required", "discrepancy_reviews": []}
    return row, artifacts, manifest, acceptance


class BodyReviewTests(unittest.TestCase):
    def result(self, row, artifacts, manifest, acceptance):
        return verify_body_review(row, artifacts, seal(row, artifacts, manifest, acceptance))

    def test_complete_bound_evidence_is_deterministic_without_mutation_or_admission(self):
        row, artifacts, manifest, acceptance = fixture()
        expected = seal(row, artifacts, manifest, acceptance)
        before = deepcopy((row, artifacts))
        result = verify_body_review(row, artifacts, expected)
        self.assertEqual(result, verify_body_review(row, artifacts, expected))
        self.assertEqual((row, artifacts), before)
        self.assertEqual((result["status"], result["identity_status"]), ("verified-body-text", "unverified"))
        self.assertEqual(result["original_diagnostics"], row["reading"]["diagnostics"])
        self.assertFalse(result["formal_eligibility_override"] or result["reviewer_identity_authenticated"] or result["official_stage2_import_eligible"])
        self.assertEqual(result["artifact_bindings"], {name: sha(raw) for name, raw in sorted(artifacts.items())})

    def test_rehashed_bundle_cannot_replace_unchanged_external_acceptance(self):
        row, artifacts, manifest, acceptance = fixture()
        expected = seal(row, artifacts, manifest, acceptance)
        manifest["coverage"]["punctuation"] = False
        seal(row, artifacts, manifest, acceptance)
        with self.assertRaisesRegex(DeliverableError, "external acceptance"):
            verify_body_review(row, artifacts, expected)

    def test_all_referenced_artifacts_require_exact_bytes(self):
        row, artifacts, manifest, acceptance = fixture()
        seal(row, artifacts, manifest, acceptance)
        names = list(artifacts)
        for missing in (True, False):
            for name in names:
                row, artifacts, manifest, acceptance = fixture()
                expected = seal(row, artifacts, manifest, acceptance)
                if missing:
                    del artifacts[name]
                else:
                    artifacts[name] += b"changed"
                with self.subTest(path=name, missing=missing), self.assertRaises(DeliverableError):
                    verify_body_review(row, artifacts, expected)

    def test_stale_source_reading_attempt_and_runtime_bindings_reject(self):
        for key in ("work_id", "source_id", "version_id", "source_version", "attempt_id", "reading_sha256", "raw_sha256", "text_sha256"):
            row, artifacts, manifest, acceptance = fixture()
            manifest["binding"][key] = "changed"
            with self.subTest(key=key):
                self.assertRaises(DeliverableError, self.result, row, artifacts, manifest, acceptance)
        row, artifacts, manifest, acceptance = fixture()
        manifest["program"] = manifest["parser_program"]
        self.assertRaisesRegex(DeliverableError, "independent reader", self.result, row, artifacts, manifest, acceptance)
        for key in ("schema_version", "parser_receipt_sha256", "program_sha256", "runtime_sha256", "pages_sha256", "discrepancies_sha256", "binding", "outcome"):
            row, artifacts, manifest, acceptance = fixture()
            seal(row, artifacts, manifest, acceptance)
            receipt = json.loads(artifacts["evidence/execution.json"])
            receipt[key] = "stale"
            artifacts["evidence/execution.json"] = canonical(receipt)
            manifest["reader_receipt"]["sha256"] = sha(canonical(receipt))
            expected = seal(row, artifacts, manifest, acceptance, execution=False)
            self.assertRaises(DeliverableError, verify_body_review, row, artifacts, expected)

    def test_scoped_alphanumeric_only_coverage_stays_pending(self):
        row, artifacts, manifest, acceptance = fixture()
        manifest["coverage"].update(punctuation=False, word_boundaries=False)
        manifest["pages"][1]["comparison"] = "scoped"
        self.assertEqual(self.result(row, artifacts, manifest, acceptance)["status"], "scoped-pending")

    def test_residual_math_table_figure_failures_remain_unresolved(self):
        for category in ("math", "table", "figure"):
            row, artifacts, manifest, acceptance = fixture()
            manifest["residual_failures"] = [{"page": 2, "failure_class": category, "detail": "Remaining source fidelity discrepancy"}]
            result = self.result(row, artifacts, manifest, acceptance)
            self.assertEqual(result["status"], "unresolved")
            self.assertEqual(result["unresolved"], manifest["residual_failures"])

    def test_page_omission_reordering_extents_quotes_and_blank_pages_reject(self):
        mutations = [lambda m: m["pages"].pop(), lambda m: m["pages"].reverse(), lambda m: m["pages"][1].update(start=0), lambda m: m["pages"][1].update(end=10**6),
                     lambda m: m["pages"][0]["quotations"][0].update(text="wrong quote"), lambda m: m["pages"][0]["quotations"][0].update(start=True), lambda m: m["pages"][0].update(quotations=[])]
        for mutate in mutations:
            row, artifacts, manifest, acceptance = fixture()
            mutate(manifest)
            self.assertRaises(DeliverableError, self.result, row, artifacts, manifest, acceptance)
        self.assertRaisesRegex(DeliverableError, "saved page text", self.result, *fixture(blank=True))

    def test_unsupported_shapes_self_review_scope_and_abstract_promotions_reject(self):
        changes = [lambda m, a: m.update(schema_version="2.0.0"), lambda m, a: m.update(normalization="allow all"),
                   lambda m, a: a.update(reviewer="SYNTHETIC-PRODUCER"), lambda m, a: a.update(scope="scientific-claims"),
                   lambda m, a: a.update(decision="PASS"), lambda m, a: m["coverage"].update(order=1)]
        for change in changes:
            row, artifacts, manifest, acceptance = fixture()
            change(manifest, acceptance)
            self.assertRaises(DeliverableError, self.result, row, artifacts, manifest, acceptance)
        row, artifacts, manifest, acceptance = fixture()
        row["reading"]["evidence_level"] = "abstract"
        self.assertRaisesRegex(DeliverableError, "full extracted", self.result, row, artifacts, manifest, acceptance)

    def test_duplicate_json_and_missing_external_acceptance_reject(self):
        row, artifacts, manifest, acceptance = fixture()
        seal(row, artifacts, manifest, acceptance)
        raw = b'{"kind":"a","kind":"b"}'
        artifacts["evidence/acceptance.json"] = raw
        row["body_review"]["acceptance_sha256"] = sha(raw)
        self.assertRaisesRegex(DeliverableError, "duplicate JSON", verify_body_review, row, artifacts, sha(raw))
        self.assertRaises(DeliverableError, verify_body_review, row, artifacts, None)

    def test_discrepancy_requires_exact_individually_reviewed_extent_and_image(self):
        row, artifacts, manifest, acceptance = fixture()
        page = manifest["pages"][1]
        artifacts["pages/2.txt"] = b"Words; in order."
        page["reader_text"]["sha256"] = sha(artifacts["pages/2.txt"])
        page["comparison"] = "discrepancy"
        image = {"path": "pages/discrepancy.png", "sha256": sha(b"synthetic image")}
        artifacts[image["path"]] = b"synthetic image"
        extent = {"page": 2, "start": page["start"] + 5, "end": page["start"] + 6, "reader_start": 5, "reader_end": 6, "saved_text_sha256": sha(b","), "reader_text_sha256": sha(b";")}
        evidence = dict(extent, kind="PDFPageDiscrepancyEvidence", schema_version="1.0.0", id="d1", binding=manifest["binding"], image_sha256=image["sha256"], failure_class="text")
        artifacts["evidence/discrepancy.json"] = canonical(evidence)
        proof = {"path": "evidence/discrepancy.json", "sha256": sha(canonical(evidence))}
        manifest["discrepancies"] = [dict(extent, id="d1", image=image, evidence=proof, failure_class="text")]
        acceptance["discrepancy_reviews"] = [dict(extent, id="d1", reviewer=acceptance["reviewer"], decision="equivalent",
                                                rationale="Synthetic independently reviewed punctuation", image_sha256=image["sha256"], evidence_sha256=proof["sha256"])]
        self.assertEqual(self.result(row, artifacts, manifest, acceptance)["status"], "verified-body-text")
        acceptance["discrepancy_reviews"][0]["decision"] = "unresolved"
        self.assertEqual(self.result(row, artifacts, manifest, acceptance)["status"], "unresolved")
        for key in ("start", "image_sha256", "evidence_sha256", "reviewer"):
            changed = deepcopy(acceptance)
            changed["discrepancy_reviews"][0][key] = "wrong"
            with self.subTest(key=key):
                self.assertRaises(DeliverableError, self.result, row, artifacts, manifest, changed)
        acceptance["discrepancy_reviews"] = []
        self.assertRaises(DeliverableError, self.result, row, artifacts, manifest, acceptance)

    def test_geometry_fallback_requires_bound_cover_evidence(self):
        row, artifacts, manifest, acceptance = fixture(geometry=True)
        self.assertRaisesRegex(DeliverableError, "cover geometry", self.result, row, artifacts, manifest, acceptance)
        artifacts["pages/cover.png"] = b"synthetic cover image"
        image = {"path": "pages/cover.png", "sha256": sha(artifacts["pages/cover.png"])}
        evidence = {"kind": "PDFCoverGeometryReviewEvidence", "schema_version": "1.0.0", "binding": manifest["binding"], "page": 1, "image_sha256": image["sha256"], "diagnostics_sha256": sha(canonical(row["reading"]["diagnostics"]))}
        artifacts["evidence/cover.json"] = canonical(evidence)
        manifest["cover_geometry_review"] = {"page": 1, "image": image,
                                              "evidence": {"path": "evidence/cover.json", "sha256": sha(canonical(evidence))}}
        for decision, status in (("reviewed", "verified-body-text"), ("unresolved", "unresolved")):
            acceptance["cover_geometry_decision"] = decision
            self.assertEqual(self.result(row, artifacts, manifest, acceptance)["status"], status)
        evidence["diagnostics_sha256"] = sha(b"stale diagnostics")
        artifacts["evidence/cover.json"] = canonical(evidence)
        manifest["cover_geometry_review"]["evidence"]["sha256"] = sha(canonical(evidence))
        self.assertRaises(DeliverableError, self.result, row, artifacts, manifest, acceptance)


if __name__ == "__main__":
    unittest.main()

"""Pure synthetic comparisons; exact quotes do not establish scientific truth."""

from copy import deepcopy
import unittest
from research_workspace_native.project_coverage_analysis import (
    coverage_context,
    coverage_instructions,
    validate_coverage,
)
from research_workspace_native.project_full_analysis import full_analysis_draft
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
from test_project_full_analysis import fixture
from test_project_semantic_analysis import proposal


def case():
    snapshot = fixture()
    reading = snapshot["reading_input"]
    value = proposal(reading["full_source"])
    text = "Synthetic Rain Study\nAlice Example\n2024\n10.1234/synthetic\nPreprint v2\nRain changes runoff."
    raw = text.encode()
    source = reading["full_source"]["sources"][0]
    source.update(text=text, text_bytes=len(raw), text_sha256=sha(raw))
    reading["saved_reading"]["sources"][0].update(
        text_bytes=len(raw), text_sha256=sha(raw)
    )
    reading["saved_reading"]["discovery"] = dict(
        record=dict(
            title="Synthetic Rain Study",
            authors=["Alice Example"],
            year=2024,
            doi="10.1234/synthetic",
            version="Preprint v2",
        )
    )
    value["screening"]["decision"] = "include"
    values = [
        "Synthetic Rain Study",
        "Alice Example",
        "2024",
        "10.1234/synthetic",
        "Preprint v2",
    ]
    fields = ["title", "authors", "year", "identifier", "version"]
    value["reading"]["evidence"] = []
    value["claims"] = []
    for i, (field, quote) in enumerate(zip(fields, values)):
        start = raw.index(quote.encode())
        value["reading"]["evidence"].append(
            dict(
                source_id=source["source_id"],
                text_sha256=source["text_sha256"],
                start_byte=start,
                end_byte=start + len(quote.encode()),
                quote=quote,
                claim_id=None,
            )
        )
        value["claims"].append(
            dict(
                claim_key="identity-" + field,
                claim_text="The synthetic primary text reports this " + field + ".",
                relation="supports",
                evidence_index=i,
                section="Synthetic front matter",
                assessment=dict(
                    reason_code="synthetic-field-match",
                    rationale="A field-specific synthetic quote matches the supplied citation field; scientific relevance remains unassessed.",
                ),
            )
        )
    quote = "Rain changes runoff."
    start = raw.index(quote.encode())
    value["reading"]["evidence"].append(
        dict(
            source_id=source["source_id"],
            text_sha256=source["text_sha256"],
            start_byte=start,
            end_byte=start + len(quote.encode()),
            quote=quote,
            claim_id=None,
        )
    )
    value["claims"].append(
        dict(
            claim_key="topic-rain",
            claim_text="The synthetic result describes a rain/runoff process.",
            relation="supports",
            evidence_index=5,
            section="Synthetic result",
            assessment=dict(
                reason_code="synthetic-topical-link",
                rationale="The quoted synthetic rain/runoff result addresses the rain-process cluster; no real scientific effect is asserted.",
            ),
        )
    )
    checked = full_analysis_draft(canonical(value), snapshot)
    context = coverage_context(
        reading,
        [dict(cluster_id="compiled-rain", title="Rain processes")],
        candidate_identity_status="unverified",
    )
    coverage = dict(
        context_sha256=sha(canonical(context)),
        identity_status="verified",
        identity_comparisons={
            field: dict(
                status="match",
                observed=deepcopy(context["expected_identity"][field]),
                claim_key="identity-" + field,
                rationale="The selected primary quote states this synthetic field.",
            )
            for field in fields
        },
        cluster_claim_keys={"compiled-rain": "topic-rain"},
        closest=True,
        rationale="Synthetic schema fixture only; relevance and independent science remain unassessed.",
    )
    return snapshot, checked, context, coverage


class CoverageAnalysisTests(unittest.TestCase):
    def validate(self, parts):
        snapshot, proposal, context, coverage = parts
        return validate_coverage(
            coverage, context, proposal, snapshot["reading_input"]["full_source"]
        )

    def test_distinct_field_quotes_and_compiled_clusters_remain_proposals(self):
        parts = case()
        self.assertEqual(self.validate(parts), parts[3])
        self.assertNotIn("scientific_acceptance", self.validate(parts))
        prompt = coverage_instructions(
            parts[2], parts[0]["reading_input"]["full_source"]
        )
        self.assertIn("Missing record.version stays unknown", prompt)
        self.assertIn("compiled-rain", prompt)
        self.assertNotIn("need-method", prompt)

    def test_missing_publication_version_is_unknown_not_internal_version(self):
        parts = case()
        context, cover = parts[2:]
        context["expected_identity"]["version"] = None
        cover["context_sha256"] = sha(canonical(context))
        with self.assertRaises(SessionApiError):
            self.validate(parts)
        cover["identity_comparisons"]["version"] = dict(
            status="unknown",
            observed=None,
            claim_key=None,
            rationale="No publication version is recorded; the internal version binding is not a publication label.",
        )
        cover.update(identity_status="unverifiable", closest=False)
        self.assertEqual(self.validate(parts)["identity_status"], "unverifiable")

    def test_arbitrary_quotes_or_shared_claim_cannot_verify_identity(self):
        for mutation in ("quote", "shared", "relation", "observed"):
            parts = case()
            proposal, cover = parts[1], parts[3]
            if mutation == "quote":
                proposal["claims"][0]["evidence_index"] = 1
            elif mutation == "shared":
                cover["identity_comparisons"]["year"]["claim_key"] = "identity-title"
            elif mutation == "relation":
                proposal["claims"][0]["relation"] = "partial"
            else:
                cover["identity_comparisons"]["year"]["observed"] = 2025
            with self.subTest(mutation=mutation), self.assertRaises(SessionApiError):
                self.validate(parts)

    def test_conflict_cannot_be_promoted_or_marked_closest(self):
        parts = case()
        parts[2]["candidate_identity_status"] = "conflict"
        parts[3]["context_sha256"] = sha(canonical(parts[2]))
        with self.assertRaises(SessionApiError):
            self.validate(parts)
        parts[3].update(identity_status="conflict", closest=False)
        self.assertEqual(self.validate(parts)["identity_status"], "conflict")

    def test_foreign_need_ids_missing_mapping_and_extra_authority_refused(self):
        for mutation in ("foreign", "empty", "authority", "hash", "identity-as-topic"):
            parts = case()
            cover = parts[3]
            if mutation == "foreign":
                cover["cluster_claim_keys"] = {"need-method": "identity-title"}
            elif mutation == "empty":
                cover["cluster_claim_keys"] = {}
            elif mutation == "authority":
                cover["scientific_acceptance"] = True
            elif mutation == "identity-as-topic":
                cover["cluster_claim_keys"] = {"compiled-rain": "identity-title"}
            else:
                cover["context_sha256"] = "0" * 64
            with self.subTest(mutation=mutation), self.assertRaises(SessionApiError):
                self.validate(parts)

    def test_empty_saved_author_list_remains_unknown(self):
        snapshot, proposal, _, cover = case()
        reading = snapshot["reading_input"]
        reading["saved_reading"]["discovery"]["record"]["authors"] = []
        context = coverage_context(
            reading,
            [dict(cluster_id="compiled-rain", title="Rain processes")],
            candidate_identity_status="unverified",
        )
        self.assertIsNone(context["expected_identity"]["authors"])
        self.assertEqual(reading["saved_reading"]["discovery"]["record"]["authors"], [])
        cover["context_sha256"] = sha(canonical(context))
        cover["identity_comparisons"]["authors"] = dict(
            status="unknown",
            observed=None,
            claim_key=None,
            rationale="The saved discovery has no authors; readability does not identify them.",
        )
        cover.update(identity_status="unverifiable", closest=False)
        self.assertEqual(
            self.validate((snapshot, proposal, context, cover))["identity_status"],
            "unverifiable",
        )

    def test_field_conflict_requires_distinct_bound_observation(self):
        parts = case()
        parts[3]["identity_comparisons"]["year"].update(
            status="conflict", claim_key=None
        )
        parts[3].update(identity_status="conflict", closest=False)
        with self.assertRaises(SessionApiError):
            self.validate(parts)

    def test_actual_changed_field_quote_stays_conflict(self):
        parts = case()
        parts[2]["expected_identity"]["year"] = 2025
        parts[3]["context_sha256"] = sha(canonical(parts[2]))
        parts[3]["identity_comparisons"]["year"].update(
            status="conflict", observed=2024
        )
        parts[3].update(identity_status="conflict", closest=False)
        self.assertEqual(self.validate(parts)["identity_status"], "conflict")

    def test_boolean_year_and_rehashed_wrong_binding_are_refused(self):
        for mutation in ("year", "binding", "source"):
            parts = case()
            if mutation == "year":
                parts[2]["expected_identity"]["year"] = True
            elif mutation == "binding":
                parts[2]["binding"]["version_id"] = "foreign"
            else:
                parts[0]["reading_input"]["full_source"]["sources"][0]["text"] += (
                    " tampered"
                )
            parts[3]["context_sha256"] = sha(canonical(parts[2]))
            with self.subTest(mutation=mutation), self.assertRaises(SessionApiError):
                self.validate(parts)

    def test_crossed_identity_source_and_evidence_refused(self):
        for mutation in [
            "work_id",
            "version_id",
            "full_source_sha256",
            "source_hash",
            "source_id",
            "span",
        ]:
            parts = case()
            proposal = parts[1]
            if mutation in ["work_id", "version_id"]:
                proposal[mutation] = "foreign"
            elif mutation == "full_source_sha256":
                proposal[mutation] = "0" * 64
            elif mutation == "source_hash":
                proposal["reading"]["evidence"][0]["text_sha256"] = "0" * 64
            elif mutation == "source_id":
                proposal["reading"]["evidence"][0]["source_id"] = "foreign"
            else:
                proposal["reading"]["evidence"][0]["start_byte"] += 1
            with self.subTest(mutation=mutation), self.assertRaises(SessionApiError):
                self.validate(parts)

    def test_malformed_proposal_refused_with_typed_error(self):
        for mutation in ["none", "claims", "index"]:
            parts = list(case())
            if mutation == "none":
                parts[1] = None
            elif mutation == "claims":
                del parts[1]["claims"]
            else:
                parts[1]["claims"][0]["evidence_index"] = 9999
            with self.subTest(mutation=mutation), self.assertRaises(SessionApiError):
                self.validate(parts)

    def test_malformed_discovery_refused_with_typed_error(self):
        for discovery in [None, [], 3]:
            snapshot = case()[0]
            reading = snapshot["reading_input"]
            reading["saved_reading"]["discovery"] = discovery
            with self.subTest(discovery=discovery), self.assertRaises(SessionApiError):
                coverage_context(
                    reading,
                    [dict(cluster_id="compiled-rain", title="Rain processes")],
                    candidate_identity_status="unverified",
                )

    def test_missing_or_invalid_screening_is_typed_refusal(self):
        for mutation in ("missing", "none", "type", "value"):
            parts = case()
            proposal = parts[1]
            if mutation == "missing":
                del proposal["screening"]
            elif mutation == "none":
                proposal["screening"] = None
            elif mutation == "type":
                proposal["screening"]["decision"] = []
            else:
                proposal["screening"]["decision"] = "accepted"
            with self.subTest(mutation=mutation), self.assertRaises(SessionApiError):
                self.validate(parts)


if __name__ == "__main__":
    unittest.main()

"""New authored reviews survive the existing delivery and authenticated API."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from io import BytesIO
import zipfile

from test_original_record_recovery import recovery_case
from research_workspace.delivery_review import delivery_review_files
from research_workspace.original_record_recovery import attach_original_records
from research_workspace.projection import validate_index
from stage1_deliverable.common import DeliverableError, canonical, sha


def review_case(root, mutation=None):
    index, _ = recovery_case(root)
    source = index["sources"][0]
    source["receipt"]["raw_sha256"] = "a" * 64
    claim = index["claims"][0]
    spec = json.loads((root / "recovery.json").read_bytes())
    spec["input_canonical_sha256"] = sha(canonical(index))
    common = dict(
        **{k: claim[k] for k in ("work_id", "version_id", "source_id")},
        source_sha256=source["receipt"]["extracted_text_sha256"],
        raw_source_sha256="a" * 64,
        reviewer=dict(type="ai", identity="synthetic reviewer", authenticated=False),
        reviewed_at="2026-10-21T03:00:00Z",
        not_historical=True,
        input_canonical_sha256=spec["input_canonical_sha256"],
        reason_code="direct-saved-evidence",
        rationale="The exact saved source reports this statement within its observed setting.",
        evidence=[
            dict(
                start=8,
                end=27,
                quote=claim["quote"],
                locator="characters8:27",
                stance="support",
            )
        ],
    )
    review = dict(
        **common,
        record_kind="claim-support-review",
        claim_id=claim["claim_id"],
        original_claim_sha256=sha(canonical(claim)),
        relation="partial",
        claim_type="paper-claim",
        scope_limit="The saved source supports only its own observed case.",
        revised_claim="The source reports the saved exact passage for this case.",
        supporting_subclaims=["Source-reported statement"],
        unsupported_subclaims=["Broader generalization"],
    )
    if mutation:
        review.update(mutation)
    (root / "new.json").write_bytes(
        canonical(
            dict(
                claim=review,
                screening=dict(
                    **common,
                    record_kind="work-screening-review",
                    decision="include",
                    need_ids=["synthetic-need"],
                    roles=["comparison"],
                    limitations="A source-bound comparison, not evidence of broad generalization.",
                ),
            )
        )
    )
    spec["claims"][0]["new_assessment"] = dict(path="new.json", pointer="/claim")
    spec["works"][0]["new_screening_review"] = dict(
        path="new.json", pointer="/screening"
    )
    (root / "recovery.json").write_bytes(canonical(spec))
    manifest = json.loads((root / "manifest.json").read_bytes())
    for name in ("recovery.json", "new.json"):
        manifest["files"][name] = sha((root / name).read_bytes())
    raw = canonical(manifest)
    (root / "manifest.json").write_bytes(raw)
    return index, sha(raw)


class SavedSourceReassessmentTests(unittest.TestCase):
    def test_prior_review_cannot_reuse_same_id_from_another_source(self):
        for mutation in (
            {},
            {"source_id": "other-source"},
            {"original_claim_sha256": "b" * 64},
            {"relation": "context"},
        ):
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory(
                    dir=Path(tempfile.gettempdir()).resolve()
                ) as folder,
            ):
                root = Path(folder)
                index, _ = review_case(root)
                new = json.loads((root / "new.json").read_bytes())
                prior = dict(new["claim"], **mutation)
                prior_raw = canonical(dict(claim=prior))
                (root / "previous-review.json").write_bytes(prior_raw)
                new["claim"]["prior_review"] = dict(
                    portable_path="previous-review.json",
                    pointer="/claim",
                    sha256=sha(prior_raw),
                    relation="partial",
                )
                (root / "new.json").write_bytes(canonical(new))
                spec = json.loads((root / "recovery.json").read_bytes())
                spec["new_review_projection_version"] = "1.1.0"
                (root / "recovery.json").write_bytes(canonical(spec))
                manifest = json.loads((root / "manifest.json").read_bytes())
                for name in ("previous-review.json", "new.json", "recovery.json"):
                    manifest["files"][name] = sha((root / name).read_bytes())
                raw = canonical(manifest)
                (root / "manifest.json").write_bytes(raw)
                if mutation:
                    with self.assertRaisesRegex(
                        DeliverableError, "prior review binding differs"
                    ):
                        attach_original_records(index, folder, sha(raw))
                else:
                    attached = attach_original_records(index, folder, sha(raw))
                    self.assertEqual(
                        attached["original_record_recovery"]["payload"]["claims"][0][
                            "new_assessment"
                        ]["previous_review"]["value"],
                        prior,
                    )

    def test_claim_report_heading_cannot_inject_html_or_new_heading(self):
        from research_workspace.reassessment_exports import claim_reports

        files = claim_reports(
            [dict(claim_id="<img src=x onerror=alert(1)>\n# injected")], b"{}"
        ).copy()
        report = files["literature/claim_assessments.md"].decode()
        self.assertIn("## &lt;img src=x onerror=alert(1)&gt; # injected", report)
        self.assertNotIn("<img", report)
        self.assertNotIn("\n# injected", report)

    def test_candidate_block_work_and_original_receipt_cannot_be_swapped(self):
        from research_workspace.candidate_reassessment import validate_candidates

        text = "A (https://example.org/a)\nB (https://example.org/b)\n"
        digest = sha(text.encode())
        observations = [
            dict(
                observation_ref=str(n),
                batch_ref="batch",
                raw_header_line=n + 1,
                title_observed=title,
                url_observed="https://example.org/" + title.lower(),
                saved_receipt_ref=dict(sha256=digest),
            )
            for n, title in enumerate("AB")
        ]
        index = dict(
            papers=[
                dict(work_id=t, url="https://example.org/" + t.lower()) for t in "AB"
            ],
            sources=[],
        )
        rows = [
            dict(
                **{
                    k: o[k]
                    for k in ("observation_ref", "title_observed", "url_observed")
                },
                original_observation_sha256=sha(canonical(o)),
                decision="include",
                linked_work_id=t,
                rationale="This saved result is identified by the exact source URL.",
                reason_code="same-source",
                saved_evidence=dict(
                    batch_ref="batch",
                    source_sha256=digest,
                    start=n * len(text.splitlines(keepends=True)[0]),
                    end=(n + 1) * len(text.splitlines(keepends=True)[0]),
                    quote=text[
                        n * len(text.splitlines(keepends=True)[0]) : (n + 1)
                        * len(text.splitlines(keepends=True)[0])
                    ],
                ),
            )
            for n, (o, t) in enumerate(zip(observations, "AB"))
        ]
        value = dict(
            kind="NewSavedCandidateScreening",
            scope="saved-observations-only",
            not_historical=True,
            input_canonical_sha256="input",
            reviewed_at="2026-10-21T03:00:00Z",
            reviewer=dict(type="ai", identity="synthetic", authenticated=False),
            observations_ref="observations",
            captures=dict(batch="capture"),
            rows=rows,
        )
        proof = dict(
            observations=dict(value=observations),
            capture=dict(value=text, source_sha256=digest),
        )
        validate_candidates(dict(value=value), proof.__getitem__, index, "input")
        for field in ("block", "work", "receipt"):
            changed = deepcopy(value)
            if field == "block":
                changed["rows"][0]["saved_evidence"] = deepcopy(
                    rows[1]["saved_evidence"]
                )
            elif field == "work":
                changed["rows"][0]["linked_work_id"] = "B"
            else:
                changed["rows"][0]["saved_evidence"]["source_sha256"] = "wrong"
            with self.assertRaises(DeliverableError):
                validate_candidates(
                    dict(value=changed), proof.__getitem__, index, "input"
                )

    def test_complete_bundle_preserves_old_and_new_and_export_replays(self):
        with tempfile.TemporaryDirectory(
            dir=Path(tempfile.gettempdir()).resolve()
        ) as folder:
            index, pin = review_case(Path(folder))
            original = deepcopy(index)
            attached = attach_original_records(index, folder, pin)
            validate_index(attached)
            files = delivery_review_files(attached)
            self.assertEqual(
                files, delivery_review_files(json.loads(canonical(attached)))
            )
            row = json.loads(files["literature/claim_verification.json"])["rows"][0]
            self.assertEqual(
                (row["relation"], row["current_relation"]), ("unverified", "partial")
            )
            self.assertEqual(row["historical_reason_state"], "recovered-record")
            self.assertEqual(row["reason_state"], "new-source-review")
            self.assertIn(
                b"Broader generalization", files["literature/claim_assessments.csv"]
            )
            self.assertIn(
                b"Broader generalization", files["literature/claim_assessments.md"]
            )
            with zipfile.ZipFile(
                BytesIO(files["literature/claim_assessments.xlsx"])
            ) as workbook:
                self.assertIn(
                    b"Broader generalization", workbook.read("xl/worksheets/sheet1.xml")
                )
            screening = json.loads(files["literature/academic_screening.json"])
            self.assertEqual(
                screening["rows"][0]["decision_scope"], "new-saved-source-review"
            )
            self.assertEqual(index, original)
            attached["original_record_recovery"]["payload"]["claims"][0][
                "new_assessment"
            ]["value"]["relation"] = "supports"
            attachment = attached["original_record_recovery"]
            attachment["payload_sha256"] = sha(canonical(attachment["payload"]))
            with self.assertRaises(DeliverableError):
                validate_index(attached)

    def test_wrong_claim_source_fake_authentication_and_false_full_support_reject(self):
        for mutation in (
            dict(original_claim_sha256="b" * 64),
            dict(source_sha256="b" * 64),
            dict(reviewer=dict(type="human", identity="invented", authenticated=True)),
            dict(relation="supports"),
            dict(revised_claim=None),
        ):
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory(
                    dir=Path(tempfile.gettempdir()).resolve()
                ) as folder,
            ):
                index, pin = review_case(Path(folder), mutation)
                with self.assertRaises(DeliverableError):
                    attach_original_records(index, folder, pin)

    def test_existing_authenticated_http_exports_new_review_and_csv(self):
        from test_research_workspace_harness_host import HarnessHostTests

        with tempfile.TemporaryDirectory(
            dir=Path(tempfile.gettempdir()).resolve()
        ) as folder:
            index, pin = review_case(Path(folder))
            attached = attach_original_records(index, folder, pin)
            payload = dict(
                index=attached, index_sha256=sha(canonical(attached)), note_paths=[]
            )
            case = HarnessHostTests(
                "test_exports_bearer_fixed_names_exact_hash_and_changed_file_rejected"
            )
            with patch(
                "test_research_workspace_harness_host.payload", return_value=payload
            ):
                case.setUp()
            try:
                status, _, raw = case.post(case.request("export-selection"))
                self.assertEqual(status, 200)
                exported = json.loads(raw)
                self.assertEqual(exported["outcome"], "succeeded", exported)
                item = next(
                    a
                    for a in exported["artifacts"]
                    if a["name"] == "literature/claim_assessments.csv"
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
                self.assertIn(b"new-source-review", raw)
            finally:
                case.doCleanups()

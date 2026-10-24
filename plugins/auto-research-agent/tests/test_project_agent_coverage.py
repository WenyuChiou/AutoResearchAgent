"""Saved analysis1.1 coverage adoption through real queue, Core, and SQLite."""

from contextlib import contextmanager
from copy import deepcopy
import unittest
from unittest.mock import patch

from analysis_run_fixture import analysis_proposal, analysis_run_fixture
from research_workspace_native.project_agent_analysis import (
    ProjectStage1AnalysisService,
)
from research_workspace_native.project_agent_coverage import (
    ProjectAgentCoverageService,
)
from research_workspace_native.project_model import _output_ref
from research_workspace_native.session_api import SessionApiError
from stage1_coverage.run import CoverageLedger
from stage1_deliverable.common import canonical, sha
from stage1_ledger.validation import validate_run
from test_workspace_project_intake import bound_body


IDENTITY_FIELDS = ("title", "authors", "year", "identifier", "version")


def _identity_text(value):
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return [value["value"]]
    return [str(value)]


def _exact_observation(text, value):
    if value is None:
        return None
    parts = _identity_text(value)
    starts = [text.find(part) for part in parts]
    if any(start < 0 for start in starts):
        return None
    start = min(starts)
    end = max(start + len(part) for start, part in zip(starts, parts))
    return start, end, text[start:end]


def coverage_proposal(context):
    """Build an honest 1.1 proposal only from the supplied saved snapshot."""
    snapshot = context["saved_reading"]
    companion = snapshot["coverage_context"]
    proposal = analysis_proposal(context)
    proposal["schema_version"] = "1.1.0"
    proposal["screening"].update(
        decision="include",
        reason_code="authored-fixture-coverage-review",
        rationale="Include this authored fixture for synthetic coverage plumbing; scientific relevance remains Unknown.",
    )
    source = snapshot["reading_input"]["full_source"]["sources"][0]
    text = source["text"]
    encoded = text.encode("utf8")
    evidence = []
    claims = []
    comparisons = {}
    matched = []

    def add_claim(key, claim_text, relation, start, end, quote, reason):
        evidence.append(
            dict(
                source_id=source["source_id"],
                text_sha256=source["text_sha256"],
                start_byte=len(text[:start].encode("utf8")),
                end_byte=len(text[:end].encode("utf8")),
                quote=quote,
                claim_id=None,
            )
        )
        claims.append(
            dict(
                claim_key=key,
                claim_text=claim_text,
                relation=relation,
                evidence_index=len(evidence) - 1,
                section="Authored synthetic fixture",
                assessment=dict(
                    reason_code=reason,
                    rationale="The exact authored fixture passage is retained; scientific applicability remains Unknown.",
                ),
            )
        )

    for field in IDENTITY_FIELDS:
        expected = companion["expected_identity"][field]
        observed = _exact_observation(text, expected)
        if observed is None:
            comparisons[field] = dict(
                status="unknown",
                observed=None,
                claim_key=None,
                rationale=f"The authored source does not establish the expected {field}; it remains Unknown.",
            )
            continue
        key = "identity-" + field
        start, end, quote = observed
        add_claim(
            key,
            f"The authored fixture explicitly records its {field}.",
            "supports",
            start,
            end,
            quote,
            "authored-identity-field",
        )
        comparisons[field] = dict(
            status="match",
            observed=deepcopy(expected),
            claim_key=key,
            rationale=f"A distinct exact authored quote states the expected {field}.",
        )
        matched.append(field)

    topical = "Synthetic households alter consumption under a declared scenario."
    if topical not in text:
        topical = text[: min(64, len(text))]
    cursor = 0
    cluster_claim_keys = {}
    for index, cluster in enumerate(companion["clusters"]):
        start = text.find(topical, cursor)
        if start < 0:
            start = text.find(topical)
        end = start + len(topical)
        cursor = end
        key = f"topic-{index:02d}"
        add_claim(
            key,
            f"The authored fixture passage is recorded for proposed cluster {cluster['cluster_id']}; relevance remains Unknown.",
            "supports" if index == 0 else "partial",
            start,
            end,
            topical,
            "authored-topical-observation",
        )
        cluster_claim_keys[cluster["cluster_id"]] = key

    proposal["reading"]["evidence"] = evidence
    proposal["claims"] = claims
    conflict = companion["candidate_identity_status"] == "conflict"
    proposal["coverage"] = dict(
        context_sha256=sha(canonical(companion)),
        identity_status=(
            "conflict"
            if conflict
            else "verified"
            if len(matched) == len(IDENTITY_FIELDS)
            else "unverifiable"
        ),
        identity_comparisons=comparisons,
        cluster_claim_keys=cluster_claim_keys,
        closest=False,
        rationale="Authored synthetic coverage proposal only; absent identity fields and scientific relevance remain Unknown.",
    )
    if companion["expected_identity"]["version"] is None:
        assert comparisons["version"] == dict(
            status="unknown",
            observed=None,
            claim_key=None,
            rationale="The authored source does not establish the expected version; it remains Unknown.",
        )
    assert len(encoded) == source["text_bytes"]
    return proposal


@contextmanager
def agent_coverage_run():
    with analysis_run_fixture(
        proposal_builder=coverage_proposal, analysis_coverage=True
    ) as run:
        run.analysis = ProjectStage1AnalysisService(
            run.case.delivery.stage1, run.model, run.case.producer
        )
        run.coverage = ProjectAgentCoverageService(run.analysis)
        yield run


class AgentCoverageTests(unittest.TestCase):
    def _adopt(self, run, *, authority_checks=False):
        body, token = run.derived(
            "stage1-agent-analysis",
            "agent-adoption",
            dict(
                output_ref=_output_ref(run.job),
                draft_sha256=run.job["analysis_draft"]["sha256"],
            ),
        )
        before = len(run.ledger.events())
        if authority_checks:
            for credential, proof in (("bob-token", token), ("alice-token", {})):
                with self.assertRaises(SessionApiError):
                    run.analysis.adopt(
                        credential, run.ref, body, run_authorization=proof
                    )
            folder = run.model._runtime_folder("alice", run.ref, run.job)
            original = (folder / "output.txt").read_bytes()
            (folder / "output.txt").write_bytes(original + b" ")
            with self.assertRaises(SessionApiError):
                run.analysis.adopt(
                    "alice-token", run.ref, body, run_authorization=token
                )
            (folder / "output.txt").write_bytes(original)
            self.assertEqual(len(run.ledger.events()), before)
        result = run.analysis.adopt(
            "alice-token", run.ref, body, run_authorization=token
        )
        self.assertEqual(result["status"], "saved")
        self.assertTrue(
            all(v == "Unknown" for v in result["reading"]["classification"].values())
        )
        self.assertTrue(
            all(v == "Unknown" for v in result["reading"]["findings"].values())
        )
        return body, result

    def _review(self, run, adoption_body, adoption):
        body, token = run.derived(
            "stage1-agent-coverage",
            "agent-adoption",
            dict(
                adoption_key=adoption_body["key"],
                adoption_request_sha256=adoption["request_sha256"],
            ),
        )
        result = run.coverage.review(
            "alice-token", run.ref, body, run_authorization=token
        )
        return body, token, result

    def test_actual_saved_coverage_review_registry_replay_and_no_resend(self):
        with agent_coverage_run() as run:
            previous_review = deepcopy(
                run.ledger.coverage_state().evidence.reviews[run.work]
            )
            adoption_body, adoption = self._adopt(run, authority_checks=True)
            self.assertNotIn(run.work, run.ledger.coverage_state().evidence.current())
            review_body, review_token, review = self._review(
                run, adoption_body, adoption
            )
            event = run.ledger.event(review["event_id"], "CoverageWorkReview")
            self.assertEqual(event["assessor"], "agent:alice")
            self.assertEqual(event["replaces_event_id"], previous_review["event_id"])
            self.assertEqual(review["reading"]["review_event_id"], event["event_id"])
            self.assertEqual(event["identity_status"], "unverifiable")
            self.assertIsNone(event["identity_claims"]["version"])
            self.assertTrue(
                review["reading"]["classification"]
                == adoption["reading"]["classification"]
                and review["reading"]["findings"] == adoption["reading"]["findings"]
            )
            after_review = len(run.ledger.events())
            replay = run.coverage.review(
                "alice-token", run.ref, review_body, run_authorization=review_token
            )
            self.assertTrue(replay["replayed"])
            self.assertEqual(len(run.ledger.events()), after_review)
            register_body, register_token = run.derived(
                "stage1-agent-reading",
                "records",
                dict(
                    adoption_key=review_body["key"],
                    adoption_request_sha256=review["request_sha256"],
                    reading_sha256=review["reading_sha256"],
                ),
            )
            registered = run.coverage.register(
                "alice-token",
                run.ref,
                register_body,
                run_authorization=register_token,
            )
            payload = registered["registry_entry"]["payload"]
            self.assertEqual(payload, review["reading"])
            self.assertEqual(payload["review_event_id"], event["event_id"])
            self.assertEqual(
                run.coverage.register(
                    "alice-token",
                    run.ref,
                    register_body,
                    run_authorization=register_token,
                )["registry_entry"],
                registered["registry_entry"],
            )
            self.assertEqual(len(run.ledger.events()), after_review)
            self.assertEqual(len(run.calls), 1)
            self.assertEqual(
                run.model.read("alice-token", run.ref)["calls_reserved"], 1
            )
            self.assertTrue(validate_run(run.ledger.root)["valid"])

    def test_actual_review_append_then_raise_is_held_and_blocks_checkpoint(self):
        with agent_coverage_run() as run:
            adoption_body, adoption = self._adopt(run)
            body, token = run.derived(
                "stage1-agent-coverage",
                "agent-adoption",
                dict(
                    adoption_key=adoption_body["key"],
                    adoption_request_sha256=adoption["request_sha256"],
                ),
            )
            original_review = CoverageLedger.review_work

            def interrupted(owner, *args, **kwargs):
                original_review(owner, *args, **kwargs)
                raise SessionApiError("synthetic-after-observed-coverage-review")

            before = run.ledger.events()
            with (
                patch.object(CoverageLedger, "review_work", new=interrupted),
                self.assertRaises(SessionApiError),
            ):
                run.coverage.review(
                    "alice-token", run.ref, body, run_authorization=token
                )
            held = run.case.intake.action(
                "alice-token", body["key"], project_ref=run.ref
            )
            self.assertEqual(held["status"], "execution-unknown")
            self.assertEqual(held["failure_phase"], "core-write-outcome-unobserved")
            after = run.ledger.events()
            self.assertGreater(len(after), len(before))
            self.assertEqual(
                [row["payload"]["event_id"] for row in after[: len(before)]],
                [row["payload"]["event_id"] for row in before],
            )
            replay = run.coverage.review(
                "alice-token", run.ref, body, run_authorization=token
            )
            self.assertTrue(replay["replayed"])
            self.assertEqual(len(run.ledger.events()), len(after))
            with self.assertRaises(SessionApiError):
                run.case.delivery.stage1.checkpoint(
                    "alice-token",
                    run.ref,
                    {
                        **bound_body(
                            run.case.intake.read("alice-token", run.ref),
                            "held-coverage-checkpoint",
                        ),
                        "confirmed": True,
                        "ledger_state_sha256": run.ledger.state_hash(),
                    },
                )
            self.assertEqual(len(run.ledger.events()), len(after))
            self.assertEqual(len(run.calls), 1)


if __name__ == "__main__":
    unittest.main()

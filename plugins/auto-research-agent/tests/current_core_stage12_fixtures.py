"""Authored offline Core fixtures with genuinely checkpoint-generated handoffs.

Fixture review assertions exercise engineering contracts; they are not real
scientific, human, saved-source admission, or research-execution acceptance.
The existing SDK fixture parses authored HTTP responses without external I/O.
"""

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from test_project_stage1_records import SavedStage1RecordsTests
from test_workspace_project_intake import compile_body
from unittest.mock import patch
from stage1_coverage.evidence import IDENTITY_FIELDS
from stage1_deliverable.common import read_json, sha
from stage1_ledger.journal import canonical, decode
from stage1_ledger.validation import validate_run


def _compact_compile_body(view):
    """Author one coverage cluster through the real public brief compiler."""
    body = compile_body(view)
    body["request"]["proposal"]["clusters"] = body["request"]["proposal"]["clusters"][
        :1
    ]
    body["request"]["query_bindings"] = body["request"]["query_bindings"][:1]
    return body


@contextmanager
def _saved_single_source_case():
    case = SavedStage1RecordsTests()
    case.setUpClass()
    try:
        case.setUp()
        # Replace only authored test-request data, never a production method,
        # gate, state file, receipt or evidence validator.
        with patch(
            "test_project_stage1_delivery.compile_body",
            side_effect=_compact_compile_body,
        ):
            fixture = case.saved(checkpoint=False)
        fixture["pairs"] = [(fixture["records"], fixture["path"].parent)]
        source = fixture["records"]["sources"][0]
        result_path = fixture["path"].parent / source["result_path"]
        case.producer.register_source(
            fixture["ref"],
            source_id=source["source_id"],
            result_path=result_path,
            expected_result_sha256=sha(result_path.read_bytes()),
            access_note=source["access_note"],
            expected_ledger_state_sha256=fixture["ledger"].state_hash(),
        )
        yield case, fixture
    finally:
        case.doCleanups()
        case.tearDownClass()


def _empty_query(ledger, query):
    attempt = ledger.start(
        "backend",
        {"fixture": "authored-empty-response"},
        backend="openalex",
        parent_id=query,
    )
    raw = ledger.save_bytes(canonical([]), producer=attempt)
    empty = ledger.save_bytes(b"", producer=attempt)
    ledger.finish(
        attempt,
        outcome="success_empty",
        http_status=200,
        exit_code=0,
        stdout=raw,
        stderr=empty,
        records=raw,
    )
    completed = ledger.complete_query(query)
    ledger.extract()
    ledger.receipt(
        completed,
        truncated=False,
        note="Authored complete empty fixture response; no external search.",
    )


@contextmanager
def current_core_stage1_case(screened=False, *, metadata_observation=False):
    """Yield an eligible native Core package, retaining its actual identity.

    Core 1.2 is selected by the producer when an authored assessment is present;
    neither record schema nor checkpoint gate/handoff fields are assigned here.
    The query callback is a rejecting Mock provided by the existing fixture.
    No source-service or model callback is constructed or dispatched.
    """
    with _saved_single_source_case() as (case, fixture):
        ledger, ref = fixture["ledger"], fixture["ref"]
        original_history = deepcopy(
            [
                row
                for row in ledger.events()
                if row["payload"]["kind"] == "ClaimEvidence"
            ]
        )
        clusters = ledger.coverage_state().plan["proposal"]["clusters"]
        for index, (records, _) in enumerate(fixture["pairs"]):
            paper = records["papers"][0]
            old = ledger.event(paper["claim_ids"][0])
            discovery = ledger.candidates()[paper["work_id"]]["discoveries"][0]
            ledger.decide(
                paper["work_id"],
                "include",
                reason="authored-fixture-include",
                rationale="Synthetic engineering inclusion; not scientific acceptance.",
                evidence_refs=[discovery["source_ref"]],
            )
            verifier = {
                "actor": "authored-core-fixture",
                "actor_type": "agent",
                "method": "authored-offline-contract-assertion",
            }
            if metadata_observation:
                ledger.claim(
                    work_id=paper["work_id"],
                    version_id=paper["version_id"],
                    claim_text="Unknown: authored discovery-metadata context.",
                    relation="pending",
                    evidence_level="metadata",
                    locator=None,
                    source_ref=deepcopy(discovery["source_ref"]),
                    verifier=verifier,
                )
            for relation, level, located in (
                ("partial", "full_text", True),
                ("pending", "metadata", False),
                ("unclear", "unavailable", False),
                ("unverifiable", "full_text", True),
                ("context", "primary_data_or_table", True),
            ):
                assessment = (
                    {
                        "reason_code": "authored-fixture-unknown",
                        "rationale": "Unknown: an authored engineering assertion, not a scientific finding.",
                    }
                    if screened and index == 0 and relation == "pending"
                    else None
                )
                ledger.claim(
                    work_id=paper["work_id"],
                    version_id=paper["version_id"],
                    claim_text="Unknown: authored Core fixture " + relation,
                    relation=relation,
                    evidence_level=level,
                    locator=deepcopy(old["locator"]) if located else None,
                    source_ref=deepcopy(old["source_ref"]),
                    verifier=verifier,
                    assessment=assessment,
                )
            identities = {}
            for field in sorted(IDENTITY_FIELDS):
                identities[field] = ledger.claim(
                    work_id=paper["work_id"],
                    version_id=paper["version_id"],
                    claim_text="Authored fixture identity assertion for " + field,
                    relation="supports",
                    evidence_level="full_text",
                    locator=deepcopy(old["locator"]),
                    source_ref=deepcopy(old["source_ref"]),
                    verifier=verifier,
                )
            ledger.review_work(
                work_id=paper["work_id"],
                version_id=paper["version_id"],
                cluster_claims={
                    row["cluster_id"]: paper["claim_ids"][0] for row in clusters
                },
                identity_status="verified",
                identity_claims=identities,
                closest=True,
                assessor="authored-core-fixture",
                rationale="Explicit synthetic operational assertion; not real identity or scientific acceptance.",
            )
            for operation in ("references", "cited-by"):
                _empty_query(
                    ledger,
                    ledger.start_expansion(
                        operation,
                        paper["work_id"],
                        paper["version_id"],
                    ),
                )
        # The reused saved-source fixture completed its discovery query.
        # Add their real coverage receipts rather than replace their history.
        for row in ledger.events():
            payload = row["payload"]
            if (
                payload["kind"] == "QueryEvent"
                and payload["event_id"] not in ledger.coverage_state().receipts
            ):
                ledger.receipt(
                    payload["event_id"],
                    truncated=False,
                    note="Authored saved discovery response; no external search.",
                )
        rounds = []
        for number in range(3):
            if number:
                ledger.open_round()
            for planned in ledger.coverage_state().queries:
                _empty_query(ledger, ledger.start_planned(planned))
            rounds.append(ledger.close_round())
        report = validate_run(ledger.root)
        if not report["valid"]:
            raise AssertionError(report)
        checkpoint = ledger.checkpoint()
        if checkpoint["stage_result"]["next_allowed_action"] != "stop-sufficient":
            raise AssertionError(checkpoint["stage_result"])
        fixture["checkpoint"] = checkpoint
        handoff_ref = checkpoint["stage_result"]["outputs"][-1]
        handoff = decode(ledger.read_ref(handoff_ref), "authored checkpoint handoff")
        if not handoff["eligible_for_stage2"]:
            raise AssertionError(handoff)
        for records, _ in fixture["pairs"]:
            paper = records["papers"][0]
            reading = case.producer.derive_reading_payload(
                ref,
                paper["work_id"],
                classification=paper["classification"],
                findings=paper["findings"],
                roles=[],
                expected_ledger_state_sha256=ledger.state_hash(),
            )
            case.producer.register_reading(
                ref,
                reading=reading,
                expected_ledger_state_sha256=ledger.state_hash(),
            )
        offer = case.producer.produce_records(
            ref,
            expected_ledger_state_sha256=ledger.state_hash(),
            expected_checkpoint_event_id=checkpoint["event_id"],
        )
        # Read the saved public offer's physical artifact location; no state edit.
        saved_offer = case.delivery._context(ref)[1]["stage1_delivery_offers"][
            offer["offer_ref"]
        ]
        records_path = Path(saved_offer["records_path"])
        case.delivery.deliver("alice-token", ref, case.body(fixture, offer))
        binding = case.delivery.binding(ref)
        brief = case.intake.binding(ref)
        resources_path = case.fixture_root / "authored-resources.txt"
        resources_path.write_text(
            "Authored engineering fixture. One researcher; zero source/model execution authorized. "
            "No real feasibility or scientific acceptance is asserted.\n",
            encoding="utf-8",
        )
        yield {
            "case": case,
            "fixture": fixture,
            "project_ref": ref,
            "root": case.root,
            "ledger": ledger,
            "checkpoint": checkpoint,
            "report": report,
            "rounds": rounds,
            "handoff": handoff,
            "handoff_ref": handoff_ref,
            "binding": binding,
            "records_path": records_path,
            "records_sha256": sha(records_path.read_bytes()),
            "records": read_json(records_path),
            "original_core_history": original_history,
            "deliverable_dir": Path(binding["deliverable_dir"]),
            "manifest_sha256": binding["manifest_sha256"],
            "handoff_path": Path(binding["handoff_path"]),
            "handoff_sha256": binding["handoff_sha256"],
            "brief_path": Path(brief["brief_path"]),
            "brief_sha256": brief["brief_sha256"],
            "resources_path": resources_path,
            "resources_sha256": sha(resources_path.read_bytes()),
            "zero_callback_counts": {
                "query_runner": case.runner.call_count,
                "source_service": 0,
                "model": 0,
            },
        }

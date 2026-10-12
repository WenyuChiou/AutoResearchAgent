"""Core enum/nullable-locator adapters preserve saved history without promotion."""

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import json
import shutil
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from test_project_stage1_records import saved_stage1_case
from research_workspace.projection import project_package
from research_workspace.canonical_delivery import project_canonical_atlas
from research_workspace.view import write_workspace
from research_workspace.wiki import wiki_files
from research_workspace_native.project_stage1_delivery import _io_root, _records_match
from research_workspace_native.project_stage2 import _verified_inputs
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import (
    DeliverableError,
    canonical,
    inventory,
    read_json,
    sha,
    write_json,
    private_output,
)
from stage1_deliverable.core_records import artifact_path, read_artifacts
from stage1_deliverable.package import build
from stage1_deliverable.package import validate as validate_package
from stage1_deliverable.records import validate_records
from stage1_ledger.journal import canonical as journal_canonical, digest


@contextmanager
def core_case():
    with saved_stage1_case() as (case, fixture):
        ledger = fixture["ledger"]
        paper = fixture["records"]["papers"][0]
        old = ledger.event(paper["claim_ids"][0])
        old_history = [
            row for row in ledger.events() if row["payload"]["kind"] == "ClaimEvidence"
        ]
        for relation, level, located in (
            ("pending", "metadata", False),
            ("unclear", "unavailable", False),
            ("unverifiable", "full_text", True),
            ("context", "primary_data_or_table", True),
        ):
            ledger.claim(
                work_id=paper["work_id"],
                version_id=paper["version_id"],
                claim_text="Unknown: synthetic Core " + relation,
                relation=relation,
                evidence_level=level,
                locator=deepcopy(old["locator"]) if located else None,
                source_ref=deepcopy(old["source_ref"]),
                verifier=dict(
                    actor="fixture-human",
                    actor_type="human",
                    method="explicit-fixture-review",
                ),
            )
        candidate = ledger.candidates()[paper["work_id"]]
        discovery = candidate["discoveries"][0]
        ledger.claim(
            work_id=paper["work_id"],
            version_id=paper["version_id"],
            claim_text="Unknown: discovery metadata is not reading evidence.",
            relation="pending",
            evidence_level="metadata",
            locator=None,
            source_ref=deepcopy(discovery["source_ref"]),
            verifier=dict(
                actor="fixture-human",
                actor_type="human",
                method="explicit-fixture-review",
            ),
        )
        fixture["checkpoint"] = ledger.checkpoint()
        readings = []
        for records, _ in fixture["pairs"]:
            target = records["papers"][0]
            payload = case.producer.derive_reading_payload(
                fixture["ref"],
                target["work_id"],
                classification=target["classification"],
                findings=target["findings"],
                roles=[],
                expected_ledger_state_sha256=ledger.state_hash(),
            )
            case.producer.register_reading(
                fixture["ref"],
                reading=payload,
                expected_ledger_state_sha256=ledger.state_hash(),
            )
            readings.append(payload)
        yield case, fixture, old_history, readings


def produced(case, fixture, *, action_body=None):
    result = case.producer.produce_records(
        fixture["ref"],
        expected_ledger_state_sha256=fixture["ledger"].state_hash(),
        expected_checkpoint_event_id=fixture["checkpoint"]["event_id"],
        action_body=action_body,
    )
    offer = result["delivery_offer"] if action_body else result
    context = case.delivery._context(fixture["ref"])
    stored = context[1]["stage1_delivery_offers"][offer["offer_ref"]]
    return result, Path(stored["records_path"]), read_json(stored["records_path"])


def saved_request(case, fixture, key):
    row = case.intake.db.execute(
        "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
        (case.intake._principal("alice-token"), fixture["ref"], key),
    ).fetchone()
    return json.loads(row["receipt"])["request"]


class CoreRecordsTests(unittest.TestCase):
    def test_raw_core_credentials_outside_quote_are_refused_on_all_admission_paths(
        self,
    ):
        with core_case() as (case, fixture, _, _):
            _, records_path, original = produced(case, fixture)
            records = deepcopy(original)
            claim = next(row for row in records["claims"] if row["quote"] is not None)
            original_ref = deepcopy(claim["core_event"]["payload"]["source_ref"])
            artifact = next(
                item
                for item in records["core_artifacts"]
                if item["source_ref"] == original_ref
            )
            raw = (records_path.parent / artifact["artifact_path"]).read_bytes()
            raw += b"\nAuthorization: Bearer synthetic-credential-outside-quote\n"
            reference = dict(original_ref, sha256=sha(raw), producer="core-raw-fixture")
            artifact.update(
                source_ref=reference, artifact_path=artifact_path(reference)
            )
            (records_path.parent / artifact["artifact_path"]).write_bytes(raw)
            for row in records["core_claim_history"]:
                if row["payload"]["source_ref"] == original_ref:
                    row["payload"]["source_ref"] = deepcopy(reference)
                    row["event_sha256"] = digest(
                        journal_canonical(
                            {
                                key: value
                                for key, value in row.items()
                                if key != "event_sha256"
                            }
                        )
                    )
            history = {
                row["payload"]["event_id"]: row for row in records["core_claim_history"]
            }
            for row in records["claims"]:
                if row["core_event"]["payload"]["source_ref"] == original_ref:
                    row["source_id"] = None
                    row["core_event"] = deepcopy(history[row["claim_id"]])
            validate_records(records)
            self.assertEqual(
                raw.decode()[claim["start"] : claim["end"]], claim["quote"]
            )
            poisoned_path = records_path.parent / "raw-core-credential-records.json"
            write_json(poisoned_path, records)
            with self.subTest(admission="raw-reader"):
                with self.assertRaisesRegex(DeliverableError, "credential-like"):
                    read_artifacts(records, records_path.parent)
            with self.subTest(admission="build"):
                with self.assertRaisesRegex(DeliverableError, "credential-like"):
                    build(
                        poisoned_path,
                        case.fixture_root / "credential-build",
                        sha(poisoned_path.read_bytes()),
                    )
            # Construct a deliberately unsafe archive to exercise later admission.
            # Only this synthetic setup disables scanning; readers run unpatched.
            unsafe = case.fixture_root / "credential-validation"
            with patch("stage1_deliverable.sources.reject_secrets"):
                receipt = build(poisoned_path, unsafe, sha(poisoned_path.read_bytes()))
            with self.subTest(admission="validator"):
                with self.assertRaisesRegex(DeliverableError, "credential-like"):
                    validate_package(unsafe, receipt["manifest_sha256"])
            with self.subTest(admission="passive-canonical-reader"):
                with self.assertRaisesRegex(DeliverableError, "credential-like"):
                    project_canonical_atlas(
                        unsafe, "unsafe-core-fixture", receipt["manifest_sha256"]
                    )

    def test_complete_core_history_package_projection_and_wiki_without_promotion(self):
        with core_case() as (case, fixture, old_history, _):
            offer, path, records = produced(case, fixture)
            self.assertEqual(records["schema_version"], "1.1.0")
            self.assertEqual(
                records["core_claim_history"][: len(old_history)], old_history
            )
            self.assertEqual(
                records["core_claim_history"],
                [
                    row
                    for row in fixture["ledger"].events()
                    if row["payload"]["kind"] == "ClaimEvidence"
                ],
            )
            nulls = [row for row in records["claims"] if row["locator"] is None]
            self.assertEqual(len(nulls), 3)
            self.assertTrue(
                all(row["start"] is row["end"] is row["quote"] is None for row in nulls)
            )
            self.assertTrue(any(row["source_id"] is None for row in nulls))
            self.assertEqual(
                {row["relation"] for row in records["claims"]},
                {
                    "supports",
                    "partial",
                    "pending",
                    "unclear",
                    "unverifiable",
                    "context",
                },
            )
            self.assertTrue(
                {"full_text", "primary_data_or_table", "unavailable"}
                <= {row["evidence_level"] for row in records["claims"]}
            )
            read_artifacts(records, path.parent)
            saved = case.delivery.deliver(
                "alice-token", fixture["ref"], case.body(fixture, offer)
            )
            self.assertEqual(saved["status"], "saved")
            self.assertFalse(saved["stage1_complete"])
            self.assertFalse(saved["scientific_quality_scored"])
            package = Path(case.delivery.binding(fixture["ref"])["deliverable_dir"])
            self.assertEqual(
                validate_package(package, saved["manifest_sha256"])["status"], "passed"
            )
            presentation = _io_root(private_output(case.fixture_root / "presentation"))
            presentation.mkdir()
            shutil.copytree(package, presentation / "deliverable")
            readiness = dict(
                status="partial-review-only", stage2_execution_authorized=False
            )
            write_json(presentation / "stage2_readiness.json", readiness)
            files = inventory(presentation)
            write_json(
                presentation / "package_manifest.json",
                dict(
                    kind="Stage1PrivateDeliveryPackageManifest",
                    schema_version="1.0.0",
                    files={
                        name: dict(
                            sha256=digest, bytes=(presentation / name).stat().st_size
                        )
                        for name, digest in files.items()
                    },
                    stage2_readiness_sha256=sha(
                        (presentation / "stage2_readiness.json").read_bytes()
                    ),
                ),
            )
            index = project_package(
                presentation,
                "synthetic-core-format",
                sha((presentation / "package_manifest.json").read_bytes()),
            )
            self.assertEqual(index["schema_version"], "1.1.0")
            for field in ("claims", "core_claim_history", "core_artifacts"):
                self.assertEqual(index[field], records[field])
            self.assertEqual(index["readiness"], readiness)
            self.assertEqual(
                index["stage2_canonical_consumer"]["status"], "unconnected"
            )
            self.assertTrue(
                all(not stage["execution_enabled"] for stage in index["stages"])
            )
            self.assertEqual(
                [stage["stage"] for stage in index["stages"]], list(range(1, 7))
            )
            notes = wiki_files(index)
            self.assertIn(b"Original Core claim history", notes["wiki/README.md"])
            reference = (
                Path(__file__).resolve().parents[1] / "references/research-workspace"
            )
            output = case.fixture_root / "view"
            view = write_workspace(index, reference, output)
            self.assertEqual(view["index_sha256"], sha(canonical(index)))
            self.assertTrue((output / "index.html").is_file())
            case.runner.assert_not_called()

    def test_legacy_records_and_rendered_formats_remain_legacy(self):
        with saved_stage1_case() as (case, fixture):
            offer, _, records = produced(case, fixture)
            self.assertEqual(records["schema_version"], "1.0.0")
            self.assertNotIn("core_claim_history", records)
            self.assertTrue(all("core_event" not in row for row in records["claims"]))
            self.assertIs(validate_records(records), records)
            self.assertFalse(offer["eligible_for_stage2"])

    def test_rewritten_event_nullable_span_and_incomplete_history_refused(self):
        with core_case() as (case, fixture, _, _):
            _, path, records = produced(case, fixture)
            bad = deepcopy(records)
            bad["claims"][0]["core_event"]["payload"]["verifier"]["actor"] = "changed"
            with self.assertRaisesRegex(DeliverableError, "preserved Core event"):
                validate_records(bad)
            bad = deepcopy(records)
            row = next(row for row in bad["claims"] if row["locator"] is None)
            row["quote"] = "invented"
            with self.assertRaisesRegex(DeliverableError, "invented source span"):
                validate_records(bad)
            bad = deepcopy(records)
            bad["core_claim_history"].pop()
            with self.assertRaises(DeliverableError):
                validate_records(bad)
            bad = deepcopy(records)
            bad["claims"][0]["source_id"] = None
            with self.assertRaisesRegex(DeliverableError, "source association"):
                validate_records(bad)
            bad = deepcopy(records)
            bad["claims"][0]["core_event"]["payload"]["created_at"] = (
                "2025-01-01T00:00:00Z"
            )
            with self.assertRaises((DeliverableError, SessionApiError)):
                _records_match(bad, fixture["ledger"], path.parent)
            artifact = path.parent / records["core_artifacts"][0]["artifact_path"]
            artifact.write_bytes(artifact.read_bytes() + b"tampered")
            with self.assertRaisesRegex(DeliverableError, "archive bytes differ"):
                read_artifacts(records, path.parent)

    def test_human_registry_uses_original_request_hash_and_preserves_history(self):
        with saved_stage1_case() as (case, fixture):
            paper = fixture["records"]["papers"][0]
            reading = case.producer.derive_reading_payload(
                fixture["ref"],
                paper["work_id"],
                classification=paper["classification"],
                findings=paper["findings"],
                roles=[],
                expected_ledger_state_sha256=fixture["ledger"].state_hash(),
            )
            current = case.intake.read("alice-token", fixture["ref"])
            action = dict(
                key="human-reading",
                confirmed=True,
                ledger_state_sha256=fixture["ledger"].state_hash(),
                output_ref="synthetic-reading-output",
                draft_sha256="1" * 64,
                offer_ref="synthetic-reading-offer",
                offer_sha256="2" * 64,
                review={
                    key: reading[key] for key in ("classification", "findings", "roles")
                },
                **{
                    key: current[key]
                    for key in ("revision", "input_version", "brief_sha256")
                },
            )
            entry = case.producer.register_reading(
                fixture["ref"],
                reading=reading,
                expected_ledger_state_sha256=fixture["ledger"].state_hash(),
                action_body=action,
            )
            receipt = case.intake.action(
                "alice-token", action["key"], project_ref=fixture["ref"]
            )
            self.assertNotIn(
                "entry_sha256", saved_request(case, fixture, action["key"])
            )
            semantic = {
                key: value for key, value in action.items() if key != "revision"
            }
            self.assertEqual(
                receipt["request_sha256"],
                sha(canonical(dict(kind="stage1-reading-registry", body=semantic))),
            )
            self.assertEqual(receipt["registry_entry"], entry)
            self.assertIsNotNone(
                case.producer._entries(case.delivery._saved_context(fixture["ref"]))
            )
            same = case.producer.register_reading(
                fixture["ref"],
                reading=reading,
                expected_ledger_state_sha256=fixture["ledger"].state_hash(),
                action_body=action,
            )
            self.assertEqual(same, entry)
            with self.assertRaisesRegex(SessionApiError, "already-registered"):
                case.producer.register_reading(
                    fixture["ref"],
                    reading=reading,
                    expected_ledger_state_sha256=fixture["ledger"].state_hash(),
                    action_body=dict(
                        action,
                        key="fresh-reading",
                        revision=case.intake.read("alice-token", fixture["ref"])[
                            "revision"
                        ],
                    ),
                )

    def test_human_preparation_preserves_request_hash_deadline_and_no_rewrite(self):
        with core_case() as (case, fixture, _, _):
            current = case.intake.read("alice-token", fixture["ref"])
            action = dict(
                key="human-prepare",
                confirmed=True,
                ledger_state_sha256=fixture["ledger"].state_hash(),
                checkpoint_event_id=fixture["checkpoint"]["event_id"],
                **{
                    key: current[key]
                    for key in ("revision", "input_version", "brief_sha256")
                },
            )
            result, path, _ = produced(case, fixture, action_body=action)
            semantic = {
                key: value for key, value in action.items() if key != "revision"
            }
            self.assertEqual(
                result["request_sha256"],
                sha(canonical(dict(kind="stage1-produce-records", body=semantic))),
            )
            self.assertNotIn(
                "records_sha256", saved_request(case, fixture, action["key"])
            )
            before = path.read_bytes()
            with patch(
                "research_workspace_native.project_stage1_records.os.link",
                side_effect=AssertionError("repeated publication"),
            ):
                replay, replay_path, _ = produced(case, fixture, action_body=action)
                self.assertTrue(replay["replayed"])
                self.assertEqual(replay_path.read_bytes(), before)
            history = case.intake.history("alice-token", fixture["ref"])["actions"]

            def expired():
                raise TimeoutError("expired")

            with self.assertRaises(TimeoutError):
                case.producer.produce_records(
                    fixture["ref"],
                    expected_ledger_state_sha256=fixture["ledger"].state_hash(),
                    expected_checkpoint_event_id=fixture["checkpoint"]["event_id"],
                    action_body=dict(action, key="expired-preparation"),
                    check_current=expired,
                )
            self.assertEqual(
                case.intake.history("alice-token", fixture["ref"])["actions"], history
            )

    def test_stage2_explicitly_refuses_new_format_before_import(self):
        with core_case() as (case, fixture, _, _):
            _, _, records = produced(case, fixture)
            folder = case.fixture_root / "unsupported-consumer"
            folder.mkdir()
            manifest = folder / "provenance_manifest.json"
            write_json(
                manifest,
                dict(
                    kind="Stage1ResearchDeliverable",
                    schema_version="1.1.0",
                    canonical_records=records,
                ),
            )
            with self.assertRaisesRegex(SessionApiError, "consumer-unconnected"):
                _verified_inputs(
                    {},
                    dict(
                        deliverable_dir=str(folder),
                        manifest_sha256=sha(manifest.read_bytes()),
                    ),
                )


if __name__ == "__main__":
    unittest.main()

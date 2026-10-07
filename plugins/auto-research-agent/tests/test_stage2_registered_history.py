"""Synthetic registered-history replay; no native call or approval evidence."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

import test_stage2_revision_provenance as revision_fixtures  # noqa: E402
import test_stage2_topic_tables_integration as table_fixtures  # noqa: E402
from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_workflow import add_snapshot, initialize_workflow, inspect_workflow  # noqa: E402
from stage2_workflow.delivery import inspect_delivery  # noqa: E402
from stage2_workflow.registered_history import (  # noqa: E402
    ARCHIVE,
    capture_registered_history,
    inspect_registered_history,
)
from stage2_workflow.store import finish_action, start_action  # noqa: E402


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def rehash(value, field):
    value[field] = canonical_hash(
        {key: item for key, item in value.items() if key != field}
    )


class RegisteredHistoryTests(unittest.TestCase):
    setUp = revision_fixtures.RevisionProvenanceTests.setUp
    _write_receipt = revision_fixtures.RevisionProvenanceTests._write_receipt

    def portable(self, state=None):
        state = state or self.state
        provenance, files = capture_registered_history(state)
        output = self.root / "portable"
        for relative, raw in files.items():
            path = output / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        (output / ARCHIVE / "actions").mkdir(parents=True, exist_ok=True)
        payload = state["latest_snapshot"]["event"]["payload"]
        manifest = {
            "workflow_manifest_sha256": state["manifest"]["manifest_sha256"],
            "workflow_head_sha256": state["head_sha256"],
            "snapshot_sequence": payload["snapshot_sequence"],
            "snapshot_sha256": payload["snapshot_sha256"],
            "snapshot_checker_manifest_sha256": payload["checker_manifest_sha256"],
            "revision_provenance_scope": "registered-content-history-only",
            "revision_provenance_sha256": canonical_hash(provenance),
        }
        return output, provenance, manifest

    def replay(self, output, provenance, manifest, packet=None):
        return inspect_registered_history(
            output, provenance, packet or self.current, manifest
        )

    def rewrite_latest(self, mutate):
        """Rehash a synthetic registered transition to exercise semantic checks."""
        checker = self.workflow / "snapshots/000002/checker"
        packet = json.loads((checker / "packet.json").read_bytes())
        mutate(packet)
        write_json(checker / "packet.json", packet)
        manifest = json.loads((checker / "run_manifest.json").read_bytes())
        original = copy.deepcopy(packet)
        paths = {
            row["source_id"]: row["original_path"]
            for row in manifest["source_snapshots"]
        }
        for row in original["sources"]:
            row["path"] = paths[row["source_id"]]
        manifest["packet_sha256"] = canonical_hash(original)
        manifest["stored_packet_sha256"] = canonical_hash(packet)
        rehash(manifest, "manifest_sha256")
        write_json(checker / "run_manifest.json", manifest)
        path = self.workflow / "events/000002.json"
        event = json.loads(path.read_bytes())
        event["payload"].update(
            original_packet_sha256=canonical_hash(original),
            snapshot_sha256=manifest["manifest_sha256"],
            checker_manifest_sha256=manifest["manifest_sha256"],
            source_versions=[
                {
                    key: row[key]
                    for key in ("source_id", "work_id", "version_id", "sha256")
                }
                for row in original["sources"]
            ],
        )
        rehash(event, "event_sha256")
        write_json(path, event)
        supplied = copy.deepcopy(self.state)
        supplied["head_sha256"] = event["event_sha256"]
        return supplied

    def test_legitimate_semantic_revisions_and_exact_event_links(self):
        output, provenance, manifest = self.portable()
        revisions = self.replay(output, provenance, manifest)
        self.assertEqual(
            [
                (row["candidate_id"], row["from_version"], row["to_version"])
                for row in revisions
            ],
            [("candidate-1", 1, 2), ("candidate-2", 1, 2)],
        )
        self.assertEqual(provenance["steps"][0]["revisions"], [])
        self.assertEqual(
            provenance["steps"][1]["event_sha256"], self.state["head_sha256"]
        )
        self.assertEqual(
            provenance["steps"][1]["parent_packet_sha256"], canonical_hash(self.parent)
        )

    def test_portable_roundtrip_after_original_workflow_and_sources_moved(self):
        output, provenance, manifest = self.portable()
        self.workflow.rename(self.root / "old-workflow")
        self.sources.rename(self.root / "old-sources")
        self.update.rename(self.root / "old-update")
        self.assertEqual(len(self.replay(output, provenance, manifest)), 2)

    def test_capture_is_readonly_and_no_call_no_approval_no_author_claim(self):
        before = {
            path.relative_to(self.workflow).as_posix(): path.read_bytes()
            for path in self.workflow.rglob("*")
            if path.is_file()
        }
        with (
            patch(
                "stage2_workflow.store.start_action",
                side_effect=AssertionError("no call"),
            ),
            patch(
                "stage2_workflow.store.add_snapshot",
                side_effect=AssertionError("no mutation"),
            ),
        ):
            provenance, _ = capture_registered_history(self.state)
        self.assertIs(provenance["native_execution_attested"], False)
        self.assertIs(provenance["human_approval"], False)
        self.assertEqual(provenance["authorship"], "not-attested")
        self.assertEqual(
            before,
            {
                path.relative_to(self.workflow).as_posix(): path.read_bytes()
                for path in self.workflow.rglob("*")
                if path.is_file()
            },
        )

    def test_unlisted_workflow_files_and_external_paths_are_not_copied(self):
        (self.workflow / "unlisted-config.json").write_bytes(
            b"synthetic excluded config"
        )
        provenance, files = capture_registered_history(self.state)
        self.assertFalse(any("unlisted-config" in name for name in files))
        self.assertEqual({row["path"] for row in provenance["files"]}, set(files))

    def test_registered_action_and_stored_artifact_are_portable_not_attested(self):
        started = start_action(
            self.workflow,
            "synthetic-record",
            "synthetic",
            {"external_path": str(self.root / "does-not-exist")},
            {},
            self.state["head_sha256"],
        )
        artifact = self.root / "synthetic-artifact.txt"
        artifact.write_bytes(b"registered bytes; no native call")
        finished = finish_action(
            self.workflow,
            "synthetic-record",
            "complete",
            {
                "result.txt": {
                    "path": str(artifact),
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                }
            },
            None,
            None,
            started["event"]["event_sha256"],
        )
        state = inspect_workflow(self.workflow, finished["event_sha256"])
        output, provenance, manifest = self.portable(state)
        artifact.rename(self.root / "moved-artifact.txt")
        self.workflow.rename(self.root / "moved-workflow")
        self.assertEqual(len(self.replay(output, provenance, manifest)), 2)
        self.assertFalse(provenance["native_execution_attested"])
        self.assertTrue(
            (
                output / ARCHIVE / "actions/synthetic-record/artifacts/result.txt"
            ).is_file()
        )

    def test_unfinished_registered_action_remains_unfinished(self):
        started = start_action(
            self.workflow, "unfinished", "synthetic", {}, {}, self.state["head_sha256"]
        )
        state = inspect_workflow(self.workflow, started["event"]["event_sha256"])
        output, provenance, manifest = self.portable(state)
        self.assertEqual(len(self.replay(output, provenance, manifest)), 2)
        self.assertFalse((output / ARCHIVE / "actions/unfinished/result.json").exists())

    def test_claim_lies_rejected_even_with_rebound_provenance_hash(self):
        output, provenance, manifest = self.portable()
        for field, lie in (
            ("native_execution_attested", True),
            ("human_approval", True),
            ("authorship", "parent-authored"),
            ("native_execution_attested", 0),
        ):
            with self.subTest(field=field, lie=lie):
                changed = copy.deepcopy(provenance)
                changed[field] = lie
                bound = dict(
                    manifest, revision_provenance_sha256=canonical_hash(changed)
                )
                with self.assertRaisesRegex(Stage2Error, "claims-invalid"):
                    self.replay(output, changed, bound)

    def test_mutated_portable_source_bytes_rejected(self):
        output, provenance, manifest = self.portable()
        source = next(
            row["path"] for row in provenance["files"] if "/sources/" in row["path"]
        )
        with (output / source).open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(Stage2Error, "file-hash-mismatch"):
            self.replay(output, provenance, manifest)

    def test_missing_event_rejected(self):
        output, provenance, manifest = self.portable()
        (output / ARCHIVE / "events/000001.json").unlink()
        with self.assertRaises(Stage2Error):
            self.replay(output, provenance, manifest)

    def test_nonconsecutive_event_rejected(self):
        (self.workflow / "events/000002.json").rename(
            self.workflow / "events/000003.json"
        )
        with self.assertRaisesRegex(Stage2Error, "event-sequence"):
            capture_registered_history(self.state)

    def test_missing_parent_snapshot_rejected(self):
        (self.workflow / "snapshots/000001").rename(self.workflow / "snapshots/000003")
        with self.assertRaises(Stage2Error):
            capture_registered_history(self.state)

    def test_wrong_snapshot_parent_binding_rejected_after_rehash(self):
        path = self.workflow / "events/000002.json"
        event = json.loads(path.read_bytes())
        event["payload"]["parent_snapshot_sha256"] = "a" * 64
        rehash(event, "event_sha256")
        write_json(path, event)
        supplied = dict(self.state, head_sha256=event["event_sha256"])
        with self.assertRaises(Stage2Error):
            capture_registered_history(supplied)

    def test_protected_brief_rewrite_rejected_after_rehash(self):
        state = self.rewrite_latest(
            lambda packet: packet["brief"].update(original_description="rewritten")
        )
        with self.assertRaises(Stage2Error):
            capture_registered_history(state)

    def test_resource_rewrite_rejected_after_rehash(self):
        state = self.rewrite_latest(
            lambda packet: packet.update(resources="rewritten resource boundary")
        )
        with self.assertRaisesRegex(Stage2Error, "resources-change"):
            capture_registered_history(state)

    def test_legacy_candidate_mutation_rejected_after_rehash(self):
        state = self.rewrite_latest(
            lambda packet: packet["candidates"][0].update(question="rewritten v1")
        )
        with self.assertRaisesRegex(Stage2Error, "candidates-history-rewritten"):
            capture_registered_history(state)

    def test_source_promotion_or_relabel_rejected_after_rehash(self):
        state = self.rewrite_latest(
            lambda packet: packet["sources"][0].update(evidence_level="abstract-only")
        )
        with self.assertRaises(Stage2Error):
            capture_registered_history(state)

    def test_old_evidence_mutation_rejected_after_rehash(self):
        state = self.rewrite_latest(
            lambda packet: packet["evidence"][0].update(locator="changed locator")
        )
        with self.assertRaisesRegex(Stage2Error, "evidence-history-rewritten"):
            capture_registered_history(state)

    def test_version_only_candidate_change_is_not_revision(self):
        def mutate(packet):
            packet["candidates"][2] = dict(
                packet["candidates"][0], version=2, parent_version=1
            )

        state = self.rewrite_latest(mutate)
        state = inspect_workflow(self.workflow, state["head_sha256"])
        with self.assertRaisesRegex(Stage2Error, "added-evidence-invalid"):
            capture_registered_history(state)

    def test_changed_reason_requires_actual_registered_event(self):
        output, provenance, manifest = self.portable()
        provenance["steps"][1]["revisions"][0]["reason"] = "invented reason"
        manifest["revision_provenance_sha256"] = canonical_hash(provenance)
        with self.assertRaisesRegex(Stage2Error, "replay-mismatch"):
            self.replay(output, provenance, manifest)

    def test_hand_authored_state_reason_is_not_captured(self):
        state = copy.deepcopy(self.state)
        state["events"][1]["payload"]["reason"] = "invented reason"
        with self.assertRaisesRegex(Stage2Error, "state-mismatch"):
            capture_registered_history(state)

    def test_current_packet_and_final_checker_binding_required(self):
        output, provenance, manifest = self.portable()
        changed = copy.deepcopy(self.current)
        changed["comparison"] += " changed"
        with self.assertRaisesRegex(Stage2Error, "delivery-binding"):
            self.replay(output, provenance, manifest, changed)
        manifest["snapshot_checker_manifest_sha256"] = "b" * 64
        with self.assertRaisesRegex(Stage2Error, "final-checker"):
            self.replay(output, provenance, manifest)

    def test_extra_portable_file_rejected(self):
        output, provenance, manifest = self.portable()
        (output / ARCHIVE / "unexpected.txt").write_bytes(b"not a verified dependency")
        with self.assertRaisesRegex(Stage2Error, "file-set-mismatch"):
            self.replay(output, provenance, manifest)

    def test_path_escape_rejected(self):
        output, provenance, manifest = self.portable()
        provenance["files"][0]["path"] = ARCHIVE + "/../../../escape"
        manifest["revision_provenance_sha256"] = canonical_hash(provenance)
        with self.assertRaises(Stage2Error):
            self.replay(output, provenance, manifest)

    def test_rehash_tamper_rejected(self):
        # The old externally retained receipt stays authoritative even if all
        # altered portable event/provenance/manifest bytes are locally rehashed.
        import test_stage2_registered_history_delivery as delivery_fixtures

        fixture = delivery_fixtures.RegisteredHistoryDeliveryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        output = fixture.root / "retained-delivery"
        manifest = fixture._deliver(output)
        receipt = manifest["manifest_sha256"]
        path = output / ARCHIVE / "events/000002.json"
        event = json.loads(path.read_bytes())
        event["payload"]["reason"] = "rehashed attacker reason"
        rehash(event, "event_sha256")
        write_json(path, event)
        provenance_path = output / "revision_provenance.json"
        provenance = json.loads(provenance_path.read_bytes())
        provenance["workflow_head_sha256"] = event["event_sha256"]
        provenance["steps"][1].update(
            event_sha256=event["event_sha256"],
            snapshot_reason=event["payload"]["reason"],
        )
        relative = path.relative_to(output).as_posix()
        for row in provenance["files"]:
            if row["path"] == relative:
                row.update(
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    size_bytes=path.stat().st_size,
                )
        write_json(provenance_path, provenance)
        manifest.update(
            workflow_head_sha256=event["event_sha256"],
            revision_provenance_sha256=canonical_hash(provenance),
        )
        for row in manifest["files"]:
            if row["path"] in {relative, "revision_provenance.json"}:
                raw = (output / row["path"]).read_bytes()
                row.update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        rehash(manifest, "manifest_sha256")
        write_json(output / "delivery_manifest.json", manifest)
        with self.assertRaisesRegex(Stage2Error, "receipt-mismatch"):
            inspect_delivery(output, receipt)

    def test_actual_research_table_bridge_and_candidate_introduction(self):
        fixture = table_fixtures.Stage2TopicTablesIntegrationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        workflow, initial, snapshot = fixture.workflow()
        current, _ = fixture.prepared(snapshot)
        path = fixture.root / "table-current.json"
        write_json(path, current)
        impact = [
            {
                "candidate_id": "candidate-table",
                "status": "affected",
                "reason": "registered synthetic tables",
            }
        ]
        event = add_snapshot(
            workflow,
            path,
            fixture.sources,
            "Introduce source-bound tables",
            impact,
            initial["head_sha256"],
        )
        state = inspect_workflow(workflow, event["event_sha256"])
        bridge = copy.deepcopy(current)
        bridge["research_tables"].update(
            input_packet_sha256=canonical_hash(current),
            input_snapshot_sha256=state["latest_snapshot"]["event"]["payload"][
                "snapshot_sha256"
            ],
        )
        bridge["research_tables"]["cells"][0]["reason"] += " Registered clarification."
        write_json(path, bridge)
        event = add_snapshot(
            workflow,
            path,
            fixture.sources,
            "Clarify one table cell",
            impact,
            state["head_sha256"],
        )
        state = inspect_workflow(workflow, event["event_sha256"])
        provenance, files = capture_registered_history(state)
        self.assertEqual(
            [step["revisions"] for step in provenance["steps"]], [[], [], []]
        )
        self.assertEqual(
            provenance["steps"][2]["parent_packet_sha256"], canonical_hash(current)
        )
        self.assertTrue(any(name.endswith("input_packet.json") for name in files))
        output, provenance, manifest = self.portable(state)
        workflow.rename(fixture.root / "moved-table-workflow")
        fixture.sources.rename(fixture.root / "moved-table-sources")
        self.assertEqual(self.replay(output, provenance, manifest, bridge), [])

    def test_imported_initial_revision_history_remains_incomplete(self):
        import test_stage2_registered_history_delivery as delivery_fixtures

        fixture = delivery_fixtures.RegisteredHistoryDeliveryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.workflow.rename(fixture.root / "earlier-unrelated-workflow")
        # This run imports v1+v2 at initialization; it has no registered v1->v2
        # event and must not borrow one from another workflow or invent a reason.
        initialize_workflow(
            fixture.packet_path, fixture.update, fixture.workflow, {}, {}
        )
        initial = inspect_workflow(fixture.workflow)
        current = copy.deepcopy(fixture.current)
        for candidate in fixture.current["candidates"]:
            if candidate["version"] == 2:
                revised = dict(
                    candidate,
                    version=3,
                    parent_version=2,
                    question=candidate["question"] + " A genuine registered v3 change.",
                )
                current["candidates"].append(revised)
        write_json(fixture.packet_path, current)
        event = add_snapshot(
            fixture.workflow,
            fixture.packet_path,
            fixture.update,
            "Register the subsequent v3 changes.",
            fixture.impact,
            initial["head_sha256"],
        )
        fixture.current = current
        fixture.state = inspect_workflow(fixture.workflow, event["event_sha256"])
        output = fixture.root / "incomplete-history-delivery"
        manifest = fixture._deliver(output)
        result = inspect_delivery(output, manifest["manifest_sha256"])
        self.assertEqual(result["selection"]["action_record_status"], "unavailable")
        self.assertIsNone(result["selection"]["action_record"])
        self.assertTrue(
            any(
                "v2: imported revision" in row
                for row in result["selection"]["action_record_blocking_items"]
            )
        )
        provenance = json.loads((output / "revision_provenance.json").read_bytes())
        rows = [row for step in provenance["steps"] for row in step["revisions"]]
        self.assertEqual(
            [(row["from_version"], row["to_version"]) for row in rows], [(2, 3), (2, 3)]
        )


if __name__ == "__main__":
    unittest.main()

"""Synthetic legacy imports; local evidence does not attest calls or approval."""

import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

import test_stage2_revision_provenance as fixtures  # noqa: E402
from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_workflow.delivery import _manifest_hash, _relative_files, inspect_delivery  # noqa: E402
from stage2_workflow.imported_history import (  # noqa: E402
    PREFIX,
    capture_imported_history,
    inspect_imported_history,
)


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


class ImportedHistoryTests(unittest.TestCase):
    _write_receipt = fixtures.RevisionProvenanceTests._write_receipt
    _assessment = fixtures.RevisionProvenanceTests._assessment
    _inputs = fixtures.RevisionProvenanceTests._inputs
    _build = fixtures.RevisionProvenanceTests._build
    _append_third_version_update = (
        fixtures.RevisionProvenanceTests._append_third_version_update
    )

    def setUp(self):
        fixtures.RevisionProvenanceTests.setUp(self)
        self.delivery, self.manifest = self._build("prior-delivery")
        self.receipt = self.manifest["manifest_sha256"]
        self.initial = copy.deepcopy(self.current)
        for source in self.initial["sources"]:
            source["path"] = "relocated/" + source["path"]

    def capture(self, initial=None, bindings=None):
        return capture_imported_history(
            bindings if bindings is not None else [(self.delivery, self.receipt)],
            initial if initial is not None else self.initial,
        )

    def portable(self):
        records, files, rows = self.capture()
        output = self.root / "portable-import"
        for relative, raw in files.items():
            path = output / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        return output, records, files, rows

    def rehash_delivery(self, delivery=None):
        root = delivery or self.delivery
        manifest = json.loads((root / "delivery_manifest.json").read_bytes())
        manifest["files"] = _relative_files(root)
        manifest["manifest_sha256"] = _manifest_hash(manifest)
        write_json(root / "delivery_manifest.json", manifest)
        return manifest

    def test_roundtrip_after_prior_package_and_workflow_moved(self):
        output, records, files, rows = self.portable()
        self.delivery.rename(self.root / "moved-delivery")
        self.workflow.rename(self.root / "moved-workflow")
        self.update.rename(self.root / "moved-update")
        self.sources.rename(self.root / "moved-sources")
        self.assertEqual(inspect_imported_history(output, records, self.initial), rows)
        self.assertEqual(
            [(row["from_version"], row["to_version"]) for row in rows], [(1, 2), (1, 2)]
        )
        self.assertEqual({row["path"] for row in records[0]["files"]}, set(files))

    def test_exact_raw_files_preserve_absolute_historical_strings(self):
        records, files, _ = self.capture()
        prefix = records[0]["delivery_root"] + "/"
        expected = {row["path"] for row in self.manifest["files"]} | {
            "delivery_manifest.json"
        }
        self.assertEqual({name.removeprefix(prefix) for name in files}, expected)
        for name, raw in files.items():
            self.assertEqual(
                raw, (self.delivery / name.removeprefix(prefix)).read_bytes()
            )
        receipt_file = next(
            raw
            for name, raw in files.items()
            if name.endswith("source_update_000001.json")
        )
        self.assertEqual(json.loads(receipt_file)["source_root"], str(self.update))

    def test_empty_bindings_preserve_missing_history(self):
        self.assertEqual(capture_imported_history([], self.initial), ([], {}, []))
        self.assertEqual(inspect_imported_history(self.root, [], self.initial), [])

    def test_capture_has_no_execution_approval_or_authorship_attestation(self):
        before = {
            path.relative_to(self.delivery).as_posix(): path.read_bytes()
            for path in self.delivery.rglob("*")
            if path.is_file()
        }
        with patch(
            "stage2_workflow.store.start_action",
            side_effect=AssertionError("no native call"),
        ):
            records, _, _ = self.capture()
        self.assertEqual(records[0]["scope"], "imported-local-content-history-only")
        self.assertIs(records[0]["native_execution_attested"], False)
        self.assertIs(records[0]["human_approval"], False)
        self.assertEqual(records[0]["authorship"], "not-attested")
        self.assertEqual(
            before,
            {
                path.relative_to(self.delivery).as_posix(): path.read_bytes()
                for path in self.delivery.rglob("*")
                if path.is_file()
            },
        )

    def test_changed_initial_candidate_from_payload_rejected(self):
        initial = copy.deepcopy(self.initial)
        initial["candidates"][0]["question"] += " changed"
        with self.assertRaisesRegex(Stage2Error, "candidate-mismatch"):
            self.capture(initial)

    def test_changed_initial_candidate_to_payload_rejected(self):
        initial = copy.deepcopy(self.initial)
        initial["candidates"][2]["opportunity"] += " changed"
        with self.assertRaisesRegex(Stage2Error, "candidate-mismatch"):
            self.capture(initial)

    def test_changed_initial_evidence_object_rejected(self):
        initial = copy.deepcopy(self.initial)
        initial["evidence"][0]["locator"] = "changed locator"
        with self.assertRaisesRegex(Stage2Error, "evidence-mismatch"):
            self.capture(initial)

    def test_missing_referenced_evidence_rejected(self):
        initial = copy.deepcopy(self.initial)
        initial["evidence"].pop()
        with self.assertRaisesRegex(Stage2Error, "evidence-mismatch"):
            self.capture(initial)

    def test_source_work_version_level_and_raw_hash_must_match(self):
        for key, wrong in (
            ("work_id", "wrong-work"),
            ("version_id", "v2"),
            ("evidence_level", "abstract-only"),
            ("sha256", "f" * 64),
        ):
            with self.subTest(field=key):
                initial = copy.deepcopy(self.initial)
                initial["sources"][0][key] = wrong
                with self.assertRaisesRegex(Stage2Error, "source-mismatch"):
                    self.capture(initial)

    def test_source_path_relocation_is_allowed(self):
        initial = copy.deepcopy(self.initial)
        initial["sources"][0]["path"] = "another/relative/location.txt"
        records, _, rows = self.capture(initial)
        self.assertEqual(len(rows), 2)
        self.assertEqual(records[0]["initial_packet_sha256"], canonical_hash(initial))

    def test_unrelated_initial_candidate_rejected(self):
        initial = copy.deepcopy(self.initial)
        for candidate in initial["candidates"]:
            candidate["candidate_id"] = "unrelated-" + candidate["candidate_id"]
        with self.assertRaisesRegex(Stage2Error, "candidate-mismatch"):
            self.capture(initial)

    def test_missing_initial_transition_rejected(self):
        initial = copy.deepcopy(self.initial)
        initial["candidates"] = [
            row for row in initial["candidates"] if row["version"] == 2
        ]
        with self.assertRaisesRegex(Stage2Error, "candidate-mismatch"):
            self.capture(initial)

    def test_duplicate_transition_across_bindings_rejected(self):
        with self.assertRaisesRegex(Stage2Error, "duplicate-transition"):
            self.capture(
                bindings=[(self.delivery, self.receipt), (self.delivery, self.receipt)]
            )

    def test_duplicate_initial_identity_rejected(self):
        initial = copy.deepcopy(self.initial)
        initial["candidates"].append(copy.deepcopy(initial["candidates"][0]))
        with self.assertRaisesRegex(Stage2Error, "initial-identities-duplicate"):
            self.capture(initial)

    def test_absent_revision_rows_rejected_in_otherwise_valid_legacy_package(self):
        provenance = json.loads(
            (self.delivery / "revision_provenance.json").read_bytes()
        )
        provenance["steps"] = []
        with patch(
            "stage2_workflow.delivery.capture_revision_provenance",
            return_value=(provenance, {}),
        ):
            output, manifest = self._build("empty-history")
        self.assertEqual(
            inspect_delivery(output, manifest["manifest_sha256"])["selection"][
                "action_record_status"
            ],
            "unavailable",
        )
        with self.assertRaisesRegex(Stage2Error, "revisions-absent"):
            self.capture(bindings=[(output, manifest["manifest_sha256"])])

    def test_wrong_retained_manifest_hash_rejected(self):
        with self.assertRaisesRegex(Stage2Error, "receipt-mismatch"):
            self.capture(bindings=[(self.delivery, "f" * 64)])

    def test_rehash_tamper_rejected(self):
        output, records, _, _ = self.portable()
        package = output / records[0]["delivery_root"]
        path = package / "input_packet.json"
        packet = json.loads(path.read_bytes())
        packet["comparison"] += " attacker rewrite"
        write_json(path, packet)
        changed = self.rehash_delivery(package)
        self.assertNotEqual(
            changed["manifest_sha256"], records[0]["delivery_manifest_sha256"]
        )
        with self.assertRaisesRegex(Stage2Error, "receipt-mismatch"):
            inspect_imported_history(output, records, self.initial)

    def test_prior_manifest_raw_bytes_tamper_rejected(self):
        output, records, _, _ = self.portable()
        manifest = output / records[0]["delivery_root"] / "delivery_manifest.json"
        with manifest.open("ab") as stream:
            stream.write(b"\n")
        with self.assertRaisesRegex(Stage2Error, "record-mismatch"):
            inspect_imported_history(output, records, self.initial)

    def test_extra_legacy_file_rejected_before_reading_undeclared_bytes(self):
        extra = self.delivery / "undeclared.txt"
        extra.write_bytes(b"synthetic arbitrary file, not an allowed inventory member")
        original = Path.read_bytes

        def guarded(path):
            if path == extra:
                raise AssertionError("undeclared bytes must not be read")
            return original(path)

        with patch.object(Path, "read_bytes", guarded):
            with self.assertRaisesRegex(Stage2Error, "file-set-mismatch"):
                self.capture()

    def test_extra_portable_package_rejected(self):
        output, records, _, _ = self.portable()
        (output / PREFIX / "000002").mkdir()
        with self.assertRaisesRegex(Stage2Error, "package-set-mismatch"):
            inspect_imported_history(output, records, self.initial)

    def test_symlink_legacy_file_rejected(self):
        link = self.delivery / "linked.txt"
        try:
            link.symlink_to(self.delivery / "input_packet.json")
        except OSError as error:
            self.skipTest(f"host lacks symlink capability: {error}")
        with self.assertRaisesRegex(Stage2Error, "capture-failed"):
            self.capture()

    def test_symlink_package_root_rejected(self):
        link = self.root / "linked-delivery"
        try:
            link.symlink_to(self.delivery, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"host lacks symlink capability: {error}")
        with self.assertRaisesRegex(Stage2Error, "capture-failed"):
            self.capture(bindings=[(link, self.receipt)])

    def test_spoofed_record_attestations_rejected(self):
        output, records, _, _ = self.portable()
        for field, lie in (
            ("native_execution_attested", True),
            ("human_approval", True),
            ("authorship", "native-agent"),
            ("human_approval", 0),
        ):
            with self.subTest(field=field, lie=lie):
                changed = copy.deepcopy(records)
                changed[0][field] = lie
                with self.assertRaisesRegex(Stage2Error, "claims-invalid"):
                    inspect_imported_history(output, changed, self.initial)

    def test_unsupported_and_recursive_delivery_schema_rejected(self):
        path = self.delivery / "delivery_manifest.json"
        for version in ("1.0.0", "1.2.0", "1.3.0", "2.0.0"):
            with self.subTest(version=version):
                manifest = copy.deepcopy(self.manifest)
                manifest["schema_version"] = version
                manifest["manifest_sha256"] = _manifest_hash(manifest)
                write_json(path, manifest)
                with self.assertRaisesRegex(Stage2Error, "version-unsupported"):
                    self.capture(
                        bindings=[(self.delivery, manifest["manifest_sha256"])]
                    )

    def test_legacy_false_execution_attestation_requirement_preserved(self):
        path = self.delivery / "delivery_manifest.json"
        manifest = copy.deepcopy(self.manifest)
        manifest["actual_execution_attested"] = True
        manifest["manifest_sha256"] = _manifest_hash(manifest)
        write_json(path, manifest)
        with self.assertRaisesRegex(Stage2Error, "authorization-state-invalid"):
            self.capture(bindings=[(self.delivery, manifest["manifest_sha256"])])

    def test_recorded_reason_and_initial_hash_are_reconstructed_not_trusted(self):
        output, records, _, _ = self.portable()
        for field in ("reason", "initial_packet_sha256"):
            with self.subTest(field=field):
                changed = copy.deepcopy(records)
                if field == "reason":
                    changed[0]["revisions"][0]["reason"] = (
                        "invented retrospective reason"
                    )
                else:
                    changed[0][field] = "f" * 64
                with self.assertRaisesRegex(Stage2Error, "record-mismatch"):
                    inspect_imported_history(output, changed, self.initial)

    def test_partial_coverage_does_not_require_unrelated_initial_transition(self):
        initial = copy.deepcopy(self.initial)
        candidate = copy.deepcopy(initial["candidates"][0])
        candidate["candidate_id"] = "other-candidate"
        initial["candidates"].extend(
            [
                candidate,
                dict(
                    candidate,
                    version=2,
                    parent_version=1,
                    question="Unrecorded unrelated change",
                ),
            ]
        )
        _, _, rows = self.capture(initial)
        self.assertEqual(
            {row["candidate_id"] for row in rows}, {"candidate-1", "candidate-2"}
        )

    def test_old_delivery_remains_unchanged_and_inspectable(self):
        expected = inspect_delivery(self.delivery, self.receipt)
        self.capture()
        actual = inspect_delivery(self.delivery, self.receipt)
        self.assertEqual(actual["manifest"], expected["manifest"])
        self.assertEqual(actual["selection"], expected["selection"])


if __name__ == "__main__":
    unittest.main()

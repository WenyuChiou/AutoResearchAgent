"""Ordinary publication faults use real offline builders, never model calls."""

# ruff: noqa: E402 -- repository package and authored offline fixture.
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "cli"), str(HERE)]
import test_stage2_delivery as fixtures
from stage2_common import Stage2Error
import stage2_workflow.atomic_delivery as atomic
import stage2_workflow.delivery as delivery


def tree_hashes(directory):
    return {
        p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in directory.rglob("*")
        if p.is_file()
    }


class AtomicDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.Stage2DeliveryTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.reviews, self.resolutions = self.f._complete_inputs()
        self.output = self.f.root / "ordinary-delivery"
        self.staging = self.f.root / ".ordinary-delivery.stage2-staging"

    def build(self, reviews=None):
        return atomic.build_atomic_delivery(
            self.f.workflow,
            self.f.batch,
            self.reviews if reviews is None else reviews,
            self.resolutions,
            self.output,
            self.f.state["head_sha256"],
        )

    def interrupt_before_manifest(self):
        original = delivery._write_new

        def interrupted(path, value):
            if Path(path).name == delivery.MANIFEST:
                raise OSError("synthetic crash before manifest publication")
            return original(path, value)

        with patch.object(delivery, "_write_new", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "synthetic crash"):
                self.build()
        self.assertFalse(self.output.exists())
        self.assertTrue((self.staging / "selection.html").is_file())

    def test_complete_publication_and_replay_preserve_all_bytes(self):
        manifest = self.build()
        self.assertFalse(self.staging.exists())
        before = tree_hashes(self.output)
        with patch.object(
            delivery, "initialize_run", side_effect=AssertionError("must not rebuild")
        ):
            self.assertEqual(self.build(), manifest)
        self.assertEqual(tree_hashes(self.output), before)
        checked = delivery.inspect_delivery(self.output, manifest["manifest_sha256"])
        self.assertFalse(checked["manifest"]["stage3_execution_authorized"])

    def test_manifest_interruption_resumes_without_reinitializing_checker(self):
        with patch.object(
            delivery, "initialize_run", wraps=delivery.initialize_run
        ) as initialized:
            self.interrupt_before_manifest()
            checker_before = tree_hashes(self.staging / "checker")
            self.build()
            self.assertEqual(initialized.call_count, 1)
        self.assertEqual(tree_hashes(self.output / "checker"), checker_before)

    def test_completed_manifest_unpublished_recovery_is_readonly_until_rename(self):
        with patch.object(
            atomic, "_publish", side_effect=OSError("synthetic publish interruption")
        ):
            with self.assertRaisesRegex(OSError, "synthetic publish"):
                self.build()
        before = tree_hashes(self.staging)
        self.assertFalse(self.output.exists())
        with patch.object(
            delivery,
            "build_delivery",
            side_effect=AssertionError("must reuse sealed package"),
        ):
            self.build()
        self.assertEqual(tree_hashes(self.output), before)

    def test_changed_request_is_rejected_and_partial_evidence_is_retained(self):
        self.interrupt_before_manifest()
        before = tree_hashes(self.staging)
        changed = deepcopy(self.reviews)
        changed[0]["error"] = "different request"
        with self.assertRaisesRegex(
            Stage2Error, "delivery-resume-existing-bytes-differ"
        ):
            self.build(changed)
        self.assertEqual(tree_hashes(self.staging), before)
        self.assertFalse(self.output.exists())

    def test_tampered_partial_file_is_rejected_without_overwrite(self):
        self.interrupt_before_manifest()
        path = self.staging / "input_packet.json"
        path.write_bytes(b"{}")
        before = tree_hashes(self.staging)
        with self.assertRaisesRegex(
            Stage2Error, "delivery-resume-existing-bytes-differ"
        ):
            self.build()
        self.assertEqual(tree_hashes(self.staging), before)
        self.assertFalse(self.output.exists())

    def test_partial_checker_projection_tamper_is_rejected_without_overwrite(self):
        self.interrupt_before_manifest()
        path = self.staging / "checker" / "selection.json"
        path.write_bytes(b"truncated retained checker projection")
        before = tree_hashes(self.staging)
        with self.assertRaisesRegex(Stage2Error, "projection-existing-bytes-differ"):
            self.build()
        self.assertEqual(tree_hashes(self.staging), before)
        self.assertFalse(self.output.exists())

    def test_unpublished_manifest_rehash_cannot_change_snapshot_binding(self):
        with patch.object(atomic, "_publish", side_effect=OSError("before rename")):
            with self.assertRaisesRegex(OSError, "before rename"):
                self.build()
        path = self.staging / delivery.MANIFEST
        manifest = delivery._read_json(path)
        manifest["snapshot_checker_manifest_sha256"] = "0" * 64
        manifest["manifest_sha256"] = delivery._manifest_hash(manifest)
        path.write_bytes(delivery._canonical_bytes(manifest))
        before = tree_hashes(self.staging)
        with self.assertRaisesRegex(Stage2Error, "delivery-publication"):
            self.build()
        self.assertEqual(tree_hashes(self.staging), before)
        self.assertFalse(self.output.exists())

    def test_publication_cannot_replace_destination_created_after_precheck(self):
        staging = self.f.root / "race-staging"
        output = self.f.root / "race-output"
        staging.mkdir()
        (staging / "retained.txt").write_bytes(b"payload")
        output.mkdir()
        original_exists = Path.exists

        def stale_exists(path):
            return False if path == output else original_exists(path)

        with patch.object(Path, "exists", stale_exists):
            with self.assertRaisesRegex(Stage2Error, "destination-exists"):
                atomic._publish(staging, output)
        self.assertEqual((staging / "retained.txt").read_bytes(), b"payload")
        self.assertEqual(list(output.iterdir()), [])

    def interrupt_before_seal(self):
        original = delivery._write_new

        def interrupted(path, value):
            if Path(path).name == ".ordinary-delivery.stage2-sealed.json":
                raise OSError("before seal")
            return original(path, value)

        with patch.object(delivery, "_write_new", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "before seal"):
                self.build()
        self.assertTrue((self.staging / delivery.MANIFEST).is_file())

    def test_before_seal_crash_revalidates_without_reinitializing_checker(self):
        self.interrupt_before_seal()
        before = tree_hashes(self.staging)
        with patch.object(delivery, "initialize_run", side_effect=AssertionError()):
            self.build()
        self.assertEqual(tree_hashes(self.output), before)

    def test_unsealed_rehashed_manifest_is_rejected_by_deterministic_rebuild(self):
        self.interrupt_before_seal()
        path = self.staging / delivery.MANIFEST
        manifest = delivery._read_json(path)
        manifest["snapshot_checker_manifest_sha256"] = "0" * 64
        manifest["manifest_sha256"] = delivery._manifest_hash(manifest)
        path.write_bytes(delivery._canonical_bytes(manifest))
        before = tree_hashes(self.staging)
        with self.assertRaisesRegex(Stage2Error, "existing-bytes-differ"):
            self.build()
        self.assertEqual(tree_hashes(self.staging), before)
        self.assertFalse(self.output.exists())

    def test_published_output_without_retained_seal_is_not_adopted(self):
        self.build()
        seal = self.output.with_name(".ordinary-delivery.stage2-sealed.json")
        seal.unlink()
        before = tree_hashes(self.output)
        with self.assertRaisesRegex(Stage2Error, "publication-seal-missing"):
            self.build()
        self.assertEqual(tree_hashes(self.output), before)

    def test_existing_unbound_destination_and_lock_are_not_adopted(self):
        self.output.mkdir()
        marker = self.output / "foreign.txt"
        marker.write_bytes(b"retained")
        with self.assertRaisesRegex(Stage2Error, "unbound-existing-output"):
            self.build()
        self.assertEqual(marker.read_bytes(), b"retained")
        self.output = self.f.root / "locked-output"
        lock = self.output.with_name(".locked-output.stage2-publish.lock")
        lock.write_bytes(b"uninspected owner")
        with self.assertRaisesRegex(Stage2Error, "lock-requires-inspection"):
            self.build()
        self.assertEqual(lock.read_bytes(), b"uninspected owner")


if __name__ == "__main__":
    unittest.main()

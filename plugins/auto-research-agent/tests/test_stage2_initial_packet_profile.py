"""Offline regressions for explicit initial-packet profiles and immutable imports."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "cli")]

from research_workspace_native.project_stage2_profile import (  # noqa: E402
    inspect_initial_packet,
    prepare_initial_packet,
    read_initial_seed,
)
from research_workspace_native.session_api import SessionApiError  # noqa: E402
from stage1_ledger.journal import canonical  # noqa: E402
from stage2_common import canonical_hash, validate_packet  # noqa: E402
from stage2_common.contract import stage1_projection_hash  # noqa: E402
from stage2_fixture_helpers import _candidate, write_stage2_fixture  # noqa: E402


def write_import_seed(root):
    """Extend the small shared packet fixture with synthetic v2 import bindings."""
    packet = write_stage2_fixture(root, candidate_count=0)
    packet["schema_version"] = "2.0.0"
    packet["literature"] = []
    for source, evidence in zip(packet["sources"], packet["evidence"], strict=True):
        source.update(
            origin="stage1",
            access_status="available",
            retrieved_at="2026-10-01T00:00:00Z",
            source_url="https://example.org/synthetic-snapshot",
            final_url="https://example.org/synthetic-snapshot",
            access_note="Local synthetic source; no source acquisition was performed.",
        )
        evidence.update(
            origin="stage1",
            claim_text=evidence["quote"],
            relation="supported",
            evidence_level=source["evidence_level"],
        )
        packet["literature"].append(
            dict(
                origin="stage1",
                work_id=source["work_id"],
                version_id=source["version_id"],
                title=f"Synthetic snapshot {source['work_id']}",
                authors=["Synthetic fixture author"],
                year=2026,
                venue="Controlled test fixture",
                doi=None,
                url=source["source_url"],
                evidence_level=source["evidence_level"],
                source_ids=[source["source_id"]],
                classification=dict(
                    topic_cluster="bounded comparison",
                    method="controlled observation",
                    geography="not specified",
                    population="synthetic observations",
                    data_type="UTF-8 text",
                    domain="test fixture",
                ),
                roles=[],
                findings=dict(
                    question="Which synthetic method is supportable?",
                    data="The supplied local source snapshot.",
                    method="Compare the recorded observations.",
                    main_findings=evidence["quote"],
                    limitations="External validity remains unknown.",
                    relevance="Supports the bounded comparison.",
                    transferability="No real-world generalization was tested.",
                ),
                claim_ids=[evidence["evidence_id"]],
            )
        )
    synthetic_hash = canonical_hash("synthetic upstream fixture")
    upstream = dict(
        kind="Stage1Stage2Binding",
        schema_version="1.0.0",
        source_run_id="synthetic-import-run",
        source_state_sha256=synthetic_hash,
        stage1_handoff_sha256=synthetic_hash,
        stage1_deliverable_manifest_sha256=synthetic_hash,
        stage1_records_sha256=synthetic_hash,
        research_brief_sha256=canonical_hash(packet["brief"]),
        resources_sha256=canonical_hash(packet["resources"]),
        stage1_literature_sha256=stage1_projection_hash(packet["literature"]),
        stage1_sources_sha256=stage1_projection_hash(packet["sources"], omit={"path"}),
        stage1_evidence_sha256=stage1_projection_hash(packet["evidence"]),
        included_work_ids=[row["work_id"] for row in packet["literature"]],
        eligible_for_stage2=True,
        stage2=dict(status="not-started", execution_authorized=False),
    )
    upstream["binding_sha256"] = canonical_hash(upstream)
    packet["upstream"] = upstream
    validate_packet(packet, root)
    (root / "packet.json").write_bytes(canonical(packet))
    (root / "import.json").write_bytes(
        canonical(dict(packet_sha256=canonical_hash(packet), synthetic_fixture=True))
    )
    return packet


class InitialPacketProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.packet = write_import_seed(self.root)
        self.original = deepcopy(self.packet)
        self.import_bytes = {
            path.name: path.read_bytes() for path in self.root.iterdir()
        }
        self.policy = {"packet_profile": "scientific-v3"}

    def assert_import_preserved(self):
        self.assertEqual(self.packet, self.original)
        self.assertEqual(
            {name: (self.root / name).read_bytes() for name in self.import_bytes},
            self.import_bytes,
        )

    def test_default_and_explicit_legacy_preserve_original_packet_and_receipt(self):
        expected = (self.root / "packet.json", canonical_hash(self.packet))
        for policy in ({}, {"packet_profile": "legacy-v2"}):
            with self.subTest(policy=policy):
                path, digest, descriptor = prepare_initial_packet(
                    self.root, policy, self.packet
                )
                self.assertEqual((path, digest, descriptor), (*expected, None))
                self.assertEqual(
                    inspect_initial_packet(self.root, policy, self.packet, descriptor),
                    expected,
                )
                self.assertEqual(read_initial_seed(self.root, digest), self.original)
                self.assertEqual(
                    {path.name for path in self.root.iterdir()}, set(self.import_bytes)
                )
                self.assert_import_preserved()

    def test_explicit_scientific_profile_validates_without_promoting_import(self):
        path, digest, descriptor = prepare_initial_packet(
            self.root, self.policy, self.packet
        )
        raw = path.read_bytes()
        packet = json.loads(raw)
        validate_packet(packet, self.root)
        self.assertEqual(packet["schema_version"], "2.5.0")
        self.assertEqual(
            {key: packet[key] for key in self.original},
            {**self.original, "schema_version": "2.5.0"},
        )
        self.assertEqual(packet["candidates"], [])
        self.assertEqual(packet["prior_work_reviews"], [])
        self.assertIsNone(packet["research_tables"])
        self.assertEqual(digest, canonical_hash(packet))
        self.assertEqual(descriptor["packet_sha256"], digest)
        self.assertEqual(
            descriptor["packet_file_sha256"], hashlib.sha256(raw).hexdigest()
        )
        self.assertEqual(
            descriptor["parent_packet_sha256"], canonical_hash(self.original)
        )
        self.assertIs(descriptor["scientific_quality_verified"], False)
        self.assertIs(descriptor["execution_authorized"], False)
        self.assertEqual(
            inspect_initial_packet(self.root, self.policy, self.packet, descriptor),
            (path, digest),
        )
        self.assert_import_preserved()

    def test_invalid_policy_profile_rejects_without_writing(self):
        for profile in (None, "", "Scientific-v3", True, []):
            with self.subTest(profile=profile):
                policy = {"packet_profile": profile}
                with self.assertRaisesRegex(
                    SessionApiError, "stage2-packet-profile-invalid"
                ):
                    prepare_initial_packet(self.root, policy, self.packet)
                with self.assertRaisesRegex(
                    SessionApiError, "stage2-packet-profile-invalid"
                ):
                    inspect_initial_packet(self.root, policy, self.packet, None)
                self.assertEqual(
                    {path.name for path in self.root.iterdir()}, set(self.import_bytes)
                )
                self.assert_import_preserved()

    def test_formed_seed_cannot_enter_initial_scientific_profile(self):
        formed = deepcopy(self.packet)
        formed["candidates"] = [_candidate("candidate-1")]
        validate_packet(formed, self.root)
        for operation in (
            lambda: prepare_initial_packet(self.root, self.policy, formed),
            lambda: inspect_initial_packet(self.root, self.policy, formed, None),
        ):
            with self.assertRaisesRegex(
                SessionApiError, "stage2-initial-profile-requires-empty-seed"
            ):
                operation()
        self.assertEqual(
            {path.name for path in self.root.iterdir()}, set(self.import_bytes)
        )
        self.assert_import_preserved()

    def test_changed_descriptor_cannot_grant_authority_or_change_parent(self):
        _, _, descriptor = prepare_initial_packet(self.root, self.policy, self.packet)
        for key, value in (
            ("execution_authorized", True),
            ("scientific_quality_verified", True),
            ("parent_packet_sha256", "f" * 64),
            ("transitions", []),
        ):
            with self.subTest(field=key):
                changed = {**descriptor, key: value}
                with self.assertRaisesRegex(
                    SessionApiError, "stage2-initial-profile-binding-differs"
                ):
                    inspect_initial_packet(self.root, self.policy, self.packet, changed)
        self.assert_import_preserved()

    def test_schema_valid_packet_tamper_rejects_even_after_rehashing_descriptor(self):
        path, _, descriptor = prepare_initial_packet(
            self.root, self.policy, self.packet
        )
        changed = json.loads(path.read_bytes())
        changed["comparison"] = "A substituted comparison with no new source evidence."
        validate_packet(changed, self.root)
        raw = canonical(changed)
        path.write_bytes(raw)
        with self.assertRaisesRegex(
            SessionApiError, "stage2-initial-profile-bytes-differ"
        ):
            inspect_initial_packet(self.root, self.policy, self.packet, descriptor)
        rehashed = deepcopy(descriptor)
        rehashed["packet_sha256"] = canonical_hash(changed)
        rehashed["packet_file_sha256"] = hashlib.sha256(raw).hexdigest()
        rehashed["transitions"][-1]["packet_sha256"] = canonical_hash(changed)
        with self.assertRaisesRegex(
            SessionApiError, "stage2-initial-profile-binding-differs"
        ):
            inspect_initial_packet(self.root, self.policy, self.packet, rehashed)
        self.assert_import_preserved()

    def test_semantically_equal_but_changed_raw_bytes_reject(self):
        path, digest, descriptor = prepare_initial_packet(
            self.root, self.policy, self.packet
        )
        packet = json.loads(path.read_bytes())
        path.write_bytes(json.dumps(packet, indent=2).encode("utf-8"))
        self.assertEqual(canonical_hash(json.loads(path.read_bytes())), digest)
        with self.assertRaisesRegex(
            SessionApiError, "stage2-initial-profile-bytes-differ"
        ):
            inspect_initial_packet(self.root, self.policy, self.packet, descriptor)
        self.assert_import_preserved()

    def test_descriptor_cannot_substitute_another_packet_path(self):
        path, _, descriptor = prepare_initial_packet(
            self.root, self.policy, self.packet
        )
        alternate = self.root / "alternate-packet.json"
        alternate.write_bytes(path.read_bytes())
        changed = {**descriptor, "packet_file": alternate.name}
        with self.assertRaisesRegex(
            SessionApiError, "stage2-initial-profile-binding-differs"
        ):
            inspect_initial_packet(self.root, self.policy, self.packet, changed)
        self.assert_import_preserved()

    def test_legacy_policy_rejects_a_rich_profile_descriptor(self):
        _, _, descriptor = prepare_initial_packet(self.root, self.policy, self.packet)
        with self.assertRaisesRegex(
            SessionApiError, "stage2-unexpected-initial-profile"
        ):
            inspect_initial_packet(self.root, {}, self.packet, descriptor)
        self.assert_import_preserved()

    def test_partial_existing_profile_output_is_never_overwritten(self):
        path = self.root / "scientific-initial-packet.json"
        partial = b'{"kind":"Stage2Packet",'
        path.write_bytes(partial)
        with self.assertRaises(FileExistsError):
            prepare_initial_packet(self.root, self.policy, self.packet)
        self.assertEqual(path.read_bytes(), partial)
        self.assert_import_preserved()

    def test_original_seed_reader_rejects_changed_bytes_against_external_hash(self):
        expected = canonical_hash(self.packet)
        changed = {**self.packet, "comparison": "The original import was replaced."}
        (self.root / "packet.json").write_bytes(canonical(changed))
        with self.assertRaisesRegex(SessionApiError, "stage2-initial-seed-differs"):
            read_initial_seed(self.root, expected)


if __name__ == "__main__":
    unittest.main()

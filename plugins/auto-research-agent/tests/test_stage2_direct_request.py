"""Synthetic direct-request integration; no research/model/approval claims."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "cli")]

from stage2_common import Stage2Error, canonical_hash, validate_packet  # noqa: E402
from stage2_check import initialize_run, inspect_run  # noqa: E402
from stage2_check.bibliography import build_bibliography  # noqa: E402
from stage2_ideation.direct_request import prepare_direct_request  # noqa: E402
from stage2_ideation.prompts import build_extraction_task, build_research_task  # noqa: E402
from stage2_live.controller import _initial_review_view_version, _prior_work_completion  # noqa: E402
from stage2_live.source_updates import prepare_source_update  # noqa: E402
from stage2_workflow import initialize_workflow, inspect_workflow, add_snapshot  # noqa: E402
from stage2_workflow.store import _validate_append_only  # noqa: E402
from stage2_common import source_set_hash  # noqa: E402
import test_stage2_scientific_argument as scientific_fixture  # noqa: E402


class Stage2DirectRequestTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.request = self.root / "request.txt"
        self.raw = "請研究一個問題，保留未知。\r\n".encode()
        self.request.write_bytes(self.raw)
        self.digest = hashlib.sha256(self.raw).hexdigest()
        self.result = prepare_direct_request(
            self.request, self.root / "seed", expected_request_sha256=self.digest
        )
        self.packet = json.loads(Path(self.result["packet"]).read_bytes())

    def test_empty_direct_seed_initializes_and_replays_rich_workflow(self):
        manifest = initialize_workflow(
            self.result["packet"],
            self.root,
            self.root / "workflow",
            {},
            {},
            expected_packet_sha256=self.result["packet_sha256"],
        )
        state = inspect_workflow(self.root / "workflow")
        self.assertEqual(state["manifest"], manifest)
        packet = state["latest_snapshot"]["packet"]
        self.assertEqual(packet, self.packet)
        self.assertNotIn("upstream", packet)
        self.assertEqual(packet["brief"]["decisions"], [])
        self.assertEqual(packet["sources"], [])
        self.assertEqual(packet["candidates"], [])

    def test_checker_input_refs_never_claim_stage1_and_reject_rehashed_relabel(self):
        initialize_run(
            self.result["packet"],
            self.root,
            self.root / "checker",
            expected_packet_sha256=self.result["packet_sha256"],
        )
        state = inspect_run(self.root / "checker")
        refs = state["manifest"]["stage_run"]["input_refs"]
        self.assertTrue(
            all(r["producer"] == "stage2-direct-request-handoff" for r in refs)
        )
        manifest = state["manifest"]
        manifest["stage_run"]["input_refs"][0]["producer"] = "stage1-stage2-handoff"
        unsigned = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
        manifest["manifest_sha256"] = canonical_hash(unsigned)
        (self.root / "checker/run_manifest.json").write_text(json.dumps(manifest))
        with self.assertRaises(Stage2Error):
            inspect_run(self.root / "checker")

    def test_external_packet_and_request_hashes_required(self):
        with self.assertRaisesRegex(Stage2Error, "external-hash-mismatch"):
            prepare_direct_request(
                self.request, self.root / "wrong", expected_request_sha256="0" * 64
            )
        with self.assertRaisesRegex(Stage2Error, "expected-packet-sha256-required"):
            initialize_workflow(
                self.result["packet"], self.root, self.root / "unbound", {}, {}
            )

    def test_raw_request_hash_and_origin_not_self_attested(self):
        packet = copy.deepcopy(self.packet)
        packet["entry"]["request_text"] += "changed"
        unsigned = {k: v for k, v in packet["entry"].items() if k != "binding_sha256"}
        packet["entry"]["binding_sha256"] = canonical_hash(unsigned)
        with self.assertRaisesRegex(Stage2Error, "byte-hash-mismatch"):
            validate_packet(packet, self.root)
        packet = copy.deepcopy(self.packet)
        packet["entry"]["stage1_lineage"] = True
        with self.assertRaises(Stage2Error):
            validate_packet(packet, self.root)

    def test_cannot_inject_scope_decisions_or_upstream(self):
        packet = copy.deepcopy(self.packet)
        packet["brief"]["needs"][0]["question"] = "A hidden research hint"
        with self.assertRaisesRegex(Stage2Error, "derived-input-mismatch"):
            validate_packet(packet, self.root)
        packet = copy.deepcopy(self.packet)
        packet["upstream"] = {}
        with self.assertRaises(Stage2Error):
            validate_packet(packet, self.root)

    def test_request_origin_cannot_change_across_snapshots(self):
        other = self.root / "other.txt"
        other.write_bytes(b"Different request")
        result = prepare_direct_request(
            other,
            self.root / "other-seed",
            expected_request_sha256=hashlib.sha256(other.read_bytes()).hexdigest(),
        )
        packet = json.loads(Path(result["packet"]).read_bytes())
        # Even a self-consistent new origin cannot be adopted under an old workflow.
        with self.assertRaises(Stage2Error):
            _validate_append_only(self.packet, packet)

    def test_rich_guidance_extraction_and_prior_work_are_not_silently_disabled(self):
        task = build_research_task(self.packet, "a" * 64)
        self.assertIn("scientific argument", task["prompt"])
        self.assertIn("source-bound matrix", task["prompt"])
        self.assertIn(self.packet["entry"]["request_sha256"], task["prompt"])
        extraction = build_extraction_task("A proposal", self.packet, "a" * 64)
        self.assertEqual(extraction["schema_version"], "1.2.0")
        self.assertEqual(_initial_review_view_version(self.packet), "1.2.0")
        self.assertEqual(
            _prior_work_completion(self.packet, "a" * 64)["status"], "complete"
        )
        self.assertTrue(build_bibliography(self.packet, {}, {})["available"])

    def test_invalid_text_and_existing_seed_fail_without_replacing_output(self):
        before = Path(self.result["packet"]).read_bytes()
        with self.assertRaises(FileExistsError):
            prepare_direct_request(
                self.request, self.root / "seed", expected_request_sha256=self.digest
            )
        self.assertEqual(Path(self.result["packet"]).read_bytes(), before)
        self.request.write_bytes(b"\x00")
        with self.assertRaisesRegex(Stage2Error, "invalid-text"):
            prepare_direct_request(
                self.request,
                self.root / "invalid",
                expected_request_sha256=hashlib.sha256(b"\x00").hexdigest(),
            )
        self.assertFalse((self.root / "invalid").exists())

    def test_formed_direct_packet_keeps_argument_and_prior_work_validation(self):
        fixture = scientific_fixture.Stage2ScientificArgumentTests(
            "test_packet_2_5_is_opt_in_and_requires_a_core_closed_argument"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        packet = copy.deepcopy(fixture.packet)
        packet["schema_version"] = "2.6.0"
        packet.pop("upstream")
        for field in ("entry", "brief", "resources"):
            packet[field] = copy.deepcopy(self.packet[field])
        for field in ("sources", "evidence", "literature", "supplemental_literature"):
            for row in packet[field]:
                row["origin"] = "stage2"
        for row in packet["prior_work_reviews"]:
            row["source_set_sha256"] = source_set_hash(packet)
        validate_packet(packet, fixture.fixture.source_root)
        bibliography = build_bibliography(
            packet,
            {s["source_id"]: s for s in packet["sources"]},
            {e["evidence_id"]: e for e in packet["evidence"]},
        )
        self.assertTrue(bibliography["available"])
        invalid = copy.deepcopy(packet)
        invalid["candidates"][0]["scientific_argument"]["questions"][0]["priority"] = (
            "secondary"
        )
        invalid["prior_work_reviews"][0]["candidate_sha256"] = canonical_hash(
            invalid["candidates"][0]
        )
        with self.assertRaisesRegex(Stage2Error, "requires a core question"):
            validate_packet(invalid, fixture.fixture.source_root)
        invalid = copy.deepcopy(packet)
        invalid["sources"][0]["origin"] = "stage1"
        with self.assertRaisesRegex(Stage2Error, "cannot-claim-stage1-origin"):
            validate_packet(invalid, fixture.fixture.source_root)

    def test_empty_seed_acquires_source_through_existing_public_transition(self):
        fixture = scientific_fixture.Stage2ScientificArgumentTests(
            "test_packet_2_5_is_opt_in_and_requires_a_core_closed_argument"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        source = copy.deepcopy(fixture.packet["sources"][0])
        source["origin"] = "stage2"
        evidence = copy.deepcopy(fixture.packet["evidence"])
        for row in evidence:
            row["origin"] = "stage2"
        literature = copy.deepcopy(fixture.packet["literature"][0])
        literature["origin"] = "stage2"
        initialize_workflow(
            self.result["packet"],
            self.root,
            self.root / "workflow",
            {},
            {},
            expected_packet_sha256=self.result["packet_sha256"],
        )
        before = inspect_workflow(self.root / "workflow")
        addition = {
            "source": source,
            "evidence": evidence,
            "literature": literature,
            "raw_path": str(fixture.fixture.source_root / source["path"]),
            "acquisition": {
                "status": "obtained",
                "url": "https://example.org/fixture",
                "retrieved_at": "2026-10-21T00:00:00Z",
                "raw_sha256": source["sha256"],
                "identity_status": "matched",
                "evidence_level": source["evidence_level"],
                "reason": "Deterministic source transition fixture; no live acquisition.",
                "action_ref": "synthetic-acquisition-1",
            },
        }
        result = prepare_source_update(
            self.packet,
            self.root,
            [addition],
            [],
            {},
            self.root / "source-update",
            expected_packet_sha256=canonical_hash(self.packet),
        )
        event = add_snapshot(
            self.root / "workflow",
            result["packet_path"],
            result["source_root"],
            "New saved source; no candidate yet.",
            result["impact"],
            before["head_sha256"],
        )
        after = inspect_workflow(self.root / "workflow", event["event_sha256"])
        packet = after["latest_snapshot"]["packet"]
        self.assertEqual(packet["entry"], self.packet["entry"])
        self.assertEqual(packet["sources"], [source])
        self.assertEqual(packet["literature"], [literature])
        self.assertTrue(result["review_required"])
        self.assertFalse(result["scientific_quality_verified"])


if __name__ == "__main__":
    unittest.main()

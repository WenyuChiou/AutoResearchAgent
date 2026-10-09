# ruff: noqa: E402 -- import the repository CLI without installing a package.
"""Authenticated native proposal selection and controller integration tests."""

import copy
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stage2_common import Stage2Error
from stage2_live.controller import _ProductionAdapter
from stage2_live.native_proposal import (
    MAX_PROPOSAL_BYTES,
    PROPOSAL_PATH,
    RECOVERY_PROPOSAL_PATH,
    RECOVERY_START_PATH,
    START_PROPOSAL_PATH,
    choose_captured_proposal,
    recover_captured_proposal,
)
from stage2_ideation import build_research_task
from stage2_fixture_helpers import write_stage2_fixture


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class NativeProposalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        # macOS exposes /var through a symlink; bind the real fixture workspace.
        self.root = Path(temporary.name).resolve()

    def capture(self, name="capture", *, proposal=b"Full proposal.\n", final="Saved."):
        root = self.root / name
        end = root / "archive" / "workspace-end"
        start = root / "archive" / "workspace-start"
        end.mkdir(parents=True)
        start.mkdir(parents=True)
        final_raw = (final + "\n").encode("utf-8")
        (root / "final.txt").write_bytes(final_raw)
        inventory = {"final.txt": digest(final_raw)}
        if proposal is not None:
            path = end / "stage2_proposal.md"
            path.write_bytes(proposal)
            inventory[PROPOSAL_PATH] = digest(proposal)
        return root, {
            "status": "complete",
            "record_sha256_receipt": "a" * 64,
            "event_summary": {"final_output": final},
            "archived_files": inventory,
            "workspace_start": {"kind": "directory", "files": {}},
            "evidence_class": "host-native-capture",
        }

    def recovery_capture(
        self, name="recovery", *, output=b"Recovered proposal.\n", seed=None
    ):
        root, record = self.capture(name, proposal=None, final="Original final answer")
        end = root / "archive" / "workspace-end"
        output_path = end / "output.txt"
        output_path.write_bytes(output)
        output_hash = digest(output)
        record["archived_files"][RECOVERY_PROPOSAL_PATH] = output_hash
        record["workspace_end"] = {
            "kind": "directory",
            "files": {"output.txt": output_hash},
        }
        if seed is not None:
            start_path = root / RECOVERY_START_PATH
            start_path.write_bytes(seed)
            seed_hash = digest(seed)
            record["archived_files"][RECOVERY_START_PATH] = seed_hash
            record["workspace_start"]["files"]["output.txt"] = seed_hash
        return root, record, output_hash

    def test_forward_prompt_requires_complete_canonical_workspace_artifact(self):
        packet = write_stage2_fixture(self.root / "prompt-fixture", candidate_count=0)
        packet["schema_version"] = "2.2.0"
        packet["research_tables"] = None
        prompt = build_research_task(packet, "b" * 64)["prompt"]

        self.assertIn("relative path stage2_proposal.md", prompt)
        self.assertIn("complete proposal", prompt)
        self.assertIn("all prose, comparison tables, and references", prompt)
        self.assertIn("Do not substitute a link or summary", prompt)
        self.assertIn("do not reuse or overwrite another seed file", prompt)
        self.assertIn("complete proposal in your final answer", prompt)
        for legacy_version in ("2.0.0", "2.1.0"):
            with self.subTest(version=legacy_version):
                packet["schema_version"] = legacy_version
                legacy_prompt = build_research_task(packet, "b" * 64)["prompt"]
                self.assertNotIn("relative path stage2_proposal.md", legacy_prompt)

    def test_prefers_full_workspace_file_over_brief_final_answer(self):
        root, record = self.capture(proposal=b"Complete file proposal.\n")
        chosen = choose_captured_proposal(root, record)
        self.assertEqual(chosen["text"], "Complete file proposal.\n")
        self.assertEqual(
            chosen["provenance"],
            {
                "kind": "workspace-artifact",
                "path": PROPOSAL_PATH,
                "sha256": digest(b"Complete file proposal.\n"),
            },
        )

    def test_announced_file_hash_alias_preexisting_binary_and_size_fail_closed(self):
        root, record = self.capture("hash")
        (root / PROPOSAL_PATH).write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "sha256-mismatch"):
            choose_captured_proposal(root, record)

        root, record = self.capture("alias")
        target = Path(os.path.abspath(root / PROPOSAL_PATH))
        original_lstat = os.lstat

        def aliased(path):
            status = original_lstat(path)
            if Path(path) == target:
                return SimpleNamespace(
                    st_mode=status.st_mode,
                    st_file_attributes=0x400,
                )
            return status

        with (
            patch("stage2_live.native_proposal.os.lstat", side_effect=aliased),
            self.assertRaisesRegex(Stage2Error, "alias-forbidden"),
        ):
            choose_captured_proposal(root, record)

        root, record = self.capture("preexisting")
        start = root / START_PROPOSAL_PATH
        start.write_text("preexisting", encoding="utf-8")
        record["archived_files"][START_PROPOSAL_PATH] = digest(start.read_bytes())
        record["workspace_start"]["files"]["stage2_proposal.md"] = digest(
            start.read_bytes()
        )
        with self.assertRaisesRegex(Stage2Error, "preexisting-input"):
            choose_captured_proposal(root, record)

        root, record = self.capture("binary", proposal=b"\xff\xfe")
        with self.assertRaisesRegex(Stage2Error, "not-utf8"):
            choose_captured_proposal(root, record)

        oversized = b"x" * (MAX_PROPOSAL_BYTES + 1)
        root, record = self.capture("oversize", proposal=oversized)
        with self.assertRaisesRegex(Stage2Error, "oversize"):
            choose_captured_proposal(root, record)

    def test_absent_workspace_file_uses_full_captured_final_answer(self):
        root, record = self.capture(proposal=None, final="Legacy full final answer")
        chosen = choose_captured_proposal(root, record)
        self.assertEqual(chosen["text"], "Legacy full final answer")
        self.assertEqual(chosen["provenance"]["kind"], "final-answer")
        self.assertEqual(chosen["provenance"]["path"], "final.txt")

    def test_explicit_recovery_authenticates_changed_output_without_mutation(self):
        root, record, expected = self.recovery_capture(seed=b"Seed instructions.\n")
        before_record = copy.deepcopy(record)
        before_files = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

        recovered = recover_captured_proposal(root, record, expected_sha256=expected)

        self.assertEqual(recovered["text"], "Recovered proposal.\n")
        self.assertEqual(
            recovered["provenance"],
            {
                "kind": "recovered-workspace-artifact",
                "path": RECOVERY_PROPOSAL_PATH,
                "sha256": expected,
                "previous_sha256": digest(b"Seed instructions.\n"),
                "record_sha256_receipt": "a" * 64,
                "original_proposal_sha256": record["archived_files"]["final.txt"],
            },
        )
        self.assertEqual(record, before_record)
        self.assertEqual(
            {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            },
            before_files,
        )

        root, record, expected = self.recovery_capture("no-seed")
        recovered = recover_captured_proposal(root, record, expected_sha256=expected)
        self.assertIsNone(recovered["provenance"]["previous_sha256"])

    def test_recovery_rejects_incomplete_capture_and_broken_bindings(self):
        mutations = {
            "start-shape": lambda record, expected: record.update(workspace_start=None),
            "end-shape": lambda record, expected: record.update(workspace_end=[]),
            "status": lambda record, expected: record.update(status="failed"),
            "receipt": lambda record, expected: record.update(
                record_sha256_receipt="bad"
            ),
            "archive-hash": lambda record, expected: record["archived_files"].update(
                {RECOVERY_PROPOSAL_PATH: "c" * 64}
            ),
            "end-hash": lambda record, expected: record["workspace_end"][
                "files"
            ].update({"output.txt": "c" * 64}),
            "missing-archive": lambda record, expected: record["archived_files"].pop(
                RECOVERY_PROPOSAL_PATH
            ),
            "missing-end": lambda record, expected: record["workspace_end"][
                "files"
            ].pop("output.txt"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                root, record, expected = self.recovery_capture(name)
                mutate(record, expected)
                with self.assertRaises(Stage2Error):
                    recover_captured_proposal(root, record, expected_sha256=expected)

        root, record, _ = self.recovery_capture("invalid-explicit-hash")
        with self.assertRaisesRegex(Stage2Error, "artifact-binding-mismatch"):
            recover_captured_proposal(root, record, expected_sha256="bad")

        root, record, expected = self.recovery_capture("altered-output")
        (root / RECOVERY_PROPOSAL_PATH).write_bytes(b"Unrecorded new content.")
        with self.assertRaisesRegex(Stage2Error, "sha256-mismatch"):
            recover_captured_proposal(root, record, expected_sha256=expected)

        root, record, expected = self.recovery_capture("altered-original-final")
        (root / "final.txt").write_bytes(b"Unrecorded final answer.")
        with self.assertRaisesRegex(Stage2Error, "sha256-mismatch"):
            recover_captured_proposal(root, record, expected_sha256=expected)

    def test_recovery_rejects_seed_mismatch_unchanged_and_ghost_start(self):
        root, record, expected = self.recovery_capture(
            "unchanged", output=b"same", seed=b"same"
        )
        with self.assertRaisesRegex(Stage2Error, "unchanged-input"):
            recover_captured_proposal(root, record, expected_sha256=expected)

        root, record, expected = self.recovery_capture("seed-hash", seed=b"seed")
        (root / RECOVERY_START_PATH).write_bytes(b"tampered")
        with self.assertRaisesRegex(Stage2Error, "start-sha256-mismatch"):
            recover_captured_proposal(root, record, expected_sha256=expected)

        root, record, expected = self.recovery_capture("ghost-start")
        record["archived_files"][RECOVERY_START_PATH] = digest(b"ghost")
        with self.assertRaisesRegex(Stage2Error, "start-binding-mismatch"):
            recover_captured_proposal(root, record, expected_sha256=expected)

        root, record, expected = self.recovery_capture(
            "missing-start-archive", seed=b"seed"
        )
        record["archived_files"].pop(RECOVERY_START_PATH)
        with self.assertRaisesRegex(Stage2Error, "start-binding-mismatch"):
            recover_captured_proposal(root, record, expected_sha256=expected)

    def test_recovery_rejects_canonical_or_arbitrary_artifacts(self):
        root, record, expected = self.recovery_capture("canonical")
        canonical = root / PROPOSAL_PATH
        canonical.write_bytes(b"Preferred canonical proposal.\n")
        canonical_hash = digest(canonical.read_bytes())
        record["archived_files"][PROPOSAL_PATH] = canonical_hash
        record["workspace_end"]["files"]["stage2_proposal.md"] = canonical_hash
        with self.assertRaisesRegex(Stage2Error, "canonical-artifact-present"):
            recover_captured_proposal(root, record, expected_sha256=expected)

        root, record, expected = self.recovery_capture("arbitrary")
        arbitrary = root / "archive" / "workspace-end" / "proposal.txt"
        arbitrary.write_bytes(b"arbitrary")
        arbitrary_hash = digest(arbitrary.read_bytes())
        record["archived_files"]["archive/workspace-end/proposal.txt"] = arbitrary_hash
        record["workspace_end"]["files"]["proposal.txt"] = arbitrary_hash
        with self.assertRaisesRegex(Stage2Error, "artifact-binding-mismatch"):
            recover_captured_proposal(root, record, expected_sha256=arbitrary_hash)

    def test_recovery_rejects_invalid_output_content_and_aliases(self):
        for name, output, error in (
            ("binary-output", b"\xff\xfe", "not-utf8"),
            ("empty-output", b" \r\n", "empty"),
            ("oversize-output", b"x" * (MAX_PROPOSAL_BYTES + 1), "oversize"),
        ):
            with self.subTest(name=name):
                root, record, expected = self.recovery_capture(name, output=output)
                with self.assertRaisesRegex(Stage2Error, error):
                    recover_captured_proposal(root, record, expected_sha256=expected)

        for name, alias_target in (
            ("leaf-alias", RECOVERY_PROPOSAL_PATH),
            ("ancestor-alias", "archive/workspace-end"),
        ):
            with self.subTest(name=name):
                root, record, expected = self.recovery_capture(name)
                target = Path(os.path.abspath(root / alias_target))
                original_lstat = os.lstat

                def aliased(path, *, _target=target):
                    status = original_lstat(path)
                    if Path(path) == _target:
                        return SimpleNamespace(
                            st_mode=status.st_mode,
                            st_file_attributes=0x400,
                        )
                    return status

                with (
                    patch("stage2_live.native_proposal.os.lstat", side_effect=aliased),
                    self.assertRaisesRegex(Stage2Error, "alias-forbidden"),
                ):
                    recover_captured_proposal(root, record, expected_sha256=expected)

    def test_production_research_uses_injected_capture_seam_mechanically(self):
        root, record = self.capture(proposal=b"File-backed proposal\n", final="Brief")
        context = {
            "task": {"prompt": "synthetic"},
            "source_root": self.root / "sources",
            "paths": {"workspace": self.root / "workspace", "home": self.root / "home"},
            "spec": {"native": {}},
            "output": root,
        }
        with patch.object(
            _ProductionAdapter, "_capture", return_value=copy.deepcopy(record)
        ):
            result = _ProductionAdapter().research(context)
        self.assertEqual(result["raw_proposal"], "File-backed proposal\n")
        self.assertEqual(result["proposal_provenance"]["kind"], "workspace-artifact")
        self.assertEqual(result["record_sha256_receipt"], "a" * 64)
        self.assertFalse(result["synthetic"])


if __name__ == "__main__":
    unittest.main()

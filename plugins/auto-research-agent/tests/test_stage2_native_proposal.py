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

from stage2_common import Stage2Error
from stage2_live.controller import _ProductionAdapter
from stage2_live.native_proposal import (
    MAX_PROPOSAL_BYTES,
    PROPOSAL_PATH,
    START_PROPOSAL_PATH,
    choose_captured_proposal,
)


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

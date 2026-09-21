"""Consume the public merged audit schema without importing hub internals."""

from pathlib import Path
import sys
import tempfile
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
# ruff: noqa: E402 -- load the repository CLI without installing it.
from stage1_ledger.journal import LedgerError, canonical, digest
from stage1_retrieval.audit import checked, read_audit
from stage1_retrieval.projection import project


def initial_write_failure():
    return dict(
        schema_version="1.0.0",
        type="audit_manifest",
        created_at="2026-01-01T00:00:01Z",
        command_id="a" * 32,
        complete=False,
        outcome="error",
        exit_code=1,
        event_count=0,
        events=dict(path="events.jsonl", bytes=0, sha256=digest(b"")),
    )


class MergedHubContractTests(unittest.TestCase):
    def test_incomplete_zero_event_failure_is_valid_but_never_empty_success(self):
        manifest = initial_write_failure()
        self.assertEqual(checked(manifest), manifest)
        saved = {"audit_manifest.json": canonical(manifest), "events.jsonl": b""}
        with self.assertRaisesRegex(LedgerError, "incomplete-manifest"):
            read_audit(saved=saved)
        result = project(
            saved, backend="openalex", process={"failure": None, "exit_code": 1}
        )
        self.assertEqual(
            result,
            dict(
                records=None,
                paths=[],
                provider_attempts=None,
                http_attempts=None,
                outcome="unknown_error",
                http_status=None,
                error="hub-audit:incomplete-manifest",
            ),
        )

    def test_complete_manifest_still_requires_start_and_finish(self):
        for count in (0, 1):
            with self.subTest(event_count=count):
                manifest = dict(
                    initial_write_failure(), complete=True, event_count=count
                )
                with self.assertRaisesRegex(LedgerError, "hub-audit:schema"):
                    checked(manifest)

    def test_process_failure_retains_manifest_and_replays_without_retry(self):
        from unittest.mock import patch
        from stage1_ledger.store import Ledger
        from stage1_ledger.validation import validate_run
        from stage1_retrieval.runner import execute
        from stage1_retrieval.runtime_identity import capture_identity
        from test_retrieval_execution import runtime

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pin = runtime(root)
            script = root / "synthetic_cli.py"
            script.write_text(
                "import sys,json\nfrom pathlib import Path\n"
                "p=Path(sys.argv[sys.argv.index('--audit-output')+1]); p.mkdir()\n"
                "(p/'events.jsonl').write_bytes(b'')\n"
                "(p/'audit_manifest.json').write_text(json.dumps("
                + repr(initial_write_failure())
                + "),encoding='utf-8')\nprint('[]'); sys.exit(1)\n",
                encoding="utf-8",
            )
            pin["code_identity"] = capture_identity(pin["argv_prefix"])
            ledger = Ledger.create(
                root / "run",
                run_id="synthetic",
                objective="synthetic",
                research_hub_pin=pin,
            )
            query = ledger.start("search", dict(query="synthetic", limit=3))
            completion = ledger.event(
                execute(ledger.root, query, "openalex"), "ActionFinished"
            )
            self.assertEqual(completion["outcome"], "unknown_error")
            self.assertEqual(completion["exit_code"], 1)
            ledger.complete_query(query)
            ledger.extract()
            with patch(
                "subprocess.Popen",
                side_effect=AssertionError("replay must not execute"),
            ):
                report = validate_run(ledger.root)
            self.assertTrue(report["valid"], report)
            self.assertEqual(report["counts"]["backend_failures"], 1)
            self.assertEqual(report["counts"]["works"], 0)
            import json

            receipt = json.loads(ledger.read_ref(completion["execution_ref"]))
            saved = json.loads(
                ledger.read_ref(receipt["audit_files"]["audit_manifest.json"])
            )
            self.assertEqual(saved, initial_write_failure())
            self.assertIsNone(receipt["projection"]["provider_attempts"])
            self.assertNotEqual(
                ledger.checkpoint()["stage_result"]["next_allowed_action"],
                "stop-sufficient",
            )


if __name__ == "__main__":
    unittest.main()

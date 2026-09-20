"""Public execution receipts supplement ledger counts without inventing totals."""

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from test_stage1_ledger import fixture
from stage1_export.bundle import export_run, validate_export
from stage1_ledger.journal import LedgerError, canonical, digest


class NativeCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger, _, _, _ = fixture(self.root / "run")
        self.ledger.checkpoint()
        self.capture = self.root / "capture"
        self.capture.mkdir()
        self.output = self.root / "export"
        self.events = [
            dict(type="thread.started", thread_id="synthetic-thread"),
            dict(type="turn.started"),
            dict(
                type="item.started",
                item=dict(id="a", type="command_execution", status="in_progress"),
            ),
            dict(
                type="item.updated",
                item=dict(id="a", type="command_execution", status="in_progress"),
            ),
            dict(
                type="item.completed",
                item=dict(
                    id="a", type="command_execution", status="completed", exit_code=0
                ),
            ),
            dict(
                type="item.completed",
                item=dict(id="b", type="mcp_tool_call", status="failed"),
            ),
            dict(type="item.completed", item=dict(id="c", type="web_search")),
            dict(
                type="item.completed",
                item=dict(id="d", type="agent_message", text="Synthetic answer"),
            ),
            dict(
                type="turn.completed",
                usage=dict(
                    input_tokens=100,
                    cached_input_tokens=40,
                    output_tokens=20,
                    reasoning_output_tokens=5,
                ),
            ),
        ]
        self.context = dict(
            kind="Stage1NativeCaptureSpec",
            schema_version="1.0.0",
            format="codex-exec-json-v1",
            runtime_version="synthetic-runtime",
            scope="captured-invocation",
            expected_thread_id="synthetic-thread",
            source_run_id=self.ledger.manifest["research_run"]["run_id"],
            source_state_sha256=self.ledger.state_hash(),
            source_journal_sha256=digest(
                (self.ledger.root / "stage_events.jsonl").read_bytes()
            ),
            started_at="2026-01-01T00:00:00Z",
            ended_at="2026-01-01T00:01:30Z",
            exit_code=0,
            events_sha256="0" * 64,
        )

    def write_capture(self):
        raw = b"\n".join(canonical(e) for e in self.events) + b"\n"
        self.context["events_sha256"] = digest(raw)
        (self.capture / "events.jsonl").write_bytes(raw)
        (self.capture / "capture.json").write_bytes(canonical(self.context))

    def export(self):
        self.write_capture()
        return export_run(self.ledger.root, self.output, native_capture=self.capture)

    def native(self):
        return json.loads((self.output / "native_usage.json").read_bytes())

    def test_items_deduplicate_updates_and_tokens_keep_their_reported_scope(self):
        before = (self.ledger.root / "stage_events.jsonl").read_bytes()
        self.assertTrue(self.export()["valid"])
        report = self.native()
        self.assertEqual(report["capture_status"], "complete")
        self.assertEqual(
            report["tool_outcomes"], {"succeeded": 1, "failed": 1, "unknown": 1}
        )
        self.assertEqual(report["observed_tool_items"], 3)
        self.assertEqual(report["reported_turn_usage"]["input_tokens"], 100)
        self.assertEqual(report["elapsed_seconds"], 90)
        self.assertIsNone(report["model_calls"])
        self.assertIsNone(report["cost"])
        efficiency = json.loads((self.output / "efficiency.json").read_bytes())
        self.assertIsNone(efficiency["tokens"])
        self.assertEqual(efficiency["native_capture"]["path"], "native_usage.json")
        self.assertEqual((self.ledger.root / "stage_events.jsonl").read_bytes(), before)

    def test_unknown_events_and_pending_tools_preserve_incomplete_observation(self):
        self.events.pop()
        self.events += [
            dict(type="future.event"),
            dict(
                type="item.started",
                item=dict(id="e", type="command_execution", status="in_progress"),
            ),
        ]
        self.context["exit_code"] = 130
        self.export()
        report = self.native()
        self.assertEqual(report["capture_status"], "incomplete")
        self.assertIn("future.event", report["unknown_event_types"])
        self.assertIsNone(report["reported_turn_usage"])
        self.assertEqual(report["tool_outcomes"]["pending"], 1)

    def test_failed_turn_and_fatal_error_are_not_success(self):
        self.events[-1] = dict(
            type="turn.failed", error=dict(message="Synthetic failure")
        )
        self.events.append(dict(type="error", message="Synthetic terminal failure"))
        self.context["exit_code"] = 1
        self.export()
        self.assertEqual(self.native()["capture_status"], "failed")
        self.assertEqual(self.native()["fatal_error_lines"], [10])
        self.assertIsNone(self.native()["reported_turn_usage"])

    def test_wrong_run_state_thread_hash_and_time_are_rejected(self):
        for key, value in [
            ("source_run_id", "wrong-run"),
            ("source_state_sha256", "f" * 64),
            ("source_journal_sha256", "f" * 64),
            ("expected_thread_id", "wrong-thread"),
            ("ended_at", "2025-01-01T00:00:00Z"),
            ("started_at", "2026-01-01T00:00:00"),
        ]:
            with self.subTest(key=key):
                previous = self.context[key]
                self.context[key] = value
                with self.assertRaises(LedgerError):
                    self.export()
                self.assertFalse(self.output.exists())
                self.context[key] = previous
        self.write_capture()
        (self.capture / "events.jsonl").write_bytes(b"{}\n")
        with self.assertRaisesRegex(LedgerError, "native-event-hash"):
            export_run(self.ledger.root, self.output, native_capture=self.capture)

    def test_duplicate_terminals_multiturn_and_invalid_usage_fail_closed(self):
        original = list(self.events)
        for extra in [
            self.events[4],
            dict(type="turn.started"),
            dict(type="thread.started", thread_id="another"),
        ]:
            with self.subTest(extra=extra):
                self.events = original[:-1] + [extra, original[-1]]
                with self.assertRaises(LedgerError):
                    self.export()
        self.events = original
        for value in [True, -1, "100"]:
            with self.subTest(value=value):
                self.events[-1]["usage"]["input_tokens"] = value
                with self.assertRaises(LedgerError):
                    self.export()

    def test_export_replays_native_bytes_even_after_attacker_rehashes_numbers(self):
        self.export()
        path = self.output / "native_usage.json"
        changed = self.native()
        changed["observed_tool_items"] = 500
        path.write_bytes(canonical(changed) + b"\n")
        manifest_path = self.output / "export_manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        entry = next(e for e in manifest["files"] if e["path"] == path.name)
        entry.update(bytes=path.stat().st_size, sha256=digest(path.read_bytes()))
        manifest_path.write_bytes(canonical(manifest) + b"\n")
        self.assertFalse(validate_export(self.output)["valid"])

    def test_capture_is_optional_and_only_explicit_source_files_are_copied(self):
        (self.capture / "unrelated.txt").write_text(
            "Synthetic private note", encoding="utf-8"
        )
        self.export()
        self.assertFalse((self.output / "native/unrelated.txt").exists())
        old = self.root / "without-native"
        self.assertTrue(export_run(self.ledger.root, old)["valid"])
        self.assertNotIn(
            "native_capture", json.loads((old / "efficiency.json").read_bytes())
        )

    def test_cli_and_malformed_capture_contract(self):
        self.write_capture()
        cli = Path(__file__).resolve().parents[1] / "cli/stage1_export"
        result = subprocess.run(
            [
                sys.executable,
                str(cli),
                "create",
                "--run",
                str(self.ledger.root),
                "--output",
                str(self.output),
                "--native-capture",
                str(self.capture),
            ],
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["valid"])
        for key in ["format", "schema_version"]:
            old = self.context[key]
            self.context[key] = "unknown"
            self.write_capture()
            with self.assertRaisesRegex(LedgerError, "export-schema"):
                export_run(
                    self.ledger.root,
                    self.root / "rejected",
                    native_capture=self.capture,
                )
            self.context[key] = old
        for raw in [b'{"type":', b"{}\n", b"[]\n", b'{"type":"a","type":"b"}\n']:
            (self.capture / "events.jsonl").write_bytes(raw)
            self.context["events_sha256"] = digest(raw)
            (self.capture / "capture.json").write_bytes(canonical(self.context))
            with self.assertRaises(LedgerError):
                export_run(
                    self.ledger.root,
                    self.root / "rejected",
                    native_capture=self.capture,
                )


if __name__ == "__main__":
    unittest.main()

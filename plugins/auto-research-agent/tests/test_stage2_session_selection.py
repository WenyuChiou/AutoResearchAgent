"""Authenticated session ownership stays separate from unrelated body parsing."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
# ruff: noqa: E402
from stage2_common import Stage2Error
from stage2_live.environment import verify_environment_capture
from stage2_live.preflight import PreflightError, _actual_runtime, _load_jsonl
from stage2_live.session_selection import select_production_session


def metadata(identity, parent=None):
    payload = {"id": identity}
    if parent is not None:
        payload["source"] = {"subagent": {"thread_spawn": {"parent_thread_id": parent}}}
    return {"type": "session_meta", "payload": payload}


TRUNCATED_BODY = (
    '{"timestamp":"2026-10-09T20:47:10Z","ordinal":81,"type":"event_msg",'
    '"payload":{"type":"item_completed","thread_id":"old-thread",'
    '"item":{"type":"CommandExecution","command":"unfinished'
)


class ProductionSessionSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sessions = self.root / "archive/native-sessions"
        self.sessions.mkdir(parents=True)
        self.context = {
            "model": "m",
            "effort": "high",
            "sandbox_policy": {"type": "workspace-write", "network_access": True},
        }
        self.primary = [
            metadata("current-thread"),
            {"type": "turn_context", "payload": self.context},
        ]
        self.write("unrelated-filename.jsonl", self.primary)

    def write(self, name, rows, suffix=""):
        path = self.sessions / name
        path.write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n" + suffix,
            encoding="utf-8",
        )
        return path

    def verify_environment(self, production=True):
        stable = {"codex_home": "home", "workspace": "workspace", "config_bindings": {}}
        actual = {
            "stable_request_binding": stable,
            "started_at": "2026-10-09T01:00:00+00:00",
            "event_summary": {"thread_id": "current-thread"},
        }
        prior = {
            "stable_request_binding": stable,
            "ended_at": "2026-10-09T00:00:00+00:00",
        }
        kind = "Stage2ProductionRuntime" if production else "Stage2Runtime"
        report = {
            "kind": kind + "Preflight",
            "runtime_gate": True,
            "formal_ready": False,
            "actual_runtime": _actual_runtime(self.context, "workspace"),
        }
        if production:
            report.update(
                validation_scope="production-single",
                filesystem_read_isolation="not-assessed",
                quality_improvement="not-established",
            )
        preflight = {
            "report": {},
            "capture_dir": "prior",
            "receipt": "b" * 64,
            "probe_spec": {"kind": kind + "ProbeSpec", "schema_version": "1.0.0"},
            "inventory_receipt": {},
        }
        with (
            patch("stage2_live.environment.verify_preflight", return_value=report),
            patch(
                "stage2_live.environment.verify_capture",
                side_effect=[(actual, ""), (prior, "")],
            ),
        ):
            return verify_environment_capture(self.root, "a" * 64, preflight, None)

    def test_unrelated_truncated_body_preserved_but_formal_stays_strict(self):
        old = self.write("old.jsonl", [metadata("old-thread")], TRUNCATED_BODY)
        before = old.read_bytes()
        self.assertEqual(
            self.verify_environment(),
            {
                "status": "verified",
                "thread_id": "current-thread",
                "inventory_sha256": None,
                "inventory_status": "not-captured",
            },
        )
        self.assertEqual(
            select_production_session(self.root, "current-thread"), self.primary
        )
        self.assertEqual(old.read_bytes(), before)
        with self.assertRaisesRegex(PreflightError, "malformed native session JSONL"):
            self.verify_environment(production=False)

    def test_literal_lf_records_preserve_unicode_separators_in_all_bodies(self):
        for separator in ("\u0085", "\u2028", "\u2029"):
            with self.subTest(separator=repr(separator)):
                text = "before" + separator + "after"
                body = {
                    "type": "event_msg",
                    "payload": {"type": "message", "text": text},
                }
                selected = [*self.primary, body]
                old = [metadata("old-thread"), copy.deepcopy(body)]
                for name, rows in (
                    ("unrelated-filename.jsonl", selected),
                    ("old.jsonl", old),
                ):
                    path = self.sessions / name
                    raw = (
                        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
                        + "\n"
                    ).encode("utf-8")
                    path.write_bytes(raw)
                    # Formal replay uses this same strict native-session loader.
                    self.assertEqual(_load_jsonl(path), rows)
                    self.assertEqual(path.read_bytes(), raw)
                self.assertEqual(
                    select_production_session(self.root, "current-thread"), selected
                )
                self.assertEqual(self.verify_environment()["status"], "verified")

    def test_unicode_body_does_not_hide_later_conflicting_ownership(self):
        for separator in ("\u0085", "\u2028", "\u2029"):
            with self.subTest(separator=repr(separator)):
                rows = [
                    metadata("old-thread"),
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "message",
                            "text": "body" + separator + "text",
                        },
                    },
                    metadata("current-thread"),
                ]
                path = self.sessions / "old.jsonl"
                raw = (
                    "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
                    + "\n"
                ).encode("utf-8")
                path.write_bytes(raw)
                with self.assertRaisesRegex(PreflightError, "conflicting identities"):
                    select_production_session(self.root, "current-thread")
                self.assertEqual(path.read_bytes(), raw)

    def test_crlf_records_pass_but_cr_only_records_are_not_jsonl(self):
        path = self.sessions / "unrelated-filename.jsonl"
        rows = [
            *self.primary,
            {"type": "event_msg", "payload": {"text": "before\u0085after"}},
        ]
        raw = (
            "\r\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\r\n"
        ).encode("utf-8")
        path.write_bytes(raw)
        self.assertEqual(_load_jsonl(path), rows)
        self.assertEqual(select_production_session(self.root, "current-thread"), rows)
        self.assertEqual(path.read_bytes(), raw)

        raw = "\r".join(json.dumps(row) for row in rows).encode("utf-8")
        path.write_bytes(raw)
        with self.assertRaisesRegex(PreflightError, "malformed native session JSONL"):
            _load_jsonl(path)
        with self.assertRaisesRegex(
            PreflightError, "unclassified native session JSONL"
        ):
            select_production_session(self.root, "current-thread")
        self.assertEqual(path.read_bytes(), raw)

    def test_selected_primary_and_child_bodies_are_strict(self):
        for rows in (
            [metadata("current-thread")],
            [metadata("parent"), metadata("current-thread", "parent")],
        ):
            with self.subTest(rows=rows):
                self.write("unrelated-filename.jsonl", rows, TRUNCATED_BODY)
                with self.assertRaisesRegex(
                    PreflightError, "malformed native session JSONL"
                ):
                    self.verify_environment()

    def test_known_nested_and_array_body_strings_can_be_deferred(self):
        for body in (
            '"type":"function_call","arguments":"unfinished',
            '"type":"function_call_output","output":"unfinished',
            '"type":"message","content":[{"type":"text","text":"unfinished',
            '"type":"reasoning","summary":[{"type":"summary_text","text":"unfinished',
        ):
            with self.subTest(body=body):
                suffix = '{"type":"response_item","payload":{' + body
                self.write("old.jsonl", [metadata("old-thread")], suffix)
                self.assertEqual(
                    self.verify_environment()["thread_id"], "current-thread"
                )

    def test_unclassified_or_malformed_ownership_always_blocks(self):
        for rows, suffix in (
            ([], TRUNCATED_BODY),
            ([], '{"type":"session_meta","payload":{"id":"unfinished'),
            (
                [metadata("old-thread")],
                '{"type":"session_meta","payload":{"id":"unfinished',
            ),
            (
                [metadata("old-thread")],
                '{"type":"turn_context","payload":{"model":"unfinished',
            ),
            (
                [metadata("old-thread")],
                '{"type":"unknown","payload":{"type":"message","text":"unfinished',
            ),
            (
                [metadata("old-thread")],
                '{"type":"event_msg","payload":{"type":"session_meta","id":"unfinished',
            ),
            ([{"type": "session_meta", "payload": {}}], TRUNCATED_BODY),
            ([metadata("old-thread")], "null"),
            (
                [metadata("old-thread")],
                '{"type":"event_msg","payload":{"type":"message","text":INVALID}}',
            ),
            (
                [metadata("old-thread")],
                '{"type":"event_msg","payload":{"type":"message","text":"complete"}} extra',
            ),
        ):
            with self.subTest(rows=rows, suffix=suffix):
                self.write("old.jsonl", rows, suffix)
                with self.assertRaises(PreflightError):
                    self.verify_environment()

    def test_later_metadata_is_checked_after_truncated_body(self):
        for later, error in (
            (metadata("current-thread"), "conflicting identities"),
            (metadata("other-child", "parent"), "child session.*conflicting"),
        ):
            with self.subTest(later=later):
                rows = [metadata("old-thread")]
                if "source" in later["payload"]:
                    rows.append(metadata("old-child", "parent"))
                self.write("old.jsonl", rows, TRUNCATED_BODY + "\n" + json.dumps(later))
                with self.assertRaisesRegex(PreflightError, error):
                    self.verify_environment()

    def test_duplicate_structural_members_cannot_hide_truncated_metadata(self):
        for suffix in (
            '{"type":"event_msg","type":"session_meta","payload":{"type":"message","id":"current-thread","text":"unfinished',
            '{"type":"event_msg","payload":{"type":"message","type":"session_meta","id":"current-thread","text":"unfinished',
            '{"type":"event_msg","payload":{"type":"message"},"payload":{"type":"session_meta","id":"current-thread","text":"unfinished',
            '{"type":"event_msg","payload":{"type":"message","content":{"type":"text","text":"complete"},"content":{"text":"unfinished',
        ):
            with self.subTest(suffix=suffix):
                self.write("old.jsonl", [metadata("old-thread")], suffix)
                with self.assertRaisesRegex(
                    PreflightError, "unclassified native session"
                ):
                    self.verify_environment()

    def test_complete_duplicate_ownership_cannot_hide_selected_session(self):
        for raw in (
            '{"type":"session_meta","payload":{"id":"current-thread","id":"old-thread"}}',
            '{"type":"session_meta","payload":{"id":"old-thread","id":"current-thread"}}',
            '{"type":"session_meta","payload":{"id":"current-thread","\\u0069d":"old-thread"}}',
            '{"type":"session_meta","payload":{"id":"current-thread"},"payload":{"id":"old-thread"}}',
            '{"type":"session_meta","type":"event_msg","payload":{"type":"message","id":"current-thread","text":"complete"}}',
            '{"type":"event_msg","payload":{"type":"session_meta","type":"message","id":"current-thread","text":"complete"}}',
            '{"type":"session_meta","payload":{"id":"child","source":{"subagent":{"thread_spawn":{"parent_thread_id":"current-thread","parent_thread_id":"old-thread"}}}}}',
        ):
            with self.subTest(raw=raw):
                (self.sessions / "ambiguous.jsonl").write_text(
                    raw + "\n" + TRUNCATED_BODY + "\n", encoding="utf-8"
                )
                with self.assertRaisesRegex(
                    PreflightError, "unclassified native session JSONL"
                ):
                    self.verify_environment()

    def test_truncation_must_be_a_value_in_a_known_body_field(self):
        for suffix in (
            '{"type":"event_msg","payload":{"type":"message","source":"unfinished',
            '{"type":"event_msg","payload":{"type":"message","thread_id":"unfinished',
            '{"type":"event_msg","payload":{"type":"message","text":"complete","unfinished',
            '{"type":"event_msg","payload":{"type":"message","text":"contains \\"type\\":\\"session_meta\\" unfinished',
        ):
            with self.subTest(suffix=suffix):
                self.write("old.jsonl", [metadata("old-thread")], suffix)
                if "contains" in suffix:
                    self.assertEqual(
                        self.verify_environment()["thread_id"], "current-thread"
                    )
                else:
                    with self.assertRaisesRegex(
                        PreflightError, "unclassified native session"
                    ):
                        self.verify_environment()

    def test_alias_and_inherited_parent_cannot_hide_another_primary(self):
        self.write("alias.jsonl", self.primary)
        with self.assertRaisesRegex(Stage2Error, "primary-session-not-unique"):
            self.verify_environment()
        self.write(
            "alias.jsonl",
            [metadata("current-thread"), metadata("child", "current-thread")],
            TRUNCATED_BODY,
        )
        self.assertEqual(self.verify_environment()["thread_id"], "current-thread")
        self.write(
            "alias.jsonl",
            [metadata("parent"), metadata("current-thread", "parent")],
            TRUNCATED_BODY,
        )
        with self.assertRaisesRegex(Stage2Error, "primary-session-not-unique"):
            self.verify_environment()

    def test_current_context_still_requires_matching_unambiguous_runtime(self):
        different = copy.deepcopy(self.context)
        different["model"] = "other-model"
        self.write(
            "unrelated-filename.jsonl",
            [
                metadata("current-thread"),
                {"type": "turn_context", "payload": different},
            ],
        )
        with self.assertRaisesRegex(Stage2Error, "effective-policy-differs"):
            self.verify_environment()
        self.write(
            "unrelated-filename.jsonl",
            self.primary + [{"type": "turn_context", "payload": different}],
        )
        with self.assertRaisesRegex(PreflightError, "ambiguous primary turn_context"):
            self.verify_environment()

    def test_external_capture_authentication_precedes_session_selection(self):
        with (
            patch(
                "stage2_live.environment.verify_capture",
                side_effect=Stage2Error("archive-tampered"),
            ),
            patch("stage2_live.environment.select_production_session") as selector,
        ):
            with self.assertRaisesRegex(Stage2Error, "archive-tampered"):
                verify_environment_capture(self.root, "a" * 64, {}, None)
            selector.assert_not_called()


if __name__ == "__main__":
    unittest.main()

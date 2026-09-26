import json
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))

from stage1_ab.native_search import (  # noqa: E402
    native_search_receipt,
    verify_native_search_receipt,
)
from stage1_eval.common import EvaluationError, canonical, sha  # noqa: E402


def line(event):
    return json.dumps(event, separators=(",", ":")).encode()


def completed(event_id, action, **item_fields):
    return {
        "type": "item.completed",
        "item": {
            "id": event_id,
            "type": "web_search",
            "action": action,
            **item_fields,
        },
    }


class NativeSearchCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, event_groups, *, exit_codes=None, run_json=False):
        attempts = []
        exit_codes = exit_codes or [0] * len(event_groups)
        for number, events in enumerate(event_groups, 1):
            raw = b"\n".join(line(event) for event in events) + b"\n"
            name = f"attempt-{number:02d}.jsonl"
            (self.root / name).write_bytes(raw)
            attempts.append(
                {
                    "started_at": f"2026-09-26T00:00:0{number}+00:00",
                    "ended_at": f"2026-09-26T00:00:1{number}+00:00",
                    "exit_code": exit_codes[number - 1],
                    "files": {name: sha(raw)},
                }
            )
        if run_json:
            (self.root / "run.json").write_text(
                json.dumps({"attempts": attempts}), encoding="utf-8"
            )
        return attempts

    def test_actual_action_queries_win_over_abbreviated_query_and_prose_fake(self):
        actual = {
            "type": "search",
            "queries": ["generic method evidence", "generic recent comparison"],
        }
        events = [
            {
                "type": "item.completed",
                "item": {
                    "id": "message-1",
                    "type": "agent_message",
                    "text": "web_search queries=['fabricated prose query']",
                },
            },
            {
                **completed("web-1", actual),
                "item": {**completed("web-1", actual)["item"], "query": "generic…"},
            },
        ]
        attempts = self.save([events], run_json=True)
        receipt = native_search_receipt(self.root, attempts)
        action = receipt["attempts"][0]["actions"][0]
        self.assertEqual(action["raw_action"], actual)
        self.assertEqual(action["queries"], actual["queries"])
        self.assertEqual(receipt["counts"]["completed_search_queries"], 2)
        self.assertEqual(receipt["counts"]["completed_search_actions"], 1)
        self.assertIsNone(receipt["limitations"]["result_count"])
        self.assertEqual(
            receipt["limitations"]["retrieval_failure_state"], "not-exposed"
        )
        raw_line = (self.root / "attempt-01.jsonl").read_bytes().splitlines()[1]
        self.assertEqual(action["raw_line_sha256"], sha(raw_line))
        self.assertFalse(receipt["network_reexecution"])

    def test_multi_attempt_preserves_failures_and_allows_repeated_ids(self):
        first = [
            {"type": "item.started", "item": {"id": "web-1", "type": "web_search"}},
            {"type": "turn.failed", "id": "turn-1", "message": "network unavailable"},
        ]
        second = [
            {"type": "item.started", "item": {"id": "web-1", "type": "web_search"}},
            completed("web-1", {"type": "search", "queries": ["generic retry"]}),
        ]
        attempts = self.save([first, second], exit_codes=[1, 0])
        receipt = native_search_receipt(self.root, attempts)
        self.assertEqual([row["exit_code"] for row in receipt["attempts"]], [1, 0])
        self.assertEqual(receipt["counts"]["started_web_events"], 2)
        self.assertEqual(receipt["counts"]["incomplete_web_events"], 1)
        self.assertEqual(receipt["counts"]["error_events"], 1)
        self.assertEqual(receipt["counts"]["completed_search_actions"], 1)

    def test_partial_other_action_and_missing_queries_are_distinct(self):
        events = [
            {"type": "item.started", "item": {"id": "pending", "type": "web_search"}},
            completed(
                "open-1", {"type": "open_page", "url": "https://example.invalid"}
            ),
            {
                **completed("search-1", {"type": "search"}),
                "item": {
                    **completed("search-1", {"type": "search"})["item"],
                    "query": "abbreviated text must not be used",
                },
            },
            {"type": "error", "id": "error-1", "message": "observed error"},
        ]
        attempts = self.save([events])
        receipt = native_search_receipt(self.root, attempts)
        self.assertEqual(receipt["counts"]["completed_other_actions"], 1)
        self.assertEqual(receipt["counts"]["completed_search_actions"], 1)
        self.assertEqual(receipt["counts"]["completed_search_queries"], 0)
        self.assertEqual(receipt["counts"]["search_actions_missing_queries"], 1)
        self.assertEqual(receipt["counts"]["incomplete_web_events"], 1)
        search = next(
            row
            for row in receipt["attempts"][0]["actions"]
            if row["event_id"] == "search-1"
        )
        self.assertEqual(search["queries"], [])
        self.assertFalse(search["queries_exposed"])

    def test_explicit_structured_results_and_failure_are_not_inferred_from_summary(
        self,
    ):
        events = [
            completed(
                "web-1",
                {"type": "search", "queries": ["generic evidence"]},
                results=[{"url": "https://example.invalid/1"}],
                status="failed",
                error={"message": "provider rejected request"},
                text="summary says many results",
            )
        ]
        attempts = self.save([events])
        receipt = native_search_receipt(self.root, attempts)
        self.assertEqual(receipt["limitations"]["result_count"], 1)
        self.assertEqual(
            receipt["limitations"]["retrieval_failure_state"], "exposed-error"
        )
        self.assertFalse(receipt["limitations"]["search_success_inferred"])

    def test_open_results_cannot_fill_an_unexposed_search_result_count(self):
        attempts = self.save(
            [
                [
                    completed("search", {"type": "search", "queries": ["q"]}),
                    completed(
                        "open", {"type": "open_page"}, results=[{"text": "page"}]
                    ),
                ]
            ]
        )
        receipt = native_search_receipt(self.root, attempts)
        self.assertIsNone(receipt["limitations"]["result_count"])
        self.assertEqual(receipt["counts"]["completed_other_actions"], 1)

    def test_malformed_tampered_and_duplicate_events_fail_closed(self):
        attempts = self.save(
            [[completed("web-1", {"type": "search", "queries": ["q"]})]]
        )
        (self.root / "attempt-01.jsonl").write_bytes(b"not-json\n")
        attempts[0]["files"]["attempt-01.jsonl"] = sha(b"not-json\n")
        with self.assertRaisesRegex(EvaluationError, "invalid JSON"):
            native_search_receipt(self.root, attempts)

        attempts = self.save(
            [[completed("web-1", {"type": "search", "queries": ["q"]})]]
        )
        (self.root / "attempt-01.jsonl").write_bytes(b"tampered")
        with self.assertRaisesRegex(EvaluationError, "hash differs"):
            native_search_receipt(self.root, attempts)

        duplicate = completed("same-id", {"type": "search", "queries": ["q"]})
        attempts = self.save([[duplicate, duplicate]])
        with self.assertRaisesRegex(EvaluationError, "duplicate completed event ID"):
            native_search_receipt(self.root, attempts)

    def test_unsafe_file_and_run_record_mismatch_fail_closed(self):
        attempts = self.save(
            [[completed("web-1", {"type": "search", "queries": ["q"]})]]
        )
        workspace = self.root / "workspace" / "01" / "notes" / "evidence.json"
        workspace.parent.mkdir(parents=True)
        workspace.write_bytes(b"saved workspace evidence")
        attempts[0]["files"]["workspace/01/notes/evidence.json"] = sha(
            workspace.read_bytes()
        )
        receipt = native_search_receipt(self.root, attempts)
        self.assertEqual(receipt["counts"]["completed_search_actions"], 1)

        attempts[0]["files"]["../escape"] = "0" * 64
        with self.assertRaisesRegex(EvaluationError, "unsafe file"):
            native_search_receipt(self.root, attempts)

        attempts = self.save(
            [[completed("web-1", {"type": "search", "queries": ["q"]})]], run_json=True
        )
        attempts[0]["exit_code"] = 9
        with self.assertRaisesRegex(EvaluationError, "differ from run.json"):
            native_search_receipt(self.root, attempts)

    def test_replay_rejects_rehashed_submitted_receipt(self):
        attempts = self.save(
            [[completed("web-1", {"type": "search", "queries": ["q"]})]]
        )
        receipt = native_search_receipt(self.root, attempts)
        self.assertEqual(
            verify_native_search_receipt(self.root, attempts, receipt), receipt
        )
        forged = json.loads(json.dumps(receipt))
        forged["counts"]["completed_search_queries"] = 99
        unsigned = {
            key: value for key, value in forged.items() if key != "receipt_sha256"
        }
        forged["receipt_sha256"] = sha(canonical(unsigned))
        with self.assertRaisesRegex(EvaluationError, "differs from replay"):
            verify_native_search_receipt(self.root, attempts, forged)


if __name__ == "__main__":
    unittest.main()

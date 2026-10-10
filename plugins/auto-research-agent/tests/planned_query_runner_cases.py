"""Core runner hook is before Popen; legacy behavior is not admitted execution."""

import atlas_test_paths  # noqa: F401
import stage1_retrieval.runner as runner
from stage1_ledger.journal import LedgerError
from planned_query_fixture import QueryCase


class PlannedQueryRunnerHookTests(QueryCase):
    def test_false_and_truthy_nonboolean_hook_retain_backend_intent_without_spawn(self):
        for index, decision in enumerate((False, 1)):
            with self.subTest(decision=decision):
                query = self.ledger.start_planned(self.permit["planned_ids"][index])
                with (
                    self.no_probe(),
                    self.fake_runner(),
                    self.assertRaisesRegex(LedgerError, "execution-admission-refused"),
                ):
                    runner.execute(
                        self.ledger_root,
                        query,
                        "openalex",
                        before_spawn=lambda _: decision,
                    )
        self.assertEqual(self.children, [])
        self.assertEqual(len(self.ledger.pending()), 4)

    def test_hook_receives_exact_argv_runtime_query_and_legacy_none_is_retained(self):
        seen = []
        query = self.ledger.start_planned(self.permit["planned_ids"][0])
        with self.no_probe(), self.fake_runner():
            runner.execute(
                self.ledger_root,
                query,
                "openalex",
                before_spawn=lambda event: seen.append(event) or True,
            )
        self.assertEqual(
            set(seen[0]), {"query_id", "backend", "argv", "runtime_sha256"}
        )
        self.assertEqual(seen[0]["query_id"], query)
        self.assertEqual(seen[0]["backend"], "openalex")
        self.assertEqual(seen[0]["runtime_sha256"], self.item["runtime_sha256"])
        self.assertEqual(seen[0]["argv"], self.children[0])
        query = self.ledger.start_planned(self.permit["planned_ids"][1])
        with self.no_probe(), self.fake_runner():
            runner.execute(self.ledger_root, query, "openalex")
        self.assertEqual(len(self.children), 2)

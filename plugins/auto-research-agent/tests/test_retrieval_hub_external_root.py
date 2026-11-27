"""The retrieval child must be allowed a research-hub root outside HOME (no network)."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_retrieval_execution import _FixedLedgerClock, runtime
from stage1_ledger.store import Ledger
from stage1_retrieval.runner import execute

HUB = importlib.util.find_spec("research_hub") is not None
FLAG = "RESEARCH_HUB_ALLOW_EXTERNAL_ROOT"
REAL_POPEN = subprocess.Popen


class HubExternalRootTests(unittest.TestCase):
    def setUp(self):
        clock = patch("stage1_ledger.journal.datetime", _FixedLedgerClock)
        clock.start()
        self.addCleanup(clock.stop)

    def child_environment(self):
        """Run one synthetic search and return the environment its child received."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ledger = Ledger.create(
                root / "run",
                run_id="synthetic",
                objective="Synthetic query",
                research_hub_pin=runtime(root),
            )
            query = ledger.start("search", dict(query="synthetic query", limit=3))
            seen = []

            def spy(argv, **options):
                # The identity probe also uses Popen (no env); only the search child has one.
                if "env" in options:
                    seen.append(dict(options["env"]))
                return REAL_POPEN(argv, **options)

            with patch("stage1_retrieval.runner.subprocess.Popen", side_effect=spy):
                execute(ledger.root, query, "openalex")
        self.assertEqual(len(seen), 1)
        return seen[0]

    def test_child_environment_allows_external_root_even_if_caller_disabled_it(self):
        for caller in (None, "0", "no"):
            with self.subTest(caller=caller), patch.dict(os.environ):
                os.environ.pop(FLAG, None)
                if caller is not None:
                    os.environ[FLAG] = caller
                env = self.child_environment()
                self.assertEqual(env[FLAG], "1")
                self.assertEqual(env["RESEARCH_HUB_NO_ZOTERO"], "1")
                self.assertTrue(env["RESEARCH_HUB_CONFIG"].endswith("config.json"))

    @unittest.skipUnless(HUB, "research_hub is not installed in this environment")
    def test_hub_config_check_passes_with_that_environment_and_fails_without(self):
        with patch.dict(os.environ):
            os.environ.pop(FLAG, None)
            flag = self.child_environment()[FLAG]
        from research_hub.config import HubConfig

        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            root, home = base / "kb", base / "home"
            root.mkdir()
            home.mkdir()
            config = base / "hub-config.json"
            config.write_text(
                json.dumps({"knowledge_base": {"root": str(root)}}), encoding="utf-8"
            )
            wanted = {"RESEARCH_HUB_CONFIG": str(config), "RESEARCH_HUB_NO_ZOTERO": "1"}
            # HOME is a sibling directory, so the root is outside it. Only the config
            # is loaded: no search, no network.
            with patch.object(Path, "home", return_value=home):
                with patch.dict(os.environ, wanted):
                    os.environ.pop(FLAG, None)
                    with self.assertRaisesRegex(ValueError, "outside HOME"):
                        HubConfig()
                with patch.dict(os.environ, {**wanted, FLAG: flag}):
                    self.assertEqual(Path(HubConfig().root).resolve(), root.resolve())


if __name__ == "__main__":
    unittest.main()

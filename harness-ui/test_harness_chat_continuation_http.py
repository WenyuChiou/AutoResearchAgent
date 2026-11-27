"""Continuation grant through the real startup wiring and the real HTTP routes; scripted Codex only.

The old test of this path was deleted together with the write tools it also covered. This one
covers the read-only chat: a pinned contract, a signed permit receipt and key, the original
budget ledger, and a ``--chat-root`` that must never be created.
"""

# ruff: noqa: E402 -- the plugin and Wiki use repository-local imports.
import hashlib
import hmac
from pathlib import Path
import sqlite3
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(REPO / "plugins/auto-research-agent/cli"),
    str(REPO / "plugins/auto-research-agent/tests"),
]

import chat_test_fixtures as fixtures
from current_chat_host import install_wiki_chat
from harness_chat_continuation import digest, encoded
from harness_chat_permit import canonical
from test_harness_chat_continuation import MemoryRpc, identity
from test_harness_chat_http import HostFixture


class ContinuationHttp(unittest.TestCase):
    def build(self, fx):
        root = fx.root / "cont"
        owner_dir = root / "original-owner"
        owner_dir.mkdir(parents=True)
        self.owner = owner_dir / "conversations.sqlite3"
        self.budget = root / "old-budget.sqlite3"
        for name in ("codex.exe", "config.toml", "module.py"):
            (root / name).write_text("fixture-only-not-executable", encoding="utf-8")
        self.modules = {"fixture_module": str(root / "module.py")}
        manifest = dict(
            kind="V9ChatRuntimeBinding",
            version=1,
            executable=identity(root / "codex.exe"),
            config=identity(root / "config.toml"),
            modules={"fixture_module": identity(root / "module.py")},
        )
        (root / "binding.json").write_bytes(encoded(manifest))
        old = dict(
            executable=str(root / "codex.exe"),
            config_path=str(root / "config.toml"),
            model="old-model",
            effort="high",
            expires_at=1,
            max_turns=3,
            turn_seconds=120,
            previous_calls=5,
            previous_seconds=840,
            max_calls=8,
            max_seconds=1200,
            pins={},
            authorization="fixture-historical-only",
            budget_path=str(self.budget),
        )
        (root / "old-operator.json").write_bytes(encoded(old))
        old_pin = digest((root / "old-operator.json").read_bytes())
        db = sqlite3.connect(self.owner)
        db.executescript(
            "CREATE TABLE sessions(id TEXT PRIMARY KEY,body TEXT NOT NULL);"
            "CREATE TABLE turns(id TEXT PRIMARY KEY,session_id TEXT,body TEXT NOT NULL);"
            "CREATE TABLE events(seq INTEGER PRIMARY KEY,turn_id TEXT,body TEXT NOT NULL);"
        )
        db.commit()
        db.close()
        db = sqlite3.connect(self.budget)
        db.execute(
            "CREATE TABLE budget(id INTEGER PRIMARY KEY,pin TEXT,owner TEXT,turns INTEGER,seconds INTEGER)"
        )
        db.execute(
            "INSERT INTO budget VALUES(1,?,?,2,240)",
            (old_pin, str(self.owner.resolve())),
        )
        db.commit()
        db.close()
        now = time.time()
        scope = dict(
            id="fixture-only-chat-lease-0001",
            issued_at=now - 5,
            expires_at=now + 300,
            principal=fixtures.PRINCIPAL,
            bindings=[fx.binding()],
            money_cap_usd=None,
            stages=[1, 2],
            actions=["state", "materials", "read_material"],
            model="fixture-model",
            effort="high",
            expected_account_sha256=digest(
                encoded({"type": "chatgpt", "identity": "fixture@example.invalid"})
            ),
            model_messages_authorized=True,
            research_execution=False,
            max_turns=3,
            turn_seconds=120,
            previous_calls=5,
            previous_seconds=840,
            max_calls=8,
            max_seconds=1200,
        )
        contract = dict(
            kind="V9ChatContinuation",
            version=3,
            predecessor=identity(root / "old-operator.json"),
            budget=dict(
                path=str(self.budget),
                owner=str(self.owner),
                identity_pin=old_pin,
                minimum_turns=2,
                minimum_seconds=240,
            ),
            binding=identity(root / "binding.json"),
            scope=scope,
            authorization=dict(ref="synthetic-test-only-not-human-approval"),
        )
        contract_path = root / "FIXTURE-DO-NOT-ACTIVATE.json"
        contract_path.write_bytes(encoded(contract))
        pin = digest(contract_path.read_bytes())
        private = root / "private"
        private.mkdir()
        key = b"0123456789abcdef0123456789abcdef"
        (private / "synthetic.key").write_bytes(key)
        request = dict(
            kind="V9ChatContinuationPermissionCheck",
            contract_sha256=pin,
            contract=contract,
            research_execution=False,
        )
        receipt = dict(
            kind="V9LocalChatOnlyPermit",
            version=1,
            contract_sha256=pin,
            request_sha256=hashlib.sha256(canonical(request)).hexdigest(),
            authorization_source_sha256="b" * 64,
            issued_at=int(now) - 4,
            expires_at=int(now) + 280,
        )
        receipt["signature"] = hmac.new(
            key, canonical(receipt), hashlib.sha256
        ).hexdigest()
        receipt_path = root / "receipt.json"
        receipt_path.write_bytes(canonical(receipt))
        self.never = fx.root / "chat-root-must-not-exist"
        return SimpleNamespace(
            chat_config=contract_path,
            chat_config_sha256=pin,
            chat_root=self.never,
            chat_permit_receipt=receipt_path,
            chat_permit_receipt_sha256=hashlib.sha256(
                receipt_path.read_bytes()
            ).hexdigest(),
            chat_permit_key=private / "synthetic.key",
        )

    def ledger(self):
        connection = sqlite3.connect(self.budget)
        try:
            return connection.execute(
                "SELECT turns,seconds,owner FROM budget WHERE id=1"
            ).fetchone()
        finally:
            connection.close()

    def test_startup_options_then_http_send_spends_the_old_ledger_not_chat_root(self):
        fx = HostFixture(self)
        options = self.build(fx)
        with patch(
            "harness_chat_runtime.runtime_module_paths", return_value=self.modules
        ):
            service = install_wiki_chat(
                fx.host, fx.store, options, rpc_factory=lambda record: MemoryRpc(record)
            )
        self.addCleanup(service.close)
        self.assertIsNotNone(service.spec, getattr(service, "reason", None))
        path = "/api/v9/chat/state?project=" + fx.ref + "&stage="
        code, state = fx.call(path + "1")
        self.assertEqual(
            (code, state["panel_state"], state["can_send"]), (200, "ready", True), state
        )
        self.assertTrue(state["budget_identity_preserved"])
        code, turn = fx.call("/api/v9/chat/send", fx.send_body())
        self.assertEqual(code, 200, turn)
        deadline = time.monotonic() + 8
        row = service.get("turns", turn["id"])
        while row["status"] not in {"completed", "failed", "unknown"}:
            self.assertLess(time.monotonic(), deadline, row)
            time.sleep(0.02)
            row = service.get("turns", turn["id"])
        self.assertEqual(row["status"], "completed", row)
        spent = self.ledger()
        self.assertEqual(spent[:2], (3, 360), "the reservation lands on the original ledger")
        self.assertEqual(spent[2], str(self.owner.resolve()))
        self.assertFalse(self.never.exists(), "--chat-root is ignored and never created")
        connection = sqlite3.connect(self.owner)
        try:
            count = connection.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 1, "the turn is recorded in the original conversation store")
        # Stages outside the grant stay closed.
        self.assertNotEqual(fx.call(path + "3")[1]["panel_state"], "ready")

    def test_a_revoked_receipt_leaves_the_inert_service_and_spends_nothing(self):
        fx = HostFixture(self)
        options = self.build(fx)
        Path(str(options.chat_permit_receipt) + ".revoked").write_text("operator", encoding="utf-8")
        with patch(
            "harness_chat_runtime.runtime_module_paths", return_value=self.modules
        ):
            service = install_wiki_chat(fx.host, fx.store, options)
        self.addCleanup(service.close)
        self.assertIsNone(service.spec)
        code, state = fx.call("/api/v9/chat/state?project=" + fx.ref + "&stage=1")
        self.assertEqual((code, state["panel_state"], state["can_send"]), (200, "not-configured", False))
        self.assertEqual(fx.call("/api/v9/chat/send", fx.send_body())[0], 409)
        self.assertEqual(self.ledger()[:2], (2, 240))
        self.assertFalse(self.never.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Chat service against the real material store and a scripted Codex transcript; no model, no network."""

# ruff: noqa: E402 -- the plugin and Wiki use repository-local imports.
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time
import unittest

from chat_test_fixtures import PRINCIPAL, ChatFixture, FakeRpc
from harness_chat import ChatService

READ_NOTES = lambda fx: dict(action="read_material", id=fx.text["id"], note="")  # noqa: E731


class ChatServiceTests(unittest.TestCase):
    def setUp(self):
        self.fx = ChatFixture(self)

    def test_read_tool_persistent_thread_and_stage_isolation(self):
        fx = self.fx
        service = fx.service(action=READ_NOTES(fx))
        first = fx.finished(service, fx.send(service))
        self.assertEqual(first["status"], "completed", first)
        value = first["outputs"][0]["value"]
        self.assertEqual(value["material_id"], fx.text["id"])
        self.assertTrue(value["text"].startswith("Saved reading note"))
        self.assertFalse(value["research_generated"])
        self.assertFalse(value["execution_authorized"])
        second = fx.finished(
            service,
            fx.send(service, key="unique-request-0002", session=first["session_id"]),
        )
        self.assertEqual(second["thread_id"], first["thread_id"])
        self.assertEqual(fx.rpcs[-1].resumed, first["thread_id"])
        self.assertEqual(len(service.status(fx.ref, 2, PRINCIPAL)["turns"]), 0)
        restored = fx.service()
        self.assertEqual(len(restored.status(fx.ref, 1, PRINCIPAL)["turns"]), 2)
        self.assertFalse(restored.running)

    def test_wrong_native_binding_held_and_readonly_recovery(self):
        fx = self.fx
        service = fx.service(
            action=dict(action="state", id="", note=""), wrong_binding=True
        )
        turn = fx.finished(service, fx.send(service))
        self.assertEqual(turn["status"], "unknown")
        with self.assertRaisesRegex(ValueError, "unresolved"):
            fx.send(service, key="unique-request-0002")
        result = service.reconcile(turn["id"])
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("turn/start", fx.rpcs[-1].methods)
        self.assertNotIn("thread/resume", fx.rpcs[-1].methods)
        self.assertEqual(service.status(fx.ref, 1, PRINCIPAL)["reserved_turns"], 1)

    def test_other_project_material_and_expired_lease(self):
        fx = self.fx
        fx.projects.add("project-beta", "pid-beta")
        other = fx.tools.context("project-beta", 1)
        with self.assertRaisesRegex(ValueError, "binding"):
            fx.tools.call(
                other, dict(action="read_material", id=fx.text["id"], note="")
            )
        service = fx.service(fx.grant(expires_at=time.time() - 1))
        with self.assertRaisesRegex(ValueError, "lease-expired"):
            fx.send(service)
        self.assertEqual(fx.rpcs, [])

    def test_shared_budget_cannot_be_reset_by_new_material_root(self):
        fx = self.fx
        service = fx.service()
        fx.finished(service, fx.send(service))
        with self.assertRaisesRegex(ValueError, "another-store"):
            ChatService(
                fx.root / "other-chat",
                fx.tools,
                fx.grant(),
                rpc_factory=lambda r: FakeRpc(r),
            )
        self.assertEqual(service.status(fx.ref, 1, PRINCIPAL)["reserved_turns"], 1)

    def test_native_question_and_interrupt(self):
        fx = self.fx
        service = fx.service(question=True)
        turn = fx.send(service)
        pending = fx.wait(service, turn, {"waiting"})["pending"]
        service.answer(
            dict(
                turn_id=turn["id"],
                request_id=pending["id"],
                request_sha256=pending["sha256"],
                value={"scope": "Current topic only"},
            )
        )
        self.assertEqual(fx.finished(service, turn)["status"], "completed")
        again = fx.send(service, key="unique-request-0002", session=turn["session_id"])
        fx.wait(service, again, {"waiting"})
        service.stop(again["id"])
        self.assertEqual(fx.finished(service, again)["status"], "interrupted")

    def test_two_service_instances_cannot_admit_concurrent_turns(self):
        fx = self.fx
        first, second = fx.service(question=True), fx.service(question=True)
        gate = threading.Barrier(2)

        def submit(service, key):
            gate.wait()
            try:
                return fx.send(service, key=key)
            except ValueError as exc:
                return str(exc)

        with ThreadPoolExecutor(2) as pool:
            a = pool.submit(submit, first, "concurrent-key-0001")
            b = pool.submit(submit, second, "concurrent-key-0002")
            results = [a.result(), b.result()]
        self.assertEqual(sum(isinstance(x, dict) for x in results), 1, results)
        self.assertIn("chat-unresolved-turn-must-be-reconciled", results)
        winner = next(x for x in results if isinstance(x, dict))
        owner = first if winner["id"] in first.running else second
        fx.wait(owner, winner, {"waiting"})
        owner.stop(winner["id"])
        fx.finished(owner, winner)
        self.assertEqual(owner.status(fx.ref, 1, PRINCIPAL)["reserved_turns"], 1)

    def test_command_request_is_auto_declined_and_noted_without_asking(self):
        fx = self.fx
        service = fx.service(command=True)
        row = fx.finished(service, fx.send(service))
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["notices"], [dict(kind="auto-declined-command")])
        self.assertEqual(fx.rpcs[-1].sent[-1]["result"], {"decision": "decline"})
        self.assertIsNone(row["pending"])

    def test_long_tool_result_is_kept_whole_and_marked_as_truncated_for_codex(self):
        fx = self.fx
        text = "line of notes" + chr(10)
        big = fx.register_text(fx.ref, 1, "long.md", (text * 4600).encode())
        service = fx.service(action=dict(action="read_material", id=big["id"], note=""))
        row = fx.finished(service, fx.send(service))
        output = row["outputs"][0]
        self.assertEqual(len(output["value"]["text"]), 14 * 4600)
        self.assertTrue(output["model_saw_truncated"])
        service.rpc_factory = lambda record: FakeRpc(
            record, action=dict(action="read_material", id=fx.text["id"], note="")
        )
        short = fx.finished(service, fx.send(service, key="unique-request-0009"))
        self.assertFalse(short["outputs"][0]["model_saw_truncated"])

    def test_status_reads_never_write_the_stores(self):
        fx = self.fx
        service = fx.service()
        fx.finished(service, fx.send(service))

        def snapshot():
            return {
                p.name: (
                    p.stat().st_mtime_ns,
                    hashlib.sha256(p.read_bytes()).hexdigest(),
                )
                for p in sorted(fx.root.rglob("*.sqlite3"))
            }

        before = snapshot()
        self.assertEqual(
            sorted(before),
            ["conversations.sqlite3", "materials.sqlite3", "quota.sqlite3"],
        )
        for stage in range(1, 7):
            service.status(fx.ref, stage, PRINCIPAL)
        service.status(fx.ref, 1, "someone-else")
        self.assertEqual(snapshot(), before)

    def test_material_rows_say_whether_each_file_can_be_read(self):
        fx = self.fx
        big = fx.register_text(fx.ref, 1, "big.txt", b"x" * (64 * 1024 + 1))
        fx.register_text(fx.ref, 1, "paper.pdf", b"%PDF-1.7 fixture")
        gone = fx.register_text(fx.ref, 1, "gone.txt", b"will be deleted")
        changed = fx.register_text(fx.ref, 1, "changed.txt", b"before")
        upload = fx.store.begin_upload(
            dict(
                project_ref=fx.ref,
                name="partial.txt",
                stage=1,
                bytes=10,
                sha256="c" * 64,
            )
        )
        base = Path(fx.store.root) / "files"
        (base / (gone["id"] + ".bin")).unlink()
        (base / (changed["id"] + ".bin")).write_bytes(b"after!")
        rows = {
            m["name"]: m["readable"] for m in fx.tools.context(fx.ref, 1)["materials"]
        }
        self.assertEqual(rows["notes.md"], dict(ok=True, reason=None, text="能读"))
        self.assertEqual(rows["big.txt"]["reason"], "too-large")
        self.assertEqual(rows["paper.pdf"]["reason"], "not-plain-text")
        self.assertEqual(rows["gone.txt"]["reason"], "file-missing")
        self.assertEqual(rows["changed.txt"]["reason"], "changed-since-registration")
        self.assertEqual(rows["partial.txt"]["reason"], "not-screened-or-verified")
        self.assertTrue(
            upload["name"] in rows and all(r["text"] for r in rows.values())
        )
        service = fx.service(action=dict(action="read_material", id=big["id"], note=""))
        result = fx.finished(service, fx.send(service))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["outputs"], [])
        self.assertFalse(fx.rpcs[-1].sent[-1]["result"]["success"])

    def test_other_projects_materials_are_not_listed_or_readable(self):
        fx = self.fx
        fx.projects.add("project-beta", "pid-beta")
        foreign = fx.register_text("project-beta", 1, "secret.md", b"belongs to beta")
        names = [m["name"] for m in fx.tools.context(fx.ref, 1)["materials"]]
        self.assertEqual(names, ["notes.md"])
        service = fx.service(
            action=dict(action="read_material", id=foreign["id"], note="")
        )
        result = fx.finished(service, fx.send(service))
        self.assertEqual(result["outputs"], [])
        self.assertFalse(fx.rpcs[-1].sent[-1]["result"]["success"])
        self.assertIn("binding", json.dumps(fx.rpcs[-1].sent[-1]["result"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)

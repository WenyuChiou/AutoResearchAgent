"""Repository cases + actual Python fake child/SQLite/HTTP, never Codex/models."""

import atlas_test_paths  # noqa: F401 -- standalone discovery needs the local CLI.

import http.client
import json
from pathlib import Path
import subprocess
import sqlite3
import threading
import unittest
from unittest.mock import patch

from research_workspace_native.runtime_factory import CompositionError, compose_runtime
from research_workspace.atlas import atlas_files
from research_workspace_native.atlas_host import AtlasHost
from research_workspace_native.frame_journal import FrameJournal
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha

from atlas_native_runtime_fixtures import CompositionCase, cross_project_case


class CompositionTests(CompositionCase):
    def test_disabled_missing_authority_and_duplicate_projects_do_not_spawn(self):
        with patch(
            "research_workspace_native.runtime_factory.OwnedProcessChannel.__init__"
        ) as channel:
            self.assertIsNone(compose_runtime([("missing", "invalid")]))
            for options in (
                dict(enabled=1),
                dict(enabled=True),
                dict(enabled=True, authenticate=lambda _: "local-viewer", gates={}),
            ):
                with self.assertRaises(ValueError):
                    compose_runtime([(self.config, self.pin)], **options)
            with self.assertRaises(ValueError):
                compose_runtime(
                    [(self.config, self.pin)] * 2,
                    enabled=True,
                    authenticate=lambda _: "local-viewer",
                    gates=self.gates,
                )
            channel.assert_not_called()
        self.assertFalse(Path(self.spec["store_path"]).exists())

    def test_cross_project_storage_cannot_write_into_another_source(self):
        registrations, paths = cross_project_case(self.spec, self.config, self.root)
        with patch(
            "research_workspace_native.runtime_factory.OwnedProcessChannel.__init__"
        ) as child:
            with self.assertRaisesRegex(ValueError, "cross-project"):
                compose_runtime(
                    registrations,
                    enabled=True,
                    authenticate=lambda _: "local-viewer",
                    gates={**self.gates, "other-case": self.gates["repo-case"]},
                )
            child.assert_not_called()
        self.assertTrue(all(not Path(path).exists() for path in paths))

    def test_literal_gates_cleanup_retains_failed_intent(self):
        self.allowed = 1  # Truthy callback is never authority.
        with self.assertRaises(CompositionError) as rejected:
            self.compose()
        orphan = rejected.exception.orphan
        self.addCleanup(orphan["store"].close)
        self.assertIsNone(orphan["channel"].process)
        self.assertTrue(orphan["channel"].closed)
        state = orphan["store"].snapshot(self.spec["project_id"])
        self.assertEqual(state["intents"]["spawn"]["status"], "intent-recorded")
        self.assertTrue(Path(self.spec["store_path"]).exists())

    def test_store_constructor_schema_failure_closes_real_connection_before_spawn(self):
        original = sqlite3.connect
        connections = []

        class FailingSchema(sqlite3.Connection):
            def executescript(self, sql):
                raise sqlite3.OperationalError("synthetic schema failure")

        def connect(*args, **kwargs):
            connection = original(*args, **kwargs, factory=FailingSchema)
            connections.append(connection)
            return connection

        with patch(
            "research_workspace_native.store.sqlite3.connect", side_effect=connect
        ):
            with patch(
                "research_workspace_native.runtime_factory.OwnedProcessChannel.__init__"
            ) as child:
                with self.assertRaises(sqlite3.OperationalError):
                    self.compose()
                child.assert_not_called()
        self.assertEqual(len(connections), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[0].execute("SELECT 1")
        self.assertTrue(Path(self.spec["store_path"]).exists())

    def test_project_source_auth_and_restart_are_fail_closed(self):
        runtime = self.compose()
        self.assertFalse(runtime.status()["repo-case"]["authenticated_process"])
        with self.assertRaises(SessionApiError):
            runtime.api.view("wrong", "repo-case")
        with self.assertRaises(SessionApiError):
            runtime.api.view(self.token, "other-project")
        count = self.count()
        for _ in range(3):
            self.view()
        self.assertEqual(self.count(), count)
        self.assertFalse(runtime.status()["repo-case"]["started"])
        self.input.write_bytes(b"changed-version")
        with self.assertRaises(SessionApiError):
            runtime.api.offer(self.token, "repo-case")
        receipt = runtime.shutdown()
        self.assertTrue(receipt["repo-case"]["leader_reaped"])
        with self.assertRaises(ValueError):
            self.compose()

    def test_question_answer_replay_and_native_resolution_remain_distinct(self):
        runtime = self.compose()
        runtime.start()
        with self.assertRaises(ValueError):
            runtime.start()
        self.assertFalse(runtime.status()["repo-case"]["failure"])
        _, message = self.message("question")
        self.assertIn(message["status"], {"write-observed", "dispatched"})
        self.wait(lambda: self.pending() is not None)
        body = self.answer({"answers": {"q": {"answers": ["Synthetic confirmed"]}}})
        result = runtime.api.answer(self.token, "repo-case", body)
        self.assertEqual(result["status"], "dispatched")
        self.wait(lambda: self.view()["requests"][0]["status"] == "request-resolved")
        count = self.count()
        replay = runtime.api.answer(self.token, "repo-case", body)
        self.assertTrue(replay["replayed"])
        self.assertEqual(self.count(), count)
        self.wait(lambda: self.view()["operations"][0]["status"] == "completed")
        self.assertEqual(len(self.view()["requests"]), 1)

    def test_approval_default_denies_accept_explicit_policy_still_checks_final_gate(
        self,
    ):
        self.gates["repo-case"]["approval_policy"] = lambda context: self.allow_accept
        runtime = self.compose()
        runtime.start()
        self.message("approval")
        self.wait(lambda: self.pending() is not None)
        self.assertFalse(self.pending()["can_accept"])
        count = self.count()
        with self.assertRaises(SessionApiError):
            runtime.api.answer(
                self.token, "repo-case", self.answer({"decision": "accept"})
            )
        self.assertEqual(self.count(), count)
        self.allow_accept = True
        self.assertTrue(self.pending()["can_accept"])
        body = self.answer({"decision": "accept"})
        self.allowed = False
        result = runtime.api.answer(self.token, "repo-case", body)
        self.assertEqual(result["status"], "refused")
        self.assertEqual(self.count(), count)
        # A previously refused action cannot be silently revived after policy changes.
        self.allowed = True
        self.assertTrue(runtime.api.answer(self.token, "repo-case", body)["replayed"])
        self.assertEqual(self.count(), count)

    def test_explicit_synthetic_approval_accept_is_dispatched_once(self):
        self.gates["repo-case"]["approval_policy"] = lambda context: (
            context["action"]["request"]["payload"]["command"] == "synthetic-no-op"
        )
        runtime = self.compose()
        runtime.start()
        self.message("approval")
        self.wait(lambda: self.pending() is not None)
        self.assertTrue(self.pending()["can_accept"])
        body = self.answer({"decision": "accept"})
        self.assertEqual(
            runtime.api.answer(self.token, "repo-case", body)["status"], "dispatched"
        )
        self.wait(lambda: self.view()["requests"][0]["status"] == "request-resolved")
        count = self.count()
        self.assertTrue(runtime.api.answer(self.token, "repo-case", body)["replayed"])
        self.assertEqual(self.count(), count)

    def test_interrupt_uses_bound_operation_and_replay_does_not_redispatch(self):
        runtime = self.compose()
        runtime.start()
        self.message("question")
        self.wait(
            lambda: (
                self.pending() is not None
                and self.view()["operations"][0]["can_interrupt"]
            )
        )
        view = self.view()
        operation = view["operations"][0]
        body = dict(
            key="interrupt-1",
            revision=view["revision"],
            index_sha256=self.spec["index_sha256"],
            input_version=self.spec["input_version"],
            action_ref=operation["action_ref"],
            action_sha256=operation["action_sha256"],
        )
        runtime.api.interrupt(self.token, "repo-case", body)
        self.wait(lambda: self.view()["operations"][0]["status"] == "completed")
        count = self.count()
        self.assertTrue(
            runtime.api.interrupt(self.token, "repo-case", body)["replayed"]
        )
        self.assertEqual(self.count(), count)

    def test_bootstrap_and_attach_rejection_close_and_reap_actual_fake_child(self):
        original = subprocess.Popen
        for name in ("admit_lifecycle", "admit_attach"):
            self.spec["store_path"] = (self.storage / (name + ".sqlite")).as_posix()
            self.pin = self.save()
            gates = {ref: dict(callbacks) for ref, callbacks in self.gates.items()}
            gates["repo-case"][name] = lambda context: False
            children = []

            def launch(args, **kwargs):
                process = original(args, **kwargs)
                if Path(args[0]) == Path(self.spec["executable"]):
                    children.append(process)
                return process

            with patch(
                "research_workspace_native.process_channel.subprocess.Popen",
                side_effect=launch,
            ):
                with self.assertRaises(ValueError):
                    self.compose(gates=gates)
            self.assertEqual(len(children), 1)
            self.assertIsNotNone(children[0].poll())
            reopened = FrameJournal(self.spec["store_path"])
            try:
                state = reopened.snapshot(self.spec["project_id"])
                self.assertEqual(state["intents"]["spawn"]["status"], "completed")
                self.assertEqual(len(state["process_channels"]), 1)
            finally:
                reopened.close()

    def test_actual_http_repository_stage1_stage2_case_message_refresh_and_replay(self):
        runtime = self.compose()
        rendered = atlas_files(self.value)
        files = {"/views/case/" + name: raw for name, raw in rendered.items()}
        views = [
            dict(
                ref="case",
                label="Repository synthetic Stage 1 + Stage 2",
                url="/views/case/atlas.html",
                fixture=True,
                manifest_sha256=sha(b"fixture"),
                project_id=self.spec["project_id"],
                index_sha256=self.spec["index_sha256"],
            )
        ]
        server = AtlasHost(
            files=files, views=views, native_runtime=runtime, credential=self.token
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        runtime.start()
        stopped = False

        def stop():
            nonlocal stopped
            if stopped:
                return
            server.shutdown()
            server.server_close()
            worker.join(3)
            self.assertFalse(worker.is_alive())
            stopped = True

        self.addCleanup(stop)

        def request(path, body=None, token=None):
            client = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=3
            )
            headers = {"Authorization": "Bearer " + (token or self.token)}
            method = "GET" if body is None else "POST"
            if body is not None:
                headers.update(
                    Origin=server.expected_origin,
                    **{"Content-Type": "application/json"},
                )
            try:
                client.request(
                    method,
                    path,
                    body=None if body is None else canonical(body),
                    headers=headers,
                )
                response = client.getresponse()
                return response.status, response.read()
            finally:
                client.close()

        path = "/api/native/projects/repo-case"
        self.assertEqual(request("/views/case/atlas.html")[0], 200)
        status, raw = request("/host-bootstrap/case.js")
        self.assertEqual(status, 200)
        bootstrap = json.loads(
            raw.decode().split("window.WORKSPACE_NATIVE_ATLAS=")[1].split(";\n")[0]
        )
        self.assertEqual(bootstrap["project_ref"], "repo-case")
        offer = json.loads(request(path + "/offer")[1])
        body = dict(
            key="http-message",
            revision=offer["revision"],
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            text="repository case display check",
        )
        status, raw = request(path + "/messages", body)
        self.assertEqual(status, 200, raw)
        self.wait(
            lambda: any(
                e["role"] == "assistant" for e in self.view()["transcript"]["entries"]
            )
        )
        count = self.count()
        self.assertTrue(json.loads(request(path + "/messages", body)[1])["replayed"])
        self.assertEqual(
            request(path + "/messages", {**body, "text": "changed"})[0], 409
        )
        self.assertEqual(request(path, token="wrong-token")[0], 401)
        self.assertEqual(request("/api/native/projects/foreign")[0], 404)
        for _ in range(3):
            self.assertEqual(request(path)[0], 200)
        self.assertEqual(self.count(), count)
        self.assertEqual(len(self.value["stage2"]["evaluation"]["rows"]), 9)
        self.wait(lambda: self.view()["operations"][0]["status"] == "completed")
        saved = Path(self.spec["store_path"])
        stop()
        reopened = FrameJournal(saved)
        try:
            state = reopened.snapshot(self.spec["project_id"])
            key = next(
                key
                for key, value in state["session_api_actions"].items()
                if value["request"]["key"] == "http-message"
            )
            self.assertEqual(state["intents"][key]["status"], "completed")
        finally:
            reopened.close()


if __name__ == "__main__":
    unittest.main()

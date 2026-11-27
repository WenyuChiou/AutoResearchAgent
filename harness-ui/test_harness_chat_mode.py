"""Synthetic handlers/services only: no HTTP server, DB, network or native."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from harness_chat_mode import ALLOWED_POST_PATHS, install_chat_only


def make_host(enabled=True):
    class Parent:
        def __init__(self, path, *, authenticated=True, same_origin=True, small_body=True):
            self.path = path
            self.authenticated = authenticated
            self.same_origin = same_origin
            self.small_body = small_body
            self.close_connection = False
            self.calls = []

        def _reply(self, code, body):
            self.calls.append(("reply", code))
            return code, body

        def do_GET(self):
            self.calls.append(("parent-get", self.path))
            return self._reply(200, {"read": self.path})

        def do_POST(self):
            self.calls.append(("parent-post", self.path))
            if not self.authenticated:
                return self._reply(401, {"error": "credential-rejected"})
            if not self.same_origin:
                return self._reply(403, {"error": "cross-site-rejected"})
            if not self.small_body:
                return self._reply(415, {"error": "small-json-body-required"})
            return self._reply(200, {"original_chat_handler": True})

        def do_PUT(self):
            raise AssertionError("parent PUT must not be entered")

        do_PATCH = do_PUT
        do_DELETE = do_PUT

    observation = dict(kind="V9HarnessConversation", project_ref="view:synthetic", stage=1,
        enabled=enabled, disabled_reason=None if enabled else "expired-synthetic-permit",
        local_admission_ready=enabled, admission_blockers=[] if enabled else ["expired"],
        reserved_turns=3, reserved_seconds=360, max_turns=5,
        context=dict(project_ref="view:synthetic", stage=1,
                     supported_actions=["state", "materials", "read_paper", "register_delivery",
                                        "save_review", "prepare_workflow", "prepare_advice"],
                     capabilities=dict(material_registration=True, local_review_notes=True,
                         offline_workflow_preparation=True, formal_selection=True,
                         research_execution=True, saved_stage_reading=True)),
        turns=[], sessions=[])

    class Service:
        def __init__(self):
            self.spec = {"_continuation": True, "actions": ["state", "materials", "read_paper"]}
            self.status_calls = []

        def status(self, project, stage):
            self.status_calls.append((project, stage))
            return observation

    return SimpleNamespace(harness_chat=Service(), RequestHandlerClass=Parent,
                           host_binding={"original": "preserved"}, observation=observation)


class ChatOnlyModeTests(unittest.TestCase):
    def test_exact_three_post_routes_reach_original_handler(self):
        host = make_host()
        install_chat_only(host)
        for path in ALLOWED_POST_PATHS:
            handler = host.RequestHandlerClass(path)
            code, body = handler.do_POST()
            self.assertEqual(code, 200)
            self.assertTrue(body["original_chat_handler"])
            self.assertEqual(handler.calls[0], ("parent-post", path))

    def test_disallowed_paths_never_enter_parent(self):
        host = make_host()
        install_chat_only(host)
        paths = ("/api/v9/chat/reconcile", "/api/v9/chat/cleanup", "/api/v9/register",
                 "/api/v9/workflow/prepare", "/api/v9/formal/select", "/api/v9/fresh/dispatch",
                 "/api/project/create", "/", "/api/v9/chat/send/", "/api/v9/chat/send?x=1",
                 "/api/v9/chat/Send", "/API/v9/chat/send", "/api/v9/chat/%73end",
                 "/api/v9/chat//send", "http://127.0.0.1/api/v9/chat/send")
        for path in paths:
            with self.subTest(path=path):
                handler = host.RequestHandlerClass(path)
                code, body = handler.do_POST()
                self.assertEqual(code, 405)
                self.assertTrue(handler.close_connection)
                self.assertFalse(any(call[0] == "parent-post" for call in handler.calls))
                self.assertFalse(body["research_execution"])

    def test_all_put_patch_delete_are_rejected(self):
        host = make_host()
        install_chat_only(host)
        for method in ("do_PUT", "do_PATCH", "do_DELETE"):
            for path in (*ALLOWED_POST_PATHS, "/api/v9/draft", "/"):
                with self.subTest(method=method, path=path):
                    handler = host.RequestHandlerClass(path)
                    self.assertEqual(getattr(handler, method)()[0], 405)
                    self.assertEqual(handler.calls, [("reply", 405)])

    def test_gets_are_inherited_without_filtering(self):
        host = make_host()
        original_get = host.RequestHandlerClass.do_GET
        install_chat_only(host)
        self.assertIs(host.RequestHandlerClass.do_GET, original_get)
        handler = host.RequestHandlerClass("/api/v9/chat/state?project=synthetic&stage=1")
        self.assertEqual(handler.do_GET()[0], 200)
        self.assertEqual(handler.calls[0][0], "parent-get")

    def test_original_authentication_and_origin_and_body_checks_retained(self):
        host = make_host()
        install_chat_only(host)
        for kwargs, expected in (({"authenticated": False}, 401),
                                 ({"same_origin": False}, 403),
                                 ({"small_body": False}, 415)):
            handler = host.RequestHandlerClass("/api/v9/chat/send", **kwargs)
            self.assertEqual(handler.do_POST()[0], expected)
            self.assertEqual(handler.calls[0][0], "parent-post")

    def test_context_actions_and_capabilities_restricted(self):
        host = make_host()
        install_chat_only(host)
        status = host.harness_chat.status("view:synthetic", 1)
        self.assertEqual(status["context"]["supported_actions"], ["state", "materials", "read_paper"])
        for name in ("material_registration", "local_review_notes", "offline_workflow_preparation",
                     "formal_selection", "research_execution"):
            self.assertIs(status["context"]["capabilities"][name], False)
        self.assertTrue(status["context"]["capabilities"]["saved_stage_reading"])

    def test_enabled_and_disabled_details_never_fabricated(self):
        for enabled in (True, False):
            host = make_host(enabled)
            install_chat_only(host)
            result = host.harness_chat.status("view:synthetic", 1)
            self.assertIs(result["enabled"], enabled)
            self.assertEqual(result["disabled_reason"], host.observation["disabled_reason"])
            self.assertEqual(result["admission_blockers"], host.observation["admission_blockers"])
            self.assertEqual(result["local_admission_ready"], host.observation["local_admission_ready"])
            self.assertTrue(result["registered_config_activated"])
            self.assertTrue(result["chat_only"])
            self.assertFalse(result["connection_preparation"])
            self.assertFalse(result["research_execution"])

    def test_budget_numbers_pass_through_unchanged(self):
        host = make_host()
        before = deepcopy(host.observation)
        install_chat_only(host)
        result = host.harness_chat.status("view:synthetic", 1)
        for key in ("reserved_turns", "reserved_seconds", "max_turns", "turns", "sessions"):
            self.assertEqual(result[key], before[key])
        self.assertEqual(host.observation, before)

    def test_original_status_identity_arguments_retained(self):
        host = make_host()
        install_chat_only(host)
        host.harness_chat.status("view:another", 4)
        self.assertEqual(host.harness_chat.status_calls, [("view:another", 4)])

    def test_does_not_touch_assets_or_existing_binding(self):
        host = make_host()
        host._assets = {"/app.js": b"frozen", "/host-binding.json": b"caller-must-reseal"}
        before = deepcopy(host._assets)
        binding = install_chat_only(host)
        self.assertEqual(host._assets, before)
        self.assertEqual(host.host_binding["original"], "preserved")
        self.assertEqual(binding["allowed_post_paths"], list(ALLOWED_POST_PATHS))
        self.assertFalse(binding["other_http_writes_enabled"])
        self.assertFalse(binding["native_started_by_install"])
        binding["allowed_post_paths"].clear()
        self.assertEqual(host.host_binding["chat_only"]["allowed_post_paths"], list(ALLOWED_POST_PATHS))

    def test_repeated_installation_rejected(self):
        host = make_host()
        install_chat_only(host)
        with self.assertRaisesRegex(ValueError, "already-installed"):
            install_chat_only(host)

    def test_legacy_or_missing_spec_cannot_open_chat_only_mode(self):
        for spec in (None, {}, {"actions": ["state"]}, {"_continuation": 1, "actions": ["state"]}):
            host = make_host()
            host.harness_chat.spec = spec
            before_handler = host.RequestHandlerClass
            with self.assertRaisesRegex(ValueError, "continuation-config-required"):
                install_chat_only(host)
            self.assertIs(host.RequestHandlerClass, before_handler)

    def test_non_read_actions_and_bad_shapes_rejected(self):
        for actions in ([], "state", ["register_delivery"], ["prepare_workflow"], ["state", "state"], [True]):
            host = make_host()
            host.harness_chat.spec["actions"] = actions
            with self.assertRaisesRegex(ValueError, "read-actions-required"):
                install_chat_only(host)

    def test_invalid_status_shapes_fail_closed(self):
        for invalid in (None, {}, {"context": []}, {"context": {"supported_actions": "state"}},
                        {"context": {"supported_actions": [], "capabilities": []}}):
            host = make_host()
            host.harness_chat.status = lambda *args: invalid
            install_chat_only(host)
            with self.assertRaises(ValueError):
                host.harness_chat.status("view:synthetic", 1)


if __name__ == "__main__":
    unittest.main()

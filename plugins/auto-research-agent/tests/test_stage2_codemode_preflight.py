"""Production-only Code Mode witness tests for Stage 2 preflight."""

# ruff: noqa: E402 -- import the repository CLI directly.

import copy
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "cli"))

from stage2_live.codemode import (
    CodeModeWitnessError,
    inspect_production_child,
    inspect_production_wrapper,
    parse_constant_wrapper,
    _cwd_path,
)


EXECUTOR = {
    "family": "windows",
    "shell_path": r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    "working_directory": r"C:\Stage2NativeProduction_20261003\workspace",
}
READ_COMMAND = "[System.IO.File]::ReadAllText('read-probe.txt')"


def response(kind, call_id, **values):
    return {
        "type": "response_item",
        "payload": {"type": kind, "call_id": call_id, **values},
    }


def item(value):
    return {
        "type": "event_msg",
        "payload": {"type": "item_completed", "item": value},
    }


def wrapper(tool, arguments, *, result_name="r"):
    return (
        f"const {result_name} = await tools.{tool}("
        + json.dumps(arguments)
        + f");\ntext(JSON.stringify({result_name}));\n"
    )


def terminal(value):
    return [
        {"type": "input_text", "text": "Script completed\nOutput:\n"},
        {"type": "input_text", "text": json.dumps(value)},
    ]


def native_command(output="proof\r\n", exit_code=0):
    return item(
        {
            "type": "CommandExecution",
            "id": "exec-native",
            "command": [EXECUTOR["shell_path"], "-NoProfile", "-Command", READ_COMMAND],
            "cwd": "file:///C:/Stage2NativeProduction_20261003/workspace",
            "status": "completed" if exit_code == 0 else "failed",
            "exit_code": exit_code,
            "aggregated_output": output,
        }
    )


def custom_call(call_id, tool, arguments, *, output=None):
    events = [
        response(
            "custom_tool_call",
            call_id,
            name="exec",
            status="completed",
            input=wrapper(tool, arguments),
        )
    ]
    if output is not None:
        events.append(response("custom_tool_call_output", call_id, output=output))
    return events


def function_call(call_id, name, arguments):
    return response(
        "function_call", call_id, name=name, arguments=json.dumps(arguments)
    )


class Stage2CodeModeWrapperTests(unittest.TestCase):
    def setUp(self):
        self.arguments = {
            "cmd": READ_COMMAND,
            "shell": EXECUTOR["shell_path"],
            "workdir": EXECUTOR["working_directory"],
            "login": False,
            "yield_time_ms": 10000,
            "max_output_tokens": 2000,
        }

    def read_events(self):
        wait = {"cell_id": "1", "yield_time_ms": 30000, "max_tokens": 2000}
        return custom_call(
            "call-read",
            "exec_command",
            self.arguments,
            output="Script running with cell ID 1\nOutput:\n",
        ) + [
            function_call("wait-one", "wait", wait),
            response(
                "function_call_output",
                "wait-one",
                output="Script running with cell ID 1\nOutput:\n",
            ),
            function_call("wait-two", "wait", wait),
            native_command(),
            response(
                "function_call_output",
                "wait-two",
                output=terminal({"exit_code": 0, "output": "proof\r\n"}),
            ),
        ]

    def test_literal_parser_rejects_dynamic_extra_and_transformed_wrappers(self):
        self.assertEqual(_cwd_path("C:/"), _cwd_path("c:\\"))
        self.assertNotEqual(_cwd_path("C:/"), _cwd_path("c:"))
        self.assertNotEqual(_cwd_path("/"), _cwd_path(""))
        self.assertNotEqual(_cwd_path("/tmp/Probe"), _cwd_path("/tmp/probe"))
        self.assertIsNone(_cwd_path("file://foreign-host/C:/workspace"))
        valid = "const r=await tools.web__run({search_query:[{q:'fixed'}]});text(JSON.stringify(r));"
        self.assertEqual(
            parse_constant_wrapper(valid),
            ("web__run", {"search_query": [{"q": "fixed"}]}),
        )
        invalid = (
            "const r=await tools.web__run({x:" + "9" * 5000 + "});text(r);",
            "const r=await tools.web__run(makeArgs());text(JSON.stringify(r));",
            "const r=await tools.web__run({search_query:[]});console.log('echo');text(JSON.stringify(r));",
            "const r=await tools.web__run({search_query:[]});text(JSON.stringify({r}));",
            "const r=await tools.web__run({x:"
            + "[" * 40
            + "0"
            + "]" * 40
            + "});text(JSON.stringify(r));",
        )
        for source in invalid:
            with self.subTest(source=source), self.assertRaises(CodeModeWitnessError):
                parse_constant_wrapper(source)

    def test_yielded_read_links_one_cell_and_native_terminal(self):
        witness = inspect_production_wrapper(
            self.read_events(), "call-read", "exec_command", EXECUTOR
        )
        self.assertEqual(witness["output"]["output"], "proof\r\n")
        self.assertEqual(witness["native_item_id"], "exec-native")

    def test_windows_path_separators_do_not_change_executor_identity(self):
        self.arguments["shell"] = self.arguments["shell"].replace("\\", "/")
        self.arguments["workdir"] = self.arguments["workdir"].replace("\\", "/")
        witness = inspect_production_wrapper(
            self.read_events(), "call-read", "exec_command", EXECUTOR
        )
        self.assertEqual(witness["native_item_id"], "exec-native")
        self.arguments["shell"] = "C:/different/shell.exe"
        with self.assertRaises(CodeModeWitnessError):
            inspect_production_wrapper(
                self.read_events(), "call-read", "exec_command", EXECUTOR
            )

    def test_immediate_write_and_search_accept_authenticated_native_results(self):
        write_events = custom_call("write", "exec_command", self.arguments) + [
            native_command(output=""),
            response(
                "custom_tool_call_output",
                "write",
                output=terminal({"exit_code": 0, "output": ""}),
            ),
        ]
        self.assertEqual(
            inspect_production_wrapper(write_events, "write", "exec_command", EXECUTOR)[
                "native_item_id"
            ],
            "exec-native",
        )
        query = "literature error correction"
        search_events = custom_call(
            "search",
            "web__run",
            {"search_query": [{"q": query}], "response_length": "short"},
        ) + [
            item(
                {
                    "type": "Extension",
                    "kind": "web.search",
                    "id": "search-native",
                    "query": query,
                    "results": [{"url": "https://example.test"}],
                }
            ),
            response(
                "custom_tool_call_output",
                "search",
                output=terminal("A paper about error correction"),
            ),
        ]
        self.assertEqual(
            inspect_production_wrapper(search_events, "search", "web__run", EXECUTOR)[
                "native_item_id"
            ],
            "search-native",
        )
        search_events[0]["payload"]["input"] = (
            'const r=await tools.web__run({search_query:[{q:"literature error correction"}]});text(r)'
        )
        search_events[-1]["payload"]["output"][1]["text"] = (
            "A paper about error correction"
        )
        self.assertEqual(
            inspect_production_wrapper(search_events, "search", "web__run", EXECUTOR)[
                "output"
            ],
            "A paper about error correction",
        )

    def test_wait_rejects_cross_cell_unfinished_failed_and_missing_terminal(self):
        cases = []
        crossed = self.read_events()
        crossed[2]["payload"]["arguments"] = json.dumps({"cell_id": "2"})
        cases.append(crossed)
        cases.append(self.read_events()[:-3])
        failed = self.read_events()
        failed[-1]["payload"]["output"] = terminal({"exit_code": 1, "output": "failed"})
        cases.append(failed)
        missing = self.read_events()
        del missing[5]
        cases.append(missing)
        substituted = self.read_events()
        substituted[5]["payload"]["item"]["command"][0] = "unbound-shell.exe"
        cases.append(substituted)
        wrong_mode = self.read_events()
        wrong_mode[5]["payload"]["item"]["command"][1:-1] = ["-File", "unbound.ps1"]
        cases.extend((wrong_mode, [None], [{"payload": []}]))
        for events in cases:
            with (
                self.subTest(events=len(events)),
                self.assertRaises(CodeModeWitnessError),
            ):
                inspect_production_wrapper(
                    events, "call-read", "exec_command", EXECUTOR
                )


class Stage2ProductionChildWitnessTests(unittest.TestCase):
    def fixture(self):
        primary = "thread-primary"
        child = "thread-child"
        path = "/root/arithmetic_check"
        events = [
            response(
                "function_call",
                "spawn",
                name="spawn_agent",
                namespace="collaboration",
                arguments=json.dumps(
                    {
                        "task_name": "arithmetic_check",
                        "fork_turns": "all",
                        "message": "encrypted",
                    }
                ),
            ),
            item(
                {
                    "type": "SubAgentActivity",
                    "id": "spawn",
                    "kind": "started",
                    "agent_thread_id": child,
                    "agent_path": path,
                }
            ),
            response(
                "function_call_output", "spawn", output=json.dumps({"task_name": path})
            ),
        ]
        child_events = [
            {
                "type": "session_meta",
                "payload": {
                    "id": child,
                    "source": {
                        "subagent": {
                            "thread_spawn": {
                                "parent_thread_id": primary,
                                "depth": 1,
                                "agent_path": path,
                            }
                        }
                    },
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "42"}],
                },
            },
        ]
        return events, [(child, child_events)]

    def test_child_requires_matching_host_link_lineage_and_result(self):
        events, sessions = self.fixture()
        self.assertEqual(
            inspect_production_child(
                events, "spawn", "thread-child", "thread-primary", sessions
            ),
            {
                "agent_path": "/root/arithmetic_check",
                "parent_thread_id": "thread-primary",
            },
        )
        for mutation in (
            "wrong-parent",
            "wrong-path",
            "missing-result",
            "ambiguous",
            "user-only",
            "malformed-source",
            "boolean-depth",
            "user-agent-message",
        ):
            changed_events = copy.deepcopy(events)
            changed_sessions = copy.deepcopy(sessions)
            if mutation == "wrong-parent":
                changed_sessions[0][1][0]["payload"]["source"]["subagent"][
                    "thread_spawn"
                ]["parent_thread_id"] = "other"
            elif mutation == "wrong-path":
                changed_sessions[0][1][0]["payload"]["source"]["subagent"][
                    "thread_spawn"
                ]["agent_path"] = "/root/other"
            elif mutation == "missing-result":
                changed_sessions[0][1].pop()
            elif mutation == "user-only":
                changed_sessions[0][1][-1]["payload"]["role"] = "user"
            elif mutation == "user-agent-message":
                changed_sessions[0][1][-1]["payload"].update(
                    type="agent_message", role="user"
                )
            elif mutation == "malformed-source":
                changed_sessions[0][1][0]["payload"]["source"] = "foreign"
            elif mutation == "boolean-depth":
                changed_sessions[0][1][0]["payload"]["source"]["subagent"][
                    "thread_spawn"
                ]["depth"] = True
            else:
                changed_sessions.append(copy.deepcopy(changed_sessions[0]))
            with (
                self.subTest(mutation=mutation),
                self.assertRaises(CodeModeWitnessError),
            ):
                inspect_production_child(
                    changed_events,
                    "spawn",
                    "thread-child",
                    "thread-primary",
                    changed_sessions,
                )


if __name__ == "__main__":
    unittest.main()

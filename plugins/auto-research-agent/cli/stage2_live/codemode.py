"""Strict decoding of production Code Mode capability witnesses.

This module recognizes a deliberately small JavaScript subset.  It never
executes subject-authored code: the wrapper must contain one constant tool call
and must serialize that call's unmodified result.
"""

import json
import re
from urllib.parse import unquote, urlparse


class CodeModeWitnessError(ValueError):
    """A Code Mode wrapper or its host evidence is not an admissible witness."""


_PREFIX = re.compile(
    r"\s*const\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*await\s+"
    r"tools\.(exec_command|web__run)\s*\(",
)
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_RUNNING = re.compile(r"\A" r"Script running with cell ID ([^\s]+)\r?\n", re.DOTALL)


class _LiteralParser:
    def __init__(self, source, position):
        self.source = source
        self.position = position
        self.depth = 0

    def _space(self):
        while self.position < len(self.source) and self.source[self.position].isspace():
            self.position += 1

    def _take(self, token):
        self._space()
        if not self.source.startswith(token, self.position):
            raise CodeModeWitnessError("Code Mode wrapper contains a non-literal value")
        self.position += len(token)

    def value(self):
        self._space()
        if self.position >= len(self.source):
            raise CodeModeWitnessError("Code Mode wrapper literal is incomplete")
        char = self.source[self.position]
        if char in "{[":
            if self.depth >= 32:
                raise CodeModeWitnessError("Code Mode literal nesting is too deep")
            self.depth += 1
            try:
                return self._object() if char == "{" else self._array()
            finally:
                self.depth -= 1
        if char in "\"'":
            return self._string()
        for token, value in (("true", True), ("false", False), ("null", None)):
            if self.source.startswith(token, self.position):
                end = self.position + len(token)
                if end == len(self.source) or not re.match(
                    r"[A-Za-z0-9_$]", self.source[end]
                ):
                    self.position = end
                    return value
        match = _NUMBER.match(self.source, self.position)
        if match:
            self.position = match.end()
            try:
                return json.loads(match.group())
            except ValueError as error:
                raise CodeModeWitnessError("Code Mode number is invalid") from error
        raise CodeModeWitnessError("Code Mode wrapper contains a non-literal value")

    def _string(self):
        quote = self.source[self.position]
        self.position += 1
        result = []
        escapes = {
            '"': '"',
            "'": "'",
            "\\": "\\",
            "/": "/",
            "b": "\b",
            "f": "\f",
            "n": "\n",
            "r": "\r",
            "t": "\t",
        }
        while self.position < len(self.source):
            char = self.source[self.position]
            self.position += 1
            if char == quote:
                return "".join(result)
            if char in "\r\n":
                raise CodeModeWitnessError("Code Mode string contains a raw newline")
            if char != "\\":
                result.append(char)
                continue
            if self.position >= len(self.source):
                break
            escaped = self.source[self.position]
            self.position += 1
            if escaped == "u":
                digits = self.source[self.position : self.position + 4]
                if not re.fullmatch(r"[0-9A-Fa-f]{4}", digits):
                    raise CodeModeWitnessError("Code Mode string escape is invalid")
                result.append(chr(int(digits, 16)))
                self.position += 4
            elif escaped in escapes:
                result.append(escapes[escaped])
            else:
                raise CodeModeWitnessError("Code Mode string escape is invalid")
        raise CodeModeWitnessError("Code Mode string is unterminated")

    def _object(self):
        self._take("{")
        result = {}
        self._space()
        if self.source.startswith("}", self.position):
            self.position += 1
            return result
        while True:
            self._space()
            if self.position < len(self.source) and self.source[self.position] in "\"'":
                key = self._string()
            else:
                match = _IDENTIFIER.match(self.source, self.position)
                if not match:
                    raise CodeModeWitnessError("Code Mode object key is invalid")
                key = match.group()
                self.position = match.end()
            if key in result:
                raise CodeModeWitnessError("Code Mode object contains a duplicate key")
            self._take(":")
            result[key] = self.value()
            self._space()
            if self.source.startswith("}", self.position):
                self.position += 1
                return result
            self._take(",")

    def _array(self):
        self._take("[")
        result = []
        self._space()
        if self.source.startswith("]", self.position):
            self.position += 1
            return result
        while True:
            result.append(self.value())
            self._space()
            if self.source.startswith("]", self.position):
                self.position += 1
                return result
            self._take(",")


def parse_constant_wrapper(source):
    """Return ``(tool_name, literal_arguments)`` for the one allowed wrapper."""
    if not isinstance(source, str) or len(source) > 32000:
        raise CodeModeWitnessError("Code Mode wrapper must be text")
    match = _PREFIX.match(source)
    if not match:
        raise CodeModeWitnessError("Code Mode wrapper shape is invalid")
    variable, tool_name = match.groups()
    parser = _LiteralParser(source, match.end())
    arguments = parser.value()
    if not isinstance(arguments, dict):
        raise CodeModeWitnessError("Code Mode tool arguments must be an object")
    suffix = re.compile(
        r"\s*\)\s*;\s*text\s*\(\s*(?:JSON\.stringify\s*\(\s*"
        + re.escape(variable)
        + r"\s*\)|"
        + re.escape(variable)
        + r")\s*\)\s*;?\s*\Z"
    )
    if not suffix.match(source, parser.position):
        raise CodeModeWitnessError("Code Mode wrapper has extra or transformed output")
    return tool_name, arguments


def _payload(event):
    if not isinstance(event, dict):
        raise CodeModeWitnessError("native event must be an object")
    value = event.get("payload")
    if value is not None and not isinstance(value, dict):
        raise CodeModeWitnessError("native event payload must be an object")
    return value if isinstance(value, dict) else event


def _content_text(value, raw_result=False):
    if isinstance(value, str):
        return value, None
    if not isinstance(value, list) or not value:
        raise CodeModeWitnessError("Code Mode host output is malformed")
    texts = []
    for part in value:
        if not isinstance(part, dict) or set(part) != {"type", "text"}:
            raise CodeModeWitnessError("Code Mode host output is malformed")
        if part["type"] != "input_text" or not isinstance(part["text"], str):
            raise CodeModeWitnessError("Code Mode host output is malformed")
        texts.append(part["text"])
    if len(texts) == 2 and texts[0].startswith("Script completed"):
        if raw_result:
            return texts[0], texts[1]
        try:
            return texts[0], json.loads(texts[1])
        except ValueError as error:
            raise CodeModeWitnessError(
                "Code Mode terminal result is malformed"
            ) from error
    return "".join(texts), None


def _cwd_path(value):
    if not isinstance(value, str):
        return None
    if value.lower().startswith("file:"):
        parsed = urlparse(value)
        if parsed.netloc:
            return None
        value = unquote(parsed.path)
        if re.match(r"/[A-Za-z]:/", value):
            value = value[1:]
    if re.match(r"[A-Za-z]:[\\/]", value):
        return value.replace("/", "\\").rstrip("\\").casefold()
    return value.rstrip("/")


def _native_items(events, start, end, item_type):
    matches = []
    for position in range(start + 1, end):
        event = events[position]
        payload = _payload(event)
        item = payload.get("item") if payload.get("type") == "item_completed" else None
        if isinstance(item, dict) and item.get("type") == item_type:
            matches.append(item)
    return matches


def _terminal_result(events, call_position, output_position, output, raw_result=False):
    text, result = _content_text(output, raw_result)
    if result is not None:
        return output_position, result
    running = _RUNNING.match(text)
    if not running:
        raise CodeModeWitnessError("Code Mode wrapper has no terminal result")
    cell_id = running.group(1)
    terminal = None
    for position in range(output_position + 1, len(events)):
        payload = _payload(events[position])
        if payload.get("type") != "function_call" or payload.get("name") != "wait":
            continue
        try:
            arguments = json.loads(payload.get("arguments", ""))
        except ValueError as error:
            raise CodeModeWitnessError(
                "Code Mode wait arguments are malformed"
            ) from error
        if not isinstance(arguments, dict) or set(arguments) - {
            "cell_id",
            "yield_time_ms",
            "max_tokens",
        }:
            raise CodeModeWitnessError("Code Mode wait arguments are not bounded")
        if str(arguments.get("cell_id")) != cell_id:
            raise CodeModeWitnessError("Code Mode wait crossed host cells")
        call_id = payload.get("call_id")
        outputs = [
            (index, _payload(event))
            for index, event in enumerate(events[position + 1 :], position + 1)
            if _payload(event).get("type") == "function_call_output"
            and _payload(event).get("call_id") == call_id
        ]
        if len(outputs) != 1:
            raise CodeModeWitnessError("Code Mode wait output is ambiguous")
        wait_position, wait_output = outputs[0]
        wait_text, wait_result = _content_text(wait_output.get("output"), raw_result)
        if wait_result is not None:
            terminal = (wait_position, wait_result)
            break
        continued = _RUNNING.match(wait_text)
        if not continued or continued.group(1) != cell_id:
            raise CodeModeWitnessError("Code Mode wait has no terminal result")
    if terminal is None:
        raise CodeModeWitnessError("Code Mode host cell is unfinished")
    return terminal


def inspect_production_wrapper(events, event_id, expected_tool, executor):
    """Validate a production wrapper against its terminal and native host item."""
    calls = []
    outputs = []
    for position, event in enumerate(events):
        payload = _payload(event)
        if payload.get("call_id") != event_id:
            continue
        if payload.get("type") == "custom_tool_call":
            calls.append((position, payload))
        elif payload.get("type") == "custom_tool_call_output":
            outputs.append((position, payload))
    if len(calls) != 1 or len(outputs) != 1:
        raise CodeModeWitnessError("Code Mode call/output identity is ambiguous")
    call_position, call = calls[0]
    output_position, output = outputs[0]
    if (
        call_position >= output_position
        or call.get("name") != "exec"
        or call.get("status") != "completed"
    ):
        raise CodeModeWitnessError("Code Mode host call did not complete")
    tool_name, arguments = parse_constant_wrapper(call.get("input"))
    if tool_name != expected_tool:
        raise CodeModeWitnessError("Code Mode wrapper called the wrong tool")
    terminal_position, result = _terminal_result(
        events,
        call_position,
        output_position,
        output.get("output"),
        raw_result=expected_tool == "web__run"
        and not re.search(r"text\s*\(\s*JSON\.stringify", call["input"]),
    )
    if expected_tool == "exec_command":
        allowed = {
            "cmd",
            "workdir",
            "shell",
            "login",
            "yield_time_ms",
            "max_output_tokens",
        }
        if (
            set(arguments) - allowed
            or arguments.get("shell") != executor["shell_path"]
            or arguments.get("workdir") != executor["working_directory"]
            or arguments.get("login") is not False
            or not isinstance(arguments.get("cmd"), str)
        ):
            raise CodeModeWitnessError(
                "Code Mode exec arguments violate the probe binding"
            )
        if (
            not isinstance(result, dict)
            or type(result.get("exit_code")) is not int
            or result.get("exit_code") != 0
            or not isinstance(result.get("output"), str)
        ):
            raise CodeModeWitnessError("Code Mode exec terminal result failed")
        native = _native_items(
            events, call_position, terminal_position, "CommandExecution"
        )
        native = [
            item
            for item in native
            if isinstance(item.get("command"), list)
            and item["command"]
            and _cwd_path(item["command"][0]) == _cwd_path(executor["shell_path"])
            and item["command"][1:-1]
            == (
                ["-NoProfile", "-Command"]
                if executor.get("family") == "windows"
                else ["-c"]
            )
            and item["command"][-1] == arguments["cmd"]
            and _cwd_path(item.get("cwd")) == _cwd_path(executor["working_directory"])
        ]
        if len(native) != 1:
            raise CodeModeWitnessError(
                "Code Mode exec lacks one matching native terminal"
            )
        item = native[0]
        if (
            item.get("status") != "completed"
            or type(item.get("exit_code")) is not int
            or item.get("exit_code") != 0
            or item.get("aggregated_output", item.get("stdout")) != result["output"]
        ):
            raise CodeModeWitnessError("Code Mode native exec terminal failed")
    else:
        queries = arguments.get("search_query")
        if (
            not isinstance(queries, list)
            or len(queries) != 1
            or not isinstance(queries[0], dict)
            or set(queries[0]) - {"q", "domains", "recency"}
            or not isinstance(queries[0].get("q"), str)
            or not isinstance(result, str)
            or not result.strip()
        ):
            raise CodeModeWitnessError("Code Mode search result is malformed")
        native = _native_items(events, call_position, terminal_position, "Extension")
        native = [
            item
            for item in native
            if item.get("kind") == "web.search"
            and item.get("query") == queries[0]["q"]
            and isinstance(item.get("results"), list)
            and item["results"]
        ]
        if len(native) != 1:
            raise CodeModeWitnessError(
                "Code Mode search lacks one matching native terminal"
            )
        item = native[0]
    if not isinstance(item.get("id"), str) or not item["id"]:
        raise CodeModeWitnessError("Code Mode native terminal has no identity")
    return {
        "arguments": arguments,
        "output": result,
        "native_item_id": item["id"],
    }


def inspect_production_child(
    events, event_id, child_thread_id, parent_thread_id, session_rows
):
    """Validate host spawn evidence and the child's native lineage metadata."""
    calls = []
    outputs = []
    activities = []
    for event in events:
        payload = _payload(event)
        if payload.get("call_id") == event_id:
            if payload.get("type") == "function_call":
                calls.append(payload)
            elif payload.get("type") == "function_call_output":
                outputs.append(payload)
        item = payload.get("item") if payload.get("type") == "item_completed" else None
        if isinstance(item, dict) and item.get("id") == event_id:
            activities.append(item)
    if len(calls) != 1 or len(outputs) != 1 or len(activities) != 1:
        raise CodeModeWitnessError("production child host linkage is ambiguous")
    call, output, activity = calls[0], outputs[0], activities[0]
    if call.get("name") != "spawn_agent" or call.get("namespace") != "collaboration":
        raise CodeModeWitnessError("production child call is not a native spawn")
    try:
        arguments = json.loads(call.get("arguments", ""))
        host_result = json.loads(output.get("output", ""))
    except ValueError as error:
        raise CodeModeWitnessError(
            "production child call metadata is malformed"
        ) from error
    if (
        not isinstance(arguments, dict)
        or set(arguments) != {"task_name", "fork_turns", "message"}
        or not isinstance(arguments["task_name"], str)
        or not isinstance(arguments["message"], str)
        or not isinstance(host_result, dict)
        or set(host_result) != {"task_name"}
        or not isinstance(host_result["task_name"], str)
    ):
        raise CodeModeWitnessError("production child call metadata is malformed")
    agent_path = host_result["task_name"]
    if (
        activity.get("type") != "SubAgentActivity"
        or activity.get("kind") != "started"
        or activity.get("agent_thread_id") != child_thread_id
        or activity.get("agent_path") != agent_path
        or not agent_path.endswith("/" + arguments["task_name"])
    ):
        raise CodeModeWitnessError("production child host linkage differs")
    matches = [row for row in session_rows if row[0] == child_thread_id]
    if len(matches) != 1:
        raise CodeModeWitnessError("production child session identity is ambiguous")
    _, child_events = matches[0]
    metadata = []
    for event in child_events:
        payload = _payload(event)
        if event.get("type") == "session_meta" and payload.get("id") == child_thread_id:
            metadata.append(payload)
    if len(metadata) != 1:
        raise CodeModeWitnessError("production child lineage metadata is ambiguous")
    source = metadata[0].get("source")
    subagent = source.get("subagent") if isinstance(source, dict) else None
    spawn = subagent.get("thread_spawn") if isinstance(subagent, dict) else None
    if (
        not isinstance(spawn, dict)
        or spawn.get("parent_thread_id") != parent_thread_id
        or type(spawn.get("depth")) is not int
        or spawn["depth"] != 1
        or spawn.get("agent_path") != agent_path
    ):
        raise CodeModeWitnessError("production child lineage metadata differs")
    result = False
    for event in child_events:
        payload = _payload(event)
        if (
            event.get("type") == "response_item"
            and payload.get("type") == "message"
            and payload.get("role") == "assistant"
        ):
            content = payload.get("content")
            if isinstance(content, str) and content.strip():
                result = True
            elif isinstance(content, list) and any(
                isinstance(part, dict)
                and part.get("type") in {"output_text", "text"}
                and isinstance(part.get("text"), str)
                and part["text"].strip()
                for part in content
            ):
                result = True
    if not result:
        raise CodeModeWitnessError("production child result is missing")
    return {"agent_path": agent_path, "parent_thread_id": spawn["parent_thread_id"]}

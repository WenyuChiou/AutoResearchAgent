"""Exact fresh-session permit gates; admission is not completed inference."""

from copy import deepcopy
from pathlib import Path
import re
import threading
import time
from _atlas_local_source import (
    LauncherError,
    require,
    digest,
    canonical,
    pinned,
    inventory,
)


class PermitLeaseExpired(LauncherError):
    """An observed permit boundary; never a source-integrity classification."""


class PermitAuthority:
    def __init__(
        self,
        *,
        spec,
        spec_path,
        spec_sha256,
        permit_path,
        permit_sha256,
        permit,
        manifest,
        repo,
    ):
        self.spec, self.path, self.sha = deepcopy(spec), spec_path, spec_sha256
        self.permit_path, self.permit_sha, self.permit = (
            permit_path,
            permit_sha256,
            permit,
        )
        self.manifest, self.repo = manifest, repo
        self.epoch = self.thread = None
        self.runtime, self.starts, self.phase = None, 0, -1
        self.lock = threading.RLock()
        self.deadline = time.monotonic() + min(
            spec["limits"]["lifetime_seconds"],
            permit.get("expires_at_unix", time.time() + 600) - time.time(),
        )

    def verify(self, event, *, full=False):
        with self.lock:
            require(
                set(event) == {"spec_sha256", "spec"}
                and event["spec_sha256"] == self.sha
                and event["spec"] == self.spec,
                "source callback binding differs",
            )
            self._active()
            pinned(self.path, self.sha)
            pinned(self.permit_path, self.permit_sha)
            pinned(
                self.permit["host_config"]["path"], self.permit["host_config"]["sha256"]
            )
            pinned(
                self.permit["user_config"]["path"], self.permit["user_config"]["sha256"]
            )
            pinned(
                self.permit["source_manifest"]["path"],
                self.permit["source_manifest"]["sha256"],
                1024 * 1024,
            )
            for name, expected in (
                ("index_path", "index_sha256"),
                ("input_path", "input_version"),
            ):
                pinned(self.spec[name], self.spec[expected], 32 * 1024 * 1024)
            if full:
                for root, expected in (
                    (
                        self.repo / "plugins/auto-research-agent",
                        self.manifest["plugin_files"],
                    ),
                    (Path(self.spec["source_root"]), self.manifest["source_files"]),
                ):
                    require(
                        inventory(root) == expected, "source/plugin inventory changed"
                    )
                pinned(
                    self.spec["executable"],
                    self.spec["executable_sha256"],
                    512 * 1024 * 1024,
                )
            elif getattr(self, "loader", None) is not None:
                for path in tuple(self.loader.paths.values()):
                    relative = "cli/" + path.relative_to(self.loader.root).as_posix()
                    pinned(
                        path, self.manifest["plugin_files"][relative], 32 * 1024 * 1024
                    )
            for path in getattr(self, "helper_paths", ()):
                relative = (
                    "cli/"
                    + path.relative_to(
                        self.repo / "plugins/auto-research-agent/cli"
                    ).as_posix()
                )
                pinned(path, self.manifest["plugin_files"][relative], 32 * 1024 * 1024)
            self._active()
            return True

    def _active(self):
        if not (
            time.monotonic() < self.deadline
            and time.time() < self.permit["expires_at_unix"]
        ):
            raise PermitLeaseExpired("permit/lease expired")

    def gate(self, name, event):
        with self.lock:
            require(
                set(event) == {"spec_sha256", "permit_sha256", "spec", "action"},
                "gate envelope fields differ",
            )
            self.verify(
                {k: event[k] for k in ("spec_sha256", "spec")},
                full=name in {"admit_spawn", "admit_attach", "admit_action"},
            )
            require(event["permit_sha256"] == self.permit_sha, "permit binding differs")
            action, spec = event["action"], self.spec
            require(
                isinstance(action, dict)
                and all(
                    action.get(k) == spec[k] for k in ("project_id", "index_sha256")
                ),
                "action project differs",
            )
            if name == "admit_spawn":
                expected = {
                    "project_id",
                    "index_sha256",
                    "input_version",
                    "connection_id",
                    "intent_key",
                    "payload_sha256",
                    "argv",
                }
                payload = dict(
                    executable=spec["executable"],
                    executable_sha256=spec["executable_sha256"],
                    cwd=spec["source_root"],
                    input_version=spec["input_version"],
                )
                require(
                    set(action) == expected
                    and action["input_version"] == spec["input_version"]
                    and action["intent_key"] == "spawn"
                    and action["payload_sha256"] == digest(canonical(payload))
                    and action["argv"]
                    == [str(Path(spec["executable"])), "app-server", "--stdio"],
                    "spawn scope differs",
                )
                epoch = action["connection_id"]
                require(
                    isinstance(epoch, str)
                    and re.fullmatch("atlas-[0-9a-f]{32}", epoch)
                    and self.epoch in (None, epoch),
                    "spawn epoch differs",
                )
                self._active()
                self.epoch = epoch
            elif name == "admit_lifecycle":
                methods = (
                    "new-session",
                    "initialize",
                    "initialized",
                    "account/read",
                    "thread/start",
                    "handoff",
                )
                params = dict(
                    cwd=spec["source_root"],
                    model=spec["model"],
                    approvalPolicy="on-request",
                    sandbox="read-only",
                    config=spec["thread_config"],
                )
                require(
                    set(action)
                    == {
                        "project_id",
                        "index_sha256",
                        "input_version",
                        "intent_key",
                        "method",
                        "params_sha256",
                    }
                    and action["input_version"] == spec["input_version"]
                    and action["intent_key"] == "new-thread"
                    and action["params_sha256"] == digest(canonical(params))
                    and self.epoch is not None
                    and action["method"] in methods,
                    "lifecycle scope differs",
                )
                phase = methods.index(action["method"])
                require(
                    phase in (self.phase, self.phase + 1), "lifecycle order differs"
                )
                self._active()
                self.phase = phase
            elif name == "admit_attach":
                require(
                    set(action)
                    == {
                        "project_ref",
                        "project_id",
                        "source_root",
                        "index_sha256",
                        "input_version",
                        "thread_id",
                        "connection_id",
                    }
                    and all(
                        action[k] == spec[k]
                        for k in ("project_ref", "source_root", "input_version")
                    )
                    and action["connection_id"] == self.epoch
                    and self.phase == 5
                    and isinstance(action["thread_id"], str)
                    and 0 < len(action["thread_id"]) <= 256
                    and self.thread in (None, action["thread_id"]),
                    "attach scope differs",
                )
                self._active()
                self.thread = action["thread_id"]
            elif name == "admit_action":
                self._action(action)
            else:
                raise LauncherError("unsupported gate")
            self._active()
            return True

    def _action(self, action):
        require(
            set(action)
            == {
                "project_id",
                "index_sha256",
                "thread_id",
                "connection_id",
                "method",
                "payload",
                "request_identity",
                "request_sha256",
            }
            and self.runtime is not None
            and action["connection_id"] == self.epoch
            and action["thread_id"] == self.thread,
            "action session differs",
        )
        payload, method = action["payload"], action["method"]
        controller = self.runtime._entries[0]["controller"]
        state = controller.store.snapshot(self.spec["project_id"])
        require(
            state["thread_id"] == self.thread
            and controller.connection_id == self.epoch,
            "active session differs",
        )
        if method == "turn/start":
            require(
                action["request_identity"] is None
                and action["request_sha256"] is None
                and isinstance(payload, dict)
                and set(payload) == {"threadId", "cwd", "model", "input"}
                and payload["threadId"] == self.thread
                and payload["cwd"] == self.spec["source_root"]
                and payload["model"] == self.spec["model"]
                and isinstance(payload["input"], list)
                and len(payload["input"]) == 1,
                "turn scope differs",
            )
            text = payload["input"][0]
            require(
                isinstance(text, dict)
                and set(text) == {"type", "text", "text_elements"}
                and text["type"] == "text"
                and text["text_elements"] == []
                and isinstance(text["text"], str)
                and text["text"].strip()
                and len(text["text"].encode("utf8"))
                <= self.spec["limits"]["max_text_bytes"]
                and self.starts < self.permit["max_turns"],
                "text/turn budget differs",
            )
            self._active()
            self.starts += 1
        elif method == "turn/interrupt":
            require(
                action["request_identity"] is None
                and action["request_sha256"] is None
                and isinstance(payload, dict)
                and set(payload) == {"threadId", "turnId"}
                and payload["threadId"] == self.thread
                and any(
                    row.get("native_turn_id") == payload["turnId"]
                    and row["method"] == "turn/start"
                    and row["status"] not in {"completed", "retired"}
                    for row in state["intents"].values()
                ),
                "interrupt target differs",
            )
        else:
            require(
                method
                in {
                    "item/tool/requestUserInput",
                    "item/commandExecution/requestApproval",
                    "item/fileChange/requestApproval",
                },
                "unsupported native request; no implicit answer",
            )
            matches = [
                r
                for r in state["requests"].values()
                if r["request_identity"] == action["request_identity"]
                and r["record_sha256"] == action["request_sha256"]
                and r["method"] == method
                and r["status"] == "pending"
            ]
            require(
                len(matches) == 1
                and action["request_identity"]["connection_id"] == self.epoch,
                "native request correlation differs",
            )
            from research_workspace_native.transport import validate_answer

            row = matches[0]
            validate_answer(
                dict(
                    id=action["request_identity"]["native_id"],
                    method=method,
                    params=row["payload"],
                ),
                payload,
            )
            require(
                method == "item/tool/requestUserInput"
                or payload.get("decision") in {"decline", "cancel"},
                "command/file approval Accept is not permitted",
            )

    def callbacks(self):
        def verify_source(event):
            try:
                return self.verify(event)
            except PermitLeaseExpired as error:
                # The permit helper runs before the pinned package loader exists.
                # Runtime callbacks run only after that loader is installed.
                from research_workspace_native.process_deadline import (
                    SessionLeaseExpired,
                )

                raise SessionLeaseExpired("permit/lease expired") from error

        return {
            "verify_source": verify_source,
            **{
                name: (lambda event, name=name: self.gate(name, event))
                for name in (
                    "admit_spawn",
                    "admit_lifecycle",
                    "admit_attach",
                    "admit_action",
                )
            },
        }

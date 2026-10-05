"""Bind an existing injected channel without creating a native session.

The caller supplies a real event sink, byte verifier and admission callback.
These callbacks do not authenticate a process or grant research authority.
Construction does no channel I/O; failure cleanup may close an established
recording wrapper. A later action controller can inherit this bound context.
"""

from .frame_journal import FrameJournal
from .recording import RecordingChannel
from .store import JournalError, _invalidate, _require
from .transport import JsonRpcTransport


class ControllerError(JournalError):
    """Controller stopped; persisted observations never authorize resending."""


def _mirror_unknown(state):
    for key, item in state.get("controller_actions", {}).items():
        if state["intents"].get(key, {}).get("status") == "execution-unknown":
            item["status"] = "execution-unknown"


class BoundControllerContext:
    """Own one bound epoch; expose context, private snapshots and explicit close."""

    def __init__(
        self,
        *,
        store,
        project_id,
        owner,
        connection_id,
        index_sha256,
        thread_id,
        channel,
        verify_binding,
        admit_action,
        on_event,
    ):
        _require(isinstance(store, FrameJournal), "frame journal required")
        _require(callable(on_event), "durable event sink required")
        _require(callable(admit_action) and callable(verify_binding), "gates required")
        _require(
            isinstance(connection_id, str) and 0 < len(connection_id) <= 128,
            "connection ID required",
        )
        _require(
            all(
                callable(getattr(channel, name, None))
                for name in ("read", "write", "close")
            ),
            "binary channel required",
        )
        self.channel = None
        self.store, self.project_id, self.owner = store, project_id, owner
        self.connection_id, self.index_sha256, self.thread_id = (
            connection_id,
            index_sha256,
            thread_id,
        )
        self.admit_action, self.failure, self.outgoing = admit_action, None, None
        with store._lock:
            state = store.snapshot(project_id)
            _require(
                state["index_sha256"] == index_sha256
                and state["thread_id"] == thread_id
                and isinstance(thread_id, str)
                and thread_id
                and state["owner"] is not None
                and state["owner"]["token"] == owner,
                "existing project/index/thread/owner binding required",
            )
            old = state.get("protocol", {}).get("binding", {})
            channels = state.get("byte_channels", {})
            _require(
                not any(
                    row.get("owner") == owner and not row.get("fault")
                    for row in channels.values()
                ),
                "healthy channel already owns this project",
            )
            _require(
                old.get("owner") != owner
                or channels.get(old.get("connection_id"), {}).get("fault")
                or state.get("controller_initialization_failures", {})
                .get(old.get("connection_id"), {})
                .get("owner")
                == owner,
                "existing protocol epoch must be closed",
            )
            _require(
                len(state.get("protocol", {}).get("connections", [])) < 128,
                "controller epoch history bound exceeded",
            )
            try:
                store.bind_connection(
                    project_id, owner, connection_id, state["revision"]
                )
                with store._edit(
                    project_id, owner, None, "controller-recovery-projection", {}
                ) as current:
                    _mirror_unknown(current)
                self.channel = RecordingChannel(
                    channel,
                    store=store,
                    project_id=project_id,
                    owner=owner,
                    connection_id=connection_id,
                )
                self.transport = JsonRpcTransport(
                    self.channel,
                    connection_id=connection_id,
                    verify_binding=verify_binding,
                    on_event=on_event,
                )
            except BaseException as error:
                self._initialization_failed(error)

    def _initialization_failed(self, error):
        self.failure = "controller initialization failed; no automatic reconnect"
        try:
            with self.store._edit(
                self.project_id,
                self.owner,
                None,
                "controller-initialization-failed",
                dict(
                    connection_id=self.connection_id,
                    exception_type=type(error).__name__,
                ),
            ) as state:
                binding = state.get("protocol", {}).get("binding", {})
                if binding.get(
                    "connection_id"
                ) == self.connection_id and self.connection_id not in state.get(
                    "controller_initialization_failures", {}
                ):
                    _invalidate(state)
                    _mirror_unknown(state)
                    state.setdefault("controller_initialization_failures", {})[
                        self.connection_id
                    ] = dict(owner=self.owner, exception_type=type(error).__name__)
                    channel = state.get("byte_channels", {}).get(self.connection_id)
                    if channel is not None:
                        channel["fault"] = self.failure
        except BaseException:
            self.failure += "; fault persistence unobserved"
        finally:
            if self.channel is not None:
                try:
                    self.channel.close()
                except BaseException:
                    self.failure += "; cleanup persistence unobserved"
        raise ControllerError(self.failure) from error

    def _context(self):
        state = self.store.snapshot(self.project_id)
        _require(
            state["index_sha256"] == self.index_sha256
            and state["thread_id"] == self.thread_id
            and state["owner"] is not None
            and state["owner"]["token"] == self.owner
            and self.store._owners.get(self.project_id, (None,))[0] == self.owner
            and state.get("protocol", {}).get("binding")
            == dict(
                connection_id=self.connection_id,
                owner=self.owner,
                index_sha256=self.index_sha256,
                thread_id=self.thread_id,
            ),
            "controller owner/project/epoch expired",
        )
        return state

    def view(self):
        """Detached private view; owner tokens, correlations and raw bytes omitted."""
        with self.store._lock:
            state = self._context()
            return dict(
                project_id=self.project_id,
                index_sha256=self.index_sha256,
                thread_id=self.thread_id,
                connection_id=self.connection_id,
                revision=state["revision"],
                failure=self.failure,
                requests=state["requests"],
                intents=state["intents"],
                turns=state["turns"],
                actions=state.get("controller_actions", {}),
            )

    def close(self):
        with self.store._lock:
            if self.failure:
                try:
                    self.transport.close()
                except Exception:
                    self.failure += "; cleanup persistence unobserved"
                return
            self.failure = "controller closed; no automatic reconnect"
            try:
                self._context()
                with self.store._edit(
                    self.project_id, self.owner, None, "controller-closed", {}
                ) as state:
                    _invalidate(state)
                    _mirror_unknown(state)
            finally:
                try:
                    self.transport.close()
                except Exception:
                    self.failure += "; cleanup persistence unobserved"

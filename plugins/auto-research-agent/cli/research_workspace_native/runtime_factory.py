"""Explicit bounded native composition; disabled by default, no resume.

Trusted callbacks are required and do not establish authentication or authority.
This supplies no model-token budget, process-tree isolation or research run.
"""

from copy import deepcopy
import threading
import uuid

from stage1_deliverable.common import private_output, reject_links, sha
from research_workspace_native.bootstrap import BootstrapSession
from research_workspace_native.controller import InjectedSessionController
from research_workspace_native.frame_journal import FrameJournal
from research_workspace_native.process_channel import OwnedProcessChannel
from research_workspace_native.server_owner import SessionOwners
from research_workspace_native.session_api import SessionApi
from .runtime_spec import CompositionError, _load_all, _read, _require, _thread_config


class NativeAtlasRuntime:
    """Own a ready registry and its private stores, with explicit passive start."""

    def __init__(self, registry):
        self.api, self.registry = registry.api, registry
        self._entries, self._closed, self._receipt = [], False, None
        self._lifecycle, self._started = threading.RLock(), False

    def bindings(self):
        return self.registry.bindings()

    def status(self):
        return {entry["ref"]: entry["owner"].status() for entry in self._entries}

    def start(self):
        with self._lifecycle:
            _require(
                not self._closed and not self._started,
                "runtime closed or already started",
            )
            try:
                for entry in self._entries:
                    entry["owner"].start()
                self._started = True
            except BaseException:
                self.shutdown()
                raise

    def shutdown(self, timeout=10):
        with self._lifecycle:
            if self._closed:
                return deepcopy(self._receipt)
            receipt = self.registry.shutdown(timeout)
            for entry in self._entries:
                if not entry.get("store_closed"):
                    entry["store"].close()
                    entry["store_closed"] = True
            self._closed, self._receipt = True, receipt
            return deepcopy(receipt)


def compose_runtime(registrations, *, authenticate=None, gates=None, enabled=False):
    """Create only explicitly admitted NEW sessions from pinned private specs.

    Each registration is (absolute spec path, exact SHA256). ``gates`` maps its
    project_ref to explicit verify_source/admit_spawn/admit_lifecycle/admit_attach/
    admit_action callbacks. Every gate receives the pinned spec hash and permit
    alongside the actual action. Callback success must be literal True. The
    default returns None without inspecting files or creating stores/processes.
    """
    _require(type(enabled) is bool, "literal enable flag required")
    if not enabled:
        return None
    _require(
        callable(authenticate) and isinstance(gates, dict),
        "trusted identity/gates required",
    )
    loaded = _load_all(registrations)
    callbacks = {
        "verify_source",
        "admit_spawn",
        "admit_lifecycle",
        "admit_attach",
        "admit_action",
    }
    _require(
        set(gates) == {row[2]["project_ref"] for row in loaded},
        "runtime gate refs differ",
    )
    for _, _, spec in loaded:
        bound = gates[spec["project_ref"]]
        _require(
            isinstance(bound, dict)
            and callbacks <= set(bound) <= callbacks | {"approval_policy"}
            and all(callable(bound[name]) for name in bound),
            "explicit runtime gates required",
        )
    runtime = NativeAtlasRuntime(
        SessionOwners(api=SessionApi(authenticate=authenticate))
    )
    orphan = None
    try:
        for path, digest, spec in loaded:
            bound = gates[spec["project_ref"]]

            def check(path=path, digest=digest, spec=spec, bound=bound):
                _require(sha(_read(path)) == digest, "runtime spec changed")
                for name, expected in (
                    ("index_path", "index_sha256"),
                    ("input_path", "input_version"),
                ):
                    _require(
                        sha(_read(spec[name], 32 * 1024 * 1024)) == spec[expected],
                        "source version changed",
                    )
                _require(
                    bound["verify_source"](
                        dict(spec_sha256=digest, spec=deepcopy(spec))
                    )
                    is True,
                    "literal source verification required",
                )
                return True

            def gate(name, action, digest=digest, spec=spec, bound=bound):
                return (
                    bound[name](
                        dict(
                            spec_sha256=digest,
                            permit_sha256=spec["permit_sha256"],
                            spec=deepcopy(spec),
                            action=deepcopy(action),
                        )
                    )
                    is True
                )

            check()
            path_store = private_output(spec["store_path"])
            reject_links(path_store)
            with path_store.open("xb"):
                pass  # Exclusive reservation; failed state is retained, not removed.
            store = FrameJournal.__new__(FrameJournal)
            orphan = dict(store=store, channel=None, controller=None)
            FrameJournal.__init__(store, path_store)
            store.bind_project(spec["project_id"], spec["index_sha256"])
            token = store.acquire_owner(spec["project_id"], "atlas-composition")
            epoch = "atlas-" + uuid.uuid4().hex
            store.record_intent(
                spec["project_id"],
                token,
                "spawn",
                "app-server/spawn",
                dict(
                    executable=spec["executable"],
                    executable_sha256=spec["executable_sha256"],
                    cwd=spec["source_root"],
                    input_version=spec["input_version"],
                ),
                store.snapshot(spec["project_id"])["revision"],
            )
            # Retain even a failed constructor so its physical cleanup can be observed.
            raw = OwnedProcessChannel.__new__(OwnedProcessChannel)
            orphan["channel"] = raw
            OwnedProcessChannel.__init__(
                raw,
                store=store,
                project_id=spec["project_id"],
                owner=token,
                connection_id=epoch,
                index_sha256=spec["index_sha256"],
                input_version=spec["input_version"],
                intent_key="spawn",
                verify_binding=check,
                admit_spawn=lambda a, g=gate: g("admit_spawn", a),
                lifetime=spec["limits"]["lifetime_seconds"],
                max_stream_bytes=spec["limits"]["max_stream_bytes"],
            )
            params = dict(
                cwd=spec["source_root"],
                model=spec["model"],
                approvalPolicy=spec["approval_policy"],
                sandbox="read-only",
            )
            if "thread_config" in spec:
                params["config"] = _thread_config(spec["thread_config"])
            store.record_intent(
                spec["project_id"],
                token,
                "new-thread",
                "thread/start",
                params,
                store.snapshot(spec["project_id"])["revision"],
            )
            boot = BootstrapSession(
                store=store,
                project_id=spec["project_id"],
                owner=token,
                connection_id=epoch,
                index_sha256=spec["index_sha256"],
                input_version=spec["input_version"],
                intent_key="new-thread",
                channel=raw,
                verify_binding=check,
                admit_lifecycle=lambda a, g=gate: g("admit_lifecycle", a),
            )
            boot.open_thread(
                dict(name="harness-atlas", version="1"),
                timeout=spec["limits"]["timeout_seconds"],
                **(
                    {"total_timeout": spec["handshake_timeout_seconds"]}
                    if "handshake_timeout_seconds" in spec
                    else {}
                ),
            )
            controller = InjectedSessionController.adopt_ready(
                boot, admit_action=lambda a, g=gate: g("admit_action", a)
            )
            orphan["controller"] = controller

            def verify_source(binding, check=check, spec=spec):
                _require(
                    all(
                        binding[name] == spec[name]
                        for name in (
                            "project_ref",
                            "project_id",
                            "source_root",
                            "index_sha256",
                            "input_version",
                        )
                    ),
                    "attach source binding differs",
                )
                return check()

            def offer(context, check=check, spec=spec):
                check()
                _require(
                    all(
                        context[name] == spec[name]
                        for name in (
                            "project_ref",
                            "project_id",
                            "source_root",
                            "index_sha256",
                            "input_version",
                        )
                    )
                    and context["principal"] in spec["principals"],
                    "offer project differs",
                )
                return dict(
                    project_id=spec["project_id"],
                    index_sha256=spec["index_sha256"],
                    input_version=spec["input_version"],
                    source_root=spec["source_root"],
                    model=spec["model"],
                    permit_sha256=spec["permit_sha256"],
                    limits={
                        k: spec["limits"][k]
                        for k in ("max_text_bytes", "max_starts", "timeout_seconds")
                    },
                )

            approval = None
            if "approval_policy" in bound:

                def approval(a, g=gate):
                    return g("approval_policy", a)

            owner = runtime.registry.register(
                spec["project_ref"],
                controller=controller,
                owned_channel=raw,
                principals=spec["principals"],
                source_root=spec["source_root"],
                index_sha256=spec["index_sha256"],
                input_version=spec["input_version"],
                verify_source=verify_source,
                admit_attach=lambda a, g=gate: g("admit_attach", a),
                start_offer=offer,
                approval_policy=approval,
            )
            runtime._entries.append(dict(orphan, owner=owner, ref=spec["project_ref"]))
            orphan = None
        return runtime
    except BaseException as error:
        cleanup = []
        try:
            runtime.shutdown()
        except BaseException as failed:
            cleanup.append(type(failed).__name__)
        if orphan is not None:
            try:
                if orphan["controller"] is not None:
                    orphan["controller"].close()
                if orphan["channel"] is not None:
                    orphan["channel"].close()
                    result = orphan["channel"].reap(10)
                    _require(
                        (
                            result.get("leader_reaped") is True
                            and result.get("errors") == []
                            or orphan["channel"].process is None
                            and result.get("not_started") is True
                        )
                        and result.get("journal_cleanup_observed") is True,
                        "orphan cleanup unobserved",
                    )
                if getattr(orphan["store"], "db", None) is not None:
                    orphan["store"].close()
            except BaseException as failed:
                cleanup.append(type(failed).__name__)
        if cleanup:
            failed = CompositionError(
                "composition failed; cleanup unobserved: " + ",".join(cleanup)
            )
            failed.runtime, failed.orphan = runtime, orphan
            raise failed from error
        raise

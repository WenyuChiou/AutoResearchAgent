"""Explicit local source worker, with no default dispatcher or live authority.

The source broker owns scope, grant, reservation and SQLite history. This runner
contains a fixed Windows worker and preserves its private execution observations.
Its optional fixed offline SDK operation imports saved bytes under the original
deadline. It never writes Core claims, adopts output or grants new authority.
Configuration hashes are not runtime authentication.
"""

from copy import deepcopy
from datetime import datetime, timezone
import math
import os
from pathlib import Path, PurePosixPath
import queue
import sys
import threading
import time

from stage1_deliverable.common import canonical, private_output, sha
from .acquired_source_parser import _acquisition
from .atlas_local_source import (
    LauncherError,
    PinnedLoader,
    decode,
    pinned,
    read,
    require,
    unlinked,
)
from .bounded_public_source import request_binding
from .project_stage1_source_service import ProjectStage1SourceService, SourceJobRunner
from .session_api import SessionApiError
from .project_source_permit import configuration as source_configuration
from .source_worker_process import WindowsJobProcess, WindowsJobWatchdog

MAX_FRAME = 16 * 1024
CONFIG_FIELDS = {
    "kind",
    "schema_version",
    "repo",
    "files",
    "inventory_sha256",
    "interpreter",
    "interpreter_sha256",
    "git_executable",
    "git_sha256",
    "execution_source_sha256",
    "runtime_sha256",
    "resolver_sha256",
    "materials_root",
    "cleanup_reserve_seconds",
    "guard_timeout_seconds",
    "max_stdout_bytes",
    "max_stderr_bytes",
    "max_frames",
}


def worker_configuration(value):
    require(
        type(value) is dict and set(value) == CONFIG_FIELDS,
        "source-worker-configuration-fields",
    )
    require(
        value["kind"] == "OwnedSourceWorkerConfiguration"
        and value["schema_version"] == "1.0.0",
        "source-worker-configuration-version",
    )
    for name in (
        "inventory_sha256",
        "interpreter_sha256",
        "git_sha256",
        "execution_source_sha256",
        "runtime_sha256",
        "resolver_sha256",
    ):
        text = value[name]
        require(
            type(text) is str
            and len(text) == 64
            and all(c in "0123456789abcdef" for c in text),
            "source-worker-hash-required",
        )
    for name in ("repo", "interpreter", "git_executable", "materials_root"):
        require(
            type(value[name]) is str
            and "\0" not in value[name]
            and Path(value[name]).is_absolute(),
            "source-worker-fixed-path-required",
        )
    require(
        Path(value["git_executable"]).name.lower() == "git.exe",
        "source-worker-fixed-git-required",
    )
    files = value["files"]
    require(
        type(files) is dict and 1 <= len(files) <= 4096,
        "source-worker-inventory-required",
    )
    for name, digest in files.items():
        path = PurePosixPath(name)
        require(
            type(name) is str
            and not path.is_absolute()
            and bool(path.parts)
            and str(path) == name
            and ".." not in path.parts
            and "\\" not in name
            and ":" not in name
            and type(digest) is str
            and len(digest) == 64
            and all(c in "0123456789abcdef" for c in digest),
            "source-worker-inventory-path-invalid",
        )
    require(
        sha(canonical(files)) == value["inventory_sha256"],
        "source-worker-inventory-hash-differs",
    )
    require(
        value["execution_source_sha256"] == value["inventory_sha256"],
        "source-worker-execution-inventory-differs",
    )
    for name in ("cleanup_reserve_seconds", "guard_timeout_seconds"):
        require(
            type(value[name]) in (int, float)
            and math.isfinite(value[name])
            and 0 < value[name] <= 2,
            "source-worker-time-bound-invalid",
        )
    for name in ("max_stdout_bytes", "max_stderr_bytes"):
        require(
            type(value[name]) is int and 1024 <= value[name] <= 1024 * 1024,
            "source-worker-stream-bound-invalid",
        )
    require(
        type(value["max_frames"]) is int and 1 <= value["max_frames"] <= 64,
        "source-worker-frame-bound-invalid",
    )
    return deepcopy(value)


def _save(path, value):
    raw = canonical(value)
    require(len(raw) <= 2 * 1024 * 1024, "source-worker-observation-bound")
    with path.open("xb") as stream:
        require(
            stream.write(raw) == len(raw), "source-worker-observation-partial-write"
        )
        stream.flush()
        os.fsync(stream.fileno())
    digest = sha(raw)
    pinned(path, digest, 2 * 1024 * 1024)
    return digest


class _Streams:
    """Two bounded readers and one bounded writer; no new thread per frame."""

    def __init__(self, process, config):
        self.process, self.config = process, config
        self.incoming = queue.Queue(maxsize=config["max_frames"])
        self.outgoing = queue.Queue(maxsize=1)
        self.failure = None
        self._failure_lock = threading.Lock()
        self.prefix = {"stdout": bytearray(), "stderr": bytearray()}
        self.counts = {"stdout": 0, "stderr": 0}
        self.frames = 0
        self.threads = [
            threading.Thread(target=self._reader, args=(name,), daemon=True)
            for name in ("stdout", "stderr")
        ]
        self.threads.append(threading.Thread(target=self._writer, daemon=True))
        for thread in self.threads:
            thread.start()

    def _fail(self, code):
        with self._failure_lock:
            if self.failure is None:
                self.failure = code

    def _reader(self, name):
        pending = bytearray()
        try:
            while True:
                raw = getattr(self.process, name).read(4096)
                if not raw:
                    if name == "stdout" and pending:
                        self._fail("source-worker-partial-frame")
                    return
                self.counts[name] += len(raw)
                cap = self.config["max_" + name + "_bytes"]
                self.prefix[name].extend(raw[: max(0, cap - len(self.prefix[name]))])
                if self.counts[name] > cap:
                    self._fail("source-worker-stream-overflow")
                    return
                if name == "stdout":
                    pending.extend(raw)
                    while b"\n" in pending:
                        line, _, tail = pending.partition(b"\n")
                        pending = bytearray(tail)
                        self.frames += 1
                        if (
                            not line
                            or len(line) > MAX_FRAME
                            or self.frames > self.config["max_frames"]
                        ):
                            raise ValueError("source-worker-frame-bound")
                        self.incoming.put_nowait(decode(line))
                    if len(pending) > MAX_FRAME:
                        raise ValueError("source-worker-frame-bound")
        except BaseException:
            self._fail("source-worker-stream-invalid")

    def _writer(self):
        try:
            while True:
                item = self.outgoing.get()
                if item is None:
                    return
                raw, done = item
                require(
                    self.process.stdin.write(raw) == len(raw),
                    "source-worker-pipe-partial-write",
                )
                self.process.stdin.flush()
                done.set()
        except BaseException:
            self._fail("source-worker-write-unobserved")

    def send(self, value, cutoff):
        raw = canonical(value) + b"\n"
        require(len(raw) <= MAX_FRAME, "source-worker-frame-bound")
        done = threading.Event()
        self.outgoing.put_nowait((raw, done))
        while not done.wait(min(0.02, max(0, cutoff - time.monotonic()))):
            require(
                self.failure is None and time.monotonic() < cutoff,
                "source-worker-write-deadline",
            )
        require(time.monotonic() < cutoff, "source-worker-write-deadline")

    def join(self, end):
        try:
            self.outgoing.put_nowait(None)
        except queue.Full:
            pass
        for thread in self.threads:
            thread.join(max(0, end - time.monotonic()))
        joined = all(not thread.is_alive() for thread in self.threads)
        if joined:
            for stream in (
                self.process.stdin,
                self.process.stdout,
                self.process.stderr,
            ):
                if stream is not None:
                    stream.close()
        return dict(
            threads_joined=joined,
            failure=self.failure,
            counts=dict(self.counts),
            stdout_prefix_sha256=sha(bytes(self.prefix["stdout"])),
            stderr_prefix_sha256=sha(bytes(self.prefix["stderr"])),
            stdout_prefix_truncated=self.counts["stdout"] > len(self.prefix["stdout"]),
            stderr_prefix_truncated=self.counts["stderr"] > len(self.prefix["stderr"]),
            stream_counts_scope="bytes-observed-by-parent",
            extra_frames=not self.incoming.empty(),
            observed_frames=self.frames,
        )


class ContainedSourceJobRunner(SourceJobRunner):
    """One server-registered runner; a hung guard permanently poisons reuse.

    check_current is read-only, may acquire the intake lock, and returns None on
    successful saved checks. A watchdog never waits on that lock. Its daemon
    cannot be forcibly cancelled; at most one can remain per poisoned runner.
    """

    def __init__(self, config):
        self.config = worker_configuration(config)
        self.config_sha256 = sha(canonical(self.config))
        self._lock, self._poisoned, self._observations = threading.Lock(), False, []
        self._guard_thread = None

    @property
    def binding_sha256(self):
        return self.config["execution_source_sha256"]

    @property
    def resolver_sha256(self):
        return self.config["resolver_sha256"]

    @property
    def observations(self):
        return deepcopy(self._observations)

    def verify_configuration(self, service_config):
        """Read-only physical verifier for the broker's pre-reservation gate."""
        configured = source_configuration(service_config)
        require(
            configured["runtime_sha256"] == self.config["runtime_sha256"]
            and configured["execution_source_sha256"] == self.binding_sha256,
            "source-worker-service-config-differs",
        )
        require(
            self.config["cleanup_reserve_seconds"]
            < configured["caps"]["timeout_seconds"],
            "source-worker-cleanup-reserve-invalid",
        )
        require(not self._poisoned and os.name == "nt", "source-worker-unavailable")
        self._pins()
        return True

    def create_service(self, intake, stage1, *, config, pipeline=None, run_grants=None):
        """Register only this sealed root/runner into the unchanged broker."""
        sealed_root = private_output(Path(self.config["materials_root"])).resolve()
        self.verify_configuration(config)

        def verify(service_config):
            try:
                require(
                    service.runner is self
                    and service.materials_root == sealed_root
                    and sealed_root
                    == private_output(Path(self.config["materials_root"])).resolve(),
                    "source-worker-registration-root-differs",
                )
                return self.verify_configuration(service_config)
            except (LauncherError, OSError, KeyError, TypeError) as error:
                raise SessionApiError(
                    "source-worker-configuration-unverified"
                ) from error

        service = ProjectStage1SourceService(
            intake,
            stage1,
            config=config,
            materials_root=sealed_root,
            runner=self,
            verify_configuration=verify,
            pipeline=pipeline,
            run_grants=run_grants,
        )
        return service

    def _guard(self, callback, cutoff):
        require(
            not self._poisoned and time.monotonic() < cutoff,
            "source-worker-unusable-or-expired",
        )
        require(
            sha(canonical(worker_configuration(self.config))) == self.config_sha256,
            "source-worker-config-changed",
        )
        require(
            self._guard_thread is None or not self._guard_thread.is_alive(),
            "source-worker-guard-still-running",
        )
        done = queue.Queue(maxsize=1)

        def verify():
            try:
                value = callback()
                done.put((value, None))
            except BaseException as error:
                done.put((None, error))

        self._guard_thread = threading.Thread(target=verify, daemon=True)
        guard_end = min(cutoff, time.monotonic() + self.config["guard_timeout_seconds"])
        self._guard_thread.start()
        try:
            value, error = done.get(timeout=max(0, guard_end - time.monotonic()))
        except queue.Empty as error:
            self._poisoned = True
            raise TimeoutError("source-worker-guard-deadline") from error
        self._guard_thread.join(max(0, guard_end - time.monotonic()))
        if self._guard_thread.is_alive() or time.monotonic() >= guard_end:
            self._poisoned = True
            raise TimeoutError("source-worker-guard-completion-unobserved")
        require(time.monotonic() < cutoff, "source-worker-guard-late")
        require(
            sha(canonical(worker_configuration(self.config))) == self.config_sha256,
            "source-worker-config-changed",
        )
        if error is not None:
            raise error
        require(value is None or value is True, "source-worker-current-refused")

    def _pins(self):
        require(
            sha(canonical(worker_configuration(self.config))) == self.config_sha256,
            "source-worker-config-changed",
        )
        config, repo = self.config, unlinked(Path(self.config["repo"]))
        root = unlinked(repo / "plugins/auto-research-agent")
        cli = unlinked(root / "cli")
        actual = {"cli/" + p.relative_to(cli).as_posix() for p in cli.rglob("*.py")}
        require(
            actual
            == {
                p for p in config["files"] if p.startswith("cli/") and p.endswith(".py")
            },
            "source-worker-complete-source-required",
        )
        for name, digest in config["files"].items():
            require(
                sha(read(root / name, 32 * 1024 * 1024, allow_empty=True)) == digest,
                "source-worker-inventory-bytes-differ",
            )
        names = {
            p.name
            for p in cli.iterdir()
            if p.is_dir() and (p / "__init__.py").is_file()
        } | {p.stem for p in cli.glob("*.py")}
        observed, active_loader = set(), None
        for name, module in tuple(sys.modules.items()):
            if name.split(".")[0] not in names:
                continue
            expected = cli.joinpath(*name.split("."))
            package = expected.is_dir()
            expected = (
                expected / "__init__.py" if package else expected.with_suffix(".py")
            )
            spec = getattr(module, "__spec__", None)
            loader = getattr(module, "__loader__", None)
            if name == "research_workspace_native.atlas_local_source" and spec is None:
                # Existing fresh launcher aliases this raw-pinned bootstrap
                # helper after constructing its loader, preserving class identity.
                require(
                    getattr(module, "__file__", None) == str(expected)
                    and module.PinnedLoader is PinnedLoader,
                    "source-worker-bootstrap-helper-differs",
                )
                observed.add(name)
                continue
            require(
                getattr(module, "__file__", None) == str(expected)
                and spec is not None
                and spec.origin == str(expected)
                and isinstance(loader, PinnedLoader)
                and spec.loader is loader
                and loader.root == cli
                and loader.files == config["files"]
                and loader.paths.get(name) == expected
                and loader in sys.meta_path,
                "source-worker-active-raw-origin-differs",
            )
            require(
                active_loader is None or active_loader is loader,
                "source-worker-mixed-raw-loader",
            )
            active_loader = loader
            if package:
                require(
                    list(module.__path__) == [str(expected.parent)]
                    and list(spec.submodule_search_locations or ())
                    == [str(expected.parent)],
                    "source-worker-package-path-differs",
                )
            observed.add(name)
        require(
            {
                __name__,
                "research_workspace_native.source_worker_process",
                "research_workspace_native.project_stage1_source_service",
                "research_workspace_native.acquired_source_parser",
            }.issubset(observed),
            "source-worker-required-module-missing",
        )
        require(
            type(self) is ContainedSourceJobRunner
            and self.run.__func__.__code__.co_filename
            == str(cli / "research_workspace_native/source_worker_runner.py")
            and _acquisition.__code__.co_filename
            == str(cli / "research_workspace_native/acquired_source_parser.py"),
            "source-worker-callable-origin-differs",
        )
        pinned(
            Path(config["interpreter"]), config["interpreter_sha256"], 64 * 1024 * 1024
        )
        pinned(Path(config["git_executable"]), config["git_sha256"], 64 * 1024 * 1024)
        private_output(Path(config["materials_root"]))

    def run(self, request, output_dir, *, check_current):
        request = request_binding(request)
        require(callable(check_current), "source-worker-current-check-required")
        declared = datetime.fromisoformat(
            request["deadline_utc"].replace("Z", "+00:00")
        )
        monotonic_anchor = time.monotonic()
        left = min(
            (declared - datetime.now(timezone.utc)).total_seconds(),
            request["total_timeout_seconds"],
        )
        end = monotonic_anchor + left
        cutoff = end - self.config["cleanup_reserve_seconds"]
        require(
            left > self.config["cleanup_reserve_seconds"],
            "source-worker-insufficient-deadline",
        )
        require(
            self._lock.acquire(timeout=max(0, cutoff - time.monotonic())),
            "source-worker-lock-deadline",
        )
        try:
            require(not self._poisoned, "source-worker-poisoned")
            require(os.name == "nt", "source-worker-platform-unavailable")
            self._pins()
            require(
                request["runtime_sha256"] == self.config["runtime_sha256"]
                and request["resolver_sha256"] == self.resolver_sha256,
                "source-worker-request-bindings-differ",
            )
            output = private_output(Path(output_dir))
            root = unlinked(Path(self.config["materials_root"]))
            require(
                output.is_relative_to(root) and output != root and not output.exists(),
                "source-worker-new-private-output-required",
            )
            self._guard(check_current, cutoff)
            control = private_output(
                output.parent / ("w" + sha(canonical(request))[:20])
            )
            control.mkdir()  # Exclusive: no adoption, reuse or auto-resend.
            return self._run(request, output, control, check_current, cutoff, end)
        finally:
            self._lock.release()

    def run_sdk(
        self, request, output_dir, *, parse_saved_manifest, deadline, check_current
    ):
        """Run only the registered saved parser with the original job's time.

        No new grant, reservation, acquisition retry or per-phase lease exists.
        The caller must retain its original absolute monotonic deadline object.
        """
        from .saved_source_parser_factory import original_deadline_end
        from .saved_source_parser_runtime import configuration, verify_sdk

        request = request_binding(request)
        require(callable(check_current), "saved-parser-current-check-required")
        phase = deepcopy(parse_saved_manifest)
        require(
            type(phase) is dict
            and set(phase)
            == {
                "kind",
                "schema_version",
                "operation",
                "runtime",
                "input_manifest",
                "manifest_sha256",
                "original_deadline_end",
            }
            and phase["kind"] == "SavedSourceParserOperation"
            and phase["schema_version"] == "1.0.0"
            and phase["operation"] == "parse_saved_manifest",
            "saved-parser-fixed-operation-required",
        )
        configuration(phase["runtime"])
        declared = datetime.fromisoformat(
            request["deadline_utc"].replace("Z", "+00:00")
        )
        original_end = original_deadline_end(deadline)
        require(
            phase["original_deadline_end"] == original_end,
            "saved-parser-original-end-differs",
        )
        end = min(
            original_end,
            time.monotonic() + (declared - datetime.now(timezone.utc)).total_seconds(),
        )
        cutoff = end - self.config["cleanup_reserve_seconds"]
        phase["cutoff_monotonic"] = cutoff
        require(time.monotonic() < cutoff, "saved-parser-original-deadline-expired")
        require(
            self._lock.acquire(timeout=max(0, cutoff - time.monotonic())),
            "saved-parser-lock-deadline",
        )
        try:
            require(
                not self._poisoned and os.name == "nt",
                "saved-parser-worker-unavailable",
            )
            self._pins()
            verify_sdk(phase["runtime"])
            require(
                request["runtime_sha256"] == self.config["runtime_sha256"]
                and request["resolver_sha256"] == self.resolver_sha256,
                "saved-parser-request-bindings-differ",
            )
            output = private_output(Path(output_dir))
            root = unlinked(Path(self.config["materials_root"]))
            manifest = unlinked(Path(phase["input_manifest"]))
            require(
                output.is_relative_to(root)
                and output != root
                and not output.exists()
                and manifest.is_relative_to(root)
                and manifest.name == "source-parse-input.json",
                "saved-parser-private-fresh-path-required",
            )
            require(
                sha(read(manifest, 256 * 1024)) == phase["manifest_sha256"],
                "saved-parser-manifest-hash-differs",
            )
            self._guard(check_current, cutoff)
            deadline.check()
            control = private_output(
                output.parent
                / ("p" + sha(canonical(dict(request=request, phase=phase)))[:20])
            )
            control.mkdir()
            return self._run(
                request,
                output,
                control,
                check_current,
                cutoff,
                end,
                parse_saved_manifest=phase,
            )
        finally:
            self._lock.release()

    def _run(
        self,
        request,
        output,
        control,
        callback,
        cutoff,
        end,
        *,
        parse_saved_manifest=None,
    ):
        config, process, streams, primary, terminal = (
            self.config,
            None,
            None,
            None,
            None,
        )
        watchdog = None
        sequence = 0
        event_bytes = bytearray()
        request_sha256 = sha(canonical(request))
        sdk_parse = parse_saved_manifest is not None

        def pins():
            self._pins()
            if sdk_parse:
                from .saved_source_parser_runtime import verify_sdk

                verify_sdk(parse_saved_manifest["runtime"])
            require(time.monotonic() < cutoff, "source-worker-pin-deadline")

        row = dict(
            kind="OwnedSourceWorkerObservation",
            schema_version="1.0.0",
            request_sha256=request_sha256,
            job_binding_sha256=request["job_binding_sha256"],
            config_sha256=self.config_sha256,
            deadline_utc=request["deadline_utc"],
            status="intent-recorded",
            process_started=False,
            source_acquisition_observed=False,
            runtime_authenticated=False,
            automatic_retry=False,
            synchronous_os_calls_preemptible=False,
            observation_persisted=False,
            operation="parse_saved_manifest" if sdk_parse else "acquire_public_source",
            sdk_parse_observed=False,
        )
        self._observations.append(row)
        if len(self._observations) > 128:
            del self._observations[:-128]  # Full history stays in exclusive files.

        def event(kind, **values):
            raw = (
                canonical(dict(kind=kind, request_sha256=request_sha256, **values))
                + b"\n"
            )
            with (control / "events.jsonl").open("ab") as stream:
                require(
                    stream.write(raw) == len(raw), "source-worker-event-partial-write"
                )
                stream.flush()
                os.fsync(stream.fileno())
            event_bytes.extend(raw)
            require(
                read(control / "events.jsonl", 2 * 1024 * 1024) == bytes(event_bytes),
                "source-worker-event-readback-differs",
            )

        try:
            launch = dict(
                kind="OwnedSavedSourceParserLaunch"
                if sdk_parse
                else "OwnedSourceWorkerLaunch",
                schema_version="1.0.0",
                config=deepcopy(config),
                config_sha256=self.config_sha256,
                request=request,
                request_sha256=request_sha256,
                output_dir=str(output),
                git_global_config=dict(
                    path=str(control / "gitconfig"), sha256=sha(b"")
                ),
            )
            if sdk_parse:
                launch["parse_saved_manifest"] = deepcopy(parse_saved_manifest)
            with (control / "gitconfig").open("xb") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            require(
                read(control / "gitconfig", 0, allow_empty=True) == b"",
                "source-worker-git-config-differs",
            )
            launch_sha256 = _save(control / "launch.json", launch)
            _save(control / "intent.json", row)
            temp = control / "temp"
            temp.mkdir()
            env = {
                "SystemRoot": os.environ["SystemRoot"],
                "TEMP": str(temp),
                "TMP": str(temp),
                "PATH": str(Path(config["git_executable"]).parent)
                + os.pathsep
                + str(Path(os.environ["SystemRoot"]) / "System32"),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": str(control / "gitconfig"),
                "GIT_TERMINAL_PROMPT": "0",
            }
            if sdk_parse:
                # The original SDK computes Path.home() at import time. Supply
                # an isolated real directory rather than user configuration.
                home = control / "home"
                home.mkdir()
                env["USERPROFILE"] = str(home)
            # Preserve existing sandbox restrictions, never change their values.
            env.update(
                {k: v for k, v in os.environ.items() if k.startswith("CODEX_SANDBOX")}
            )
            self._guard(callback, cutoff)
            pins()
            require(time.monotonic() < cutoff, "source-worker-startup-deadline")
            bootstrap = (
                Path(config["repo"])
                / "plugins/auto-research-agent/cli/research_workspace_native/source_worker_bootstrap.py"
            )
            process = WindowsJobProcess.launch(
                config["interpreter"],
                [
                    "-I",
                    "-S",
                    "-B",
                    "-u",
                    str(bootstrap),
                    str(control / "launch.json"),
                    launch_sha256,
                ],
                str(control),
                env,
                absolute_end=cutoff,
                cleanup_end=end,
            )
            watchdog = WindowsJobWatchdog(process, cutoff, end)
            row.update(
                process_started=True,
                pid=process.pid,
                containment_admitted=process.contained,
            )
            event(
                "suspended-child-contained",
                pid=process.pid,
                membership=process.contained,
            )
            self._guard(callback, cutoff)
            require(time.monotonic() < cutoff, "source-worker-resume-deadline")
            streams = _Streams(process, config)
            process.resume()
            event("initial-thread-resumed", pid=process.pid)
            while True:
                require(time.monotonic() < cutoff, "source-worker-execution-cutoff")
                require(streams.failure is None, "source-worker-stream-failed")
                self._guard(callback, cutoff)
                try:
                    frame = streams.incoming.get(
                        timeout=min(0.05, max(0, cutoff - time.monotonic()))
                    )
                except queue.Empty:
                    require(
                        process.poll() is None, "source-worker-exited-without-terminal"
                    )
                    continue
                common = dict(
                    sequence=sequence,
                    request_sha256=request_sha256,
                    config_sha256=self.config_sha256,
                )
                require(
                    type(frame.get("sequence")) is int
                    and all(frame.get(k) == v for k, v in common.items()),
                    "source-worker-frame-binding-differs",
                )
                if frame.get("kind") == "gate":
                    require(
                        set(frame) == set(common) | {"kind", "phase"}
                        and frame["phase"]
                        == (
                            (
                                "before-sdk-parse"
                                if sequence == 0
                                else "before-sdk-observation"
                                if sequence == 1
                                else None
                            )
                            if sdk_parse
                            else (
                                "before-transport"
                                if sequence == 0
                                else "before-dns"
                                if sequence % 2
                                else "after-dns"
                            )
                        ),
                        "source-worker-gate-invalid",
                    )
                    require(
                        (sequence == 0)
                        == (
                            frame["phase"]
                            == ("before-sdk-parse" if sdk_parse else "before-transport")
                        ),
                        "source-worker-gate-order",
                    )
                    if sdk_parse:
                        # No source parsing or observation is admitted until
                        # full source/SDK bytes and the latest owner pass. The
                        # child also repins every module/resource as loaded.
                        self._guard(callback, cutoff)
                        pins()
                        self._guard(callback, cutoff)
                        event("gate-admitted", sequence=sequence, phase=frame["phase"])
                    else:
                        pins()
                        self._guard(callback, cutoff)
                        pins()
                        require(
                            time.monotonic() < cutoff, "source-worker-admission-late"
                        )
                        event("gate-admitted", sequence=sequence, phase=frame["phase"])
                        self._guard(callback, cutoff)
                        pins()
                    require(
                        time.monotonic() < cutoff,
                        "source-worker-final-admission-expired",
                    )
                    streams.send(dict(kind="admit", **common), cutoff)
                    sequence += 1
                else:
                    require(
                        frame.get("kind") == "terminal"
                        and (
                            sequence == 2
                            if sdk_parse
                            else sequence >= 3 and sequence % 2 == 1
                        ),
                        "source-worker-terminal-invalid",
                    )
                    require(
                        set(frame)
                        == set(common)
                        | {"kind", "status", "receipt_path", "receipt_sha256"}
                        and frame["status"] == "receipt-observed"
                        and frame["receipt_path"]
                        == (
                            "source-fetch-result.json"
                            if sdk_parse
                            else "public-source-acquisition.json"
                        ),
                        "source-worker-result-unavailable",
                    )
                    terminal = frame
                    break
            while process.poll() is None:
                require(
                    time.monotonic() < cutoff and streams.failure is None,
                    "source-worker-terminal-exit-deadline",
                )
                self._guard(callback, cutoff)
                time.sleep(min(0.01, max(0, cutoff - time.monotonic())))
            require(process.poll() == 0, "source-worker-terminal-exit-failed")
            self._guard(callback, cutoff)
            # Preserve and validate the original transport receipt; no looser
            # worker-specific promotion of partial/late-failure output exists.
            if sdk_parse:
                pins()
                require(
                    sha(read(output / terminal["receipt_path"], 256 * 1024))
                    == terminal["receipt_sha256"],
                    "saved-parser-original-receipt-pin-differs",
                )
            else:
                _acquisition(
                    output / terminal["receipt_path"],
                    terminal["receipt_sha256"],
                    request,
                    request["job_binding_sha256"],
                    request["runtime_sha256"],
                )
            require(time.monotonic() < cutoff, "source-worker-validation-deadline")
            self._guard(callback, cutoff)
            row.update(
                status="complete-observed",
                source_acquisition_observed=not sdk_parse,
                sdk_parse_observed=sdk_parse,
            )
        except BaseException as error:
            primary = error
            self._poisoned = True
            row.update(
                status="failed-or-unknown",
                failure_type=type(error).__name__,
                original_error_type=getattr(error, "original_error_type", None),
                source_acquisition_observed=False,
                sdk_parse_observed=False,
            )
            if process is None and hasattr(error, "cleanup"):
                row["cleanup"] = error.cleanup
                row.update(
                    process_started=error.cleanup.get("process_created", False),
                    pid=error.cleanup.get("pid"),
                    containment_admitted=error.cleanup.get(
                        "containment_admitted", False
                    ),
                )
        finally:
            if process is not None:
                row["cleanup"] = process.cleanup(end)
            if watchdog is not None:
                row["watchdog"] = watchdog.finish()
            try:
                if streams is not None:
                    row["streams"] = streams.join(end)
                    for name, raw in streams.prefix.items():
                        with (control / (name + ".prefix")).open("xb") as stream:
                            require(
                                stream.write(raw) == len(raw),
                                "source-worker-prefix-partial-write",
                            )
                            stream.flush()
                            os.fsync(stream.fileno())
                        require(
                            read(
                                control / (name + ".prefix"),
                                config["max_" + name + "_bytes"],
                                allow_empty=True,
                            )
                            == bytes(raw),
                            "source-worker-prefix-readback-differs",
                        )
            except BaseException as error:
                primary = primary or error
                self._poisoned = True
                row.update(
                    status="failed-or-unknown",
                    source_acquisition_observed=False,
                    sdk_parse_observed=False,
                    stream_save_failure=type(error).__name__,
                )
            clean = row.get("cleanup", {})
            valid_cleanup = (
                clean.get("containment_admitted") is True
                and clean.get("leader_reaped") is True
                and clean.get("tree_empty_observed") is True
                and not clean.get("errors")
                and row.get("streams", {}).get("threads_joined") is True
                and row.get("streams", {}).get("failure") is None
                and row.get("streams", {}).get("extra_frames") is False
                and row.get("streams", {}).get("observed_frames") == sequence + 1
                and row.get("watchdog", {}).get("thread_joined") is True
                and not row.get("watchdog", {}).get("errors")
            )
            if not valid_cleanup or time.monotonic() >= end:
                self._poisoned = True
                row.update(
                    status="failed-or-unknown",
                    source_acquisition_observed=False,
                    sdk_parse_observed=False,
                )
                primary = primary or TimeoutError(
                    "source-worker-cleanup-or-deadline-unobserved"
                )
            row["guard_thread_unfinished"] = (
                self._guard_thread is not None and self._guard_thread.is_alive()
            )
            row["within_original_deadline"] = time.monotonic() < end
            if primary is None:
                try:
                    self._guard(callback, end)
                    # The SDK's receipt is private output; admission to the
                    # caller happens only after cleanup/current-owner checks.
                    if sdk_parse:
                        from .saved_source_parser_runtime import verify_sdk

                        verify_sdk(parse_saved_manifest["runtime"])
                        self._guard(callback, end)
                except BaseException as error:
                    primary = error
                    self._poisoned = True
                    row.update(
                        status="failed-or-unknown",
                        source_acquisition_observed=False,
                        sdk_parse_observed=False,
                        failure_type=type(error).__name__,
                    )
            try:
                row["within_original_deadline"] = time.monotonic() < end
                row["guard_thread_unfinished"] = (
                    self._guard_thread is not None and self._guard_thread.is_alive()
                )
                event("final-observation", status=row["status"])
                saved = deepcopy(row)
                saved["observation_persisted"] = True
                _save(control / "outcome.json", saved)
                if time.monotonic() >= end and primary is None:
                    self._poisoned = True
                    row.update(
                        status="failed-or-unknown",
                        source_acquisition_observed=False,
                        sdk_parse_observed=False,
                        late_outcome=True,
                    )
                    # Keep the original late observation; append a distinct
                    # failure rather than overwrite or adopt it as success.
                    _save(control / "post-outcome-failure.json", row)
                    primary = TimeoutError("source-worker-outcome-late")
                row["observation_persisted"] = True
            except BaseException:
                self._poisoned = True
                row.update(
                    status="failed-or-unknown",
                    source_acquisition_observed=False,
                    sdk_parse_observed=False,
                )
                raise
        if primary is not None:
            raise primary
        return dict(
            receipt_path=terminal["receipt_path"],
            receipt_sha256=terminal["receipt_sha256"],
        )

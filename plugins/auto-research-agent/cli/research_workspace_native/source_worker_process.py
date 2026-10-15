"""Windows suspended child admission and kill-on-close ownership.

Only the trusted caller supplies executable, arguments and environment. A Job
contains admitted descendants without breakaway; membership is observed before
the initial thread resumes. Synchronous OS calls cannot be forcibly timed out.
Linux is deliberately unavailable; no existing Engine guard is changed here.
"""

import ctypes
from ctypes import wintypes as wt
import math
import os
import subprocess
import threading
import time


class WorkerProcessError(OSError):
    pass


def _api():
    if os.name != "nt":
        raise WorkerProcessError("source-worker-platform-unavailable")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer = ctypes.c_void_p

    class Security(ctypes.Structure):
        _fields_ = [("size", wt.DWORD), ("descriptor", pointer), ("inherit", wt.BOOL)]

    class Startup(ctypes.Structure):
        _fields_ = [
            ("cb", wt.DWORD),
            ("reserved", wt.LPWSTR),
            ("desktop", wt.LPWSTR),
            ("title", wt.LPWSTR),
            ("x", wt.DWORD),
            ("y", wt.DWORD),
            ("xsize", wt.DWORD),
            ("ysize", wt.DWORD),
            ("xchars", wt.DWORD),
            ("ychars", wt.DWORD),
            ("fill", wt.DWORD),
            ("flags", wt.DWORD),
            ("show", wt.WORD),
            ("reserved_size", wt.WORD),
            ("reserved_ptr", pointer),
            ("stdin", wt.HANDLE),
            ("stdout", wt.HANDLE),
            ("stderr", wt.HANDLE),
        ]

    class StartupEx(ctypes.Structure):
        _fields_ = [("startup", Startup), ("attributes", pointer)]

    class ProcessInfo(ctypes.Structure):
        _fields_ = [
            ("process", wt.HANDLE),
            ("thread", wt.HANDLE),
            ("pid", wt.DWORD),
            ("tid", wt.DWORD),
        ]

    class Limits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64),
            ("job_time", ctypes.c_int64),
            ("flags", wt.DWORD),
            ("minimum_ws", ctypes.c_size_t),
            ("maximum_ws", ctypes.c_size_t),
            ("active_limit", wt.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wt.DWORD),
            ("scheduling", wt.DWORD),
        ]

    class Counters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in (
                "read_ops",
                "write_ops",
                "other_ops",
                "read_bytes",
                "write_bytes",
                "other_bytes",
            )
        ]

    class Extended(ctypes.Structure):
        _fields_ = [
            ("basic", Limits),
            ("io", Counters),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process_memory", ctypes.c_size_t),
            ("peak_job_memory", ctypes.c_size_t),
        ]

    class Accounting(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_int64)
            for name in ("user", "kernel", "period_user", "period_kernel")
        ] + [
            ("faults", wt.DWORD),
            ("total", wt.DWORD),
            ("active", wt.DWORD),
            ("terminated", wt.DWORD),
        ]

    definitions = {
        "CreateJobObjectW": ([pointer, wt.LPCWSTR], wt.HANDLE),
        "SetInformationJobObject": (
            [wt.HANDLE, ctypes.c_int, pointer, wt.DWORD],
            wt.BOOL,
        ),
        "QueryInformationJobObject": (
            [wt.HANDLE, ctypes.c_int, pointer, wt.DWORD, pointer],
            wt.BOOL,
        ),
        "CreatePipe": ([pointer, pointer, pointer, wt.DWORD], wt.BOOL),
        "SetHandleInformation": ([wt.HANDLE, wt.DWORD, wt.DWORD], wt.BOOL),
        "InitializeProcThreadAttributeList": (
            [pointer, wt.DWORD, wt.DWORD, pointer],
            wt.BOOL,
        ),
        "UpdateProcThreadAttribute": (
            [
                pointer,
                wt.DWORD,
                ctypes.c_size_t,
                pointer,
                ctypes.c_size_t,
                pointer,
                pointer,
            ],
            wt.BOOL,
        ),
        "DeleteProcThreadAttributeList": ([pointer], None),
        "CreateProcessW": (
            [
                wt.LPCWSTR,
                wt.LPWSTR,
                pointer,
                pointer,
                wt.BOOL,
                wt.DWORD,
                pointer,
                wt.LPCWSTR,
                pointer,
                pointer,
            ],
            wt.BOOL,
        ),
        "AssignProcessToJobObject": ([wt.HANDLE, wt.HANDLE], wt.BOOL),
        "IsProcessInJob": ([wt.HANDLE, wt.HANDLE, pointer], wt.BOOL),
        "ResumeThread": ([wt.HANDLE], wt.DWORD),
        "GetExitCodeProcess": ([wt.HANDLE, pointer], wt.BOOL),
        "WaitForSingleObject": ([wt.HANDLE, wt.DWORD], wt.DWORD),
        "TerminateJobObject": ([wt.HANDLE, wt.UINT], wt.BOOL),
        "TerminateProcess": ([wt.HANDLE, wt.UINT], wt.BOOL),
        "CloseHandle": ([wt.HANDLE], wt.BOOL),
        "GetCurrentProcess": ([], wt.HANDLE),
        "DuplicateHandle": (
            [wt.HANDLE, wt.HANDLE, wt.HANDLE, pointer, wt.DWORD, wt.BOOL, wt.DWORD],
            wt.BOOL,
        ),
    }
    for name, (args, result) in definitions.items():
        fn = getattr(kernel, name)
        fn.argtypes, fn.restype = args, result
    return kernel, Security, StartupEx, ProcessInfo, Extended, Accounting


def _require(value):
    if not value:
        raise WorkerProcessError(
            "source-worker-os-call-failed", ctypes.get_last_error()
        )


class WindowsJobProcess:
    """One child initially suspended; no process adoption or automatic resume."""

    @classmethod
    def launch(cls, executable, argv, cwd, env, *, absolute_end, cleanup_end=None):
        if (
            not isinstance(executable, str)
            or not os.path.isabs(executable)
            or "\0" in executable
            or type(argv) not in (list, tuple)
            or any(type(a) is not str or "\0" in a for a in argv)
            or type(cwd) is not str
            or not os.path.isabs(cwd)
            or "\0" in cwd
            or type(env) is not dict
            or any(
                type(k) is not str
                or type(v) is not str
                or not k
                or "=" in k
                or "\0" in k + v
                for k, v in env.items()
            )
        ):
            raise WorkerProcessError("source-worker-launch-fields-invalid")
        if (
            type(absolute_end) not in (int, float)
            or not math.isfinite(absolute_end)
            or absolute_end <= time.monotonic()
        ):
            raise WorkerProcessError("source-worker-deadline-expired")
        cleanup_end = absolute_end if cleanup_end is None else cleanup_end
        if (
            type(cleanup_end) not in (int, float)
            or not math.isfinite(cleanup_end)
            or not absolute_end <= cleanup_end <= absolute_end + 2
        ):
            raise WorkerProcessError("source-worker-cleanup-reserve-invalid")
        kernel, Security, StartupEx, ProcessInfo, Extended, Accounting = _api()
        obj = cls()
        obj.kernel, obj.Accounting = kernel, Accounting
        obj.process = obj.thread = obj.job = None
        obj.stdin = obj.stdout = obj.stderr = None
        obj.pid, obj.contained, obj.resumed = None, False, False
        obj.absolute_end = absolute_end
        raw_handles, attributes, attributes_ready, primary = [], None, False, None
        try:
            obj.job = kernel.CreateJobObjectW(None, None)
            _require(obj.job)
            limits = Extended()
            limits.basic.flags = 0x2000 | 0x8  # Kill-on-close + four-process cap.
            limits.basic.active_limit = 4  # No breakaway flags are permitted.
            _require(
                kernel.SetInformationJobObject(
                    obj.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
                )
            )
            sa = Security(ctypes.sizeof(Security), None, True)
            children, parents = [], []
            for index in range(3):
                reader, writer = wt.HANDLE(), wt.HANDLE()
                _require(
                    kernel.CreatePipe(
                        ctypes.byref(reader), ctypes.byref(writer), ctypes.byref(sa), 0
                    )
                )
                raw_handles.extend((reader.value, writer.value))
                child, parent = (
                    (reader.value, writer.value)
                    if index == 0
                    else (writer.value, reader.value)
                )
                _require(kernel.SetHandleInformation(parent, 1, 0))
                children.append(child)
                parents.append(parent)
            size = ctypes.c_size_t()
            kernel.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
            _require(size.value)
            attributes = ctypes.create_string_buffer(size.value)
            _require(
                kernel.InitializeProcThreadAttributeList(
                    attributes, 1, 0, ctypes.byref(size)
                )
            )
            attributes_ready = True
            handles = (wt.HANDLE * 3)(*children)
            _require(
                kernel.UpdateProcThreadAttribute(
                    attributes, 0, 0x20002, handles, ctypes.sizeof(handles), None, None
                )
            )
            start = StartupEx()
            start.startup.cb, start.startup.flags = ctypes.sizeof(start), 0x100
            start.startup.stdin, start.startup.stdout, start.startup.stderr = children
            start.attributes = ctypes.cast(attributes, ctypes.c_void_p)
            command = ctypes.create_unicode_buffer(
                subprocess.list2cmdline([executable, *argv])
            )
            environment = ctypes.create_unicode_buffer(
                "\0".join(k + "=" + env[k] for k in sorted(env, key=str.upper)) + "\0\0"
            )
            info = ProcessInfo()
            if time.monotonic() >= absolute_end:
                raise WorkerProcessError("source-worker-deadline-expired")
            _require(
                kernel.CreateProcessW(
                    executable,
                    command,
                    None,
                    None,
                    True,
                    0x4 | 0x80000 | 0x8000000 | 0x400,
                    environment,
                    cwd,
                    ctypes.byref(start),
                    ctypes.byref(info),
                )
            )
            obj.process, obj.thread, obj.pid = info.process, info.thread, info.pid
            _require(kernel.AssignProcessToJobObject(obj.job, obj.process))
            member = wt.BOOL()
            _require(kernel.IsProcessInJob(obj.process, obj.job, ctypes.byref(member)))
            _require(member.value)
            obj.contained = True
            import msvcrt

            for index, handle in enumerate(parents):
                fd = msvcrt.open_osfhandle(
                    handle, os.O_BINARY | (os.O_WRONLY if index == 0 else os.O_RDONLY)
                )
                raw_handles.remove(handle)  # FileIO owns it from this point.
                try:
                    stream = os.fdopen(fd, "wb" if index == 0 else "rb", buffering=0)
                except BaseException:
                    os.close(fd)
                    raise
                setattr(obj, ("stdin", "stdout", "stderr")[index], stream)
            return obj
        except BaseException as error:
            primary = error
            report = obj.cleanup(cleanup_end)
            for stream in (obj.stdin, obj.stdout, obj.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except BaseException as close_error:
                        report["errors"].append(
                            "close-stream-" + type(close_error).__name__
                        )
            failure = WorkerProcessError("source-worker-launch-failed")
            failure.original_error_type = type(error).__name__
            failure.cleanup = report
            raise failure from error
        finally:
            if attributes_ready:
                kernel.DeleteProcThreadAttributeList(attributes)
            close_errors = []
            for handle in raw_handles:
                if not kernel.CloseHandle(handle):
                    close_errors.append("close-launch-pipe")
            if close_errors:
                report = obj.cleanup(cleanup_end)
                report["errors"].extend(close_errors)
                for stream in (obj.stdin, obj.stdout, obj.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except BaseException as close_error:
                            report["errors"].append(
                                "close-stream-" + type(close_error).__name__
                            )
                failure = WorkerProcessError("source-worker-launch-close-unobserved")
                failure.original_error_type = (
                    type(primary).__name__ if primary is not None else None
                )
                failure.cleanup = report
                raise failure from primary

    def resume(self):
        if (
            not self.contained
            or self.resumed
            or self.thread is None
            or time.monotonic() >= self.absolute_end
        ):
            raise WorkerProcessError("source-worker-resume-refused")
        _require(self.kernel.ResumeThread(self.thread) == 1)
        self.resumed = True
        _require(self.kernel.CloseHandle(self.thread))
        self.thread = None

    def poll(self):
        if self.process is None:
            return None
        wait = self.kernel.WaitForSingleObject(self.process, 0)
        if wait == 0x102:
            return None
        _require(wait == 0)
        code = wt.DWORD()
        _require(self.kernel.GetExitCodeProcess(self.process, ctypes.byref(code)))
        return int(code.value)

    def cleanup(self, absolute_end):
        """Terminate the owned Job even after leader exit; never extend the lease."""
        report = dict(
            containment_admitted=self.contained,
            resumed=self.resumed,
            pid=self.pid,
            process_created=self.pid is not None,
            leader_reaped=self.process is None,
            active_processes=None,
            tree_empty_observed=False,
            exit_code=None,
            errors=[],
            synchronous_os_calls_preemptible=False,
        )
        kernel = self.kernel
        if type(absolute_end) not in (int, float) or not math.isfinite(absolute_end):
            absolute_end = time.monotonic()
            report["errors"].append("invalid-cleanup-deadline")
        if self.process is not None:
            try:
                if self.contained:
                    _require(kernel.TerminateJobObject(self.job, 1))
                elif self.poll() is None:
                    _require(kernel.TerminateProcess(self.process, 1))
                wait = min(
                    0xFFFFFFFE, int(max(0, absolute_end - time.monotonic()) * 1000)
                )
                report["leader_reaped"] = (
                    kernel.WaitForSingleObject(self.process, wait) == 0
                )
                report["exit_code"] = self.poll()
                if self.contained:
                    while True:
                        counts = self.Accounting()
                        _require(
                            kernel.QueryInformationJobObject(
                                self.job,
                                1,
                                ctypes.byref(counts),
                                ctypes.sizeof(counts),
                                None,
                            )
                        )
                        report["active_processes"] = int(counts.active)
                        if counts.active == 0:
                            report["tree_empty_observed"] = True
                            break
                        if time.monotonic() >= absolute_end:
                            break
                        time.sleep(min(0.01, max(0, absolute_end - time.monotonic())))
            except BaseException as error:
                report["errors"].append(type(error).__name__)
        for name in ("thread", "job", "process"):
            handle = getattr(self, name)
            if handle is not None:
                if not kernel.CloseHandle(handle):
                    report["errors"].append("close-" + name)
                else:
                    setattr(self, name, None)
        # Readers close only after Job writers have exited; coordinator owns joins.
        report["within_original_deadline"] = time.monotonic() < absolute_end
        return report


class WindowsJobWatchdog:
    """Independent owned Job cutoff; no callback, file or SQLite lock waits."""

    def __init__(self, process, cutoff, end):
        if not process.contained or not time.monotonic() < cutoff < end:
            raise WorkerProcessError("source-worker-watchdog-admission-refused")
        self.kernel, self.Accounting = process.kernel, process.Accounting
        self.cutoff, self.end, self.stop = cutoff, end, threading.Event()
        self.job = wt.HANDLE()
        owner = self.kernel.GetCurrentProcess()
        _require(
            self.kernel.DuplicateHandle(
                owner, process.job, owner, ctypes.byref(self.job), 0, False, 2
            )
        )
        self.report = dict(
            armed=True,
            termination_invoked=False,
            tree_empty_observed=False,
            errors=[],
            thread_joined=False,
            synchronous_os_calls_preemptible=False,
        )
        self.thread = threading.Thread(target=self._run, daemon=True)
        try:
            self.thread.start()
        except BaseException:
            self.kernel.CloseHandle(self.job)
            raise

    def _run(self):
        try:
            if not self.stop.wait(max(0, self.cutoff - time.monotonic())):
                self.report["termination_invoked"] = True
                _require(self.kernel.TerminateJobObject(self.job, 1))
                while True:
                    info = self.Accounting()
                    _require(
                        self.kernel.QueryInformationJobObject(
                            self.job, 1, ctypes.byref(info), ctypes.sizeof(info), None
                        )
                    )
                    self.report["active_processes"] = int(info.active)
                    if info.active == 0:
                        self.report["tree_empty_observed"] = True
                        break
                    if time.monotonic() >= self.end:
                        break
                    time.sleep(min(0.01, max(0, self.end - time.monotonic())))
        except BaseException as error:
            self.report["errors"].append(type(error).__name__)
        finally:
            if not self.kernel.CloseHandle(self.job):
                self.report["errors"].append("close-watchdog-job")
            self.report["within_original_deadline"] = time.monotonic() < self.end

    def finish(self):
        self.stop.set()
        self.thread.join(max(0, self.end - time.monotonic()))
        self.report["thread_joined"] = not self.thread.is_alive()
        return dict(self.report)

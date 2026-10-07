"""Run one native subprocess with optional owned-tree deadline cleanup."""

import math
import os
import signal
import subprocess
import tempfile
import time


_IS_WINDOWS = os.name == "nt"
_CLEANUP_TIMEOUT_SECONDS = 5
_getpgid = getattr(os, "getpgid", None)
_killpg = getattr(os, "killpg", None)
_SIGKILL = getattr(signal, "SIGKILL", 9)


def validate_timeout_seconds(value):
    """Return a valid optional timeout without coercing its numeric type."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("timeout_seconds must be a finite positive number or None")
    try:
        valid = math.isfinite(value) and value > 0
    except (OverflowError, TypeError):
        valid = False
    if not valid:
        raise ValueError("timeout_seconds must be a finite positive number or None")
    return value


def _attach_cleanup_report(error, report):
    error.cleanup_report = report


def _remaining_timeout(deadline, command, timeout_seconds):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(command, timeout_seconds)
    return remaining


def _reap(process, report):
    try:
        process.communicate(timeout=_CLEANUP_TIMEOUT_SECONDS)
        report["reap_status"] = "complete"
        report["returncode"] = process.returncode
    except subprocess.TimeoutExpired as error:
        report["reap_status"] = "timeout"
        report["errors"].append(f"reap-timeout: {error}")
    except BaseException as error:
        report["reap_status"] = "error"
        report["errors"].append(f"reap-error: {type(error).__name__}: {error}")


def _cleanup_leader(process):
    report = {
        "platform": "windows" if _IS_WINDOWS else "posix",
        "target_pid": process.pid,
        "mechanism": "Popen.kill",
        "ownership_confirmed": False,
        "attempted": True,
        "errors": [],
    }
    try:
        process.kill()
        report["leader_kill_status"] = "sent"
    except ProcessLookupError:
        report["leader_kill_status"] = "already-exited"
    except BaseException as error:
        report["leader_kill_status"] = "error"
        report["errors"].append(f"leader-kill-error: {type(error).__name__}: {error}")
    _reap(process, report)
    return report


def _cleanup_posix(process, owned_pgid, ownership_confirmed):
    report = {
        "platform": "posix",
        "target_pid": process.pid,
        "mechanism": "killpg(SIGKILL)",
        "ownership_confirmed_at_spawn": ownership_confirmed,
        "owned_process_group": owned_pgid,
        "attempted": True,
        "errors": [],
    }
    if ownership_confirmed and process.returncode is not None:
        ownership_confirmed = False
        report["errors"].append("cleanup-identity-unknown: leader-already-reaped")
    elif ownership_confirmed:
        try:
            current_pgid = _getpgid(process.pid)
            ownership_confirmed = current_pgid == owned_pgid == process.pid
            if not ownership_confirmed:
                report["errors"].append(
                    f"cleanup-identity-mismatch: expected {owned_pgid}, got {current_pgid}"
                )
        except BaseException as error:
            ownership_confirmed = False
            report["errors"].append(
                f"cleanup-identity-error: {type(error).__name__}: {error}"
            )
    report["ownership_confirmed"] = ownership_confirmed
    if ownership_confirmed:
        try:
            _killpg(owned_pgid, _SIGKILL)
            report["tree_kill_status"] = "sent"
        except ProcessLookupError:
            report["tree_kill_status"] = "already-exited"
        except BaseException as error:
            report["tree_kill_status"] = "error"
            report["errors"].append(f"killpg-error: {type(error).__name__}: {error}")
    else:
        report["tree_kill_status"] = "not-attempted-unconfirmed-ownership"
    _reap(process, report)
    return report


def _cleanup_windows(process):
    report = {
        "platform": "windows",
        "target_pid": process.pid,
        "mechanism": "taskkill /PID /T /F",
        "ownership_confirmed": False,
        "attempted": True,
        "errors": [],
    }
    try:
        ownership_confirmed = process.poll() is None
    except BaseException as error:
        ownership_confirmed = False
        report["errors"].append(
            f"cleanup-identity-error: {type(error).__name__}: {error}"
        )
    report["ownership_confirmed"] = ownership_confirmed
    if not ownership_confirmed:
        report["tree_kill_status"] = "not-attempted-unconfirmed-ownership"
        _reap(process, report)
        return report
    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_CLEANUP_TIMEOUT_SECONDS,
        )
        report["taskkill_returncode"] = result.returncode
        report["taskkill_stdout"] = result.stdout
        report["taskkill_stderr"] = result.stderr
        report["tree_kill_status"] = "complete" if result.returncode == 0 else "error"
        if result.returncode != 0:
            report["errors"].append(
                f"taskkill-returncode-{result.returncode}: {result.stderr.strip()}"
            )
    except subprocess.TimeoutExpired as error:
        report["tree_kill_status"] = "timeout"
        report["errors"].append(f"taskkill-timeout: {error}")
    except BaseException as error:
        report["tree_kill_status"] = "error"
        report["errors"].append(f"taskkill-error: {type(error).__name__}: {error}")
    _reap(process, report)
    return report


def run_bound_process(
    command,
    *,
    input,
    env,
    cwd,
    stdout,
    stderr,
    timeout_seconds=None,
) -> int:
    """Run one process and clean only its owned process tree on failure.

    POSIX ownership is confirmed immediately after ``Popen`` and checked again
    before cleanup while the leader identity remains unreaped. Cleanup refuses a
    group whose identity can no longer be confirmed. Windows cleanup likewise
    refuses a known-exited PID before addressing the spawned PID and descendants
    through ``taskkill /PID /T /F``. Callers must retain exclusive ownership of
    the ``Popen`` object; concurrent waits cannot be made race-free here.
    """

    timeout_seconds = validate_timeout_seconds(timeout_seconds)
    popen_options = {
        "env": env,
        "cwd": cwd,
        "stdout": stdout,
        "stderr": stderr,
    }
    bounded = timeout_seconds is not None
    deadline = time.monotonic() + timeout_seconds if bounded else None
    prompt_file = None
    if bounded:
        prompt_file = tempfile.TemporaryFile(mode="w+b")
        try:
            if input is not None:
                prompt_file.write(input)
            prompt_file.flush()
            prompt_file.seek(0)
            _remaining_timeout(deadline, command, timeout_seconds)
        except BaseException:
            prompt_file.close()
            raise
        popen_options["stdin"] = prompt_file
        if _IS_WINDOWS:
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_options["start_new_session"] = True
    else:
        popen_options["stdin"] = subprocess.PIPE
    try:
        process = subprocess.Popen(command, **popen_options)
    except BaseException:
        if prompt_file is not None:
            prompt_file.close()
        raise

    owned_pgid = None
    ownership_confirmed = _IS_WINDOWS
    try:
        if bounded and not _IS_WINDOWS:
            owned_pgid = _getpgid(process.pid)
            ownership_confirmed = owned_pgid == process.pid
            if not ownership_confirmed:
                raise RuntimeError(
                    "spawned process did not enter its owned process group"
                )
        if not bounded:
            process.communicate(input=input)
        else:
            remaining = _remaining_timeout(deadline, command, timeout_seconds)
            process.communicate(timeout=remaining)
        return process.returncode
    except BaseException as error:
        try:
            if not bounded:
                report = _cleanup_leader(process)
            elif _IS_WINDOWS:
                report = _cleanup_windows(process)
            else:
                report = _cleanup_posix(process, owned_pgid, ownership_confirmed)
        except BaseException as cleanup_error:
            report = {
                "platform": "windows" if _IS_WINDOWS else "posix",
                "attempted": True,
                "errors": [
                    "cleanup-internal-error: "
                    f"{type(cleanup_error).__name__}: {cleanup_error}"
                ],
            }
        try:
            _attach_cleanup_report(error, report)
        except BaseException:
            pass
        raise
    finally:
        if prompt_file is not None:
            prompt_file.close()

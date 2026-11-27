"""Explicit offline recovery of an identified Windows coverage writer."""

import argparse
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile

from stage1_deliverable.common import private_output, reject_links, safe_path
from stage1_ledger.journal import LedgerError, canonical, decode, digest, utc_now


LOCK = ".writer-lock"
MAX_RECORD_BYTES = 8192
HEX_SHA256 = re.compile(r"[0-9a-f]{64}")
HEX_GENERATION = re.compile(r"[0-9a-f]{32}")
PROOF_KIND = "Stage1CoverageWriterLockRecovery"
EXIT_EVIDENCE = {"identified-owner-exited", "identified-owner-pid-absent"}


def _need(condition, error):
    if not condition:
        raise LedgerError(error)


@lru_cache(maxsize=1)
def _windows():
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "GetCurrentProcess": ([], wintypes.HANDLE),
        "GetDriveTypeW": ([wintypes.LPCWSTR], wintypes.UINT),
        "GetVolumeInformationW": (
            [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
            + [ctypes.POINTER(wintypes.DWORD)] * 3
            + [wintypes.LPWSTR, wintypes.DWORD],
            wintypes.BOOL,
        ),
        "CreateFileW": (
            [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ],
            wintypes.HANDLE,
        ),
        "OpenProcess": (
            [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD],
            wintypes.HANDLE,
        ),
        "GetProcessTimes": (
            [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4,
            wintypes.BOOL,
        ),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    return kernel


@lru_cache(maxsize=1)
def _host_identity():
    import ctypes
    from ctypes import wintypes
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Cryptography",
        access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
    ) as key:
        machine, _ = winreg.QueryValueEx(key, "MachineGuid")
    _need(
        isinstance(machine, str) and bool(machine), "writer-lock-machine-unverifiable"
    )

    # Windows SystemBootEnvironmentInformation begins with the boot GUID.
    query = ctypes.WinDLL("ntdll").NtQuerySystemInformation
    query.argtypes = [
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
        ctypes.POINTER(wintypes.ULONG),
    ]
    query.restype = wintypes.LONG
    buffer = ctypes.create_string_buffer(64)
    size = wintypes.ULONG()
    status = query(90, buffer, len(buffer), ctypes.byref(size))
    boot = buffer.raw[:16]
    _need(
        status == 0 and 16 <= size.value <= len(buffer) and any(boot),
        "writer-lock-boot-unverifiable",
    )
    return digest(machine.casefold().encode("utf-8")), digest(boot)


def _creation_time(handle):
    import ctypes
    from ctypes import wintypes

    times = [wintypes.FILETIME() for _ in range(4)]
    if not _windows().GetProcessTimes(
        handle, *(ctypes.byref(value) for value in times)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime


def _run_identity(root):
    import ctypes

    reject_links(root)
    # Drive type 3 is a local fixed drive. Drive aliases to remote shares,
    # mounted/reparse descendants and unsupported filesystem identities refuse.
    _need(
        root.is_dir() and _windows().GetDriveTypeW(root.anchor) == 3,
        "writer-lock-local-fixed-volume-required",
    )
    filesystem = ctypes.create_unicode_buffer(32)
    _need(
        _windows().GetVolumeInformationW(
            root.anchor, None, 0, None, None, None, filesystem, len(filesystem)
        )
        and filesystem.value == "NTFS",
        "writer-lock-ntfs-required",
    )
    info = root.stat()
    _need(info.st_dev > 0 and info.st_ino > 0, "writer-lock-run-identity-unverifiable")
    machine, boot = _host_identity()
    return {
        "machine_sha256": machine,
        "boot_sha256": boot,
        "volume": info.st_dev,
        "directory_file_id": info.st_ino,
        "physical_path_sha256": digest(os.path.normcase(str(root)).encode("utf-8")),
        "manifest_sha256": digest(
            _read_file(safe_path(root, "run_manifest.json"), 262144)
        ),
    }


def owner_record(root, clock):
    """If the recoverable lock cannot be stamped, leave legacy writing available."""
    if os.name != "nt":
        return None
    try:
        identity = _run_identity(root)
        creation = _creation_time(_windows().GetCurrentProcess())
        if creation <= 0:
            return None
    except (OSError, ValueError, AttributeError):
        return None
    return {
        "kind": "Stage1CoverageWriterLock",
        "schema_version": "1.0.0",
        "generation": secrets.token_hex(16),
        "pid": os.getpid(),
        "created_at": clock(),
        "owner_creation_filetime": creation,
        "run_identity": identity,
    }


@contextmanager
def hold_writer_lock(root, record):
    lock = safe_path(root, LOCK)
    try:
        stream = lock.open("xb")
    except FileExistsError as error:
        raise LedgerError(
            "writer-locked: inspect the owner with offline lock recovery"
        ) from error
    try:
        with stream:
            stream.write(canonical(record))
            stream.flush()
            os.fsync(stream.fileno())
            yield
    finally:
        lock.unlink()


def _read_file(path, limit=MAX_RECORD_BYTES):
    reject_links(path)
    info = path.stat()
    _need(
        stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
        "writer-lock-regular-single-link-file-required",
    )
    with path.open("rb") as stream:
        contents = stream.read(limit + 1)
    _need(0 < len(contents) <= limit, "writer-lock-record-size-invalid")
    return contents


@contextmanager
def _open_read_lock(path):
    import ctypes
    import msvcrt

    reject_links(path)
    expected = path.lstat()
    kernel = _windows()
    # This maintenance reader must permit the archival rename. The writer
    # still holds its separate exclusive-delete handle for the entire write.
    handle = kernel.CreateFileW(
        str(path),
        0x80000000,  # GENERIC_READ
        1 | 2 | 4,  # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
        None,
        3,  # OPEN_EXISTING
        0x00200000,  # FILE_FLAG_OPEN_REPARSE_POINT
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except (OSError, ValueError):
        kernel.CloseHandle(handle)
        raise
    try:
        opened = os.fstat(descriptor)
        _need(
            stat.S_ISREG(opened.st_mode)
            and opened.st_nlink == 1
            and not (getattr(opened, "st_file_attributes", 0) & 0x400)
            and opened.st_ino > 0
            and (opened.st_dev, opened.st_ino) == (expected.st_dev, expected.st_ino),
            "writer-lock-opened-file-identity-differs",
        )
        with open(descriptor, "rb", closefd=False) as stream:
            yield stream
    finally:
        os.close(descriptor)


def _read_lock(path, *, access=None):
    with _open_read_lock(path) as stream:
        if access is not None:
            _verify_audit_file(access, fd=stream.fileno())
        contents = stream.read(MAX_RECORD_BYTES + 1)
    _need(0 < len(contents) <= MAX_RECORD_BYTES, "writer-lock-record-size-invalid")
    return contents


def _decoded_owner(contents, identity):
    record = decode(contents, LOCK)
    _need(
        type(record) is dict
        and set(record)
        == {
            "kind",
            "schema_version",
            "generation",
            "pid",
            "created_at",
            "owner_creation_filetime",
            "run_identity",
        }
        and record["kind"] == "Stage1CoverageWriterLock"
        and record["schema_version"] == "1.0.0"
        and type(record["generation"]) is str
        and HEX_GENERATION.fullmatch(record["generation"]) is not None
        and type(record["pid"]) is int
        and 0 < record["pid"] <= 0xFFFFFFFF
        and type(record["owner_creation_filetime"]) is int
        and 0 < record["owner_creation_filetime"] < 2**64
        and type(record["created_at"]) is str
        and record["created_at"].endswith("Z")
        and contents == canonical(record),
        "writer-lock-owner-unverifiable",
    )
    datetime.fromisoformat(record["created_at"].replace("Z", "+00:00"))
    _need(record["run_identity"] == identity, "writer-lock-run-or-boot-differs")
    return record


def _owner_exited(record):
    import ctypes

    kernel = _windows()
    # PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE; no termination rights.
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, record["pid"])
    if not handle:
        # Only the kernel's nonexistent-PID response is usable, and only after
        # the lock itself was proved to identify this machine, boot and run.
        if ctypes.get_last_error() == 87:
            return "identified-owner-pid-absent"
        raise LedgerError("writer-lock-owner-liveness-unverifiable")
    try:
        _need(
            _creation_time(handle) == record["owner_creation_filetime"],
            "writer-lock-owner-pid-reused",
        )
        status = kernel.WaitForSingleObject(handle, 0)
        if status == 258:
            raise LedgerError("writer-lock-owner-active")
        _need(status == 0, "writer-lock-owner-liveness-unverifiable")
        return "identified-owner-exited"
    finally:
        kernel.CloseHandle(handle)


@lru_cache(maxsize=1)
def _windows_security():
    import ctypes
    from ctypes import wintypes

    api = ctypes.WinDLL("advapi32", use_last_error=True)
    pointer = ctypes.c_void_p
    out_pointer = ctypes.POINTER(pointer)
    common = [wintypes.DWORD, wintypes.DWORD] + [out_pointer] * 5
    api.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, *common]
    api.GetSecurityInfo.argtypes = [wintypes.HANDLE, *common]
    api.GetNamedSecurityInfoW.restype = api.GetSecurityInfo.restype = wintypes.DWORD
    convert = api.ConvertSecurityDescriptorToStringSecurityDescriptorW
    convert.argtypes = [
        pointer,
        wintypes.DWORD,
        wintypes.DWORD,
        out_pointer,
        ctypes.POINTER(wintypes.ULONG),
    ]
    convert.restype = wintypes.BOOL
    free = ctypes.WinDLL("kernel32").LocalFree
    free.argtypes = [pointer]
    free.restype = pointer
    return api, convert, free


def _acl_descriptor(path=None, *, fd=None):
    """Read the owner, group, and DACL without changing an ACL."""
    import ctypes

    api, convert, free = _windows_security()
    if fd is None:
        reject_links(path)
        source, object_id = api.GetNamedSecurityInfoW, str(path)
    else:
        import msvcrt

        source, object_id = api.GetSecurityInfo, msvcrt.get_osfhandle(fd)
    file_object = 1
    owner_group_dacl = 0x7
    descriptor = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    sddl = ctypes.c_void_p()
    try:
        status = source(
            object_id,
            file_object,
            owner_group_dacl,
            None,
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        _need(
            status == 0 and dacl.value is not None, "writer-lock-audit-acl-unverifiable"
        )
        _need(
            convert(descriptor, 1, owner_group_dacl, ctypes.byref(sddl), None),
            "writer-lock-audit-acl-unverifiable",
        )
        return ctypes.wstring_at(sddl)
    finally:
        if sddl:
            free(sddl)
        if descriptor:
            free(descriptor)


def _effective_acl(descriptor):
    """Compare ordered, ordinary access ACEs across directories and files."""
    parts = re.fullmatch(r"(O:[^:]+G:[^:]+)D:(?:P|AR|AI)*((?:\([^()]*\))*)", descriptor)
    _need(parts is not None, "writer-lock-audit-acl-unverifiable")
    owner_group, aces = parts.groups()
    effective = []
    for ace in re.findall(r"\(([^()]*)\)", aces):
        fields = re.fullmatch(
            r"(A|D);((?:OI|CI|NP|IO|ID)*);([A-Z0-9a-fx]+);;;([A-Z0-9-]+)",
            ace,
            re.IGNORECASE,
        )
        _need(fields is not None, "writer-lock-audit-acl-unverifiable")
        kind, flags, rights, sid = fields.groups()
        if "IO" not in re.findall(r"..", flags):
            # Windows expands generic rights for effective NTFS ACEs. Do not
            # assume equivalent access for a descriptor retaining generic bits.
            _need(
                not re.search(r"G[ARWX]", rights), "writer-lock-audit-acl-unverifiable"
            )
            effective.append((kind, rights, sid))
    return owner_group, tuple(effective)


def _verify_audit_file(access, *, fd):
    actual = _effective_acl(_acl_descriptor(fd=fd))
    _need(actual == access, "writer-lock-audit-acl-differs")


def _verify_audit_directory(audit, root):
    _need(
        _acl_descriptor(audit) == _acl_descriptor(root), "writer-lock-audit-acl-differs"
    )


def _verify_audit_owner(audit, root, identity, access):
    reject_links(audit)
    _need(
        audit.is_dir() and audit.stat().st_dev == identity["volume"],
        "writer-lock-audit-volume-differs",
    )
    _verify_audit_directory(audit, root)
    marker = safe_path(audit, "owner.json")
    try:
        actual = _read_lock(marker, access=access)
    except FileNotFoundError:
        raise LedgerError("writer-lock-audit-owner-differs") from None
    _need(actual == _audit_owner(identity), "writer-lock-audit-owner-differs")


def _audit_owner(identity):
    return canonical(
        {
            "kind": "Stage1CoverageWriterLockAudit",
            "schema_version": "1.0.0",
            "run_identity": {
                field: identity[field]
                for field in (
                    "machine_sha256",
                    "volume",
                    "directory_file_id",
                    "physical_path_sha256",
                )
            },
        }
    )


def _ensure_audit(audit, root, identity, access):
    if not audit.exists():
        # Publish a fully identified directory in one Windows no-replace step.
        # A conflicting name is never adopted or written into implicitly.
        with tempfile.TemporaryDirectory(
            prefix=".writer-lock-audit-", dir=audit.parent
        ) as staging:
            _verify_audit_directory(Path(staging), root)
            with (Path(staging) / "owner.json").open("xb") as stream:
                _verify_audit_file(access, fd=stream.fileno())
                stream.write(_audit_owner(identity))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.rename(staging, audit)
            except FileExistsError:
                pass
    _verify_audit_owner(audit, root, identity, access)


def _publish_proof(path, proof, access):
    # Fsync before publishing. A crash before publication leaves at most an
    # unused temporary audit file, outside the ledger and distinct from a lock.
    descriptor, temporary = tempfile.mkstemp(prefix=".proof-", dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            _verify_audit_file(access, fd=stream.fileno())
            stream.write(canonical(proof))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.rename(temporary, path)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)


def recover_writer_lock(run, expected_sha256):
    """Prove the prior owner's exit and atomically preserve this exact generation."""
    _need(os.name == "nt", "writer-lock-recovery-windows-only")
    _need(
        isinstance(expected_sha256, str) and HEX_SHA256.fullmatch(expected_sha256),
        "writer-lock-expected-sha256-required",
    )
    root = private_output(Path(run)).resolve(strict=True)
    identity = _run_identity(root)
    from stage1_ledger.contracts import check_manifest

    check_manifest(
        decode(_read_file(safe_path(root, "run_manifest.json"), 262144), "manifest")
    )
    lock = safe_path(root, LOCK)
    audit = safe_path(root.parent, f".{root.name}.writer-lock-recovery")
    retired = safe_path(audit, expected_sha256 + ".lock")
    receipt = safe_path(audit, expected_sha256 + ".json")

    access = _effective_acl(_acl_descriptor(root))

    def proof_basis(record):
        return {
            "kind": PROOF_KIND,
            "schema_version": "1.0.0",
            "lock_sha256": expected_sha256,
            "owner": record,
        }

    def verified_proof(record):
        raw = _read_lock(receipt, access=access)
        proof = decode(raw, "writer-lock recovery receipt")
        basis = proof_basis(record)
        _need(
            type(proof) is dict
            and set(proof) == set(basis) | {"owner_exit_evidence", "verified_at"}
            and all(proof[key] == value for key, value in basis.items())
            and proof["owner_exit_evidence"] in EXIT_EVIDENCE
            and type(proof["verified_at"]) is str
            and proof["verified_at"].endswith("Z")
            and raw == canonical(proof),
            "writer-lock-recovery-receipt-differs",
        )
        return proof

    def archived(status):
        if not audit.exists():
            return None
        _verify_audit_owner(audit, root, identity, access)
        try:
            raw = _read_lock(retired, access=access)
        except FileNotFoundError:
            return None
        _need(digest(raw) == expected_sha256, "writer-lock-recovery-archive-differs")
        proof = verified_proof(_decoded_owner(raw, identity))
        return {
            "status": status,
            "lock_sha256": expected_sha256,
            "owner_exit_evidence": proof["owner_exit_evidence"],
            "archived_lock": str(retired),
            "receipt": str(receipt),
            "automatic_retries": 0,
        }

    previous = archived("already-recovered")
    if previous is not None:
        return previous
    try:
        raw = _read_lock(lock, access=access)
    except (OSError, LedgerError) as error:
        previous = archived("already-recovered")
        if previous is not None:
            return previous
        if isinstance(error, FileNotFoundError):
            raise LedgerError("writer-lock-missing") from None
        raise
    if digest(raw) != expected_sha256:
        previous = archived("already-recovered")
        if previous is not None:
            return previous
        raise LedgerError("writer-lock-sha256-differs")
    record = _decoded_owner(raw, identity)
    evidence = _owner_exited(record)
    _ensure_audit(audit, root, identity, access)
    if not receipt.exists():
        _publish_proof(
            receipt,
            {
                **proof_basis(record),
                "owner_exit_evidence": evidence,
                "verified_at": utc_now(),
            },
            access,
        )
    verified_proof(record)
    _owner_exited(record)
    # On Windows rename is an atomic no-replace operation. Every recovery of
    # this SHA targets the same archive, so a delayed contender cannot move a
    # subsequent generation even if it inspected the old lock before a winner.
    try:
        _verify_audit_directory(audit, root)
        _need(
            _effective_acl(_acl_descriptor(root)) == access,
            "writer-lock-audit-acl-differs",
        )
        _need(_read_lock(lock, access=access) == raw, "writer-lock-sha256-differs")
        os.rename(lock, retired)
    except (OSError, LedgerError):
        previous = archived("already-recovered")
        if previous is not None:
            return previous
        raise
    result = archived("recovered")
    _need(result is not None, "writer-lock-recovery-archive-unobserved")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--expect-lock-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = recover_writer_lock(args.run, args.expect_lock_sha256)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        sys.stdout.buffer.write(
            canonical({"status": "refused", "error": str(error)}) + b"\n"
        )
        return 1
    sys.stdout.buffer.write(canonical(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

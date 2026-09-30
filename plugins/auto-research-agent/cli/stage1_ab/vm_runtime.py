"""Guest-only immutable static ELF execution boundary; never execute a resolver."""

import errno
import os
from pathlib import Path
import stat
import struct

from .vm_common import require
from . import runner


def static_elf(data):
    """Admit the supported ELF64 little-endian x86-64 static/PIE layout only."""
    require(
        len(data) >= 64 and data[:7] == b"\x7fELF\x02\x01\x01",
        "guest runtime must be standalone ELF64",
    )
    kind, machine, version = struct.unpack_from("<HHI", data, 16)
    offset = struct.unpack_from("<Q", data, 32)[0]
    header_size, entry_size, count = struct.unpack_from("<HHH", data, 52)
    require(
        kind in {2, 3}
        and machine == 62
        and version == 1
        and header_size == 64
        and entry_size == 56
        and 0 < count < 65535
        and offset >= 64
        and offset + count * entry_size <= len(data),
        "unsupported guest ELF header",
    )
    dynamic = []
    loads = 0
    for index in range(count):
        tag, flags, start, _, _, size, memory, _ = struct.unpack_from(
            "<IIQQQQQQ", data, offset + index * entry_size
        )
        require(
            start + size <= len(data) and (tag != 1 or size <= memory),
            "invalid guest ELF segment",
        )
        require(tag != 3, "guest ELF interpreter is unsupported")
        loads += int(tag == 1)
        if tag == 2:
            require(size >= 16 and size % 16 == 0, "invalid guest ELF dynamic table")
            terminated = False
            for position in range(start, start + size, 16):
                dependency, value = struct.unpack_from("<qQ", data, position)
                if dependency == 0:
                    terminated = True
                    break
                require(
                    dependency
                    not in {1, 15, 29, 0x7FFFFFFD, 0x7FFFFFFF, 0x6FFFFEFB, 0x6FFFFEFC},
                    "guest ELF indirect runtime dependency is unsupported",
                )
                dynamic.append([dependency, value])
            require(terminated, "unterminated guest ELF dynamic table")
    require(loads > 0, "guest ELF has no load segment")
    return {
        "format": "static-elf64-x86_64-v1",
        "type": kind,
        "program_headers": count,
        "dynamic": dynamic,
    }


def file_capabilities(path):
    try:
        return os.getxattr(path, "security.capability", follow_symlinks=False)
    except OSError as exc:
        if exc.errno in {errno.ENODATA, errno.ENOTSUP}:
            return b""
        raise


def inventory(codex):
    """Root owns every lexical component, preventing subject replacement races.

    Root/kernel/mount administration remain trusted. Links, script/package
    launchers and loader-selected dependencies are deliberately unsupported.
    """
    path = Path(codex)
    require(
        path.is_absolute() and ".." not in path.parts,
        "guest runtime requires absolute lexical path",
    )
    nodes = []
    for component in reversed((path, *path.parents)):
        info = component.lstat()
        leaf = component == path
        require(
            info.st_uid == 0
            and info.st_mode & (0o6022 if leaf else 0o022) == 0
            and (stat.S_ISREG(info.st_mode) if leaf else stat.S_ISDIR(info.st_mode)),
            "guest runtime or ancestor is linked, writable or not root-owned",
        )
        require(
            info.st_mode & 0o111 == 0o111,
            "guest runtime or ancestor is not traversable/executable",
        )
        nodes.append(
            {
                "path": str(component),
                "uid": info.st_uid,
                "gid": info.st_gid,
                "mode": info.st_mode,
                "device": info.st_dev,
                "inode": info.st_ino,
            }
        )
    require(path.resolve() == path, "guest runtime path resolution differs")
    require(
        not file_capabilities(path), "privileged guest ELF capabilities are unsupported"
    )
    data = path.read_bytes()
    return {
        "kind": "Stage1ProtectedRuntime.v1",
        "executable": str(path),
        "nodes": nodes,
        "sha256": runner.sha(data),
        "size": len(data),
        "file_capabilities": "none",
        "elf": static_elf(data),
    }


def before_exec(codex, expected, env):
    """Compare to accepted signed inventory, including exact executable path."""
    require(
        isinstance(expected, dict)
        and expected.get("kind") == "Stage1ProtectedRuntime.v1",
        "missing accepted protected guest runtime",
    )
    require(
        str(codex) == expected["executable"] and inventory(codex) == expected,
        "protected guest runtime changed after admission",
    )
    # Even a static executable may spawn helpers later. Do not propagate loader
    # overrides from the operator environment to that subprocess tree.
    for name in tuple(env):
        if name.startswith("LD_") or name in {"GLIBC_TUNABLES", "GCONV_PATH"}:
            env.pop(name)

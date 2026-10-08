"""Opt-in physical role scope around the unchanged standalone native command.

The trusted recorder stays outside this scope. Native processes receive the
frozen image and their role files, never recorder code or peer data. Selected
actions receive only their trace child and a single final-output file.
"""

import hashlib
import json
import os
from pathlib import Path
import stat
import sys

from .trace_seal_io import SealDirectory


class NativeNamespaceError(ValueError):
    """An opt-in namespace cannot be reconstructed safely."""


SCOPE_FILE = "native-namespace.json"
_FIELDS = {
    "kind",
    "schema_version",
    "rootfs",
    "rootfs_receipt_path",
    "rootfs_receipt_sha256",
    "rootfs_tree_sha256",
    "codex",
    "codex_sha256",
    "bwrap",
    "bwrap_sha256",
    "dns_path",
    "dns_sha256",
    "home",
    "workspace",
    "telemetry",
    "capture_root",
}


def _read(path, expected=None):
    path = Path(path)
    with SealDirectory(path.parent) as directory, directory.reader(path.name) as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > 128 * 1024 * 1024:
            raise NativeNamespaceError("namespace artifact is too large")
        raw = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino, before.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ) or len(raw) != before.st_size:
            raise NativeNamespaceError("namespace artifact changed")
    digest = hashlib.sha256(raw).hexdigest()
    if expected is not None and digest != expected:
        raise NativeNamespaceError("namespace artifact receipt differs")
    return raw, digest


def _file_sha(path, expected=None):
    """Hash large frozen image files without loading them into memory."""
    path = Path(path)
    with SealDirectory(path.parent) as directory:
        if os.name == "posix":
            descriptor = os.open(
                path.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory.target,
            )
            stream = os.fdopen(descriptor, "rb")
        else:
            stream = directory.reader(path.name)
        with stream:
            return _stream_sha(stream, expected)


def _stream_sha(stream, expected):
    digest = hashlib.sha256()
    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
        raise NativeNamespaceError("namespace image artifact is not regular")
    before = os.fstat(stream.fileno())
    read = 0
    while raw := stream.read(1024 * 1024):
        read += len(raw)
        if read > before.st_size:
            raise NativeNamespaceError("namespace image artifact grew")
        digest.update(raw)
    after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mode", "st_uid", "st_gid")
    if read != before.st_size or any(
        getattr(before, f) != getattr(after, f) for f in fields
    ):
        raise NativeNamespaceError("namespace image artifact changed")
    value = digest.hexdigest()
    if expected is not None and value != expected:
        raise NativeNamespaceError("namespace image artifact receipt differs")
    return value


def _directory(value):
    path = Path(value)
    if not path.is_absolute() or str(path.resolve()) != value:
        raise NativeNamespaceError("namespace directory must be canonical")
    if value in {"/", "/home", "/root", "/mnt", "/tmp", str(Path.home().resolve())}:
        raise NativeNamespaceError("namespace mount cannot expose a broad home")
    if path.parts[1] not in {"home", "root", "mnt", "tmp"}:
        raise NativeNamespaceError("namespace role path needs a private mount base")
    with SealDirectory(path):
        pass
    return path


def image_tree_sha(root):
    """Bind image bytes, link targets and executable/ownership metadata."""
    root = Path(root)
    root_info = root.lstat()
    entries = [
        [
            ".",
            stat.S_IMODE(root_info.st_mode),
            root_info.st_uid,
            root_info.st_gid,
            "directory",
        ]
    ]
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        info = path.lstat()
        row = [
            path.relative_to(root).as_posix(),
            stat.S_IMODE(info.st_mode),
            info.st_uid,
            info.st_gid,
        ]
        if stat.S_ISREG(info.st_mode):
            digest = _file_sha(path)
            if path.lstat() != info:
                raise NativeNamespaceError("namespace image entry changed")
            row.extend(("file", info.st_size, digest))
        elif stat.S_ISDIR(info.st_mode):
            row.append("directory")
        elif stat.S_ISLNK(info.st_mode):
            row.extend(("symlink", os.readlink(path)))
        else:
            raise NativeNamespaceError("namespace image has a special file")
        entries.append(row)
    return hashlib.sha256(
        json.dumps(entries, separators=(",", ":")).encode()
    ).hexdigest()


def _native_alias(scope):
    """Only the standalone vendor subtree may appear below the image alias."""
    rootfs = Path(scope["rootfs"])
    codex = Path(scope["codex"])
    runtime = codex.parent.parent
    if (
        not runtime.is_relative_to(rootfs)
        or codex.parent.name != "bin"
        or runtime.parent.name != "vendor"
        or Path(scope["bwrap"]) != runtime / "codex-resources" / "bwrap"
        or len(runtime.relative_to(rootfs).parts) < 3
    ):
        raise NativeNamespaceError("namespace needs the standalone vendor layout")
    return str(runtime)


def _validate(scope, *, codex, home, workspace):
    if (
        not isinstance(scope, dict)
        or set(scope) != _FIELDS
        or (scope["kind"], scope["schema_version"])
        != ("Stage2NativeNamespaceScope", "1.0.0")
    ):
        raise NativeNamespaceError("namespace scope schema differs")
    if any(
        not isinstance(value, str) or not value or "\x00" in value
        for value in scope.values()
    ):
        raise NativeNamespaceError("namespace fields must be nonempty strings")
    for field in _FIELDS:
        if field.endswith("sha256") and (
            len(scope[field]) != 64
            or any(c not in "0123456789abcdef" for c in scope[field])
        ):
            raise NativeNamespaceError("namespace SHA-256 is invalid")
    for field, expected in (("codex", codex), ("home", home), ("workspace", workspace)):
        if expected is None and field == "workspace":
            continue
        if scope[field] != str(Path(expected).resolve()):
            raise NativeNamespaceError(f"namespace {field} differs from execution")
    roots = [
        _directory(scope[key])
        for key in ("home", "workspace", "telemetry", "capture_root", "rootfs")
    ]
    for index, left in enumerate(roots):
        if any(
            left == right or left in right.parents or right in left.parents
            for right in roots[index + 1 :]
        ):
            raise NativeNamespaceError("namespace role directories overlap")
    rootfs = roots[-1]
    _native_alias(scope)
    if not Path(scope["codex"]).is_relative_to(rootfs) or not Path(
        scope["bwrap"]
    ).is_relative_to(rootfs):
        raise NativeNamespaceError(
            "namespace executables must belong to the frozen image"
        )
    for name in ("codex", "bwrap", "dns"):
        path = scope["dns_path"] if name == "dns" else scope[name]
        _file_sha(path, scope[name + "_sha256"])
        if name != "dns" and not os.access(path, os.X_OK):
            raise NativeNamespaceError("namespace executable is not executable")
    for name in ("dns_path", "rootfs_receipt_path"):
        path = Path(scope[name])
        if (
            not path.is_absolute()
            or str(path.resolve()) != scope[name]
            or any(path == root or root in path.parents for root in roots[:4])
        ):
            raise NativeNamespaceError("namespace frozen file is inside a mutable role")
    raw, _ = _read(scope["rootfs_receipt_path"], scope["rootfs_receipt_sha256"])
    receipt = json.loads(raw)
    if receipt != {
        "kind": "Stage2RootfsInventoryReceipt",
        "schema_version": "1.0.0",
        "rootfs": scope["rootfs"],
        "tree_sha256": scope["rootfs_tree_sha256"],
    }:
        raise NativeNamespaceError("namespace image receipt differs")
    if image_tree_sha(rootfs) != scope["rootfs_tree_sha256"]:
        raise NativeNamespaceError("namespace image bytes changed")


def bind_namespace(codex, home, workspace=None, *, trace_root=None):
    """Bind opt-in host transport bytes; absence preserves legacy execution."""
    path = Path(home).resolve() / SCOPE_FILE
    if not os.path.lexists(path):
        if trace_root is not None:
            raise NativeNamespaceError("scoped trace requires an opt-in namespace")
        return None
    if sys.platform != "linux":
        raise NativeNamespaceError("opt-in native namespace requires Linux")
    raw, digest = _read(path)
    scope = json.loads(raw)
    _validate(scope, codex=codex, home=home, workspace=workspace)
    binding = {
        "path": str(path),
        "sha256": digest,
        "scope": scope,
        "dispatcher_sha256": _read(__file__)[1],
    }
    if trace_root is not None:
        if not isinstance(trace_root, (str, os.PathLike)):
            raise NativeNamespaceError("scoped trace path must be a path string")
        selected = _directory(os.fspath(trace_root))
        telemetry = Path(scope["telemetry"])
        if selected == telemetry or not selected.is_relative_to(telemetry):
            raise NativeNamespaceError("scoped trace must be a private telemetry child")
        if str(selected) != str(trace_root):
            raise NativeNamespaceError("scoped trace path is not canonical")
        binding["trace_root"] = str(selected)
    return binding


def wrap_namespace(command, binding, *, output_sink=None):
    """Build a bounded, shell-free prefix without changing native permissions."""
    if binding is None:
        if output_sink is not None:
            raise NativeNamespaceError("output sink requires a scoped action")
        return command
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(arg, str) for arg in command)
    ):
        raise NativeNamespaceError("native command must be a nonempty string vector")
    fields = {"path", "sha256", "scope", "dispatcher_sha256"}
    if not isinstance(binding, dict) or set(binding) not in (
        fields,
        fields | {"trace_root"},
    ):
        raise NativeNamespaceError("namespace binding schema differs")
    scope = binding["scope"]
    alias = _native_alias(scope)
    current = bind_namespace(
        command[0],
        scope["home"],
        scope["workspace"],
        trace_root=binding.get("trace_root"),
    )
    if current != binding:
        raise NativeNamespaceError("namespace binding changed before dispatch")
    sink = None
    if output_sink is not None:
        if "trace_root" not in binding or not isinstance(
            output_sink, (str, os.PathLike)
        ):
            raise NativeNamespaceError("output sink requires a scoped action")
        sink = Path(output_sink)
        if (
            not sink.is_absolute()
            or str(sink.resolve()) != os.fspath(output_sink)
            or sink.name != "final.txt"
            or not sink.is_relative_to(Path(scope["capture_root"]))
            or command.count("-o") != 1
            or command[command.index("-o") + 1 : command.index("-o") + 2] != [str(sink)]
        ):
            raise NativeNamespaceError("output sink differs from the native final path")
        _read(sink)  # Require a precreated, anchored regular file, never a directory.
    elif "trace_root" in binding and "-o" in command:
        raise NativeNamespaceError("scoped final output requires its single-file sink")
    prefix = [
        scope["bwrap"],
        "--unshare-all",
        "--share-net",
        "--unshare-user",
        "--new-session",
        "--die-with-parent",
        "--cap-drop",
        "ALL",
        "--ro-bind",
        scope["rootfs"],
        "/",
    ]
    # Writable mount points are prepared before narrow role binds. They hide
    # all ambient homes, peer workspaces and evaluator dependencies in /opt.
    for base in ("/home", "/root", "/mnt", "/opt", "/tmp", "/run"):
        prefix.extend(("--tmpfs", base))
    prefix.extend(
        (
            "--ro-bind",
            alias,
            alias,
            "--ro-bind",
            scope["dns_path"],
            "/etc/resolv.conf",
        )
    )
    names = (
        ("home", "workspace")
        if "trace_root" in binding
        else ("home", "workspace", "telemetry", "capture_root")
    )
    for name in names:
        prefix.extend(("--bind", scope[name], scope[name]))
    if "trace_root" in binding:
        # The recorder owns archives outside this process. The provider only
        # needs its selected trace child; parent/sibling evidence stays absent.
        selected = binding["trace_root"]
        prefix.extend(("--bind", selected, selected))
    if sink is not None:
        prefix.extend(("--bind", str(sink), str(sink)))
    prefix.extend(("--ro-bind", binding["path"], binding["path"]))
    prefix.extend(
        (
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--chdir",
            scope["workspace"],
            "--clearenv",
            "--setenv",
            "PATH",
            "/usr/local/bin:/usr/bin:/bin",
            "--setenv",
            "HOME",
            scope["home"],
            "--setenv",
            "CODEX_HOME",
            scope["home"],
            "--setenv",
            "CODEX_ROLLOUT_TRACE_ROOT",
            binding.get("trace_root", scope["telemetry"]),
            "--",
        )
    )
    return prefix + command

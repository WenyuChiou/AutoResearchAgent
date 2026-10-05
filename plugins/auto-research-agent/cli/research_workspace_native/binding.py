"""Reuse the accepted code-byte verifier before emitting native RPC bytes."""

from copy import deepcopy
import hashlib
from pathlib import Path
import os
import re
import stat
import subprocess

from stage1_deliverable.common import reject_links, safe_path
from stage1_retrieval.runtime_identity import tree_files, verify_identity


class BindingError(ValueError):
    """A reviewed code or immutable dependency binding changed."""


class BindingVerifier:
    """Check runtime pins and physical tracked bytes against accepted Git blobs.

    This read-only guard does not launch, authorize or attest a native process.
    A production channel still needs reviewed launch and connection admission.
    Normalized CRLF/encoding/filter worktrees must match raw blobs or fail closed.
    Each call is a point-in-time check, not a lock against concurrent file edits.
    """

    def __init__(self, runtime_pin, dependency_root, dependency_sha):
        if not re.fullmatch(r"[a-f0-9]{40}", dependency_sha):
            raise BindingError("immutable dependency SHA required")
        self.pin = deepcopy(runtime_pin)
        reject_links(Path(dependency_root).absolute())
        self.root = str(Path(dependency_root).resolve(strict=True))
        self.sha = dependency_sha
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.prefix = [
            "git",
            "--no-replace-objects",
            "--no-lazy-fetch",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "safe.directory=" + self.root,
            "-C",
            self.root,
        ]
        self.files = {}
        commit = self._object("commit", self.sha)
        if not re.match(rb"tree [a-f0-9]{40}\n", commit):
            raise BindingError("dependency commit tree unavailable")
        self._object("tree", commit.splitlines()[0][5:].decode("ascii"))
        for row in self._git(
            "ls-tree", "-r", "-t", "-z", "--full-tree", self.sha
        ).split(b"\0"):
            if not row:
                continue
            header, raw_path = row.split(b"\t", 1)
            mode, kind, oid = header.decode("ascii").split()
            if kind == "tree" and mode == "040000":
                self._object("tree", oid)
                continue
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise BindingError("unsupported dependency Git mode")
            try:
                name = raw_path.decode("utf-8", errors="strict")
                path = safe_path(self.root, name)
                if any(part.casefold() == ".git" for part in Path(name).parts):
                    raise ValueError("reserved Git path")
            except (ValueError, OSError) as error:
                raise BindingError("unsafe dependency path") from error
            if str(path).casefold() in {
                str(p).casefold() for p, _, _ in self.files.values()
            }:
                raise BindingError("ambiguous dependency path")
            self.files[raw_path] = (path, mode, oid)
        # Read retained object bytes, never a constructor snapshot of worktree bytes.
        self.blobs = {
            oid: self._object("blob", oid) for _, _, oid in self.files.values()
        }

    def _object(self, kind, oid):
        raw = self._git("cat-file", kind, oid)
        header = f"{kind} {len(raw)}\0".encode("ascii")
        if hashlib.sha1(header + raw).hexdigest() != oid:
            raise BindingError("retained Git object bytes differ from object ID")
        return raw

    def _git(self, *args):
        try:
            return subprocess.check_output(
                self.prefix + list(args), env=self.env, timeout=10
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise BindingError("dependency binding unavailable") from error

    def __call__(self):
        for root, code_only in self.pin["code_identity"]["roots"].items():
            if code_only and any(
                Path(name).suffix.lower() == ".pyc"
                for name in tree_files(root, code_only=True)
            ):
                raise BindingError(
                    "cached bytecode in adapter source tree is not admitted"
                )
        verify_identity(self.pin, probe=False)
        head = self._git("rev-parse", "HEAD").decode("ascii").strip()
        index = self._git("ls-files", "--stage", "-v", "-z")
        expected = {
            b"H " + mode.encode() + b" " + oid.encode() + b" 0\t" + name
            for name, (_, mode, oid) in self.files.items()
        }
        if (
            head != self.sha
            or set(index.split(b"\0")) - {b""} != expected
            or self._git("ls-files", "--others", "--exclude-standard", "-z")
        ):
            raise BindingError("dependency SHA or checkout bytes changed")
        try:
            for name, (path, _, oid) in self.files.items():
                path = safe_path(self.root, name.decode("utf-8"))
                if (
                    not stat.S_ISREG(path.stat().st_mode)
                    or path.read_bytes() != self.blobs[oid]
                ):
                    raise BindingError(
                        "dependency physical bytes differ from accepted blob"
                    )
        except (OSError, ValueError) as error:
            raise BindingError(
                "dependency physical bytes unavailable or changed"
            ) from error

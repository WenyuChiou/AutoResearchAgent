"""Reuse the accepted code-byte verifier before emitting native RPC bytes."""

from copy import deepcopy
from pathlib import Path
import re
import subprocess

from stage1_retrieval.runtime_identity import tree_files, verify_identity


class BindingError(ValueError):
    """A reviewed code or immutable dependency binding changed."""


class BindingVerifier:
    """Check retained Python runtime pins and a clean dependency checkout.

    This read-only guard does not launch, authorize or attest a native process.
    A production channel still needs reviewed launch and connection admission.
    """

    def __init__(self, runtime_pin, dependency_root, dependency_sha):
        if not re.fullmatch(r"[a-f0-9]{40}", dependency_sha):
            raise BindingError("immutable dependency SHA required")
        self.pin = deepcopy(runtime_pin)
        self.root = str(Path(dependency_root).resolve(strict=True))
        self.sha = dependency_sha

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
        prefix = ["git", "-c", "safe.directory=" + self.root, "-C", self.root]
        try:
            head, dirty, flags = (
                subprocess.check_output(prefix + args, text=True, timeout=10).strip()
                for args in (
                    ["rev-parse", "HEAD"],
                    ["status", "--porcelain", "--untracked-files=normal"],
                    ["ls-files", "-v", "-z"],
                )
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise BindingError("dependency binding unavailable") from error
        if (
            head != self.sha
            or dirty
            or any(row and row[0] != "H" for row in flags.split("\0"))
        ):
            raise BindingError("dependency SHA or checkout bytes changed")

"""Anchor seal reads and exclusive writes to retained directory handles."""

from contextlib import ExitStack
import os
from pathlib import Path
import stat

from .trace_files import _require
from .trace_handles import _WindowsHandles


class SealDirectory:
    def __init__(self, path, parent=None):
        self.path, self.parent, self.stack = Path(path), parent, ExitStack()
        self.active = False

    def __enter__(self):
        _require(self.parent is None or self.parent.active, "seal-parent-closed")
        try:
            if os.name == "nt":
                self.windows = _WindowsHandles()
                paths = (
                    [self.path]
                    if self.parent
                    else [*reversed(self.path.parents), self.path]
                )
                for path in paths:
                    handle = self.windows.open(path, directory=True)
                    self.stack.callback(self.windows.close, handle)
                self.target = self.path
            else:
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                if self.parent:
                    current = os.open(self.path.name, flags, dir_fd=self.parent.target)
                    self.stack.callback(os.close, current)
                else:
                    current = os.open(self.path.anchor, flags)
                    self.stack.callback(os.close, current)
                    for part in self.path.parts[1:]:
                        current = os.open(part, flags, dir_fd=current)
                        self.stack.callback(os.close, current)
                self.target = current
            self.active = True
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *error):
        self.active = False
        return self.stack.__exit__(*error)

    def _name(self, name):
        _require(self.active, "seal-directory-closed")
        _require(
            isinstance(name, str)
            and name not in {"", ".", ".."}
            and "/" not in name
            and "\\" not in name
            and ":" not in name
            and all(ord(char) >= 32 for char in name)
            and not name.endswith((".", " ")),
            "seal-leaf-invalid",
        )
        return name

    def make_dir(self, name):
        self._name(name)
        if os.name == "nt":
            os.mkdir(self.path / name)
        else:
            os.mkdir(name, dir_fd=self.target)
        return SealDirectory(self.path / name, self)

    def status(self, name):
        self._name(name)
        if os.name == "nt":
            return os.stat(self.path / name, follow_symlinks=False)
        return os.stat(name, dir_fd=self.target, follow_symlinks=False)

    def _stream(self, name, write):
        self._name(name)
        if os.name == "nt":
            import msvcrt

            if write:
                handle = self.windows.api.CreateFileW(
                    str(self.path / name), 0x40000000, 0, None, 1, 0x00200000, None
                )
                if handle == self.windows.ctypes.c_void_p(-1).value:
                    raise self.windows.ctypes.WinError(
                        self.windows.ctypes.get_last_error()
                    )
            else:
                handle = self.windows.open(self.path / name, directory=False)
            try:
                descriptor = msvcrt.open_osfhandle(
                    handle, (os.O_WRONLY if write else os.O_RDONLY) | os.O_BINARY
                )
            except BaseException:
                self.windows.close(handle)
                raise
        else:
            flags = (
                os.O_NOFOLLOW
                | os.O_NONBLOCK
                | (os.O_WRONLY | os.O_CREAT | os.O_EXCL if write else os.O_RDONLY)
            )
            descriptor = os.open(name, flags, 0o600, dir_fd=self.target)
        try:
            _require(
                stat.S_ISREG(os.fstat(descriptor).st_mode), "seal-file-not-regular"
            )
            return os.fdopen(descriptor, "wb" if write else "rb")
        except BaseException:
            os.close(descriptor)
            raise

    def reader(self, name):
        return self._stream(name, False)

    def write(self, name, value):
        with self._stream(name, True) as stream:
            stream.write(value)

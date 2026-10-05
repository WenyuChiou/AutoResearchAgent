"""Keep trace traversal attached to original directories and regular files."""

from contextlib import ExitStack
import os
from pathlib import Path
import stat

from stage2_common import Stage2Error


def _reject(message):
    raise Stage2Error(f"native-trace-{message}")


class TraceRoot:
    def __init__(self, root):
        self.root = Path(root)
        self.stack = ExitStack()
        self.directories = {}

    def __enter__(self):
        try:
            if os.name == "nt":
                self._lock_windows_directories()
            else:
                self._anchor_posix_directories()
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *exception):
        return self.stack.__exit__(*exception)

    def _anchor_posix_directories(self):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        current = os.open(self.root.anchor, flags)
        self.stack.callback(os.close, current)
        for part in self.root.parts[1:]:
            current = os.open(part, flags, dir_fd=current)
            self.stack.callback(os.close, current)
        self.directories[""] = current
        payloads = os.open("payloads", flags, dir_fd=current)
        self.stack.callback(os.close, payloads)
        self.directories["payloads"] = payloads

    def _lock_windows_directories(self):
        self.windows = _WindowsHandles()
        for path in (*reversed(self.root.parents), self.root, self.root / "payloads"):
            handle = self.windows.open(path, directory=True)
            self.stack.callback(self.windows.close, handle)
        self.directories = {"": self.root, "payloads": self.root / "payloads"}

    def entries(self, maximum):
        names = []
        for prefix, directory in self.directories.items():
            with os.scandir(directory) as entries:
                for entry in entries:
                    if not prefix and entry.name == "payloads":
                        continue
                    status = entry.stat(follow_symlinks=False)
                    if (
                        not stat.S_ISREG(status.st_mode)
                        or getattr(status, "st_file_attributes", 0) & 0x400
                    ):
                        _reject("entry-not-regular")
                    names.append(f"{prefix}/{entry.name}" if prefix else entry.name)
                    if len(names) > maximum:
                        _reject("inventory-file-limit")
        return names

    def open_file(self, name):
        if os.name == "nt":
            import msvcrt

            handle = self.windows.open(self.root / name, directory=False)
            try:
                descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            except BaseException:
                self.windows.close(handle)
                raise
        else:
            prefix, filename = name.rsplit("/", 1) if "/" in name else ("", name)
            descriptor = os.open(
                filename,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=self.directories[prefix],
            )
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                _reject("opened-file-not-regular")
            return os.fdopen(descriptor, "rb")
        except BaseException:
            os.close(descriptor)
            raise


class _WindowsHandles:
    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class FileInformation(ctypes.Structure):
            _fields_ = [
                ("attributes", wintypes.DWORD),
                ("creation", wintypes.FILETIME),
                ("access", wintypes.FILETIME),
                ("write", wintypes.FILETIME),
                ("volume", wintypes.DWORD),
                ("size_high", wintypes.DWORD),
                ("size_low", wintypes.DWORD),
                ("links", wintypes.DWORD),
                ("index_high", wintypes.DWORD),
                ("index_low", wintypes.DWORD),
            ]

        self.ctypes, self.Information = ctypes, FileInformation
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self.api.CreateFileW.restype = wintypes.HANDLE
        self.api.GetFileInformationByHandle.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(FileInformation),
        ]
        self.api.GetFileInformationByHandle.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.api.GetFileType.argtypes = [wintypes.HANDLE]
        self.api.GetFileType.restype = wintypes.DWORD

    def close(self, handle):
        if not self.api.CloseHandle(handle):
            raise self.ctypes.WinError(self.ctypes.get_last_error())

    def open(self, path, *, directory):
        # No SHARE_DELETE: retained directories cannot be renamed/replaced.
        handle = self.api.CreateFileW(
            str(path),
            0x81 if directory else 0x80000000,  # LIST_DIRECTORY + READ_ATTRIBUTES
            3 if directory else 1,
            None,
            3,
            0x02000000 | 0x00200000,
            None,
        )
        if handle == self.ctypes.c_void_p(-1).value:
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        try:
            info = self.Information()
            if not self.api.GetFileInformationByHandle(handle, self.ctypes.byref(info)):
                raise self.ctypes.WinError(self.ctypes.get_last_error())
            if info.attributes & 0x400 or bool(info.attributes & 0x10) != directory:
                _reject("opened-object-reparse-or-kind-mismatch")
            if not directory and self.api.GetFileType(handle) != 1:
                _reject("opened-file-not-disk")
            return handle
        except BaseException:
            self.close(handle)
            raise

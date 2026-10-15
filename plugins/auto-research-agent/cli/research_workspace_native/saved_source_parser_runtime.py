"""Raw-pinned SDK496/dependency imports for the fixed offline saved parser.

Inventories are physical configuration evidence, not loaded-image attestation.
The bootstrap's already loaded stdlib belongs to the trusted Python bootstrap;
SDK/dependency source is compiled from pinned bytes, without site or cached pyc.
"""

import importlib.abc
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path, PurePosixPath
import stat
import sys

from .atlas_local_source import canonical, digest, require, unlinked

SDK_COMMIT = "496a70415859a15031cb5da55d4495cb1d0a8e7d"
MAX_FILE = 128 * 1024 * 1024
MAX_TREE = 512 * 1024 * 1024


def _read_regular(path, maximum, *, allow_empty=False):
    path = Path(path)
    before = path.lstat()
    require(
        not stat.S_ISLNK(before.st_mode)
        and not getattr(before, "st_file_attributes", 0) & 0x400,
        "saved-parser-linked-runtime-file",
    )
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(opened.st_mode)
            and opened.st_nlink == 1
            and (before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino),
            "saved-parser-runtime-file-identity",
        )
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    require(
        len(raw) <= maximum
        and (bool(raw) or allow_empty)
        and (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
        == (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
        "saved-parser-runtime-file-bound-or-drift",
    )
    reopened = path.lstat()
    require(
        (reopened.st_dev, reopened.st_ino) == (opened.st_dev, opened.st_ino),
        "saved-parser-runtime-path-drift",
    )
    return raw


def read(path, maximum, *, allow_empty=False):
    """Reopen regular single-link bytes and reject identity/ancestor drift."""
    path = unlinked(Path(path))
    raw = _read_regular(path, maximum, allow_empty=allow_empty)
    unlinked(path)
    return raw


def tree_inventory(root, *, exclude=()):
    root = unlinked(Path(root))
    require(root.is_dir(), "saved-parser-runtime-directory-required")
    result, total = {}, 0
    for base, dirs, names in os.walk(root, followlinks=False):
        directory = unlinked(Path(base))
        before = directory.stat()
        dirs[:] = sorted(
            name
            for name in dirs
            if name not in {"__pycache__", ".ruff_cache", ".pytest_cache"}
            and not (Path(base) == root and name in exclude)
        )
        for name in dirs:
            unlinked(Path(base) / name)
        for name in sorted(names):
            if name.endswith((".pyc", ".pyo")):
                continue
            path = Path(base) / name
            # Check ancestors once per directory and every opened descriptor.
            # Imports still recheck every ancestor and exact physical bytes.
            raw = _read_regular(path, MAX_FILE, allow_empty=True)
            total += len(raw)
            require(
                len(result) < 16384 and total <= MAX_TREE,
                "saved-parser-inventory-bound",
            )
            result[path.relative_to(root).as_posix()] = digest(raw)
        after = unlinked(directory).stat()
        require(
            (before.st_dev, before.st_ino, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_mtime_ns),
            "saved-parser-runtime-directory-drift",
        )
    unlinked(root)
    return result


def configuration(value):
    require(
        type(value) is dict
        and set(value)
        == {
            "kind",
            "schema_version",
            "sdk_commit",
            "sdk_root",
            "sdk_tree_sha256",
            "runtime_roots",
            "module_paths",
            "runtime_support",
            "inventory_sha256",
        }
        and value["kind"] == "SavedSourceParserRuntime"
        and value["schema_version"] == "1.0.0"
        and value["sdk_commit"] == SDK_COMMIT,
        "saved-parser-runtime-fields",
    )
    roots = value["runtime_roots"]
    require(type(roots) is list and len(roots) == 3, "saved-parser-runtime-roots")
    paths = []
    for root in roots:
        require(
            type(root) is dict and set(root) == {"path", "files", "exclude"},
            "saved-parser-runtime-root-fields",
        )
        require(
            type(root["path"]) is str and Path(root["path"]).is_absolute(),
            "saved-parser-runtime-root-path",
        )
        require(
            root["exclude"] in ([], ["site-packages"]), "saved-parser-runtime-exclusion"
        )
        files = root["files"]
        require(
            type(files) is dict and 1 <= len(files) <= 16384,
            "saved-parser-runtime-inventory-required",
        )
        for name, sha in files.items():
            path = PurePosixPath(name)
            require(
                type(name) is str
                and str(path) == name
                and not path.is_absolute()
                and ".." not in path.parts
                and "\\" not in name
                and ":" not in name
                and type(sha) is str
                and len(sha) == 64
                and all(c in "0123456789abcdef" for c in sha),
                "saved-parser-runtime-inventory-path",
            )
        paths.append(root["path"])
    require(
        len(set(paths)) == 3 and value["module_paths"] == paths,
        "saved-parser-module-paths-differ",
    )
    sdk = Path(value["sdk_root"])
    require(
        sdk.name == "research_hub" and sdk.parent == Path(paths[2]),
        "saved-parser-sdk-root-differs",
    )
    sdk_files = {
        name.removeprefix("research_hub/"): sha
        for name, sha in roots[2]["files"].items()
        if name.startswith("research_hub/")
    }
    require(
        bool(sdk_files) and digest(canonical(sdk_files)) == value["sdk_tree_sha256"],
        "saved-parser-sdk-tree-binding-differs",
    )
    support = value["runtime_support"]
    require(
        type(support) is dict and 1 <= len(support) <= 16,
        "saved-parser-runtime-support-required",
    )
    for name, sha in support.items():
        require(
            Path(name).is_absolute()
            and Path(name).suffix.lower() == ".dll"
            and type(sha) is str
            and len(sha) == 64
            and all(c in "0123456789abcdef" for c in sha),
            "saved-parser-runtime-support-invalid",
        )
    binding = {name: data for name, data in value.items() if name != "inventory_sha256"}
    require(
        digest(canonical(binding)) == value["inventory_sha256"],
        "saved-parser-runtime-binding-differs",
    )
    require(len(canonical(value)) <= 1024 * 1024, "saved-parser-runtime-document-bound")
    return value


def verify_sdk(config):
    configuration(config)
    require(
        digest(canonical(tree_inventory(config["sdk_root"])))
        == config["sdk_tree_sha256"],
        "saved-parser-sdk-complete-tree-differs",
    )
    for path, sha in config["runtime_support"].items():
        require(
            digest(read(path, MAX_FILE)) == sha, "saved-parser-runtime-support-differs"
        )


class _PinnedResources(importlib.abc.ResourceReader):
    """Standard resource API using verified bytes, including certifi's PEM.

    Never expose a path that could later be reopened without its inventory hash.
    Stdlib resource contexts may copy these bytes into the confined Job TEMP.
    """

    def __init__(self, loader, package):
        self.loader, self.package = loader, package

    def _path(self, resource):
        require(
            type(resource) is str
            and resource not in {"", ".", ".."}
            and Path(resource).name == resource
            and "/" not in resource
            and "\\" not in resource
            and ":" not in resource,
            "saved-parser-resource-name-invalid",
        )
        return self.package / resource

    def open_resource(self, resource):
        return io.BytesIO(self.loader.pin(self._path(resource)))

    def resource_path(self, resource):
        self._path(resource)
        raise FileNotFoundError("sealed resource is available only as verified bytes")

    def is_resource(self, resource):
        path = self._path(resource)
        for row in self.loader.config["runtime_roots"]:
            root = Path(row["path"])
            if path.is_relative_to(root):
                return path.relative_to(root).as_posix() in row["files"]
        return False

    def contents(self):
        for row in self.loader.config["runtime_roots"]:
            root = Path(row["path"])
            if self.package.is_relative_to(root):
                prefix = self.package.relative_to(root).as_posix() + "/"
                return iter(
                    sorted(
                        {
                            name[len(prefix) :].split("/", 1)[0]
                            for name in row["files"]
                            if name.startswith(prefix)
                        }
                    )
                )
        return iter(())


class RawSavedSdkLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, config):
        self.config, self.selected = configuration(config), {}
        self.roots = tuple(Path(path) for path in config["module_paths"])

    def pin(self, path):
        path = unlinked(Path(path))
        for row in self.config["runtime_roots"]:
            root = Path(row["path"])
            if path.is_relative_to(root):
                name = path.relative_to(root).as_posix()
                require(name in row["files"], "saved-parser-unlisted-runtime-file")
                raw = read(path, MAX_FILE, allow_empty=True)
                require(
                    digest(raw) == row["files"][name],
                    "saved-parser-runtime-file-differs",
                )
                return raw
        require(False, "saved-parser-runtime-file-outside-pins")

    def find_spec(self, fullname, path=None, target=None):
        roots = self.roots if path is None else tuple(Path(name) for name in path)
        leaf = fullname.rsplit(".", 1)[-1]
        for root in roots:
            if not any(
                root == base or root.is_relative_to(base) for base in self.roots
            ):
                continue
            selected = root / leaf
            package = selected.is_dir()
            candidates = (
                [selected / "__init__.py"] if package else [selected.with_suffix(".py")]
            )
            candidates += [
                selected / ("__init__" + suffix) if package else root / (leaf + suffix)
                for suffix in importlib.machinery.EXTENSION_SUFFIXES
            ]
            for candidate in candidates:
                if candidate.is_file():
                    self.pin(candidate)
                    if candidate.suffix != ".py":
                        loader = importlib.machinery.ExtensionFileLoader(
                            fullname, str(candidate)
                        )
                    else:
                        loader = self
                    self.selected[fullname] = (candidate, loader)
                    return importlib.util.spec_from_file_location(
                        fullname,
                        candidate,
                        loader=loader,
                        submodule_search_locations=[str(selected)] if package else None,
                    )
            if package:
                unlinked(selected)
                spec = importlib.machinery.ModuleSpec(fullname, None, is_package=True)
                spec.submodule_search_locations = [str(selected)]
                return spec
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        path, _ = self.selected[module.__name__]
        exec(compile(self.pin(path), str(path), "exec"), module.__dict__)

    def get_resource_reader(self, fullname):
        selected = self.selected.get(fullname)
        if selected is not None and selected[0].name == "__init__.py":
            return _PinnedResources(self, selected[0].parent)
        return None

    def verify_loaded(self):
        for name, (path, loader) in self.selected.items():
            module = sys.modules.get(name)
            if module is None:
                continue
            spec = getattr(module, "__spec__", None)
            require(
                getattr(module, "__file__", None) == str(path)
                and spec is not None
                and spec.origin == str(path)
                and spec.loader is loader
                and getattr(module, "__loader__", None) is loader,
                "saved-parser-loaded-origin-differs",
            )
            if spec.submodule_search_locations is not None:
                require(
                    list(module.__path__) == [str(path.parent)],
                    "saved-parser-package-path-differs",
                )
            self.pin(path)
        for name, module in tuple(sys.modules.items()):
            if name.split(".")[0] == "research_hub":
                require(name in self.selected, "saved-parser-sdk-not-raw-loaded")
        require(
            "research_hub.source_fetch_saved" in self.selected,
            "saved-parser-sdk-operation-missing",
        )


def install_runtime(config):
    verify_sdk(config)
    require(
        Path(config["module_paths"][0]) == Path(sys.base_prefix) / "Lib"
        and Path(config["module_paths"][1]) == Path(sys.base_prefix) / "DLLs"
        and Path(config["module_paths"][2])
        == Path(sys.executable).parent.parent / "Lib/site-packages",
        "saved-parser-actual-interpreter-runtime-differs",
    )
    require(
        not any(
            name == "research_hub" or name.startswith("research_hub.")
            for name in sys.modules
        ),
        "saved-parser-sdk-already-loaded",
    )
    loader = RawSavedSdkLoader(config)
    # No site/.pth, user path, zip import or ordinary dependency loader fallback.
    sys.path[:] = []
    sys.meta_path.insert(1, loader)  # The owned plugin loader remains first.
    return loader


def offline_audit(event, args):
    if event.startswith("socket.") or event in {
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.spawn",
    }:
        require(False, "saved-parser-network-or-process-unavailable")
    if event == "ctypes.dlopen":
        require(
            args[0] in (None, "kernel32", "kernel32.dll"),
            "saved-parser-native-loader-unavailable",
        )

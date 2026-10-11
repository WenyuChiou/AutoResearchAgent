"""Fresh raw-pinned source worker bootstrap, including multiprocessing spawn.

Only two fixed server arguments exist: the exclusive launch manifest and its
SHA. No URL/argv/module choice comes from a browser. __mp_main__ installs the
same raw loader before the DNS target module is imported, but performs no HTTP.
"""

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import types


def _read(path, maximum, *, allow_empty=False):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("source-worker-absolute-file-required")
    for ancestor in (path, *path.parents):
        info = ancestor.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("source-worker-linked-file")
    before = path.stat()
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise ValueError("source-worker-file-identity")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    if (
        (not raw and not allow_empty)
        or len(raw) > maximum
        or (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
    ):
        raise ValueError("source-worker-file-bound-or-drift")
    return raw


def _pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            raise ValueError("source-worker-duplicate-field")
        result[key] = value
    return result


def initialize():
    if len(sys.argv) != 3:
        raise ValueError("source-worker-fixed-arguments-required")
    raw = _read(sys.argv[1], 2 * 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != sys.argv[2]:
        raise ValueError("source-worker-launch-hash-differs")
    launch = json.loads(
        raw.decode("utf8"),
        object_pairs_hook=_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(
            ValueError("source-worker-nonfinite")
        ),
    )
    if type(launch) is not dict:
        raise ValueError("source-worker-launch-shape")
    sdk_parse = launch.get("kind") == "OwnedSavedSourceParserLaunch"
    if set(launch) != {
        "kind",
        "schema_version",
        "config",
        "config_sha256",
        "request",
        "request_sha256",
        "output_dir",
        "git_global_config",
    } | ({"parse_saved_manifest"} if sdk_parse else set()):
        raise ValueError("source-worker-launch-shape")
    config = launch["config"]
    repo = Path(config["repo"])
    root = repo / "plugins/auto-research-agent/cli"
    loader_path = root / "research_workspace_native/atlas_local_source.py"
    loader_raw = _read(loader_path, 256 * 1024)
    if (
        hashlib.sha256(loader_raw).hexdigest()
        != config["files"]["cli/research_workspace_native/atlas_local_source.py"]
    ):
        raise ValueError("source-worker-loader-hash-differs")
    helpers = types.ModuleType("_source_worker_raw_pins")
    exec(compile(loader_raw, str(loader_path), "exec"), helpers.__dict__)
    helpers.require(
        launch["kind"] in {"OwnedSourceWorkerLaunch", "OwnedSavedSourceParserLaunch"}
        and launch["schema_version"] == "1.0.0",
        "source-worker-launch-version",
    )
    helpers.require(
        helpers.digest(helpers.canonical(config)) == launch["config_sha256"],
        "source-worker-config-hash-differs",
    )
    helpers.require(
        helpers.digest(helpers.canonical(config["files"]))
        == config["inventory_sha256"],
        "source-worker-inventory-hash-differs",
    )
    helpers.require(
        helpers.digest(helpers.canonical(launch["request"]))
        == launch["request_sha256"],
        "source-worker-request-hash-differs",
    )
    helpers.pinned(
        Path(__file__),
        config["files"]["cli/research_workspace_native/source_worker_bootstrap.py"],
    )
    helpers.pinned(
        Path(config["interpreter"]), config["interpreter_sha256"], 64 * 1024 * 1024
    )
    helpers.pinned(
        Path(config["git_executable"]), config["git_sha256"], 64 * 1024 * 1024
    )
    git = launch["git_global_config"]
    helpers.require(
        type(git) is dict
        and set(git) == {"path", "sha256"}
        and Path(git["path"]) == Path(sys.argv[1]).parent / "gitconfig"
        and _read(Path(git["path"]), 0, allow_empty=True) == b""
        and git["sha256"] == helpers.digest(b"")
        and os.environ.get("GIT_CONFIG_GLOBAL") == git["path"]
        and os.environ.get("GIT_CONFIG_NOSYSTEM") == "1"
        and os.environ.get("GIT_TERMINAL_PROMPT") == "0"
        and os.environ.get("PATH")
        == str(Path(config["git_executable"]).parent)
        + os.pathsep
        + str(Path(os.environ["SystemRoot"]) / "System32"),
        "source-worker-git-environment-differs",
    )
    helpers.require(
        Path(sys.executable).resolve() == Path(config["interpreter"]).resolve(),
        "source-worker-interpreter-differs",
    )
    if sdk_parse:
        private_home = Path(sys.argv[1]).parent / "home"
        helpers.require(
            os.environ.get("USERPROFILE") == str(private_home)
            and private_home.is_dir(),
            "saved-parser-private-home-differs",
        )
        helpers.unlinked(private_home)
    helpers.unlinked(repo)
    sys.dont_write_bytecode = True
    loader = helpers.PinnedLoader(repo, config["files"])
    # Same bootstrap class identity used by existing atlas_local_launcher.
    helpers.__file__ = str(loader_path)
    sys.modules["research_workspace_native.atlas_local_source"] = helpers
    sys.meta_path.insert(0, loader)
    return launch


if __name__ in {"__main__", "__mp_main__"}:
    # spawn executes this before importing its owned _dns_child target. Neither
    # __mp_main__ nor import-as-module is a transport entrypoint.
    _launch = initialize()
    if __name__ == "__main__":
        if _launch["kind"] == "OwnedSavedSourceParserLaunch":
            from research_workspace_native.saved_source_parser_worker import run_sdk

            run_sdk(_launch)
        else:
            from research_workspace_native.source_worker_transport import run_worker

            run_worker(_launch)

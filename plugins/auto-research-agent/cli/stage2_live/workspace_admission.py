"""Admit only authenticated preflight canaries into a production workspace."""

import hashlib
import os
from pathlib import Path, PurePosixPath, PureWindowsPath

from stage2_common import Stage2Error


def _relative_key(value, label):
    if not isinstance(value, str) or not value.strip():
        raise Stage2Error(f"controller-preflight-{label}-path-invalid")
    posix = PurePosixPath(value.replace("\\", "/"))
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ":" in value
        or ".." in posix.parts
        or ".." in windows.parts
        or posix.as_posix() in {".", ""}
    ):
        raise Stage2Error(f"controller-preflight-{label}-path-invalid")
    return posix.as_posix()


def _is_git_path(key):
    return key == ".git" or key.startswith(".git/")


def _reserved_probe_path(key):
    # Fail closed across case-insensitive filesystems and Win32 name aliases.
    root = PurePosixPath(key).parts[0].rstrip(" .").casefold()
    return root in {"input.json", "sources", ".git"}


def _safe_workspace_path(workspace, key, label):
    path = workspace.joinpath(*PurePosixPath(key).parts)
    for item in (path, *path.parents):
        if item == workspace.parent:
            break
        try:
            attributes = item.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise Stage2Error(
                f"controller-preflight-{label}-path-uninspectable"
            ) from error
        if item.is_symlink() or getattr(attributes, "st_file_attributes", 0) & 0x400:
            raise Stage2Error(f"controller-preflight-{label}-path-symlink")
    try:
        if not path.resolve().is_relative_to(workspace.resolve()):
            raise Stage2Error(f"controller-preflight-{label}-path-invalid")
    except (OSError, RuntimeError) as error:
        raise Stage2Error(f"controller-preflight-{label}-path-invalid") from error
    return path


def _binding_files(binding, workspace, label):
    if (
        not isinstance(binding, dict)
        or binding.get("kind") != "directory"
        or not isinstance(binding.get("files"), dict)
    ):
        raise Stage2Error(f"controller-preflight-{label}-inventory-missing")
    try:
        bound_root = Path(binding["path"]).resolve()
    except (KeyError, TypeError, OSError, RuntimeError) as error:
        raise Stage2Error(f"controller-preflight-{label}-inventory-invalid") from error
    if bound_root != workspace.resolve():
        raise Stage2Error(f"controller-preflight-{label}-workspace-mismatch")
    files = binding["files"]
    if not all(
        isinstance(key, str) and isinstance(value, str) for key, value in files.items()
    ):
        raise Stage2Error(f"controller-preflight-{label}-inventory-invalid")
    return {key.replace("\\", "/"): value for key, value in files.items()}


def _current_non_git_entries(workspace):
    entries = {}
    pending = [workspace]
    while pending:
        root = pending.pop()
        try:
            children = sorted(os.scandir(root), key=lambda item: item.name)
        except OSError as error:
            raise Stage2Error("controller-subject-workspace-uninspectable") from error
        for child in children:
            path = Path(child.path)
            key = path.relative_to(workspace).as_posix()
            if _is_git_path(key):
                continue
            try:
                attributes = child.stat(follow_symlinks=False)
                symlink = child.is_symlink()
                directory = child.is_dir(follow_symlinks=False)
                file = child.is_file(follow_symlinks=False)
            except OSError as error:
                raise Stage2Error(
                    "controller-subject-workspace-uninspectable"
                ) from error
            if symlink or getattr(attributes, "st_file_attributes", 0) & 0x400:
                raise Stage2Error("controller-subject-workspace-preflight-path-symlink")
            entries[key] = "directory" if directory else "file" if file else "other"
            if directory:
                pending.append(path)
    return entries


def admit_verified_preflight_workspace(workspace, preflight, verified):
    """Allow an empty workspace or the exact canaries in its verified preflight."""
    workspace = Path(workspace)
    entries = _current_non_git_entries(workspace)
    if not entries:
        return
    if (
        not isinstance(preflight, dict)
        or not isinstance(preflight.get("probe_spec"), dict)
        or preflight["probe_spec"].get("kind") != "Stage2ProductionRuntimeProbeSpec"
        or preflight["probe_spec"].get("schema_version") not in {"1.1.0", "1.2.0"}
        or not isinstance(verified, tuple)
        or len(verified) != 2
        or not isinstance(verified[0], dict)
        or not isinstance(verified[1], dict)
        or verified[1].get("kind") != "Stage2ProductionRuntimePreflight"
        or verified[1].get("status") != "passed"
        or verified[1].get("runtime_gate") is not True
        or verified[1].get("validation_scope") != "production-single"
    ):
        raise Stage2Error("controller-subject-workspace-preflight-proof-required")

    probes = preflight["probe_spec"].get("probes", {})
    try:
        read_key = _relative_key(probes["read"]["source_path"], "read")
        write_key = _relative_key(probes["write"]["output_path"], "write")
        write_sha = probes["write"]["sha256"]
    except (KeyError, TypeError) as error:
        raise Stage2Error(
            "controller-subject-workspace-preflight-proof-invalid"
        ) from error
    if read_key == write_key or any(
        _reserved_probe_path(key) for key in (read_key, write_key)
    ):
        raise Stage2Error("controller-subject-workspace-preflight-path-reserved")

    record = verified[0]
    start = _binding_files(record.get("workspace_start"), workspace, "start")
    end = _binding_files(record.get("workspace_end"), workspace, "end")
    start_non_git = {
        key: value for key, value in start.items() if not _is_git_path(key)
    }
    end_non_git = {key: value for key, value in end.items() if not _is_git_path(key)}
    if set(start_non_git) != {read_key} or set(end_non_git) != {
        read_key,
        write_key,
    }:
        raise Stage2Error("controller-subject-workspace-preflight-inventory-mismatch")
    if (
        start_non_git[read_key] != end_non_git[read_key]
        or end_non_git[write_key] != write_sha
    ):
        raise Stage2Error("controller-subject-workspace-preflight-hash-mismatch")
    archived = record.get("archived_files")
    expected_archived = {
        "archive/workspace-start/" + read_key: start_non_git[read_key],
        "archive/workspace-end/" + read_key: end_non_git[read_key],
        "archive/workspace-end/" + write_key: end_non_git[write_key],
    }
    if not isinstance(archived, dict) or any(
        archived.get(key) != value for key, value in expected_archived.items()
    ):
        raise Stage2Error("controller-subject-workspace-preflight-archive-mismatch")

    expected_dirs = {
        parent.as_posix()
        for key in (read_key, write_key)
        for parent in PurePosixPath(key).parents
        if parent.as_posix() != "."
    }
    if set(entries) != {read_key, write_key} | expected_dirs:
        raise Stage2Error("controller-subject-workspace-must-start-empty")
    if any(entries.get(key) != "directory" for key in expected_dirs) or any(
        entries.get(key) != "file" for key in (read_key, write_key)
    ):
        raise Stage2Error("controller-subject-workspace-preflight-path-invalid")

    for key, expected_sha in (
        (read_key, start_non_git[read_key]),
        (write_key, write_sha),
    ):
        path = _safe_workspace_path(workspace, key, key.split("/", 1)[0])
        try:
            actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise Stage2Error(
                "controller-subject-workspace-preflight-file-unreadable"
            ) from error
        if actual_sha != expected_sha:
            raise Stage2Error("controller-subject-workspace-preflight-hash-mismatch")

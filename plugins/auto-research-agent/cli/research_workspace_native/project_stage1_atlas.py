"""Authenticated, bounded Atlas projections of the latest saved Stage 1 package.

Reads reuse local ledger/receipt binding checks and a pure byte reader. They do
not rebuild a delivery, replay a source runtime, mount assets or dispatch work.
"""

import json
import os
import re
import stat
from copy import deepcopy
from pathlib import PurePosixPath
from types import MappingProxyType

from research_workspace.atlas import atlas_asset_files
from research_workspace.atlas_model import model_asset
from research_workspace.canonical_delivery import project_canonical_atlas
from research_workspace.json_bytes import decode_json
from stage1_deliverable.common import canonical, safe_path, sha

from .http import MAX_RESPONSE
from .project_stage1 import _basis
from .project_stage1_delivery import ProjectStage1DeliveryService
from .session_api import SessionApiError, _check, _hash, _text

MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_EXPORT_BYTES = 2 * 1024 * 1024
MAX_EXPORT_FILES = 1024
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
MAX_FILES = 2048
PREFIX = b"window.WORKSPACE_VIEW = "
BIB_FILES = {"references.bib", "literature/screening.bib", "literature/included.bib"}


def _regular(info):
    return (
        stat.S_ISREG(info.st_mode)
        and not getattr(info, "st_file_attributes", 0) & 0x400
    )


def _read_bounded(path, maximum):
    """Never block on a substituted FIFO or follow a final POSIX symlink."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        _check(_regular(info) and info.st_size <= maximum, "stage1-atlas-file-bound")
        raw = stream.read(maximum + 1)
    _check(len(raw) <= maximum, "stage1-atlas-file-bound")
    return raw


def _source(root, expected):
    """Enumerate metadata first, then capture a complete bounded byte snapshot."""
    path = safe_path(root, "provenance_manifest.json")
    raw = _read_bounded(path, MAX_MANIFEST_BYTES)
    _check(
        len(raw) <= MAX_MANIFEST_BYTES and sha(raw) == expected,
        "stage1-atlas-manifest-bytes-differ",
    )
    manifest = decode_json(raw)
    _check(type(manifest) is dict, "stage1-atlas-manifest-invalid")
    files = manifest.get("files")
    _check(type(files) is dict and len(files) <= MAX_FILES, "stage1-atlas-file-bound")
    directories = set()
    for name, digest in files.items():
        safe_path(root, name)
        _check(name != path.name and _hash(digest), "stage1-atlas-source-bytes-differ")
        directories.update(
            str(parent) for parent in PurePosixPath(name).parents if str(parent) != "."
        )
    found, pending, entries, size = {}, [root], 0, len(raw)
    while pending:
        with os.scandir(pending.pop()) as children:
            for entry in children:
                entries += 1
                _check(entries <= MAX_FILES * 2 + 1, "stage1-atlas-path-bound")
                name = entry.path[len(str(root)) + 1 :].replace("\\", "/")
                info = entry.stat(follow_symlinks=False)
                _check(
                    not getattr(info, "st_file_attributes", 0) & 0x400,
                    "stage1-atlas-special-path",
                )
                if stat.S_ISDIR(info.st_mode):
                    _check(name in directories, "stage1-atlas-source-path-unlisted")
                    pending.append(entry.path)
                else:
                    _check(_regular(info), "stage1-atlas-special-path")
                    _check(
                        name == path.name or name in files,
                        "stage1-atlas-source-path-unlisted",
                    )
                    maximum = (
                        MAX_MANIFEST_BYTES if name == path.name else MAX_FILE_BYTES
                    )
                    _check(info.st_size <= maximum, "stage1-atlas-file-bound")
                    found[name] = info.st_size
                    if name != path.name:
                        size += info.st_size
                        _check(size <= MAX_PACKAGE_BYTES, "stage1-atlas-package-bound")
    _check(set(found) == {*files, path.name}, "stage1-atlas-source-bytes-differ")
    snapshot, size = {path.name: raw}, len(raw)
    for name, digest in files.items():
        maximum = min(MAX_FILE_BYTES, MAX_PACKAGE_BYTES - size)
        data = _read_bounded(safe_path(root, name), maximum)
        _check(
            len(data) == found[name] and sha(data) == digest,
            "stage1-atlas-source-bytes-differ",
        )
        size += len(data)
        snapshot[name] = data
    _check(
        _read_bounded(path, MAX_MANIFEST_BYTES) == raw,
        "stage1-atlas-manifest-bytes-differ",
    )
    return MappingProxyType(snapshot)


class ProjectStage1AtlasService:
    """Private GET data only; physical paths and file selections stay server owned."""

    def __init__(self, delivery):
        _check(
            isinstance(delivery, ProjectStage1DeliveryService),
            "stage1-delivery-required",
        )
        self.delivery, self.intake = delivery, delivery.intake
        assets = {
            name: raw
            for name, raw in atlas_asset_files().items()
            if name != "atlas.html"
        }
        assets["atlas-model.js"] = model_asset()
        self._renderer_sha256 = MappingProxyType(
            {name: sha(raw) for name, raw in assets.items()}
        )

    @property
    def renderer_sha256(self):
        """Readonly renderer byte pins for the host's code-only static snapshot."""
        return self._renderer_sha256

    def _current(self, principal, ref, input_version, revision, artifact_ref, digest):
        state = self.intake._load(principal, ref)
        _check(state["revision"] == revision, "stale-revision")
        _check(state["input_version"] == input_version, "stale-input-version")
        context = self.delivery._context(ref)
        _check(
            context[0] == principal and context[1] == state,
            "stage1-atlas-state-differs",
        )
        binding = context[2]
        brief, _, _ = self.intake._brief(state)
        artifact = state.get("stage1_canonical_package")
        _check(
            artifact is not None
            and artifact["artifact_ref"] == artifact_ref
            and artifact["manifest_sha256"] == digest
            and artifact["binding"] == _basis(binding)
            and binding["input_version"] == input_version
            and binding["brief_sha256"] == brief["sha256"],
            "stage1-atlas-artifact-binding-differs",
        )
        root = self.delivery._saved_artifact(principal, state, artifact, context)
        return state, root

    def read(
        self,
        credential,
        ref,
        *,
        input_version: int,
        revision: int,
        artifact_ref: str,
        manifest_sha256: str,
        check_deadline=None,
        file_ref=None,
        file_sha256=None,
    ):
        _check(
            check_deadline is None or callable(check_deadline),
            "stage1-atlas-deadline-check-invalid",
            400,
        )
        if check_deadline is not None:
            check_deadline()
        principal = self.intake._principal(credential)
        _check(
            _text(ref)
            and type(input_version) is int
            and input_version > 0
            and type(revision) is int
            and revision >= 0
            and _text(artifact_ref)
            and re.fullmatch(r"stage1-canonical-[0-9a-f]{32}", artifact_ref)
            and _hash(manifest_sha256)
            and (
                file_ref is None
                and file_sha256 is None
                or _hash(file_ref)
                and _hash(file_sha256)
            ),
            "stage1-atlas-request-invalid",
            400,
        )
        with self.intake._lock:
            if check_deadline is not None:
                check_deadline()
            try:
                args = (
                    principal,
                    ref,
                    input_version,
                    revision,
                    artifact_ref,
                    manifest_sha256,
                )
                state, root = self._current(*args)
                source = _source(root, manifest_sha256)
                if check_deadline is not None:
                    check_deadline()
                index, files = project_canonical_atlas(
                    root, ref, manifest_sha256, artifact_bytes=source
                )
                _check(
                    all(
                        sha(files[name]) == digest
                        for name, digest in self.renderer_sha256.items()
                    ),
                    "stage1-atlas-renderer-bytes-differ",
                )
                data = files["atlas-data.js"]
                _check(
                    len(data) <= MAX_PAYLOAD_BYTES
                    and data.startswith(PREFIX)
                    and data.endswith(b";\n"),
                    "stage1-atlas-payload-invalid",
                )
                payload = decode_json(data[len(PREFIX) : -2].decode("utf-8"))
                index_hash = sha(canonical(index))
                _check(
                    type(payload) is dict
                    and payload.get("index") == index
                    and payload.get("index_sha256") == index_hash,
                    "stage1-atlas-payload-binding-differs",
                )
                result = {
                    "schema": "ProjectStage1AtlasView/1",
                    "project_ref": ref,
                    "input_version": input_version,
                    "revision": revision,
                    "artifact_ref": artifact_ref,
                    "manifest_sha256": manifest_sha256,
                    "index_sha256": index_hash,
                }
                catalog = []
                selected = None
                for path, raw in sorted(files.items()):
                    if path not in BIB_FILES and not re.fullmatch(
                        r"wiki/[0-9a-f]{64}\.md", path
                    ):
                        continue
                    _check(len(raw) <= MAX_EXPORT_BYTES, "stage1-atlas-file-bound")
                    opaque = sha(canonical([artifact_ref, index_hash, path]))
                    item = {
                        "file_ref": opaque,
                        "sha256": sha(raw),
                        "path": path,
                        "mime": "text/markdown"
                        if path.endswith(".md")
                        else "application/x-bibtex",
                    }
                    catalog.append(item)
                    _check(
                        len(catalog) <= MAX_EXPORT_FILES, "stage1-atlas-catalog-bound"
                    )
                    if opaque == file_ref:
                        _check(
                            item["sha256"] == file_sha256,
                            "stage1-atlas-file-hash-differs",
                        )
                        selected = {
                            "file_ref": opaque,
                            "sha256": item["sha256"],
                            "mime": item["mime"],
                            "filename": path.rsplit("/", 1)[-1],
                            "content": raw.decode("utf-8"),
                        }
                if file_ref is not None:
                    _check(selected is not None, "stage1-atlas-file-unavailable", 404)
                    result["file"] = selected
                else:
                    result.update(payload=payload, files=catalog)
                if check_deadline is not None:
                    check_deadline()
                current, current_root = self._current(*args)
                _check(
                    current == state and current_root == root,
                    "stage1-atlas-state-differs",
                )
                _check(
                    _source(root, manifest_sha256) == source,
                    "stage1-atlas-source-bytes-differ",
                )
                _check(
                    len(
                        json.dumps(result, ensure_ascii=True, allow_nan=False).encode(
                            "utf-8"
                        )
                    )
                    <= MAX_RESPONSE,
                    "stage1-atlas-response-bound",
                )
                if check_deadline is not None:
                    check_deadline()
                return deepcopy(result)
            except SessionApiError:
                raise
            except (ValueError, OSError, KeyError, TypeError) as error:
                raise SessionApiError("stage1-atlas-source-binding-failed") from error

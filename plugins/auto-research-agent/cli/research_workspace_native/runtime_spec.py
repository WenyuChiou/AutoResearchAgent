"""Pinned private configuration only; no sessions, processes or model calls."""

from pathlib import Path
import re

from stage1_deliverable.common import identifier, private_output, reject_links, sha
from research_workspace_native.codex_probe import _decode, _file_sha, _path


class CompositionError(ValueError):
    """The exact composition was refused or cleanup remains unobserved."""


def _require(condition, reason):
    if not condition:
        raise CompositionError(reason)


def _hash(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


DENIED_THREAD_CONFIG = {
    **{
        f"features.{name}": False
        for name in (
            "apps",
            "enable_mcp_apps",
            "plugins",
            "hooks",
            "multi_agent",
            "shell_tool",
            "unified_exec",
            "skill_mcp_dependency_install",
            "code_mode",
            "code_mode_host",
            "view_image",
        )
    },
    "memories.generate_memories": False,
    "memories.use_memories": False,
    "web_search": "disabled",
}


def _thread_config(value):
    """Optional explicit deny-only overrides; never credentials or execution rights.

    MCP names must be collected and pinned by the trusted launcher. This checker
    cannot discover effective server config or prove that all tools are absent.
    """
    _require(
        isinstance(value, dict) and len(value) <= 78, "bounded thread config required"
    )
    _require(
        all(
            value.get(k) == v and type(value.get(k)) is type(v)
            for k, v in DENIED_THREAD_CONFIG.items()
        ),
        "required tool denials differ",
    )
    for key in value.keys() - DENIED_THREAD_CONFIG.keys():
        _require(
            isinstance(key, str)
            and re.fullmatch(r"mcp_servers\.[A-Za-z0-9_-]{1,128}\.enabled", key)
            and value[key] is False,
            "only named MCP denials are supported",
        )
    return dict(value)


def _read(path, limit=65536):
    path = _path(path)
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    _require(0 < len(raw) <= limit, "bounded pinned input required")
    return raw


def _load(path, expected):
    path = private_output(path)
    raw = _read(path)
    _require(_hash(expected) and sha(raw) == expected, "runtime spec bytes differ")
    spec = _decode(raw)
    fields = {
        "kind",
        "schema_version",
        "project_ref",
        "project_id",
        "principals",
        "source_root",
        "index_path",
        "index_sha256",
        "input_path",
        "input_version",
        "store_path",
        "executable",
        "executable_sha256",
        "model",
        "approval_policy",
        "limits",
        "permit_sha256",
    }
    _require(
        set(spec) in (fields, fields | {"thread_config"}), "runtime spec fields differ"
    )
    if "thread_config" in spec:
        _thread_config(spec["thread_config"])
    _require(
        spec["kind"] == "NativeAtlasRuntimeSpec" and spec["schema_version"] == "1.0.0",
        "unsupported runtime spec",
    )
    for name in ("project_ref", "model"):
        _require(
            isinstance(spec[name], str)
            and re.fullmatch("[A-Za-z0-9_.:-]{1,128}", spec[name]),
            "bounded runtime identity required",
        )
    identifier(spec["project_id"])
    _require(
        re.fullmatch("[A-Za-z0-9_-]{1,64}", spec["project_ref"]), "invalid project ref"
    )
    _require(
        isinstance(spec["principals"], list)
        and 1 <= len(spec["principals"]) <= 16
        and all(
            isinstance(p, str) and re.fullmatch("[A-Za-z0-9_.:-]{1,128}", p)
            for p in spec["principals"]
        )
        and len(set(spec["principals"])) == len(spec["principals"]),
        "pinned principal allowlist required",
    )
    for name in ("index_sha256", "input_version", "executable_sha256", "permit_sha256"):
        _require(_hash(spec[name]), "runtime hash required")
    _require(
        spec["approval_policy"] in {"untrusted", "on-request", "never"},
        "invalid approval policy",
    )
    root = private_output(_path(spec["source_root"], directory=True))
    _require(
        spec["source_root"] == root.resolve().as_posix(),
        "canonical source root required",
    )
    for name, digest in (
        ("index_path", "index_sha256"),
        ("input_path", "input_version"),
    ):
        selected = _path(spec[name])
        _require(
            selected.is_relative_to(root)
            and sha(_read(selected, 32 * 1024 * 1024)) == spec[digest],
            "pinned project input differs",
        )
    _require(
        _decode(_read(spec["index_path"], 32 * 1024 * 1024)).get("project_id")
        == spec["project_id"],
        "project identity differs from index",
    )
    executable = _path(spec["executable"])
    _require(
        executable.stat().st_size <= 512 * 1024 * 1024
        and _file_sha(executable) == spec["executable_sha256"],
        "executable bytes differ",
    )
    store = Path(spec["store_path"])
    _require(store.is_absolute(), "absolute store path required")
    store = private_output(store)
    _require(
        spec["store_path"] == store.resolve().as_posix(),
        "canonical store path required",
    )
    _require(
        store.parent.is_dir() and not store.exists(),
        "fresh private store required; no resume",
    )
    for suffix in ("", "-wal", "-shm", "-journal"):
        sidecar = Path(str(store) + suffix)
        reject_links(sidecar)
        _require(not sidecar.exists(), "fresh store and sidecars required; no resume")
    _require(
        not store.parent.resolve().is_relative_to(root)
        and not root.is_relative_to(store.parent.resolve()),
        "source and runtime storage overlap",
    )
    limits = spec["limits"]
    bounds = {
        "lifetime_seconds": 600,
        "max_stream_bytes": 1048576,
        "max_text_bytes": 16384,
        "max_starts": 128,
        "timeout_seconds": 30,
    }
    _require(
        isinstance(limits, dict)
        and set(limits) == set(bounds)
        and all(
            type(limits[k]) is int and 1 <= limits[k] <= maximum
            for k, maximum in bounds.items()
        ),
        "bounded runtime limits required",
    )
    _require(
        limits["timeout_seconds"] <= limits["lifetime_seconds"], "timeout exceeds lease"
    )
    return path, expected, spec


def _load_all(registrations):
    _require(
        isinstance(registrations, (list, tuple)) and 1 <= len(registrations) <= 16,
        "bounded pinned registrations required",
    )
    _require(
        all(isinstance(row, (tuple, list)) and len(row) == 2 for row in registrations),
        "pinned registration pairs required",
    )
    loaded = [_load(*row) for row in registrations]
    for field in ("project_ref", "project_id", "store_path", "source_root"):
        values = [row[2][field].casefold() for row in loaded]
        _require(len(set(values)) == len(values), "duplicate runtime binding")
    roots = [Path(row[2]["source_root"]) for row in loaded]
    for _, _, spec in loaded:
        storage = Path(spec["store_path"]).parent
        _require(
            all(
                not storage.is_relative_to(root) and not root.is_relative_to(storage)
                for root in roots
            ),
            "cross-project source and storage overlap",
        )
    return loaded

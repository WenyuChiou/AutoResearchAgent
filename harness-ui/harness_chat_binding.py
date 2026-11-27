"""Strict file binding for the runtime actually loaded by a trusted host.

This module only reads local files. It does not grant a chat lease, open a
database, start Codex, or establish account identity. The caller supplies the
complete module-name to ``__file__`` mapping; a manifest cannot choose a
different historical source tree merely because its files have matching bytes.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from collections.abc import Mapping


MANIFEST_LIMIT = 64 * 1024
EXECUTABLE_LIMIT = 512 * 1024 * 1024
CONFIG_LIMIT = 1024 * 1024
MODULE_LIMIT = 8 * 1024 * 1024
MODULE_COUNT_LIMIT = 128
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MODULE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z")


class BindingError(ValueError):
    """A bounded, content-free binding validation error."""


def _require(condition, code):
    if not condition:
        raise BindingError(code)


def _pin(value):
    _require(type(value) is str and _SHA.fullmatch(value) is not None,
             "chat-binding-sha256-invalid")
    return value


def _path(value):
    _require(isinstance(value, (str, os.PathLike)) and not isinstance(value, bytes),
             "chat-binding-path-invalid")
    try:
        value = Path(value)
        _require(value.is_absolute(), "chat-binding-absolute-path-required")
        resolved = value.resolve(strict=True)
        _require(resolved.is_file(), "chat-binding-regular-file-required")
        return value, resolved
    except BindingError:
        raise
    except (OSError, ValueError, TypeError, RuntimeError):
        raise BindingError("chat-binding-file-unavailable") from None


def _identity(value):
    return (value.st_dev, value.st_ino, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


@dataclass(frozen=True)
class FileObservation:
    """File location, digest and size only; never file contents."""

    path: str
    sha256: str
    bytes: int
    identity: tuple


def _observe(value, limit, *, expected=None, keep_bytes=False):
    supplied, resolved = _path(value)
    if expected is not None:
        actual, actual_resolved = _path(expected)
        try:
            same = resolved == actual_resolved or supplied.samefile(actual)
        except OSError:
            same = False
        _require(same, "chat-binding-actual-path-differs")
    try:
        initial = supplied.stat()
        _require(stat.S_ISREG(initial.st_mode), "chat-binding-regular-file-required")
        _require(initial.st_size <= limit, "chat-binding-file-too-large")
        digest, length = hashlib.sha256(), 0
        chunks = [] if keep_bytes else None
        with supplied.open("rb") as source:
            opened = os.fstat(source.fileno())
            _require(_identity(initial) == _identity(opened), "chat-binding-file-changed")
            while True:
                block = source.read(min(1024 * 1024, limit + 1 - length))
                if not block:
                    break
                length += len(block)
                _require(length <= limit, "chat-binding-file-too-large")
                digest.update(block)
                if chunks is not None:
                    chunks.append(block)
            final = os.fstat(source.fileno())
        _require(_identity(initial) == _identity(final) == _identity(supplied.stat()),
                 "chat-binding-file-changed")
        _require(supplied.resolve(strict=True) == resolved, "chat-binding-file-changed")
        if expected is not None:
            _require(supplied.samefile(actual), "chat-binding-actual-path-differs")
        _require(length == initial.st_size, "chat-binding-file-changed")
        observation = FileObservation(str(resolved), digest.hexdigest(), length,
                                      _identity(final))
        return observation, b"".join(chunks) if chunks is not None else None
    except BindingError:
        raise
    except (OSError, ValueError, TypeError, RuntimeError):
        raise BindingError("chat-binding-file-unavailable") from None


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "chat-binding-json-duplicate-key")
        result[key] = value
    return result


def _constant(_value):
    raise BindingError("chat-binding-json-nonfinite-number")


def _descriptor(raw):
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                            parse_constant=_constant)
    except BindingError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise BindingError("chat-binding-json-invalid") from None
    _require(type(result) is dict and set(result) == {
        "kind", "version", "executable", "config", "modules"},
        "chat-binding-manifest-fields-differ")
    _require(result["kind"] == "V9ChatRuntimeBinding"
             and type(result["version"]) is int and result["version"] == 1,
             "chat-binding-manifest-version-invalid")
    return result


def _entry(value):
    _require(type(value) is dict and set(value) == {"path", "sha256"},
             "chat-binding-file-fields-differ")
    _require(type(value["path"]) is str, "chat-binding-path-invalid")
    _pin(value["sha256"])
    return value


def _actual_modules(value):
    _require(isinstance(value, Mapping) and 1 <= len(value) <= MODULE_COUNT_LIMIT,
             "chat-binding-runtime-closure-required")
    _require(all(type(name) is str and _MODULE.fullmatch(name) for name in value),
             "chat-binding-module-name-invalid")
    return tuple((name, str(_path(value[name])[0])) for name in sorted(value))


def _validate(path, pin, actual_modules, expected_executable, expected_config):
    manifest, raw = _observe(path, MANIFEST_LIMIT, keep_bytes=True)
    _require(manifest.sha256 == _pin(pin), "chat-binding-manifest-pin-differs")
    data = _descriptor(raw)
    _require(type(data["modules"]) is dict
             and set(data["modules"]) == {name for name, _ in actual_modules},
             "chat-binding-runtime-closure-differs")
    observations = []
    for name, key, expected, limit in (
        ("executable", "executable", expected_executable, EXECUTABLE_LIMIT),
        ("config", "config", expected_config, CONFIG_LIMIT),
    ):
        entry = _entry(data[key])
        observed, _ = _observe(entry["path"], limit, expected=expected)
        _require(observed.sha256 == entry["sha256"], "chat-binding-file-pin-differs")
        observations.append((name, observed))
    for name, expected in actual_modules:
        entry = _entry(data["modules"][name])
        observed, _ = _observe(entry["path"], MODULE_LIMIT, expected=expected)
        _require(observed.sha256 == entry["sha256"], "chat-binding-file-pin-differs")
        observations.append((name, observed))
    # A changing descriptor cannot switch the expected closure partway through.
    again, _ = _observe(path, MANIFEST_LIMIT)
    _require(again == manifest, "chat-binding-manifest-changed")
    return manifest, tuple(observations)


@dataclass(frozen=True)
class RuntimeBinding:
    """Frozen local observation, suitable for repeated file verification.

    ``verify`` is required immediately before every native launch. Callers must
    pass a fresh host-derived mapping if loaded module paths may have changed.
    Verification does not attest loaded memory or close a later launch race.
    """

    manifest_path: str
    manifest_sha256: str
    actual_modules: tuple
    expected_executable: str
    expected_config: str
    manifest: FileObservation
    files: tuple

    def verify(self, actual_modules=None, expected_executable=None,
               expected_config=None):
        modules = (self.actual_modules if actual_modules is None
                   else _actual_modules(actual_modules))
        executable = (self.expected_executable if expected_executable is None
                      else str(_path(expected_executable)[0]))
        config = (self.expected_config if expected_config is None
                  else str(_path(expected_config)[0]))
        manifest, files = _validate(self.manifest_path, self.manifest_sha256,
                                    modules, executable, config)
        _require(manifest == self.manifest and files == self.files,
                 "chat-binding-observation-changed")
        return self


def load_binding(path, pin, actual_modules, expected_executable, expected_config):
    """Validate an independently pinned manifest against the actual host paths.

    The host must build ``actual_modules`` from its explicit runtime closure,
    rather than from manifest keys. Every member is required; extras fail.
    Expected executable/config paths come from host activation inputs.
    """
    pin = _pin(pin)
    modules = _actual_modules(actual_modules)
    manifest_path = str(_path(path)[0])
    executable = str(_path(expected_executable)[0])
    config = str(_path(expected_config)[0])
    manifest, files = _validate(manifest_path, pin, modules, executable, config)
    return RuntimeBinding(manifest_path, pin, modules, executable, config,
                          manifest, files)

"""Explicit read-only verification of supported, externally pinned old builds.

Old source is data: it is hashed, never imported or executed. No execution or
resume entrypoint accepts this binding. Pins must come from the calling host,
separately from the subject's manifest and capture receipts.
"""

from dataclasses import dataclass
import hashlib
from importlib import metadata
import os
from pathlib import Path
import re
import stat
import sys

from stage2_common import Stage2Error, canonical_hash


_CLI = Path(__file__).resolve().parents[1]
_REGISTRY = _CLI.parent / "references/stage2-historical-verifier.v1.json"
_KEYS = {
    "kind",
    "schema_version",
    "producer_cli_root",
    "producer_cli_sha256",
    "producer_path_convention",
    "verifier_build_sha256",
    "verifier_runtime_sha256",
}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _regular(path, *, directory=False):
    value = os.lstat(path)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        stat.S_ISLNK(value.st_mode)
        or (reparse and getattr(value, "st_file_attributes", 0) & reparse)
        or not (
            stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode)
        )
    ):
        raise Stage2Error("historical-verifier-unsafe-path")


def _source_inventory(root):
    root = Path(root)
    if not root.is_absolute() or root != root.resolve():
        raise Stage2Error("historical-verifier-noncanonical-root")
    _regular(root, directory=True)
    for parent in root.parents:
        _regular(parent, directory=True)
    rows = {}
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in directories:
            _regular(Path(directory) / name, directory=True)
        for name in files:
            if name.endswith(".py"):
                path = Path(directory) / name
                _regular(path)
                rows[path.relative_to(root).as_posix()] = _sha(path)
    if not rows:
        raise Stage2Error("historical-verifier-empty-build")
    return rows


def _dependency_distributions():
    from jsonschema import _format

    names = {
        "jsonschema",
        "jsonschema-specifications",
        "referencing",
        "rpds-py",
        "attrs",
        "typing-extensions",
        "idna",
        "rfc3339-validator",
        "six",
    }
    owners = metadata.packages_distributions()
    # Include installed optional format providers actually used by jsonschema.
    for value in vars(_format).values():
        module = getattr(value, "__module__", None) or getattr(value, "__name__", "")
        top = module.split(".")[0]
        if top in sys.modules and top not in sys.stdlib_module_names:
            distributions = owners.get(top)
            if not distributions:
                raise Stage2Error("historical-verifier-dependency-owner-missing")
            names.update(distributions)
    pending = list(names)
    while pending:
        distribution = metadata.distribution(pending.pop())
        for requirement in distribution.requires or ():
            package, _, marker = requirement.partition(";")
            if re.search(r"\bextra\b", marker):
                continue
            match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", package.strip())
            if match is None:
                raise Stage2Error("historical-verifier-dependency-requirement-invalid")
            name = re.sub(r"[-_.]+", "-", match.group()).lower()
            if name not in names:
                # A supported verifier conservatively pins all non-extra
                # dependencies, including installed conditional dependencies.
                metadata.distribution(name)
                names.add(name)
                pending.append(name)
    return names, owners


def _distribution_inventory(distribution):
    files = distribution.files
    if not files:
        raise Stage2Error("historical-verifier-dependency-inventory-missing")
    rows, paths = {}, set()
    for entry in files:
        # Resource files may have no extension (e.g. schema vocabularies).
        if str(entry).endswith(".pyc") or "__pycache__" in entry.parts:
            continue
        located = Path(distribution.locate_file(entry))
        _regular(located)
        for parent in located.parents:
            _regular(parent, directory=True)
        path = located.resolve()
        rows[str(entry)] = _sha(path)
        paths.add(path)
    if not rows:
        raise Stage2Error("historical-verifier-dependency-code-missing")
    return rows, paths


def _runtime_binding():
    names, owners = _dependency_distributions()
    packages, paths = {}, set()
    for name in sorted(names):
        distribution = metadata.distribution(name)
        rows, distribution_paths = _distribution_inventory(distribution)
        paths.update(distribution_paths)
        packages[name] = {"version": distribution.version, "files": rows}
    roots = {
        root
        for root, distributions in owners.items()
        if any(re.sub(r"[-_.]+", "-", name).lower() in names for name in distributions)
    }
    for name, module in tuple(sys.modules.items()):
        if module is None or name.split(".")[0] not in roots:
            continue
        path = getattr(module, "__file__", None)
        if path and Path(path).resolve() not in paths:
            raise Stage2Error("historical-verifier-mixed-dependency-import")
        for directory in getattr(module, "__path__", ()):
            directory = Path(directory).resolve()
            if not any(directory in path.parents for path in paths):
                raise Stage2Error("historical-verifier-mixed-dependency-import")
    return {
        "python": _sha(Path(sys.executable)),
        "version": sys.version,
        "dependencies": packages,
    }


def inspect_verifier_build():
    """Return current host pins for separate retention before verification."""
    rows = _source_inventory(_CLI)
    # Reject a mixed import path even when both trees are individually valid.
    for module in tuple(sys.modules.values()):
        name = getattr(module, "__name__", "")
        path = getattr(module, "__file__", None)
        top = name.split(".")[0]
        if path and (top + ".py" in rows or top + "/__init__.py" in rows):
            expected = _CLI / Path(*name.split("."))
            candidates = {expected.with_suffix(".py"), expected / "__init__.py"}
            if Path(path).resolve() not in candidates:
                raise Stage2Error("historical-verifier-mixed-import-build")
    _regular(_REGISTRY)
    return {
        "verifier_build_sha256": canonical_hash(
            {"files": rows, "registry_sha256": _sha(_REGISTRY)}
        ),
        "verifier_runtime_sha256": canonical_hash(_runtime_binding()),
    }


@dataclass(frozen=True)
class HistoricalBuild:
    controller_sha256: str
    extraction_adapter_sha256: str
    receipt: dict


def resolve_historical_binding(binding):
    """Validate caller-supplied pins; subject self-attestation is insufficient."""
    import json

    try:
        if (
            not isinstance(binding, dict)
            or set(binding) != _KEYS
            or (
                binding["kind"] != "Stage2HistoricalVerifierBinding"
                or binding["schema_version"] != "1.0.0"
            )
        ):
            raise Stage2Error("historical-verifier-binding-invalid")
        convention = binding["producer_path_convention"]
        if convention not in ("posix", "windows"):
            raise Stage2Error("historical-verifier-path-convention-invalid")
        for key in _KEYS - {
            "kind",
            "schema_version",
            "producer_cli_root",
            "producer_path_convention",
        }:
            value = binding[key]
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)
            ):
                raise Stage2Error("historical-verifier-pin-invalid")
        host = inspect_verifier_build()
        if any(host[key] != binding[key] for key in host):
            raise Stage2Error("historical-verifier-host-build-changed")
        rows = _source_inventory(binding["producer_cli_root"])
        producer_sha = canonical_hash(rows)
        if producer_sha != binding["producer_cli_sha256"]:
            raise Stage2Error("historical-verifier-producer-build-changed")
        registry = json.loads(_REGISTRY.read_text(encoding="utf-8"))
        supported = registry["supported_producers"].get(producer_sha)
        if supported is None:
            raise Stage2Error("historical-verifier-unsupported-producer-build")
        controller_sha = rows["stage2_live/controller.py"]
        adapter_sha = canonical_hash(
            {
                name if convention == "posix" else name.replace("/", "\\"): digest
                for name, digest in rows.items()
                if name == "stage2_live/extraction.py"
                or (name.startswith("stage2_ideation/") and name.count("/") == 1)
            }
        )
        if (
            controller_sha != supported["controller_sha256"]
            or adapter_sha != supported["extraction_adapter_sha256"][convention]
        ):
            raise Stage2Error("historical-verifier-supported-build-mismatch")
        return HistoricalBuild(
            controller_sha,
            adapter_sha,
            {
                "kind": "Stage2HistoricalVerification",
                "schema_version": "1.0.0",
                "producer_cli_sha256": producer_sha,
                "producer_path_convention": convention,
                **host,
                "compatibility_registry_sha256": _sha(_REGISTRY),
                "producer_merge_sha": supported["merge_sha"],
                "read_only": True,
                "subject_upgraded": False,
                "formal_ready": False,
            },
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        metadata.PackageNotFoundError,
    ) as error:
        raise Stage2Error(f"historical-verifier-evidence-invalid: {error}") from error


def verify_historical_environment_capture(
    capture_dir, receipt, preflight, inventory_receipt, *, historical_binding
):
    """Use the corrected host selector without altering a frozen subject build."""
    from .environment import verify_environment_capture

    build = resolve_historical_binding(historical_binding)
    result = verify_environment_capture(
        capture_dir, receipt, preflight, inventory_receipt
    )
    # Recheck pins after the read-only operation; never rewrite the old receipt.
    if resolve_historical_binding(historical_binding) != build:
        raise Stage2Error("historical-verifier-build-changed-during-verification")
    verification = {
        "environment": result,
        "historical_verification": build.receipt,
        "native_capture_receipt": receipt,
        "preflight_capture_receipt": preflight["receipt"],
        "preflight_input_sha256": canonical_hash(preflight),
        "inventory_receipt_sha256": canonical_hash(inventory_receipt),
    }
    return {**verification, "verification_sha256": canonical_hash(verification)}

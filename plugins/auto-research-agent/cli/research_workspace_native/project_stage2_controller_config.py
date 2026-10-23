"""Hash-pinned local bootstrap for existing Stage 2 controllers, with no dispatch."""

import hashlib
from pathlib import Path

from stage2_live.native_prerequisites import load_native_prerequisites
from .project_stage2_controller import ProjectStage2ControllerDriver, _raw
from .session_api import _check
from .transport import _decode


def _document(path, expected_sha256):
    _check(Path(path).is_absolute(), "stage2-controller-configuration-path")
    raw = _raw(path)
    _check(
        hashlib.sha256(raw).hexdigest() == expected_sha256,
        "stage2-controller-configuration-hash-differs",
    )
    return _decode(raw.decode("utf-8"))


def load_stage2_controllers(service, credential, path, expected_sha256):
    """Read trusted config and current bindings; never activate or run a model.

    The browser cannot submit executable paths, policies or this configuration.
    Per-project activation, source, runtime and original budget are rechecked by
    the existing driver immediately before a separately requested continuation.
    """
    config = _document(path, expected_sha256)
    _check(
        type(config) is dict
        and set(config) == {"kind", "schema_version", "bindings"}
        and config["kind"] == "ProjectStage2ControllerConfiguration"
        and config["schema_version"] == "1.0.0",
        "stage2-controller-configuration-version",
    )
    rows = config["bindings"]
    _check(
        type(rows) is list and 1 <= len(rows) <= 32,
        "stage2-controller-configuration-count",
    )
    result = {}
    fields = {
        "project_ref",
        "spec_path",
        "spec_sha256",
        "controller_root",
        "delivery_root",
        "preparation_path",
        "preparation_sha256",
    }
    for row in rows:
        _check(
            type(row) is dict and set(row) == fields,
            "stage2-controller-configuration-row",
        )
        ref = row["project_ref"]
        _check(
            type(ref) is str and ref not in result,
            "stage2-controller-configuration-duplicate",
        )
        service.intake.read(credential, ref)
        binding = service.binding(ref)
        spec = _document(row["spec_path"], row["spec_sha256"])
        _check(type(spec) is dict, "stage2-controller-configuration-spec")
        for key in ("controller_root", "delivery_root", "preparation_path"):
            _check(
                type(row[key]) is str and Path(row[key]).is_absolute(),
                "stage2-controller-configuration-path",
            )
        handler = load_native_prerequisites(
            row["preparation_path"],
            row["preparation_sha256"],
            workflow=binding["workflow_root"],
            spec=spec,
        )
        result[ref] = ProjectStage2ControllerDriver(
            service,
            spec=spec,
            controller_dir=row["controller_root"],
            delivery_dir=row["delivery_root"],
            prerequisite_handler=handler,
        )
    return result

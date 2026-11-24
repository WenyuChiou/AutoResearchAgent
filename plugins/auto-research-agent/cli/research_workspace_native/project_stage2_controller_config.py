"""Hash-pinned local bootstrap for existing Stage 2 controllers, with no dispatch."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from stage2_common import Stage2Error, canonical_hash
from stage2_live import native_prerequisites
from stage2_live.preparation import _guard as _guard_preparation
from stage2_live.preparation import _raw as _raw_preparation
from stage2_live.preparation import implementation_pins
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


def _load_prerequisites(
    path, expected_sha256, *, workflow, spec, allow_readback_without_admission
):
    try:
        return native_prerequisites.load_native_prerequisites(
            path, expected_sha256, workflow=workflow, spec=spec
        )
    except Stage2Error as error:
        if not allow_readback_without_admission or error.args != (
            "native-prerequisite-original-admission-required",
        ):
            raise

    # The native loader checked configuration, policy and output placement
    # before reporting unavailable admission. Reopen the same pinned bytes.
    raw = _raw_preparation(path)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise Stage2Error("native-prerequisite-configuration-hash-differs")
    configuration = json.loads(raw)
    if _guard_preparation(configuration["output_root"]).exists():
        # If provider output appeared meanwhile, verify its binding and budget.
        verified = native_prerequisites.load_native_prerequisites(
            path, expected_sha256, workflow=workflow, spec=spec
        )
        return SimpleNamespace(
            identity=verified.identity, admission_context=verified.admission_context
        )

    # Match the original provider identity for retained-record verification.
    # This descriptor has no prepare method and cannot admit a new run.
    binding = {
        "configuration_sha256": canonical_hash(configuration),
        "guard_implementations": implementation_pins(),
        "provider_sha256": hashlib.sha256(
            Path(native_prerequisites.__file__).read_bytes()
        ).hexdigest(),
    }
    return SimpleNamespace(
        identity="native-prerequisites-" + canonical_hash(binding),
        admission_context=configuration.get("admission_context"),
    )


def load_stage2_controllers(
    service,
    credential,
    path,
    expected_sha256,
    *,
    allow_readback_without_admission=False,
):
    """Read trusted config and current bindings; never activate or run a model.

    The browser cannot submit executable paths, policies or this configuration.
    Per-project activation, source, runtime and original budget are rechecked by
    the existing driver immediately before a separately requested continuation.
    Wiki may opt into retaining the pinned readback identity without live admission.
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
        handler = _load_prerequisites(
            row["preparation_path"],
            row["preparation_sha256"],
            workflow=binding["workflow_root"],
            spec=spec,
            allow_readback_without_admission=allow_readback_without_admission,
        )
        result[ref] = ProjectStage2ControllerDriver(
            service,
            spec=spec,
            controller_dir=row["controller_root"],
            delivery_dir=row["delivery_root"],
            prerequisite_handler=handler,
        )
    return result

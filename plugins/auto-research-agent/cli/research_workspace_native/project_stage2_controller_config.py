"""Hash-pinned local bootstrap for existing Stage 2 controllers, with no dispatch."""

import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace

from stage1_deliverable.common import private_output, safe_path
from stage2_common import Stage2Error, canonical_hash
from stage2_live import native_prerequisites
from stage2_live.preparation import _guard as _guard_preparation
from stage2_live.preparation import _raw as _raw_preparation
from stage2_live.preparation import implementation_pins
from stage2_workflow import inspect_workflow
from .project_stage2_controller import ProjectStage2ControllerDriver, _raw
from .session_api import _check, _hash
from .transport import _decode


_PATHS = {"spec_path", "controller_root", "delivery_root", "preparation_path"}
_ROW = _PATHS | {"spec_sha256", "preparation_sha256"}


def _document(path, expected_sha256):
    _check(Path(path).is_absolute(), "stage2-controller-configuration-path")
    raw = _raw(path)
    _check(
        hashlib.sha256(raw).hexdigest() == expected_sha256,
        "stage2-controller-configuration-hash-differs",
    )
    return _decode(raw.decode("utf-8"))


class Stage2ControllerProfile:
    """Trusted path templates under a private, operator-pinned project parent."""

    def __init__(self, path, expected_sha256):
        self.path, self.sha256 = path, expected_sha256
        self._profile()

    def _profile(self):
        value = _document(self.path, self.sha256)
        _check(
            type(value) is dict
            and set(value)
            == _ROW
            | {"kind", "schema_version", "project_parent", "max_projects", "policy_ref"}
            and value["kind"] == "ProjectStage2ControllerProfile"
            and value["schema_version"] == "1.0.0"
            and type(value["max_projects"]) is int
            and 1 <= value["max_projects"] <= 32
            and type(value["project_parent"]) is str
            and Path(value["project_parent"]).is_absolute()
            and _hash(value["spec_sha256"])
            and _hash(value["preparation_sha256"])
            and value["policy_ref"]
            == {
                "route": "stage2-general-v3/daily_v3",
                "packet_profile": "scientific-v3",
            },
            "stage2-controller-profile-invalid",
        )
        parent = private_output(value["project_parent"])
        for key in _PATHS:
            safe_path(parent, value[key])
        return value, parent

    def resolve(self, ref):
        _check(
            type(ref) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", ref) is not None,
            "stage2-controller-profile-project-invalid",
        )
        value, parent = self._profile()
        root = safe_path(parent, ref)
        row = {**{key: value[key] for key in _ROW}, "project_ref": ref}
        for key in _PATHS:
            row[key] = str(private_output(safe_path(root, value[key])))
        paths = [Path(row[key]) for key in _PATHS]
        _check(
            all(
                left != right
                and left not in right.parents
                and right not in left.parents
                for index, left in enumerate(paths)
                for right in paths[index + 1 :]
            ),
            "stage2-controller-profile-paths-overlap",
        )
        return row, value["policy_ref"], value["max_projects"]


def _load_prerequisites(
    path,
    expected_sha256,
    *,
    workflow,
    spec,
    allow_readback_without_admission,
    profile_binding=None,
):
    def configuration():
        raw = _raw_preparation(path)
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise Stage2Error("native-prerequisite-configuration-hash-differs")
        value = (
            json.loads(raw) if profile_binding is None else _decode(raw.decode("utf-8"))
        )
        if profile_binding is not None:
            value["output_root"] = str(
                private_output(safe_path(Path(path).parent, value["output_root"]))
            )
            context = value.get("admission_context")
            _check(
                context is None
                or (
                    type(context) is dict
                    and all(
                        type(context.get(key)) is type(expected)
                        and context[key] == expected
                        for key, expected in profile_binding.items()
                    )
                ),
                "stage2-controller-admission-project-differs",
            )
        return value

    def load():
        if profile_binding is not None:
            return native_prerequisites.NativePrerequisiteHandler(
                workflow, spec, configuration()
            )
        return native_prerequisites.load_native_prerequisites(
            path, expected_sha256, workflow=workflow, spec=spec
        )

    try:
        return load()
    except Stage2Error as error:
        if not allow_readback_without_admission or error.args != (
            "native-prerequisite-original-admission-required",
        ):
            raise

    # The native loader checked configuration, policy and output placement
    # before reporting unavailable admission. Reopen the same pinned bytes.
    config = configuration()
    if _guard_preparation(config["output_root"]).exists():
        # If provider output appeared meanwhile, verify its binding and budget.
        verified = load()
        return SimpleNamespace(
            identity=verified.identity, admission_context=verified.admission_context
        )

    # Match the original provider identity for retained-record verification.
    # This descriptor has no prepare method and cannot admit a new run.
    binding = {
        "configuration_sha256": canonical_hash(config),
        "guard_implementations": implementation_pins(),
        "provider_sha256": hashlib.sha256(
            Path(native_prerequisites.__file__).read_bytes()
        ).hexdigest(),
    }
    return SimpleNamespace(
        identity="native-prerequisites-" + canonical_hash(binding),
        admission_context=config.get("admission_context"),
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
    for row in rows:
        _check(
            type(row) is dict and set(row) == _ROW | {"project_ref"},
            "stage2-controller-configuration-row",
        )
        ref = row["project_ref"]
        _check(
            type(ref) is str and ref not in result,
            "stage2-controller-configuration-duplicate",
        )
        service.intake.read(credential, ref)
        result[ref] = load_stage2_controller(
            service,
            service.binding(ref),
            row,
            allow_readback_without_admission=allow_readback_without_admission,
        )
    return result


def load_stage2_controller(
    service, binding, row, *, allow_readback_without_admission, profile_paths=False
):
    spec = _document(row["spec_path"], row["spec_sha256"])
    _check(type(spec) is dict, "stage2-controller-configuration-spec")
    if profile_paths:
        workflow = inspect_workflow(
            binding["workflow_root"], binding["workflow_head_sha256"]
        )
        initial = workflow["snapshots"][0]
        for key, expected in (
            ("confirmed_brief_sha256", workflow["manifest"]["brief_sha256"]),
            ("base_snapshot_sha256", initial["event"]["payload"]["snapshot_sha256"]),
        ):
            _check(
                key in spec and spec[key] in (None, expected),
                "stage2-controller-profile-spec-differs",
            )
            spec[key] = expected
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
        profile_binding=(
            {
                **{
                    key: binding[key]
                    for key in ("project_id", "input_version", "brief_sha256")
                },
                "project_ref": row["project_ref"],
            }
            if profile_paths
            else None
        ),
    )
    return ProjectStage2ControllerDriver(
        service,
        spec=spec,
        controller_dir=row["controller_root"],
        delivery_dir=row["delivery_root"],
        prerequisite_handler=handler,
    )

"""One pinned configuration entry point; references never create objects."""

from copy import deepcopy
from pathlib import Path

from research_workspace.interface_config import compile_config
from stage1_deliverable.common import sha

from .http import _decode
from .maintenance_inbox import MaintenanceInbox


class HostRegistry:
    """Trusted embedding code supplies existing objects, never paths or factories."""

    def __init__(self, *, runtimes=None, inboxes=None):
        self.runtimes = dict(runtimes or {})
        self.inboxes = dict(inboxes or {})
        if any(
            isinstance(value, (str, bytes, Path)) or callable(value)
            for value in self.runtimes.values()
        ):
            raise ValueError("registered runtime object required")
        if any(
            not isinstance(value, MaintenanceInbox) for value in self.inboxes.values()
        ):
            raise ValueError("registered inbox object required")


def load_config(
    config_path,
    expected_sha256,
    *,
    contract_path=None,
    expected_contract_sha256=None,
    schema_path=None,
    expected_schema_sha256=None,
):
    from .atlas_host import _read, _snapshot_views
    from stage1_deliverable.common import private_output

    raw = _read(private_output(Path(config_path)), 256 * 1024)
    if sha(raw) != expected_sha256:
        raise ValueError("host configuration binding differs")
    value = _decode(raw.decode("utf-8"))
    if isinstance(value, dict) and set(value) == {"views"}:
        compiled = dict(
            config_kind="legacy",
            host_config=value,
            presentation=dict(language="en", density="comfortable"),
            server_object_requests=dict(
                native=dict(mode="disabled"), maintenance=dict(mode="disabled")
            ),
        )
    else:
        if not all(
            (
                contract_path,
                expected_contract_sha256,
                schema_path,
                expected_schema_sha256,
            )
        ):
            raise ValueError(
                "semantic configuration requires external interface/schema pins"
            )
        compiled = compile_config(
            raw,
            expected_sha256=expected_sha256,
            contract_raw=_read(Path(contract_path), 128 * 1024),
            expected_contract_sha256=expected_contract_sha256,
            schema_raw=_read(Path(schema_path), 128 * 1024),
            expected_schema_sha256=expected_schema_sha256,
        )
        compiled["config_kind"] = "semantic"
    files, views = _snapshot_views(compiled["host_config"])
    return dict(compiled, files=files, views=views)


def create_host(config, *, registry=None, **options):
    from .atlas_host import AtlasHost

    registry = HostRegistry() if registry is None else registry
    if not isinstance(registry, HostRegistry):
        raise ValueError("trusted host registry required")
    if (
        config["config_kind"] == "semantic"
        and options.get("maintenance_db") is not None
    ):
        raise ValueError("semantic configuration requires a registered inbox")
    requests = config["server_object_requests"]
    native = requests["native"]
    maintenance = requests["maintenance"]
    runtime = registry.runtimes.get(native.get("runtime_ref"))
    inbox = registry.inboxes.get(maintenance.get("inbox_ref"))
    if maintenance["mode"] == "disabled":
        inbox = None
    if native["mode"] == "disabled":
        runtime = None
    # The persistent native connection is delivered by the next integration PR.
    state = dict(
        native="disabled"
        if native["mode"] == "disabled"
        else ("registered-unconnected" if runtime is not None else "unavailable"),
        maintenance="disabled"
        if maintenance["mode"] == "disabled"
        else ("record-only" if inbox is not None else "unavailable"),
    )
    return AtlasHost(
        files=config["files"],
        views=config["views"],
        presentation=deepcopy(config["presentation"]),
        capability_state=state,
        maintenance_inbox=inbox,
        **options,
    )

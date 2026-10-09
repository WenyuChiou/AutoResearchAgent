"""Compile pinned server configuration without creating or authorizing a runtime.

The output keeps AtlasHost's existing {views} format. Object references request
lookup in a trusted server registry; they are never imports, paths or permits.
The caller still runs load_views and actual owner/API checks before hosting.
"""

from copy import deepcopy
from hashlib import sha256
import json

from jsonschema import Draft202012Validator


def _reject_constant(value):
    raise ValueError("non-finite JSON value")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _read(raw, expected, limit):
    if (
        not isinstance(raw, bytes)
        or not 0 < len(raw) <= limit
        or not isinstance(expected, str)
        or len(expected) != 64
        or sha256(raw).hexdigest() != expected
    ):
        raise ValueError("configuration artifact binding differs")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("valid UTF-8 JSON required") from exc
    if not isinstance(value, dict):
        raise ValueError("configuration object required")
    return value


def compile_config(
    raw,
    *,
    expected_sha256,
    contract_raw,
    expected_contract_sha256,
    schema_raw,
    expected_schema_sha256,
):
    """Pure validation/translation; no files, callbacks, native I/O or dispatch.

    Config/native mode is a declaration, not proof of an admitted registration.
    Private manifests and their inventory still require AtlasHost.load_views.
    Presentation preferences are separate from the semantic data contract.
    """
    contract = _read(contract_raw, expected_contract_sha256, 128 * 1024)
    if (
        contract.get("kind") != "WorkspaceInterfaceContract"
        or contract.get("contract_version") != "1.0.0"
    ):
        raise ValueError("unsupported interface contract")
    schema = _read(schema_raw, expected_schema_sha256, 128 * 1024)
    if schema.get("title") != "WorkspaceUiConfig v1":
        raise ValueError("unsupported configuration schema")
    # No externally resolved refs or vocabularies are allowed by this compiler.
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise ValueError("unsupported schema dialect")

    def local_only(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"$ref", "$dynamicRef"} and (
                    not isinstance(item, str) or not item.startswith("#/")
                ):
                    raise ValueError("external schema references forbidden")
                local_only(item)
        elif isinstance(value, list):
            for item in value:
                local_only(item)

    local_only(schema)
    Draft202012Validator.check_schema(schema)
    config = _read(raw, expected_sha256, 256 * 1024)
    errors = list(Draft202012Validator(schema).iter_errors(config))
    if errors:
        raise ValueError("invalid WorkspaceUiConfig")
    if config["interface_sha256"] != expected_contract_sha256:
        raise ValueError("configuration interface differs")
    refs = [row["ref"] for row in config["views"]]
    if len(refs) != len(set(refs)):
        raise ValueError("duplicate case reference")
    # Path validation/inventory remains centralized in load_views, not copied.
    native = config["native"]
    maintenance = config["maintenance"]
    result = {
        "kind": "WorkspaceUiCompiledConfig",
        "schema_version": "1.0.0",
        "interface_sha256": expected_contract_sha256,
        "config_sha256": expected_sha256,
        "host_config": {"views": deepcopy(config["views"])},
        "presentation": deepcopy(config["presentation"]),
        "server_object_requests": {
            "native": deepcopy(native),
            "maintenance": deepcopy(maintenance),
        },
        "capability_state": {
            "source_inventory": "requires-load-views",
            "native": "disabled"
            if native["mode"] == "disabled"
            else "declared-not-activated",
            "maintenance": "disabled"
            if maintenance["mode"] == "disabled"
            else "declared-not-activated",
            "execution_authority": False,
            "scientific_improvement": "not-demonstrated",
        },
    }
    return result

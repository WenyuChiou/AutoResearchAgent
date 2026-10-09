"""Parse the host's named JSON assignments in tests, without evaluating JavaScript."""

import json
import re


def bootstrap_objects(raw, *required_names):
    """Keep independent bootstrap domains separate, regardless of line order."""
    values = {}
    for line in raw.decode("utf-8").splitlines():
        match = re.fullmatch(r"window\.(WORKSPACE_[A-Z_]+)=(.+);", line)
        if match is None:
            raise AssertionError("invalid bootstrap assignment")
        name, encoded = match.groups()
        if name in values:
            raise AssertionError("duplicate bootstrap name: " + name)
        value = json.loads(encoded)
        if not isinstance(value, dict):
            raise AssertionError("bootstrap object required: " + name)
        values[name] = value
    missing = set(required_names) - values.keys()
    if missing:
        raise AssertionError("missing bootstrap names: " + ", ".join(sorted(missing)))
    return values

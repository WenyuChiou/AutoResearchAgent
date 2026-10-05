"""Decode the exact bound bytes without reopening a mutable input path."""

import json

from stage1_deliverable.common import DeliverableError


def decode_json(raw):
    """Match the shared reader's duplicate-key rejection on a byte snapshot."""

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise DeliverableError("duplicate JSON key: " + key)
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=unique)

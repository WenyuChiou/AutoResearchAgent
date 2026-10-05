"""Rebuild a private, read-only view without starting a research session."""

import argparse
import json
import sys

from stage1_deliverable.common import DeliverableError, private_output, read_json

from .projection import project_package
from .view import write_workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_root")
    parser.add_argument("output_dir")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--reference-root", required=True)
    parser.add_argument("--stage2-delivery")
    parser.add_argument("--stage2-bridge")
    parser.add_argument("--expected-stage2-bridge-sha256")
    args = parser.parse_args()
    try:
        index = project_package(
            args.package_root,
            args.project_id,
            args.expected_manifest_sha256,
        )
        options = {}
        supplied = (
            args.stage2_delivery,
            args.stage2_bridge,
            args.expected_stage2_bridge_sha256,
        )
        if any(value is not None for value in supplied):
            if not all(value is not None for value in supplied):
                raise DeliverableError(
                    "All three Stage 2 import arguments are required"
                )
            options = {
                "stage2_delivery": args.stage2_delivery,
                "stage2_bridge": read_json(private_output(args.stage2_bridge)),
                "expected_stage2_bridge_sha256": args.expected_stage2_bridge_sha256,
            }
        receipt = write_workspace(
            index, args.reference_root, args.output_dir, **options
        )
    except (DeliverableError, OSError, ValueError) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

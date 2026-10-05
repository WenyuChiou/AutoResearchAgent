"""Rebuild a private, read-only view without starting a research session."""

import argparse
import json
import sys

from stage1_deliverable.common import DeliverableError

from .projection import project_package
from .view import write_workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_root")
    parser.add_argument("output_dir")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--reference-root", required=True)
    args = parser.parse_args()
    try:
        index = project_package(
            args.package_root,
            args.project_id,
            args.expected_manifest_sha256,
        )
        receipt = write_workspace(index, args.reference_root, args.output_dir)
    except (DeliverableError, OSError, ValueError) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate source-bound core nominations without asserting semantic truth."""

import argparse
import json
import sys
from pathlib import Path

from .assessment import validate_assessment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assessment", type=Path)
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args(argv)
    record = json.loads(args.assessment.read_text(encoding="utf-8"))
    errors = validate_assessment(record, args.source_root)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(
        "Core assessment source bindings are valid; semantic sufficiency is not certified."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

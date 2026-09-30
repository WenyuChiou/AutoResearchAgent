"""Explicit operator amendment admission; no implicit approval or restart."""

import argparse
import json
import sys

from .scheduler import reserve_fence, run


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("reserve", "run"))
    parser.add_argument("amendment")
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--approved-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = (reserve_fence if args.action == "reserve" else run)(
            args.amendment, args.sha256, approval_sha256=args.approved_sha256
        )
    except Exception as exc:
        print(f"stage1-operator: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0 if result.get("status", "complete") == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())

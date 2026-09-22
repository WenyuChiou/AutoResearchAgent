"""Validate a Stage 1 local ledger through its documented command interface."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage1_ledger.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main(["--run", *sys.argv[1:], "validate"]))

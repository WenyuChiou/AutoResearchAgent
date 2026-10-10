"""Explicit repository CLI bootstrap for independently discovered Atlas tests."""

from pathlib import Path
import sys

CLI_ROOT = str(Path(__file__).resolve().parents[1] / "cli")
if CLI_ROOT not in sys.path:
    sys.path.insert(0, CLI_ROOT)

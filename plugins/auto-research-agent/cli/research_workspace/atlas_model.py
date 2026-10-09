"""Pure atlas navigation asset; no research, reading or execution."""

from pathlib import Path


def model_asset():
    """Return the navigation implementation used by the read-only atlas."""
    return (
        Path(__file__).parents[2] / "references/research-workspace/atlas/atlas-model.js"
    ).read_bytes()

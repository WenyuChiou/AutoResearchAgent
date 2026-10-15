"""Fixed offline SDK import-saved operation under the existing Windows Job."""

from pathlib import Path
import sys
import time

from .atlas_local_source import decode, digest, read, require
from .saved_source_parser_runtime import install_runtime, offline_audit, verify_sdk
from .source_worker_transport import _Gates


def run_sdk(launch):
    phase, gates = launch["parse_saved_manifest"], _Gates(launch)
    require(
        time.monotonic() < phase["cutoff_monotonic"], "saved-parser-original-cutoff"
    )
    gates.gate("before-sdk-parse")
    sys.addaudithook(offline_audit)
    loader = install_runtime(phase["runtime"])
    from research_hub.source_fetch_saved import import_saved_public_source

    require(
        import_saved_public_source.__code__.co_filename
        == str(Path(phase["runtime"]["sdk_root"]) / "source_fetch_saved.py"),
        "saved-parser-sdk-callable-origin-differs",
    )
    result = import_saved_public_source(
        input_manifest=Path(phase["input_manifest"]),
        expected_manifest_sha256=phase["manifest_sha256"],
        output_dir=Path(launch["output_dir"]),
    )
    require(
        time.monotonic() < phase["cutoff_monotonic"], "saved-parser-original-cutoff"
    )
    loader.verify_loaded()
    verify_sdk(phase["runtime"])
    gates.gate("before-sdk-observation")
    receipt = Path(launch["output_dir"]) / "source-fetch-result.json"
    raw = read(receipt, 256 * 1024)
    require(
        decode(raw) == result.to_dict(), "saved-parser-original-sdk-receipt-differs"
    )
    require(
        time.monotonic() < phase["cutoff_monotonic"], "saved-parser-original-cutoff"
    )
    gates.frame(
        "terminal",
        status="receipt-observed",
        receipt_path=receipt.name,
        receipt_sha256=digest(raw),
    )

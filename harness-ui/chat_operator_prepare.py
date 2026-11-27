"""Prepare a fresh local runtime binding observation, never a message permit.

Operator tool, run outside the page. It hashes the Codex executable, the Codex
config and every chat runtime module of this checkout, writes the manifest that a
continuation grant pins, and re-verifies it. It creates no grant, opens no
conversation or budget store, and starts no Codex process.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

from harness_chat_binding import load_binding
from harness_chat_runtime import runtime_module_paths


def observation(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return {"path": str(path), "sha256": digest.hexdigest()}


def prepare(output, executable, codex_config):
    output = Path(output)
    if not output.is_absolute() or output.exists():
        raise ValueError("new-absolute-observation-directory-required")
    if any((parent / ".git").exists() for parent in (output, *output.parents)):
        raise ValueError("observation-output-must-be-outside-git")
    modules = runtime_module_paths()
    manifest = {
        "kind": "V9ChatRuntimeBinding",
        "version": 1,
        "executable": observation(executable),
        "config": observation(codex_config),
        "modules": {name: observation(path) for name, path in modules.items()},
    }
    output.mkdir(parents=True)
    descriptor = output / "runtime-binding.json"
    content = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    descriptor.write_bytes(content)
    pin = hashlib.sha256(content).hexdigest()
    (output / "runtime-binding.sha256").write_text(pin + "\n", encoding="ascii")
    started = time.monotonic()
    bound = load_binding(descriptor, pin, modules, executable, codex_config)
    bound.verify(actual_modules=runtime_module_paths())
    elapsed = time.monotonic() - started
    result = {
        "kind": "V9LocalRuntimeBindingObservation",
        "manifest_sha256": pin,
        "module_file_count": len(modules),
        "full_file_rechecks": 2,
        "verification_wall_seconds": round(elapsed, 3),
        "message_permit_created": False,
        "authorization": None,
        "chat_registered": False,
        "send_ready": False,
        "model_messages": 0,
        "source_claim": "host-owned chat modules plus the process channel of this checkout; not memory attestation",
    }
    (output / "preparation.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--executable",
        type=Path,
        required=True,
        help="native codex executable (not .cmd/.ps1)",
    )
    parser.add_argument(
        "--codex-config",
        type=Path,
        required=True,
        help="config.toml of the Codex home to use",
    )
    args = parser.parse_args()
    print(json.dumps(prepare(args.output, args.executable, args.codex_config)))


if __name__ == "__main__":
    main()

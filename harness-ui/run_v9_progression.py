"""Explicitly enable Stage 1 progression on the ordinary loopback V9 Host."""

import argparse
from pathlib import Path
import sys

import run_v7
import run_v9


def main(argv=None, *, stage1_dispatch=None):
    """Trusted embedding may supply a fixed dispatch callback, never via HTTP."""
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--stage-progression-consent", required=True, type=Path)
    parser.add_argument("--stage-progression-consent-sha256", required=True)
    options, rest = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    original = run_v7.install_renderer

    def install(host, assets, metadata, project_handler, atlas_handler):
        from research_workspace_native.session_api import _hash
        from stage3_plan.storage import private_output
        from wiki_project_progression import MAX_CONSENT_BYTES
        from wiki_project_progression_http import install_project_progression

        if not options.stage_progression_consent.is_absolute() or not _hash(
            options.stage_progression_consent_sha256
        ):
            raise ValueError("absolute consent path and SHA-256 required")

        def read_consent(_credential, _ref):
            path = private_output(options.stage_progression_consent)
            if not path.is_file():
                return None
            with path.open("rb") as stream:
                return stream.read(
                    MAX_CONSENT_BYTES + 1
                ), options.stage_progression_consent_sha256

        original(host, assets, metadata, project_handler, atlas_handler)
        install_project_progression(
            host,
            read_consent=read_consent,
            limits=metadata["run_limits"],
            runtime_sha256=metadata["harness_inventory_sha256"],
            dispatch=stage1_dispatch,
        )

    run_v7.install_renderer = install
    try:
        return run_v9.main(rest)
    finally:
        run_v7.install_renderer = original


if __name__ == "__main__":
    raise SystemExit(main())

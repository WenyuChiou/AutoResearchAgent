"""Real-scale run manifests: the pinned runtime inventory makes them large."""

from pathlib import Path
from unittest.mock import patch

from research_workspace_native.planned_query_contract import inspect_registration
from research_workspace_native.session_api import SessionApiError
from stage1_ledger.journal import MAX_MANIFEST_BYTES
from planned_query_fixture import QueryCase


class LargeRuntimeManifestTests(QueryCase):
    # 3,000 pinned files make a manifest well over the former 64 KB cap;
    # the 2026-11-27 trial runtime pins 13,696 files (2.95 MB manifest).
    RUNTIME_EXTRA_FILES = 3000

    def manifest(self):
        return Path(self.item["ledger_root"]) / "run_manifest.json"

    def test_registration_reads_a_manifest_over_the_former_caps(self):
        size = self.manifest().stat().st_size
        self.assertGreater(size, 262144)
        self.assertLess(size, MAX_MANIFEST_BYTES)
        inspect_registration("case", self.item)

    def test_changed_large_manifest_is_still_refused(self):
        raw = self.manifest().read_bytes()
        self.manifest().write_bytes(raw.replace(b"module_00001.py", b"module_00001.pz"))
        with self.assertRaisesRegex(SessionApiError, "query-input-bytes-differ"):
            inspect_registration("case", self.item)

    def test_manifest_over_the_new_cap_is_still_refused(self):
        size = self.manifest().stat().st_size
        with (
            patch(
                "research_workspace_native.planned_query_contract.MAX_MANIFEST_BYTES",
                size - 1,
            ),
            self.assertRaisesRegex(SessionApiError, "query-input-bytes-differ"),
        ):
            inspect_registration("case", self.item)

"""Neutral archived-source replay through the real workspace projector."""

import json
import inspect
import unittest
from copy import deepcopy
from pathlib import Path
import shutil
from unittest.mock import patch


import test_research_workspace as workspace_fixtures
import test_stage1_deliverable as source_fixtures
from research_workspace.projection import project_package
from stage1_deliverable import sources
from stage1_deliverable.common import (
    DeliverableError,
    canonical,
    inventory,
    read_json,
    sha,
    write_json,
)


DOI = "10.1234/neutral"


def _archive(case):
    return case.fixture.output / "sources/src1"


def _rebind(case):
    delivery = case.fixture.output
    case.records["sources"][0]["result_sha256"] = sha(
        (_archive(case) / "original.json").read_bytes()
    )
    write_json(delivery / "records.original.json", case.records)
    (delivery / "papers.jsonl").write_bytes(
        b"".join(canonical(paper) + b"\n" for paper in case.records["papers"])
    )
    manifest = read_json(delivery / "provenance_manifest.json")
    manifest.update(
        canonical_records=case.records,
        original_input_sha256=sha((delivery / "records.original.json").read_bytes()),
        files=inventory(delivery),
    )
    write_json(delivery / "provenance_manifest.json", manifest)
    case.rebind()


def _alter_receipt(case, mutate):
    path = _archive(case) / "original.json"
    receipt = read_json(path)
    mutate(receipt)
    receipt["receipt_sha256"] = sources.receipt_digest(receipt)
    write_json(path, receipt)
    _rebind(case)
    return receipt


def _observed_package(test_case):
    workspace_fixtures.WorkspaceTests.setUpClass()
    case = workspace_fixtures.WorkspaceTests()
    test_case.addCleanup(case.doCleanups)
    make_records = source_fixtures.ResearchDeliverableTests.make_records
    raw = source_fixtures.HTML.replace(
        b"</head>", f'<meta name="citation_doi" content="{DOI}"></head>'.encode()
    )
    with patch.object(
        source_fixtures.ResearchDeliverableTests,
        "make_records",
        lambda current: make_records(current, raw=raw),
    ):
        case.setUp()
    case.records["papers"][0]["doi"] = DOI
    _, _, replay = sources.validate_archive(_archive(case))
    write_json(_archive(case) / "validation.json", replay)
    _rebind(case)
    return case


class ObservedDoiTests(unittest.TestCase):
    def test_url_only_replayed_doi_reaches_project_package(self):
        observed_package = _observed_package(self)
        case = observed_package
        path = _archive(case) / "original.json"
        before = path.read_bytes()
        index = case.project()
        assert index["papers"][0]["doi"] == DOI
        assert index["sources"][0]["receipt"]["expected_identity"]["doi"] == ""
        assert index["sources"][0]["receipt"]["observed_identity"]["doi"] == DOI
        assert index["claims"] == case.records["claims"]
        assert index["readiness"] == case.readiness
        assert index["status"] == "partial-review-only"
        assert index["provenance"]["validation"]["semantic_replay"] == "not-performed"
        assert path.read_bytes() == before

    def test_observed_doi_archive_is_portable_without_original_input(self):
        observed_package = _observed_package(self)
        case = observed_package
        original = case.fixture.inputs.resolve()
        assert original.is_relative_to(case.fixture.root.resolve())
        shutil.rmtree(original)
        assert case.project()["papers"][0]["doi"] == DOI

    def test_conflicting_requested_doi_or_url_cannot_be_overridden(self):
        for requested in ["10.1234/other", "https://example.org/study"]:
            with self.subTest(requested=requested):
                observed_package = _observed_package(self)

                def mutate(receipt):
                    receipt["expected_identity"]["doi"] = requested
                    receipt["request"]["doi"] = requested

                _alter_receipt(observed_package, mutate)
                with self.assertRaises(DeliverableError):
                    observed_package.project()

    def test_missing_or_wrong_observed_doi_is_rejected(self):
        for observed in ["", "10.1234/other", "https://example.org/study"]:
            with self.subTest(observed=observed):
                observed_package = _observed_package(self)
                _alter_receipt(
                    observed_package,
                    lambda receipt: receipt["observed_identity"].update(doi=observed),
                )
                with self.assertRaisesRegex(DeliverableError, "semantic replay"):
                    observed_package.project()

    def test_identity_mismatch_is_rejected(self):
        observed_package = _observed_package(self)
        _alter_receipt(
            observed_package, lambda receipt: receipt.update(identity_status="mismatch")
        )
        with self.assertRaises(DeliverableError):
            observed_package.project()

    def test_wrong_request_url_invalidates_bound_observation(self):
        observed_package = _observed_package(self)
        _alter_receipt(
            observed_package,
            lambda receipt: receipt["request"].update(
                url="https://example.org/different"
            ),
        )
        with self.assertRaisesRegex(
            DeliverableError, "saved source validation observation differs"
        ):
            observed_package.project()

    def test_title_guard_still_rejects_rehashed_mismatch(self):
        observed_package = _observed_package(self)
        _alter_receipt(
            observed_package,
            lambda receipt: receipt["expected_identity"].update(title="Another work"),
        )
        with self.assertRaisesRegex(DeliverableError, "source title binding mismatch"):
            observed_package.project()

    def test_replayed_receipt_must_equal_the_bound_receipt(self):
        observed_package = _observed_package(self)
        validate_archive = sources.validate_archive

        def altered_replay(root):
            receipt, mapping, replay = validate_archive(root)
            receipt = deepcopy(receipt)
            receipt["observed_identity"]["doi"] = "10.1234/different"
            return receipt, mapping, replay

        with patch.object(sources, "validate_archive", side_effect=altered_replay):
            with self.assertRaisesRegex(
                DeliverableError, "source replay receipt binding mismatch"
            ):
                observed_package.project()

    def test_missing_validation_observation_is_rejected(self):
        observed_package = _observed_package(self)
        (_archive(observed_package) / "validation.json").unlink()
        _rebind(observed_package)
        with self.assertRaisesRegex(DeliverableError, "unlisted package artifact"):
            observed_package.project()

    def test_rehashed_wrong_validation_observation_is_rejected(self):
        observed_package = _observed_package(self)
        path = _archive(observed_package) / "validation.json"
        observation = read_json(path)
        observation["network_acquisition"] = True
        write_json(path, observation)
        _rebind(observed_package)
        with self.assertRaisesRegex(DeliverableError, "observation differs"):
            observed_package.project()

    def test_forged_observation_with_all_hashes_recomputed_fails_raw_replay(self):
        observed_package = _observed_package(self)
        case = observed_package
        case.records["papers"][0]["doi"] = "10.1234/forged"
        receipt = _alter_receipt(
            case,
            lambda receipt: receipt["observed_identity"].update(doi="10.1234/forged"),
        )
        path = _archive(case) / "validation.json"
        observation = read_json(path)
        relocated = sources._relocate(
            receipt,
            Path(observation["command"][7]).parent,
            sources.artifact_map(receipt),
        )
        observation["original_sha256"] = sha(
            (_archive(case) / "original.json").read_bytes()
        )
        observation["relocated_sha256"] = sha(canonical(relocated) + b"\n")
        report = json.loads(observation["stdout"])
        report["receipt_sha256"] = relocated["receipt_sha256"]
        observation["stdout"] = canonical(report).decode()
        write_json(path, observation)
        _rebind(case)
        with self.assertRaisesRegex(DeliverableError, "semantic replay"):
            project_package(case.root, "neutral-project", case.digest)

    def test_legacy_equal_request_identity_does_not_replay(self):
        for doi in [None, DOI]:
            with self.subTest(doi=doi):
                observed_package = _observed_package(self)
                case = observed_package
                case.records["papers"][0]["doi"] = doi
                if doi is not None:

                    def requested(receipt):
                        receipt["request"]["doi"] = doi
                        receipt["expected_identity"]["doi"] = doi

                    _alter_receipt(case, requested)
                _rebind(case)
                with patch.object(
                    sources,
                    "validate_archive",
                    side_effect=AssertionError("legacy replay"),
                ):
                    index = case.project()
                assert index["papers"][0]["doi"] == doi
                assert index["sources"][0]["receipt"]["expected_identity"]["doi"] == (
                    doi or ""
                )

    def test_transient_observation_cannot_override_manifest_bound_bytes(self):
        for null_observation in [False, True]:
            with self.subTest(null_observation=null_observation):
                observed_package = _observed_package(self)
                case = observed_package
                path = _archive(case) / "validation.json"
                valid = path.read_bytes()
                invalid = read_json(path)
                if null_observation:
                    invalid = None
                else:
                    invalid["network_acquisition"] = True
                write_json(path, invalid)
                invalid_bytes = path.read_bytes()
                _rebind(case)
                read_bytes = Path.read_bytes

                def transient_read(current):
                    caller = inspect.currentframe().f_back
                    if (
                        current == path
                        and caller.f_code.co_name == "read_json"
                        and caller.f_back.f_code.co_name == "validate_observation"
                    ):
                        current.write_bytes(valid)
                        try:
                            return read_bytes(current)
                        finally:
                            current.write_bytes(invalid_bytes)
                    return read_bytes(current)

                try:
                    with patch.object(Path, "read_bytes", transient_read):
                        with self.assertRaisesRegex(DeliverableError, "observation"):
                            case.project()
                finally:
                    assert path.read_bytes() == invalid_bytes

    def test_observation_snapshot_preserves_default_read_behavior(self):
        for snapshot in [False, True]:
            with self.subTest(snapshot=snapshot):
                observed_package = _observed_package(self)
                archive = _archive(observed_package)
                saved = read_json(archive / "validation.json")
                receipt, mapping, replay = sources.validate_archive(archive)
                kwargs = {"saved_observation": saved} if snapshot else {}
                with patch.object(
                    sources, "read_json", wraps=sources.read_json
                ) as reading:
                    sources.validate_observation(
                        archive, receipt, mapping, replay, **kwargs
                    )
                if snapshot:
                    reading.assert_not_called()
                else:
                    reading.assert_called_once_with(archive / "validation.json")


if __name__ == "__main__":
    unittest.main()

"""Synthetic compatibility binding tests; no real Core/HTML/SDK authority."""

from copy import deepcopy
import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile

from research_workspace import saved_admission as admission
from research_workspace import saved_admission_compat as compat
from research_workspace.host_replay import HostReplay
from stage1_deliverable.common import canonical, sha
import test_saved_source_admission as acceptance_fixture


class CompatibilityAcceptanceTests(unittest.TestCase):
    def setUp(self):
        f = acceptance_fixture.ExternalAcceptanceBindingTests(methodName="runTest")
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.fx = f
        self.root, self.snapshot = f.root, f.snapshot
        self.snapshot_ref = f.save("snapshot.json", self.snapshot)
        self.digest = self.snapshot_ref["sha256"]
        # This fixture is an INTERNAL post-load binding probe only. It does not
        # run load_host_replay/package validation or attest real30 observations.
        for category, ref in f.acceptance["checks"].items():
            import json

            obj = json.loads((self.root / ref["path"]).read_bytes())
            obj["snapshot_sha256"] = self.digest
            f.acceptance["checks"][category] = f.save(ref["path"], obj)
        f.html["snapshot_sha256"] = self.digest
        f.acceptance.update(
            snapshot_sha256=self.digest, html=f.save("html-receipt.json", f.html)
        )
        receiver = deepcopy(f.acceptance["producer"])
        receiver.update(
            delivered_commit="9" * 40,
            reviewed_head="8" * 40,
            merge_parents=["8" * 40, "7" * 40],
            merge_tree="6" * 40,
        )
        for job in receiver["ci"]:
            job["head_sha"] = "8" * 40 if job["phase"] == "pr" else "9" * 40
        self.receiver = receiver
        self.removed = {
            "cli/research_workspace/saved_admission_compat.py",
            "schemas/stage1-saved-admission-compat.v2.schema.json",
            "cli/research_workspace_native/project_reading_dispatch.py",
        }
        historical = f.acceptance["producer"]["sources"]
        for name in self.removed:
            historical.pop(name)
        archived = {
            name: f.save(
                "historical-source/" + name,
                (admission.SCHEMA.parent.parent / name).read_bytes(),
            )
            for name in historical
        }
        self.historical_ref = f.save("historical-acceptance.json", f.acceptance)
        self.context = HostReplay(
            dict(
                snapshot_ref=self.snapshot_ref,
                project_id=self.snapshot["project_id"],
                input_version=self.snapshot["input_version"],
                canonical_manifest_sha256=self.snapshot["bindings"]["deliverable"][
                    "sha256"
                ],
                sources=[],
            ),
            "5" * 64,
            self.root,
        )
        self.review = dict(
            kind="SavedSourceAdmissionCompatibilityReview",
            schema_version="1.0.0",
            snapshot_sha256=self.digest,
            project_id=self.snapshot["project_id"],
            input_version=self.snapshot["input_version"],
            historical_acceptance_sha256=self.historical_ref["sha256"],
            receiver_delivered_commit=receiver["delivered_commit"],
            receiver_sources_sha256=sha(canonical(receiver["sources"])),
            host_replay_sha256="5" * 64,
            scope=compat.SCOPE,
            validator=f.proof,
            rubric=f.proof,
            results=[
                dict(
                    check_id="synthetic-binding-only",
                    status="passed",
                    locator="fixture:1",
                    reason="No real receiving/Core assertion.",
                )
            ],
            outcome="accepted",
            observations="Synthetic fixture only.",
            evidence=[f.proof],
            scientific_acceptance=False,
            execution_authorized=False,
        )
        self.envelope = dict(
            kind="SavedSourceAdmissionCompatibilityAcceptance",
            schema_version="2.0.0",
            snapshot_sha256=self.digest,
            snapshot_ref=self.snapshot_ref,
            project_id=self.snapshot["project_id"],
            input_version=self.snapshot["input_version"],
            contract_sha256=sha(compat.SCHEMA.read_bytes()),
            historical_acceptance=self.historical_ref,
            historical_sources=archived,
            receiver=receiver,
            host_replay_sha256="5" * 64,
            compatibility_review=f.save("compatibility-review.json", self.review),
        )

    def check(self, envelope=None, *, context=True, trusted=None):
        envelope = self.envelope if envelope is None else envelope
        ref = self.fx.save("compatibility.json", envelope)
        return admission._check_acceptance(
            self.root,
            ref,
            ref["sha256"] if trusted is None else trusted,
            self.digest,
            self.snapshot,
            self.fx.view,
            host_replay=self.context if context else None,
        )

    def changed_review(self, **changes):
        value = dict(self.review, **changes)
        ref = self.fx.save("changed-review.json", value)
        return dict(self.envelope, compatibility_review=ref)

    def test_separate_complete_closures_without_relabeling_original_acceptance(self):
        self.assertEqual(self.check(), self.envelope)
        self.assertNotEqual(
            self.envelope["receiver"]["delivered_commit"],
            self.fx.acceptance["producer"]["delivered_commit"],
        )
        self.assertEqual(
            set(self.receiver["sources"]) - set(self.envelope["historical_sources"]),
            self.removed,
        )
        self.assertFalse(self.review["execution_authorized"])
        self.assertFalse(self.context.evidence()["core_acceptance"])

    def test_v1_does_not_fall_back_or_ignore_new_current_files(self):
        with self.assertRaisesRegex(ValueError, "runtime inventory incomplete"):
            admission._check_acceptance(
                self.root,
                self.historical_ref,
                self.historical_ref["sha256"],
                self.digest,
                self.snapshot,
                self.fx.view,
            )
        self.assertEqual(self.check(), self.envelope)

    def test_external_digest_context_and_unknown_contract_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "independent external hash"):
            self.check(trusted="0" * 64)
        with self.assertRaisesRegex(ValueError, "verified host replay"):
            self.check(context=False)
        for field, value in (
            ("schema_version", "3.0.0"),
            ("kind", "Unknown"),
            ("input_version", 1),
            ("contract_sha256", "0" * 64),
            ("host_replay_sha256", "0" * 64),
        ):
            with self.subTest(field=field), self.assertRaises((ValueError, KeyError)):
                self.check(dict(self.envelope, **{field: value}))

    def test_historical_inventory_bytes_and_bound_core_substitution_are_rejected(self):
        original = self.envelope["historical_sources"]
        name = next(iter(original))
        for fault in ("missing", "extra", "digest", "linked-path", "core"):
            e = deepcopy(self.envelope)
            refs = e["historical_sources"]
            if fault == "missing":
                del refs[name]
            elif fault == "extra":
                refs["extra"] = deepcopy(refs[name])
            elif fault == "digest":
                refs[name]["sha256"] = "0" * 64
            elif fault == "linked-path":
                refs[name]["path"] = "../escape"
            else:
                changed = deepcopy(self.fx.acceptance)
                changed["producer"]["delivered_commit"] = "1" * 40
                e["historical_acceptance"] = self.fx.save("changed-core.json", changed)
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                self.check(e)
        path = self.root / original[name]["path"]
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaises(ValueError):
            self.check()

    def test_receiver_full_closure_exact_head_and_successful_ci_are_required(self):
        for fault in (
            "missing",
            "extra",
            "digest",
            "head",
            "failure",
            "skipped",
            "no-post-main",
        ):
            e = deepcopy(self.envelope)
            row = e["receiver"]
            name = next(iter(row["sources"]))
            if fault == "missing":
                del row["sources"][name]
            elif fault == "extra":
                row["sources"]["unknown"] = "0" * 64
            elif fault == "digest":
                row["sources"][name] = "0" * 64
            elif fault == "head":
                row["ci"][0]["head_sha"] = "0" * 40
            elif fault in ("failure", "skipped"):
                row["ci"][0]["conclusion"] = fault
            else:
                row["ci"] = [x for x in row["ci"] if x["phase"] != "post-main"]
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                self.check(e)

    def test_review_binding_outcome_evidence_and_no_execution_gate(self):
        for field, value in (
            ("historical_acceptance_sha256", "0" * 64),
            ("receiver_delivered_commit", "0" * 40),
            ("receiver_sources_sha256", "0" * 64),
            ("host_replay_sha256", "0" * 64),
            ("snapshot_sha256", "0" * 64),
            ("input_version", 1),
            ("scope", "unrelated"),
            ("outcome", "pending"),
            ("scientific_acceptance", True),
            ("execution_authorized", True),
            ("results", []),
            ("evidence", []),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check(self.changed_review(**{field: value}))

    def test_malformed_receiver_shapes_are_typed_refusals(self):
        for field, value in (
            ("sources", []),
            ("ci", [False]),
            ("ci", [{"phase": [], "name": "bad"}]),
            ("merge_parents", [{}, []]),
        ):
            e = deepcopy(self.envelope)
            e["receiver"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.check(e)

    def test_all_original_category_and_html_checks_still_run(self):
        category = next(iter(self.fx.acceptance["checks"]))
        ref = self.fx.acceptance["checks"][category]
        (self.root / ref["path"]).write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.check()


class OuterCompatibilityForwardingTests(unittest.TestCase):
    def test_outer_entry_reuses_exact_resolved_context_for_core_validation(self):
        # Isolate context forwarding. Upstream validators and Core result are
        # deliberately mocked, so this is not an actual admission or replay.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            snapshot, index, progress, save = acceptance_fixture.saved_binding_fixture(
                root, original_receipt=True
            )
            ref = save("snapshot.json", snapshot)
            context = object()
            core_ref = {"path": "synthetic-core.json", "sha256": "d" * 64, "bytes": 1}
            with (
                patch(
                    "research_workspace.host_replay.resolve_host_replay",
                    return_value=context,
                ),
                patch.object(admission, "_view", return_value=({}, index, {})),
                patch.object(
                    admission, "derive_formal_readiness", return_value=progress
                ),
                patch.object(
                    admission.deliverable_package, "validate"
                ) as package_validation,
                patch.object(
                    admission,
                    "_check_acceptance",
                    return_value={"kind": "synthetic-only"},
                ) as acceptance_validation,
            ):
                result = admission.inspect_saved_admission(
                    root,
                    ref,
                    acceptance_ref=core_ref,
                    trusted_acceptance_sha256="d" * 64,
                    verified_host_replay=context,
                )
            self.assertIs(package_validation.call_args.kwargs["host_replay"], context)
            self.assertIs(
                acceptance_validation.call_args.kwargs["host_replay"], context
            )
            self.assertEqual(result["acceptance_ref"], core_ref)
            self.assertFalse(result["stage1_completed"])
            self.assertFalse(result["stage2"]["execution_authorized"])


if __name__ == "__main__":
    unittest.main()

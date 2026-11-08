"""Authored registered-material integrity tests; no Host or model calls."""

# ruff: noqa: E402 -- private prototype uses the production package imports.

from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))

from stage3_plan.contracts import Stage3Error, canonical_bytes
from stage3_plan.prompts import MAX_CONTEXT_BYTES
from stage3_plan.storage import MAX_ARTIFACT_BYTES, read_json

from stage3_plan import direction_materials as materials


def binding(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class RegisteredMaterialsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="stage3-material-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.context = {
            "project_ref": "authored-project",
            "input_version": 1,
            "intent_sha256": "a" * 64,
            "source_manifest_sha256": "b" * 64,
            "questions": [{"question_ref": "authored-direction@1/q1"}],
            "unresolved": ["Lawful use and source fitness remain unknown."],
        }
        self.catalog_calls = []
        self.read_calls = []
        self.documents = {}
        self.entries = []
        self.selections = []
        self.add_material(
            "1" * 32,
            {"a/b": {"~label": [None, {"status": "unknown"}]}, "counts": [2, 5]},
            ["/a~1b/~0label/1/status", "/counts/0", "/a~1b/~0label/0"],
        )

    def add_material(self, suffix, document, pointers):
        file_id = "file-" + suffix
        raw = canonical_bytes(document)
        self.documents[file_id] = raw
        self.entries.append(
            {
                "id": file_id,
                "kind": "manual-file",
                "project_ref": self.context["project_ref"],
                "stage": 3,
                "name": f"Authored material {suffix}.json",
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "status": "registered",
                "content_status": "unreviewed-material-not-screened-or-read",
                "registered_at": "2026-11-08T00:00:00Z",
                "execution_authorized": False,
            }
        )
        self.selections.append(
            {
                "file_id": file_id,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "pointers": pointers,
                "question_refs": [self.context["questions"][0]["question_ref"]],
                "purpose": "Inspect an authored source value for the stated question.",
                "limits": "Registration does not establish rights or scientific fitness.",
            }
        )
        return file_id

    def catalog(self, project_ref):
        self.catalog_calls.append(project_ref)
        return deepcopy(self.entries)

    def reader(self, file_id):
        self.read_calls.append(file_id)
        return self.documents[file_id]

    def prepare(self, *, output=None, context=None, selections=None, reader=None):
        return materials.prepare_registered_materials(
            self.context if context is None else context,
            self.selections if selections is None else selections,
            self.root / "frontier" if output is None else output,
            catalog=self.catalog,
            read_file=self.reader if reader is None else reader,
        )

    def test_string_consumer_version_is_retained_without_numeric_coercion(self):
        self.context["input_version"] = "authored-v1"
        result = materials.prepare_registered_materials(
            self.context,
            self.selections,
            self.root / "string-version",
            catalog=self.catalog,
            read_file=self.reader,
        )
        projected = materials.inspect_registered_materials(result, self.context)
        self.assertEqual(projected["consumer"]["input_version"], "authored-v1")

    def test_projection_preserves_source_status_unknowns_and_pointer_escapes(self):
        original_context = deepcopy(self.context)
        original_selections = deepcopy(self.selections)
        saved = self.prepare()
        projection = materials.inspect_registered_materials(saved, self.context)
        self.assertEqual(
            projection,
            {
                "kind": "Stage3RegisteredMaterialFrontier",
                "consumer": {
                    key: self.context[key]
                    for key in (
                        "project_ref",
                        "input_version",
                        "intent_sha256",
                        "source_manifest_sha256",
                    )
                },
                "catalog_input_version": "not-recorded",
                "scientific_quality_verified": False,
                "rights_verified": False,
                "execution_authorized": False,
                "materials": [
                    {
                        "catalog": self.entries[0],
                        "purpose": self.selections[0]["purpose"],
                        "limits": self.selections[0]["limits"],
                        "question_refs": self.selections[0]["question_refs"],
                        "values": [
                            {"pointer": "/a~1b/~0label/1/status", "value": "unknown"},
                            {"pointer": "/counts/0", "value": 2},
                            {"pointer": "/a~1b/~0label/0", "value": None},
                        ],
                    }
                ],
            },
        )
        self.assertEqual(self.context, original_context)
        self.assertEqual(self.selections, original_selections)
        self.assertEqual(self.catalog_calls, [self.context["project_ref"]])
        self.assertEqual(self.read_calls, [self.selections[0]["file_id"]])

    def test_completed_replay_has_no_additional_catalog_or_file_callbacks(self):
        saved = self.prepare()
        callbacks = (deepcopy(self.catalog_calls), deepcopy(self.read_calls))
        self.assertEqual(self.prepare(), saved)
        first = materials.inspect_registered_materials(saved, self.context)
        self.assertEqual(
            materials.inspect_registered_materials(saved, self.context), first
        )
        self.assertEqual((self.catalog_calls, self.read_calls), callbacks)

    def test_interrupted_second_read_resumes_without_repeating_first_or_catalog(self):
        second = self.add_material("2" * 32, {"value": "pending"}, ["/value"])

        def interrupted_reader(file_id):
            self.read_calls.append(file_id)
            if file_id == second:
                raise RuntimeError("Authored second-read interruption.")
            return self.documents[file_id]

        with self.assertRaisesRegex(RuntimeError, "second-read interruption"):
            self.prepare(reader=interrupted_reader)
        saved = self.prepare()
        self.assertEqual(self.catalog_calls, [self.context["project_ref"]])
        self.assertEqual(
            self.read_calls, [self.selections[0]["file_id"], second, second]
        )
        self.assertEqual(
            len(
                materials.inspect_registered_materials(saved, self.context)["materials"]
            ),
            2,
        )

    def test_rehashed_projection_tamper_is_rejected_against_original_raw_bytes(self):
        saved = self.prepare()
        packet_path = Path(saved["path"])
        packet = read_json(packet_path)
        packet["projection"]["materials"][0]["values"][0]["value"] = "fabricated"
        packet_path.write_bytes(canonical_bytes(packet))
        with self.assertRaisesRegex(Stage3Error, "projection differs"):
            materials.inspect_registered_materials(binding(packet_path), self.context)
        source = packet_path.parent / (self.selections[0]["file_id"] + ".json")
        self.assertEqual(
            source.read_bytes(), self.documents[self.selections[0]["file_id"]]
        )

    def test_saved_source_byte_tamper_rejects_inspection_and_replay_without_reread(
        self,
    ):
        saved = self.prepare()
        source = Path(saved["path"]).parent / (self.selections[0]["file_id"] + ".json")
        changed = read_json(source)
        changed["counts"][0] = 3
        tampered = canonical_bytes(changed)
        self.assertEqual(len(tampered), self.selections[0]["bytes"])
        source.write_bytes(tampered)
        before = (deepcopy(self.catalog_calls), deepcopy(self.read_calls))
        with self.assertRaisesRegex(Stage3Error, "saved bytes differ"):
            materials.inspect_registered_materials(saved, self.context)
        with self.assertRaisesRegex(Stage3Error, "saved bytes differ"):
            self.prepare()
        self.assertEqual((self.catalog_calls, self.read_calls), before)

    def test_wrong_catalog_project_status_hash_or_duplicates_reject_before_reader(self):
        original = deepcopy(self.entries[0])
        variants = [
            [{**original, "project_ref": "another-project"}],
            [{**original, "status": "removed"}],
            [{**original, "sha256": "f" * 64}],
            [deepcopy(original), deepcopy(original)],
        ]
        for index, rows in enumerate(variants):
            self.entries = rows
            with self.subTest(index=index), self.assertRaises(Stage3Error):
                self.prepare(output=self.root / f"bad-catalog-{index}")
            self.assertEqual(self.read_calls, [])

    def test_malformed_or_overbound_selections_reject_before_any_callback(self):
        original = deepcopy(self.selections[0])
        variants = [
            [],
            [deepcopy(original), deepcopy(original)],
            [{**original, "file_id": "not-a-registered-file"}],
            [{**original, "bytes": True}],
            [{**original, "bytes": MAX_ARTIFACT_BYTES + 1}],
            [{**original, "question_refs": ["unrequested@1/q"]}],
            [{**original, "pointers": ["/bad~2escape"]}],
            [{**original, "pointers": ["not-an-absolute-pointer"]}],
            [{**original, "purpose": "x" * (MAX_CONTEXT_BYTES + 1)}],
        ]
        for index, selections in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(Stage3Error):
                self.prepare(
                    output=self.root / f"bad-selection-{index}", selections=selections
                )
            self.assertEqual((self.catalog_calls, self.read_calls), ([], []))

    def test_stale_consumer_or_noninteger_version_rejects_without_callbacks(self):
        saved = self.prepare()
        before = (deepcopy(self.catalog_calls), deepcopy(self.read_calls))
        changes = [
            {"project_ref": "another-project"},
            {"input_version": 2},
            {"input_version": True},
            {"input_version": 1.0},
            {"intent_sha256": "c" * 64},
            {"source_manifest_sha256": "d" * 64},
        ]
        for change in changes:
            context = {**self.context, **change}
            with self.subTest(change=change):
                with self.assertRaises(Stage3Error):
                    materials.inspect_registered_materials(saved, context)
                with self.assertRaises(Stage3Error):
                    self.prepare(context=context)
            self.assertEqual((self.catalog_calls, self.read_calls), before)

    def test_overbound_first_projection_stops_before_reading_second_material(self):
        self.documents, self.entries, self.selections = {}, [], []
        first = self.add_material(
            "3" * 32, {"large": "x" * (MAX_CONTEXT_BYTES + 1)}, ["/large"]
        )
        self.add_material("4" * 32, {"value": "still unrequested"}, ["/value"])
        with self.assertRaisesRegex(Stage3Error, "context bound"):
            self.prepare()
        self.assertEqual(self.read_calls, [first])
        self.assertFalse((self.root / "frontier/packet.json").exists())


if __name__ == "__main__":
    unittest.main()

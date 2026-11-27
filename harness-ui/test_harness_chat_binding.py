"""No-model runtime binding checks using synthetic files only."""

from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from harness_chat_binding import BindingError, load_binding


TEMP_ROOT = Path(tempfile.gettempdir()) / "ara-chat-tests"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RuntimeBindingTests(unittest.TestCase):
    def setUp(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="binding-", dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.exe = self.root / "codex.exe"
        self.config = self.root / "config.toml"
        self.module = self.root / "harness_chat.py"
        self.helper = self.root / "helper.py"
        self.manifest = self.root / "binding.json"
        self.exe.write_bytes(b"synthetic native executable; never run")
        self.config.write_bytes(b'model = "test-only"\n')
        self.module.write_bytes(b"NO_EXECUTION = True\n")
        self.helper.write_bytes(b"HELPER = True\n")
        self.actual = {"harness_chat": self.module, "helper": self.helper}
        self.data = {
            "kind": "V9ChatRuntimeBinding",
            "version": 1,
            "executable": self.entry(self.exe),
            "config": self.entry(self.config),
            "modules": {name: self.entry(path) for name, path in self.actual.items()},
        }
        self.save()

    def entry(self, path):
        return {"path": str(path), "sha256": sha(path)}

    def save(self, raw=None):
        self.manifest.write_bytes(
            raw
            if raw is not None
            else json.dumps(self.data, ensure_ascii=False, sort_keys=True).encode(
                "utf-8"
            )
        )
        self.pin = sha(self.manifest)

    def load(self, **overrides):
        args = {
            "path": self.manifest,
            "pin": self.pin,
            "actual_modules": self.actual,
            "expected_executable": self.exe,
            "expected_config": self.config,
        }
        args.update(overrides)
        return load_binding(**args)

    def rejects(self, code, **overrides):
        with self.assertRaisesRegex(BindingError, "^" + code + "$"):
            self.load(**overrides)

    def test_success_frozen_and_repeatable_without_file_changes(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        bound = self.load()
        self.assertIs(bound.verify(actual_modules=self.actual), bound)
        self.assertEqual(len(bound.files), 4)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        with self.assertRaises(FrozenInstanceError):
            bound.manifest_sha256 = "a" * 64

    def test_duplicate_top_level_key_rejected(self):
        self.save(b'{"kind":"V9ChatRuntimeBinding","kind":"V9ChatRuntimeBinding"}')
        self.rejects("chat-binding-json-duplicate-key")

    def test_duplicate_nested_key_rejected(self):
        self.save(b'{"modules":{"x":{"path":"x","path":"y"}}}')
        self.rejects("chat-binding-json-duplicate-key")

    def test_manifest_limit_is_bounded(self):
        self.save(b" " * (65536 + 1))
        self.rejects("chat-binding-file-too-large")

    def test_bad_json_utf8_and_nonfinite_rejected(self):
        for raw, code in [
            (b"{", "chat-binding-json-invalid"),
            (b"\xff", "chat-binding-json-invalid"),
            (b'{"version":NaN}', "chat-binding-json-nonfinite-number"),
        ]:
            with self.subTest(raw=raw):
                self.save(raw)
                self.rejects(code)

    def test_external_manifest_pin_cannot_be_self_selected(self):
        self.rejects("chat-binding-manifest-pin-differs", pin="0" * 64)

    def test_sha_requires_lowercase_exact_length(self):
        for pin in ["A" * 64, "a" * 63, "a" * 65, None, 1]:
            with self.subTest(pin=pin):
                self.rejects("chat-binding-sha256-invalid", pin=pin)

    def test_version_bool_and_unknown_top_field_rejected(self):
        self.data["version"] = True
        self.save()
        self.rejects("chat-binding-manifest-version-invalid")
        self.data["version"] = 1
        self.data["authorization"] = "not an authority"
        self.save()
        self.rejects("chat-binding-manifest-fields-differ")

    def test_wrong_module_path_even_with_identical_bytes_rejected(self):
        old = self.root / "historical-copy.py"
        old.write_bytes(self.module.read_bytes())
        self.data["modules"]["harness_chat"] = self.entry(old)
        self.save()
        self.rejects("chat-binding-actual-path-differs")

    def test_wrong_config_and_executable_paths_even_same_bytes_rejected(self):
        for field, original in [("config", self.config), ("executable", self.exe)]:
            with self.subTest(field=field):
                old = self.root / ("old-" + original.name)
                old.write_bytes(original.read_bytes())
                original_entry = self.data[field]
                self.data[field] = self.entry(old)
                self.save()
                self.rejects("chat-binding-actual-path-differs")
                self.data[field] = original_entry

    def test_manifest_modules_must_match_host_closure_exactly(self):
        for mode in ["missing", "extra"]:
            with self.subTest(mode=mode):
                original = dict(self.data["modules"])
                if mode == "missing":
                    del self.data["modules"]["helper"]
                else:
                    self.data["modules"]["another"] = self.entry(self.helper)
                self.save()
                self.rejects("chat-binding-runtime-closure-differs")
                self.data["modules"] = original

    def test_host_closure_required_and_named(self):
        self.rejects("chat-binding-runtime-closure-required", actual_modules={})
        self.rejects(
            "chat-binding-module-name-invalid", actual_modules={"../x": self.module}
        )

    def test_entry_extra_fields_and_relative_path_rejected(self):
        self.data["config"]["extra"] = True
        self.save()
        self.rejects("chat-binding-file-fields-differ")
        del self.data["config"]["extra"]
        self.data["config"]["path"] = "config.toml"
        self.save()
        self.rejects("chat-binding-absolute-path-required")

    def test_changed_executable_config_or_module_bytes_rejected(self):
        for target in [self.exe, self.config, self.module]:
            with self.subTest(file=target.name):
                original = target.read_bytes()
                target.write_bytes(original + b"changed")
                self.rejects("chat-binding-file-pin-differs")
                target.write_bytes(original)

    def test_file_change_after_initial_load_rejected_on_verify(self):
        bound = self.load()
        self.module.write_bytes(b"new source")
        with self.assertRaisesRegex(BindingError, "^chat-binding-file-pin-differs$"):
            bound.verify()

    def test_manifest_change_after_initial_load_rejected_on_verify(self):
        bound = self.load()
        self.manifest.write_bytes(self.manifest.read_bytes() + b"\n")
        with self.assertRaisesRegex(
            BindingError, "^chat-binding-manifest-pin-differs$"
        ):
            bound.verify()

    def test_recheck_uses_new_actual_loaded_mapping(self):
        bound = self.load()
        new_module = self.root / "loaded-elsewhere.py"
        new_module.write_bytes(self.module.read_bytes())
        with self.assertRaisesRegex(BindingError, "^chat-binding-actual-path-differs$"):
            bound.verify(
                actual_modules={"harness_chat": new_module, "helper": self.helper}
            )

    def test_deleted_file_and_directory_rejected(self):
        self.module.unlink()
        self.rejects("chat-binding-file-unavailable")
        self.module.mkdir()
        self.rejects("chat-binding-regular-file-required")

    def test_same_file_hardlink_alias_is_accepted(self):
        alias = self.root / "same-file.py"
        alias.hardlink_to(self.module)
        self.data["modules"]["harness_chat"] = self.entry(alias)
        self.save()
        self.assertIsNotNone(self.load().verify())

    def test_module_size_is_bounded_before_hashing(self):
        with self.module.open("wb") as stream:
            stream.truncate(8 * 1024 * 1024 + 1)
        self.data["modules"]["harness_chat"]["sha256"] = "0" * 64
        self.save()
        self.rejects("chat-binding-file-too-large")


if __name__ == "__main__":
    unittest.main(verbosity=2)

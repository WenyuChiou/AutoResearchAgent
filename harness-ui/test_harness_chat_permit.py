"""Synthetic grant checks only; never read real authorization or private keys."""

from copy import deepcopy
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from harness_chat_permit import PermitError, canonical, load_permit_verifier


TEMP_ROOT = Path(tempfile.gettempdir()) / "ara-chat-tests"


class PermitTests(unittest.TestCase):
    def setUp(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="permit-", dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.private = self.root / "private"
        self.private.mkdir()
        self.key_path = self.private / "synthetic.key"
        self.key = b"0123456789abcdef0123456789abcdef"
        self.key_path.write_bytes(self.key)
        if os.name != "nt":
            self.key_path.chmod(0o600)
        self.receipt_path = self.root / "synthetic-receipt.json"
        now = int(time.time())
        self.request = {"kind": "V9ChatContinuationPermissionCheck",
                        "contract_sha256": "a" * 64, "research_execution": False,
                        "contract": {"kind": "V9ChatContinuation", "version": 3,
                                     "scope": {"issued_at": now - 10, "expires_at": now + 3600,
                                               "model_messages_authorized": True,
                                               "research_execution": False,
                                               "actions": ["state", "materials"]}}}
        self.receipt = {"kind": "V9LocalChatOnlyPermit", "version": 1,
                        "contract_sha256": "a" * 64,
                        "request_sha256": hashlib.sha256(canonical(self.request)).hexdigest(),
                        "authorization_source_sha256": "b" * 64,
                        "issued_at": now - 5, "expires_at": now + 3500,
                        "signature": "0" * 64}
        self.save()

    def save(self, raw=None, *, sign=True):
        if sign:
            payload = {key: value for key, value in self.receipt.items() if key != "signature"}
            self.receipt["signature"] = hmac.new(self.key, canonical(payload), hashlib.sha256).hexdigest()
        raw = raw if raw is not None else canonical(self.receipt)
        self.receipt_path.write_bytes(raw)
        self.pin = hashlib.sha256(raw).hexdigest()

    def bind(self, **kwargs):
        args = {"receipt_path": self.receipt_path, "receipt_sha": self.pin, "key_path": self.key_path}
        args.update(kwargs)
        return load_permit_verifier(**args)

    def rejects_load(self, code, **kwargs):
        with self.assertRaisesRegex(PermitError, "^" + code + "$"):
            self.bind(**kwargs)

    def resign_request(self):
        self.receipt["request_sha256"] = hashlib.sha256(canonical(self.request)).hexdigest()
        self.save()

    def test_fixed_request_success_and_no_file_changes(self):
        before = self.key_path.read_bytes(), self.receipt_path.read_bytes()
        verify = self.bind()
        for _ in range(2):
            result = verify(deepcopy(self.request))
            self.assertEqual(result, {"kind": "V9VerifiedChatOnlyPermit",
                                      "request_sha256": self.receipt["request_sha256"],
                                      "model_messages_authorized": True, "research_execution": False})
        self.assertEqual(before, (self.key_path.read_bytes(), self.receipt_path.read_bytes()))

    def test_operator_revocation_marker_stops_a_valid_permit(self):
        verify = self.bind()
        self.assertEqual(verify(deepcopy(self.request))["model_messages_authorized"], True)
        Path(str(self.receipt_path) + ".revoked").write_text("operator revoked", encoding="utf-8")
        with self.assertRaisesRegex(PermitError, "^chat-permit-revoked$"):
            verify(deepcopy(self.request))
        Path(str(self.receipt_path) + ".revoked").unlink()
        self.assertEqual(verify(deepcopy(self.request))["model_messages_authorized"], True)

    def test_canonical_rule_matches_contract_encoding(self):
        expected = json.dumps({"中文": [2, 1], "a": False}, ensure_ascii=False,
                              sort_keys=True, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.assertEqual(canonical({"中文": [2, 1], "a": False}), expected)

    def test_receipt_external_pin_is_required(self):
        self.rejects_load("chat-permit-receipt-pin-differs", receipt_sha="0" * 64)

    def test_bad_hmac_rejected_even_with_updated_external_pin(self):
        self.receipt["signature"] = "0" * 64
        self.save(sign=False)
        self.rejects_load("chat-permit-signature-differs")

    def test_request_contract_pin_and_fingerprint_are_fixed(self):
        verify = self.bind()
        changed = deepcopy(self.request)
        changed["contract_sha256"] = "c" * 64
        with self.assertRaisesRegex(PermitError, "^chat-permit-contract-pin-differs$"):
            verify(changed)
        changed = deepcopy(self.request)
        changed["contract"]["scope"]["actions"] = ["state"]
        with self.assertRaisesRegex(PermitError, "^chat-permit-fixed-request-differs$"):
            verify(changed)

    def test_does_not_sign_or_allow_an_arbitrary_request(self):
        changed = deepcopy(self.request)
        changed["contract"]["scope"]["new_field"] = "different"
        with self.assertRaisesRegex(PermitError, "^chat-permit-fixed-request-differs$"):
            self.bind()(changed)

    def test_research_or_no_model_authority_rejected_even_if_signed(self):
        for field, value in [("research_execution", True), ("model_messages_authorized", False)]:
            with self.subTest(field=field):
                original = self.request["contract"]["scope"][field]
                self.request["contract"]["scope"][field] = value
                self.resign_request()
                with self.assertRaisesRegex(PermitError, "^chat-permit-scope-chat-only-required$"):
                    self.bind()(self.request)
                self.request["contract"]["scope"][field] = original

    def test_write_or_duplicate_actions_rejected_even_if_signed(self):
        for actions in [["approve"], ["state", "state"], [], "state"]:
            with self.subTest(actions=actions):
                self.request["contract"]["scope"]["actions"] = actions
                self.resign_request()
                with self.assertRaisesRegex(PermitError, "^chat-permit-read-actions-only$"):
                    self.bind()(self.request)

    def test_request_shape_and_outer_research_rejected(self):
        verify = self.bind()
        changed = dict(self.request, extra=True)
        with self.assertRaisesRegex(PermitError, "^chat-permit-request-fields-differ$"):
            verify(changed)
        changed = dict(self.request, research_execution=True)
        with self.assertRaisesRegex(PermitError, "^chat-permit-request-chat-only-required$"):
            verify(changed)

    def test_receipt_extra_fields_and_bool_version_rejected(self):
        self.receipt["extra"] = True
        self.save()
        self.rejects_load("chat-permit-receipt-fields-differ")
        del self.receipt["extra"]
        self.receipt["version"] = True
        self.save()
        self.rejects_load("chat-permit-receipt-version-invalid")

    def test_duplicate_keys_and_nonfinite_json_rejected(self):
        for raw, code in [(b'{"kind":"x","kind":"y"}', "chat-permit-json-duplicate-key"),
                          (b'{"issued_at":NaN}', "chat-permit-json-nonfinite"),
                          (b"\xff", "chat-permit-json-invalid")]:
            with self.subTest(code=code):
                self.save(raw, sign=False)
                self.rejects_load(code)

    def test_receipt_size_and_sha_format_are_bounded(self):
        self.rejects_load("chat-permit-sha256-invalid", receipt_sha="A" * 64)
        self.save(b" " * (65536 + 1), sign=False)
        self.rejects_load("chat-permit-file-too-large")

    def test_receipt_future_expired_and_invalid_windows_rejected(self):
        now = int(time.time())
        for issued, expiry, code in [(now + 10, now + 20, "chat-permit-not-current"),
                                     (now - 20, now - 10, "chat-permit-not-current"),
                                     (True, now + 10, "chat-permit-time-invalid"),
                                     (now + 10, now, "chat-permit-time-invalid")]:
            with self.subTest(code=code):
                self.receipt.update(issued_at=issued, expires_at=expiry)
                self.save()
                self.rejects_load(code)

    def test_receipt_cannot_extend_contract_window(self):
        self.request["contract"]["scope"]["expires_at"] = self.receipt["expires_at"] - 1
        self.resign_request()
        with self.assertRaisesRegex(PermitError, "^chat-permit-time-outside-contract$"):
            self.bind()(self.request)

    def test_callback_rechecks_time_without_new_verifier(self):
        verify = self.bind()
        with patch("harness_chat_permit.time.time", return_value=self.receipt["expires_at"]):
            with self.assertRaisesRegex(PermitError, "^chat-permit-not-current$"):
                verify(self.request)

    def test_callback_rechecks_receipt_bytes_and_key_content(self):
        verify = self.bind()
        raw = self.receipt_path.read_bytes()
        self.receipt_path.write_bytes(raw + b"\n")
        with self.assertRaisesRegex(PermitError, "^chat-permit-receipt-pin-differs$"):
            verify(self.request)
        self.receipt_path.write_bytes(raw)
        self.key_path.write_bytes(b"f" * 32)
        with self.assertRaisesRegex(PermitError, "^chat-permit-key-changed$"):
            verify(self.request)

    def test_key_must_be_exactly_32_bytes(self):
        for raw, code in [(b"a" * 31, "chat-permit-key-size-invalid"),
                          (b"a" * 33, "chat-permit-file-too-large")]:
            with self.subTest(length=len(raw)):
                self.key_path.write_bytes(raw)
                self.rejects_load(code)

    def test_key_must_be_in_explicit_private_directory(self):
        other = self.root / "public.key"
        other.write_bytes(self.key)
        self.rejects_load("chat-permit-private-key-directory-required", key_path=other)

    def test_key_cannot_live_in_git_checkout(self):
        (self.root / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
        self.rejects_load("chat-permit-key-in-git-refused")

    def test_key_symlink_or_reparse_is_rejected(self):
        # Simulated OS metadata makes this test independent of Windows link rights.
        original = Path.lstat
        key_path = self.key_path

        def linked(path):
            info = original(path)
            if path == key_path:
                class Reparse:
                    st_mode = info.st_mode
                    st_file_attributes = 0x400
                return Reparse()
            return info

        with patch.object(Path, "lstat", linked):
            self.rejects_load("chat-permit-key-link-refused")


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Select proposal text from an already authenticated native capture."""

import hashlib
import os
import stat
from pathlib import Path

from stage2_common import Stage2Error


PROPOSAL_PATH = "archive/workspace-end/stage2_proposal.md"
START_PROPOSAL_PATH = "archive/workspace-start/stage2_proposal.md"
MAX_PROPOSAL_BYTES = 100 * 1024


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _regular_unaliased(path, root, label):
    candidate = Path(os.path.abspath(os.fspath(path)))
    boundary = Path(os.path.abspath(os.fspath(root)))
    if not candidate.is_relative_to(boundary):
        raise Stage2Error(f"native-proposal-{label}-escaped-capture")
    chain = [candidate, *candidate.parents]
    for index, item in enumerate(chain):
        try:
            status = os.lstat(item)
        except OSError as error:
            raise Stage2Error(f"native-proposal-{label}-missing") from error
        attributes = getattr(status, "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(status.st_mode) or (reparse and attributes & reparse):
            raise Stage2Error(f"native-proposal-{label}-alias-forbidden")
        if index == 0 and not stat.S_ISREG(status.st_mode):
            raise Stage2Error(f"native-proposal-{label}-not-regular-file")
        if index > 0 and not stat.S_ISDIR(status.st_mode):
            raise Stage2Error(f"native-proposal-{label}-ancestor-invalid")
    return candidate


def _captured_text(root, relative, expected_sha256, label, *, strip_final=False):
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise Stage2Error(f"native-proposal-{label}-invalid-sha256")
    path = _regular_unaliased(Path(root) / relative, root, label)
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise Stage2Error(f"native-proposal-{label}-unreadable") from error
    if _sha256(raw) != expected_sha256:
        raise Stage2Error(f"native-proposal-{label}-sha256-mismatch")
    if len(raw) > MAX_PROPOSAL_BYTES:
        raise Stage2Error(f"native-proposal-{label}-oversize")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise Stage2Error(f"native-proposal-{label}-not-utf8") from error
    if strip_final:
        text = text.rstrip("\r\n")
    if not text.strip():
        raise Stage2Error(f"native-proposal-{label}-empty")
    return text, _sha256(raw)


def choose_captured_proposal(capture_dir, capture_record):
    """Return authenticated proposal text and its exact capture provenance."""

    if not isinstance(capture_record, dict) or not isinstance(
        capture_record.get("archived_files"), dict
    ):
        raise Stage2Error("native-proposal-capture-record-shape")
    inventory = capture_record["archived_files"]
    if PROPOSAL_PATH in inventory:
        start_files = capture_record.get("workspace_start", {}).get("files", {})
        if START_PROPOSAL_PATH in inventory or (
            isinstance(start_files, dict) and "stage2_proposal.md" in start_files
        ):
            raise Stage2Error("native-proposal-preexisting-input")
        text, digest = _captured_text(
            capture_dir, PROPOSAL_PATH, inventory[PROPOSAL_PATH], "workspace-artifact"
        )
        return {
            "text": text,
            "provenance": {
                "kind": "workspace-artifact",
                "path": PROPOSAL_PATH,
                "sha256": digest,
            },
        }

    final_output = capture_record.get("event_summary", {}).get("final_output")
    if not isinstance(final_output, str) or not final_output.strip():
        raise Stage2Error("native-proposal-final-answer-missing")
    if "final.txt" not in inventory:
        raise Stage2Error("native-proposal-final-answer-not-archived")
    saved, digest = _captured_text(
        capture_dir,
        "final.txt",
        inventory["final.txt"],
        "final-answer",
        strip_final=True,
    )
    if saved != final_output:
        raise Stage2Error("native-proposal-final-answer-mismatch")
    return {
        "text": final_output,
        "provenance": {
            "kind": "final-answer",
            "path": "final.txt",
            "sha256": digest,
        },
    }

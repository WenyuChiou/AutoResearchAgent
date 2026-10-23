"""Verify externally trusted, saved offline replays after a host relocation.

No code from an evidence directory is imported or executed. This receipt is
technical replay evidence, never a Core review or an execution authorization.
"""

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator
from stage1_deliverable import sources
from stage1_deliverable.common import (
    DeliverableError,
    canonical,
    inventory,
    reject_links,
    safe_path,
    sha,
)
from stage1_deliverable.records import timestamp
from .saved_admission_evidence import read_bound_json, valid_input_version
from .json_bytes import decode_json

SCHEMA = (
    Path(__file__).resolve().parents[2] / "schemas/stage1-host-replay.v1.schema.json"
)
OBSERVATION_KEYS = {
    "command",
    "returncode",
    "stdout",
    "stderr",
    "original_sha256",
    "relocated_sha256",
    "network_acquisition",
}


def require(condition, message):
    if not condition:
        raise DeliverableError("host-replay: " + message)


def _bound_json(path, digest):
    """Hash and parse one byte snapshot; never reopen a trusted JSON path."""
    raw = Path(path).read_bytes()
    require(sha(raw) == digest, "JSON bytes differ from trusted external SHA-256")
    value = decode_json(raw.decode("utf-8"))
    # decode_json rejects duplicate keys; also reject NaN, infinity and overflow.
    json.dumps(value, allow_nan=False)
    return value


def exporter_files(root):
    """Read the complete exporter module inventory without executing it."""
    reject_links(root)
    return {
        path.name: sha(safe_path(root, path.name).read_bytes())
        for path in sorted(Path(root).glob("*.py"))
    }


def validator_files():
    """Pin every shipped CLI/schema file and declared dependency requirements."""
    root = SCHEMA.parent.parent
    names = {
        path.relative_to(root).as_posix()
        for directory in (root / "cli", root / "schemas")
        for path in directory.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    } | {"requirements-test.in", "requirements-test.txt"}
    return {name: sha(safe_path(root, name).read_bytes()) for name in sorted(names)}


def _dependencies(runtime):
    # Only the separately pinned exporter may differ. No package, distribution,
    # interpreter byte, SDK merge or Python version check is omitted.
    return {key: value for key, value in runtime.items() if key != "exporter_sha256"}


def _observation(archive, result, mapping, observation, executable):
    require(set(observation) == OBSERVATION_KEYS, "observation fields differ")
    require(
        type(observation["returncode"]) is int
        and observation["returncode"] == 0
        and observation["network_acquisition"] is False
        and observation["original_sha256"]
        == sha((archive / "original.json").read_bytes()),
        "source replay failed or original receipt changed",
    )
    # Reuse every production observation predicate, including argument order and
    # reconstructed relocation digest; only its independently bound interpreter
    # location is parameterized by this opt-in contract.
    sources._validate_observation(
        archive,
        result,
        mapping,
        observation,
        executable,
        saved_observation=observation,
    )
    path = Path(observation["command"][7])
    relocated = sources._relocate(result, path.parent, mapping)
    report = json.loads(observation["stdout"])
    require(
        report.get("valid") is True
        and report.get("errors") == []
        and report.get("receipt_sha256") == relocated["receipt_sha256"]
        and report.get("source_version") == result["source_version"]
        and report.get("result_path") == str(path)
        and report.get("output_dir") == str(path.parent),
        "saved replay report is not a successful bound validation",
    )


class HostReplay:
    """A validated receipt scoped to exactly one immutable package and snapshot."""

    def __init__(self, receipt, digest, package_root):
        self._receipt = deepcopy(receipt)
        self._digest = digest
        self._root = Path(package_root).resolve()
        self._sources = {row["source_id"]: row for row in self._receipt["sources"]}

    def package(self, root, expected_sha256, manifest, runtime):
        receipt = self._receipt
        require(Path(root).resolve() == self._root, "package root changed")
        require(
            expected_sha256 == receipt["canonical_manifest_sha256"],
            "canonical manifest changed",
        )
        require(
            manifest
            == _bound_json(self._root / "provenance_manifest.json", expected_sha256),
            "canonical manifest bytes changed",
        )
        require(
            manifest["runtime"] == receipt["historical_producer"]["runtime"],
            "historical producer runtime changed",
        )
        require(
            runtime == receipt["validator"]["runtime"]
            and validator_files() == receipt["validator"]["files"],
            "current validator code or dependency runtime changed",
        )
        require(
            _dependencies(runtime)
            == _dependencies(receipt["historical_producer"]["runtime"])
            == _dependencies(receipt["replayer"]["runtime"]),
            "replay dependency or interpreter bytes differ",
        )
        require(
            receipt["replayer"]["executable"] == sys.executable,
            "current replay interpreter location differs",
        )
        canonical_sources = manifest["canonical_records"]["sources"]
        require(
            len(self._sources) == len(receipt["sources"]) == len(canonical_sources)
            and set(self._sources) == {row["source_id"] for row in canonical_sources},
            "missing, duplicate or extra source replay",
        )
        for source in canonical_sources:
            self.source(safe_path(self._root, "sources/" + source["source_id"]), source)

    def source(self, archive, source):
        archive = Path(archive)
        require(
            archive.resolve()
            == safe_path(self._root, "sources/" + source["source_id"]),
            "source archive outside bound package",
        )
        row = self._sources.get(source["source_id"])
        require(
            row is not None
            and all(
                row[key] == source[key]
                for key in ("source_id", "work_id", "version_id")
            ),
            "source identity differs",
        )
        actual = inventory(archive)
        # inventory() excludes provenance_manifest.json; such an undeclared file
        # must not disappear from this exact source archive check.
        require(
            not (archive / "provenance_manifest.json").exists()
            and actual == row["files"],
            "source inventory or bytes changed",
        )
        require(
            actual["original.json"] == source["result_sha256"]
            and actual["validation.json"] == row["historical_observation_sha256"],
            "source observation or original binding differs",
        )
        result = _bound_json(archive / "original.json", source["result_sha256"])
        sources.validate_receipt_shape(result)
        require(
            result["schema_version"] == "source-fetch-result/v1"
            and sources.receipt_digest(result) == result["receipt_sha256"],
            "original source receipt differs",
        )
        mapping = sources.artifact_map(result)
        require(
            set(actual) == {*mapping.values(), "original.json", "validation.json"},
            "unrecognized or missing raw artifact",
        )
        for item in [result, *result["attempts"]]:
            for path_key, hash_key in (
                ("raw_path", "raw_sha256"),
                ("extracted_text_path", "extracted_text_sha256"),
            ):
                if item.get(path_key):
                    raw = safe_path(archive, mapping[item[path_key]]).read_bytes()
                    sources.reject_secrets(raw)
                    require(sha(raw) == item[hash_key], "raw/text source hash changed")
                    if "response_bytes" in item:
                        require(
                            len(raw) == item["response_bytes"],
                            "raw source length changed",
                        )
        for attempt in result["attempts"]:
            timestamp(attempt["requested_at"])
            if attempt.get("received_at"):
                timestamp(attempt["received_at"])
        old = _bound_json(
            archive / "validation.json", row["historical_observation_sha256"]
        )
        fresh = row["observation"]
        _observation(
            archive,
            result,
            mapping,
            old,
            self._receipt["historical_producer"]["executable"],
        )
        _observation(
            archive, result, mapping, fresh, self._receipt["replayer"]["executable"]
        )
        sources._validate_observation(
            archive,
            result,
            mapping,
            fresh,
            self._receipt["historical_producer"]["executable"],
            saved_observation=old,
        )
        times = [
            row["started_at"],
            json.loads(fresh["stdout"])["checked_at"],
            row["ended_at"],
        ]
        for value in times:
            timestamp(value)
        require(
            sorted(
                datetime.fromisoformat(value.replace("Z", "+00:00")) for value in times
            )
            == [
                datetime.fromisoformat(value.replace("Z", "+00:00")) for value in times
            ],
            "replay observation time outside process interval",
        )
        return result, mapping, deepcopy(fresh)

    def check_snapshot(self, root, snapshot_ref):
        """Rebind a verified context to the same immutable receiving inputs."""
        require(
            self._receipt["snapshot_ref"] == snapshot_ref, "snapshot reference differs"
        )
        snapshot = read_bound_json(root, snapshot_ref)
        require(
            valid_input_version(self._receipt["input_version"])
            and valid_input_version(snapshot["input_version"]),
            "typed input version required",
        )
        require(
            (self._receipt["project_id"], self._receipt["input_version"])
            == (snapshot["project_id"], snapshot["input_version"])
            and type(self._receipt["input_version"]) is type(snapshot["input_version"]),
            "project/input differs",
        )
        ref = snapshot["bindings"]["deliverable"]
        require(
            self._receipt["canonical_manifest_sha256"] == ref["sha256"]
            and safe_path(root, ref["path"]).parent.resolve() == self._root,
            "snapshot package differs",
        )

    def evidence(self):
        return {
            "kind": "HostReplayReceipt",
            "schema_version": "1.0.0",
            "sha256": self._digest,
            "source_count": len(self._sources),
            "mode": "saved-offline-replay",
            "new_source_execution": False,
            "core_acceptance": False,
        }


def resolve_host_replay(
    root,
    snapshot_ref,
    *,
    host_replay_receipt=None,
    trusted_host_replay_sha256=None,
    historical_exporter_root=None,
    replayer_exporter_root=None,
    verified_host_replay=None,
):
    """Resolve explicit host trust once; never accept a context from browser JSON."""
    inputs = (
        host_replay_receipt,
        trusted_host_replay_sha256,
        historical_exporter_root,
        replayer_exporter_root,
    )
    require(
        all(value is None for value in inputs)
        or all(value is not None for value in inputs),
        "all host replay inputs required",
    )
    if verified_host_replay is not None:
        require(
            type(verified_host_replay) is HostReplay
            and all(value is None for value in inputs),
            "verified context conflicts with explicit host trust inputs",
        )
        verified_host_replay.check_snapshot(root, snapshot_ref)
        return verified_host_replay
    if host_replay_receipt is None:
        return None
    return load_host_replay(
        host_replay_receipt,
        trusted_host_replay_sha256,
        root,
        snapshot_ref,
        historical_exporter_root=historical_exporter_root,
        replayer_exporter_root=replayer_exporter_root,
    )


def load_host_replay(
    receipt_path,
    trusted_sha256,
    evidence_root,
    snapshot_ref,
    *,
    historical_exporter_root,
    replayer_exporter_root,
):
    """Validate separate trust input and original bytes before admitting a replay."""
    reject_links(receipt_path)
    require(type(trusted_sha256) is str, "trusted external SHA-256 required")
    receipt = _bound_json(receipt_path, trusted_sha256)
    schema = _bound_json(
        SCHEMA, receipt["validator"]["files"]["schemas/" + SCHEMA.name]
    )
    errors = list(Draft202012Validator(schema).iter_errors(receipt))
    require(not errors, "receipt schema invalid")
    require(
        valid_input_version(receipt["input_version"]), "typed input version required"
    )
    require(receipt["snapshot_ref"] == snapshot_ref, "snapshot reference differs")
    snapshot = read_bound_json(evidence_root, snapshot_ref)
    require(
        valid_input_version(snapshot["input_version"]), "typed input version required"
    )
    require(
        (receipt["project_id"], receipt["input_version"])
        == (snapshot["project_id"], snapshot["input_version"])
        and type(receipt["input_version"]) is type(snapshot["input_version"]),
        "project/input differs",
    )
    ref = snapshot["bindings"]["deliverable"]
    require(
        receipt["canonical_manifest_sha256"] == ref["sha256"],
        "snapshot canonical manifest differs",
    )
    manifest = read_bound_json(evidence_root, ref)
    for name, root in (
        ("historical_producer", historical_exporter_root),
        ("replayer", replayer_exporter_root),
    ):
        actual = exporter_files(root)
        require(
            bool(actual)
            and actual == receipt[name]["exporter_files"]
            and sha(canonical(actual)) == receipt[name]["runtime"]["exporter_sha256"],
            name + " source code inventory changed",
        )
    package_root = safe_path(evidence_root, ref["path"]).parent
    context = HostReplay(receipt, trusted_sha256, package_root)
    context.package(package_root, ref["sha256"], manifest, sources.runtime_binding())
    return context

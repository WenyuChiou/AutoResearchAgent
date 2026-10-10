"""Explicit query registration for a local host; never infer it from text rights."""

from copy import deepcopy
import os
from pathlib import Path

from .planned_query_contract import KEY, inspect_registration, tree_sha
from .planned_queries import PlannedQueryService


class QueryRegistration:
    def __init__(self, source, authority, path, expected_sha256):
        self.source, self.authority = source, authority
        self.path = source.unlinked(path).resolve()
        self.sha = expected_sha256
        self.document = source.decode(source.pinned(self.path, self.sha, 65536))
        self._inspect()

    def _inspect(self):
        source, authority = self.source, self.authority
        authority.verify(
            dict(spec_sha256=authority.sha, spec=authority.spec), full=True
        )
        value = source.decode(source.pinned(self.path, self.sha, 65536))
        source.require(value == self.document, "query registration changed")
        source.require(
            set(value) == {"kind", "schema_version", "project_ref", "registration"}
            and value["kind"] == "LocalAtlasQueryRegistration"
            and value["schema_version"] == "1.0.0"
            and value["project_ref"] == authority.spec["project_ref"],
            "independent query registration required",
        )
        ref, item = value["project_ref"], value["registration"]
        source.require(
            isinstance(item, dict)
            and all(
                item.get(k) == authority.spec[k]
                for k in ("project_id", "index_sha256", "input_version", "principals")
            )
            and item.get("execution_source_root") == authority.repo.as_posix()
            and item.get("execution_source_sha256")
            == source.digest(source.canonical(authority.manifest["plugin_files"])),
            "query/native source or principal differs",
        )
        item, permit, _, pin = inspect_registration(ref, item)
        stages = authority.permit["stage_inputs"]
        parent = stages.get(1, stages.get("1"))
        source.require(
            isinstance(parent, dict)
            and Path(parent["ledger_root"]).resolve().as_posix()
            == item["parent_ledger_root"]
            and tree_sha(parent["ledger_root"]) == item["parent_ledger_sha256"],
            "query/native Stage1 parent differs",
        )
        # Both mutable query locations are independent of every native input and
        # future native attempt. The query service checks its own source roots.
        roots = [
            authority.repo,
            Path(authority.spec["source_root"]),
            Path(authority.permit["attempt_root"]),
        ]
        roots.extend(
            source.unlinked(value).resolve()
            for stage in stages.values()
            for name, value in (stage or {}).items()
            if name.endswith("_root") and value is not None
        )
        roots.extend(Path(p) for p in pin["code_identity"]["roots"])
        config = authority.permit["host_config"]
        host = source.decode(source.pinned(config["path"], config["sha256"]))
        source.require(
            set(host) == {"views"}
            and isinstance(host["views"], list)
            and 1 <= len(host["views"]) <= 16,
            "pinned host views required",
        )
        for view in host["views"]:
            manifest = source.unlinked(view["manifest"]).resolve()
            source.pinned(manifest, view["sha256"], 1024 * 1024)
            roots.append(manifest.parent)
        protected = [
            self.path,
            Path(authority.path),
            Path(authority.permit_path),
            *[
                Path(authority.permit[k]["path"])
                for k in ("host_config", "user_config", "source_manifest")
            ],
            Path(authority.spec["executable"]),
            Path(item["brief_path"]),
            Path(item["permit_path"]),
            Path(pin["config"]["path"]),
            *[Path(p) for p in pin["code_identity"]["files"]],
            *[Path(p) for p in pin["code_identity"]["absent_paths"]],
        ]
        ledger = Path(item["ledger_root"])
        database = Path(item["control_store_path"])
        owner = ledger.parent / (
            ".planned-query-owner-"
            + source.digest(os.path.normcase(str(ledger)).encode())
            + ".sqlite3"
        )
        writers = [
            Path(str(database) + suffix)
            for suffix in ("", "-wal", "-shm", "-journal", ".created")
        ]
        writers.extend(
            Path(str(owner) + suffix) for suffix in ("", "-wal", "-shm", "-journal")
        )
        pid = "planned-query-" + source.digest(ref.encode())[:32]
        project_owner = database.with_name(
            database.name + ".owner-" + source.digest(pid.encode()) + ".sqlite3"
        )
        writers.extend(
            Path(str(project_owner) + suffix)
            for suffix in ("", "-wal", "-shm", "-journal")
        )
        protected = [source.unlinked(p).resolve() for p in protected]
        for mutable in (ledger, *writers):
            mutable = source.unlinked(mutable).resolve()
            source.require(
                all(
                    not mutable.is_relative_to(r) and not r.is_relative_to(mutable)
                    for r in roots
                )
                and all(
                    mutable != p
                    and (mutable != ledger or not p.is_relative_to(mutable))
                    for p in protected
                ),
                "query/native storage overlap",
            )
        return ref, item, permit, pin

    def source_proof(self, claim):
        ref, item, _, _ = self._inspect()
        self.source.require(
            isinstance(claim, dict)
            and set(claim) == {"project_ref", "execution_source_sha256", "phase"}
            and claim["project_ref"] == ref
            and claim["execution_source_sha256"] == item["execution_source_sha256"],
            "query source claim differs",
        )
        return dict(
            repo=self.authority.repo.as_posix(),
            files=deepcopy(self.authority.manifest["plugin_files"]),
        )

    def admit(self, event):
        ref, item, permit, pin = self._inspect()
        require = self.source.require
        require(
            isinstance(event, dict)
            and set(event)
            == {
                "project_ref",
                "principal",
                "permit_sha256",
                "execution_source_sha256",
                "offer",
                "client_key",
                "budget",
                "phase",
            }
            and event["project_ref"] == ref
            and event["principal"] in item["principals"]
            and event["permit_sha256"] == item["permit_sha256"]
            and event["execution_source_sha256"] == item["execution_source_sha256"]
            and isinstance(event["client_key"], str)
            and KEY.fullmatch(event["client_key"]),
            "query admission identity differs",
        )
        offer, budget = event["offer"], event["budget"]
        require(
            isinstance(offer, dict)
            and offer.get("project_ref") == ref
            and offer.get("principal") == event["principal"]
            and all(
                offer.get(k) == item[k]
                for k in (
                    "index_sha256",
                    "input_version",
                    "brief_sha256",
                    "plan_sha256",
                    "runtime_sha256",
                    "execution_source_sha256",
                    "permit_sha256",
                )
            )
            and offer.get("planned_id") in permit["planned_ids"]
            and offer.get("backend") in permit["backends"]
            and offer.get("timeout_seconds") == pin["timeout_seconds"]
            and offer.get("execution_authority") == "separate-research-permit"
            and isinstance(budget, dict)
            and set(budget) == {"attempts", "seconds"}
            and type(budget["attempts"]) is int
            and 1 <= budget["attempts"] <= permit["max_attempts"]
            and type(budget["seconds"]) in (int, float)
            and 0 < budget["seconds"] <= permit["max_reserved_seconds"],
            "query admission offer or budget differs",
        )
        phase = event["phase"]
        require(
            phase == "before-runner"
            or isinstance(phase, dict)
            and set(phase) == {"query_id", "backend", "argv", "runtime_sha256"}
            and phase["backend"] == offer["backend"]
            and phase["runtime_sha256"] == item["runtime_sha256"],
            "query admission phase differs",
        )
        # PlannedQueryService independently rechecks exact argv, owner, journal,
        # intake/permit expiry and raw sources after this return, before I/O.
        return True

    def create_service(self, authenticate):
        ref, item, _, _ = self._inspect()
        return PlannedQueryService(
            item["control_store_path"],
            registrations={ref: item},
            authenticate=authenticate,
            admit=self.admit,
            verify_source=self.source_proof,
        )

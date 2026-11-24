"""Durable Host-owned references to native, already saved Stage 3 evidence."""

from contextlib import closing
from pathlib import Path
import sqlite3

from stage3_plan.contracts import Stage3Error, canonical_bytes
from stage3_plan.preparation import closed, file_binding, sha256
from stage3_plan.storage import decode_json, inspect_completed_package, private_output
from stage3_plan.workflow import MAX_CHECKPOINT_REVISIONS

from stage3_plan_review_readback import plan_review_identity, read_plan_review


class Stage3CheckpointIndex:
    """Index archived native jobs; authenticate project views before using it.

    The caller supplies the job's pinned completed receipt from
    PlanningJobs.inspect_saved and the owner's explicit archived references.
    The Host chooses the current or authorized historical view and maintains
    its normal project lock. This index never selects a current plan itself.
    """

    def __init__(self, database, *, archive_root):
        self.database = private_output(database)
        self.archive_root = private_output(archive_root)
        if not self.database.parent.is_dir() or not self.archive_root.is_dir():
            raise Stage3Error("checkpoint index and archive roots must exist")

    def _reference(self, value):
        closed(value, {"path", "sha256"}, "checkpoint index reference")
        sha256(value["sha256"])
        if not isinstance(value["path"], (str, Path)):
            raise Stage3Error("checkpoint index reference requires an absolute path")
        path = Path(value["path"])
        if not path.is_absolute():
            raise Stage3Error("checkpoint index reference requires an absolute path")
        path = private_output(path)
        if not path.is_relative_to(self.archive_root):
            raise Stage3Error("checkpoint index reference is outside the Host archive")
        return {"path": str(path), "sha256": value["sha256"]}

    def _database(self, *, write):
        path = private_output(self.database)
        if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
            raise Stage3Error("checkpoint index requires a regular private database")
        mode = "rwc" if write else "ro"
        return sqlite3.connect(f"{path.as_uri()}?mode={mode}", uri=True)

    def _get(self, connection, identity):
        schema = connection.execute(
            "SELECT type, name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
        ).fetchall()
        if not schema:
            # SQLite may have created its file before the first transaction
            # committed the schema, or left this file after an interruption.
            return None
        if schema != [("table", "stage3_checkpoint_bindings_v1")]:
            raise Stage3Error("unexpected checkpoint index schema")
        row = connection.execute(
            "SELECT checkpoint, decision FROM stage3_checkpoint_bindings_v1 "
            "WHERE identity = ?",
            (canonical_bytes(identity),),
        ).fetchone()
        if row is None:
            return None
        return {
            "identity": identity,
            "checkpoint": self._reference(decode_json(row[0])),
            "decision": None
            if row[1] is None
            else self._reference(decode_json(row[1])),
        }

    def lookup(self, identity):
        """Return the exact private binding for #510 without creating an index."""
        if identity is None or not self.database.exists():
            return None
        with closing(self._database(write=False)) as connection:
            return self._get(connection, identity)

    def _lineage(self, anchor, checkpoint):
        # Follow only same-plan attachments from this job's originally saved
        # checkpoint. The readback then verifies the complete native workflow.
        lineage = []
        while len(lineage) < MAX_CHECKPOINT_REVISIONS:
            row = file_binding(checkpoint["path"], checkpoint["sha256"])
            if not isinstance(row, dict):
                raise Stage3Error("archived workflow checkpoint must be an object")
            lineage.append((checkpoint, row))
            if checkpoint == anchor:
                return lineage
            if row.get("action") not in {"attach-review", "prepare-ab"}:
                break
            checkpoint = self._reference(row.get("parent"))
        raise Stage3Error("checkpoint does not descend from the saved planning job")

    def publish(self, view, saved_job, *, checkpoint=None, decision=None):
        """Register or rebuild one plan's index entry from pinned archive bytes.

        Keeping the same review preserves an existing decision. A new review
        can have its own decision. Conflicting decisions for one unchanged
        review require an explicit decision succession protocol.
        """
        identity = plan_review_identity(view)
        result = saved_job.get("result") or {}
        plan = result.get("plan") or {}
        if (
            identity is None
            or saved_job.get("status") != "completed"
            or saved_job.get("inspection_scope")
            != "pinned-completed-artifact-read-only"
            or saved_job.get("key") != view["job"]["key"]
            or saved_job.get("request_sha256") != identity["job_request_sha256"]
            or result.get("outcome") != "saved"
            or plan.get("manifest_sha256") != identity["plan_manifest_sha256"]
        ):
            raise Stage3Error(
                "checkpoint index requires the displayed plan's pinned job"
            )
        anchor = self._reference(result.get("checkpoint"))
        checkpoint = anchor if checkpoint is None else self._reference(checkpoint)
        lineage = self._lineage(anchor, checkpoint)
        if lineage[-1][1].get("bindings", {}).get("plan") != plan:
            raise Stage3Error("saved job checkpoint does not bind its archived plan")
        package = private_output(plan["package"])
        if not package.is_relative_to(self.archive_root):
            raise Stage3Error("planning package is outside the Host archive")
        saved = inspect_completed_package(package, identity["plan_manifest_sha256"])
        origin = saved["artifacts"]["request.json"]["intake"].get("input_origin") or {}
        if origin.get("kind") != "projecthost-ui-submission" or canonical_bytes(
            [
                origin.get(name)
                for name in ("project_ref", "input_version", "request_sha256")
            ]
        ) != canonical_bytes(
            [
                identity[name]
                for name in ("project_ref", "input_version", "selection_request_sha256")
            ]
        ):
            raise Stage3Error("archived selection does not bind this project or input")
        previous = self.lookup(identity)
        decision = None if decision is None else self._reference(decision)

        if previous is not None:
            current = next(
                (row for ref, row in lineage if ref == previous["checkpoint"]), None
            )
            if current is None:
                raise Stage3Error("checkpoint index refuses a rollback or fork")
            # Compare review across the whole suffix. Returning to an old review
            # after an intervening replacement does not restore an old decision.
            if previous["decision"] is not None:
                review = current["bindings"]["review"]
                for ref, row in lineage:
                    if row["bindings"]["review"] != review:
                        break
                    if ref == previous["checkpoint"]:
                        if decision is not None and decision != previous["decision"]:
                            raise Stage3Error("checkpoint index decision conflicts")
                        decision = previous["decision"]
                        break

        binding = {"identity": identity, "checkpoint": checkpoint, "decision": decision}
        read_plan_review(view, trusted_binding=binding)
        with closing(self._database(write=True)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._get(connection, identity)
            if current != binding:
                if current != previous:
                    raise Stage3Error(
                        "checkpoint index changed during publication; retry"
                    )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS stage3_checkpoint_bindings_v1 ("
                    "identity BLOB PRIMARY KEY, checkpoint BLOB NOT NULL, decision BLOB)"
                )
                connection.execute(
                    "INSERT INTO stage3_checkpoint_bindings_v1 VALUES (?, ?, ?) "
                    "ON CONFLICT(identity) DO UPDATE SET "
                    "checkpoint = excluded.checkpoint, decision = excluded.decision",
                    (
                        canonical_bytes(identity),
                        canonical_bytes(checkpoint),
                        None if decision is None else canonical_bytes(decision),
                    ),
                )
        return binding

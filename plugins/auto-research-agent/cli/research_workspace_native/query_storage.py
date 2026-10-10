"""One canonical permit budget journal and exclusive mutable ledger owner."""

import os
from pathlib import Path
import sqlite3
import stat

from stage1_deliverable.common import (
    canonical,
    private_output,
    reject_links,
    safe_path,
    sha,
)
from .planned_query_contract import require


def _regular_single_link(path):
    reject_links(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    require(stat.S_ISREG(info.st_mode), "query-mutable-file-required")
    require(info.st_nlink == 1, "query-mutable-hardlink-refused")


def check_writer_paths(roots, database=None, projects=()):
    """Reject shared inodes for every existing query SQLite write target."""
    paths = []
    for root in roots:
        reject_links(root)
        root = root.resolve()
        owner = root.parent / (
            ".planned-query-owner-"
            + sha(os.path.normcase(str(root)).encode())
            + ".sqlite3"
        )
        paths.extend(
            Path(str(owner) + suffix) for suffix in ("", "-wal", "-shm", "-journal")
        )
    if database is not None:
        database = Path(database)
        paths.extend(
            Path(str(database) + suffix)
            for suffix in ("", "-wal", "-shm", "-journal", ".created")
        )
        for project in projects:
            owner = database.parent / (
                database.name + ".owner-" + sha(project.encode()) + ".sqlite3"
            )
            paths.extend(
                Path(str(owner) + suffix) for suffix in ("", "-wal", "-shm", "-journal")
            )
    for path in paths:
        _regular_single_link(path)


def check_mutable_storage(roots, database=None, projects=()):
    """A byte-identical clone must still own every mutable ledger file."""
    roots = [Path(root) for root in roots]
    check_writer_paths(roots, database, projects)
    for root in roots:
        reject_links(root)
        require(root.is_dir(), "query-working-root-required")
        for base, directories, names in os.walk(root, followlinks=False):
            for name in directories:
                path = Path(base) / name
                reject_links(path)
                require(
                    stat.S_ISDIR(path.lstat().st_mode),
                    "query-working-directory-required",
                )
            for name in names:
                _regular_single_link(Path(base) / name)


def budget_path(store_path, prepared):
    raw = Path(store_path)
    require(raw.is_absolute(), "absolute-query-store-required", 400)
    database = private_output(raw).resolve()
    require(
        all(
            item["control_store_path"] == database.as_posix()
            for _, item, _, _, _ in prepared
        ),
        "query-permit-store-differs",
    )
    for suffix in ("", "-wal", "-shm", "-journal", ".created"):
        safe_path(database.parent, database.name + suffix)
    immutable = [
        Path(item[name])
        for _, item, _, _, _ in prepared
        for name in ("parent_ledger_root", "plan_root", "execution_source_root")
    ]
    working = [Path(item["ledger_root"]) for _, item, _, _, _ in prepared]
    require(
        all(
            not a.is_relative_to(b) and not b.is_relative_to(a)
            for i, a in enumerate(working)
            for b in working[i + 1 :]
        ),
        "query-working-roots-overlap",
    )
    require(
        all(
            not a.is_relative_to(b) and not b.is_relative_to(a)
            for a in working
            for b in immutable
        ),
        "query-working-source-overlap",
    )
    require(
        all(not database.is_relative_to(root) for root in immutable + working),
        "query-database-input-overlap",
    )
    require(
        all(
            database
            not in (
                Path(item["brief_path"]),
                Path(item["permit_path"]),
                Path(pin["config"]["path"]),
            )
            for _, item, _, _, pin in prepared
        ),
        "query-database-input-overlap",
    )
    check_mutable_storage(
        working,
        database,
        ["planned-query-" + sha(ref.encode())[:32] for ref, *_ in prepared],
    )
    marker = safe_path(database.parent, database.name + ".created")
    expected = canonical(
        dict(
            kind="Stage1QueryBudgetJournal",
            schema_version="1.0.0",
            registrations={ref: item for ref, item, _, _, _ in prepared},
        )
    )
    if database.exists():
        require(
            marker.is_file()
            and marker.stat().st_size == len(expected)
            and marker.read_bytes() == expected,
            "query-budget-marker-differs",
        )
    else:
        require(not marker.exists(), "query-budget-journal-missing")
        from .planned_query_contract import tree_sha

        require(
            all(
                tree_sha(item["ledger_root"]) == item["parent_ledger_sha256"]
                for _, item, _, _, _ in prepared
            ),
            "query-clone-parent-bytes-differ",
        )
        database.parent.mkdir(parents=True, exist_ok=True)
        with marker.open("xb") as stream:
            stream.write(expected)
            stream.flush()
            os.fsync(stream.fileno())
    return database


class LedgerOwners:
    def __init__(self, roots):
        roots = list(roots)
        check_mutable_storage(roots)
        self.connections = []
        try:
            for root in roots:
                root = root.resolve()
                name = (
                    ".planned-query-owner-"
                    + sha(os.path.normcase(str(root)).encode())
                    + ".sqlite3"
                )
                for suffix in ("", "-wal", "-shm", "-journal"):
                    safe_path(root.parent, name + suffix)
                connection = sqlite3.connect(
                    root.parent / name,
                    timeout=0,
                    isolation_level=None,
                    check_same_thread=False,
                )
                self.connections.append(connection)
                connection.execute("BEGIN IMMEDIATE")
        except BaseException as error:
            try:
                self.close()
            except BaseException:
                error.query_owners = self
            raise

    def close(self):
        for connection in self.connections:
            connection.close()
        self.connections.clear()

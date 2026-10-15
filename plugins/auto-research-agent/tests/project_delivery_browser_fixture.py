"""Lease-bound authored source fixture for real UI delivery, never research.

Reuse the HTTP case's actual Core ledger, SQLite and saved sources. Reading,
checkpoint, preparation and delivery are left to browser actions. SDK dependency
bytes, real search/model/native execution and research acceptance are not attested.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def emit(value):
    print(json.dumps(value, ensure_ascii=True, allow_nan=False), flush=True)


def private_stop(path, repo):
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise ValueError("fresh absolute stop file required")
    parent = path.parent.resolve(strict=True)
    if parent != path.parent or path.is_relative_to(repo):
        raise ValueError("stop file must be outside the checkout")
    for ancestor in (parent, *parent.parents):
        if (ancestor / ".git").exists():
            raise ValueError("stop file must be outside Git")
    return path


def inventory(repo, helper, executed):
    rows = dict(executed)
    for source in (Path(__file__).resolve(strict=True), helper):
        rows[str(source)] = digest(source.read_bytes())
    result = []
    for name, expected in sorted(rows.items()):
        source = Path(name)
        if (
            source.resolve(strict=True) != source
            or digest(source.read_bytes()) != expected
        ):
            raise ValueError("executed owned source changed")
        result.append({"path": source.relative_to(repo).as_posix(), "sha256": expected})
    return result


def summary(case, baseline):
    fixture = case.fixture
    events = fixture["ledger"].events()
    case.assertEqual(events[: len(baseline)], baseline)
    case.case.runner.assert_not_called()
    overview = case.host.overview(case.token, fixture["ref"])
    project = overview["project"]
    stage = overview["stage1"]
    artifact = stage["delivery"]["canonical_package"]
    atlas_summary = None
    if artifact is not None:
        atlas = case.host.project_stage1_atlas.read(
            case.token,
            fixture["ref"],
            input_version=project["input_version"],
            revision=project["revision"],
            artifact_ref=artifact["artifact_ref"],
            manifest_sha256=artifact["manifest_sha256"],
        )
        atlas_summary = {
            "index_sha256": atlas["index_sha256"],
            "work_ids": [row["work_id"] for row in atlas["payload"]["index"]["papers"]],
            "unknown_retained": "Unknown" in str(atlas["payload"]["index"]),
            "stage2_input": atlas["stage2_input"],
        }
    return {
        "project_ref": fixture["ref"],
        "input_version": project["input_version"],
        "revision": project["revision"],
        "brief_sha256": project["brief_sha256"],
        "readings": len(case.reading_entries()),
        "baseline_events": len(baseline),
        "events": len(events),
        "appended_event_types": [
            row["payload"]["kind"] for row in events[len(baseline) :]
        ],
        "original_events_retained": True,
        "checkpoint": stage["checkpoint"],
        "canonical_package": artifact,
        "atlas": atlas_summary,
        "stage1_complete": stage["delivery"]["stage1_complete"],
        "scientific_quality_scored": False,
        "native_calls": 0,
        "model_calls": 0,
        "search_calls": case.case.runner.call_count,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop-file", type=Path, required=True)
    args = parser.parse_args()
    own = Path(__file__).resolve(strict=True)
    repo = own.parents[3]
    plugin = repo / "plugins/auto-research-agent"
    if own != plugin / "tests/project_delivery_browser_fixture.py":
        raise ValueError("fixture must belong to the complete candidate")
    stop = private_stop(args.stop_file, repo)
    helper = plugin / "tests/browser/project-intake-fixture.py"
    helper_raw = helper.read_bytes()
    namespace = {"__name__": "delivery_raw_loader", "__file__": str(helper)}
    exec(compile(helper_raw, str(helper), "exec"), namespace)
    executed = namespace["EXECUTED_SOURCES"]
    executed[str(helper)] = digest(helper_raw)
    roots = (plugin / "cli", plugin / "tests")
    sys.path[:0] = [str(path) for path in roots]
    sys.dont_write_bytecode = True
    sys.meta_path.insert(0, namespace["RawSources"](roots))
    from stage1_ledger.journal import canonical
    from test_project_source_reading_http import ProjectSourceReadingHttpTests

    case = ProjectSourceReadingHttpTests(methodName="runTest")
    class_ready = False
    result = None
    failure = None
    try:
        case.setUpClass()
        class_ready = True
        case.setUp()
        # The reused test injects these after host construction. Describe those
        # actual services for frontend bootstrap; no production guard is changed.
        case.host.project_stage1_records = case.case.producer
        case.host.host_binding.update(
            project_stage1_saved_records=True,
            project_stage1_saved_claim_review=True,
            project_stage1_reading_review=True,
        )
        case.host._assets["/host-binding.json"] = canonical(case.host.host_binding)
        baseline = case.fixture["ledger"].events()
        case.case.runner.assert_not_called()
        case.assertEqual(case.reading_entries(), [])
        works = [
            {
                key: paper[key]
                for key in ("work_id", "title", "version_id", "source_ids")
            }
            for records, _ in case.fixture["pairs"]
            for paper in records["papers"]
        ]
        emit(
            {
                "kind": "Stage1DeliveryBrowserFixture",
                "url": case.host.expected_origin + "/projects.html",
                "project_ref": case.fixture["ref"],
                "works": works,
                "baseline_readings": 0,
                "baseline_events": len(baseline),
                "lease_seconds": 180,
                "native_calls": 0,
                "model_calls": 0,
                "search_calls": case.case.runner.call_count,
                "source_inventory": inventory(repo, helper, executed),
                "scope": "authored-saved-source-engineering-only",
            }
        )
        deadline = time.monotonic() + 180
        while not stop.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        expired = not stop.exists()
        if not expired and (
            stop.is_symlink()
            or stop.resolve(strict=True) != stop
            or not stop.is_file()
            or stop.stat().st_size > 64
        ):
            raise ValueError("invalid stop file")
        result = summary(case, baseline)
        result.update(
            lease_expired=expired,
            source_inventory=inventory(repo, helper, executed),
        )
        if expired:
            raise TimeoutError("fixture lease expired")
    except Exception as exc:
        failure = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        if hasattr(case, "worker"):
            case.stop()
        if hasattr(case, "case"):
            case.assertTrue(case.case.doCleanups(), "nested fixture cleanup failed")
        case.assertTrue(case.doCleanups(), "HTTP fixture cleanup failed")
        if class_ready:
            case.tearDownClass()
        case.doClassCleanups()
        if hasattr(case, "worker"):
            case.assertFalse(case.worker.is_alive())
        if hasattr(case, "case") and hasattr(case.case, "runner"):
            case.case.runner.assert_not_called()
    emit(
        {
            "kind": "Stage1DeliveryBrowserFixtureStopped",
            **(result or {}),
            "cleanup_complete": True,
            "failure": failure,
        }
    )
    return 1 if failure is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())

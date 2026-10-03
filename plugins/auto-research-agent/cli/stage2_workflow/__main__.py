"""Offline Stage 2 workflow records; native Codex still executes research."""

import argparse
import json
from pathlib import Path
import sys

from stage2_check.contracts import decode_json
from stage2_common import Stage2Error

from .orchestration import prepare_review_batch, reconcile_batch
from .delivery import build_delivery, inspect_delivery
from .interaction import record_interaction
from .import_stage1 import build_stage2_seed
from .exploratory import build_exploratory_seed
from .store import (
    add_snapshot,
    finish_action,
    initialize_workflow,
    inspect_workflow,
    start_action,
)


def _read(path):
    return decode_json(Path(path).read_bytes(), str(path))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m stage2_workflow")
    commands = parser.add_subparsers(dest="command", required=True)
    handoff = commands.add_parser(
        "import-stage1", help="validate Stage 1 and build an unstarted Stage 2 seed"
    )
    handoff.add_argument("--deliverable", required=True)
    handoff.add_argument("--deliverable-manifest-sha256", required=True)
    handoff.add_argument("--handoff", required=True)
    handoff.add_argument("--handoff-sha256", required=True)
    handoff.add_argument("--brief", required=True)
    handoff.add_argument("--resources", required=True)
    handoff.add_argument("--output", required=True)
    exploratory = commands.add_parser(
        "import-stage1-exploratory",
        help="build a non-sufficient Stage 2 seed from a reviewed Stage 1 deliverable",
    )
    exploratory.add_argument("--deliverable", required=True)
    exploratory.add_argument("--deliverable-manifest-sha256", required=True)
    exploratory.add_argument("--acceptance", required=True)
    exploratory.add_argument("--acceptance-sha256", required=True)
    exploratory.add_argument("--brief", required=True)
    exploratory.add_argument("--resources", required=True)
    exploratory.add_argument("--output", required=True)
    init = commands.add_parser(
        "init", help="save the first immutable evidence snapshot"
    )
    init.add_argument("--packet", required=True)
    init.add_argument("--source-root", required=True)
    init.add_argument("--output", required=True)
    init.add_argument("--settings", required=True)
    init.add_argument("--policy-ref", required=True)
    init.add_argument("--expected-packet-sha256")
    show = commands.add_parser(
        "inspect", help="revalidate records and saved source bytes"
    )
    show.add_argument("--run", required=True)
    show.add_argument("--expected-head")
    snapshot = commands.add_parser(
        "snapshot", help="append evidence and invalidate prior checks"
    )
    snapshot.add_argument("--run", required=True)
    snapshot.add_argument("--packet", required=True)
    snapshot.add_argument("--source-root", required=True)
    snapshot.add_argument("--reason", required=True)
    snapshot.add_argument("--impact", required=True)
    snapshot.add_argument("--expected-head", required=True)
    start = commands.add_parser(
        "start", help="record action intent without invoking a model or tool"
    )
    start.add_argument("--run", required=True)
    start.add_argument("--action-id", required=True)
    start.add_argument("--kind", required=True)
    start.add_argument("--inputs", required=True)
    start.add_argument("--settings", required=True)
    start.add_argument("--expected-head", required=True)
    finish = commands.add_parser(
        "finish", help="save result artifacts and the actual terminal state"
    )
    finish.add_argument("--run", required=True)
    finish.add_argument("--action-id", required=True)
    finish.add_argument(
        "--status",
        required=True,
        choices=["complete", "failed", "unavailable", "empty", "interrupted"],
    )
    finish.add_argument("--artifacts", required=True)
    finish.add_argument("--cost")
    finish.add_argument("--error")
    finish.add_argument("--expected-head", required=True)
    plan = commands.add_parser("review-plan", help="prepare isolated review views")
    plan.add_argument("--screening", required=True)
    plan.add_argument("--seed", required=True)
    reconcile = commands.add_parser("reconcile", help="check local review results")
    reconcile.add_argument("--batch", required=True)
    reconcile.add_argument("--reviews", required=True)
    reconcile.add_argument("--resolutions", required=True)
    deliver = commands.add_parser("deliver", help="build a versioned proposal package")
    for name in ("batch", "reviews", "resolutions"):
        deliver.add_argument("--" + name, required=True)
    for command in (plan, reconcile, deliver):
        command.add_argument("--run", required=True)
        command.add_argument("--expected-head", required=True)
        command.add_argument("--output", required=True)
    delivery_check = commands.add_parser(
        "inspect-delivery", help="verify a retained proposal receipt"
    )
    delivery_check.add_argument("--delivery", required=True)
    delivery_check.add_argument("--manifest-sha256", required=True)
    human = commands.add_parser(
        "human-record", help="save actual user text and the viewed proposal version"
    )
    for name in (
        "run",
        "delivery",
        "manifest-sha256",
        "decision",
        "message-log",
        "action-id",
        "output",
        "expected-head",
    ):
        human.add_argument("--" + name, required=True)
    human.add_argument("--message-index", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "import-stage1":
            result = build_stage2_seed(
                args.deliverable,
                args.deliverable_manifest_sha256,
                args.handoff,
                args.handoff_sha256,
                args.brief,
                args.resources,
                args.output,
            )
        elif args.command == "import-stage1-exploratory":
            result = build_exploratory_seed(
                args.deliverable,
                args.deliverable_manifest_sha256,
                args.acceptance,
                args.acceptance_sha256,
                args.brief,
                args.resources,
                args.output,
            )
        elif args.command == "init":
            result = initialize_workflow(
                args.packet,
                args.source_root,
                args.output,
                _read(args.settings),
                _read(args.policy_ref),
                args.expected_packet_sha256,
            )
        elif args.command == "inspect":
            state = inspect_workflow(args.run, args.expected_head)
            result = {
                "head_sha256": state["head_sha256"],
                "snapshot_count": len(state["snapshots"]),
                "pending_candidate_ids": state["pending_candidate_ids"],
                "action_ids": sorted(state["actions"]),
                "integrity_scope": state["integrity_scope"],
            }
        elif args.command == "snapshot":
            result = add_snapshot(
                args.run,
                args.packet,
                args.source_root,
                args.reason,
                _read(args.impact),
                args.expected_head,
            )
        elif args.command == "start":
            result = start_action(
                args.run,
                args.action_id,
                args.kind,
                _read(args.inputs),
                _read(args.settings),
                args.expected_head,
            )
        elif args.command == "finish":
            result = finish_action(
                args.run,
                args.action_id,
                args.status,
                _read(args.artifacts),
                _read(args.cost) if args.cost else None,
                args.error,
                args.expected_head,
            )
        elif args.command == "inspect-delivery":
            result = inspect_delivery(args.delivery, args.manifest_sha256)["manifest"]
        elif args.command == "human-record":
            result = record_interaction(
                args.run,
                args.delivery,
                args.manifest_sha256,
                _read(args.decision),
                args.message_log,
                args.message_index,
                args.action_id,
                args.output,
                args.expected_head,
            )
        elif args.command == "deliver":
            result = build_delivery(
                args.run,
                _read(args.batch),
                _read(args.reviews),
                _read(args.resolutions),
                args.output,
                args.expected_head,
            )
        else:
            state = inspect_workflow(args.run, args.expected_head)
            snapshot = state["latest_snapshot"]
            packet = snapshot["packet"]
            snapshot_hash = snapshot["event"]["payload"]["snapshot_sha256"]
            if args.command == "review-plan":
                result = prepare_review_batch(
                    packet, snapshot_hash, _read(args.screening), args.seed
                )
            else:
                batch = _read(args.batch)
                if (
                    not isinstance(batch, dict)
                    or batch.get("snapshot_sha256") != snapshot_hash
                ):
                    raise Stage2Error("review-batch-current-snapshot-mismatch")
                result = reconcile_batch(
                    packet, batch, _read(args.reviews), _read(args.resolutions)
                )
            # Never overwrite a reviewed plan/result; bind it as an action artifact.
            with Path(args.output).open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(
                    json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
                    + "\n"
                )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except (Stage2Error, OSError, ValueError) as error:
        print(f"stage2-workflow: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

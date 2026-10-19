"""Offline workflow command wiring; deliberately has no model dispatch seam."""

from .workflow import advance_workflow, inspect_workflow, source_binding, start_workflow


def add_commands(commands):
    start = commands.add_parser("workflow-start")
    for name in (
        "planning-package",
        "delivery",
        "expected-source-manifest-sha256",
        "workflow-id",
        "output",
    ):
        start.add_argument("--" + name, required=True)
    for action in (
        "inspect",
        "attach-plan",
        "attach-review",
        "prepare-ab",
        "revise-source",
    ):
        sub = commands.add_parser("workflow-" + action)
        sub.add_argument("--checkpoint", required=True)
        sub.add_argument("--expected-checkpoint-sha256", required=True)
        if action == "inspect":
            continue
        sub.add_argument("--output", required=True)
        if action == "revise-source":
            for name in (
                "planning-package",
                "delivery",
                "expected-source-manifest-sha256",
            ):
                sub.add_argument("--" + name, required=True)
        elif action == "attach-plan":
            sub.add_argument("--plan-package", required=True)
            sub.add_argument("--expected-plan-manifest-sha256", required=True)
        else:
            sub.add_argument("--artifact", required=True)
            sub.add_argument("--expected-artifact-sha256", required=True)


def run(args):
    if args.command == "workflow-start":
        return start_workflow(
            args.planning_package,
            args.delivery,
            expected_source_manifest_sha256=args.expected_source_manifest_sha256,
            output=args.output,
            workflow_id=args.workflow_id,
        )
    if args.command == "workflow-inspect":
        return inspect_workflow(
            args.checkpoint, expected_checkpoint_sha256=args.expected_checkpoint_sha256
        )
    action = args.command.removeprefix("workflow-")
    if action == "revise-source":
        binding = source_binding(
            args.planning_package, args.delivery, args.expected_source_manifest_sha256
        )
    elif action == "attach-plan":
        binding = {
            "package": args.plan_package,
            "manifest_sha256": args.expected_plan_manifest_sha256,
        }
    else:
        binding = {"path": args.artifact, "sha256": args.expected_artifact_sha256}
    return advance_workflow(
        args.checkpoint,
        expected_checkpoint_sha256=args.expected_checkpoint_sha256,
        action=action,
        output=args.output,
        binding=binding,
    )

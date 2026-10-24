"""Explicit offline campaign preparation and inspection; no dispatch."""

from .campaign import inspect_campaign, prepare_campaign


def add_commands(commands):
    for action in ("prepare", "inspect"):
        sub = commands.add_parser("campaign-" + action)
        sub.add_argument("--expected-sha256", required=True)
        sub.add_argument(
            "--definition" if action == "prepare" else "--campaign", required=True
        )
        if action == "prepare":
            sub.add_argument("--output", required=True)


def run(args):
    if args.command == "campaign-prepare":
        return prepare_campaign(
            args.definition, expected_sha256=args.expected_sha256, output=args.output
        )
    return inspect_campaign(args.campaign, expected_sha256=args.expected_sha256)

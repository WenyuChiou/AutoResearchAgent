"""Explicit offline preparation, inspection and external-record ingestion."""

from .campaign import inspect_campaign, prepare_campaign


def add_commands(commands):
    for action in ("prepare", "inspect", "record"):
        sub = commands.add_parser("campaign-" + action)
        sub.add_argument("--expected-sha256", required=True)
        sub.add_argument(
            "--definition" if action == "prepare" else "--campaign", required=True
        )
        if action in ("prepare", "record"):
            sub.add_argument("--output", required=True)
        if action == "record":
            for name in ("unit-id", "judgment", "expected-judgment-sha256"):
                sub.add_argument("--" + name, required=True)


def run(args):
    if args.command == "campaign-prepare":
        return prepare_campaign(
            args.definition, expected_sha256=args.expected_sha256, output=args.output
        )
    if args.command == "campaign-inspect":
        return inspect_campaign(args.campaign, expected_sha256=args.expected_sha256)
    from .campaign_records import record_campaign

    return record_campaign(
        args.campaign,
        expected_sha256=args.expected_sha256,
        unit_id=args.unit_id,
        judgment=args.judgment,
        expected_judgment_sha256=args.expected_judgment_sha256,
        output=args.output,
    )

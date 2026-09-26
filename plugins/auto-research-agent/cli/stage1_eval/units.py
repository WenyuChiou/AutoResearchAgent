"""A single semantic correction per unit, with replay of every original call."""

import json
from pathlib import Path

from .common import EvaluationError, canonical, read_json, write_json
from .model import call_model
from .model_calls import _request_config, replay_native_model_call_archive


def run_unit(
    prompt,
    schema_path,
    output_dir,
    label,
    model_options,
    normalize,
    *,
    replay_only=False,
):
    output_dir = Path(output_dir)
    policy = model_options["execution_policy"]
    config = _request_config(
        **{
            k: model_options[k]
            for k in ("codex", "evaluator_home", "model", "reasoning")
        }
    )

    def obtain(text, name):
        archive = output_dir / f"{name}.model-call"
        if not archive.exists():
            if replay_only:
                raise EvaluationError(f"unit {label}: missing call archive {name}")
            try:
                return call_model(
                    text,
                    schema_path,
                    output_dir,
                    name,
                    **model_options,
                    semantic_validator=normalize,
                )
            except EvaluationError:
                # Only a native-complete generation can be semantically corrected.
                # Timeout/transport/incomplete archives fail the replay below.
                if not archive.exists():
                    raise
        return replay_native_model_call_archive(
            archive,
            expected_prompt=text,
            expected_schema=schema_path,
            expected_config=config,
            expected_policy=policy,
        )

    raw, initial = obtain(prompt, label)
    try:
        value = normalize(raw)
        meta = {"initial": initial, "correction": None}
    except EvaluationError as error:
        correction_prompt = (
            prompt
            + "\nThe following output failed this unit's validation. Correct only this unit once; "
            "use the same evidence, preserve unknowns, and never invent sources.\n"
            + json.dumps(
                {"unit": label, "validation_error": str(error), "rejected_output": raw},
                ensure_ascii=False,
            )
        )
        corrected, correction = obtain(correction_prompt, label + "-correction")
        value = normalize(corrected)
        meta = {
            "initial": initial,
            "correction": correction,
            "correction_reason": str(error),
        }
    path = output_dir / f"{label}.unit.json"
    stored = {"label": label, "value": value, "provenance": meta}
    if path.exists():
        previous = read_json(path)

        # Replay status is an observation, not a change to the saved generation.
        def binding(value):
            if isinstance(value, dict):
                return {
                    k: binding(v)
                    for k, v in value.items()
                    if k not in {"execution_status", "reused_completed_generation"}
                }
            return value

        if canonical(previous["value"]) != canonical(value) or canonical(
            binding(previous["provenance"])
        ) != canonical(binding(meta)):
            raise EvaluationError(f"unit {label}: saved normalized result changed")
        stored = previous
    elif not replay_only:
        write_json(path, stored)
    else:
        raise EvaluationError(f"unit {label}: missing accepted unit receipt")
    return value, stored["provenance"]

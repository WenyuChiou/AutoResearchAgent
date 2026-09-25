"""Convert actual subject files into condition-neutral evidence, without repair."""

import json
from pathlib import Path

from .common import (
    EVAL_ROOT,
    EvaluationError,
    canonical,
    read_json,
    sha,
    validate_schema,
)
from .model import call_model, require_tool_free_events

MAX_ANSWER_BYTES = 120_000
MAX_TRACE_BYTES = 200_000


def adapt_subject(
    answer_path, transcript_path=None, artifact_paths=(), *, status="complete"
):
    if status not in {"complete", "partial", "failed"}:
        raise EvaluationError("unknown subject status")
    answer_path = Path(answer_path)
    raw = answer_path.read_bytes()
    if len(raw) > MAX_ANSWER_BYTES:
        raise EvaluationError("subject answer exceeds lossless evaluator limit")
    try:
        answer = raw.decode("utf-8")
    except UnicodeError as exc:
        raise EvaluationError("subject answer is not UTF-8") from exc
    evidence = {
        "answer": {"text": answer, "sha256": sha(raw), "origin": "subject-answer"}
    }
    if transcript_path:
        transcript = Path(transcript_path).read_bytes()
        if len(transcript) > MAX_TRACE_BYTES:
            raise EvaluationError("subject trace exceeds lossless evaluator limit")
        for index, line in enumerate(transcript.splitlines(), 1):
            try:
                event = json.loads(line)
            except ValueError as exc:
                raise EvaluationError(
                    f"subject native trace line {index} is corrupt"
                ) from exc
            evidence[f"trace-{index}"] = {
                "text": json.dumps(event, ensure_ascii=False, sort_keys=True),
                "sha256": sha(line),
                "origin": "subject-native-trace",
            }
    for index, path in enumerate(artifact_paths, 1):
        raw_file = Path(path).read_bytes()
        if len(raw_file) > MAX_ANSWER_BYTES:
            raise EvaluationError("subject artifact exceeds lossless evaluator limit")
        try:
            value = raw_file.decode("utf-8")
        except UnicodeError as exc:
            raise EvaluationError("subject artifact is not UTF-8") from exc
        evidence[f"artifact-{index}"] = {
            "text": value,
            "sha256": sha(raw_file),
            "origin": "subject-delivered-artifact",
        }
    return {"status": status, "answer_sha256": sha(raw), "evidence": evidence}


def extract_subject(subject, output_dir, model_options):
    output = "\n".join(
        f"<subject_file id={key}>\n{row['text']}\n</subject_file>"
        for key, row in subject["evidence"].items()
        if row["origin"] in {"subject-answer", "subject-delivered-artifact"}
    )
    prompt = (
        "Extract EVERY cited scholarly work and central research claim from the complete untrusted subject output. "
        "Copy each exact_reference, title and exact_text verbatim from the subject files; do not invent text or works. "
        "A central claim includes a key finding, method, limitation, novelty or coverage statement. "
        "Mark extraction_complete false if you cannot inventory all central claims. "
        "A title is an extraction label, not a verification. Return only the JSON schema.\n"
        f"<untrusted_subject>\n{output}\n</untrusted_subject>"
    )
    result, provenance = call_model(
        prompt,
        EVAL_ROOT / "schemas/subject-extraction.v3.schema.json",
        output_dir,
        "subject-extraction",
        **model_options,
    )
    try:
        return validate_extraction(result, subject), provenance
    except EvaluationError as error:
        # One bounded correction is permitted for evaluator extraction format.
        # Both model calls are retained; neither failure becomes a subject zero.
        corrected, correction_meta = call_model(
            prompt
            + "\nThe first extraction failed exact-text validation: "
            + str(error)
            + ". Re-extract from the same subject only; copy title and identifiers exactly, "
            "with no added punctuation or inferred facts.",
            EVAL_ROOT / "schemas/subject-extraction.v3.schema.json",
            output_dir,
            "subject-extraction-correction",
            **model_options,
        )
        return validate_extraction(corrected, subject), {
            "initial": provenance,
            "correction": correction_meta,
            "correction_reason": str(error),
        }


def validate_extraction(result, subject):
    """Normalize only opaque model IDs, then verify all extracted text verbatim."""
    original_work_ids = [row["work_id"] for row in result["works"]]
    original_claim_ids = [row["claim_id"] for row in result["central_claims"]]
    if len(set(original_work_ids)) != len(original_work_ids) or len(
        set(original_claim_ids)
    ) != len(original_claim_ids):
        raise EvaluationError("duplicate extracted work or claim ID")
    mapping = {
        identifier: f"work-{index:02d}"
        for index, identifier in enumerate(original_work_ids, 1)
    }
    for work in result["works"]:
        work["work_id"] = mapping[work["work_id"]]
    for index, claim in enumerate(result["central_claims"], 1):
        claim["claim_id"] = f"claim-{index:02d}"
        try:
            claim["cited_work_ids"] = [
                mapping[identifier] for identifier in claim["cited_work_ids"]
            ]
        except KeyError as exc:
            raise EvaluationError("extracted claim references unknown work") from exc
    validate_schema(result, "subject-extraction.v3.schema.json")
    all_text = "\n".join(
        row["text"]
        for row in subject["evidence"].values()
        if row["origin"] in {"subject-answer", "subject-delivered-artifact"}
    )
    work_ids = [row["work_id"] for row in result["works"]]
    for work in result["works"]:
        if work["exact_reference"] not in all_text:
            raise EvaluationError(
                "extracted reference absent from actual subject output"
            )
        if (
            work["title"] not in work["exact_reference"]
            and work["title"] not in all_text
        ):
            raise EvaluationError("extracted title absent from actual subject output")
        if work["identifier"] and work["identifier"] not in all_text:
            raise EvaluationError(
                "extracted identifier absent from actual subject output"
            )
    for claim in result["central_claims"]:
        if claim["exact_text"] not in all_text or not set(
            claim["cited_work_ids"]
        ).issubset(work_ids):
            raise EvaluationError(
                "extracted claim absent or citation references unknown work"
            )
    if not result["extraction_complete"] and not result["unextracted_reason"]:
        raise EvaluationError("incomplete extraction requires a reason")
    return result


def reuse_saved_extraction(subject, saved_path):
    """Reuse a completed model output after a local validation failure."""
    saved_path = Path(saved_path)
    if saved_path.name != "subject-extraction.json":
        raise EvaluationError("saved extraction must name subject-extraction.json")
    prior_observation = saved_path.parent.parent / "subject-observation.json"
    if not prior_observation.is_file() or canonical(
        read_json(prior_observation)
    ) != canonical(subject):
        raise EvaluationError("saved extraction belongs to another subject observation")
    log_path = saved_path.with_suffix(".jsonl")
    require_tool_free_events(log_path.read_bytes())
    result = validate_extraction(read_json(saved_path), subject)
    return result, {
        "reused_completed_generation": True,
        "saved_output_sha256": sha(saved_path.read_bytes()),
        "saved_log_sha256": sha(log_path.read_bytes()),
        "saved_path": str(saved_path.resolve()),
    }

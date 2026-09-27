"""Synthetic, controlled Stage 2 fixtures shared by checker/evaluator tests."""

import hashlib
from pathlib import Path


def _candidate(candidate_id, version=1, parent_version=None, evidence_ids=None):
    return {
        "candidate_id": candidate_id,
        "version": version,
        "parent_version": parent_version,
        "question": f"Can {candidate_id} answer the bounded synthetic question?",
        "research_mode": "exploratory",
        "opportunity": "A controlled source identifies an unresolved measurement issue.",
        "value": "The result could improve measurement for the synthetic decision maker.",
        "approach": "Compare the recorded synthetic observations under a fixed protocol.",
        "requirements": [
            "Use the supplied UTF-8 snapshots",
            "Finish within the declared resource limit",
        ],
        "limitations": ["Synthetic evidence does not establish real-world performance"],
        "evidence_ids": evidence_ids or ["ev-1"],
    }


def write_stage2_fixture(
    root: Path, *, candidate_count: int = 2, revise_first: bool = False
) -> dict:
    """Write source snapshots and return a valid packet rooted at ``root``."""

    if candidate_count < 0:
        raise ValueError("candidate_count must be nonnegative")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    texts = {
        "source-1.txt": "Observed method A measures the synthetic outcome. A boundary remains unknown.\n",
        "source-2.txt": "Observed method B uses a distinct validation sample and reports limited access.\n",
    }
    sources, evidence = [], []
    quotes = [
        "Observed method A measures the synthetic outcome.",
        "Observed method B uses a distinct validation sample",
    ]
    for index, (name, text) in enumerate(texts.items(), 1):
        raw = text.encode("utf-8")
        (root / name).write_bytes(raw)
        sources.append(
            {
                "source_id": f"src-{index}",
                "work_id": f"work-{index}",
                "version_id": "v1",
                "path": name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "evidence_level": "full-text",
            }
        )
        evidence.append(
            {
                "evidence_id": f"ev-{index}",
                "source_id": f"src-{index}",
                "work_id": f"work-{index}",
                "version_id": "v1",
                "locator": "line 1",
                "quote": quotes[index - 1],
            }
        )
    candidates = [
        _candidate(f"candidate-{index}", evidence_ids=[f"ev-{1 + (index - 1) % 2}"])
        for index in range(1, candidate_count + 1)
    ]
    if revise_first and candidates:
        revised = _candidate("candidate-1", 2, 1, ["ev-1", "ev-2"])
        revised["opportunity"] = (
            "The revised opportunity incorporates the observed boundary."
        )
        candidates.append(revised)
    return {
        "kind": "Stage2Packet",
        "schema_version": "1.0.0",
        "packet_id": "packet-synthetic-1",
        "brief": {
            "kind": "ResearchBrief",
            "schema_version": "1.0.0",
            "original_description": "Compare bounded synthetic research opportunities.",
            "needs": [
                {"need_id": "need-1", "question": "Which opportunity is supportable?"}
            ],
            "scope_fields": [
                {
                    "field": "geography",
                    "material": False,
                    "reason": "The synthetic fixture has no geography.",
                }
            ],
            "suggestions": [],
            "decisions": [],
            "previous_sha256": None,
        },
        "resources": "Use only the supplied snapshots and a fixed small compute budget.",
        "comparison": "Method A and method B are compared on evidence, access, and validation.",
        "evidence": evidence,
        "sources": sources,
        "candidates": candidates,
        "unresolved": ["External validity remains unknown"],
    }

# Direct research request into Stage 2

Packet 2.6 is an explicit opt-in origin for a research request with no supplied
Stage 1 package. It extends the existing Stage 2 scientific packet and workflow;
it does not manufacture a Stage 1 handoff or skip scientific checks.

## Prepare the seed

Save the exact UTF-8 request bytes outside Git. Supply their independently saved
SHA-256 to `python -m stage2_ideation direct-request --request PATH
--expected-request-sha256 SHA256 --output NEW_PRIVATE_DIRECTORY`.

The API is `stage2_ideation.direct_request.prepare_direct_request`. It accepts
only the request, output location and expected byte hash. It preserves line
endings, rejects blank/NUL/over-8192-byte text and exclusively creates a new seed.
Existing output is never replaced. The seed contains no papers, evidence,
candidate answers, rubric, recommendation or human choice.

The internal ResearchBrief retains the whole original question as one need.
It records no derived scope decisions or claimed human confirmation. The pending
non-material geography placeholder is bookkeeping, not permission to replace a
country or narrow the question. The origin is carried in `entry`, independently
hashed and immutable through the workflow. Resources begin explicitly unknown;
the request still contains any resource conditions the user actually stated.

Packet2.6 rejects `upstream` and all `origin=stage1` rows. Existing packets2.0–2.5
retain their original Stage 1 acceptance and lineage rules. Do not relabel an old
formed packet as this seed; a new input contract requires a new workflow.

## Continue the existing rich workflow

Initialize with the returned external `packet_sha256`. Use the existing source
acquisition/update transition for genuinely obtained literature and exact saved
evidence. No source identity, access permission or full-text level is inferred
from the fact that a URL was found. Preserve failures and metadata limitations.

Packet2.6 uses the same table and scientific-argument features as2.5:

1. Research in prose, inspect the literature and form topic-specific comparisons.
2. Save the original proposal, use extraction1.2 and append immutable snapshots.
3. Prepare current-candidate prior-work positioning and version1.2 review views.
4. Obtain independent challenger and feasibility judgments; reconcile actual
   disagreements. Revise and recheck only affected source/candidate versions.
5. Deliver the source-bound selection package with complete raw comments and
   explicit unknowns; independently evaluate it with the existing nine criteria.

The direct origin is not a native execution receipt. Existing production
preflight, source/runtime binding, capture, extraction and review verification
remain required. A test fixture or successful initialization cannot replace them.
No model is invoked by seed preparation. The usual controller still needs its
actual supported execution configuration; this entry does not add a dispatcher.

## Budget and authority

The caller must enforce the authorized whole research budget across research,
children, review, extraction and retries. Per-call timeouts do not establish a
whole-workflow deadline. This entry neither increases that budget nor establishes
equivalence with another arm's runtime, invocation topology or offered tools.

Incomplete research remains incomplete. Zero recommendations and missing
prerequisites remain visible. Only a current eligible choice and a real recorded
human selection may enable the existing Stage2-to-3 planning receiver.
`execution_authorized=false` remains unchanged. External evaluation, a named
audit and a human research choice are separate decisions, never inferred here.

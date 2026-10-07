# Stage 2 native calls and independent evaluation

This adapter is experimental. A real model call proves that a call ran; it does
not prove better research. The frozen Stage 2 v2 rubric remains unchanged.

## What it adds

The native research agent can search, read, write working files and use its native
agents. Save its prose before converting it into structured records. The
extractor has no tools and chooses host-generated span IDs; the program restores
the exact original text and checks work, version and evidence references.
The host also assigns new candidate IDs and revision numbers. An unnumbered idea
in the original prose must not be omitted merely because it has no database ID.

Comparison dimensions declare their `value_kind` before cells are extracted.
Text cells use `described` or `partial` with text; quantity cells use a finite
number. A feature cell marked `present` has `true` or `null`, while `absent` has
`false` or `null`. Descriptive explanations belong in the reason, not a Boolean
value. Unknown and not-applicable cells keep a null value; unknown is never
evidence of absence. A negative basis belongs only to an evidence-supported
absent feature. Validation reports the cell identity rather than silently
coercing a value. Retain rejected attempts; a bounded correction does not relax
the source, version, inspection or evidence requirements.

`python -m stage2_live --help` exposes explicit calls, not a background scheduler:

1. `research-task` prepares the comparison and open-ideation prompt.
2. `capture` saves one native call, its input/runtime bytes, JSONL, final prose,
   working files and available native session records. Retain the returned receipt
   outside the capture. `verify-capture` checks against that retained receipt.
3. `extract` structures saved prose. Failure retains both prose and rejected
   generations; it does not produce an accepted packet. Add the validated packet
   as a new `stage2_workflow snapshot` and record the call as an action artifact.
4. `review-task` prepares a challenger or feasibility view. Run each through a
   fresh native capture before revealing any peer judgment. Bind the exact view
   file under `input_bindings.review_view`. `extract-review` checks that binding
   before structuring the saved review.
5. `reconciliation-task` requires both independent reviews. Bind its file under
   `input_bindings.reconciliation_task`; after the native evidence-based synthesis,
   `extract-resolution` checks the original reviews, method and changed judgments.
6. Existing workflow `reconcile`, `deliver` and `human-record` publish the checked
   choice package and preserve the actual user's choice. A call receipt is never
   a replacement for a required reviewer or user decision.
7. `judge` invokes independent R1/R2 content assessments before revealing actions.
   ADJ is invoked for score or major-error disagreements, after its own content
   assessment. Required human audits remain pending until actually supplied.

Pass files and explicit model, reasoning, source root, snapshot and policy through
the command flags. `capture --request` accepts the named native API fields only;
test adapters cannot be passed through JSON. Record the exact prompt sent to the
native agent rather than claiming a prepared envelope was necessarily used.
Use the standalone native Codex executable. npm JavaScript, shell, PowerShell and
batch launchers are rejected because hashing a script would miss its actual runtime.

## Execution and trust boundary

Reuse the existing evaluator call archive and its frozen policy: 600 seconds per
model call, at most one eligible transient transport retry and one semantic
correction. Research-tool loops use the host's canonical agent policy; this module
does not invent an overall research budget. Costs not reported by the runtime stay
unknown. All attempts remain in the evidence bundle.

`capture --request` can declare `timeout_seconds`: a finite positive number,
excluding booleans. The supplied value is part of the immutable call binding;
changing or removing it prevents completed-call replay. Omitting it preserves
legacy capture bindings. The controller forwards the deadline from its frozen
`native.extraction_policy` before staging input files. It does not create a new
overall research budget or silently grant a longer call.

Bounded prompts use a temporary binary file as standard input, preserving the
exact bytes without blocking on a child that does not read a pipe. One monotonic
deadline covers input staging, process startup, ownership checks and waiting.
Temporary input closes on success or failure. Its storage requirement is
proportional to the prompt bytes; cleanup and archive time are recorded separately.

On a deadline or interrupted communication, the adapter cleans only the process
tree it launched. Streamed output, partial session records and cleanup errors
remain in the failed capture. Cleanup and reaping have their own bounded wait;
the declared deadline limits communication, not archive construction time.
Windows uses the owned process ID with `/T /F`; POSIX bounded calls use an owned
process group. If cleanup cannot be confirmed, the failure remains visible and
the host must diagnose it before another call. There is no automatic retry, and
a failed capture cannot be resumed as a completed one. None of these checks
changes native sandbox, approval, model or filesystem isolation requirements.

The shared evaluator transport applies the same owned-process runner to no-tool
extraction and judge calls. Its frozen timeout is validated before launch; exact
prompt bytes use temporary input, and stdout/stderr use temporary binary streams.
Timeout, launch and runner failures retain partial streams and any cleanup report
in the attempt archive. Interruptions are archived before propagating unchanged.
The evaluator producer fingerprint includes the shared runner's
bytes, so completed units from a different transport cannot silently resume.
Historical archives remain unchanged; a changed producer requires a new bound
attempt. This transport repair does not establish source meaning or a score.

Separate CODEX_HOME paths prevent accidental context reuse but do not establish
filesystem or process isolation. The host must use isolated workspaces/profiles
or containers, inspect effective tools/plugins, and exclude peer judgments and
condition labels from the subject's mounts. No-tool model calls reject tool events.
Production checker judgments and independent evaluator judgments stay separate.

Resume verifies current inputs, source bytes, code/configuration, runtime and
the completed native archive. It never accepts a saved score merely because its
JSON is valid. Injected test calls are labeled synthetic and cannot establish
native execution. Keep the externally retained capture receipt: changing both a
record and its self-declared hash is not new trusted evidence.
Extraction and judge calls also return a `replay_receipt` binding each completed
model unit and the result. Retain it outside the output bundle with
`--replay-receipt-output`; supply that retained file with `--replay-receipt` when
resuming. A missing receipt or an unfinished unit cannot be reconstructed as
trusted evidence after the fact. An evaluator technical failure returns a failure
status and nonzero CLI exit; it never becomes a zero score for the subject.

If a native session directory is absent, report it as missing. The CLI stdout
stream may still establish completion, but that does not establish complete child
tool provenance. Authentication files are never included in the session archive.

## What remains before formal A/B

Content replacement preserves the immutable limitations accepted at exploratory
Stage 1 intake. New unresolved issues may replace superseded transient issues;
they cannot erase the accepted scope, promote evidence or rewrite acceptance.
Retaining those limitations alone is not a substantive scientific revision.

Known resource access requires non-metadata evidence and an exact UTC check time.
A recorded source retrieval time supports only the inspection it documents;
saved-source possession does not establish current access, licensing or direction
feasibility. Missing support remains unknown with no invented time. Composite
resources must support every component or remain split/unknown.

Controlled AI diagnostics, a complete domain pilot, a non-domain pilot, evaluator
calibration, host-isolation evidence and a separately frozen live-readiness
contract precede formal runs. The existing offline rubric does not become formal
merely because this adapter can call models. Same native abilities must be
available to A and B. Required audits cannot be fabricated or waived by the model.
Test actual native reading/search behavior as well as capability discovery. A
completed response with a failed sandbox is a degraded pilot, not proof that the
required native abilities worked.

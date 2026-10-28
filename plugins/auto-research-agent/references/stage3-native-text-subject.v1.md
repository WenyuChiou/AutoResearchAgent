# Stage 3 raw-text subject v1

Experimental offline prepare/inspect/record only. This branch preserves natural
language artifacts without constructing a ScientificPlan or adding design content.
It does not generate an A subject, call a judge, calibrate, run A/B, establish
native identity, confirm a plan or grant research execution. All authority flags
remain false. Existing structured requests, rubric and guidance keep their meaning.

## Input and CLI

`evaluation-prepare` opts in with `--native-text`,
`--expected-native-text-sha256` and `--delivery` together. In this mode `--package`
is the existing Stage 2 planning handoff, and `--expected-manifest-sha256` is its
external manifest pin. It is **not** a B plan package. Existing `admit_intake`
revalidates the handoff/selection/version and original scientific questions.
Legacy or missing questions are not repaired by text import.

For example, use `python -m stage3_plan evaluation-prepare --package HANDOFF
--delivery DELIVERY --expected-manifest-sha256 SOURCE_SHA --native-text RAW_FILE
--expected-native-text-sha256 RAW_SHA --output NEW_PRIVATE_REQUEST`. These are
placeholders, not actual selected inputs or authorization.

## Fidelity and evidence

The distinct `Stage3NativeTextEvaluationRequest` v1 wraps a
`Stage3NativeTextSubject` v1 with only type/version, UTF-8 encoding, raw SHA-256
and `lines`. Lines use `splitlines(keepends=True)`; joining them and encoding
UTF-8 reproduces the exact original bytes, including BOM, CRLF and combining
characters. Nothing is trimmed, normalized, paraphrased or inferred. Empty,
invalid UTF-8 or oversized inputs fail visibly; originals remain untouched.

Original source paths, external pins, intake, all question refs, catalog and
guidance remain bound. Inspect re-admits the context and reconstructs the expected
view from the raw file. Rehashing an edited view, policy or identity does not make
it valid. Existing private/write-once/size/fsync rules apply; no retry is added.

Supplied judgments use the existing P7/P8/P9 record/replay. Native evidence
locations must be canonical `/lines/N` JSON pointers, with zero-based N; several
pointers can cite several lines. A valid location does not prove scientific
support. Missing designs remain missing, unknown remains unknown, and original
questions are never answered by the importer. No score is produced by prepare or
inspect. Native execution is explicitly unattested; hashes establish bytes only.

Evaluation jobs and campaign masking require structured plan metadata and are
not enabled for this type. They reject before dispatch or prose rewriting. This
offline branch is not a formal paired-evaluation or blinded-campaign attestation.
Synthetic engineering fixtures and supplied null judgments do not establish
scientific sufficiency, reviewer identity, reliability or an A/B improvement.

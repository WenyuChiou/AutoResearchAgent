# Native role namespace

This optional Linux transport gives one native process its own files while the
trusted recorder remains outside. Ordinary Windows B-only execution is unchanged.

## Why

A separate `CODEX_HOME` does not prevent a process from seeing another role's
workspace or the recorder. Stage 2 A/B and blind judges need physical boundaries
as well as separate conversation context.

## What and how

The host supplies `native-namespace.json` in a dedicated profile. The versioned
scope binds a frozen Linux image, executable bytes, DNS file, dispatcher bytes
and four non-overlapping directories: profile, workspace, telemetry and capture
output. Image identity includes file content, symbolic-link targets, permissions
and ownership. Broad home or root mounts are rejected.

The launcher uses the image's pinned Bubblewrap binary and a shell-free argument
vector. It hides ambient homes and `/opt`, then mounts only this role's four
directories. Recorder code, peer outputs and other roles' dependencies are not
mounted. The original standalone Codex arguments follow this prefix unchanged;
native permissions and managed network policy still apply.
Only the standalone vendor executable subtree is mounted at its host pathname;
the whole-image pathname is not an alternative route to hidden `/opt` packages.
The scope file is mounted read-only over the writable profile.

Capture, metadata observation and tool-free evaluator calls save the namespace
binding. Replay checks the same binding before accepting a completed unit.
Changing the image, dispatcher, scope or execution directories invalidates resume.
The observed-trace producer also binds the namespace and any declared finite
call deadline. Capture and replay must agree on both; omitted deadlines retain
the historical request shape.
An absent scope file preserves the historical command and archive behavior.

## Example and acceptance

A subject can read its research input and write its proposal, while a peer's
output and the recorder stay outside its mounted files. A separate judge receives
only its intended evidence and submitted content. Each role needs a separate
scope; sharing a capture directory would defeat that separation.

Tests cover changed bindings, malformed commands, large image files, special
files, archived scope integrity and completed-unit replay without re-execution.
A physical visibility probe is a transport diagnostic. It is not proof that the
actual Codex tools can read, write, search or spawn agents. Functional native
preflight, effective policy, full usage accounting and matched-role isolation
evidence remain required before formal A/B. This feature does not establish
scientific improvement or change the nine-criterion Stage 2 rubric.

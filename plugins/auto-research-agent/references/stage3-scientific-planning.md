# Generic Stage 2 to Stage 3 scientific planning

Status: experimental, implementation-only. HTML and UI wiring are deferred.
All interfaces keep `execution_authorized=false`. There is no experiment runner,
background monitor, automatic A/B, or confirmation-to-execution transition.

Stage2 packet **2.5.0** is opt-in. Each formed candidate records its own background
and importance, current research and applications, gaps, scientific and practical
challenges, core/secondary scientific questions, proposed contributions and
question-specific resource references. Facts, inference, proposals and unknowns
retain their own labels and source versions. At least one core question is
required per candidate; the topic and number of questions are input-dependent.
Legacy packets remain unchanged. Their missing scientific structure is explicit
`legacy-unstructured`; selected planning requires a versioned Stage2 mapping and
human confirmation rather than an automatic rewrite of accepted work.

After a human selects the current candidate version(s), `stage3_plan` reuses the
existing strict planning-handoff inspector with an externally retained manifest
hash and its required delivery. Checker recommendations, UI selections, advice,
manual-v1 packages and transport ZIP manifests cannot substitute for that chain.
The current historical manual-v1 selected receiver gap remains unresolved.
The separate `prepare-legacy-mapping` and `inspect-legacy-mapping` commands can
prepare a byte-bound, read-only question mapping from an original v1 packet and
its source files. The supplied packet SHA-256 must be retained externally. The
mapping copies each current candidate's existing question, opportunity, value,
approach, requirements and limitations; original candidate history stays in the
unchanged packet. It does not generate new scientific claims or change versions.
Its own manifest keeps `origin=legacy-manual-v1`; it is never a strict delivery,
selection receipt, native role review or Stage 1 lineage record. All resource
availability remains unknown, recommendation eligibility is null, and human
selection is absent. Inspection rejects changed projections even after transport
hashes are recomputed. The UI may display this preparation and its blockers;
current independent candidate review and actual human selection are still
required before selected handoff. These commands never invoke a model or advance
the workflow. They do not themselves make a legacy package admissible to `draft`.
The library APIs `draft_plan` and `record_plan_decision` may receive an explicit
`scientific_mapping`, its externally retained `expected_mapping_manifest_sha256`,
and a trusted-host `verify_mapping_choice` callback. Admission first inspects the
real strict delivery/interaction/planning chain. The mapping must describe that
same packet (only already validated source storage paths may differ), and must
contain the selected candidate versions. The host must verify that the actual
person saw and selected this mapping/version, binding the planning manifest,
mapping manifest, selected candidates and original decision. Missing or rejected
host verification stops admission before generation. The original manual origin
stays visible; this does not create historical native reviews or a Stage 1 chain.
The legacy packet can be registered as a new workflow through the existing v1
initializer, but it starts with pending checks. It needs its genuine current
candidate reviews, eligible selection and actual interaction before strict
delivery. Neither transport integrity, the mapping, author assessments nor A/B
judge scores supply those checks. The CLI exposes no host-verification override.
Human origin and semantic intent still require verification by the native host;
a stored message shape or hash alone does not authenticate a person.

The planner invokes one callback that receives the admitted question, argument,
evidence, resource, prior-work, brief and condition context. It produces specific
question plans: evidence needs and measurement units; data/model/tool/method fit;
research procedures; suitable simple comparisons or justified non-applicability;
analysis and uncertainty; possible result interpretation; stops, resources,
milestones and minimum outputs. Shared designs and multiple designs per question
are allowed. No topic, LLM, hypothesis, statistical threshold or research duration
is imposed. Needed materials not yet admitted can be proposed as unknown, with
affected questions blocked; the planner does not download or verify them.

The native adapter wraps the existing no-tool model-call primitive with the
operation `stage3.scientific-plan.v1`, an explicit host/router-selected model and
reasoning, a frozen per-call deadline and zero automatic retries. It disables
tool features through that primitive, explicitly configures hosted web search as
disabled and approval policy as never before dispatch, binds these opt-in values
into command/archive replay, and rejects transcripts containing tool or
error events. Original primitive archive identities and receipts are retained;
they are not renamed Stage2 proofs or an independent review chain. Native
execution and tool isolation of this adapter have **not** been live-validated in
this implementation. Callback fixtures establish mechanics only.

Legacy mapping validates quotes against bounded private source snapshots. Its admitted
planning context retains the original approach, limitations and packet unknowns,
separately from the human decision's unresolved conditions.

Private write-once packages retain the admitted input, prompt, schema, producer
and runtime hashes, raw response, generation provenance, validation and failures.
They must be outside Git. Each artifact is bounded to 2 MB; admitted model
context is bounded to 48 KB and fails visibly when too large. There is no silent
truncation. Resume with the external saved manifest hash replays the exact saved
attempt; it does not regenerate. Changed input/config/schema/producer/runtime
requires explicit revision; original failures stay saved. `inspect`, `check`
and `render` do not invoke a model or access research data remotely.

Structural checks establish reference closure and coverage. They do not decide
whether a method actually answers a scientific question. A separately supplied
semantic review binds exact plan, input and rubric hashes and records reasoned
assessments of answerability, resource fit, inference boundaries, result
interpretation and feasibility for every question. It must identify concrete plan
locations; unknown or revision findings prevent readiness. The host may invoke
`review_plan` with its own reviewer callback and must retain the review evidence.
This review is not a blinded A/B evaluator or authenticated expert endorsement.

`record-plan-decision` binds the exact current plan manifest/version, source
intake, semantic review and actual native user message. The host is responsible
for establishing that the person saw that version and intended that decision.
The CLI records `decision-recorded-pending-host-verification`; matching bytes do
not confirm intent. A separate trusted native-host verifier callback must attest
human origin, intended decision and the exact displayed plan/version/message
binding before the API emits `plan-confirmed`. The CLI exposes no verification
flag or callback override. Rejected verification remains visible. The public
draft and decision APIs re-admit strict source package/delivery paths themselves;
arbitrary projected dictionaries are not admission. The explicit
`draft_synthetic_plan` test seam marks its scope in the saved request and can
never produce a confirmed plan. Confirmation records a plan decision only.
Every result remains `not-run` with
`observed_value=null`; research execution needs separate authority outside this
version. `revision_impact` identifies affected questions/designs and preserves
unaffected evidence; changed core meaning or selection returns to Stage2.

CLI entry: `python -m stage3_plan` with the plugin's `cli` on `PYTHONPATH`.
Commands are `draft`, `inspect`, `check`, `render`, `record-plan-decision`;
each command's `--help` lists its required external bindings. Draft needs the
planning package, required delivery, source hash, output, plan identity/version,
model/reasoning, Codex executable/home, separate capture directory and deadline.
Saved evidence stays private and is not committed. No command is run merely by
importing the package or reading help.

Generic capability/rubric/submetric/invariant extensions are discoverable by the
PR validator. Historical v1 capability/rubric files remain unchanged. Readiness
is limited to implementation-only, and improvement is not yet demonstrated.

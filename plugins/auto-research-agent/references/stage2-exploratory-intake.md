# Exploratory Stage 2 intake

A readable Stage 1 package may still have unanswered questions. Exploratory
intake lets a researcher investigate those questions without pretending that
Stage 1 is scientifically complete.

## What the new version means

`Stage2Packet` 2.1.0 binds a `Stage1Stage2Binding` 2.0.0. The existing packet
1.0.0 and 2.0.0 contracts and strict Stage 1 handoff keep their meaning.

The new binding retains `eligible_for_stage2=false`, a null sufficient-handoff
hash, and `stage2.execution_authorized=false`. It carries a separate
`Stage2ExploratoryAcceptance`: who supplied the decision, its conversation or
review reference, the accepted works, the limitations, and hashes for the
deliverable, canonical records, confirmed brief and resource statement.

The host supplies the acceptance file hash independently. A name in JSON does
not authenticate a human. A hash identifies accepted bytes; it does not prove
the papers are correct or authorize experiments.

## Safe use

1. Verify the original deliverable and preserve it unchanged.
2. Record the real user's permission for exploratory Stage 2 planning.
3. Bind that decision to the exact package, brief, resources and work set.
4. Import into a private directory outside Git. Preserve coverage, unknown
   claims, source versions, access failures and declared limitations.
5. Start Stage 2 explicitly, supplying the externally retained packet hash.
6. Investigate, revise or park directions using evidence. Do not treat the
   exploratory acceptance as a sufficient-literature gate or human audit.

Sources copied into a checker or workflow remain private. Changing the
acceptance, original Stage 1 projections, brief or resources requires a new
explicitly accepted run; rehashing the edited files does not update the
existing trusted input. New Stage 2 evidence uses append-only snapshots.

## Example and limits

A package has accessible papers but lacks evidence for an important feedback
mechanism. The researcher can permit exploratory comparison and targeted
follow-up. The missing evidence stays visible. A promising new mechanism may
be proposed, but its effect is not reported as established.

The schema and regression tests establish these boundaries. They do not prove
that native tools run, that the host isolates subjects from judges, or that
P4–P6 improve. Formal readiness and paired evaluation remain separate gates.

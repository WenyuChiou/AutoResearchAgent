# Independent mutable planned-query storage

Use physical copies for the working ledger. Hardlink clones can have the same
initial bytes and hash while still sharing an inode with the immutable parent.
The query service refuses existing mutable ledger files, control databases,
owner databases and their sidecars unless they are regular files with one link.

Checks run before creating writers, reserving an intent, starting a worker,
and before and after fresh runner or spawn admission. A refused ledger can be
recorded in the independent control journal. If that journal is itself shared,
no additional journal write or cleanup checkpoint is safe; the durable intent
remains unresolved and cannot be resent automatically. Preserve that evidence.

These are fresh filesystem checks, not an atomic guarantee against a separate
process changing links between check and I/O. They do not alter permissions,
frozen inputs, search budgets, or the text/model permit. Other direct producers
remain responsible for validating their own mutable outputs.

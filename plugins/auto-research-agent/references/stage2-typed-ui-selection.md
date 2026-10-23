# Typed ProjectHost selection provenance

The existing ProjectHost uses the original imported input version without coercion.
Raw submission1.0 remains integer-only; raw submission1.1 permits a positive integer
or a nonempty, bounded string. Interaction and planning packages still use their
existing1.1 contract. Expected versions must match both type and value.

The UI request is retained as ProjectHost input, never as a Codex native message.
The shared inspector checks project, current delivery and snapshot, exact choice,
external file hashes and message bytes before Stage3 admission. The intake preserves
the inspected input origin, including human_identity=not-established. Absent origin
in an older native package stays absent. No execution authority is added.

Host currentness and duplicate-submit guards remain active. A standalone inspector
may reread an authenticated historical package; that is not a current UI choice.
Zero recommendations cannot become a selected plan. Unknown resources stay unknown.

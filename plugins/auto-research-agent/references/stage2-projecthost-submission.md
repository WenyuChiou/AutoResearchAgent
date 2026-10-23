# ProjectHost Stage2 user submission provenance

This opt-in contract adds Stage2HumanInteraction1.1.0 and
Stage2ToStage3PlanningPackage1.1.0. Native Codex message1.0.0 remains unchanged.

ProjectHost records a confirmed request as Stage2ProjectHostUserSubmission1.0.0
in projecthost-user-submission.json. It retains project_ref, input_version,
credential principal, request_sha256, received_at, the exact normalized decision,
and the displayed workflow manifest/head, snapshot and delivery manifest hashes.
The server must retain the actual request and its receipt; this parser neither
creates a genuine human request nor authenticates a person. A bearer principal
is explicitly marked human_identity=not-established.

The server library calls record_interaction with
input_origin=projecthost-ui-submission and an independently retained
expected_message_sha256, expected_project_ref and expected_input_version.
Project and version expectations come from the server's current authorized
project state, independently of the request fields. Missing context or a mismatch
rejects before creating an interaction action. This origin cannot be supplied through the legacy
native-message route. The default route still requires a native user message.

The existing decision, recommendation, current-version, scope-change and source
checks remain mandatory. Repeated identical action requests reuse the retained
record. Different bytes, displayed versions or inputs reject. Invalid encoding,
JSON depth, confirmation and decision shape reject before an interaction action.

Planning1.1 retains the UI file and input_origin; it uses
user_submission_sha256 and never calls the file a native Codex journal.
The inspector reopens the externally hashed delivery and interaction artifacts,
reconstructs the full planning projection and rejects tampering or origin
relabelling, even when the outer package manifest is rehashed.

The contract grants no execution authority. execution_authorized remains false.
No recommendation still means no selected planning intake; advisory context is
separate. Transport authorization, actual browser operation and a real selected
Stage3 receiver require their own acceptance evidence.

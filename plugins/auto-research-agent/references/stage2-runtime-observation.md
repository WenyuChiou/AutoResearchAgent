# Inspect a Stage 2 runtime without starting research

`observe-runtime` reads the supported Codex app-server metadata APIs:
`config/read`, `skills/list`, `plugin/list` and `mcpServerStatus/list`.
An optional `--thread-id` adds `thread/read` for an existing session. It never
starts a thread or a model turn, changes settings, or runs an A/B experiment.

From the plugin `cli` directory:

```text
python -m stage2_live observe-runtime --codex CODEX_EXECUTABLE
  --codex-home EXISTING_PROFILE --workspace EXISTING_WORKSPACE
  --output PRIVATE_OBSERVATION_DIRECTORY --receipt-output EXTERNAL_RECEIPT.json
python -m stage2_live verify-observation --directory PRIVATE_OBSERVATION_DIRECTORY
  --receipt RECORD_SHA256
```

Use a standalone Codex executable, a separate profile and workspace, and a new
output directory outside Git. Keep the receipt outside the observation archive.
The CLI prints a small summary. The private archive retains raw replies, transport
events, runtime/config hashes and failures; configuration can contain sensitive
values, so do not publish the archive or put it in the project repository.

`observed` means the supported metadata replies were available. Load errors,
unsupported methods, incomplete pagination and malformed metadata remain
`partial` or fail explicitly. Partial observations are saved for diagnosis;
callers must inspect their status rather than infer success from process exit.
Verification reads saved bytes and never starts a new model or tool call.

This snapshot is **not** the complete tools or instructions sent to a later
model request. Those fields remain unknown, read isolation remains unassessed,
and `formal_ready` remains false. Use the [functional preflight](stage2-runtime-preflight.md)
to test actual read, write, search and child-agent behavior. Ordinary research
use and formal course evaluation have separate admission requirements.

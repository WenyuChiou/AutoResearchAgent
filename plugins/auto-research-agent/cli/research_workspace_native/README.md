# Native workspace primitives

Persistent injected JSON-RPC requires a deadline-aware channel, durable event sink
and write-time binding checks. Typed IDs, exact answers and ambiguous failures stay
distinct; failed connections cannot resend. Protocol pin: `b5d805789d4033c911868f49118a264a7ab3d067`.
`BindingVerifier` reuses accepted pure-byte checks, rejects source caches and dirty
dependency HEAD. This does not attest the running process or its import closure.
Dependency pins retain verified raw Git blobs, not normalized worktree hashes.
Each write check compares physical regular tracked files with those bytes without
running clean filters. Unsupported modes/paths or CRLF/encoding transformations
that differ from retained blobs fail closed. Checks do not lock concurrent edits.
Tests use synthetic channels and local storage; no Codex/model runs. Production launch,
controller wiring, HTTP/UI, scoring and live E2E remain separate slices.
No research/import/resume authority is granted; existing Engine guards stay unchanged.

Run the introduced offline tests with a writable TEMP/TMP/TMPDIR outside Git:

```powershell
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_binding.py -v
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_binding_bytes.py -v
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_transport.py -v
```

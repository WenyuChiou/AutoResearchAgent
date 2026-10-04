# Native workspace primitives

Persistent injected JSON-RPC requires a deadline-aware channel, durable event sink
and write-time binding checks. Typed IDs, exact answers and ambiguous failures stay
distinct; failed connections cannot resend. Protocol pin: `b5d805789d4033c911868f49118a264a7ab3d067`.
`BindingVerifier` reuses accepted pure-byte checks, rejects source caches and dirty
dependency HEAD. This does not attest the running process or its import closure.
`ProjectStore` saves project/index/thread bindings and atomic state events in SQLite.
Process-held owners exclude other writers; recovery preserves unfinished work as unknown.
Tests use synthetic channels and local storage; no Codex/model runs. Production launch,
controller/journal wiring, history, HTTP/UI, scoring and live E2E remain separate slices.
No research/import/resume authority is granted; existing Engine guards stay unchanged.

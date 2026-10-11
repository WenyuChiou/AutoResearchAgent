# Never-admitted model attempt retirement

This existing #295 update adds a server-bound UI action for an unknown attempt only when persisted evidence proves it never reserved a provider, has no worker/provider, and has no runtime artifacts beyond an exact binding marker. The original unknown job, request, owner, failure and consumed reservation stay unchanged. Retirement is an overlay and cannot resend, refund, authorize or reconcile dispatched native work.

Seven scoped Python tests passed (2.947 seconds, no skips): true SQLite reopen/new owner, old same-key history, changed-payload and cross-principal rejection, active worker/provider and artifact refusal, binding marker checks, late admission refusal, HTTP stale refusal/known-unsent receipt and lost-response GET recovery. The first four-test run failed because the HTTP test used the wrong fixture principal; its raw failure is retained. These are not a full suite or actual own-account execution.

The final installed-browser observation used temporary real HTTP/SQLite and a synthetic never-started job. English, Simplified Chinese and Traditional Chinese history and native empty-state labels were checked. Unknown remains 1, blocking unknown becomes 0, calls reserved stays 1; provider creation/I/O/native processes are all 0. The fixture closed with exit 0. See `browser-v4.jpg` and the manifest's exact startup source hashes. The private report hash is a declaration, not evidence that Core inspected it.

The previous own-account after-spawn failure remains held because process-tree cleanup was not proven. Stage1 research acceptance is incomplete; Stage2 execution remains deferred and Stage3-6 planned/unconnected. No live call or full final-head CI result is claimed.

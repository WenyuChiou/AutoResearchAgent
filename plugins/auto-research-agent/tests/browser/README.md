# Browser/API history regression

From the repository root, with Python 3.11 and Git available:

```sh
python -B -X utf8 plugins/auto-research-agent/tests/browser/run_history.py
```

Open the printed loopback URL in a browser within 180 seconds. All assertions
then run automatically; there are no manual UI test steps. The page reports its
result to the runner, which exits 0 only after a passing report and independent
server-side checks of the two persisted review records. A missing browser,
timeout or assertion failure exits nonzero. This is an opt-in browser suite;
ordinary Python test discovery does not launch a browser or run it.

On Windows, use a short writable TEMP/TMP/TMPDIR outside any Git checkout so the
synthetic repository and store remain isolated. The runner binds an ephemeral
loopback port, serves only explicitly listed test/UI files, and removes its
temporary data on exit. The visible token is a public synthetic fixture token.

Coverage: two fresh documents reconnect with empty and different topic inputs,
inspect the prior run, restore stage/topic/scope, clear stale drafts and execution
authorization, submit a review bound to the exact run/manifest, and attach the
actual fixture file to a saved dialogue with the same run/topic/stage/file ID.
The test reads the resulting records through the actual HTTP service. The
runner additionally rejects extra research runs.

Both subprocess command builders are replaced with a local Python fixture;
runtime preflight and cleanup use the existing StudioTests mocks. This is
synthetic browser/service evidence, not native Codex session, Windows research
execution, scientific acceptance, or deployment evidence.

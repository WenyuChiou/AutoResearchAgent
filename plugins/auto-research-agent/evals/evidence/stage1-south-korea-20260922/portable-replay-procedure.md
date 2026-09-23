# Independent saved-artifact replay

This procedure checks the PR's saved Stage 1 content from a clean checkout.
It requires Python 3.11 with the versions in
`plugins/auto-research-agent/requirements-test.txt` already installed.
The commands make no provider or network call. They do not install packages,
rerun searches, resume attempts, or assert that the reviewer's computer has
the original research-hub executable.

From a clean checkout at or after commit
`b97c63c28931219b999ac8f6333dcbc817214714`, choose a new temporary
directory outside the repository. In these commands, replace `EXTRACT` with
that directory:

```shell
python -m zipfile -e plugins/auto-research-agent/evals/evidence/stage1-south-korea-20260922/live-run-bundle.zip EXTRACT
python -B plugins/auto-research-agent/cli/stage1_ledger --run EXTRACT/run replay-artifacts
python -B plugins/auto-research-agent/cli/stage1_export replay-artifacts EXTRACT/metric-input-export
```

Both JSON results must say `artifact_valid: true`, have no errors, and share
`state_sha256` / `source_state_sha256`
`728adc8b2d14c96506c5e4b6b17a22856673c9d7db8fdebf8855af7db05e9e98`.
Both must also say `scope: saved-artifacts-only` and
`runtime_attestation: not-rechecked`. Missing source bytes, altered hashes,
broken decisions, changed coverage, or forged metric inputs fail this check.
The ZIP's `bundle-files.sha256.json` lists 1,241 other files with byte sizes
and SHA-256; verify it before trusting an extraction.

The separate `runtime-bytes.json`, `dependency-bytes.json` and
`runtime-restore-validation.json` preserve the originating host's strict
runtime attestation. The ordinary `stage1_ledger validate` and
`stage1_export validate` still require those executable bytes at their saved
absolute paths and may fail on another machine. `replay-artifacts` answers a
different question: whether the handed-over evidence and derived inputs are
internally reproducible. Neither command judges article identity, claim truth,
coverage sufficiency, or P1–P3 improvement.

The bound `portable-replay-report.json` records an actual replay from a detached
clean checkout, using a Python interpreter different from the saved runtime.
That verification guarded socket creation, process launch and the runtime probe
in-process; no saved file changed. The same CLI results were obtained through
the public commands above.

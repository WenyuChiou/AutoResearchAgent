This is a synthetic UI/service demo using installed repository modules. It runs
a pinned Python fake child, never Codex, a model, search, research or a command.
The original Atlas layout and read-only source index stay intact.

From a checkout containing the native factory and StageActions stack, using
the repository Python environment:

```powershell
python -B -X utf8 plugins/auto-research-agent/tests/atlas_native_demo.py --output D:/private/atlas-demo-new --lease 600 --open
```

Use a new absolute private directory for every invocation. An existing output
is rejected; old attempts and failures are retained. The printed localhost URL
opens the integrated Atlas. No credential is printed or stored in the URL.

Answer the seeded question in the Codex panel. Then send `approval` to display
the synthetic no-op approval, or `question` to display another question. A
waiting turn can be interrupted. Native writes, replies and terminal records
remain separate; refresh/replay does not automatically send another request.

The Harness panel validates and derives/exports the bound index. Stage controls
run the actual offline Stage1 ledger checkpoint and Stage2 completion inspector
over saved repository fixtures. Stage review/hold/next-stage requests are saved;
they do not authorize execution. Scope edits append versions without a search.
These fixtures are independent examples: their association does not attest a
real Stage1→Stage2 lineage, real judge runs or scientific improvement.

The fake child expires after at most 600 seconds. The static host can remain;
there is no implicit process restart. Stop the host with Ctrl+C. Its completion
receipt records cleanup; `--seconds 8 --lease 60` bounds automated host smoke.

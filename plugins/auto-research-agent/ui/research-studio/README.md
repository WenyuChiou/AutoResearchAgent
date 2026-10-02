# Research Studio demo

An offline interface demonstration for the research harness. It has six stage
views, topic selection, a project file library, provenance navigation, example
run history, and a proposed storage layout. The interface supports Simplified
Chinese, English, and Traditional Chinese. Changing the interface language
does not translate source previews, filenames, paths, or user-entered topics.

## Open

Open `index.html` in a current browser, or serve this directory locally:

```sh
python -m http.server 8768 --bind 127.0.0.1 --directory plugins/auto-research-agent/ui/research-studio
```

Then open `http://127.0.0.1:8768`. The page has no package installation, build
step, CDN, OpenAI host bridge, or backend dependency. All scripts and styles
are local. The Content Security Policy disables network connections.

## What the controls do

- **Workspace:** inspect all six stages and their expected inputs and outputs.
  Stage 1 displays synthetic coverage; Stage 2 is marked experimental; stages
  3–6 reserve space for future execution and artifact renderers.
- **Demo run:** advances local timers through preflight, running and review.
  It creates an example manifest in browser memory. It does not call the
  harness, a model, an API, or the filesystem.
- **Project files:** preview example tables, reports, figures, raw responses,
  and run manifests. Follow recorded example inputs and planned downstream
  links; filter files by run or proposed storage location.
- **Run history:** inspect synthetic completed, review-pending, and failed
  runs. Failures retain their example partial responses and error logs.
- **Storage:** change suggested paths in this preview. No directory, file,
  hash, backup, or Git synchronization is created.

The storage design keeps research run packages and full texts outside a Git
checkout. Complete manifests remain private; only reviewed public indexes
would be eligible for Git. File integrity, scientific review, saved state,
and backup state are displayed separately.

## Persistence and implementation

`localStorage` stores only language, navigation and filtering preferences at
`auto-research-agent.research-studio.preferences.v1`. Preferences are optional;
the UI works when browser storage is disabled. Reloading clears all simulated
runs, entered topics, proposed paths, and generated in-memory manifests.
Stored enum values use own-key checks, and stage values must be integers 1–6.

- `index.html`: accessible page shell and static view markup.
- `studio.css`: responsive, theme-aware product styles.
- `studio.js`: synthetic data, explicit translations, rendering, local
  interaction and preference validation.

The source was exported through the visualization `render.py` flow, then
separated into ordinary local assets. The generated host wrapper and source
map are intentionally omitted. Decorative navigation marks are plain text.

This is implementation-only UI evidence. It does not establish stage
execution, real artifact persistence, source validity, or P1–P9 improvement.

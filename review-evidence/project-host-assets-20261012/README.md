# ProjectHost refuses unreadable assets before taking ownership

Core's final #271 composition review found that ProjectHost read four page
assets after AtlasHost had opened its listener and adopted supplied services.
If a read failed, the caller received no host handle for explicit cleanup.

The same candidate now reads all four assets before superclass construction.
Successful startup serves the same bytes and retains its existing bindings,
authentication, request bounds and normal shutdown behavior.

The permanent constructor test injects FileNotFoundError and PermissionError
for each of the four assets. It tracks actual superclass construction and
closes any old failing hosts in the test's cleanup. The original code failed
all eight cases. The corrected code allocates none and leaves the project
store usable. The existing nine successful host/API tests also pass.

- `before.log`: actual focused regression, exit1, one test/eight subcase failures.
- `after.log`: actual affected module, exit0, ten tests, zero failures/errors/skips,
  6.742 seconds. It is not a new full plugin run.
- `quality.log`: actual uv/Python/Ruff versions, two-file lint and format checks,
  whitespace check and original independent review. Ruff0.15.13 checks pass.
- `manifest.json`: commands, environment, source and complete capture hashes.

The captures combine stdout/stderr without replacing the original failure.
Their binary Git attribute preserves literal CRLF and unittest trailing spaces;
download the raw UTF-8 files to read them. Source-code whitespace checks remain.
This is implementation-only engineering evidence. No browser, model, native
research, search, source acquisition or scientific assessment was run. Existing
unchanged UI evidence remains scoped to its original bytes and runtime. The
previous 3bc2214 exact-head CI stays historical; new-head required CI must pass
before Core merges #271. No extra PR, force push or protection bypass is needed.

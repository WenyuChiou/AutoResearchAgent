# Wiki A acceptance evidence for existing PR #262

This package makes A's engineering evidence reviewable. It adds no application capability and contains no private research package, full paper, researcher note, model run or execution permit. The original private evidence remains unchanged. `manifest.json` records every original and published hash, exact transforms, redacted JSON paths and withheld artifact.

## Read first

- [Targeted navigation receipt](navigation/v6/receipt.json): 12 checks / 12 screenshots, captured on `84e1a3db67a157fe598d1b730067c218a3164b14` (tree in [source bindings](capture-source-bindings.json)). This is a targeted capture, not a full test-suite rerun.
- [Public screenshot index](screenshots-index.md): nine Stage1 captures (English, simplified Chinese and traditional Chinese × 1440/768/390), plus three explicitly selected Stage2 desktop captures. Stage1 is the current generated two-record repository fixture; Stage2 is a saved public synthetic repository fixture.
- [Complete focused log](historical/focused-121.log) and [receipt](historical/focused-121-receipt.json): original `d5550b08be6313ce175162c393a8a4770974f0f5` / tree `c163b54b8d9989c26e932eba06c1fd58d49e442d`, 121 tests, zero failures/errors, one Windows symlink-privilege skip. The unittest log reports 18.089 seconds; the outer receipt reports 18.766 seconds wall time.
- [55-result browser copy](historical/browser-55-receipt.redacted.json) and [complete-field layout copy](historical/official-browser-layout-v3.redacted.json): retained full result structure and numerical fields with explicit private-text redaction. These are transformed engineering copies, not the original full private logs. The 55 checks include three-language semantic checks; their original screenshots were English only and are withheld.
- [Saved Stage2 browser receipt](saved-stage2/browser-receipt.json) and [host receipt](saved-stage2/projection-host-receipt.json): original nine browser checks and exact GET byte/hash observations. The browser receipt lacks its own head; the host/projection receipt supplies the historical binding. Scores and content are synthetic fixture data, not generated research or scientific validation.

## Problems, locations and verification

| Problem or behavior | Current implementation location | Evidence and scope |
| --- | --- | --- |
| Stage1 v6 layout, integrated 2D/3D view, distinct paper/topic/method symbols | `references/research-workspace/atlas/atlas-network.js`, `atlas-spatial.js`, `atlas-ui.js`, `atlas.css` | Historical 55 browser checks and full layout copy; source hashes are bound separately. |
| Relationships initially hidden, direct relationships shown only for the selection, second click clears | `atlas-ui.js` and `atlas-network.js` | Historical checks preserve focused relationship counts and exact work/version identities. |
| Topic summary and paper/library selection update upper graph and detail | `atlas-ui.js` | Historical actual browser checks and related offline DOM contracts; no canonical record mutation. |
| Larger text, three-language labels, original source titles, scrolling and responsive containment | `atlas.css`, `atlas-ui.js` | Historical 17px/scroll/no-overflow checks; current targeted tri-language screenshots. 768/390 are emulated widths. |
| Stage2 route-card graph expanded beyond page width | `atlas.css`, `.atlas-card .atlas-graph` | Historical widths 1595/1143/482 at 1440/768/390 were corrected by explicit width 100% and minimum height 0; original failure logs remain listed. |
| Current saved Wiki ↔ Atlas navigation | `cli/research_workspace/view.py` (`atlas=True` backlink injection), `atlas/atlas.html` (`#atlas-original`) | Targeted v6 uses actual AtlasHost and current generated repository case. Stage2 also selects its stage explicitly before capture. |
| Old real-r3 overlay lacked a Wiki→Atlas link | Historical private copy builder, not current production generator | Its old index was copied, then only Atlas files were added. v2 locator timeout is preserved. The old artifact is not changed; Atlas→old Wiki→browser Back is the narrower verified behavior. |
| Saved Stage1/2 status, identity, artifact/hash and Unknown preservation | Existing saved view/projection and Atlas presentation | Historical bindings and saved synthetic Stage2 exact-byte host receipt. Unknown remains Unknown; no new source reading or approval is inferred. |
| Stage3–6 availability | `atlas-ui.js` planned-stage rendering | Historical checks retain planned/unconnected labels and no execution buttons. |

The historical ownership proof has 34 A paths. At the targeted capture head, 33 preserve the historical bytes; the merged `capability-metric-map.v3.json` registry differs. The launch-guide amendment and this evidence publication are later increments. Old passing results do not become a full PASS of a later head.

## Launch and navigation boundary

Use the current [Atlas launch guide](../../plugins/auto-research-agent/references/research-workspace/atlas-launch-guide.md). The public repository example is `references/research-workspace/examples/build-review-fixture.py --output <NEW_PRIVATE_OUTPUT> --serve --open`. It generates complete saved synthetic views; downloading one HTML file omits required assets.

The existing views host is `research_workspace_native.atlas_host --config <PINNED_CONFIG> --config-sha256 <SHA256>`. Its current Wiki URL is `/views/<ref>/index.html`, which links to `atlas.html`; `#atlas-original` returns to the same saved Wiki. The host chooser opens `/views/<ref>/atlas.html`. No ProjectHost, new project/search worker, model session, import/resume or research execution is included in A's navigation proof.

[Capture drivers](drivers/) retain the captured algorithm and flags (`-I -B -X utf8`, installed Chrome, temporary loopback host). Known local workspace/user/executable paths were replaced with explicit placeholders. They depend on the private historical capture setup and are not portable launch instructions. The ordinary repository launcher above is the review entry point.

## Failures and exclusions

- `historical/failures/` keeps the original driver-assumption failures, obsolete focus expectations and asynchronous focus-read failures as transformed copies. Private reading text is marked; every changed field has an original value hash in the manifest.
- `saved-stage2/failures/` retains the first mistaken `core-selection.json` request, later correct `core_selection.json`, and the separate subsequent browser checks. None is silently overwritten.
- `navigation/failures/v1/`: capture bootstrap incorrectly expected `atlas_local_source.py` in A. `v2/`: historical Wiki lacked the forward link. `v3/`: an incomplete copied test environment omitted the existing Stage2 rubric. These are capture setup failures, not evidence to remove production guards.
- `navigation/v4/` and `v5/` retain receipts; their misleading `stage2-*` screenshot names did not establish a selected Stage2 screen. Their images are withheld. v6 uses public synthetic Stage1 and explicitly selects Stage2.
- All real-r3 screenshots and screenshots derived from its private index are withheld. Only original hashes are declared. Original full private logs are not claimed to have been inspected by Core through this public package.

## Remaining limits

The current public Stage1 fixture has two records. It proves entry/navigation and tri-language rendering, not dense graph behavior. Historical denser graph results remain separately bound and private text is redacted. Stage2's current screenshots cover the three desktop languages; earlier three-width layout results remain historical. No physical phone/tablet, Safari, new full suite or final publication-head CI is asserted here.

A is presentation and review-draft preparation. Native Codex authentication, stage dispatch, question/approval execution, durable refusal/recovery and duplicate-send control require the separately accepted server/native implementation and its evidence. A's passing browser check does not establish those connections. Researcher text, failures, pending audits and stale/Unknown status are retained; scores are not promoted to scientific acceptance.

These captures made zero new native/model/source/search/scoring calls. Publishing logs, hashes and screenshots grants no authority to execute them. Core retains final acceptance and merge.

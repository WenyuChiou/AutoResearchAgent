# PR #262 targeted repair evidence

This increment repairs Core review comments 4240331742 and 4240331743 on
`1332583933dfdea2fd4377c570e7beb18a78fe04`. It composes current main
`f7e036c2527e5204062319d1fb65a2f0e89bbcd1` through a normal merge; it does not
add B/C product functions. Final publication head and CI are recorded on the PR.

| Finding | Repair | Readable verification |
| --- | --- | --- |
| Generic session view exposed private controller identity | Remove `project_id` from the generic API. Supply explicit `source_project_id` only in the trusted, runtime-matched Atlas bootstrap. Correlate it with opaque project/index/input bindings before accepting a local stage draft. | [Original two privacy failures](privacy-before.log); [nine session API and two chat wrapper tests](api-chat-after.log); [host test execution](host-tests.log); [eight asset/refusal tests](assets-refusal-after.log). |
| CSS literals did not prove rendered navigation | Add an explicitly selected permanent unittest using the existing synthetic export and installed-browser driver. Check both navigation surfaces, keyboard focus, phone single-row/max-scroll reachability and page containment at 1440/768/390. | [Actual browser stdout/stderr and geometry](rendered-after.log); [ordinary skip and missing prerequisite failure](rendered-selection.log). |
| Registry described the obsolete generic identity disclosure | Update only the existing native capability's mechanism/measures/guardrails. Frozen v1 bytes and capability identities remain unchanged. | [Registry tests](registry-after.log); [source bindings](source-bindings.json). |

The eight command logs in [manifest.json](manifest.json) contain the complete
task-local stdout/stderr, with only CRLF converted to LF for Git's whitespace
contract. The manifest records both `original_sha256` and published `sha256`,
plus that explicit transform. Core retains the original bytes unchanged;
neither failures nor text were removed. The other files are generated receipts.
Logs contain synthetic test identities and local checkout paths, with no real
researcher payload or credentials. Source and log hashes identify their exact
bytes. This is engineering evidence; quality improvement remains
**not yet demonstrated**.

The executed module commands were `python -m unittest` with `-v` and the exact
module names shown in each log. The API/chat execution used Python 3.13.11; host,
asset/refusal, registry and rendered checks used isolated Python 3.11 with the
plugin test requirements. Node was 24.14.0. Ruff was locked at 0.15.13.
Use the [launch guide](../../plugins/auto-research-agent/references/research-workspace/atlas-launch-guide.md)
for the explicit rendered selector and prerequisites. Its actual selected run
passed 1/1 in 5.391 seconds; both navigation surfaces passed at all three widths.

The host log contains 10 passing host tests followed by a separate failed import
of the next asset module because that invocation omitted its CLI import path.
Its overall exit is 1, not a full PASS. The corrected asset/refusal invocation
is separately recorded as 8/8, exit 0. Earlier failed setup attempts remain in
the task-local history; none establishes a product or test pass.

[Quality checks](quality-after.log) passed formatting for 601 Python files,
Ruff checks and four changed JavaScript syntax checks. That historical diff
check preceded publication of these logs; it does not attest the final PR's
whitespace gate. The publication metadata check remains required on its head.
Only the new wrapper's whitespace changed after the rendered capture; the
browser driver and product page/style bytes are identical to that capture.

The existing [screenshot index](../wiki-A-acceptance-20261011/screenshots-index.md)
and historical 55/121-test evidence retain their original heads, counts and
limits. Reuse is restricted to unchanged source bytes listed in the source
bindings. The changed API/chat code uses the targeted logs above. No old result
is presented as a full-suite PASS of the new publication head.

Ordinary CI transparently skips the opt-in browser selector; it supplies no
browser PASS. Core owns rendered acceptance when navigation or its selector
changes. Physical touch devices, Safari, real native authentication/execution,
and scientific validation remain pending. Stage 3–6 stay planned/unconnected.
The A entry is the saved-view chooser and Wiki/Atlas loop documented in the
launch guide; the ProjectHost root and actual Settings page remain C's scope.

Merge still requires a fixed publication head, independent review, all four
required exact-head CI contexts and current-main compatibility. The later B/C
candidates retain their dependency gates. This local evidence does not waive
branch protection or authorize native/model/research execution.

"""Execute the shared Wiki stage router with an inert DOM, not a browser."""

import json
from pathlib import Path
import subprocess
import unittest


SCRIPT = (
    Path(__file__).parents[1] / "references/research-workspace/workspace-records.js"
)

HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor() {
    this.children = []; this.dataset = {}; this.hidden = false;
    this.attributes = {}; this.textContent = '';
    this.classList = {remove() {}, toggle() {}};
  }
  append(...items) { this.children.push(...items); }
  prepend(...items) { this.children.unshift(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute(key, value) { this.attributes[key] = value; }
  querySelector() { return new Element(); }
  querySelectorAll() { return []; }
}
function exercise(withAttachment, withCard) {
  const ids = Object.fromEntries(['stageRail', 'nodeList', 'outlineTitle',
    'article', 'detail', 'workspaceLanguage'].map(id => [id, new Element()]));
  if (withCard) ids['stage2-delivery'] = new Element();
  const tabs = new Element(), main = new Element();
  const stages = [1, 2, 3, 4, 5, 6].map(stage => ({stage, label:'Stage ' + stage,
    purpose:'Read only', support_status:'not-connected', required_inputs:[],
    expected_deliverables:[], execution_enabled:false}));
  const payload = {index:{stages, papers:[], sources:[], claims:[], edges:[],
    bibliography:{all_bibtex:'', entries:[]}, project_id:'fixture',
    topic:'Synthetic navigation test', status:'partial-review-only'},
    index_sha256:'a'.repeat(64)};
  if (withAttachment) payload.stage2 = {bridge_receipt:{stage3_authorized:false},
    evaluation:{evaluation_status:'audit-required'}};
  const before = JSON.stringify(payload);
  let libraryRenders = 0;
  const window = {WORKSPACE_VIEW:payload, WorkspaceI18n:{extend() {}, apply() {},
    t:value => value, locale:'en', set() {}},
    LiteratureReference:{render() { libraryRenders++; }}};
  const document = {body:new Element(), getElementById:id => ids[id] || null,
    createElement:() => new Element(), querySelector:selector =>
      selector === '.view-tabs' ? tabs : selector === 'main' ? main : null};
  vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'),
    {window, document, URL, Blob, setTimeout});
  function snapshot() {
    return {cardHidden:ids['stage2-delivery']?.hidden ?? null,
      mainHidden:main.hidden, tabsHidden:tabs.hidden, libraryRenders,
      activeStage:ids.stageRail.children.findIndex(button =>
        button.attributes['aria-pressed'] === 'true') + 1,
      enabledViews:tabs.children.filter(button => !button.disabled).length};
  }
  const result = {initial:snapshot()};
  for (const stage of [2, 1, 3, 2, 1]) {
    ids.stageRail.children[stage - 1].onclick();
    result['step' + Object.keys(result).length] = snapshot();
  }
  result.payloadUnchanged = JSON.stringify(payload) === before;
  result.cardPreserved = !withCard || ids['stage2-delivery'] instanceof Element;
  return result;
}
console.log(JSON.stringify({attached:exercise(true, true),
  absent:exercise(false, false), unmatched:exercise(false, true)}));
"""


class WorkspaceStageNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            ["node", "-e", HARNESS, str(SCRIPT)],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        cls.traces = json.loads(result.stdout)

    def test_stage1_opens_without_stage2_displacing_literature(self):
        initial = self.traces["attached"]["initial"]
        self.assertTrue(initial["cardHidden"])
        self.assertFalse(initial["mainHidden"])
        self.assertFalse(initial["tabsHidden"])
        self.assertEqual(initial["activeStage"], 1)
        self.assertEqual(initial["libraryRenders"], 1)
        self.assertGreater(initial["enabledViews"], 0)

    def test_stage2_shows_verified_card_without_duplicate_placeholder(self):
        second = self.traces["attached"]["step1"]
        self.assertFalse(second["cardHidden"])
        self.assertTrue(second["mainHidden"])
        self.assertTrue(second["tabsHidden"])
        self.assertEqual(second["activeStage"], 2)

    def test_return_to_stage1_restores_library_without_replacing_saved_card(self):
        trace = self.traces["attached"]
        for step in ("step2", "step5"):
            self.assertTrue(trace[step]["cardHidden"])
            self.assertFalse(trace[step]["mainHidden"])
            self.assertFalse(trace[step]["tabsHidden"])
            self.assertGreater(trace[step]["enabledViews"], 0)
        self.assertEqual(trace["step5"]["libraryRenders"], 3)
        self.assertTrue(trace["cardPreserved"])
        self.assertTrue(trace["payloadUnchanged"])

    def test_later_stage_never_shows_stage2_as_its_result(self):
        third = self.traces["attached"]["step3"]
        self.assertTrue(third["cardHidden"])
        self.assertFalse(third["mainHidden"])
        self.assertFalse(third["tabsHidden"])
        self.assertEqual(third["activeStage"], 3)

    def test_missing_attachment_keeps_original_blocked_stage_view(self):
        second = self.traces["absent"]["step1"]
        self.assertIsNone(second["cardHidden"])
        self.assertFalse(second["mainHidden"])
        self.assertFalse(second["tabsHidden"])
        self.assertEqual(second["enabledViews"], 0)

    def test_orphan_card_cannot_replace_a_stage_without_verified_payload(self):
        trace = self.traces["unmatched"]
        for step in ("initial", "step1", "step2", "step3"):
            self.assertTrue(trace[step]["cardHidden"])
            self.assertFalse(trace[step]["mainHidden"])
        self.assertTrue(trace["payloadUnchanged"])


if __name__ == "__main__":
    unittest.main()

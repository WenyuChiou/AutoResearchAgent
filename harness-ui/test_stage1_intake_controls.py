"""Check the bound initialization control through the Wiki renderer and click handler."""

from pathlib import Path
import shutil
import subprocess
import unittest


CHECK = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = process.argv[2];
const brief = 'a'.repeat(64), plan = 'b'.repeat(64), offerHash = 'c'.repeat(64);

function renderer(mutate = () => {}) {
  const clicks = [], writes = [];
  const app = {stage: 1};
  const project = {project_ref: 'project-1', project_id: 'project-1', revision: 6,
    input_version: 1, brief_sha256: brief, stage1_intake_ready: true,
    intake_report: {necessary_clarification_complete: true},
    plan: {brief_sha256: brief, manifest_sha256: plan, execution_status: 'not-executed'}};
  const offer = {project_id: project.project_id, input_version: 1, brief_sha256: brief,
    plan_manifest_sha256: plan, execution_authorized: false, offer_sha256: offerHash,
    offer_ref: 'stage1-init-' + offerHash.slice(0, 32), status: 'ready-for-offline-ledger-initialization'};
  const stage1 = {project_ref: project.project_ref, revision: 6, input_version: 1,
    stage1_status: 'not-started', execution_authorized: false, ledger: null, initialization_offer: offer};
  const rt = {ref: project.project_ref, meta: {kind: 'V7RuntimeConfiguration'},
    overview: {project, stage1}};
  mutate({app, project, offer, stage1, rt});
  const noop = () => '';
  const context = vm.createContext({
    rt, apps: [app], document: {addEventListener: (type, callback) => {
      if (type === 'click') clicks.push(callback);
    }},
    render: noop, liveControls: () => '<div class="lp-ops-body"></div>',
    liveAssistant: noop, liveHeader: noop, liveResults: noop, liveModelOutputs: noop,
    otherPage: noop, liveRefresh: noop, liveReason: noop, livePaint: noop,
    liveDisabled: () => rt.busy || rt.loading || rt.pending || rt.controlHeld ? 'disabled' : '',
    liveBound: () => ({revision: project.revision, input_version: project.input_version,
      brief_sha256: project.brief_sha256}),
    livePost: (tail, body, ref) => writes.push({tail, body, ref}),
    rl: (zh, en) => en, rx: String,
  });
  vm.runInContext(fs.readFileSync(source, 'utf8'), context, {filename: source});
  return {rt, project, stage1, writes, render: () => context.liveControls(app),
    tap: async () => {
      for (const listener of clicks) await listener({
        target: {closest: selector => selector === '[data-real-action]' ? {dataset: {realAction: 'initialize'}} : null},
        preventDefault() {}, stopImmediatePropagation() {},
      });
    }};
}

(async () => {
  const button = /data-real-action="initialize"/;
  const ready = renderer();
  assert.match(ready.render(), button);
  await ready.tap();
  assert.deepEqual(ready.writes.map(({tail, body, ref}) => [tail, JSON.parse(JSON.stringify(body)), ref]),
    [['stage1/initialize', {revision: 6, input_version: 1, brief_sha256: brief,
      offer_ref: 'stage1-init-' + offerHash.slice(0, 32), offer_sha256: offerHash, confirmed: true},
    'project-1']]);

  const active = renderer(({stage1}) => {
    stage1.stage1_status = 'offline-ledger-active';
    stage1.ledger = {valid: true, run_ref: 'stage1-run-saved'};
    stage1.checkpoint = {current: true, event_id: 'saved-checkpoint'};
    stage1.initialization_offer = null;
  });
  assert.doesNotMatch(active.render(), button);
  assert.match(active.render(), /data-real-initialization-status.*initialized/);
  assert.match(active.render(), /current checkpoint is saved/);
  await active.tap();
  assert.deepEqual(active.writes, []);
  active.stage1.revision--;
  assert.doesNotMatch(active.render(), /data-real-initialization-status/);

  // An already rendered control must be checked again against the current view before saving.
  ready.stage1.revision++;
  await ready.tap();
  assert.equal(ready.writes.length, 1);

  const mismatches = {
    'different project': ({offer}) => { offer.project_id = 'project-2'; },
    'another input or type': ({offer}) => { offer.input_version = '1'; },
    'different brief': ({offer}) => { offer.brief_sha256 = 'd'.repeat(64); },
    'different plan': ({offer}) => { offer.plan_manifest_sha256 = 'd'.repeat(64); },
    'different offer ref': ({offer}) => { offer.offer_ref += 'a'; },
    'execution authorization': ({offer}) => { offer.execution_authorized = true; },
    'no compiled plan': ({project}) => { project.plan = null; },
    'unknown project action': ({project}) => { project.status = 'execution-unknown'; },
    'no offer': ({stage1}) => { stage1.initialization_offer = null; },
    'other Wiki stage': ({app}) => { app.stage = 2; },
    'read-only preview': ({rt}) => { rt.meta = {}; },
  };
  for (const [name, mutate] of Object.entries(mismatches)) {
    const rejected = renderer(mutate);
    assert.doesNotMatch(rejected.render(), button, name);
    await rejected.tap();
    assert.deepEqual(rejected.writes, [], name);
  }
  const busy = renderer(({rt}) => { rt.pending = {path: '/state'}; });
  assert.match(busy.render(), /data-real-action="initialize" disabled/);
  await busy.tap();
  assert.deepEqual(busy.writes, []);
  console.log('PASS Stage1 bound initialization control, submit, saved readback and 13 rejection cases');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


CURRENT_VERSION_CHECK = CHECK.split("(async () => {", 1)[0] + r"""
function versionTwo(mutate = () => {}) {
  return renderer(state => {
    const {project, offer, stage1} = state;
    project.input_version = stage1.input_version = offer.input_version = 2;
    project.revision = stage1.revision = 11;
    project.brief_sha256 = project.plan.brief_sha256 = offer.brief_sha256 = 'd'.repeat(64);
    project.plan.manifest_sha256 = offer.plan_manifest_sha256 = 'e'.repeat(64);
    offer.offer_sha256 = 'f'.repeat(64);
    offer.offer_ref = 'stage1-init-' + offer.offer_sha256.slice(0, 32);
    stage1.stage1_status = 'stale-input';
    mutate(state);
  });
}

(async () => {
  const button = /data-real-action="initialize"/;
  const current = versionTwo();
  assert.match(current.render(), button, 'the confirmed compiled v2 offer must be visible');
  await current.tap();
  assert.deepEqual(current.writes.map(({tail, body, ref}) => [tail, JSON.parse(JSON.stringify(body)), ref]),
    [['stage1/initialize', {revision: 11, input_version: 2, brief_sha256: 'd'.repeat(64),
      offer_ref: 'stage1-init-' + 'f'.repeat(32), offer_sha256: 'f'.repeat(64), confirmed: true},
    'project-1']]);

  const mismatches = {
    'v1 historical offer': ({stage1}) => {stage1.initialization_offer = {
      project_id: 'project-1', input_version: 1, brief_sha256: brief,
      plan_manifest_sha256: plan, offer_ref: 'stage1-init-' + offerHash.slice(0, 32),
      offer_sha256: offerHash, execution_authorized: false, status: 'ready-for-offline-ledger-initialization'};},
    'foreign current project': ({rt}) => {rt.ref = 'project-2';},
    'typed input mismatch': ({offer}) => {offer.input_version = '2';},
    'different current brief': ({offer}) => {offer.brief_sha256 = brief;},
    'different current plan': ({offer}) => {offer.plan_manifest_sha256 = plan;},
    'unconfirmed current input': ({project}) => {project.stage1_intake_ready = false;
      project.intake_report.necessary_clarification_complete = false;},
    'uncompiled current input': ({project}) => {project.plan = null;},
    'unknown current stage': ({stage1}) => {stage1.stage1_status = 'execution-unknown';},
  };
  for (const [name, mutate] of Object.entries(mismatches)) {
    const rejected = versionTwo(mutate);
    assert.doesNotMatch(rejected.render(), button, name);
    await rejected.tap();
    assert.deepEqual(rejected.writes, [], name);
  }
  current.stage1.stage1_status = 'offline-ledger-active';
  current.stage1.ledger = {valid: true, run_ref: 'stage1-v2'};
  current.stage1.initialization_offer = null;
  assert.match(current.render(), /data-real-initialization-status/);
  assert.doesNotMatch(current.render(), button);
  await current.tap();
  assert.equal(current.writes.length, 1, 'reopened initialized state cannot submit again');
  console.log('PASS Stage1 current-version stale-ledger offer and ' +
    Object.keys(mismatches).length + ' rejected version/brief/plan bindings');
})().catch(error => {console.error(error); process.exitCode = 1;});
"""


class Stage1IntakeControlsTests(unittest.TestCase):
    def test_offline_initialization_control(self):
        self._assert_check(CHECK, "PASS Stage1 bound initialization control")

    def test_current_version_after_prior_ledger(self):
        self._assert_check(CURRENT_VERSION_CHECK, "PASS Stage1 current-version stale-ledger offer")

    def _assert_check(self, check, expected):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for the Wiki renderer tests")
        source = Path(__file__).with_name("renderer") / "src/real-runtime.js"
        result = subprocess.run(
            [node, "-", str(source)],
            input=check,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(expected, result.stdout)

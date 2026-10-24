/* Real imported overview through current loadProject/buttons; DOM mock only. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const snapshot = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync(path.resolve(__dirname, '../../cli/research_workspace_native/web/projects.js'), 'utf8');
function extract(name, next, asyncName = false, asyncNext = false) {
  const begin = source.indexOf('  ' + (asyncName ? 'async ' : '') + 'function ' + name + '(');
  const end = source.indexOf('  ' + (asyncNext ? 'async ' : '') + 'function ' + next + '(', begin);
  assert(begin >= 0 && end > begin);
  return source.slice(begin, end);
}
(async () => {
  for (const language of ['en', 'zh-Hant', 'zh-Hans']) {
    const elements = new Map();
    function element(id) {
      if (!elements.has(id)) elements.set(id, {value:'stale-native-budget',checked:true,hidden:false,disabled:false,
        reset(){},querySelector(){return element(id+'-button');},querySelectorAll(){return [element(id+'-button')];}});
      return elements.get(id);
    }
    const state = {generation:0, readingGeneration:0, busy:false, language};
    const sandbox = {state, Event, pending:[], bootstrap:{models:false}, window:{},
      document:{dispatchEvent(){},querySelectorAll(){return [];}},
      $:element, budgetIds:{native_calls:'native-calls'}, rows:(v,k)=>v && Array.isArray(v[k])?v[k]:[],
      route:(ref,tail)=>tail, request:async route=>{if(route==='overview')return snapshot;throw Error('contract unavailable');},
      availableSavedPreparation:()=>false,availableDelivery:()=>false,
      renderProject(){},renderStages(){},refreshList:async()=>{},history:async()=>{},native:async()=>{}};
    vm.runInNewContext(extract('availableStage2','text') + extract('buttons','openReadingDraft',false,true) + extract('loadProject','identity',true,false) + '\n globalThis.load = loadProject;', sandbox);
    await sandbox.load(snapshot.project.project_ref);
    assert.equal(state.project.project_ref, snapshot.project.project_ref);
    assert.equal(state.project.input_version, snapshot.project.input_version);
    assert.equal(typeof state.project.input_version, 'string');
    assert.equal(state.stage2.offers[0].offer_sha256, snapshot.stage2.offers[0].offer_sha256);
    assert.equal(element('activate-stage2').disabled, false, 'verified offer remains actionable');
    assert.equal(element('confirm-form').hidden, true, 'imported Stage1 intake stays read-only');
    assert.equal(element('revise-form').hidden, true);
    assert.equal(element('native-calls').value, '', 'unknown imported budget is not invented or stale');
    assert.equal(element('search-consent').checked, false);
    assert.equal(element('read-consent').checked, false);
  }
  console.log('PASS: imported actual overview opens and exposes Stage2 activation, three languages, no invented Stage1 consent/budget');
})().catch(error=>{console.error(error);process.exitCode=1;});

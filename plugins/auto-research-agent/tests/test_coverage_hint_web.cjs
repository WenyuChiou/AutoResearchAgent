/* The coverage-gate hint text in the Host page: pure text, no browser, no host, no network. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../cli/research_workspace_native/web/projects.js'), 'utf8');
const start = source.indexOf('Object.assign(words.en, {coverageNeed');
const end = source.indexOf('function renderQueries()');
assert.ok(start > 0 && end > start, 'hint block not found');
function lines(language, need) {
  const words = {en: {}, 'zh-Hans': {}, 'zh-Hant': {}}, state = {language};
  const t = key => words[state.language][key] || words.en[key] || key;
  return new Function('words', 'state', 't', source.slice(start, end) + '; return coverageHintLines;')(words, state, t)(need);
}
const need = (over = {}) => ({min_closed_rounds: 3, min_search_attempts: 150, searches_per_round: 48, expansions_min: 6,
  approved_rounds: 3, approved_search_attempts: 14, can_reach_coverage_gate: false, ...over});

test('a scope that cannot reach the gate says so and still only informs', () => {
  const out = lines('zh-Hans', need());
  assert.equal(out.length, 2);
  assert.match(out[0], /至少需要 3 个已关闭的轮 \/ 150 次检索/);
  assert.match(out[0], /3 轮 \/ 14 次检索/);
  assert.match(out[1], /过不了覆盖门/);
  assert.match(out[1], /仍可授权/);
});

test('English wording says at least and shows both numbers', () => {
  const out = lines('en', need());
  assert.match(out[0], /at least 3 closed rounds \/ 150 search attempts/);
  assert.match(out[0], /3 rounds \/ 14 search attempts/);
  assert.match(out[1], /cannot pass the coverage gate/);
});

test('a sufficient scope gets one line and no warning', () => {
  const out = lines('en', need({approved_search_attempts: 150, can_reach_coverage_gate: true}));
  assert.equal(out.length, 1);
});

test('missing or malformed data adds nothing', () => {
  for (const value of [null, undefined, {}, {min_search_attempts: 'x'}]) assert.deepEqual(lines('en', value), []);
});

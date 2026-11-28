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
  min_reserved_seconds: 13530, plan_max_rounds: 3, plan_rounds_too_small: false,
  approved_rounds: 3, approved_search_attempts: 14, approved_seconds: 600,
  rounds_enough: true, search_attempts_enough: false, seconds_enough: false, can_reach_coverage_gate: false, ...over});
const texts = (language, value) => lines(language, value).map(row => row.text);

test('a scope that cannot reach the gate says so, names what is short, and still only informs', () => {
  const out = texts('zh-Hans', need());
  assert.equal(out.length, 2);
  assert.match(out[0], /至少需要 3 个已关闭的轮 \/ 150 次检索 \/ 13530 秒预留/);
  assert.match(out[0], /3 轮 \/ 14 次检索 \/ 600 秒预留/);
  assert.match(out[1], /过不了覆盖门/);
  assert.match(out[1], /仍可授权/);
  assert.match(out[1], /不够的是：次检索 \/ 秒预留/);
  assert.equal(lines('zh-Hans', need())[1].warn, true);
});

test('English wording says at least and shows all three numbers', () => {
  const out = texts('en', need());
  assert.match(out[0], /at least 3 closed rounds \/ 150 search attempts \/ 13530 reserved seconds/);
  assert.match(out[0], /3 rounds \/ 14 search attempts \/ 600 reserved seconds/);
  assert.match(out[1], /cannot pass the coverage gate/);
});

test('reserved seconds running out first is reported although attempts are enough', () => {
  const out = texts('en', need({search_attempts_enough: true, approved_search_attempts: 128}));
  assert.match(out[1], /Not enough: reserved seconds/);
});

test('a plan whose own round limit is too small is not described as a small scope', () => {
  const out = texts('zh-Hans', need({plan_rounds_too_small: true, plan_max_rounds: 2, rounds_enough: false}));
  assert.equal(out.length, 2);
  assert.match(out[1], /这份计划自己的轮数上限太小/);
  assert.match(out[1], /上限：2/);
  assert.doesNotMatch(out[1], /这个范围过不了/);
});

test('a sufficient scope gets one line and no warning', () => {
  const out = lines('en', need({approved_search_attempts: 150, approved_seconds: 13530, can_reach_coverage_gate: true,
    search_attempts_enough: true, seconds_enough: true}));
  assert.equal(out.length, 1);
  assert.equal(out[0].warn, false);
});

test('a value that cannot be computed shows the reason instead of nothing', () => {
  const out = texts('zh-Hans', {unavailable: 'coverage-plan-unreadable'});
  assert.equal(out.length, 1);
  assert.match(out[0], /暂时算不出覆盖门的最低需求。原因：coverage-plan-unreadable/);
  assert.match(texts('en', {unavailable: 'plan-values-invalid'})[0], /cannot be computed right now\. Reason: plan-values-invalid/);
});

test('missing data without a reason adds nothing', () => {
  for (const value of [null, undefined, {}, {min_search_attempts: 'x'}]) assert.deepEqual(lines('en', value), []);
});

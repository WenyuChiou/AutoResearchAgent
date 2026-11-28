// Structural guard for the card gate (review 1128): every control that can write must be inside a gate scope.
//
// What counts as a "control that can write" (the rule is deliberately broad and default-deny):
//   every <button>, <input type=file|submit>, and <form> that is VISIBLE on a V1 page, in a shadow root too.
//   A control is fine when
//     (a) it carries data-v1-write AND has a card root (nearest [data-v1-card] or <section>), the scope v1GateCards uses; or
//     (b) it is listed in NOT_A_WRITE below by a data-* attribute: navigation, filters, tabs, local-only or read-only
//         (GET) actions. A control with an attribute that is in neither list FAILS: a new entry cannot slip through
//         without being classified here, and a write entry cannot be classified without getting the gate.
//   A <form> is fine when it contains a marked control.
// Part 1 is static and always runs: templates in the V1-reachable modules that draw a file input, a submit button or a
// form must carry data-v1-write. Part 2 renders the real pages in Chrome (Playwright) in zh, en and tw and applies the rule;
// it needs a running preview, so it runs only when V1_PLAYWRIGHT (path of the playwright module) and V1_ORIGIN
// (e.g. http://127.0.0.1:62488/, the zero-quota preview with sample projects: project rows 0..4 = scope page, scope
// confirmed, scope confirmed, archive, synthetic Stage 2) are set; V1_INVENTORY_OUT writes the control list as JSON.
// Part 2 also fails when an en/tw page shows a fallback marker (text that fell back to Simplified Chinese).
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const read = name => fs.readFileSync(path.join(__dirname, name), 'utf8');
const MARK = '⁠';

// Controls that never write. Navigation, tabs, filters, local-only and read-only (GET) actions, by data-* attribute.
const NOT_A_WRITE = new Set([
 'data-page', 'data-stage', 'data-v1-menu', 'data-v1-goto', 'data-v1-home', 'data-v1-open', 'data-v1-reload', 'data-v1g-guide', 'data-v1g-open',
 'data-v1g-close', 'data-v1g-filter', 'data-v1g-raw', 'data-v1g-download', 'data-v1-leave', 'data-v1-alert-close', 'data-v1-recover', 'data-v1-later',
 'data-wiki-home-open', 'data-wiki-home-filter', 'data-wiki-home-focus', 'data-wiki-home-guide-close', 'data-wiki-home-codex', 'data-wiki-home-recover', 'data-wiki-home-retry', 'data-wiki-home-pending-open',
 'data-s1-tab', 'data-s1-graph', 'data-s1-group', 'data-s1-mode', 'data-s1-paper', 'data-s1-claim', 'data-s1-check', 'data-s1-relation', 'data-s1-sort',
 'data-s2-tab', 'data-s2-card', 'data-s2-card-open', 'data-s2-flag', 'data-s2-lit', 'data-s2-save', 'data-s2-compare', 'data-s2-pick',
 'data-s3-tab', 'data-s3-dec-read',
 'data-ws-go', 'data-ws-load-paper', 'data-ws-draft', 'data-ws-edit-scope', 'data-wsg-reason-confirm',
 'data-node-key', 'data-spatial-navigation', 'data-live-mode', 'data-live-paper', 'data-live-tab', 'data-live-phase', 'data-live-file',
 'data-wc-open', 'data-wc-close', 'data-wc-new', 'data-wc-refresh', 'data-wc-recheck', 'data-wc-settings', 'data-wc-chip', 'data-wc-tech', 'data-wc-other',
 'data-n9-file', 'data-n9-export', 'data-n9-open-packet', 'data-n9-jump', 'data-n9-focus', 'data-n9-route', 'data-n2-view', 'data-v93-read', 'data-v94-read', 'data-v96-read',
 'data-v94f-focus', 'data-v94f-edit-refused', 'data-v95-material-download'
]);

// ---------- Part 1: static ----------
const MODULES = fs.readdirSync(__dirname).filter(n => /^(wiki-.*|v9-.*|stage2_display)\.js$/.test(n) && n !== 'wiki-v1-text.js').concat(['renderer/src/expansion-ui.js', 'renderer/src/retirement-ui.js']);
test('static: templates that draw a file input, a submit button or a form carry data-v1-write', () => {
 const problems = [];
 for (const file of MODULES) {
  const src = read(file);
  for (const m of src.matchAll(/<(input)\b[^>]*type="file"[^>]*>|<button\b[^>]*type="submit"[^>]*>/g)) {
   if (!/data-v1-write/.test(m[0])) problems.push(`${file}: ${m[0].slice(0, 90)}`);
  }
  for (const m of src.matchAll(/<form\b[^>]*>/g)) {
   const after = src.slice(m.index, src.indexOf('</form>', m.index) + 7);
   if (!/data-v1-write/.test(after)) problems.push(`${file}: <form> without a marked control: ${m[0].slice(0, 70)}`);
  }
 }
 assert.deepEqual(problems, [], 'unmarked write-capable templates:\n' + problems.join('\n'));
});

// ---------- Part 2: rendered pages ----------
const PLAYWRIGHT = process.env.V1_PLAYWRIGHT, ORIGIN = process.env.V1_ORIGIN;
const live = PLAYWRIGHT && ORIGIN ? test : test.skip;
live('rendered V1 pages (zh, en, tw): every control that can write is inside a gate scope; no fallback text on en/tw pages', async () => {
 const {chromium} = require(PLAYWRIGHT);
 const browser = await chromium.launch({channel: 'chrome', headless: true});
 const inventory = {}, problems = [];
 const collect = () => {
  const visible = el => !!el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
  const rows = [], seen = new Set();
  const visit = (el, inShadow) => {
   if (seen.has(el)) return; seen.add(el);
   if (!visible(el)) return;
   const attrs = el.getAttributeNames().filter(n => n.startsWith('data-') && !/^data-(v1-gated|v1-write|v1-card|connection-basis|v7-index|v7-expansion-index|v7-expansion-basis|v7-control-ref|v7-control-key|v7-control-basis|v7-archive-basis|v7-job|ws-gate|ws-needs.*|ws-blocked|wsg-prepared|wsg-base|n9-.*-basis|node-kind|node-shape|spatial-navigation-mode|s1-paper-index)$/.test(n));
   const card = el.closest('[data-v1-card]') || el.closest('section');
   rows.push({tag: el.tagName.toLowerCase() + (el.type ? '[' + el.type + ']' : ''), attrs, marked: el.hasAttribute('data-v1-write'), hasCard: !!card || inShadow, inShadow,
    text: (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 40), hasMarkedChild: el.tagName === 'FORM' ? !!el.querySelector('[data-v1-write]') : false});
  };
  const scan = (root, inShadow) => {
   for (const el of root.querySelectorAll('button, input[type=file], input[type=submit], form')) visit(el, inShadow);
   for (const host of root.querySelectorAll('*')) if (host.shadowRoot) scan(host.shadowRoot, true);
  };
  scan(document.querySelector('.hs-product') || document.body, false);
  const wc = document.querySelector('.wc-root'); if (wc) scan(wc, false);
  return {rows, marker: (document.body.innerText || '').includes('⁠')};
 };
 try {
  for (const lang of ['zh', 'en', 'tw']) {
   const page = await (await browser.newContext({viewport: {width: 1440, height: 900}})).newPage();
   const record = async label => {
    const {rows, marker} = await page.evaluate(collect);
    inventory[`${lang} | ${label}`] = rows;
    if (lang !== 'zh' && marker) problems.push(`${lang} | ${label}: text fell back to Simplified Chinese (fallback marker on the page)`);
    for (const r of rows) {
     const key = r.attrs.join(' ') || r.tag;
     if (r.tag === 'form') { if (!r.hasMarkedChild && !r.attrs.some(a => NOT_A_WRITE.has(a))) problems.push(`${lang} | ${label}: form ${key} has no marked control`); continue; }
     if (r.marked) { if (!r.hasCard) problems.push(`${lang} | ${label}: marked control ${key} "${r.text}" has no card root`); continue; }
     if (r.attrs.some(a => NOT_A_WRITE.has(a))) continue;
     if (!r.attrs.length && ['button', 'button[button]'].includes(r.tag)) continue; // plain buttons without any action attribute do nothing on their own
     problems.push(`${lang} | ${label}: unclassified control ${r.tag} ${key} "${r.text}": mark it data-v1-write (and give it a card) or classify it in NOT_A_WRITE`);
    }
   };
   const go = async (row, steps = []) => {
    await page.goto(ORIGIN, {waitUntil: 'load'}); await page.waitForSelector('select[data-language]'); await page.waitForTimeout(900);
    await page.selectOption('select[data-language]', lang); await page.waitForTimeout(900);
    if (row === null) return;
    await page.click(`tr[data-wiki-home-origin] button[data-wiki-home-open] >> nth=${row}`); await page.waitForTimeout(2800);
    for (const selector of steps) { const el = await page.$(selector); if (el) { await el.click(); await page.waitForTimeout(1300); } }
   };
   await go(null); await record('home');
   await go(0); await record('project 0: scope page');
   await go(1); await record('project 1: stage 1');
   for (const tab of ['sources', 'evidence', 'synthesis', 'ops', 'materials']) { const el = await page.$(`[data-s1-tab="${tab}"]`); if (el) { await el.click(); await page.waitForTimeout(1200); await record('project 1: stage 1 ' + tab); } }
   { const el = await page.$('[data-wc-open]'); if (el) { await el.click(); await page.waitForTimeout(900); await record('project 1: chat drawer open'); } }
   await go(3); for (const tab of ['sources', 'evidence', 'materials']) { const el = await page.$(`[data-s1-tab="${tab}"]`); if (el) { await el.click(); await page.waitForTimeout(1200); await record('archive: ' + tab); } }
   await go(4); await record('synthetic: stage 2');
   for (const tab of ['literature', 'materials']) { const el = await page.$(`[data-s2-tab="${tab}"]`); if (el) { await el.click(); await page.waitForTimeout(1200); await record('synthetic: stage 2 ' + tab); } }
   { const el = await page.$('.v1-flow-item[data-stage="3"]'); if (el) { await el.click(); await page.waitForTimeout(1500); await record('synthetic: stage 3'); } }
   { const el = await page.$('[data-s3-tab="materials"]'); if (el) { await el.click(); await page.waitForTimeout(1200); await record('synthetic: stage 3 materials'); } }
   for (const nav of ['files', 'history', 'settings']) { const el = await page.$(`.v1-nav-item[data-page="${nav}"]`); if (el) { await el.click(); await page.waitForTimeout(1300); await record('global: ' + nav); } }
   await page.context().close();
  }
 } finally { await browser.close(); }
 if (process.env.V1_INVENTORY_OUT) fs.writeFileSync(process.env.V1_INVENTORY_OUT, JSON.stringify(inventory, null, 1), 'utf8');
 assert.deepEqual([...new Set(problems)], [], 'unguarded controls:\n' + [...new Set(problems)].join('\n'));
});

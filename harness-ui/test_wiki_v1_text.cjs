// Wiki V1 copy table (wiki-v1-text.js): the three languages carry the same keys and the same {placeholders}, nothing is
// empty, every v1t('...') in the translated modules has an entry (and every entry is used), a missing en/tw text falls
// back to the Simplified key and warns once per key. No network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = name => fs.readFileSync(path.join(__dirname, name), 'utf8');
const TRANSLATED = ['wiki-home.js', 'wiki-v1.js', 'wiki-v1-global.js', 'wiki-harness-record.js', 'wiki-stage1.js', 'wiki-stage1-ops.js', 'wiki-stage1-materials.js', 'wiki-stage1-grant.js', 'wiki-stage2.js', 'wiki-stage3.js', 'wiki-stage3-plan-request.js', 'wiki-stage3-decision.js', 'wiki-chat.js'];
const MARK = '\u2060';
const CJK = /[　-〿一-鿿＀-￯]/;

function load(lang) {
 const warnings = [];
 const context = vm.createContext({apps:[{lang}], console:{warn:(...args) => warnings.push(args.join(' '))}});
 vm.runInContext(read('wiki-v1-text.js') + '\nthis.__t = {v1Text, v1t, v1Lang, v1StageLang, v1Locale};', context);
 return {t:context.__t, warnings, context};
}
const table = load('zh').t.v1Text;
const keys = Object.keys(table);
const placeholders = text => (String(text).match(/\{\w+\}/g) || []).sort().join(',');

// 1. Same keys, no empty values, same placeholders in all three languages.
assert.ok(keys.length > 500, 'the batch 1 table has its entries');
for (const key of keys) {
 const entry = table[key];
 assert.deepEqual(Object.keys(entry).sort(), ['en', 'tw'], 'only en and tw are stored; zh is the key: ' + key);
 for (const lang of ['en', 'tw']) {
  assert.equal(typeof entry[lang], 'string', lang + ' value is a string: ' + key);
  assert.ok(entry[lang].trim().length > 0, lang + ' value is not empty: ' + key);
  assert.equal(placeholders(entry[lang]), placeholders(key), lang + ' placeholders match the key: ' + key);
  assert.ok(!/[<>"]/.test(entry[lang]), lang + ' adds no markup characters: ' + key);
 }
 assert.ok(CJK.test(key.replace(/\{\w+\}/g, '')), 'the key is Simplified Chinese text: ' + key);
}
// English text has no CJK at all; Traditional text has no Simplified-only character.
const simplifiedOnly = /[这个课题还没后页点档项设为过时间导览载够发称线续决问许额检运连续资护验证编选历状态观览图]/;
for (const key of keys) {
 assert.ok(!CJK.test(table[key].en), 'en has no Chinese characters: ' + key);
 assert.ok(!simplifiedOnly.test(table[key].tw), 'tw has no Simplified-only character: ' + key + ' => ' + table[key].tw);
}
// Taiwan wording where the two forms differ (a character-only conversion would leave these wrong).
const twAll = keys.map(key => table[key].tw).join('\n');
for (const bad of ['文献', '默认', '信息', '保存', '项目', '链接', '设置', '界面', '数据', '检索词', '运行']) {
 assert.ok(!twAll.includes(bad), 'tw does not use the mainland form ' + bad);
}
for (const bad of ['預設', '信息', '資訊系統', '保存', '鏈接', '界面', '數據', '運行']) {
 assert.ok(!twAll.includes(bad), 'tw does not use ' + bad);
}

// Terms fixed by the authorization review (1128): consent form, 呼叫 / 取得 / 重送 / 連線與設定 in Traditional text.
for (const key of keys) {
 if (key.includes('同意书')) assert.ok(!/consent(?! form| items)/i.test(table[key].en), 'en says consent form for 同意书: ' + key);
 assert.ok(!/調用|獲取|重發|連接與設定/.test(table[key].tw), 'tw uses 呼叫/取得/重送/連線與設定: ' + key);
}

// Quota wording (checked against the backend 1128): the seconds budget is a total (project_resource_budget.py remaining =
// declared - reserved; project_stage1_run_grant.py max_seconds <= budgets.seconds), never "per call".
for (const key of keys) assert.ok(!key.includes('每次最多'), 'no quota text says 每次最多: ' + key);
for (const file of TRANSLATED) assert.ok(!read(file).includes('每次最多'), file + ' has no 每次最多');
// The Stage 1 quota bar number is models.calls_reserved (wsBudget), so it says reserved, like the settings page.
assert.ok(!Object.hasOwn(table, '已用 {n} /') && /Reserved/.test(table['已预留 {n} /']?.en) && /已預留/.test(table['已预留 {n} /']?.tw), 'the quota bar says reserved, not used');
assert.ok(read('wiki-stage1-ops.js').includes("v1t('已预留 {n} /'"), 'wiki-stage1-ops.js shows the reserved count');
{
 const quotaLine = '模型调用 {usedPart}上限 {n} · 检索 上限 {n2} · 总共最多 {n3} 秒';
 assert.ok(Object.hasOwn(table, quotaLine) && /in total/.test(table[quotaLine].en) && /總共/.test(table[quotaLine].tw), 'the quota line says the seconds are a total in en and tw');
 assert.ok(/total/i.test(table['总共最多'].en) && /總共/.test(table['总共最多'].tw), 'the quota bar label says total in en and tw');
}

// 2. Source and table agree in both directions.
function used(file) {
 const src = read(file), found = new Set();
 const unesc = body => body.replace(/\\(u[0-9a-fA-F]{4}|.)/g, (m, c) => c[0] === 'u' && c.length === 5 ? String.fromCharCode(parseInt(c.slice(1), 16)) : c === 'n' ? '\n' : c);
 for (const m of src.matchAll(/v1t\('((?:[^'\\\n]|\\.)*)'/g)) found.add(unesc(m[1]));
 if (file === 'wiki-v1-text.js') return found;
 const lines = src.split('\n');
 // Labels added to a lazy table at load time hold the Simplified text (translated when read), e.g. Object.assign(wikiS1Checks, {...}).
 for (const line of lines) {
  if (!/^(Object\.assign\(wiki|wikiS1Tabs\.)/.test(line)) continue;
  for (const q of line.matchAll(/'((?:[^'\\]|\\.)*)'/g)) { const text = unesc(q[1]); if (CJK.test(text)) found.add(text); }
 }
 for (let n = 0; n < lines.length; n++) {
  if (!/^(const|let|var)\s+[\w$]+\s*=/.test(lines[n])) continue;
  const fn = /^(const|let|var)\s+[\w$]+\s*=\s*(async\s+)?(function\b|\([^)]*\)\s*=>|[\w$]+\s*=>)/.test(lines[n]);
  let m = n + 1;
  while (m < lines.length && !(lines[m].length && !/^[\s}\])]/.test(lines[m]))) m++;
  if (!fn) {
   for (let k = n; k < m; k++) {
    for (const q of lines[k].replace(/\s\/\/.*$/, '').matchAll(/'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"/g)) {
     const s = unesc(q[1] ?? q[2]);
     if (CJK.test(s)) found.add(s);
    }
   }
  }
  n = m - 1;
 }
 return found;
}
const usedKeys = new Set();
for (const file of [...TRANSLATED, 'wiki-v1-text.js']) for (const key of used(file)) usedKeys.add(key);
for (const key of usedKeys) assert.ok(Object.hasOwn(table, key), 'used in the code but missing from the table: ' + key);
for (const key of keys) assert.ok(usedKeys.has(key), 'in the table but not used by any translated module: ' + key);

// 3. Behaviour of v1t.
{
 const zh = load('zh'), en = load('en'), tw = load('tw');
 const key = '打开 {title}{twin}';
 assert.equal(zh.t.v1t(key, {title:'甲', twin:''}), '打开 甲', 'Simplified shows the key itself');
 assert.equal(en.t.v1t(key, {title:'A', twin:' · x'}), 'Open A · x');
 assert.equal(tw.t.v1t(key, {title:'A', twin:''}), '開啟 A');
 assert.equal(en.t.v1t('项目文件'), 'Project files');
 assert.equal(tw.t.v1t('项目文件'), '專案檔案');
 assert.equal(en.t.v1t('不在表里 {n} 次', {n:3}), '不在表里 3 次' + MARK, 'a key that is not in the table shows as written (fallback) with the fallback marker');
 assert.equal(zh.t.v1t('不在表里 {n} 次', {n:3}), '不在表里 3 次', 'zh never carries the marker');
 assert.equal(en.t.v1t('ready-code'), 'ready-code', 'text without Chinese (codes, ids) passes through untouched');
 assert.equal(en.warnings.length, 1, 'and does not warn');
 assert.equal(en.t.v1t('值 {a}', {}), '值 {a}' + MARK, 'an unfilled placeholder stays visible');
 assert.equal(en.t.v1t(undefined), undefined);
 assert.equal(en.t.v1t(''), '');
 assert.equal(en.t.v1t('未知的键，没有译文'), '未知的键，没有译文' + MARK, 'missing key falls back to the Simplified key, never blank');
 en.t.v1t('未知的键，没有译文');
 assert.equal(en.warnings.filter(line => line.includes('未知的键，没有译文')).length, 1, 'one warning per key');
 tw.t.v1t('未知的键，没有译文');
 assert.equal(tw.warnings.length, 1, 'tw warns on its own');
 assert.equal(zh.warnings.length, 0, 'zh never warns');
 // An entry whose value is empty or missing also falls back and warns.
 const probe = load('en');
 vm.runInContext("v1Text['空值'] = {en:'', tw:'x'}; v1Text['缺值'] = {tw:'x'};", probe.context);
 assert.equal(probe.t.v1t('空值'), '空值' + MARK);
 assert.equal(probe.t.v1t('缺值'), '缺值' + MARK);
 assert.equal(probe.warnings.length, 2);
 // The language comes from apps[0].lang; unknown languages read as zh.
 const flip = load('en');
 flip.context.apps[0].lang = 'tw';
 assert.equal(flip.t.v1Locale(), 'tw');
 flip.context.apps[0].lang = 'constructor';
 assert.equal(flip.t.v1Locale(), 'zh');
 // Gates: every page (home, global pages, Stage pages, drawer) opens for all three languages.
 for (const lang of ['zh', 'en', 'tw']) assert.equal(zh.t.v1Lang({lang}), true);
 for (const lang of ['fr', 'constructor', undefined]) assert.equal(zh.t.v1Lang({lang}), false);
 assert.equal(zh.t.v1Lang(null), false);
 assert.deepEqual(['zh', 'en', 'tw'].map(lang => zh.t.v1StageLang({lang})), [true, true, true]);
 // v1Lazy tables read through v1t at the moment of use.
 const lazy = en.context.apps[0];
 lazy.lang = 'en';
 const table1 = vm.runInContext("v1Lazy({names: [['x', '项目文件']], one: '项目文件', n: 3, re: /a/})", en.context);
 assert.equal(table1.one, 'Project files');
 assert.equal(table1.names[0][1], 'Project files');
 assert.equal(table1.names.map(([id, name]) => id + name).join(), 'xProject files');
 assert.equal(table1.n, 3);
 lazy.lang = 'tw';
 assert.equal(table1.one, '專案檔案', 'the same table follows a language switch');
 lazy.lang = 'zh';
 assert.equal(table1.one, '项目文件');
}

// 4. Chinese text left outside v1t() in the translated modules is a table key used by lookup, a comparison with
//    another module's Simplified text (Stage pages are Simplified-only for now), or a regular expression.
for (const file of TRANSLATED) {
 const lines = read(file).split('\n');
 lines.forEach((line, i) => {
  const bare = line.replace(/\s\/\/.*$/, '').replace(/^\s*\/\/.*$/, '').replace(/v1t\('((?:[^'\\\n]|\\.)*)'/g, 'v1t(\'\'');
  for (const q of bare.matchAll(/'((?:[^'\\]|\\.)*)'/g)) {
   if (!CJK.test(q[1])) continue;
   const text = q[1].replace(/\\'/g, "'");
   const ok = Object.hasOwn(table, text) || /===|!==|\.includes\(|\.test\(|\.replace\(|indexOf\(/.test(bare);
   assert.ok(ok, `${file}:${i + 1} Chinese literal outside v1t(): ${text}`);
  }
 });
}
console.log('PASS Wiki V1 text table: ' + keys.length + ' keys, same keys and placeholders in en/tw, fallback warns once, source and table agree.');

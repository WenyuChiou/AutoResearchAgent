// Wiki V1 copy table (wiki-v1-text.js): the three languages carry the same keys and the same {placeholders}, nothing is
// empty, every v1t('...') in the translated modules has an entry (and every entry is used), a missing en/tw text falls
// back to the Simplified key and warns once per key. No network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = name => fs.readFileSync(path.join(__dirname, name), 'utf8');
const TRANSLATED = ['wiki-home.js', 'wiki-v1.js', 'wiki-v1-global.js', 'wiki-harness-record.js'];
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
for (const bad of ['項目', '預設', '信息', '資訊系統', '保存', '鏈接', '界面', '數據', '運行']) {
 assert.ok(!twAll.includes(bad), 'tw does not use ' + bad);
}

// 2. Source and table agree in both directions.
function used(file) {
 const src = read(file), found = new Set();
 const unesc = body => body.replace(/\\(u[0-9a-fA-F]{4}|.)/g, (m, c) => c[0] === 'u' && c.length === 5 ? String.fromCharCode(parseInt(c.slice(1), 16)) : c === 'n' ? '\n' : c);
 for (const m of src.matchAll(/v1t\('((?:[^'\\\n]|\\.)*)'/g)) found.add(unesc(m[1]));
 const lines = src.split('\n');
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
for (const file of TRANSLATED) for (const key of used(file)) usedKeys.add(key);
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
 assert.equal(en.t.v1t('不在表里 {n} 次', {n:3}), '不在表里 3 次', 'a key that is not in the table shows as written (fallback)');
 assert.equal(en.t.v1t('值 {a}', {}), '值 {a}', 'an unfilled placeholder stays visible');
 assert.equal(en.t.v1t(undefined), undefined);
 assert.equal(en.t.v1t(''), '');
 assert.equal(en.t.v1t('未知的键，没有译文'), '未知的键，没有译文', 'missing key falls back to the Simplified key, never blank');
 en.t.v1t('未知的键，没有译文');
 assert.equal(en.warnings.filter(line => line.includes('未知的键，没有译文')).length, 1, 'one warning per key');
 tw.t.v1t('未知的键，没有译文');
 assert.equal(tw.warnings.length, 1, 'tw warns on its own');
 assert.equal(zh.warnings.length, 0, 'zh never warns');
 // An entry whose value is empty or missing also falls back and warns.
 const probe = load('en');
 vm.runInContext("v1Text['空值'] = {en:'', tw:'x'}; v1Text['缺值'] = {tw:'x'};", probe.context);
 assert.equal(probe.t.v1t('空值'), '空值');
 assert.equal(probe.t.v1t('缺值'), '缺值');
 assert.equal(probe.warnings.length, 2);
 // The language comes from apps[0].lang; unknown languages read as zh.
 const flip = load('en');
 flip.context.apps[0].lang = 'tw';
 assert.equal(flip.t.v1Locale(), 'tw');
 flip.context.apps[0].lang = 'constructor';
 assert.equal(flip.t.v1Locale(), 'zh');
 // Gates: the batch 1 pages open for all three languages; Stage pages and the drawer stay Simplified until batch 2.
 for (const lang of ['zh', 'en', 'tw']) assert.equal(zh.t.v1Lang({lang}), true);
 for (const lang of ['fr', 'constructor', undefined]) assert.equal(zh.t.v1Lang({lang}), false);
 assert.equal(zh.t.v1Lang(null), false);
 assert.deepEqual(['zh', 'en', 'tw'].map(lang => zh.t.v1StageLang({lang})), [true, false, false]);
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

// Home page at 390-900px (wiki-home.css). Browser check: check_wiki_v1_narrow_browser.cjs scenario home-root.
// Cause of the old 632px page: .wiki-home was a one-column grid with an automatic track, so the 「开始一个新研究」
// card's input (intrinsic ~490px) set the minimum width of the page; and the hidden 「操作」 label in the project table
// is absolutely placed, so without a positioned scroll box it escaped the table's overflow and widened the page.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const css = fs.readFileSync(path.join(__dirname, 'wiki-home.css'), 'utf8');
const rule = selector => {
 const start = css.indexOf('\n' + selector + ' {');
 assert.ok(start >= 0, 'missing rule ' + selector);
 return css.slice(start, css.indexOf('}', start));
};
assert.match(rule('.wiki-home'), /grid-template-columns:\s*minmax\(0,\s*1fr\)/, 'the page grid has one shrinkable column');
assert.match(css, /\.wiki-home > \*, \.wiki-home-top > \* \{ min-width:0; \}/, 'grid items may shrink below their content');
assert.match(rule('.wiki-home-table'), /overflow-x:\s*auto/);
assert.match(rule('.wiki-home-table'), /position:\s*relative/, 'the scroll box contains the absolutely placed hidden label');
assert.match(rule('.wiki-home-visually-hidden'), /position:\s*absolute/);
console.log('PASS home layout rules keep the page inside narrow screens.');

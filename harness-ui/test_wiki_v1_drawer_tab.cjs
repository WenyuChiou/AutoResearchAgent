// The right edge carries one Codex tab: the real drawer button (wiki-chat.js, button.wc-tab). The grey placeholder tag
// 「Codex 对话 · 还没有开放」 (commit 4a32ddac, role="note", not a button) is gone from the scripts and styles.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const read = name => fs.readFileSync(path.join(__dirname, name), 'utf8');

for (const name of fs.readdirSync(__dirname).filter(file => /^wiki-.*\.(js|css)$/.test(file))) {
 const text = read(name);
 assert.ok(!text.includes('data-v1-drawer-tab'), name + ' still draws the placeholder tab');
 assert.ok(!text.includes('v1-drawer-tab'), name + ' still styles the placeholder tab');
 assert.ok(!/Codex 对话[^\n]*还没有开放/.test(text), name + ' still words the placeholder tag');
}
const chat = read('wiki-chat.js');
assert.match(chat, /class="wc-tab"/, 'the real drawer tab stays');
// The drawer root lets clicks through everywhere except its own tab and panel, so a closed drawer never blocks the page.
assert.match(read('wiki-chat.css'), /\.wc-root \{[^}]*pointer-events:none/);
console.log('PASS right edge: only the real wc-tab button, no placeholder tag.');

// Page wording must not show launch flags such as --run-limits (acceptance M-4); say it in words.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
for (const name of fs.readdirSync(__dirname).filter(file => /^wiki-.*\.js$/.test(file))) {
 const text = fs.readFileSync(path.join(__dirname, name), 'utf8');
 const shown = text.split('\n').filter(line => !/^\s*\/\//.test(line)).join('\n');
 assert.doesNotMatch(shown, /--run-limits|--[a-z]+-[a-z-]+ 重新启动/, name + ' shows a command-line flag in page text');
}
console.log('PASS no launch flags in page wording.');

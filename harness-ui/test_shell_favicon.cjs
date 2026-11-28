// The page has no favicon file; without an explicit empty icon every page load asked /favicon.ico and logged a 404 (acceptance M-3).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const shell = fs.readFileSync(path.join(__dirname, 'renderer/src/shell.html'), 'utf8');
assert.match(shell, /<link rel="icon" href="data:,">/);
assert.match(fs.readFileSync(path.join(__dirname, 'run_v7.py'), 'utf8'), /img-src 'self' data:/, 'the content policy allows the data: icon');
console.log('PASS shell declares an empty icon.');

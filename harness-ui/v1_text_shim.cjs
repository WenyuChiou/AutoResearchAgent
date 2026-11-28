// Test helper (not a test): Wiki V1 modules call v1t() from wiki-v1-text.js, which the production bundle loads before
// them. The older unit tests load single modules or slices of them into a vm context; requiring this file makes
// vm.runInContext define the copy table in each new context before the first code that uses v1t(), v1Lazy() or the
// language gates. Contexts that already define v1t are left alone.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const textSource = fs.readFileSync(path.join(__dirname, 'wiki-v1-text.js'), 'utf8');
const original = vm.runInContext;
const prepared = new WeakSet();
vm.runInContext = function (code, context, ...rest) {
 if (context && typeof context === 'object' && !prepared.has(context) && /\b(v1t|v1Lazy|v1Lang|v1StageLang|v1Locale)\b/.test(String(code))) {
  prepared.add(context);
  if (!Object.hasOwn(context, 'v1t')) original.call(vm, textSource, context);
 }
 return original.call(vm, code, context, ...rest);
};

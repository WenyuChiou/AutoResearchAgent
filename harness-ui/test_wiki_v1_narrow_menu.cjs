// Narrow-screen menu logic of the Wiki V1 shell (wiki-v1.js "Narrow screens" block), run against stub DOM objects.
// The real layout is checked in a browser by check_wiki_v1_narrow_browser.cjs.
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(path.join(__dirname, 'wiki-v1.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, 'wiki-v1.css'), 'utf8');
const start = source.indexOf('function v1MenuSet('), end = source.indexOf("document.addEventListener('toggle'", start);
assert(start > 0 && end > start, 'the narrow menu block must exist');

function setup() {
 const handlers = {};
 const attrs = {};
 const button = { attrs: {}, focused: 0, setAttribute(k, v) { this.attrs[k] = v; }, focus() { this.focused++; } };
 const side = { open: false, toggleAttribute(k, on) { this.open = !!on; }, querySelector: s => s === '[data-v1-menu]' ? button : null, contains: n => n === button || n === side };
 const app = { el: { querySelector: s => s === '.v1-side' ? side : null }, v1MenuOpen: false };
 const target = hit => ({ closest: s => s.split(',').some(sel => hit.includes(sel.trim())) ? {} : null });
 const media = {}; const context = { apps: [app], v1On: () => true, window: { addEventListener: (type, fn) => { handlers[type] = fn; }, matchMedia: q => { media.query = q; return { addEventListener: (type, fn) => { media[type] = fn; } }; } }, document: { activeElement: button } };
 vm.createContext(context);
 vm.runInContext(source.slice(start, end), context);
 return { app, side, button, handlers, target, media };
}

test('menu button toggles aria-expanded and the open state', () => {
 const { app, side, button, handlers, target } = setup();
 handlers.click({ target: target(['[data-v1-menu]']) });
 assert.equal(app.v1MenuOpen, true); assert.equal(side.open, true); assert.equal(button.attrs['aria-expanded'], 'true');
 handlers.click({ target: target(['[data-v1-menu]']) });
 assert.equal(app.v1MenuOpen, false); assert.equal(side.open, false); assert.equal(button.attrs['aria-expanded'], 'false');
});

test('Escape closes the menu and returns focus to the button', () => {
 const { app, button, handlers, target } = setup();
 handlers.click({ target: target(['[data-v1-menu]']) });
 handlers.keydown({ key: 'Escape' });
 assert.equal(app.v1MenuOpen, false); assert.equal(button.attrs['aria-expanded'], 'false'); assert.equal(button.focused, 1);
 handlers.keydown({ key: 'Escape' }); // already closed: nothing happens
 assert.equal(button.focused, 1);
});

test('picking a menu item or clicking outside closes it; other keys and in-menu labels do not', () => {
 const { app, handlers, target } = setup();
 handlers.click({ target: target(['[data-v1-menu]']) });
 handlers.keydown({ key: 'a' });
 handlers.click({ target: target(['.v1-side']) });
 assert.equal(app.v1MenuOpen, true, 'a click on non-navigating sidebar text keeps the menu open');
 handlers.click({ target: target(['.v1-side', '[data-stage]']) });
 assert.equal(app.v1MenuOpen, false);
 handlers.click({ target: target(['[data-v1-menu]']) });
 handlers.click({ target: target([]) });
 assert.equal(app.v1MenuOpen, false);
});

test('markup and CSS contract: button is hidden on desktop and shown only in the narrow media block', () => {
 assert(/<button type="button" class="v1-menu-btn" data-v1-menu aria-controls="v1-side" aria-expanded="/.test(source));
 assert(css.includes('.v1-menu-btn { display:none; }'));
 const media = css.slice(css.indexOf('@media (max-width:900px)'));
 assert(media.includes('.v1-menu-btn { display:inline-flex;') && media.includes('grid-template-columns') === true);
 assert(!css.slice(0, css.indexOf('@media (max-width:900px)')).includes('.v1-menu-btn { display:inline-flex'));
 assert(/min-height:44px; min-width:44px/.test(media), 'menu button keeps a 44px target');
});

test('crossing the 900px breakpoint closes the menu and resets aria-expanded', () => {
 const { app, side, button, handlers, target, media } = setup();
 assert.equal(media.query, '(max-width: 900px)');
 handlers.click({ target: target(['[data-v1-menu]']) });
 assert.equal(button.attrs['aria-expanded'], 'true');
 media.change();
 assert.equal(app.v1MenuOpen, false); assert.equal(side.open, false); assert.equal(button.attrs['aria-expanded'], 'false'); assert.equal(button.focused, 0);
});

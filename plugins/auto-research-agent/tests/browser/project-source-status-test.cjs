/* Actual API serializer records → actual renderSources/text functions.
 * Authored DOM by default; optional installed-browser run uses a temporary
 * loopback HTTP page. Neither mode executes the full project page or a worker. */
'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const crypto = require('node:crypto');
const jobs = JSON.parse(fs.readFileSync(0, 'utf8'));
const web = path.resolve(__dirname, '../../cli/research_workspace_native/web');
const source = fs.readFileSync(path.join(web, 'projects.js'), 'utf8');
function slice(start, end) {
  const first = source.indexOf(start), last = source.indexOf(end, first);
  assert(first >= 0 && last > first); return source.slice(first, last);
}
const textFunction = source.match(/^  function text\(.*$/m);
assert(textFunction);
const functions = textFunction[0] + '\n' + slice('  function renderSources()', '  async function executeSourceGrant(');
const languages = ['en', 'zh-Hans', 'zh-Hant'];
const labels = {
  en: ['Acquisition', 'Parsing / Harness source registration', 'Reading is recorded separately'],
  'zh-Hans': ['来源获取', '解析 / Harness 来源登记', '阅读单独记录'],
  'zh-Hant': ['來源取得', '解析 / Harness 來源登記', '閱讀單獨記錄']
};
class Element {
  constructor(tag) {this.tag = tag; this.children = []; this.ownText = '';}
  append(node) {this.children.push(node);}
  set textContent(text) {this.ownText = text;}
  get textContent() {return this.ownText + this.children.map(node => node.textContent).join('\n');}
  set innerHTML(_) {throw Error('unsafe HTML sink');}
}
const forbidden = () => {throw Error('source status rendering dispatched work');};
function assertText(text, job, language) {
  for (const label of labels[language]) assert(text.includes(label), label);
  assert(text.includes(job.status));
  assert(text.includes(job.followup ? job.followup.status : 'Unknown'));
  if (job.followup && job.followup.failure) {
    assert(text.includes(job.followup.failure.code));
    assert(text.includes(job.followup.failure.error_code || job.followup.failure.error_type));
    assert(text.includes(job.failure.code));
  }
  assert(!text.includes('reading_complete · false'), 'historical flag is not current reading status');
}
let renders = 0;
for (const language of languages) for (const job of jobs) {
  for (let refresh = 0; refresh < 2; refresh++) {
    const area = new Element('div'), before = JSON.stringify(job);
    const sandbox = {state: {language, stage1: {source_execution: {jobs: {one: job}, grants: {}}}},
      document: {createElement: tag => new Element(tag)}, $: () => area,
      guarded: forbidden, executeSourceGrant: forbidden, fetch: forbidden, loadProject: forbidden};
    vm.runInNewContext(functions + '\nrenderSources();', sandbox);
    assertText(area.textContent, job, language);
    assert.equal(JSON.stringify(job), before); renders++;
  }
}
assert.equal(renders, 36); console.log('PASS 36 historical source status renders; actual serializer, 3 languages, no dispatch/HTML');

async function browser() {
  const output = path.resolve(process.argv[3]); fs.mkdirSync(output, {recursive: false});
  const {chromium} = require(process.env.PLAYWRIGHT_PATH);
  const server = require('node:http').createServer((request, response) => {
    if (request.url === '/projects.css') {
      response.setHeader('Content-Type', 'text/css'); response.end(fs.readFileSync(path.join(web, 'projects.css')));
    } else {
      response.setHeader('Content-Type', 'text/html; charset=utf-8');
      response.end('<!doctype html><html><meta charset="utf-8"><link rel="stylesheet" href="/projects.css"><title>Source status seam fixture</title><main><h1>Saved source job observations</h1><p>Authored observations · actual serializer and UI functions · no native/model execution</p><div id="query-observations"></div></main></html>');
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let instance;
  const errors = [], diagnostics = [];
  try {
    instance = await chromium.launch({executablePath: process.env.CHROME_PATH, headless: true});
    const page = await instance.newPage({viewport: {width: 1120, height: 760}});
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {if (message.type() === 'error') diagnostics.push(message.text());});
    await page.goto('http://127.0.0.1:' + server.address().port);
    let checks = 0;
    for (const language of languages) for (const job of jobs) {
      for (let refresh = 0; refresh < 2; refresh++) {
        await page.evaluate(({functions, language, job}) => {
          const area = document.getElementById('query-observations'); area.replaceChildren();
          window.state = {language, stage1: {source_execution: {jobs: {one: job}, grants: {}}}};
          window.$ = () => area;
          const refuse = () => {throw Error('unexpected execution');};
          window.guarded = window.executeSourceGrant = window.fetch = window.loadProject = refuse;
          (0, eval)(functions + '\nrenderSources();');
        }, {functions, language, job});
        assertText(await page.locator('#query-observations').innerText(), job, language); checks++;
      }
    }
    assert.deepEqual(errors, []); assert.deepEqual(diagnostics, []);
    await page.screenshot({path: path.join(output, 'source-status.png'), fullPage: true});
    const receipt = {checks, browser: await instance.version(), page_errors: errors, console_errors: diagnostics,
      source_sha256: crypto.createHash('sha256').update(source).digest('hex'), scope: 'actual serializer/render functions only; authored observations and temporary HTTP page',
      native_model_search_acquisition_calls: 0, full_project_page: false};
    fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2) + '\n', {flag: 'wx'});
    console.log(JSON.stringify(receipt));
  } finally {
    if (instance) await instance.close();
    await new Promise(resolve => server.close(resolve));
  }
}
if (process.argv[2] === '--browser') browser().catch(error => {console.error(error); process.exitCode = 1;});

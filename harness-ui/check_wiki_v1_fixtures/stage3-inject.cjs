// Visual check only: serves a fixed Stage 3 plan (same shape as test_wiki_stage3.cjs) to the browser.
// The Host has no saved plan at zero quota; nothing here reaches the Host's write paths.
const fs = require('node:fs');
const path = require('node:path');
const plan = JSON.parse(fs.readFileSync(path.join(__dirname, 'stage3-plan.json'), 'utf8'));
const review = JSON.parse(fs.readFileSync(path.join(__dirname, 'stage3-review.json'), 'utf8'));
module.exports = async page => {
 const ref = process.env.WIKI_V1_PROJECT;
 await page.route('**/project-bootstrap.js', async route => {
  try {
   const r = await route.fetch(), body = await r.text();
   await route.fulfill({response:r, body:body + `;window.RESEARCH_PROJECTS.stage3_planning_projects=[${JSON.stringify(ref)}];`});
  } catch (_) { await route.continue().catch(() => {}); } // request cancelled by a navigation
 });
 await page.route(`**/api/projects/${ref}/connections`, route => route.request().method() === 'GET'
  ? route.fulfill({status:404, contentType:'application/json', body:'{"error":"not-found"}'}) : route.continue());
 await page.route(`**/api/projects/${ref}/stage3/planning`, async route => {
  let overview;
  try { overview = await (await route.fetch({url:route.request().url().replace('/stage3/planning', '/overview')})).json(); }
  catch (_) { await route.continue().catch(() => {}); return; }
  const p = overview.project;
  const view = {project_ref:p.project_ref, input_version:p.input_version, revision:p.revision, brief_sha256:p.brief_sha256, plan, review,
   job:{plan_manifest_sha256:'b'.repeat(64), request_sha256:'c'.repeat(64)},
   direction_context:{questions:[{question_ref:'q1', text:'人口老龄化通过哪些渠道改变家庭消费结构？'}]}};
  await route.fulfill({status:200, contentType:'application/json', body:JSON.stringify(view)});
 });
};

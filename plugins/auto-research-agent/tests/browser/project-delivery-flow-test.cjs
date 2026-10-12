/* Installed browser over actual HTTP/SQLite/Core; authored sources, no model. */
"use strict";
const fs = require("node:fs"), path = require("node:path"), cp = require("node:child_process"), crypto = require("node:crypto"), assert = require("node:assert/strict");
const [python, output] = process.argv.slice(2);
if (!python || !path.isAbsolute(output)) throw Error("python and fresh absolute private output required");
fs.mkdirSync(output);
const stop = path.join(output, "stop"), fixture = path.resolve(__dirname, "../project_delivery_browser_fixture.py");
const child = cp.spawn(python, ["-B", "-X", "utf8", "-u", fixture, "--stop-file", stop], {stdio:["ignore","pipe","pipe"]});
let lines = "", stderr = "", ready, final, browser, observedPage, exitCode, failure, resolveReady, rejectReady;
const checks = [], posts = [], gets = [], pageErrors = [], diagnostics = [], downloads = [];
const started = new Promise((ok,no) => {resolveReady=ok;rejectReady=no;});
const exited = new Promise(resolve => {
  child.on("exit", (code,signal) => {exitCode=code; if (!ready) rejectReady(Error("fixture exited before ready: " + code)); resolve({code,signal});});
  child.on("error", error => {rejectReady(error);resolve({error:error.message});});
});
child.stderr.on("data", bytes => {stderr += bytes;});
child.stdout.on("data", bytes => {
  lines += bytes; const rows=lines.split("\n"); lines=rows.pop();
  for (const line of rows) {
    try {const row=JSON.parse(line); if (row.kind === "Stage1DeliveryBrowserFixture") {ready=row;resolveReady(row);} else if (row.kind === "Stage1DeliveryBrowserFixtureStopped") final=row;}
    catch {diagnostics.push("non-JSON fixture output");}
  }
});
const within = (value,ms,message) => {let timer; return Promise.race([value,new Promise((_,no)=>{timer=setTimeout(()=>no(Error(message)),ms);})]).finally(()=>clearTimeout(timer));};
const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const record = name => checks.push({name,passed:true});
(async () => {
  try {
    await within(started,60000,"fixture ready timeout");
    assert.equal(ready.baseline_readings,0); assert.equal(ready.works.length,2);
    assert.deepEqual([ready.native_calls,ready.model_calls,ready.search_calls],[0,0,0]);
    const {chromium}=require(process.env.PLAYWRIGHT_MODULE || "playwright");
    browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH});
    const context=await browser.newContext({viewport:{width:1500,height:1000}});
    const origin=new URL(ready.url).origin;
    await context.route("**/*",route=>new URL(route.request().url()).origin===origin ? route.continue() : route.abort());
    context.on("page",page=>{
      page.setDefaultTimeout(30000);
      page.on("pageerror",error=>pageErrors.push(error.message));
      page.on("console",message=>{if(message.type()==="error") diagnostics.push(message.text());});
      page.on("request",request=>{
        const route=new URL(request.url()).pathname;
        if(request.method()==="POST") posts.push(route);
        else if(request.method()==="GET") gets.push(route);
      });
    });
    const page=await context.newPage(); observedPage=page; await page.goto(ready.url);
    const initialOverview=page.waitForResponse(response=>response.url().endsWith("/overview") && response.status()===200);
    await page.locator("#project-list button").click();
    const initial=await (await initialOverview).json();
    await page.locator("#stage1-actions > summary").click();
    await page.locator("#stage1-library").waitFor({state:"visible"});
    await page.waitForFunction(()=>document.querySelectorAll("#screening-list button").length===2);
    assert.equal(await page.locator("#screening-list button").count(),2);
    assert.equal(posts.length,0);
    assert.equal(initial.stage1.reading_registration.status,"missing");
    assert.equal(initial.stage1.reading_registration.missing_works.length,2);
    assert.equal(initial.stage1.progress.next_action.reason,"reading-registration-required");
    assert.equal(await page.locator("#ledger-prepare").isDisabled(),true);
    record("actual two saved-source works are visible without model/search/native calls");
    const snapshots=[];
    for (const [number,work] of ready.works.entries()) {
      await page.locator("#screening-list button").nth(number).click();
      await page.getByRole("button",{name:"Review evidence in saved source text",exact:true}).click();
      await page.locator("#saved-claim-source-text").waitFor({state:"visible"});
      const sourceReply=page.waitForResponse(response=>response.url().includes("/stage1/source-reading/") && response.status()===200);
      await page.getByRole("button",{name:"Review and register reading notes",exact:true}).click();
      const source=await (await sourceReply).json();
      assert.equal(source.work_ref,work.work_id); assert.equal(source.stage1_complete,false);
      snapshots.push({work_id:source.work_ref,source_snapshot_sha256:source.source_snapshot_sha256,source_ids:source.sources.map(row=>row.source_id)});
      const form=page.locator("#reading-notes-form"); await form.waitFor({state:"attached"});
      await form.locator("..").locator("summary").first().click();
      assert.equal(await form.locator("textarea[data-reading-note]").count(),13);
      const original=await form.locator("textarea[data-reading-note]").evaluateAll(rows=>rows.map(row=>row.value));
      assert(original.some(value=>value.startsWith("Unknown")));
      await form.locator('textarea[data-reading-note="classification.topic_cluster"]').fill("Authored UI delivery topic " + (number+1));
      await form.locator('textarea[data-reading-note="findings.limitations"]').fill("Authored engineering fixture; research evidence and acceptance remain Unknown.");
      await form.locator(":scope > label.check input").check();
      const saved=page.waitForResponse(response=>response.url().endsWith("/stage1/reading-review") && response.status()===200);
      const refreshed=page.waitForResponse(response=>response.url().endsWith("/overview") && response.status()===200);
      await form.locator('button[type="submit"]').click();
      const result=await (await saved).json(); assert.equal(result.status,"saved"); assert.notEqual(result.stage1_complete,true);
      const overview=await (await refreshed).json();
      const registration=overview.stage1.reading_registration;
      assert.equal(registration.status,number===0 ? "missing" : "ready");
      assert.equal(registration.missing_works.length,1-number);
      assert.equal(registration.grants_execution,false);
      for(const key of ["project_ref","revision","input_version","brief_sha256"]) assert.equal(registration[key],overview.project[key]);
      assert.equal(registration.ledger_state_sha256,overview.stage1.ledger.state_sha256);
      await page.waitForFunction(revision=>new RegExp(" · r"+revision+"(?:\\D|$)").test(document.getElementById("stage1-progress").textContent) && document.getElementById("reading-card").hidden,overview.project.revision);
    }
    assert.equal(posts.filter(route=>route.endsWith("/stage1/reading-review")).length,2);
    record("two explicit source-bound reading registrations retain Unknown with no generated model draft");
    async function step(id,route) {
      const button=page.locator("#"+id); await button.waitFor({state:"visible"});
      await page.waitForFunction(name=>!document.getElementById(name).disabled,id,{timeout:15000});
      assert.equal(await button.isEnabled(),true,id+" should be offered by saved state");
      const response=page.waitForResponse(reply=>reply.url().endsWith(route));
      const refreshed=page.waitForResponse(reply=>reply.url().endsWith("/overview") && reply.status()===200);
      await button.click(); const observed=await response,body=await observed.json();
      assert.equal(observed.status(),200,JSON.stringify(body));
      const overview=await (await refreshed).json();
      await page.waitForFunction(revision=>new RegExp(" · r"+revision+"(?:\\D|$)").test(document.getElementById("stage1-progress").textContent),overview.project.revision);
      return body;
    }
    const checkpoint=await step("ledger-checkpoint","/stage1/checkpoint");
    assert(checkpoint.checkpoint_event_id);
    const prepared=await step("ledger-prepare","/stage1/prepare-delivery");
    assert.equal(prepared.status,"saved"); assert.equal(prepared.delivery_offer.eligible_for_stage2,false);
    const graphResponse=page.waitForResponse(response=>response.url().includes("/stage1/atlas/") && !response.url().includes("/files/") && response.status()===200);
    const delivered=await step("ledger-deliver","/stage1/deliver");
    assert.equal(delivered.status,"saved"); assert.equal(delivered.stage1_complete,false);
    const manifest=delivered.manifest_sha256;
    assert(/^[a-f0-9]{64}$/.test(manifest));
    await page.locator("#project-atlas-frame").waitFor({state:"visible"});
    assert((await page.locator("#delivery-artifact").innerText()).includes(manifest));
    assert.equal(await page.locator("#activate-stage2").isEnabled(),false);
    record("actual UI checkpoint → records preparation → canonical delivery retains partial/ineligible gate and exact manifest");
    const graph=await (await page.locator("#project-atlas-frame").elementHandle()).contentFrame(), atlas=await (await graphResponse).json();
    assert.equal(context.pages().length,1);
    assert.equal(atlas.project_ref,ready.project_ref); assert.equal(atlas.manifest_sha256,manifest);
    await graph.getByRole("heading",{name:"Literature knowledge network",exact:true}).first().waitFor({state:"visible"});
    await graph.getByRole("button",{name:"Return to project",exact:true}).waitFor({state:"visible"});
    assert.equal(await graph.locator("#project-intake-card").count(),0);
    assert.equal(await graph.locator("#project-operations-frame").count(),0);
    assert((await graph.locator("#project-atlas-status").innerText()).includes(ready.project_ref));
    const payload=await graph.evaluate(()=>window.WORKSPACE_VIEW);
    assert.equal(payload.index_sha256,atlas.index_sha256); assert.equal(payload.index.papers.length,2);
    assert(payload.index.papers.every(work=>ready.works.some(row=>row.work_id===work.work_id)));
    assert(JSON.stringify(payload.index).includes("Unknown"));
    await graph.locator("#atlas-content").scrollIntoViewIfNeeded();
    await graph.locator("#atlas-content").screenshot({path:path.join(output,"saved-delivery-graph.png")});
    record("same v6 renderer opens this project's newly delivered two-work package, matching manifest and index identities");
    const bibliography=atlas.files.find(row=>row.path==="references.bib"); assert(bibliography);
    const read=page.waitForResponse(response=>response.url().endsWith("/files/"+bibliography.file_ref+"/"+bibliography.sha256));
    const download=page.waitForEvent("download");
    await graph.getByRole("link",{name:"Complete bibliography",exact:true}).click();
    const fileResponse=await read, fileResult=await fileResponse.json(); assert.equal(fileResponse.status(),200);
    const actualDownload=await download, destination=path.join(output,"references.bib"); await actualDownload.saveAs(destination);
    assert.equal(sha(fs.readFileSync(destination)),bibliography.sha256);
    assert.equal(fileResult.file.sha256,bibliography.sha256);
    downloads.push({path:"references.bib",sha256:bibliography.sha256,actual_click:true});
    record("actual browser bibliography click downloads the exact bound UTF8 file through the read-only parent channel");
    for(const language of ["zh-Hans","zh-Hant","en"]) {
      await page.locator("#language").selectOption(language);
      await graph.waitForFunction(value=>document.getElementById("atlas-language").value===value,language);
      assert.equal(await graph.evaluate(()=>window.WORKSPACE_VIEW.index_sha256),atlas.index_sha256);
    }
    const postsBefore=posts.length;
    const refreshed=page.waitForResponse(response=>response.url().includes("/stage1/atlas/") && response.status()===200);
    await graph.evaluate(()=>location.reload()); assert.equal((await (await refreshed).json()).manifest_sha256,manifest);
    await graph.getByRole("button",{name:"Return to project",exact:true}).waitFor({state:"visible"});
    assert.equal(posts.length,postsBefore);
    record("trilingual rendering and child reload re-read the same saved binding with zero new mutation");
    await graph.getByRole("button",{name:"Return to project",exact:true}).click();
    assert.equal(context.pages().length,1);
    await page.locator("#refresh").click();
    await page.locator("#project-atlas-frame").waitFor({state:"visible"});
    assert.equal(posts.length,postsBefore);
    assert((await page.locator("#delivery-artifact").innerText()).includes(manifest));
    assert.notEqual((await page.locator("#stage1-state").textContent()).trim(),"complete");
    await page.screenshot({path:path.join(output,"delivery-operation-history.png"),fullPage:false});
    record("return and project history refresh preserve one preparation/delivery and do not accept research");
    for (const tail of ["checkpoint","prepare-delivery","deliver"]) assert.equal(posts.filter(route=>route.endsWith("/stage1/"+tail)).length,1);
    const inputArea=page.locator("#project-atlas-entry details").first();
    await inputArea.locator(":scope > summary").click();
    const inputResponse=page.waitForResponse(response=>response.url().includes("/stage1/atlas/") && response.status()===200);
    await inputArea.getByRole("button",{name:"Review Stage 1 → Stage 2 input",exact:true}).click();
    const input=(await (await inputResponse).json()).stage2_input;
    assert.equal(input.manifest_sha256,manifest); assert.equal(input.index_sha256,atlas.index_sha256);
    assert.equal(input.execution_authorized,false); assert.equal(input.works.length,2);
    const inputForm=inputArea.locator("form"); await inputForm.waitFor({state:"visible"});
    await inputForm.locator("select").selectOption("hold");
    await inputForm.locator("textarea").fill("Authored UI handoff review only; research evidence remains partial and Stage2 execution is deferred.");
    const savedInput=page.waitForResponse(response=>response.url().endsWith("/stage1/review-stage2-input"));
    const inputRefresh=page.waitForResponse(response=>response.url().endsWith("/overview") && response.status()===200);
    await inputForm.getByRole("button",{name:"Save input decision",exact:true}).click();
    const reviewed=await savedInput; assert.equal(reviewed.status(),200,JSON.stringify(await reviewed.json()));
    const afterInput=await (await inputRefresh).json();
    assert.equal(afterInput.stage1.delivery.canonical_package.manifest_sha256,manifest);
    assert.equal(await page.locator("#activate-stage2").isEnabled(),false);
    assert.equal(posts.filter(route=>route.endsWith("/stage1/review-stage2-input")).length,1);
    record("explicit source-bound Stage2 input hold is saved without activating research or granting model authority");
    assert.equal(posts.length,6);
    assert.deepEqual(pageErrors,[]);
    ready.checked_bindings={manifest_sha256:manifest,index_sha256:atlas.index_sha256,sources:snapshots};
  } catch(error) {
    failure=error.stack || String(error);
    if(observedPage && !observedPage.isClosed()) {
      fs.writeFileSync(path.join(output,"failure-ui.txt"),await observedPage.locator("#project-content").innerText().catch(()=>"UI text unavailable"),{flag:"wx"});
      await observedPage.screenshot({path:path.join(output,"failure-ui.png"),fullPage:false}).catch(()=>{});
    }
  }
  finally {
    if(browser) await browser.close().catch(error=>{failure ||= error.message;});
    fs.writeFileSync(stop,"stop",{flag:"wx"});
    try {await within(exited,15000,"fixture cleanup timeout");} catch(error) {failure ||= error.message; child.kill(); await within(exited,5000,"termination unobserved").catch(()=>{});}
    if(exitCode!==0 || !final || stderr) failure ||= "fixture completion/stderr failure";
    if(!failure && (final.readings!==2 || final.stage1_complete!==false || final.native_calls!==0 || final.model_calls!==0 || final.search_calls!==0)) failure="unexpected fixture completion state";
    const receipt={kind:"Stage1DeliveryBrowserFlow.v1",passed:!failure,checks,failure,pageErrors,diagnostics,posts,gets,downloads,
      fixture:ready,completion:final,fixture_exit:exitCode,stderr,real_research_execution:false,
      driver_sha256:sha(fs.readFileSync(__filename))};
    fs.writeFileSync(path.join(output,"receipt.json"),JSON.stringify(receipt,null,2)+"\n",{flag:"wx"});
    process.stdout.write(JSON.stringify({passed:receipt.passed,checks:checks.length,failure})+"\n");
    process.exitCode=receipt.passed ? 0 : 1;
  }
})().catch(error=>{process.stderr.write(error.stack+"\n");process.exitCode=1;});

/* Real saved-source HTTP detail; authored UI overlays never grant execution. */
"use strict";
const fs=require("node:fs"),path=require("node:path"),cp=require("node:child_process"),crypto=require("node:crypto"),assert=require("node:assert/strict");
const [python,output]=process.argv.slice(2);
if(!python || !path.isAbsolute(output)) throw Error("python and fresh absolute private output required");
fs.mkdirSync(output);
const stop=path.join(output,"stop"),fixture=path.resolve(__dirname,"../project_delivery_browser_fixture.py");
const asset=path.resolve(__dirname,"../../cli/research_workspace_native/web/projects-library.js");
const sha=bytes=>crypto.createHash("sha256").update(bytes).digest("hex"),sourceSha=sha(fs.readFileSync(asset));
const child=cp.spawn(python,["-B","-X","utf8","-u",fixture,"--stop-file",stop],{stdio:["ignore","pipe","pipe"]});
let pending="",stderr="",ready,final,browser,page,exitCode,failure,resolveReady,rejectReady,mode="actual-available";
const checks=[],posts=[],pageErrors=[],diagnostics=[],details=[];
const started=new Promise((ok,no)=>{resolveReady=ok;rejectReady=no;});
const exited=new Promise(resolve=>{
  child.on("exit",(code,signal)=>{exitCode=code;if(!ready)rejectReady(Error("fixture stopped before ready"));resolve({code,signal});});
  child.on("error",error=>{rejectReady(error);resolve({error:error.message});});
});
child.stderr.on("data",bytes=>{stderr+=bytes;});
child.stdout.on("data",bytes=>{
  pending+=bytes;const lines=pending.split("\n");pending=lines.pop();
  for(const line of lines)try{
    const row=JSON.parse(line);
    if(row.kind==="Stage1DeliveryBrowserFixture"){ready=row;resolveReady(row);}
    else if(row.kind==="Stage1DeliveryBrowserFixtureStopped")final=row;
  }catch{diagnostics.push("non-JSON fixture output");}
});
function within(value,ms,message){let timer;return Promise.race([value,new Promise((_,no)=>{timer=setTimeout(()=>no(Error(message)),ms);})]).finally(()=>clearTimeout(timer));}
function overlay(value){
  const row=value.row,current=row.source_attempts.filter(item=>item.started.version_id===row.selected_version_id);
  assert(current.some(item=>item.finished?.outcome==="available"),"actual fixture source must be available in selected version");
  const item=structuredClone(current[0]);
  if(mode!=="actual-available")value.reading_offer=mode==="model-blocked" ? {available:false,blocked_reason:"reading-model-or-records-unconnected"} : null;
  if(mode==="old-version-only"){
    item.started.version_id="authored-old-version";row.source_attempts=[item];row.source_status="not-acquired";
  }else if(mode==="failed"){
    item.finished.outcome="network_error";row.source_attempts=[item];row.source_status="network_error";
  }else if(mode==="missing"){
    row.source_attempts=[];row.source_imports=[];row.source_status="not-acquired";
  }else if(mode==="pending"){
    item.finished=null;row.source_attempts=[item];row.source_status="pending";
  }else if(mode==="unknown"){
    item.finished.outcome="Unknown";row.source_attempts=[item];row.source_status="Unknown";
  }else if(mode==="imported-readable"){
    row.source_attempts=[];
    row.source_imports=[{started:{...item.started,kind:"SourceImportStarted"},artifacts:[item.finished.raw_ref]}];
    row.source_status="saved-import-bytes-recorded";
    value.reading_offer={available:true,snapshot_sha256:"a".repeat(64),execution_authorized:false};
  }
  return value;
}
(async()=>{
  try{
    await within(started,60000,"fixture ready timeout");
    assert.equal(ready.baseline_readings,0);assert.equal(ready.works.length,2);
    const {chromium}=require(process.env.PLAYWRIGHT_MODULE||"playwright");
    browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH});
    const context=await browser.newContext({viewport:{width:1450,height:1000}}),origin=new URL(ready.url).origin;
    await context.route("**/*",async route=>{
      const request=route.request(),url=new URL(request.url());
      if(url.origin!==origin)return route.abort();
      if(request.method()==="POST"){posts.push(url.pathname);return route.abort();}
      if(url.pathname.endsWith("/overview")){
        const response=await route.fetch(),value=await response.json();
        // Presentation-only source connectivity; the actual fixture has no
        // source dispatcher/provider, and every POST is denied by this driver.
        value.stage1.source_execution={runner_connected:true,jobs:[]};
        return route.fulfill({response,json:value});
      }
      if(url.pathname.includes("/screening-detail/")){
        const response=await route.fetch(),actual=await response.json();
        if(mode==="actual-available")details.push(actual);
        return route.fulfill({response,json:overlay(structuredClone(actual))});
      }
      return route.continue();
    });
    page=await context.newPage();page.setDefaultTimeout(15000);
    page.on("pageerror",error=>pageErrors.push(error.message));
    page.on("console",message=>{if(message.type()==="error")diagnostics.push(message.text());});
    const served=page.waitForResponse(response=>new URL(response.url()).pathname==="/projects-library.js");
    await page.goto(ready.url);assert.equal(sha(await(await served).body()),sourceSha);
    await page.locator("#project-list button").click();
    for(const [scenario,wanted] of [["actual-available",false],["model-blocked",false],["old-version-only",true],["failed",true],["missing",true],["pending",false],["unknown",false],["imported-readable",false]]){
      mode=scenario;
      const refreshed=page.waitForResponse(response=>response.url().endsWith("/overview")&&response.status()===200);
      await page.locator("#refresh").click();await refreshed;
      await page.waitForFunction(()=>!document.getElementById("native-refresh").disabled&&document.querySelectorAll("#screening-list button").length===2);
      const detail=page.waitForResponse(response=>response.url().includes("/screening-detail/")&&response.status()===200);
      await page.locator("#screening-list button").first().click();await detail;
      await page.locator("#screening-detail h3").waitFor({state:"visible"});
      assert.equal(await page.getByRole("button",{name:"Acquire this public source",exact:true}).count(),wanted?1:0,scenario+" acquisition condition");
      assert.equal(await page.getByRole("button",{name:"Review evidence in saved source text",exact:true}).count(),1);
      if(scenario==="model-blocked")assert((await page.locator("#screening-detail").innerText()).includes("reading-model-or-records-unconnected"));
      if(scenario==="unknown")assert((await page.locator("#screening-detail").innerText()).includes("Unknown"));
      if(scenario==="imported-readable")assert.equal(await page.getByRole("button",{name:"Ask Codex to read this saved paper",exact:true}).count(),1);
      checks.push({scenario,passed:true,authored_status_overlay:scenario!=="actual-available"});
    }
    assert.equal(posts.length,0);assert.deepEqual(pageErrors,[]);
    assert.equal(sha(fs.readFileSync(asset)),sourceSha);
  }catch(error){failure=error.stack||String(error);if(page)diagnostics.push(await page.locator("#screening-detail").innerText().catch(()=>"detail unavailable"));}
  finally{
    if(browser)await browser.close().catch(error=>{failure||=error.message;});
    fs.writeFileSync(stop,"stop",{flag:"wx"});
    try{await within(exited,15000,"fixture cleanup timeout");}catch(error){failure||=error.message;child.kill();await within(exited,5000,"termination unobserved").catch(()=>{});}
    if(exitCode!==0||!final||stderr||final.failure)failure||="fixture completion/stderr failure";
    if(!failure&&(final.readings!==0||final.events!==ready.baseline_events||final.model_calls!==0||final.search_calls!==0||final.native_calls!==0))failure="fixture state changed";
    const receipt={kind:"ProjectLibrarySourceCondition.v1",passed:!failure,failure,checks,posts,pageErrors,diagnostics,
      library_sha256:sourceSha,actual_saved_details:details,fixture:ready,completion:final,fixture_exit:exitCode,stderr,
      scope:"library-rendering-only; source runner descriptor and seven status scenarios are authored UI overlays; no backend reacquisition or protected import proof",
      driver_sha256:sha(fs.readFileSync(__filename))};
    fs.writeFileSync(path.join(output,"receipt.json"),JSON.stringify(receipt,null,2)+"\n",{flag:"wx"});
    process.stdout.write(JSON.stringify({passed:receipt.passed,checks:checks.length,failure})+"\n");process.exitCode=receipt.passed?0:1;
  }
})().catch(error=>{process.stderr.write(error.stack+"\n");process.exitCode=1;});

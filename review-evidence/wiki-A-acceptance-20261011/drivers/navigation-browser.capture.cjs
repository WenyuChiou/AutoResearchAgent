"use strict";
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const repo='<LOCAL_WORKSPACE>/worktrees/ca-wiki', out=process.argv[2];
fs.mkdirSync(out,{recursive:false});
const python='<LOCAL_WORKSPACE>/_private/workspace-return/atlas-current-sdk-env-20261010-v1/Scripts/python.exe';
const driver=path.join('<LOCAL_WORKSPACE>/_private/workspace-return','wiki-A-compatible-host-20261011.py');
const command=[python,'-I','-B','-X','utf8',driver,repo,out];
const stdout=fs.openSync(path.join(out,'host-stdout.log'),'wx'),stderr=fs.openSync(path.join(out,'host-stderr.log'),'wx');
const child=cp.spawn(command[0],command.slice(1),{cwd:repo,stdio:['ignore',stdout,stderr],windowsHide:true,env:{...process.env,TEMP:'<LOCAL_WORKSPACE>/_temp/fq10',TMP:'<LOCAL_WORKSPACE>/_temp/fq10',TMPDIR:'<LOCAL_WORKSPACE>/_temp/fq10'}});
fs.closeSync(stdout);fs.closeSync(stderr);
let ended=false,exitCode=null;const exited=new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',code=>{ended=true;exitCode=code;resolve(code);});});
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms)),hash=raw=>crypto.createHash('sha256').update(raw).digest('hex');
const captures=[],checks=[],errors=[],external=[];let browser,ready,chromeVersion;
async function main(){
try{
 const deadline=Date.now()+30000;while(!fs.existsSync(path.join(out,'ready.json'))){assert(!ended,'host exited before ready');assert(Date.now()<deadline,'host ready timeout');await pause(50);}
 ready=JSON.parse(fs.readFileSync(path.join(out,'ready.json')));
 browser=await chromium.launch({executablePath:'<LOCAL_CHROME_EXECUTABLE>',headless:true,args:['--enable-unsafe-swiftshader']});
 chromeVersion=browser.version();
 const context=await browser.newContext({reducedMotion:'reduce'});await context.route('**/*',route=>{if(new URL(route.request().url()).origin===ready.origin)return route.continue();external.push(route.request().url());return route.abort();});
 const page=await context.newPage();page.on('pageerror',e=>errors.push(String(e)));
 await page.goto(ready.origin+'/');await page.locator('a[href="/views/stage1-current/atlas.html"]').click();await page.waitForSelector('#atlas-network');
 await page.locator('#atlas-original').click();assert.equal(new URL(page.url()).pathname,'/views/stage1-current/index.html');
 await page.locator('a[href="atlas.html"]').first().click();assert.equal(new URL(page.url()).pathname,'/views/stage1-current/atlas.html');checks.push({name:'actual AtlasHost chooser → current generated repository Stage1 Atlas → saved Wiki → Atlas',status:'PASS'});
 await page.goto(ready.origin+'/views/stage1/atlas.html');await page.locator('#atlas-original').click();assert.equal(new URL(page.url()).pathname,'/views/stage1/index.html');await page.goBack();assert.equal(new URL(page.url()).pathname,'/views/stage1/atlas.html');checks.push({name:'historical r3 overlay → retained saved Wiki → browser Back; old index has no Atlas backlink',status:'PASS',limitation:'historical artifact is not rebuilt or modified'});
 await page.goto(ready.origin+'/views/stage1-current/atlas.html');
 for(const width of [1440,768,390]){await page.setViewportSize({width,height:1000});for(const lang of ['en','zh-Hans','zh-Hant']){
  await page.locator('#atlas-language').selectOption(lang);await page.locator('#atlas-network').scrollIntoViewIfNeeded();await page.waitForFunction(()=>document.querySelector('.atlas-spatial-host')?.atlasDiagnostics().nodes>0);
  assert.equal(await page.locator('html').getAttribute('lang'),lang);const dimensions=await page.evaluate(()=>({client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth}));assert(dimensions.scroll<=dimensions.client+1);
  const name=`stage1-${lang}-${width}.png`,file=path.join(out,name);await page.screenshot({path:file});captures.push({file:name,language:lang,width,height:1000,sha256:hash(fs.readFileSync(file)),scope:'current source-generated public synthetic repository Stage1 fixture; Chrome viewport emulation'});checks.push({name:`stage1 ${lang}/${width} capture/no overflow`,status:'PASS'});
 }}
 await page.goto(ready.origin+'/views/stage2/atlas.html');await page.locator('#atlas-stages button').nth(1).click();for(const lang of ['en','zh-Hans','zh-Hant']){await page.setViewportSize({width:1440,height:1000});await page.locator('#atlas-language').selectOption(lang);await page.waitForSelector('#atlas-content h1');assert.equal(await page.locator('html').getAttribute('data-atlas-stage'),'2');const name=`stage2-${lang}-1440.png`,file=path.join(out,name);await page.screenshot({path:file});captures.push({file:name,language:lang,width:1440,height:1000,sha256:hash(fs.readFileSync(file)),scope:'original saved synthetic repository Stage2 fixture selected comparison stage; not generated research'});}
 await page.locator('#atlas-original').click();assert.equal(new URL(page.url()).pathname,'/views/stage2/index.html');await page.locator('a[href="atlas.html"]').first().click();assert.equal(new URL(page.url()).pathname,'/views/stage2/atlas.html');checks.push({name:'actual saved Stage2 Wiki → Atlas → Wiki links',status:'PASS'});
 assert.equal(errors.length,0);assert.equal(external.length,0);await context.close();
} finally {if(browser)await browser.close();fs.writeFileSync(path.join(out,'stop'),'',{flag:'wx'});const timer=new Promise(resolve=>setTimeout(()=>resolve('timeout'),5000));const code=await Promise.race([exited,timer]);if(code==='timeout'){child.kill();throw new Error('owned host cleanup timeout');}assert.equal(code,0,'host exit');}
const cleanup=JSON.parse(fs.readFileSync(path.join(out,'host-cleanup.json')));assert(cleanup.source_inventory_equal);assert(!cleanup.shutdown_thread_alive);
const receipt={kind:'WikiACompatibilityBrowser.v1',created_at:new Date().toISOString(),head:ready.head,chrome:chromeVersion,command,captures,checks,page_errors:errors,external_requests:external,host_exit:exitCode,cleanup,actual_native_model_source_search_scoring:0,scope:'Targeted A navigation and missing language screenshots only; prior full presentation checks retain original binding'};
fs.writeFileSync(path.join(out,'receipt.json'),JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify({head:ready.head,checks:checks.length,screenshots:captures.length,host_exit:exitCode,passed:true}));
}
main().catch(e=>{fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({error:String(e),checks,captures,page_errors:errors,external_requests:external,host_exit:exitCode},null,2)+'\n',{flag:'wx'});console.error(e);process.exitCode=1;});

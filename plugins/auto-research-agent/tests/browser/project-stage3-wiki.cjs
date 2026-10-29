/* Offline DOM integration: real page script, synthetic saved views, no provider. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const web = path.resolve(__dirname, "../../cli/research_workspace_native/web");
const script = fs.readFileSync(path.join(web, "project-stage3-planning.js"), "utf8");
const ids = [...fs.readFileSync(path.join(web, "project-stage3-planning.html"), "utf8").matchAll(/\bid="([^"]+)"/g)].map(m => m[1]);

function fixture() {
  const questions = ["q-observe", "q-explain"].map((question_ref, i) => ({question_ref,
    candidate_id: "synthetic-choice", candidate_version: 3, question_id: `SQ${i + 1}`,
    text: i ? "Which explanation survives a negative case?" : "What difference can be estimated?",
    priority: i ? "secondary" : "core", gap_ids: ["gap-1"], intended_claim: "Bounded contribution, not an established result"}));
  const plan = {kind: "Stage3ResearchPlan", schema_version: "1.1.0", plan_id: "synthetic-plan", version: 1,
    source_manifest_sha256: "a".repeat(64), selected_candidates: [{candidate_id: "synthetic-choice", candidate_version: 3}], questions,
    question_plans: questions.map((q, i) => ({question_ref: q.question_ref, evidence_needed: `Evidence for SQ${i + 1}`,
      measurement: i ? "Case and interpretation" : "Observed sampling unit", claim_boundary: "No causal identification claimed",
      resource_uses: [{resource_id: `r${i + 1}`, purpose: i ? "Documentary material" : "Observed measurements", fit_rationale: "Bounded source fit", status: "unknown"}],
      design_ids: ["shared-design"], analysis_ids: [`a${i + 1}`], result_ids: [`out${i + 1}`], blockers: ["u-material"], minimum_deliverable: "Answer the original SQ within its limits"})),
    resources: [1, 2].map(i => ({resource_id: `r${i}`, origin: "stage2", availability: "unknown", access_conditions: "Rights remain to be checked",
      fitness: "Appropriate unit subject to verification", scale_basis: "Cases times review effort", minimum: "Small defensible scope", standard: "Expanded scope", uncertainties: ["Access unresolved"]})),
    designs: [{design_id: "shared-design", question_refs: questions.map(q => q.question_ref), family: "observational / qualitative",
      procedure: "Collect eligible units and assess rival explanations", comparisons: {status: "not-applicable", description: "No randomized intervention", reason: "Question asks for bounded description and explanation"},
      credibility_checks: ["Negative cases"], failure_conditions: ["Unit mismatch"], stop_conditions: ["Necessary material unavailable"]}],
    analyses: [1, 2].map(i => ({analysis_id: `a${i}`, question_refs: [questions[i - 1].question_ref], design_ids: ["shared-design"],
      method: i === 1 ? "Descriptive estimate" : "Traceable interpretive comparison", criteria: "Question-specific criterion", uncertainty: "Sampling or interpretive uncertainty", limitations: "No wider population claim"})),
    results: [1, 2].map(i => ({result_id: `out${i}`, question_refs: [questions[i - 1].question_ref], analysis_ids: [`a${i}`], artifact: `Planned output ${i}`,
      status: "not-run", observed_value: null, interpretation: {supports: "Supports the bounded claim", contradicts: "Weakens the proposed explanation", inconclusive: "Cannot distinguish explanations"}})),
    unknowns: [{unknown_id: "u-material", description: "Material fit is unresolved", question_refs: questions.map(q => q.question_ref), resource_ids: ["r1", "r2"], kind: "material-fit", blocking: true,
      resolve_before: "material-design", resolution: "Inspect unit documentation", resolution_evidence_needed: "Versioned unit and rights evidence", owner: null,
      recheck_trigger: "New source version", fallback: "Narrow the claim or return for a scope decision", scope_change_required: false, disposition: "blocked"}],
    condition_dispositions: [{condition_ref: "selection_conditions-0", source_sha256: "b".repeat(64), question_refs: ["q-observe"], interpretation: "Retain the source restriction", disposition: "blocked", response: "Resolve material fit", unknown_ids: ["u-material"]}],
    milestones: [{milestone_id: "m1", description: "Resolve necessary material", depends_on: [], design_ids: ["shared-design"], duration_basis: "Documentation effort", deliverable: "Decision with evidence"}], execution_authorized: false};
  return {planning_configured: true, selection_status: "recorded", default_request: {request_sha256: "c".repeat(64)},
    job: {status: "completed", outcome: "saved", planning_status: "needs-information"}, plan,
    execution_authorized: false, evaluation_calls_authorized: false, formal_execution_enabled: false, external_claim_ready: false, usable_for_formal_pairing: false};
}

class Element {
  constructor(tag = "div") { this.tagName = tag; this.children = []; this._text = ""; this.value = ""; this.dataset = {}; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(n => n.textContent).join("\n"); }
  set innerHTML(_) { throw new Error("Unsafe HTML rendering"); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this._text = ""; this.children = children; }
}
const settle = async () => { for (let i = 0; i < 4; i++) await new Promise(resolve => setImmediate(resolve)); };
async function page(view = fixture(), responder) {
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  elements.language.value = "en";
  const calls = [], created = [];
  const document = {documentElement: {}, getElementById: id => { assert.ok(elements[id], id); return elements[id]; },
    querySelectorAll: () => [], createElement: tag => { created.push(tag); return new Element(tag); }};
  vm.runInNewContext(script, {document, window: {RESEARCH_PROJECTS: {credential: "synthetic", stage3_planning_projects: ["project-a", "project-b"]}},
    location: {hash: "#project-a"}, fetch: async (url, options) => { calls.push({url, options}); return responder ? responder(url, options) : {ok: true, json: async () => structuredClone(view)}; }});
  await settle();
  return {elements, calls, created, text: () => Object.values(elements).map(n => n.textContent).join("\n")};
}

if (require.main === module) {
  test("per-SQ joins show the right material, method, design and three result interpretations", async () => {
    const p = await page(), articles = p.elements.questions.children;
    assert.equal(articles.length, 2);
    for (const [i, article] of articles.entries()) {
      for (const text of [`r${i + 1}`, `Evidence for SQ${i + 1}`, "shared-design", "not-run", "null", "Supports the bounded claim", "Weakens the proposed explanation", "Cannot distinguish explanations"]) assert.ok(article.textContent.includes(text), text);
      assert.ok(article.textContent.includes(i ? "Traceable interpretive comparison" : "Descriptive estimate"));
      assert.ok(!article.textContent.includes(i ? "Descriptive estimate" : "Traceable interpretive comparison"));
    }
    assert.ok(p.text().includes("Shared across these questions; not independent replications"));
  });
  test("blocking unknown, evidence, timing, owner and source condition remain visible", async () => {
    const p = await page();
    for (const article of p.elements.questions.children) for (const text of ["u-material", "material-design", "Versioned unit and rights evidence", "New source version", "return for a scope decision", "null", "false"]) assert.ok(article.textContent.includes(text), text);
    assert.ok(p.elements["plan-conditions"].textContent.includes("selection_conditions-0"));
    assert.ok(p.elements["plan-milestones"].textContent.includes("Documentation effort"));
    assert.ok(p.elements["evidence-state"].textContent.includes("needs-information"));
    assert.ok(p.elements["evidence-state"].textContent.includes("no semantic-review"));
  });
  test("dangling refs and legacy missing fields are explicit without inventing availability", async () => {
    const data = fixture(); data.plan.schema_version = "1.0.0"; delete data.plan.condition_dispositions;
    delete data.plan.unknowns[0].resolve_before; data.plan.question_plans[0].design_ids = ["absent-design"]; data.plan.resources = [];
    const p = await page(data);
    for (const text of ["Unresolved reference: absent-design", "Unresolved reference: r1", "Unknown / not supplied"]) assert.ok(p.text().includes(text), text);
    assert.ok(p.text().includes("Material fit is unresolved"));
  });
  test("all three languages rerender the same saved plan without fetch or mutation", async () => {
    const data = fixture(), before = JSON.stringify(data), p = await page(data), count = p.calls.length;
    for (const [language, label] of [["en", "Research / experiment design"], ["zh-TW", "研究／實驗設計"], ["zh-CN", "研究／实验设计"]]) {
      p.elements.language.value = language; p.elements.language.onchange();
      assert.ok(p.elements.questions.textContent.includes(label)); assert.ok(!p.text().includes("undefined"));
    }
    assert.equal(p.calls.length, count); assert.equal(JSON.stringify(data), before);
    assert.deepEqual(JSON.parse(p.elements["plan-json"].textContent), data.plan);
  });
  test("untrusted text stays inert and original zero, false and null values survive", async () => {
    const data = fixture(), injection = '<script>alert("x")</script><img src=x onerror=alert(1)>';
    data.plan.questions[0].text = injection; data.plan.results[0].observed_value = 0;
    const p = await page(data); assert.ok(p.elements.questions.textContent.includes(injection));
    const recordedValues = [];
    function collect(element) {
      if (element.tagName === "dl") for (let i = 0; i < element.children.length; i += 2)
        if (element.children[i].textContent === "Observed value (null until run)") recordedValues.push(element.children[i + 1].textContent);
      element.children.forEach(collect);
    }
    collect(p.elements.questions); assert.deepEqual(recordedValues, ["0", "null"]);
    assert.ok(!p.created.some(t => ["script", "img", "iframe"].includes(t)));
    assert.ok(p.calls.every(call => call.options.method === "GET"));
    assert.deepEqual(JSON.parse(p.elements["plan-json"].textContent), data.plan);
  });
  test("pending, unconfigured, failed and execution-unknown never fabricate a plan", async () => {
    for (const patch of [{selection_status: "pending"}, {planning_configured: false}, {job: {outcome: "failed"}}, {job: {status: "execution-unknown"}}]) {
      const p = await page({...fixture(), ...patch, plan: null});
      assert.equal(p.elements.plan.hidden, true); assert.equal(p.elements.questions.children.length, 0);
      assert.ok(p.calls.every(call => call.options.method === "GET"));
    }
  });
  test("a stale project read cannot overwrite the newly selected project", async () => {
    const pending = [], p = await page(null, () => new Promise(resolve => pending.push(resolve)));
    p.elements.project.value = "project-b"; p.elements.project.onchange();
    const newer = fixture(); newer.plan.questions[0].text = "New project question";
    pending[1]({ok: true, json: async () => newer}); await settle();
    pending[0]({ok: true, json: async () => fixture()}); await settle();
    assert.ok(p.elements.questions.textContent.includes("New project question")); assert.equal(p.calls.length, 2);
    assert.ok(p.calls.every(call => call.options.method === "GET"));
  });
  test("theoretical and simulation plans retain lawful alternative comparisons", async () => {
    for (const family of ["theoretical", "simulation"]) {
      const data = fixture(); data.plan.designs[0].family = family;
      const p = await page(data); assert.ok(p.elements.questions.textContent.includes(family));
      assert.ok(p.elements.questions.textContent.includes("not-applicable"));
      assert.ok(p.elements.questions.textContent.includes("Question asks for bounded description and explanation"));
    }
  });
  function conditionalView() {
    const data=fixture(), questions=data.plan.questions.map(q=>({...q,question_id:q.question_ref}));
    data.selection_status="pending";data.planning_mode="direction-intent";
    data.job={status:"completed",outcome:"saved"};
    data.default_request={key:"same-direction-key",revision:1,input_version:1,brief_sha256:"b".repeat(64),mode:"direction-intent",direction_intent_sha256:"d".repeat(64),request_sha256:"e".repeat(64)};
    data.direction_context={questions,conditions:["Original direction restriction"],unresolved:["Permission remains unknown"],source_unresolved:["Stage2-only governance restriction"],pending_scope_questions:["Confirm the target universe"],missing_mapping:[],
      preferred_cards:[{candidate_id:"synthetic-choice",candidate_version:3,scientific_questions:questions.map(q=>({question:q,resource_mapping_status:"unknown",resource_uses:[{resource_ref:{purpose:"Evidence for "+q.question_ref,fit_status:"unknown"},resource:{status:"unknown",license:"not-established"}}]}))}]};
    data.plan={kind:"Stage3DirectionPlanningResult",markdown:"Conditional plan, no experiment run.",question_plans:questions.map((q,i)=>({question_ref:q.question_ref,materials:"Unverified documentary source",method:`Method for SQ${i+1}`,design:"Conditional design",validation:"Negative cases",analysis:"Bounded comparison",interpretation:"Support, contradiction or inconclusive",unknowns:["Resolve access before collection"],minimum_deliverable:"Bounded answer"})),execution_authorized:false};
    return data;
  }
  test("a pending direction preference shows its conditional SQ plan and original unknowns", async () => {
    const data=conditionalView(), original=JSON.stringify(data), p=await page(data), count=p.calls.length;
    assert.equal(p.elements.actions.hidden,false);assert.equal(p.elements.plan.hidden,false);
    assert.equal(p.elements.questions.children.length,2);
    for(const [i,a] of p.elements.questions.children.entries()){
      for(const text of [`Method for SQ${i+1}`,"unknown","not-established","Resolve access before collection"])assert.ok(a.textContent.includes(text),text);
    }
    assert.ok(p.elements["plan-conditions"].textContent.includes("Permission remains unknown"));
    for(const t of ["Stage2-only governance restriction","Confirm the target universe"])assert.ok(p.elements["plan-conditions"].textContent.includes(t));
    for(const [i,a] of p.elements.questions.children.entries()){assert.ok(a.textContent.includes("Evidence for "+data.direction_context.questions[i].question_ref));}
    assert.ok(p.elements["evidence-state"].textContent.includes("desktop agent conversation is not connected"));
    assert.ok(p.elements.status.textContent.includes("conditional draft"));
    const labels={
      en:["Use and suitability for this question","Interpretation of possible results","Study or experiment design","Validation and credibility checks"],
      "zh-TW":["本題用途與適用性","可能結果的判讀","研究或實驗設計","驗證與可信度檢查"],
      "zh-CN":["本题用途与适用性","可能结果的判读","研究或实验设计","验证与可信度检查"]
    };
    for(const language of ["en","zh-TW","zh-CN"]){
      p.elements.language.value=language;p.elements.language.onchange();assert.ok(!p.text().includes("undefined"));
      const text=p.elements.questions.textContent;
      for(const label of labels[language])assert.ok(text.includes(label),label);
      for(const key of ["resource_ref","unresolved_resource_refs","next_check_status",'"purpose":'])assert.ok(!text.includes(key),key);
    }
    assert.equal(JSON.stringify(data),original);
    assert.equal(p.calls.length,count);assert.ok(p.calls.every(c=>c.options.method==="GET"));
  });
  test("missing source question mapping is visible and cannot start planning", async () => {
    const data=conditionalView();data.direction_context.missing_mapping=[{reason:"No source question mapping"}];
    data.direction_context.questions=[];data.default_request=null;data.job=null;data.plan=null;
    const p=await page(data);assert.equal(p.elements.prepare.disabled,true);assert.equal(p.elements.run.disabled,true);
    assert.ok(p.elements.status.textContent.includes("More information"));
    assert.ok(p.elements["plan-conditions"].textContent.includes("No source question mapping"));
    assert.ok(p.calls.every(c=>c.options.method==="GET"));
  });
  test("an oversized saved preference shows its focus reason and never starts planning", async () => {
    const data=conditionalView();data.dispatch_action="needs-information";data.planning_status="needs-information";
    data.planning_blockers=["Narrow the scope while retaining source context"];data.default_request=null;data.job=null;data.plan=null;
    const p=await page(data);assert.equal(p.elements.prepare.disabled,true);assert.equal(p.elements.run.disabled,true);
    assert.ok(p.elements.status.textContent.includes("narrower planning scope"));
    assert.ok(p.elements["plan-conditions"].textContent.includes("Narrow the scope while retaining source context"));
    assert.ok(p.calls.every(c=>c.options.method==="GET"));
  });
  test("explicit conditional start retains its mode and intent key without a target override", async () => {
    const data=conditionalView();data.job={status:"intent-recorded"};data.plan=null;
    const p=await page(data,(url,options)=>({ok:true,json:async()=>options.method==="POST"?{submission_status:"accepted"}:structuredClone(data)}));
    p.elements.confirmed.checked=true;await p.elements.run.onclick();await p.elements.run.onclick();
    const writes=p.calls.filter(c=>c.options.method==="POST");assert.equal(writes.length,1);
    const body=JSON.parse(writes[0].options.body);assert.equal(body.mode,"direction-intent");
    assert.equal(body.key,"same-direction-key");assert.equal(body.direction_intent_sha256,"d".repeat(64));
    assert.equal(body.confirmed,true);assert.equal(body.target_thread,undefined);assert.equal(body.selection_request_sha256,undefined);
  });
}
module.exports = {fixture, web};

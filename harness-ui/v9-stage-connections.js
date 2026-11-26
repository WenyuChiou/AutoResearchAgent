// Discover only the current project. GET /connections does not include its input or revision.
const v9ConnectionStages = {2: 'stage2-controller', 3: 'stage3-planning'};
const v9ConnectionFields = ['project_ref', 'project_id', 'input_version', 'brief_sha256', 'revision'];
let v9ConnectionView = null, v9ConnectionWriting = false;
const v9ConnectionHash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

function v9ConnectionBasis(project) {
  if (canonicalReadonly() || !project || project.project_ref !== rt.ref ||
      typeof project.project_ref !== 'string' || !/^[A-Za-z0-9_-]{1,64}$/.test(project.project_ref) ||
      typeof project.project_id !== 'string' || !project.project_id ||
      !(Number.isSafeInteger(project.input_version) && project.input_version > 0 ||
        typeof project.input_version === 'string' && project.input_version.trim() === project.input_version &&
        project.input_version.length > 0 && project.input_version.length <= 128) ||
      !Number.isSafeInteger(project.revision) || project.revision < 0 ||
      !v9ConnectionHash(project.brief_sha256)) return null;
  return Object.fromEntries(v9ConnectionFields.map(key => [key, project[key]]));
}
function v9ConnectionCurrent(view) {
  const basis = v9ConnectionBasis(rt.overview?.project), app = apps[0];
  return !!view && view === v9ConnectionView && !rt.loading && rt.epoch === view.epoch &&
    app?.page === 'workspace' && v9ConnectionStages[app.stage] === view.stage &&
    basis && v9ConnectionFields.every(key => basis[key] === view.basis[key]);
}
function v9ConnectionConnected(stage) {
  const view = v9ConnectionView;
  return v9ConnectionCurrent(view) && view.stage === stage && !view.error &&
    !v9ConnectionPending() && view.row?.status === 'connected';
}
function v9ConnectionPending() {
  return !!rt.pending && rt.pending.ref === rt.ref && (rt.pending.path === projectPath(rt.ref,'connections') ||
    (apps[0]?.stage===2 && rt.pending.path===projectPath(rt.ref,'stage2/actions')));
}
function v9ConnectionCanWrite() {
  try {
    return !rt.loading && !rt.busy && !rt.pending && !rt.controlHeld &&
      sessionStorage.getItem('v7-pending-action') === null && typeof globalThis.navigator?.locks?.request === 'function';
  } catch { return false; }
}
function v9LegacyConnection(stage) {
  const view=v9ConnectionView;
  return v9ConnectionCurrent(view) && view.stage===stage && view.legacyMissing && !v9ConnectionPending();
}
function v9AllowsCandidateRequest() {
  return v9ConnectionConnected('stage2-controller') || v9LegacyConnection('stage2-controller');
}
function v9ContinuationConflict() {
  return typeof wikiStage2State!=='undefined' && wikiStage2State?.error==='stage2-continuation-result-not-current' &&
    JSON.stringify(wikiStage2Basis())===JSON.stringify(wikiStage2State.basis);
}
async function v9ReadConnection(view, afterWrite=false) {
  const {basis, stage} = view;
  let response, missing;
  try { response = await liveRequest(projectPath(basis.project_ref, 'connections')); }
  catch (error) { if (error.status !== 404) throw error; missing = error; }
  // The initial overview came from liveRefresh. Bracket discovery with another overview.
  const fresh = v9ConnectionBasis((await liveRequest(projectPath(basis.project_ref, 'overview')))?.project);
  if (!v9ConnectionCurrent(view) || !fresh || !v9ConnectionFields.every(key => key==='revision' && afterWrite ? fresh.revision>=basis.revision : fresh[key]===basis[key]))
    throw Error('connection-project-binding-mismatch');
  if (missing) { view.legacyMissing = true; throw missing; }
  const row=v9ConnectionRow(response,basis,stage);
  if (stage==='stage2-controller' && row.status==='consent-required' && row.reason==='stage2-continuation-activation-required') {
    const proof=await v9FindActivationOffer(fresh,row.profile_sha256);
    return {...row, proof, observedRevision:fresh.revision};
  }
  return {...row, observedRevision:fresh.revision};
}
function v9ConnectionRow(response,basis,stage) {
  if (response?.project_ref !== basis.project_ref || response.execution_authorized !== false || !response.connections || Array.isArray(response.connections))
    throw Error('connection-project-binding-mismatch');
  const row = response.connections?.[stage];
  if (!Number.isSafeInteger(basis.input_version) && row?.profile_sha256 !== null) throw Error('connection-project-binding-mismatch');
  if (!row) throw Error('stage-connection-interface-unavailable');
  if ((row.reason != null && ['connected','connectable'].includes(row.status)) ||
      !['connectable', 'connected', 'consent-required', 'unavailable'].includes(row.status) ||
      (row.reason !== null && typeof row.reason !== 'string') ||
      (row.profile_sha256 !== null && !v9ConnectionHash(row.profile_sha256)) ||
      (row.status === 'connectable' && !v9ConnectionHash(row.profile_sha256)) ||
      (row.status === 'connected' && row.profile_sha256 !== null &&
        (!v9ConnectionHash(row.connection_id) || typeof row.receipt_id !== 'string' || !row.receipt_id)) ||
      (row.status === 'connected' && row.profile_sha256 === null &&
        (row.connection_id !== null || row.receipt_id !== null)) ||
      (row.status !== 'connected' && (row.connection_id !== null || row.receipt_id !== null)))
    throw Error('stage-connection-response-invalid');
  return row;
}
// The published offer response has no receipt ID. Native history commits the original
// register-offer key and its canonical, revision-independent request digest.
async function v9FindActivationOffer(basis, profile) {
  const stage=await liveRequest(projectPath(basis.project_ref,'stage2'));
  const matches=value=>value?.project_ref===basis.project_ref && value.revision===basis.revision && value.execution_authorized===false;
  if (!matches(stage) || !Array.isArray(stage.offers)) throw Error('stage2-activation-record-unverified');
  const offers=stage.offers.filter(offer=>offer?.status==='ready-for-researcher-activation' &&
    offer.input_version===basis.input_version && offer.brief_sha256===basis.brief_sha256 &&
    v9ConnectionHash(offer.offer_sha256) && offer.offer_ref==='stage2-'+offer.offer_sha256.slice(0,32));
  if (!offers.length) return null;
  const history=await liveRequest(projectPath(basis.project_ref,'history'));
  if (!matches(history) || !Array.isArray(history.actions)) throw Error('stage2-activation-record-unverified');
  const verified=[];
  for (const action of history.actions) {
    const offer=offers.find(row=>row.offer_ref===action?.offer?.offer_ref && row.offer_sha256===action.offer.offer_sha256);
    if (!offer || action.kind!=='stage2-register-offer' || action.project_ref!==basis.project_ref ||
        action.status!=='saved' || action.execution_authorized!==false || typeof action.key!=='string' ||
        action.offer.input_version!==basis.input_version || action.offer.brief_sha256!==basis.brief_sha256) continue;
    // Native canonical JSON sorts these ASCII keys and omits revision.
    const body={brief_sha256:basis.brief_sha256,connection_profile_sha256:profile,
      input_version:basis.input_version,key:action.key,offer_sha256:offer.offer_sha256};
    const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify({body,kind:action.kind})));
    const digest=Array.from(new Uint8Array(bytes),byte=>byte.toString(16).padStart(2,'0')).join('');
    if (digest===action.request_sha256) verified.push({offer,key:action.key});
  }
  if (verified.length!==1) throw Error('stage2-activation-record-unverified');
  return verified[0];
}
function v9ConnectionAction(view) {
  const row=view.row;
  if (!row || !Number.isSafeInteger(view.basis.input_version) || !v9ConnectionHash(row.profile_sha256) ||
      view.error || view.stage==='stage2-controller' && v9ContinuationConflict()) return null;
  if (row.status==='connectable') return 'connect';
  if (view.stage==='stage2-controller' && row.status==='consent-required' &&
      row.reason==='stage2-continuation-activation-required') return row.proof?'activate':'publish';
  return null;
}
async function v9ConnectionRead(view) {
  if (!v9ConnectionCurrent(view) || view.reading) return;
  view.reading = true; view.http=null; view.legacyMissing=false; view.row = null; view.error = ''; livePaint();
  try { view.row = await v9ReadConnection(view); }
  catch (error) { view.error = error.message; view.http = error.status; }
  finally { view.reading = false; if (v9ConnectionCurrent(view)) livePaint(); }
}
function v9ConnectionReason(code, http) {
  if (code === 'stage2-continuation-activation-required')
    return rl('还差本项目的 Stage 2 启用同意。请查看本版启用记录并确认原提议。','Stage 2 needs your consent. Review this version’s activation record and confirm its original offer.');
  if (code === 'stage2-controller-current-input-required')
    return rl('还缺本课题已接收的 Stage 2 输入包和接收回执。请先查看 Stage 1 交付。','The current Stage 2 input packet and receiving receipt are required. Check the Stage 1 delivery.');
  if (code === 'stage3-current-selection-required')
    return rl('还缺本课题当前版本的正式选案和已核验的选案回执。','A verified formal selection and receipt for this version are required.');
  if (/^stage[23]-(controller|planning)-profile-unavailable$/.test(code))
    return rl('这次启动没有提供本阶段的运行配置。请在原项目目录用已核验的配置重开。','This launch lacks the stage configuration. Reopen the original project directory with the verified configuration.');
  if (code === 'stage2-continuation-result-not-current' || /^(?:connection-project-binding-mismatch|(?:stage[23]|stage-connection)-[a-z0-9-]*(?:binding-differs|project-stale|connection-differs|path-mismatch|current-input-differs|native-input-differs|receipt-differs))$/.test(code))
    return rl('本次核对与原记录不一致。若搬过目录，请回原物理目录，用原已核配置重开，先只读核对项目、整数输入版本、原包和回执。原路径无法恢复时保留记录，等待经核验的迁移入口。请勿重新执行、换请求键或手改回执。','The binding differs. If files moved, reopen the original physical directory with the verified configuration. Check the project, integer input version, original packet and receipt using read-only requests. If the path cannot be restored, retain the records for a verified migration. Do not rerun, change keys or edit receipts.');
  if (code==='stage2-activation-record-unverified')
    return rl('已有启用提议或记录，但缺少同一项目、档案和请求键的可核回执。请保留原记录，只读复核。','The original activation offer lacks a verifiable matching request receipt. Retain the record and check again.');
  if (http === 404 || code === 'stage-connection-interface-unavailable')
    return rl('这次启动没有提供本阶段接通接口，暂时无法核验。','This launch does not expose the stage connection interface.');
  if (code === 'project-lock-busy' || code === 'project-lock-failed')
    return rl('暂时无法取得跨标签页项目锁。请稍后只读复核。','The project lock is unavailable. Check the saved state again later.');
  if (http === 403 || code === 'cross-site-rejected' || code === 'credential-rejected')
    return rl('访问被拒绝。请用原项目的已认证页面查看记录。','Access was refused. Check the records in the original authenticated project page.');
  return rl('原记录暂时无法核验。请保留现有记录，查看技术详情后再只读复核。','The original record could not be verified. Retain it and check the technical details before reading again.');
}
function v9ConnectionPanel(app) {
  if (app !== apps[0] || app.page !== 'workspace' || canonicalReadonly() || !rt.ref) return '';
  const stage = v9ConnectionStages[app.stage], basis = v9ConnectionBasis(rt.overview?.project);
  if (!stage) return '';
  const heading = 'Stage ' + app.stage + ' · ' + rl('本课题接通状态','Project connection');
  if (!basis || rt.loading) return '<section class="hs-panel"><h2>'+heading+'</h2><p>'+rl('等待核对本课题、整数输入版本和摘要。','Waiting for a verified project, integer input version and brief digest.')+'</p></section>';
  if (!v9ConnectionCurrent(v9ConnectionView)) {
    const next = {epoch: rt.epoch, basis, stage, reading: false, row: null, error: ''};
    v9ConnectionView = next;
    queueMicrotask(() => v9ConnectionRead(next));
  }
  const view = v9ConnectionView, row = view.row;
  const code = view.error || row?.reason, unknown = v9ConnectionPending();
  let message = rl('正在核对本课题的接通记录。','Checking this project’s saved connection.');
  if (unknown && rt.pending.path===projectPath(rt.ref,'stage2/actions')) message=rl('上次启用结果仍为 Unknown。请保留原请求，查询原启用回执。','Activation remains Unknown. Retain the request and check its original receipt.');
  else if (unknown) message = rl('上次登记结果仍为 Unknown。保留原请求键和记录，当前接口缺少可核对该请求的回执。这里只能查询。','The last registration remains Unknown. Its key and record are retained. This interface lacks a verifiable request receipt. Only readback is available.');
  else if (view.error || row?.status === 'consent-required' || row?.status === 'unavailable') message = v9ConnectionReason(code, view.http);
  else if (row?.status === 'connected') message = rl('本课题已接通。已核对接通登记；执行与交付须另查原记录。','This project is connected. Registration was verified. Execution and delivery have separate records.');
  else if (row?.status === 'connectable') message = rl('本课题还没有接通。可以登记当前配置，登记不会启动研究。','This project is ready to connect. Registering the current configuration does not start research.');
  const token = rx(JSON.stringify([stage, view.epoch, ...Object.values(basis)]));
  const button = (action, label, disabled) => `<button type="button" class="hs-button" data-v9-connection="${action}" data-connection-basis="${token}" ${disabled?'disabled':''}>${label}</button>`;
  const action=v9ConnectionAction(view);
  const labels={connect:rl('接通本课题','Connect this project'),publish:rl('生成本课题的启用提议','Publish the project activation offer'),
    activate:rl('同意这份提议并启用 Stage 2','Confirm this offer and activate Stage 2')};
  const proposal=action==='activate'?'<p>'+rl('原启用提议','Original activation offer')+' · '+rx(row.proof.offer.offer_ref)+'</p>':'';
  const controls=!unknown && action?button(action,labels[action],!v9ConnectionCanWrite()||v9ConnectionWriting):'';
  const lockHint = controls && typeof globalThis.navigator?.locks?.request !== 'function'
    ? rl('此浏览器缺少跨标签页项目锁，仅可查看。','This browser lacks cross-tab project locks. Readback is available.') : '';
  return `<section class="hs-panel" data-v9-connection-panel><h2>${heading}</h2><p role="status">${message} ${lockHint}</p>${proposal}${controls}
    ${button('read', rl('重新核对接通记录','Check connection again'), view.reading || v9ConnectionWriting)}
    ${code ? '<details><summary>'+rl('技术详情','Technical details')+'</summary><code>'+rx(code)+'</code></details>' : ''}</section>`;
}
document.addEventListener('click', async event => {
  const button = event.target.closest?.('[data-v9-connection]'), view = v9ConnectionView;
  if (!button || button.disabled || !v9ConnectionCurrent(view) || !apps[0].el.contains(button) ||
      button.dataset.connectionBasis !== JSON.stringify([view.stage, view.epoch, ...Object.values(view.basis)]) ||
      view.reading || v9ConnectionWriting) return;
  if (button.dataset.v9Connection === 'read') return v9ConnectionRead(view);
  const action=button.dataset.v9Connection, row=view.row, {stage,basis}=view;
  if (action!==v9ConnectionAction(view) || !v9ConnectionCanWrite()) return;
  v9ConnectionWriting=true; livePaint();
  try {
    await navigator.locks.request('ara.stage2.transaction.v1.'+basis.project_ref,{mode:'exclusive',ifAvailable:true}, async lock=>{
      if (!lock) throw Error('project-lock-busy');
      if (!v9ConnectionCurrent(view)||!v9ConnectionCanWrite()) return;
      const fresh=await v9ReadConnection(view);
      if (!v9ConnectionCurrent(view)||!v9ConnectionCanWrite()) return;
      view.row=fresh;
      if (action!==v9ConnectionAction(view)) return;
      if (fresh.profile_sha256!==row.profile_sha256 || fresh.proof?.offer.offer_sha256!==row.proof?.offer.offer_sha256)
        throw Error('stage-connection-profile-differs');
      await v9RegisterStage(view,action);
    });
  } catch (error) {
    if (v9ConnectionCurrent(view)) {view.row=null;view.error=error.message||'project-lock-failed';view.http=error.status;}
  } finally {v9ConnectionWriting=false;livePaint();}
});

async function v9RegisterStage(view, action) {
  const {basis,stage,row}=view, ref=basis.project_ref, activate=action==='activate';
  const fields=activate?{offer_ref:row.proof.offer.offer_ref,offer_sha256:row.proof.offer.offer_sha256}
    :{stage,profile_sha256:row.profile_sha256};
  const body={revision:basis.revision,input_version:basis.input_version,brief_sha256:basis.brief_sha256,
    ...fields,confirmed:true,key:crypto.randomUUID()};
  const pending={path:projectPath(ref,activate?'stage2/actions':'connections'),ref,body};
  const serialized=JSON.stringify(pending), storage='v7-pending-action';
  const owns=()=>rt.pending===pending && JSON.stringify(pending)===serialized && sessionStorage.getItem(storage)===serialized;
  const clear=()=>{sessionStorage.removeItem(storage);rt.pending=null;};
  sessionStorage.setItem(storage,serialized);
  rt.pending=pending;rt.busy=true;livePaint();
  try {
    let response;
    try { response=await liveRequest(pending.path,body); }
    catch (error) {
      if (owns() && [400,401,403,404,413,415].includes(error.status)) clear();
      throw error;
    }
    if (!owns() || !v9ConnectionCurrent(view)) return;
    if (activate) {
      if (response?.execution_authorized!==false || response.status!=='saved' ||
          response.offer_ref!==body.offer_ref || response.offer_sha256!==body.offer_sha256 ||
          response.input_version!==body.input_version || response.brief_sha256!==body.brief_sha256 ||
          response.stage2_status!=='ready-for-explicit-stage2-run' ||
          !await liveReceiptBound(pending,response)) throw Error('stage2-activation-receipt-unverified');
    } else {
      const result=v9ConnectionRow(response,basis,stage);
      if (Object.keys(response.connections).length!==1 || result.profile_sha256!==body.profile_sha256)
        throw Error('stage-connection-receipt-unverified');
      if (result.status==='connected' && result.receipt_id!==body.key) throw Error('stage-connection-receipt-unverified');
      if (!['connected','consent-required'].includes(result.status) || action==='publish' && result.status!=='consent-required') throw Error('stage-connection-receipt-unverified');
      const read=await v9ReadConnection(view,true);
      if (read.profile_sha256!==body.profile_sha256 || read.status!==result.status) throw Error('stage-connection-receipt-unverified');
      if (result.status==='connected') {
        if (read.receipt_id!==body.key || read.connection_id!==result.connection_id) throw Error('stage-connection-receipt-unverified');
      } else {
        const offer=result.activation_offer;
        if (stage!=='stage2-controller'||result.reason!=='stage2-continuation-activation-required'||
            !Number.isSafeInteger(result.revision)||result.revision!==read.observedRevision||!offer||
            offer.input_version!==basis.input_version||offer.brief_sha256!==basis.brief_sha256||
            offer.status!=='ready-for-researcher-activation'||read.proof?.key!==body.key||
            read.proof.offer.offer_sha256!==offer.offer_sha256||read.proof.offer.offer_ref!==offer.offer_ref)
          throw Error('stage2-activation-record-unverified');
      }
    }
    if (!owns() || !v9ConnectionCurrent(view)) return;
    clear();
    await liveRefresh(ref,{list:true});
  } finally {rt.busy=false;}
}

// Generic recovery hashes an operation named "connections". Native history records
// register-offer or stage-connection requests with different derived bodies.
const v9OriginalRecover=liveRecover;
liveRecover=async function(){
  const pending=rt.pending;
  if (!pending?.ref || pending.path!==projectPath(pending.ref,'connections')) return v9OriginalRecover();
  if (pending.ref!==rt.ref || rt.busy) return;
  if (v9ConnectionCurrent(v9ConnectionView)) return v9ConnectionRead(v9ConnectionView);
  // Preserve the original intent on other pages too. A discovery read cannot settle it.
  try { await liveRequest(projectPath(pending.ref,'connections')); } catch { /* Still unknown. */ }
};

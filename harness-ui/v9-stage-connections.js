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
const v9ConnectionPaint = livePaint;
livePaint = function () {
  const view = v9ConnectionView, app = apps[0];
  const selector = '[data-v9-connection-panel] h2';
  const heading = view?.stage === 'stage2-controller' && v9ConnectionCurrent(view)
    ? app.el?.querySelector(selector) : null;
  const restore = heading && document.activeElement === heading;
  const result = v9ConnectionPaint();
  // Async readbacks replace the DOM. Restore only the heading the user was still focused on.
  if (restore && document.activeElement === document.body && v9ConnectionCurrent(view))
    app.el.querySelector(selector)?.focus({preventScroll:true});
  return result;
};
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
function v9StaticStage3Read() {
  const view=v9ConnectionView, configured=window.RESEARCH_PROJECTS?.stage3_planning_projects;
  return v9ConnectionCurrent(view) && view.stage==='stage3-planning' && view.stage2Only &&
    !view.error && !v9ConnectionPending() && Array.isArray(configured) && configured.includes(view.basis.project_ref);
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
  // The Stage 2 adapter can be present while Stage 3 uses the original static bootstrap binding.
  if (stage==='stage3-planning' && !afterWrite && v9Stage2OnlyDiscovery(response,basis)) {
    view.stage2Only = true;
    // What the Stage 2 row says (e.g. no run configuration in this launch) is all the page learns about this launch.
    view.stage2Reason = response.connections['stage2-controller']?.reason || null;
    return null;
  }
  const row=v9ConnectionRow(response,basis,stage);
  if (stage==='stage2-controller' && row.status==='consent-required' && row.reason==='stage2-continuation-activation-required') {
    const proof=await v9FindActivationOffer(fresh,row.profile_sha256);
    return {...row, proof, observedRevision:fresh.revision};
  }
  return {...row, observedRevision:fresh.revision};
}
function v9Stage2OnlyDiscovery(response,basis) {
  const rows=response?.connections;
  if (!Number.isSafeInteger(basis.input_version) || response?.project_ref!==basis.project_ref ||
      response.execution_authorized!==false || Object.keys(response).length!==3 ||
      !rows || typeof rows!=='object' || Array.isArray(rows) || Object.keys(rows).length!==1 ||
      !Object.hasOwn(rows,'stage2-controller')) return false;
  const controller=v9ConnectionRow(response,basis,'stage2-controller');
  if (Object.keys(controller).length!==5) return false;
  if (controller.status==='consent-required')
    return controller.reason==='stage2-continuation-activation-required' && v9ConnectionHash(controller.profile_sha256);
  if (controller.status==='unavailable')
    return !!controller.reason?.trim() && (controller.reason!=='stage2-controller-profile-unavailable' || controller.profile_sha256===null);
  return true;
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
    const digest=await v9NativeRequestDigest(action.kind,body);
    if (digest===action.request_sha256) verified.push({offer,key:action.key});
  }
  if (verified.length!==1) throw Error('stage2-activation-record-unverified');
  return verified[0];
}
async function v9NativeRequestDigest(kind, sortedBody) {
  const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify({body:sortedBody,kind})));
  return Array.from(new Uint8Array(bytes),byte=>byte.toString(16).padStart(2,'0')).join('');
}
function v9ConnectionAction(view) {
  const row=view.row;
  if (!row || !Number.isSafeInteger(view.basis.input_version) || !v9ConnectionHash(row.profile_sha256) ||
      view.error || view.stage==='stage2-controller' && v9ContinuationConflict()) return null;
  if (row.status==='connectable') return 'connect';
  // A saved Stage 3 registration whose planning lease was lost (the Host was force-stopped) reads "unavailable"
  // with this reason; registering again with a never-used key returns the saved record (backend-fixes-1127-0630 §5).
  if (view.stage==='stage3-planning' && row.status==='unavailable' && row.reason==='stage3-planning-resource-unavailable') return 'reconnect';
  if (view.stage==='stage2-controller' && row.status==='consent-required' &&
      row.reason==='stage2-continuation-activation-required') return row.proof?'activate':'publish';
  return null;
}
async function v9ConnectionRead(view) {
  if (!v9ConnectionCurrent(view) || view.reading) return;
  view.reading = true; view.http=null; view.legacyMissing=false; view.stage2Only=false; view.stage2Reason=null; view.row = null; view.error = ''; livePaint();
  try { view.row = await v9ReadConnection(view); }
  catch (error) { view.error = error.message; view.http = error.status; }
  finally { view.reading = false; if (v9ConnectionCurrent(view)) livePaint(); }
}
function v9ConnectionReason(code, http, stage) {
  if (code === 'stage2-continuation-activation-required')
    return rl('还差本项目的 Stage 2 启用同意。请查看本版启用记录并确认原提议。','Stage 2 needs your consent. Review this version’s activation record and confirm its original offer.');
  if (code === 'stage2-controller-current-input-required')
    return rl('还缺本课题已接收的 Stage 2 输入包和接收回执。请先查看 Stage 1 交付。','The current Stage 2 input packet and receiving receipt are required. Check the Stage 1 delivery.');
  if (code === 'stage3-planning-resource-unavailable')
    return rl('Stage 3 的规划登记已保存；如果上次是强行关闭，这次启动后会先显示『未接通』，点『重新接通』即可恢复，不会重复执行任何步骤，也不会新增记录。','The Stage 3 planning registration is saved. If the last session was force-closed, it first shows "not connected" after launch; choose "Reconnect" to restore it. No step is repeated and no record is added.','Stage 3 的規劃登記已儲存；如果上次是強行關閉，這次啟動後會先顯示『未接通』，點『重新接通』即可恢復，不會重複執行任何步驟，也不會新增紀錄。');
  if (code === 'stage3-current-selection-required')
    return rl('还缺本课题当前版本的正式选案和已核验的选案回执。','A verified formal selection and receipt for this version are required.');
  if (code === 'stage2-controller-profile-unavailable')
    return rl('这次启动没有提供 Stage 2 运行配置。请联系原项目操作者，请其用已核验的配置从原项目目录重开。','This launch has no Stage 2 configuration. Ask the project operator to reopen the original project directory with the verified configuration.','這次啟動沒有提供 Stage 2 執行設定。請聯絡原專案操作者，請其用已核驗的設定從原專案目錄重開。');
  if (/^stage[23]-(controller|planning)-profile-unavailable$/.test(code))
    return rl('这次启动没有提供本阶段的运行配置。请在原项目目录用已核验的配置重开。','This launch lacks the stage configuration. Reopen the original project directory with the verified configuration.');
  if (code === 'stage2-continuation-result-not-current' || /^(?:connection-project-binding-mismatch|(?:stage[23]|stage-connection)-[a-z0-9-]*(?:binding-differs|project-stale|connection-differs|path-mismatch|current-input-differs|native-input-differs|receipt-differs))$/.test(code))
    return rl('本次核对与原记录不一致。若搬过目录，请回原物理目录，用原已核配置重开，先只读核对项目、整数输入版本、原包和回执。原路径无法恢复时保留记录，等待经核验的迁移入口。请勿重新执行、换请求键或手改回执。','The binding differs. If files moved, reopen the original physical directory with the verified configuration. Check the project, integer input version, original packet and receipt using read-only requests. If the path cannot be restored, retain the records for a verified migration. Do not rerun, change keys or edit receipts.');
  if (code==='stage2-activation-record-unverified')
    return rl('已有启用提议或记录，但缺少同一项目、档案和请求键的可核回执。请保留原记录，只读复核。','The original activation offer lacks a verifiable matching request receipt. Retain the record and check again.');
  if ((http === 404 || code === 'stage-connection-interface-unavailable') && stage === 'stage2-controller')
    return rl('这次启动没有提供 Stage 2 接通接口。请联系原项目操作者，确认能否用支持该接口的版本重开。','This launch does not expose the Stage 2 connection interface. Ask the project operator whether it can be reopened with a version that supports it.','這次啟動沒有提供 Stage 2 接通介面。請聯絡原專案操作者，確認能否用支援該介面的版本重開。');
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
  const heading = rl('本课题的 Stage ' + app.stage, 'Stage ' + app.stage + ' connection');
  if (!basis || rt.loading) return '<section class="hs-panel"><h2>'+heading+'</h2><p>'+rl('还没有可核对的接通记录。正在等待本课题、输入版本和摘要。','No connection record is available to check yet. Waiting for the project, input version and brief digest.')+'</p></section>';
  if (!v9ConnectionCurrent(v9ConnectionView)) {
    const next = {epoch: rt.epoch, basis, stage, reading: false, row: null, error: ''};
    v9ConnectionView = next;
    queueMicrotask(() => v9ConnectionRead(next));
  }
  const view = v9ConnectionView, row = view.row;
  const code = view.error || row?.reason, unknown = v9ConnectionPending();
  const action = v9ConnectionAction(view);
  const missingInput = !unknown && !view.error && stage==='stage2-controller' &&
    row?.status==='unavailable' && code==='stage2-controller-current-input-required';
  let message = rl('正在核对本课题的接通记录。','Checking this project’s saved connection.');
  if (unknown && rt.pending.path===projectPath(rt.ref,'stage2/actions')) message=rl('上次启用结果仍为 Unknown。请保留原请求，查询原启用回执。','Activation remains Unknown. Retain the request and check its original receipt.');
  else if (unknown) message = rl('上次登记结果仍为 Unknown。原请求键已保留；请只读核对接通状态及对应的操作回执。','Registration remains Unknown. Its key is retained. Check the saved connection and the matching action receipt.');
  else if (view.stage2Only) message = v9StaticStage3Read()
    ? rl('可查看原配置下本课题已保存的 Stage 3 规划。','Read the saved Stage 3 plan for this project under its original configuration.','可查看原設定下本課題已儲存的 Stage 3 規劃。')
    : v9ConnectionReason('stage-connection-interface-unavailable', null, stage);
  else if (action === 'publish') message = rl('还差这个课题的 Stage 2 启用同意。先生成一份启用提议，看过再同意。','Stage 2 needs your consent. Generate an offer and review it before agreeing.');
  else if (action === 'activate') message = rl('启用提议已生成，生成时间暂不可读。同意后只登记启用，不会启动研究。','The activation offer was generated. Its timestamp is unavailable. Agreeing records activation without starting research.');
  else if (view.error || row?.status === 'consent-required' || row?.status === 'unavailable') message = v9ConnectionReason(code, view.http, stage);
  else if (row?.status === 'connected') message = rl('本课题已接通。已核对接通登记；执行与交付须另查原记录。','This project is connected. Registration was verified. Execution and delivery have separate records.');
  else if (row?.status === 'connectable') message = rl('本课题还没有接通。可以登记当前配置，登记不会启动研究。','This project is ready to connect. Registering the current configuration does not start research.');
  const token = rx(JSON.stringify([stage, view.epoch, ...Object.values(basis)]));
  const button = (action, label, disabled) => `<button type="button" class="hs-button" ${action === 'read' ? '' : 'data-v1-write'} data-v9-connection="${action}" data-connection-basis="${token}" ${disabled?'disabled':''}>${label}</button>`;
  const labels={connect:rl('接通本课题','Connect this project'),reconnect:rl('重新接通','Reconnect','重新接通'),publish:rl('生成本课题的启用提议','Publish the project activation offer'),
    activate:rl('同意这份提议并启用 Stage 2','Confirm this offer and activate Stage 2')};
  const controls=!unknown && action?button(action,labels[action],!v9ConnectionCanWrite()||v9ConnectionWriting):'';
  const lockHint = controls && (!v9ConnectionCanWrite() || v9ConnectionWriting)
    ? typeof globalThis.navigator?.locks?.request !== 'function'
      ? rl('此浏览器缺少跨标签页项目锁，仅可查看。','This browser lacks cross-tab project locks. Readback is available.')
      : rl('正在等待当前操作或核对完成。','Waiting for the current operation or readback to finish.')
    : '';
  const stage1 = missingInput ? `<button type="button" class="hs-button" data-stage="1">${rl('前往 Stage 1 查看交付','Go to Stage 1 to view delivery','前往 Stage 1 查看交付')}</button>` : '';
  const status = !unknown && (action === 'publish' ? rl('等你 · 第 1 步','Waiting for you · Step 1')
    : action === 'activate' ? rl('等你 · 第 2 步','Waiting for you · Step 2')
    : missingInput ? rl('缺输入包','Input packet required') : '');
  const offerRef = row?.proof?.offer.offer_ref;
  const request = stage === 'stage2-controller' && v9ConnectionConnected(stage) && typeof wikiStage2RequestRow === 'function'
    ? wikiStage2RequestRow(wikiStage2State) : '';
  return `<section class="hs-panel" data-v9-connection-panel><h2 tabindex="-1">${heading}</h2><p role="status">${status ? '<strong>'+status+'</strong> ' : ''}${message} ${lockHint}</p>${controls}${stage1}
    ${controls ? '' : button('read', unknown ? rl('核对上次提交','Check previous submission') : rl('重新读取','Read again'), view.reading || v9ConnectionWriting)}
    ${code || offerRef ? `<details><summary>${rl('技术细节','Technical details')}</summary>${code ? '<code>'+rx(code)+'</code>' : ''}${offerRef ? '<p>'+rl('启用提议编号','Activation offer ID')+' · <code>'+rx(offerRef)+'</code></p>' : ''}</details>` : ''}
    ${request ? '<hr><h3>'+rl('生成候选','Generate candidates')+'</h3>'+request : ''}</section>`;
}
// Read-only description of the same connection state for the Wiki V1 page. It uses the
// panel's discovery path (one GET read) and returns plain values; it renders nothing.
function v9ConnectionModel(app) {
  if (app !== apps[0] || app.page !== 'workspace' || canonicalReadonly() || !rt.ref) return null;
  const stage = v9ConnectionStages[app.stage], basis = v9ConnectionBasis(rt.overview?.project);
  if (!stage) return null;
  if (!basis || rt.loading) return {phase: 'waiting', stage, basis: null};
  if (!v9ConnectionCurrent(v9ConnectionView)) {
    const next = {epoch: rt.epoch, basis, stage, reading: false, row: null, error: ''};
    v9ConnectionView = next;
    queueMicrotask(() => v9ConnectionRead(next));
  }
  const view = v9ConnectionView, row = view.row, unknown = v9ConnectionPending();
  const action = v9ConnectionAction(view), code = view.error || row?.reason;
  return {phase: 'ready', stage, basis, view, row, code, unknown, action, http: view.http,
    stage2Only: !!view.stage2Only, stage2Reason: view.stage2Reason || null,
    token: JSON.stringify([stage, view.epoch, ...Object.values(basis)]),
    reading: !!view.reading, writing: v9ConnectionWriting, canWrite: v9ConnectionCanWrite(),
    noLocks: typeof globalThis.navigator?.locks?.request !== 'function',
    connected: v9ConnectionConnected(stage), offerRef: row?.proof?.offer.offer_ref || null,
    reconnectError: v9ReconnectErrors.get(basis.project_ref) || null};
}
document.addEventListener('click', async event => {
  const button = event.target.closest?.('[data-v9-connection]'), view = v9ConnectionView;
  if (!button || button.disabled || !v9ConnectionCurrent(view) || !apps[0].el.contains(button) ||
      button.dataset.connectionBasis !== JSON.stringify([view.stage, view.epoch, ...Object.values(view.basis)]) ||
      view.reading || v9ConnectionWriting) return;
  if (button.dataset.v9Connection === 'read') return v9ConnectionPending()?liveRecover():v9ConnectionRead(view);
  const action=button.dataset.v9Connection, row=view.row, {stage,basis}=view;
  if (action!==v9ConnectionAction(view) || !v9ConnectionCanWrite()) return;
  v9ConnectionWriting=true;
  // A new attempt replaces the reason kept from an earlier failed reconnect, so it cannot hide what happens now.
  if (action==='reconnect') v9ReconnectErrors.delete(basis.project_ref);
  livePaint();
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
      if (action==='reconnect') await v9ReconnectStage(view); else await v9RegisterStage(view,action);
    });
  } catch (error) {
    // A failed reconnect keeps the row and its button; the reason is kept per project (v9ReconnectErrors) so the
    // block can say the last attempt failed instead of losing the button (review P2-2).
    // Only this attempt's own recorded failure keeps the row; any other error (lock busy, profile changed) is shown.
    if (v9ConnectionCurrent(view) && !(action==='reconnect' && error?.v9ReconnectRecorded)) {view.row=null;view.error=error.message||'project-lock-failed';view.http=error.status;}
  } finally {v9ConnectionWriting=false;livePaint();}
});

// Re-attach a saved Stage 3 registration. The service answers with the record it already saved (same
// connection_id and the original receipt_id) and writes no new action, so nothing is retried automatically and
// no unknown-outcome marker is kept: a lost answer is settled by reading the state again. Every click uses a new key.
const v9UsedReconnectKeys=new Set(), v9ReconnectErrors=new Map();
function v9ReconnectKey(){
  let key;
  do key=crypto.randomUUID(); while (v9UsedReconnectKeys.has(key));
  v9UsedReconnectKeys.add(key);
  return key;
}
async function v9ReconnectStage(view) {
  const {basis,stage,row}=view, ref=basis.project_ref;
  const body={revision:basis.revision,input_version:basis.input_version,brief_sha256:basis.brief_sha256,
    stage,profile_sha256:row.profile_sha256,confirmed:true,key:v9ReconnectKey()};
  rt.busy=true;livePaint();
  let answered=false;
  try {
    const response=await liveRequest(projectPath(ref,'connections'),body);
    answered=true;
    if (!v9ConnectionCurrent(view)) return;
    const result=v9ConnectionRow(response,basis,stage);
    // The saved record carries the original receipt; this click's key coming back means a new registration was
    // written, which a reconnect must never do (review P2-1).
    if (Object.keys(response.connections).length!==1 || result.status!=='connected' || result.profile_sha256!==body.profile_sha256 ||
        !v9ConnectionHash(result.connection_id) || typeof result.receipt_id!=='string' || !result.receipt_id || result.receipt_id===body.key)
      throw Error('stage-connection-receipt-unverified');
    const read=await v9ReadConnection(view,true);
    if (read.status!=='connected' || read.connection_id!==result.connection_id || read.receipt_id!==result.receipt_id)
      throw Error('stage-connection-receipt-unverified');
    if (!v9ConnectionCurrent(view)) return;
    v9ReconnectErrors.delete(ref);
    await liveRefresh(ref,{list:true});
  } catch (error) {
    if (ref!==rt.ref) throw error; // the topic changed meanwhile; nothing is shown for it
    v9ReconnectErrors.set(ref,{code:error.message||'stage-connection-receipt-unverified',http:error.status??null});
    if (error && typeof error==='object') error.v9ReconnectRecorded=true;
    // After the service answered, read the project again so the page shows the real state (review P2-4).
    if (answered) { try { await liveRefresh(ref,{list:true}); } catch (_) { /* The reason above stays on the page. */ } }
    throw error;
  } finally {rt.busy=false;}
}
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

// Native registration history stores a derived body, not the submitted /connections body.
// Reconcile only a matching original journal entry; every request in this path is a GET.
const v9OriginalRecover=liveRecover;
liveRecover=async function(){
  const pending=rt.pending, ref=pending?.ref;
  const connection=!!ref && pending.path===projectPath(ref,'connections');
  const activation=!!ref && pending.path===projectPath(ref,'stage2/actions');
  if (!connection && !activation) return v9OriginalRecover();
  const basis=v9ConnectionBasis(rt.overview?.project), body=pending.body, epoch=rt.epoch;
  if (rt.busy||rt.loading||ref!==rt.ref||!basis||!body||!Number.isSafeInteger(body.input_version)||
      body.input_version!==basis.input_version||body.brief_sha256!==basis.brief_sha256||
      !Number.isSafeInteger(body.revision)||body.revision<0||body.revision>basis.revision||
      body.confirmed!==true||typeof body.key!=='string'||!/^[A-Za-z0-9_-]{1,128}$/.test(body.key)) return;
  const fields=['revision','input_version','brief_sha256','key','confirmed',...(connection?['stage','profile_sha256']:['offer_ref','offer_sha256'])];
  if (Object.keys(body).length!==fields.length||!fields.every(key=>Object.hasOwn(body,key))||
      (connection&&(!Object.values(v9ConnectionStages).includes(body.stage)||!v9ConnectionHash(body.profile_sha256)))||
      (activation&&(!v9ConnectionHash(body.offer_sha256)||body.offer_ref!=='stage2-'+body.offer_sha256.slice(0,32)))) return;
  const storage='v7-pending-action', serialized=JSON.stringify(pending);
  const current=()=>{
    if(rt.pending!==pending||rt.ref!==ref||rt.epoch!==epoch||rt.busy||rt.loading||
        !v9ConnectionFields.every(key=>rt.overview?.project?.[key]===basis[key])) return false;
    try {return JSON.stringify(pending)===serialized&&sessionStorage.getItem(storage)===serialized;}
    catch {return false;}
  };
  try {
    if (!current()) return;
    let row;
    if (connection) {
      row=v9ConnectionRow(await liveRequest(pending.path),basis,body.stage);
      if (!current()||row.profile_sha256!==body.profile_sha256||
          !['connected','consent-required'].includes(row.status)) return;
    }
    const history=await liveRequest(projectPath(ref,'history'));
    if (!current()||history?.project_ref!==ref||history.execution_authorized!==false||!Array.isArray(history.actions)) return;
    const saved=history.actions.filter(action=>action?.key===body.key);
    if (saved.length!==1) return;
    const receipt=saved[0];
    if (receipt.project_ref!==ref||receipt.execution_authorized!==false||receipt.status!=='saved') return;
    const fresh=v9ConnectionBasis((await liveRequest(projectPath(ref,'overview')))?.project);
    if (!current()||!fresh||fresh.revision<basis.revision||fresh.revision!==history.revision||
        !['project_ref','project_id','input_version','brief_sha256'].every(key=>fresh[key]===basis[key])) return;
    if (activation) {
      if (receipt.stage2_status!=='ready-for-explicit-stage2-run'||receipt.offer_ref!==body.offer_ref||
          receipt.offer_sha256!==body.offer_sha256||receipt.input_version!==body.input_version||
          receipt.brief_sha256!==body.brief_sha256||!await liveReceiptBound(pending,receipt)) return;
    } else if (row.status==='connected') {
      const kind=body.stage==='stage2-controller'?'stage2-record-connection':'stage3-record-connection';
      if (row.receipt_id!==body.key||!v9ConnectionHash(row.connection_id)||
          receipt.kind!==kind||receipt.connection_id!==row.connection_id) return;
      const digest=await v9NativeRequestDigest(kind,{brief_sha256:body.brief_sha256,connection_sha256:row.connection_id,
        input_version:body.input_version,key:body.key});
      if (digest!==receipt.request_sha256) return;
    } else {
      if (body.stage!=='stage2-controller'||row.reason!=='stage2-continuation-activation-required'||
          (await v9FindActivationOffer(fresh,body.profile_sha256))?.key!==body.key) return;
    }
    if (!current()) return;
    sessionStorage.removeItem(storage);rt.pending=null;
    await liveRefresh(ref,{list:true});
  } catch (error) {
    if (current()&&v9ConnectionCurrent(v9ConnectionView)) {v9ConnectionView.error=error.message;livePaint();}
  }
};

// Pure projection of the existing project/models/model_offers GET contracts.
// No credential, storage, network, login probe, authorization or execution here.
function connectionDiagnostics(input, now) {
 const p=input.project,m=input.models,o=input.offers;
 const current=!!p&&p.project_ref===input.ref&&Number.isSafeInteger(p.input_version)&&p.input_version>0&&Number.isSafeInteger(p.revision)&&/^[a-f0-9]{64}$/.test(p.brief_sha256||'');
 const bound=current&&!!m&&m.project_ref===p.project_ref&&m.input_version===p.input_version&&m.revision===p.revision&&m.brief_sha256===p.brief_sha256;
 const finite=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0?value:null;
 const v={binding:current?'current':'unavailable',topic:current?p.brief?.original_description??null:null,
  project:current?p.project_ref:null,inputVersion:current?p.input_version:null,
  provider:'unknown',authentication:'unknown',permission:'unknown',researchAuthorized:null,
  budgets:{},monetaryCost:null,callsReserved:null,permits:[],recovery:'read-failed'};
 if(!current)return v;
 if(p.settings?.brief_sha256===p.brief_sha256){
  for(const key of ['model_calls','rounds','search_calls','seconds','source_reads'])v.budgets[key]=finite(p.settings?.budgets?.[key]);
  v.researchAuthorized=typeof p.settings.execution_authorized==='boolean'?p.settings.execution_authorized:null;
 }
 v.monetaryCost=finite(p.monetary_cost);
 if(input.error){v.recovery=input.error==='credential-required'?'credential':input.error==='origin-or-host-rejected'?'origin':'read-failed';return v;}
 if(!bound)return v;
 v.provider=m.connected===true?'registered':m.connected===false?'absent':'unknown';
 v.authentication=m.native_authenticated===true?'verified':m.native_authenticated===false?'not-authenticated':'unknown';
 v.callsReserved=finite(m.calls_reserved);
 v.recovery=v.provider==='absent'?'provider':'permission';
 if(o?.project_ref===p.project_ref&&o.revision===p.revision&&Array.isArray(o.offers)){
  v.permits=o.offers.map(row=>{
   const expires=typeof row.expires_at==='string'&&/(Z|[+-]\d\d:\d\d)$/.test(row.expires_at)?Date.parse(row.expires_at):NaN;
   let reason='unknown';
   if(row.input_version!==p.input_version||row.brief_sha256!==p.brief_sha256)reason='stale';
   else if(!Number.isFinite(expires)||!Number.isFinite(now))reason='unknown-expiry';
   else if(expires<=now)reason='expired';
   else if(row.available!==true)reason=({
    'model-permit-call-budget-exhausted':'exhausted','model-provider-unconnected':'provider',
    'model-owner-unavailable':'provider','model-permit-expired':'expired'
   })[row.blocked_reason]||'refused';
   else if(!Number.isSafeInteger(row.max_calls)||row.max_calls<=0||!Number.isSafeInteger(row.max_seconds)||row.max_seconds<=0)reason='unknown';
   else if(v.provider!=='registered')reason='provider';
   else reason='confirmable';
   return {operation:reason!=='stale'&&typeof row.operation==='string'?row.operation:'Unknown',reason,
    expiresAt:Number.isFinite(expires)?new Date(expires).toISOString():null,
    maxCalls:finite(row.max_calls),maxSeconds:finite(row.max_seconds)};
  });
  v.permission=v.permits.some(row=>row.reason==='confirmable')?'confirmable':v.permits.length?'blocked':'none';
 }
 if(m.blocking_unknown_count>0){v.permission='held';v.recovery='unknown-write';}
 return v;
}

function connectionDiagnosticsHtml(v, locale) {
 const en=locale==='en',t=(zh,english)=>en?english:zh;
 const esc=value=>String(value??'Unknown').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const labels={
  unknown:t('未知；当前回应不足以核实','Unknown; current response cannot verify this'),
  absent:t('此项目尚未登记模型连接','No model connection registered for this project'),
  registered:t('此项目已登记模型连接；不代表已登录','Model connection registered; this does not establish login'),
  verified:t('当前服务明确报告已认证','Current service explicitly reports authentication'),
  'not-authenticated':t('当前服务明确报告未认证','Current service explicitly reports no authentication'),
  none:t('没有当前内容任务许可；需先确认范围与上限','No current content-task permission; confirm scope and limits first'),
  confirmable:t('当前内容任务可供确认；不是科研运行许可','Current content task may be confirmed; not research execution permission'),
  blocked:t('已保存许可当前不可用，见下方原因','Saved permission is not usable; see reasons below'),
  held:t('有结果未确认的写入；先恢复原回执','A write outcome is unknown; recover the original receipt first'),
  stale:t('项目输入已变化；需重新读取本版许可','Input changed; read permission for the current version'),
  expired:t('许可已到期；需原操作者重新确认，不能自动续期','Permission expired; original operator must reconfirm, never auto-renew'),
  'unknown-expiry':t('有效期无法核实；不能判为有效许可','Expiry cannot be verified; cannot report valid permission'),
  exhausted:t('调用上限已用完；不能自动追加','Call limit exhausted; never increase it automatically'),
  provider:t('模型连接未就绪；请由本机操作者检查启动配置','Model connection is unavailable; ask the local operator to check startup configuration'),
  refused:t('服务拒绝此许可；请查看原操作回执','Service refused this permission; inspect the original operation receipt')
 };
 const recovery={
  credential:t('从同一个 Wiki 普通首页重新打开，恢复只读会话；不要复制旧令牌。','Reopen the same ordinary Wiki homepage to restore the read session; do not copy old tokens.'),
  origin:t('回到原 Wiki 地址，勿混用端口、别名或 file://；保留同源检查。','Return to the original Wiki address; do not mix ports, aliases or file://; keep same-origin checks.'),
  'read-failed':t('当前项目回应缺失或不匹配。重新选择本课题并刷新；无法核实前不沿用旧课题状态。','Current project response is missing or mismatched. Select this topic and refresh; do not reuse the previous topic status.'),
  provider:labels.provider,
  permission:t('在本课题正常操作入口核对内容任务范围、上限与到期时间，再由本人明确确认。本面板只读，不执行或续期。','Review this topic’s content-task scope, limits and expiry in the normal action entry, then explicitly confirm. This panel only reads; it never executes or renews.'),
  'unknown-write':t('保留原操作 key，在原操作面板读取回执或恢复。不要换 key 重投，也不要因刷新而再次执行。','Keep the original operation key and read or recover its receipt in the original action panel. Do not change keys or re-execute on refresh.')
 };
 const row=(name,value)=>`<tr><th scope="row">${esc(name)}</th><td>${esc(value)}</td></tr>`;
 const auth=v.authentication==='unknown'?t('无法核实登录状态；不会从连接登记或历史任务推断','Login cannot be verified; never infer it from registration or historical jobs'):labels[v.authentication];
 const limits=Object.entries(v.budgets).map(([key,value])=>`${key}: ${value??'Unknown'}`).join(' · ')||'Unknown';
 return `<section class="hs-panel live-files" data-connection-diagnostics><h2>${t('连接、许可与恢复','Connection, permission and recovery')}</h2><table class="live-table"><tbody>${
  row(t('当前课题','Current topic'),v.topic)+row(t('项目 / 整数输入版本','Project / integer input version'),`${v.project??'Unknown'} / ${v.inputVersion??'Unknown'}`)+
  row(t('模型连接登记','Model connection registration'),labels[v.provider])+row(t('登录核验','Authentication evidence'),auth)+
  row(t('内容任务许可','Content-task permission'),labels[v.permission])+row(t('科研运行许可','Research execution permission'),v.researchAuthorized===false?t('未授权','Not authorized'):t('不能由本诊断判定有效科研许可','This diagnostic cannot attest effective research permission'))+
  row(t('项目资源上限（不是金额）','Project resource limits (not money)'),limits)+row(t('已预留模型调用','Reserved model calls'),v.callsReserved)+
  row(t('已报告金额（不是费用上限）','Reported cost (not a spending cap)'),v.monetaryCost)+row(t('货币上限','Monetary cap'),t('Unknown；当前接口未提供','Unknown; not provided by the current contract'))
 }</tbody></table>${v.permits.length?`<h3>${t('逐项许可','Individual permissions')}</h3><ul>${v.permits.map(p=>`<li>${esc(p.operation)} — ${esc(labels[p.reason])}; ${t('到期','Expires')}: ${esc(p.expiresAt)}; ${t('调用 / 秒上限','Call / second limits')}: ${esc(p.maxCalls)} / ${esc(p.maxSeconds)}</li>`).join('')}</ul>`:''}<h3>${t('如何恢复','Recovery')}</h3><p>${esc(recovery[v.recovery])}</p><p>${t('此处仅呈现已有记录，不探测登录、不读取个人会话库、不调用模型或检索。许可仍由正常产品入口核验。','Only existing records are presented: no login probe, personal-session access, model call or search. The normal product entry still validates permission.')}</p></section>`;
}

// Explanation only; action eligibility and raw saved observations stay unchanged.
const savedQueryRefusalFeedback=liveFeedback;
liveFeedback=function(app){
 const html=savedQueryRefusalFeedback(app),p=rt.overview?.project,q=rt.overview?.stage1?.query_execution;
 if(!liveReal()||app.stage!==1||!rt.ref||p?.project_ref!==rt.ref||q?.status!=='unavailable-or-stale'||typeof q.refusal!=='string'||!q.refusal)return html;
 const messages={
  'project-query-snapshot-semantics-differ':['保存输入与当前配置不一致；具体差异需核对原始记录。','Saved inputs differ from the current configuration; inspect the original record for the specific difference.','保存輸入與目前設定不一致；具體差異須核對原始記錄。'],
  'project-query-bootstrap-binding-differs':['执行版本或来源绑定不一致。','The execution version or source binding differs.','執行版本或來源綁定不一致。'],
  'project-query-seal-expired':['许可已过期。','The permit has expired.','許可已過期。']
 };
 const reason=messages[q.refusal]||['校验未通过；请核对下方原始拒绝记录。','Validation did not pass; inspect the original refusal below.','驗證未通過；請核對下方原始拒絕記錄。'];
 const explanation=`<div class="live-callout" data-v7-query-refusal role="status"><strong>${rl('执行请求被拒绝','Execution request refused','執行請求被拒絕')}</strong><p>${rl(...reason)}</p><p><small>${rl('原始拒绝','Original refusal','原始拒絕')}: <code>${rx(q.refusal)}</code></small></p><p>${rl('旧记录、Unknown 和预算保持不变。是否能接续尚未验证，不会自动重发。原始拒绝保留在下方记录中。','Existing records, Unknown outcomes and budgets remain unchanged. Continuation has not been verified; no request is resent automatically. The original refusal remains in the records below.','舊記錄、Unknown 與預算保持不變。是否能接續尚未驗證，不會自動重發。原始拒絕保留在下方記錄中。')}</p></div>`;
 return html.replace('<div class="rf-body">','<div class="rf-body">'+explanation);
};

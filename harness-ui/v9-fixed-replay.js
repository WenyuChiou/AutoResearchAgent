// Explicit ordinary action; use the existing pending-key/receipt recovery path.
const fixedReplayFeedback = liveFeedback;
liveFeedback = function(app) {
 const original = fixedReplayFeedback(app), stage = rt.overview?.stage1;
 if(app.stage !== 1 || stage?.fixed_replay?.mode !== 'fixed-offline-engineering') return original;
 const query = (stage.queries || []).find(q => q.execution_available === true);
 const complete = stage.fixed_replay.planned_queries > 0 && stage.fixed_replay.completed_queries === stage.fixed_replay.planned_queries;
 return original + `<section class="hs-panel" data-fixed-replay><h3>${rl('固定离线工程回放','Fixed offline engineering replay')}</h3><p>${rl('只回放启动时固定的响应字节；不联网、不调用模型，不代表已阅读或覆盖通过。','Replays pinned response bytes only. No network/model call, reading or coverage acceptance.')}</p><p>${rx(stage.fixed_replay.reason || (query ? query.purpose + ': ' + query.query : (complete ? 'fixed-query-replay-complete; reading and coverage remain separate' : 'fixed-query-replay-held-or-incomplete')))}</p><button class="hs-button" data-fixed-replay-next ${query ? liveDisabled() : 'disabled'}>${rl('回放下一条固定查询','Replay next fixed query')}</button></section>`;
};
document.addEventListener('click', async e => {
 if(!e.target.closest('[data-fixed-replay-next]')) return;
 e.preventDefault();
 const stage = rt.overview?.stage1, query = stage?.queries?.find(q => q.execution_available === true);
 if(stage?.fixed_replay?.mode !== 'fixed-offline-engineering' || !query) return;
 await livePost('stage1/execute-query', {...liveBound(), confirmed:true,
   ledger_state_sha256:stage.ledger.state_sha256, query_ref:query.query_ref, query_sha256:query.query_sha256});
});

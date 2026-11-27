// Display only. Callers supply project-bound, persisted records from the Host.
const wikiRecordMissing = '这一段还没有运行，没有记录。';
const wikiRecordNumber = value => Number.isSafeInteger(value) && value >= 0;

function wikiRecordSummary(record) {
 const parts = [];
 if (wikiRecordNumber(record?.recordCount)) parts.push(record.recordCount + ' 条记录');
 if (wikiRecordNumber(record?.blockedCount)) parts.push('拦下 ' + record.blockedCount + ' 次');
 return parts.join(' · ') || wikiRecordMissing;
}

function wikiHarnessRecord(record) {
 const checks = (record?.checks || []).filter(row => row?.name && row.result && row.raw != null);
 const timeline = (record?.timeline || []).filter(row => row?.step && row.raw != null);
 const blocked = [
  ['failedCheck', '没通过的检查'], ['wrongProject', '错项目'], ['staleVersion', '旧版本'],
  ['duplicate', '重复点击'], ['overLimit', '超额度']
 ];
 const resume = record?.resume;
 const recordedBlocks = blocked.some(([key]) => wikiRecordNumber(record?.blocked?.[key]));
 const summary = typeof record?.summary === 'string' && record.summary ? record.summary : wikiRecordSummary(record);
 const raw = value => `<details><summary>看原始记录</summary><pre>${esc(JSON.stringify(value, null, 2))}</pre></details>`;
 const table = (headers, rows) => `<table><thead><tr>${headers.map(name => `<th scope="col">${name}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`;
 const missing = record?.summary ? '<p class="wiki-record-gap">这份交付没有保存这一项。</p>' : `<p>${wikiRecordMissing}</p>`;
 const chip = '<strong class="wiki-record-chip">Harness 记录</strong>';
 const chips = (record?.chips || []).map(([text, warn]) => `<span class="wiki-record-count${warn ? ' warn' : ''}">${esc(text)}</span>`).join('');
 if (summary === wikiRecordMissing && !checks.length && !timeline.length && !recordedBlocks && resume?.raw == null) {
  return `<div class="wiki-record" data-wiki-record>${chip}<span>${wikiRecordMissing}</span></div>`;
 }
 return `<details class="wiki-record" data-wiki-record>
  <summary>${chip}<span>${summary === wikiRecordMissing ? '有已保存的明细' : summary}</span>${chips ? `<span class="wiki-record-counts">${chips}</span>` : ''}<span class="wiki-record-expand">展开明细</span><span class="wiki-record-collapse">收起明细</span></summary>
  <div class="wiki-record-body">
   <p>这里只说做了哪些检查，不代表研究结论是对的。</p>${record?.source ? `<p class="wiki-record-gap">${esc(record.source)}</p>` : ''}
   <h3>这一段查了什么、留了什么</h3>
   ${checks.length ? table(['事项', '结果', '原始记录'], checks.map(row => `<tr><th scope="row">${esc(row.name)}</th><td>${esc(row.result)}</td><td>${raw(row.raw)}</td></tr>`)) : missing}
   <h3>被拦下的事</h3>
   ${recordedBlocks ? table(['事项', '结果'], blocked.map(([key, label]) => {
    const count = record.blocked[key];
    return `<tr><th scope="row">${label}</th><td>${count === 0 ? '0 次 · 没有发生' : wikiRecordNumber(count) ? count + ' 次' : '未提供'}</td></tr>`;
   })) : missing}
   <h3>关掉重开</h3>
   ${resume?.raw != null ? `<p>${esc(resume.result || '未提供')}${wikiRecordNumber(resume.newJobs) ? ' · 新增作业 ' + resume.newJobs + ' 个' : ''}</p>${raw(resume.raw)}` : missing}
   <h3>运行过程</h3>
   ${timeline.length ? table(['步骤', '开始–结束', '模型调用', '花费', '发生了什么', '原始记录'], timeline.map(row => `<tr><th scope="row">${esc(row.step)}</th><td>${esc(row.time || '未提供')}</td><td>${wikiRecordNumber(row.modelCalls) ? row.modelCalls : '未提供'}</td><td>${esc(row.cost ?? '未提供')}</td><td>${esc(row.result || '未提供')}</td><td>${raw(row.raw)}</td></tr>`)) : missing}
  </div>
 </details>`;
}
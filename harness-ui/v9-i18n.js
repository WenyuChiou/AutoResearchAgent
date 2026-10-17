// UI-only translations. Artifact text, identifiers and saved bytes stay verbatim.
const n9UiLabels = {
 '问题':['问题','Question','問題'], '方法':['方法','Method','方法'],
 '价值':['价值','Value','價值'], '限制':['限制','Limits','限制'],
 '建议理由':['建议理由','Recommendation rationale','建議理由'],
 '用途':['用途','Role','用途'], '原卡说明与限制':['原卡说明与限制','Source-card notes and limits','原卡說明與限制'],
 '方法与样本':['方法与样本','Method and sample','方法與樣本'], '作者':['作者','Authors','作者'],
 'Unknown':['未提供','Unknown','未提供'], 'unknown':['未知','Unknown','未知'],
 'registered':['已登记','Registered','已登記'], 'verified-saved-package':['已核验保存交付','Verified saved delivery','已核驗保存交付'],
 'validated-stage2-packet':['已校验Stage2材料','Validated Stage2 input','已校驗Stage2材料'],
 'prepared':['接续快照已保存','Workflow prepared','接續快照已保存'],
 'local-only':['已保存本地草稿','Local draft saved','已保存本機草稿'],
 'unsaved-local-only':['本地草稿未保存','Local draft not saved','本機草稿未保存'],
 'not-saved':['未保存','Not saved','未保存'],
 'cleared-local-only':['本地草稿已清除','Local draft cleared','本機草稿已清除'],
 'storage-error-local-only':['本地保存失败','Local storage failed','本機保存失敗'],
 'full-text':['全文','Full text','全文'], 'partial-text':['部分正文','Partial text','部分內文'],
 'abstract-only':['仅摘要','Abstract only','僅摘要'],
 'metadata-only':['仅书目','Metadata only','僅書目']
};
function n9UiLabel(value){return n9UiLabels[value]?rl(...n9UiLabels[value]):value;}
function n9Message(value){return typeof value==='function'?value():value;}
function n9OriginalNotice(){return `<p class="n2-hint n9-original-language" role="note">${rl('路线译文随界面语言切换，仅用于阅读；可展开交付原文核对。论文标题、直接引文和自填笔记保留原语言；缺少译文的字段会明确标注。','Route translations follow the selected language for reading. Expand the delivery original to verify. Paper titles, direct quotations and your notes retain their original language; unavailable translations are labeled.','路線譯文隨介面語言切換，僅供閱讀；可展開交付原文核對。論文標題、直接引文及自填筆記保留原語言；缺少譯文的欄位會明確標註。')}</p>`;}

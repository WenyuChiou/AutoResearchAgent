// Display-only, exact-source translations. No model call, artifact mutation or authority.
function n9PacketIdentity(){return typeof p9!=='undefined'&&p9.shown?p9.shown.view.packet_file_sha256:n2.meta?.packet_json_sha256;}
function n9RouteValue(route,path){return path.split('.').reduce((v,k)=>v&&Object.hasOwn(v,k)?v[k]:undefined,route);}
function n9RouteTranslation(route,path){
 const original=n9RouteValue(route,path),locale=apps[0]?.lang||'zh';
 const packet=n9TranslationBundle.packets.find(p=>p.packet_file_sha256===n9PacketIdentity());
 const entry=packet?.fields.find(f=>f.candidate_id===route.candidate.candidate_id&&f.version===route.candidate.version&&f.path===path);
 if(entry&&n2Same(entry.source,original)&&Object.hasOwn(entry.translations,locale))
  return {value:entry.translations[locale],original,available:true,translated:!n2Same(entry.translations[locale],original)};
 return {value:original,original,available:false,translated:false};
}
function n9RoutePreview(route,path,limit){const t=n9RouteTranslation(route,path);return n2Short(Array.isArray(t.value)?t.value.join('；'):t.value,limit);}
function n9RouteText(route,path,limit=160){
 const t=n9RouteTranslation(route,path);
 if(t.original===null||t.original===undefined||t.original==='')return `<span class="n9-missing">${n9Missing()}</span>`;
 const text=Array.isArray(t.value)?t.value.join('\n'):String(t.value);
 const detail=text.length>limit?`<details class="n2-long"><summary>${rx(n2Short(text,limit))}</summary><div class="n2-original">${rx(text)}</div></details>`:`<div class="n2-original">${rx(text)}</div>`;
 const original=t.translated?`<details class="n9-route-original"><summary>${rl('查看交付原文','View delivery original','查看交付原文')}</summary><div class="n2-original">${rx(Array.isArray(t.original)?t.original.join('\n'):t.original)}</div></details>`:'';
 const missing=!t.available?`<small class="n9-missing">${rl('此字段译文未提供，显示原文','Translation unavailable for this field; showing original','此欄位譯文未提供，顯示原文')}</small>`:'';
 return `<div class="n9-route-content" data-route-field="${rx(path)}">${detail}${original}${missing}</div>`;
}
const n9CheckNames={answerability:['可回答性','Answerability','可回答性'],execution:['执行条件','Execution','執行條件'],materials:['材料条件','Materials','材料條件'],opportunity:['研究缺口','Research opportunity','研究缺口'],value:['研究价值','Research value','研究價值']};
function n9Check(route,key){const check=route.assessment?.checks?.[key];if(!check)return n9Missing();return `<strong>${check.status==='assessed'?rl('已有评估','Assessed','已有評估'):n9UiLabel(check.status)}</strong><p>${rl('阻挡','Blocking','阻擋')}: ${check.blocking===true?rl('是','Yes','是'):check.blocking===false?rl('否','No','否'):n9Missing()}</p>${n9RouteText(route,'assessment.checks.'+key+'.rationale',220)}${check.next_check?`<b>${rl('待核实的下一步','Next verification','待核實的下一步')}</b>${n9RouteText(route,'assessment.checks.'+key+'.next_check',220)}`:''}`;}
function n9RouteDetails(route){return `<details class="n2-secondary"><summary>${rl('下一步与完整检查','Next step & full checks','下一步與完整檢查')}</summary><h4>${rl('研究机会','Research opportunity','研究機會')}</h4>${n9RouteText(route,'candidate.opportunity',260)}<h4>${rl('所需材料与工具','Required data & tools','所需材料與工具')}</h4>${n9RouteText(route,'candidate.requirements',260)}<h4>${rl('下一步','Next step','下一步')}</h4>${n9RouteText(route,'assessment.next_step',260)}${Object.keys(route.assessment?.checks||{}).map(key=>`<details><summary>${n9CheckNames[key]?rl(...n9CheckNames[key]):rx(key)}</summary>${n9Check(route,key)}</details>`).join('')}${n2Record(rl('完整检查原文','Original full assessment','完整檢查原文'),route.assessment)}</details>`;}
const n9OriginalGap=n2Gap;
n2Gap=function(routes){return `<details class="n2-secondary"><summary>${rl('Gap、执行条件与缺失项','Gaps, execution conditions & missing items','Gap、執行條件與缺失項')}</summary>${n2Table(routes.map(route=>({id:route.candidate.candidate_id,title:n9RouteName(route.candidate.candidate_id),route})),Object.keys(n9CheckNames).map(key=>({label:rl(...n9CheckNames[key]),cell:o=>n9Check(o.route,key)})))}<details><summary>${rl('原始Gap、全包事项与资料补件','Original gaps, packet-wide issues & addendum','原始Gap、全包事項與資料補件')}</summary>${n9OriginalGap(routes)}</details></details>`;};

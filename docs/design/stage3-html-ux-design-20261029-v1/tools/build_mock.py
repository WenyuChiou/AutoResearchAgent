"""Generate static documents from one canonical synthetic saved view per case."""
import hashlib
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPY = json.loads((ROOT / "copy.json").read_text(encoding="utf-8"))
LOCALES = COPY["locales"]
OUT = ROOT / "blocks"
OUT.mkdir(exist_ok=True)


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def text(value):
    if value is None:
        return "null / unknown"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return "\n".join(text(v) for v in value) if value else "[]"
    if isinstance(value, dict):
        return value.get("text") or json.dumps(value, ensure_ascii=False)
    return str(value)


def esc(value):
    return html.escape(text(value))


def label(key, locale):
    return COPY["labels"][key][locale]


def ui(key, locale):
    return label("field_" + key, locale)


def block(identity, title, paragraphs, region="main"):
    return {"id": identity, "title": title, "paragraphs": [text(p) for p in paragraphs], "region": region}


def explicit_edges(view):
    plan = view.get("plan") or {}
    designs = {r["design_id"] for r in plan.get("designs", [])}
    analyses = {r["analysis_id"] for r in plan.get("analyses", [])}
    results = {r["result_id"] for r in plan.get("results", [])}
    edges = set()
    for row in plan.get("question_plans", []):
        for identity in row.get("design_ids", []):
            if identity in designs:
                edges.add((row["question_ref"], identity))
    for row in plan.get("analyses", []):
        for identity in row.get("design_ids", []):
            if identity in designs:
                edges.add((identity, row["analysis_id"]))
    for row in plan.get("results", []):
        for identity in row.get("analysis_ids", []):
            if identity in analyses:
                edges.add((identity, row["result_id"]))
    return sorted(edges)


def scientific_blocks(case, locale):
    view = case["view"]
    plan = view.get("plan") or {}
    context = view.get("direction_context") or {}
    questions = context.get("questions") or plan.get("questions", [])
    argument = next(iter(context.get("preferred_options", [])), {}).get("candidate", {}).get("scientific_argument", {})
    blocks = [block("overview", label("overview", locale), [
        ui("candidate", locale) + ": " + "; ".join(sorted({q["candidate_id"] + "@" + str(q["candidate_version"]) for q in questions})),
        ui("motivation", locale) + ": " + text(argument.get("motivation")),
        ui("current_state", locale) + ": " + text(argument.get("current_state")),
        ui("gap", locale) + ": " + ("\n".join(r.get("statement", text(r)) for r in argument.get("gaps", [])) or label("missing", locale)) + " / " + text(argument.get("contribution_claims")),
        label("source", locale),
    ], "full")]
    for q in questions:
        p = next((x for x in plan.get("question_plans", []) if x["question_ref"] == q["question_ref"]), {})
        paragraphs = [q["question_ref"], q["text"], ui("claim", locale) + ": " + text(q.get("intended_claim"))]
        if view.get("planning_mode") == "direction-intent":
            for key, title in [("materials", "materials"), ("method", "method"), ("design", "method"), ("validation", "validation"), ("analysis", "validation"), ("interpretation", "interpret"), ("minimum_deliverable", "resume")]:
                paragraphs.append(label(title, locale) + "：" + text(p.get(key)))
        else:
            for key in ["evidence_needed", "measurement", "claim_boundary", "design_ids", "analysis_ids", "result_ids", "blockers", "minimum_deliverable"]:
                paragraphs.append(ui(key, locale) + ": " + text(p.get(key)))
            paragraphs.extend(ui("resource_uses", locale) + ": " + text(u.get("purpose")) + "; " + ui("fit_basis", locale) + ": " + text(u.get("fit_rationale")) + " (" + text(u.get("status")) + ")" for u in p.get("resource_uses", []))
        blocks.append(block("sq-" + q["question_id"], label("sq", locale) + " · " + q["question_id"], paragraphs))
    edges = explicit_edges(view)
    blocks.append(block("figures", label("graph", locale), [label("graph_note", locale) if edges else label("no_graph", locale), label("future", locale)]))
    for design in plan.get("designs", []):
        blocks.append(block(design["design_id"], label("shared", locale) + " · " + design["design_id"], [
            ui("questions", locale) + ": " + text(design["question_refs"]), ui("procedure", locale) + ": " + text(design.get("procedure")),
            ui("comparisons", locale) + ": " + text(design.get("comparisons", {}).get("description")) + "; " + text(design.get("comparisons", {}).get("reason")), ui("checks", locale) + ": " + text(design.get("credibility_checks")),
            ui("stop", locale) + ": " + text(design.get("failure_conditions")) + " / " + text(design.get("stop_conditions")),
        ]))
    for analysis in plan.get("analyses", []):
        blocks.append(block(analysis["analysis_id"], label("validation", locale) + " · " + analysis["analysis_id"], [
            text(analysis.get(k)) for k in ["question_refs", "design_ids", "method", "criteria", "uncertainty", "limitations"]]))
    for result in plan.get("results", []):
        blocks.append(block(result["result_id"], label("interpret", locale) + " · " + result["result_id"], [
            text(result.get(k)) for k in ["question_refs", "analysis_ids", "artifact", "status", "observed_value"]] + [
                ui(key, locale) + ": " + text(result.get("interpretation", {}).get(key)) for key in ["supports","contradicts","inconclusive"]]))
    unknown = []
    for row in plan.get("unknowns", []):
        unknown.extend([row["unknown_id"] + ": " + row["description"], ui("questions",locale) + ": " + text(row["question_refs"]),
                        ui("deadline",locale) + ": " + text(row.get("resolve_before")), ui("owner",locale) + ": " + text(row.get("owner")),
                        ui("evidence_trigger",locale) + ": " + text(row.get("resolution_evidence_needed")) + " / " + text(row.get("recheck_trigger")),
                        ui("fallback",locale) + ": " + text(row.get("fallback"))])
    for row in plan.get("question_plans", []):
        for value in row.get("unknowns", []):
            unknown.append(row["question_ref"] + "：" + text(value))
    for key in ["source_unresolved", "conditions", "unresolved", "pending_scope_questions", "missing_mapping"]:
        if key in context:
            unknown.append(ui(key,locale) + ": " + text(context[key]))
    blocks.append(block("unknowns", label("unknown", locale), unknown or [label("missing", locale)], "side"))
    resources = plan.get("resources", [])
    resource_text = [ui("resource_rule",locale), label("file", locale) + ": null / unknown", label("rights", locale) + ": " + label("permission_unknown", locale)]
    if resources:
        for r in resources:
            resource_text.extend([ui("origin",locale)+": "+text(r.get("origin")), ui("availability",locale)+": "+text(r.get("availability")), ui("access_conditions",locale)+": "+text(r.get("access_conditions")), ui("fitness",locale)+": "+text(r.get("fitness")), ui("scale",locale)+": "+text(r.get("minimum"))+" / "+text(r.get("standard")), ui("scale_basis",locale)+": "+text(r.get("scale_basis"))])
    else:
        grouped = {}
        for card in context.get("preferred_cards", []):
            for sq in card.get("scientific_questions", []):
                for use in sq.get("resource_uses", []):
                    r=use.get("resource") or {}; ref=use.get("resource_ref") or {}
                    identity = ref.get("resource_id") or r.get("resource_id")
                    group = grouped.setdefault(identity, {"resource":r,"uses":[]})
                    group["uses"].append((sq.get("question",{}).get("question_id"),ref))
        for identity, group in grouped.items():
            r=group["resource"]
            resource_text.extend([ui("entry",locale)+": "+str(identity)+" · "+text(r.get("name"))+"; "+ui("url",locale)+": "+text(r.get("url")), label("file",locale)+": "+text(r.get("file_acquired")),label("rights",locale)+": "+text(r.get("use_permission"))])
            for question_id,ref in group["uses"]:
                resource_text.append(str(question_id)+" · "+ui("resource_uses",locale)+": "+text(ref.get("purpose"))+"; "+ui("fitness",locale)+": "+text(ref.get("fit_status")))
    blocks.append(block("resources", label("materials", locale), resource_text, "side"))
    blocks.append(block("reviews", label("review", locale), [label("assessment", locale), ui("review_missing",locale)], "side"))
    blocks.append(block("resume", label("resume", locale), [label("repro", locale)] + [ui("milestone",locale)+": "+text(m.get("description"))+"; "+ui("deliverable",locale)+": "+text(m.get("deliverable"))+"; "+ui("duration",locale)+": "+text(m.get("duration_basis")) for m in plan.get("milestones", [])], "side"))
    return blocks, edges


def graph_svg(view, edges):
    if not edges:
        return ""
    plan = view["plan"]
    columns = [[q["question_ref"] for q in plan.get("questions", [])], [r["design_id"] for r in plan.get("designs", [])], [r["analysis_id"] for r in plan.get("analyses", [])], [r["result_id"] for r in plan.get("results", [])]]
    positions = {identity: (20 + col * 200, 40 + i * 90) for col, identities in enumerate(columns) for i, identity in enumerate(identities)}
    lines = []
    for a, b in edges:
        x, y = positions[a]; xx, yy = positions[b]
        lines.append(f'<path d="M{x+155},{y+25} L{xx},{yy+25}" stroke="#226b80" stroke-width="2" fill="none" marker-end="url(#arrow)"/>')
    for identity, (x, y) in positions.items():
        display = identity.split("/")[-1]
        lines.append(f'<rect x="{x}" y="{y}" width="155" height="50" rx="8" fill="#edf3f7" stroke="#226b80"/><text x="{x+8}" y="{y+31}" font-size="16" fill="#143f6b">{html.escape(display)}</text>')
    return '<div class="scroll"><svg class="graph" viewBox="0 0 800 240" width="800" height="240" role="img" aria-labelledby="f03-title"><title id="f03-title">F03 静态明确引用示意；完整原文和边对照保留在表中</title><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="8" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#226b80"/></marker></defs>'+''.join(lines)+'</svg></div>'


def card(b, extra=""):
    return '<section class="card" id="'+html.escape(b["id"])+ '"><h2>'+esc(b["title"])+ '</h2>'+''.join('<p class="source-text" lang="zh-CN">'+esc(p)+'</p>' for p in b["paragraphs"])+extra+'</section>'


def page(case, locale, blocks, edges, stage2=False):
    meta, view = case["mock_meta"], case["view"]
    prefix = "stage2-" if stage2 else "mock-"
    languages = ' '.join('<a href="'+prefix+meta["id"]+'.'+l+'.html#research">'+html.escape(l)+'</a>' for l in LOCALES)
    top = '<a class="skip" href="#research">'+esc(label("skip",locale))+'</a><div class="frame"><header class="top"><a href="design.html">Design v1 · '+('Stage 2' if stage2 else 'Stage 3')+'</a><nav aria-label="Language">'+languages+'</nav></header>'
    title = ui("stage2_title",locale) if stage2 else label("title",locale)
    primary = label("save_start", locale) if stage2 else label("primary", locale)
    hero = '<section class="banner"><div class="eyebrow">'+esc(label("mock",locale))+'</div><p class="eyebrow">'+esc(title)+'</p><h1 lang="zh-CN">'+esc(meta["title"])+'</h1><p class="meta" style="color:white">'+esc(view["project_ref"]+' · '+meta["view_version"]+' · base57ae0509')+'</p><span class="tag light">'+esc(label("saved",locale))+'</span><span class="tag">'+esc(label("pending",locale))+'</span><span class="tag">'+esc(label("notrun",locale))+'</span><p>'+esc(label("boundary",locale))+'</p><button class="primary" disabled>'+esc(primary)+'</button><p class="action-note">'+esc(label("demo_actions",locale))+'</p></section>'
    nav = '<nav class="localnav">'+''.join('<a href="#'+key+'">'+esc(label(l,locale))+'</a>' for key,l in [("overview","overview"),("sq-SQ-01","sq"),("figures","graph"),("unknowns","unknown"),("resume","resume")])+'</nav>'
    if stage2:
        content = '<main id="research"><section class="card"><h2>'+esc(ui("comparison",locale))+'</h2><p>'+esc(meta["title"])+'</p><p>'+esc(ui("comparison_missing",locale))+'</p><div class="pair"><div class="placeholder">'+esc(meta["research_type"])+'<p>'+esc(ui("source_review",locale))+'</p></div><div class="placeholder">'+esc(ui("other_candidate",locale))+'</div></div></section>'+''.join(card(b) for b in blocks if b["id"] in ["overview","resources","unknowns"])+ '<section class="card"><h2>'+esc(ui("save_intent",locale))+'</h2><p>'+esc(ui("selection_missing",locale))+'</p><button class="ghost" disabled>'+esc(label("save",locale))+'</button><p>'+esc(label("demo_actions",locale))+'</p><a href="mock-'+meta["id"]+'.'+locale+'.html">'+esc(ui("open_stage3",locale))+' →</a></section></main>'
    else:
        rendered = {}
        for b in blocks:
            extra = graph_svg(view, edges) + ('<table><tr><th>Explicit source</th><th>Explicit target</th></tr>'+''.join('<tr><td>'+esc(a)+'</td><td>'+esc(z)+'</td></tr>' for a,z in edges)+'</table>' if edges else '') if b["id"]=="figures" else ""
            if b["id"].startswith("sq-"):
                extra += '<nav class="localnav" aria-label="SQ language">'+''.join('<a data-preserve-sq="'+b["id"]+'" href="mock-'+meta["id"]+'.'+l+'.html#'+b["id"]+'">'+l+'</a>' for l in LOCALES)+'</nav>'
            rendered[b["id"]] = card(b, extra)
        content = '<main id="research">'+nav+''.join(rendered[b["id"]] for b in blocks if b["region"]=="full")+'<div class="main-layout"><div>'+''.join(rendered[b["id"]] for b in blocks if b["region"]=="main")+'</div><aside>'+''.join(rendered[b["id"]] for b in blocks if b["region"]=="side")+'</aside></div></main>'
    receipt = '<details><summary>'+esc(label("technical",locale))+'</summary><pre>'+html.escape(json.dumps(case,ensure_ascii=False,indent=2))+'</pre></details>'
    footer = '<footer><a href="'+('mock-' if stage2 else 'stage2-')+meta["id"]+'.'+locale+'.html">'+esc(label("back",locale))+'</a><p>Design walkthrough only · usability / accessibility / E2E / science: NOT_RUN</p></footer></div>'
    return '<!doctype html><html lang="'+locale+'"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Stage 3 design · '+esc(meta["title"])+'</title><link rel="stylesheet" href="mock.css"></head><body>'+top+hero+content+receipt+footer+'</body></html>'


def inline(line):
    out = html.escape(line)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    return re.sub(r"\[([^]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', out)


def markdown(md):
    output=[]; table=False
    for line in md.splitlines():
        if line.startswith("|"):
            if not table: output.append('<div class="tablewrap"><table>'); table=True
            cells=line.strip().strip("|").split("|")
            if all(re.fullmatch(r"[\s:-]+", c) for c in cells): continue
            output.append('<tr>'+''.join('<td>'+inline(c.strip())+'</td>' for c in cells)+'</tr>'); continue
        if table: output.append('</table></div>'); table=False
        if not line.strip(): continue
        match=re.match(r"^(#{1,3}) (.*)",line)
        output.append(f'<h{len(match[1])}>{inline(match[2])}</h{len(match[1])}>' if match else '<p>'+inline(line)+'</p>')
    if table: output.append('</table></div>')
    return ''.join(output)


def main():
    generated=[]
    for fixture in sorted((ROOT/'fixtures').glob('*.json')):
        case=read(str(fixture.relative_to(ROOT)))
        for locale in LOCALES:
            blocks,edges=scientific_blocks(case,locale)
            payload={"case":case["mock_meta"],"locale":locale,"labels":{k:label(k,locale) for k in COPY["labels"]},"source_fixture_sha256":hashlib.sha256(fixture.read_bytes()).hexdigest(),"blocks":blocks,"explicit_edges":edges}
            (OUT/(case["mock_meta"]["id"]+'.'+locale+'.json')).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            for stage2 in [False,True]:
                name=('stage2-' if stage2 else 'mock-')+case['mock_meta']['id']+'.'+locale+'.html'
                (ROOT/name).write_text(page(case,locale,blocks,edges,stage2),encoding='utf-8'); generated.append(name)
    states=read('state-matrix.json')['states']; mapping=read('source-map.json')['rows']
    def mdcell(value):
        return text(value).replace('|','\\|').replace('\n','<br>')
    state_md=['# 19种状态／互动矩阵','', '每一行是设计规格；mock不执行操作，产品行为 NOT_RUN。', '', '| 状态 | 当前主要任务 | 唯一主动作（简中／繁中／EN） | 行为与下一状态 | 保留／执行边界 |','|---|---|---|---|---|']
    for s in states:
        state_md.append('| '+' | '.join(mdcell(v) for v in [s['id'],s['primary_task'],' / '.join(s['primary_action'].values()),s['behavior']+' → '+s['next_state'],text(s['preserve'])+' / '+s['dispatch_boundary']])+' |')
    (ROOT/'STATES.md').write_text('\n'.join(state_md)+'\n',encoding='utf-8')
    source_md=['# 同版来源→画面元素对照','', '固定基线57ae0509；图、表、卡只读同一个saved view。下列为具体JSON pointer示例，不使用通配符；null表示基线缺件/future。', '', '| 类别／元素 | 原view JSON pointer | 显示条件 | 空值处置 |','|---|---|---|---|']
    for r in mapping:
        source_md.append('| '+' | '.join(mdcell(v) for v in [r['category']+' / '+r['element'],r['production_pointer'],r['display_condition'],r['empty_policy']])+' |')
    source_md+=['','版本标示：project/input_version/revision、candidate/version、原question_ref，以及已提供的plan/version或direction intent。完整hash没有提供就保持unknown，不补seal。','', '原字段来源/行号与版本规则见[source-map.json](source-map.json)，固定Git blob与原bytes hashes见[SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)。']
    (ROOT/'SOURCE_MAP.md').write_text('\n'.join(source_md)+'\n',encoding='utf-8')
    review=read('self-review.json')
    review_md=['# 一次设计 self-review','', '作者自查一次，不是独立code review、真人usability或科学评审。','', '| ID | finding | 设计修正／unknown | 对应位置／状态 | 剩余限制 |','|---|---|---|---|---|']
    for f in review['findings']:
        review_md.append('| '+' | '.join(mdcell(v) for v in [f['id'],f['finding'],f['resolution'],text(f['location'])+' / '+f['state'],f['remaining']])+' |')
    review_md+=['', 'NOT_RUN：'+', '.join(review['not_run']), '', '未造参与者、成功率、评分或费用；五项权限保持false。']
    (ROOT/'SELF_REVIEW.md').write_text('\n'.join(review_md)+'\n',encoding='utf-8')
    docs=markdown((ROOT/'DESIGN.md').read_text(encoding='utf-8'))
    docs+='<h2>19种状态／互动矩阵</h2><div class="tablewrap"><table><tr><th>状态</th><th>任务／唯一主动作</th><th>行为／之后状态</th><th>保留／边界</th></tr>'+''.join('<tr><td>'+esc(s['id'])+'</td><td>'+esc(s['primary_task'])+'<br>'+esc(s['primary_action']['zh-CN'])+'</td><td>'+esc(s['behavior'])+'<br>'+esc(s['next_state'])+'</td><td>'+esc(s['preserve'])+'<br>'+esc(s['proof_status'])+'</td></tr>' for s in states)+'</table></div>'
    docs+='<h2>36条同版来源→元素对照</h2><div class="tablewrap"><table><tr><th>类别／元素</th><th>JSON pointer（无*）</th><th>显示条件</th><th>空值／版本</th></tr>'+''.join('<tr><td>'+esc(r['category']+' / '+r['element'])+'</td><td><code>'+esc(r['production_pointer'])+'</code></td><td>'+esc(r['display_condition'])+'</td><td>'+esc(r['empty_policy'])+'<br>'+esc(r['version_label'])+'</td></tr>' for r in mapping)+'</table></div>'
    links='<p><a href="downloads/design-only.zip">下载完整离线包</a> · <a href="SELF_REVIEW.md">一次 self-review</a></p><p>'+ ' · '.join('<a href="'+n+'">'+html.escape(n)+'</a>' for n in generated)+'</p>'
    (ROOT/'design.html').write_text('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Stage 3 HTML UX 设计稿</title><link rel="stylesheet" href="mock.css"></head><body><main class="doc"><p class="note">静态设计稿 · 不接 backend · 所有案例合成 · 五项权限 false</p>'+links+docs+'</main></body></html>',encoding='utf-8')
    print(json.dumps({"mock_pages":len(generated),"locales":LOCALES,"states":len(states),"source_rows":len(mapping),"product_tests":"NOT_RUN"}))


if __name__=='__main__':
    main()

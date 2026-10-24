"""Fixed, script-free reader languages; saved research is never translated."""

from html import escape

from stage2_workflow.decision_card_views import render_decision_cards_html


PAGE_FILES = {
    "en": "index.html",
    "zh-Hant": "index.zh-Hant.html",
    "zh-Hans": "index.zh-Hans.html",
}
LANGUAGE_NAMES = {"en": "English", "zh-Hant": "繁體中文", "zh-Hans": "简体中文"}
UI_TEXT = {
    "en": {},
    "zh-Hant": {
        "Return to workspace": "返回工作台",
        "Full saved report": "完整保存報告（原文）",
        "Saved selection JSON": "保存的方向紀錄 JSON",
        "Package identity": "交付包來源與版本",
        "Independent Stage 2 report. This reading entry does not link the report to this project's Stage 1 run or record a research choice.": "獨立保存的 Stage 2 報告。此閱讀入口不建立與目前專案 Stage 1 的接續關係，也不登記研究選案。",
        "Directions:": "研究方向：",
        "recommended candidates:": "推薦候選：",
        "Reading only; no research or experiment is started here.": "此處僅供閱讀，不會啟動研究或實驗。",
        "Full saved report, review comments and limitations": "完整保存報告、評語與限制（原文）",
        "Source and version binding": "來源與版本紀錄",
        "Stage 2 decision cards": "Stage 2 方向決策卡",
        "Candidate question:": "候選方向問題：",
        "Research mode:": "研究模式：",
        "Scientific argument:": "科學論證狀態：",
        "Closest precedent": "最接近的前例",
        "Scientific questions": "科學問題",
        "Unassigned contribution claims": "尚未對應問題的貢獻主張",
        "Suggested approach": "建議方法",
        "Requirements": "所需條件",
        "Same-version resources not mapped to a question": "此版本尚未對應問題的資源",
        "Limitations": "限制",
        "Alternatives": "替代方案",
        "Next checks": "下一步查核",
        "Question ID": "問題識別碼",
        "Priority / status": "優先度／狀態",
        "Object": "研究對象",
        "Intended claim": "預期主張",
        "Resource mapping": "資源對應",
        "Contribution": "研究貢獻",
        "Mapped resources": "已對應的資源",
        "Resource ID": "資源識別碼",
        "Required": "是否必要",
        "Availability": "可用狀態",
        "Question fit": "問題適配狀態",
        "Question-specific purpose": "對此問題的用途",
        "Resource purpose": "資源用途",
        "Version": "版本",
        "Access conditions": "存取條件",
        "License": "授權依據",
        "Cost basis": "費用依據",
        "Checked at": "查核時間",
        "URL": "來源網址",
        "Question evidence IDs": "問題證據識別碼",
        "Resource evidence IDs": "資源證據識別碼",
        "Resource-ref source": "資源對應紀錄來源",
        "Resource source": "資源紀錄來源",
        "Status": "狀態",
        "Question IDs": "問題識別碼",
        "Role": "前例角色",
        "Established": "已知成果",
        "Overlap": "重疊之處",
        "Difference": "差異",
        "Evidence IDs": "證據識別碼",
        "Review status": "審查狀態",
        "Positioning": "前例定位",
        "None recorded": "未記錄",
        "None recorded.": "未記錄。",
        "None mapped for this candidate version.": "此候選版本尚未對應資源。",
        "Not recorded for this candidate version.": "此候選版本尚未記錄。",
        "No closest-work comparison recorded.": "尚未記錄最近前例的比較。",
        "No scientific questions are recorded for this candidate version.": "此候選版本尚未記錄科學問題。",
        "Mapped to this question. Mapping does not establish feasibility or availability.": "已對應至此問題；資源對應不代表已證實可行或可用。",
        "The mapping or a recorded resource status is unknown. This is not evidence that the resource does not exist.": "對應關係或資源狀態仍為 unknown；這不代表該資源不存在。",
        "No same-version resource is mapped to this question. This is not evidence that no data or resource exists.": "尚無同版本資源對應至此問題；這不代表沒有資料或資源。",
    },
    "zh-Hans": {
        "Return to workspace": "返回工作台",
        "Full saved report": "完整保存报告（原文）",
        "Saved selection JSON": "保存的方向记录 JSON",
        "Package identity": "交付包来源与版本",
        "Independent Stage 2 report. This reading entry does not link the report to this project's Stage 1 run or record a research choice.": "独立保存的 Stage 2 报告。此阅读入口不建立与当前项目 Stage 1 的接续关系，也不登记研究选案。",
        "Directions:": "研究方向：",
        "recommended candidates:": "推荐候选：",
        "Reading only; no research or experiment is started here.": "此处仅供阅读，不会启动研究或实验。",
        "Full saved report, review comments and limitations": "完整保存报告、评语与限制（原文）",
        "Source and version binding": "来源与版本记录",
        "Stage 2 decision cards": "Stage 2 方向决策卡",
        "Candidate question:": "候选方向问题：",
        "Research mode:": "研究模式：",
        "Scientific argument:": "科学论证状态：",
        "Closest precedent": "最接近的前例",
        "Scientific questions": "科学问题",
        "Unassigned contribution claims": "尚未对应问题的贡献主张",
        "Suggested approach": "建议方法",
        "Requirements": "所需条件",
        "Same-version resources not mapped to a question": "此版本尚未对应问题的资源",
        "Limitations": "限制",
        "Alternatives": "替代方案",
        "Next checks": "下一步查核",
        "Question ID": "问题标识码",
        "Priority / status": "优先度／状态",
        "Object": "研究对象",
        "Intended claim": "预期主张",
        "Resource mapping": "资源对应",
        "Contribution": "研究贡献",
        "Mapped resources": "已对应的资源",
        "Resource ID": "资源标识码",
        "Required": "是否必要",
        "Availability": "可用状态",
        "Question fit": "问题适配状态",
        "Question-specific purpose": "对此问题的用途",
        "Resource purpose": "资源用途",
        "Version": "版本",
        "Access conditions": "存取条件",
        "License": "授权依据",
        "Cost basis": "费用依据",
        "Checked at": "查核时间",
        "URL": "来源网址",
        "Question evidence IDs": "问题证据标识码",
        "Resource evidence IDs": "资源证据标识码",
        "Resource-ref source": "资源对应记录来源",
        "Resource source": "资源记录来源",
        "Status": "状态",
        "Question IDs": "问题标识码",
        "Role": "前例角色",
        "Established": "已知成果",
        "Overlap": "重叠之处",
        "Difference": "差异",
        "Evidence IDs": "证据标识码",
        "Review status": "审查状态",
        "Positioning": "前例定位",
        "None recorded": "未记录",
        "None recorded.": "未记录。",
        "None mapped for this candidate version.": "此候选版本尚未对应资源。",
        "Not recorded for this candidate version.": "此候选版本尚未记录。",
        "No closest-work comparison recorded.": "尚未记录最近前例的比较。",
        "No scientific questions are recorded for this candidate version.": "此候选版本尚未记录科学问题。",
        "Mapped to this question. Mapping does not establish feasibility or availability.": "已对应至此问题；资源对应不代表已证实可行或可用。",
        "The mapping or a recorded resource status is unknown. This is not evidence that the resource does not exist.": "对应关系或资源状态仍为 unknown；这不代表该资源不存在。",
        "No same-version resource is mapped to this question. This is not evidence that no data or resource exists.": "尚无同版本资源对应至此问题；这不代表没有数据或资源。",
    },
}
_INTRO = (
    "Independent Stage 2 report. This reading entry does not link the report "
    "to this project's Stage 1 run or record a research choice."
)


def reading_pages(label, binding, binding_raw, cards, saved_report):
    pages = {}
    for language, filename in PAGE_FILES.items():

        def text(value):
            return escape(UI_TEXT[language].get(value, value), quote=True)

        languages = " · ".join(
            f'<a href="{name}" hreflang="{lang}"'
            + (' aria-current="page"' if lang == language else "")
            + f">{LANGUAGE_NAMES[lang]}</a>"
            for lang, name in PAGE_FILES.items()
        )
        page = (
            f'<!doctype html><html lang="{language}"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{escape(label, quote=True)}</title>"
            '<link rel="stylesheet" href="/project-stage2-selection.css">'
            '<link rel="stylesheet" href="reading.css"></head><body><main>'
            '<nav class="stage2-reading-nav">'
            f'<a href="/projects.html#stage2-reading-language={language}">{text("Return to workspace")}</a> · '
            f'<a href="selection.md">{text("Full saved report")}</a> · '
            f'<a href="selection.json">{text("Saved selection JSON")}</a> · '
            f'<a href="binding.json">{text("Package identity")}</a></nav>'
            f'<nav class="stage2-reading-nav">{languages}</nav>'
            f'<h1 translate="no">{escape(label, quote=True)}</h1>'
            f"<p>{text(_INTRO)}</p>"
            f"<p>{text('Directions:')} {binding['direction_count']}; "
            f"{text('recommended candidates:')} {binding['recommendation_count']}. "
            f"{text('Reading only; no research or experiment is started here.')}</p>"
            + render_decision_cards_html(cards, ui_text=UI_TEXT[language])
            + f'<details><summary>{text("Full saved report, review comments and limitations")}</summary><pre translate="no">'
            + escape(saved_report.decode("utf-8"), quote=True)
            + f'</pre></details><details><summary>{text("Source and version binding")}</summary><pre translate="no">'
            + escape(binding_raw.decode("utf-8"), quote=True)
            + "</pre></details></main></body></html>"
        )
        pages[filename] = page.encode("utf-8")
    return pages

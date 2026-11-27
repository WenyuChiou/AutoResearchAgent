"""Play the U.S. household spending case study using Edtrace and the v57 manuscript.

Run this file with Python 3.11 or newer. The companion folders contain the
player runtime, the study figures, and the recorded prompt. Use --export-pages
to rebuild the GitHub Pages entry, --trace-only to record the talk, or
--no-browser to print the local player address.
"""

import argparse
from collections.abc import Sequence
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.parse import urlencode, urlsplit
import webbrowser

HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "runtime"
WHEEL = RUNTIME / "edtrace-0.1.25-py3-none-any.whl"
sys.path.insert(0, str(WHEEL))

from edtrace import plot, text

ENTRY = Path(__file__).stem
STUDY_TITLE = 'A Large Language Model Simulation of U.S. Household Spending under Population Aging and Gasoline Price Feedback'
PROMPT_PDF = "sources/recorded-spending-prompt.pdf"
TRACE_PATH = HERE / "var" / "traces" / f"{ENTRY}.json"
OBSERVED = "images/observed-bls.png"
WORKFLOW = "images/household-loop.png"
SQ1_COMPARISON = "images/sq1-quarterly-comparison.png"
AGING = "images/sq2-aging.png"
FEEDBACK = "images/sq3-feedback.png"

AGING_CHART = {
    "title": "U.S. residents aged 65+",
    "data": {"values": [{"year": "2004", "share": 12.4}, {"year": "2024", "share": 18.0}]},
    "width": 240,
    "height": 75,
    "encoding": {
        "y": {"field": "year", "type": "nominal", "sort": ["2004", "2024"], "title": None},
        "x": {
            "field": "share", "type": "quantitative", "title": "Percent of U.S. residents",
            "scale": {"domain": [0, 20]}, "axis": {"tickCount": 5},
        },
    },
    "mark": {"type": "bar", "color": "#087269"},
    "config": {"view": {"stroke": None}},
}

SQ1_SCORES = [
    [
        "Method",
        "Scaled error",
        "Correct quarterly direction"
    ],
    [
        "Gemma",
        "15.99%",
        "47 / 80"
    ],
    [
        "CPI basket",
        "15.99%",
        "48 / 80"
    ],
    [
        "Seasonal ridge",
        "12.36%",
        "50 / 80"
    ]
]
SQ2_SPENDING = [
    [
        "Increase in 65+ share",
        "Annual gap (USD per consumer unit)"
    ],
    [
        "+5 pp",
        "−$1,149"
    ],
    [
        "+10 pp",
        "−$2,297"
    ],
    [
        "+15 pp",
        "−$3,446"
    ]
]
AGE_MIX_CAPTION = (
    "Table 3. U.S. household spending in 2030 on the CBO central path. "
    "Amounts are in billions of nominal U.S. dollars. "
    "Parentheses show reductions from the fixed mix under the same gasoline price rule. Differences use unrounded values."
)
AGE_MIX_SPENDING = [
    ["Age mix", "65+ share", "No feedback", "With feedback", "Added reduction"],
    ["Fixed", "28.22%", "9,125.58", "9,125.58", "—"],
    ["+5 pp", "33.22%", "8,969.65 (155.92)", "8,966.06 (159.52)", "3.60"],
    ["+10 pp", "38.22%", "8,813.73 (311.84)", "8,803.89 (321.69)", "9.85"],
    ["+15 pp", "43.22%", "8,657.81 (467.76)", "8,638.12 (487.46)", "19.70"],
]


Cell = str | tuple[tuple[str, str], ...]


def table_cell(cell: Cell) -> str:
    if isinstance(cell, str):
        return escape(cell)
    return "<br>".join(f'<a href="{escape(url)}">{escape(label)}</a>' for label, url in cell)


def table(caption: str, rows: Sequence[Sequence[Cell]], *, compact: bool = False) -> str:
    wrapper_class = "table-wrap table-wrap-compact" if compact else "table-wrap"
    headings, *body = rows
    head = "".join(f'<th scope="col">{table_cell(cell)}</th>' for cell in headings)
    entries = "".join(
        f'<tr><th scope="row">{table_cell(label)}</th>'
        + "".join(f"<td>{table_cell(cell)}</td>" for cell in cells) + "</tr>"
        for label, *cells in body
    )
    return (
        f'<div class="{wrapper_class}"><table><caption>' + escape(caption) + '</caption>'
        + f"<thead><tr>{head}</tr></thead><tbody>{entries}</tbody></table></div>"
    )


DATA_ROLES = [
    ["Source", "What it provides"],
    [
        (
            (
                'U.S. Bureau of Labor Statistics (BLS), Consumer Expenditure Interview Survey, Public Use Microdata',
                'https://www.bls.gov/cex/pumd.htm',
            ),
        ),
        'Observed spending, age, region, income, and survey weights.',
    ],
    [
        (
            (
                'BLS, Consumer Price Index',
                'https://www.bls.gov/cpi/',
            ),
        ),
        'Historical price changes used to update spending baskets.',
    ],
    [
        (
            (
                'U.S. Congressional Budget Office, The Budget and Economic Outlook',
                'https://www.cbo.gov/publication/61882',
            ),
            (
                'Federal Reserve Bank of Philadelphia, Survey of Professional Forecasters',
                'https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/survey-of-professional-forecasters',
            ),
            (
                'BLS, Employment Cost Index',
                'https://www.bls.gov/eci/',
            ),
        ),
        'The central 2026–2030 price and income path, plus inputs for four alternatives.',
    ],
    [
        (
            (
                'U.S. Energy Information Administration (EIA), U.S. Gasoline and Diesel Retail Prices',
                'https://www.eia.gov/dnav/pet/pet_pri_gnd_dcus_nus_m.htm',
            ),
            (
                'EIA, Weekly Petroleum Status Report',
                'https://www.eia.gov/petroleum/supply/weekly/archive/',
            ),
            (
                'EIA, Short-Term Energy Outlook archives',
                'https://www.eia.gov/outlooks/steo/outlook.php',
            ),
        ),
        'Historical pump prices, inventories, and archived outlooks for checking the gasoline market model.',
    ],
    [
        (
            (
                'EIA, Annual Energy Outlook',
                'https://www.eia.gov/outlooks/aeo/',
            ),
            (
                'Federal Highway Administration (FHWA), Monthly Motor Fuel: Gasoline Volumes Distributed',
                'https://data.transportation.gov/d/5qxh-t94v',
            ),
        ),
        'The future gasoline reference path and fuel-volume weights for regional and seasonal calculations.',
    ],
]


def figure_caption(label: str, description: str) -> str:
    return f'<figcaption class="figure-caption"><strong>{escape(label)}</strong> {escape(description)}</figcaption>'


def study_figure(path: str, alt: str, label: str, description: str) -> str:
    image_path = escape(path)
    return (
        '<figure class="study-figure">'
        f'<a href="{image_path}" target="_blank" rel="noopener" title="Open the full-size figure">'
        f'<img src="{image_path}" alt="{escape(alt)}"></a>'
        f'{figure_caption(label, description)}</figure>'
    )


def spending_prompt_table() -> str:
    return f"""<div class="table-wrap">
<table>
<caption>Table S11. Recorded quarterly spending prompt (excerpt)</caption>
<thead><tr><th scope="col">Prompt block</th><th scope="col">What the model sees or returns</th></tr></thead>
<tbody>
<tr><th scope="row">Household profile</th><td><strong>2026 Q1</strong> under the CBO central path. <strong>South</strong>, reference age <strong>76</strong> at sampling, <strong>2</strong> people, <strong>0</strong> earners, <strong>owner with mortgage</strong>, <strong>4</strong> vehicles.</td></tr>
<tr><th scope="row">Prices and spending history</th><td>Income and price updates, the past four simulated quarters, and a price-adjusted reference for the same season. This household can spend up to <strong>$31,209</strong> this quarter.</td></tr>
<tr><th scope="row">Model output</th><td>Eight whole-number adjustments, one per spending category, from −100% to +150%. Their implied spending must stay within the limit.</td></tr>
</tbody>
</table>
</div>
<p><a href="{escape(PROMPT_PDF)}">Read the full recorded prompt in Table S11</a>.</p>"""


def workflow_cue(block: str, title: str = "", explanation: str = "") -> str:
    cue = f'<strong>{escape(title)}.</strong> {escape(explanation)}' if title else ""
    return f'<span class="workflow-step" data-block="{escape(block)}" hidden>{cue}</span>'


def workflow_figure() -> str:
    first_cue = workflow_cue(
        "households",
        "Set up households",
        "Start the 500 BLS profiles from their saved spending at the end of 2025.",
    )
    return (
        f'<figure class="workflow-figure" data-block="">{first_cue}'
        f'<a class="workflow-art" href="{WORKFLOW}" target="_blank" rel="noopener" '
        'title="Open the full-size workflow figure">'
        '<span class="workflow-focus" aria-hidden="true"></span></a>'
        '<div class="workflow-cue" aria-live="polite"></div>'
        + figure_caption(
            "Figure 1. Forward simulation, 2026–2030.",
            "The top return arrow carries spending into the next quarter. "
            "The dashed arrow shows the two-quarter delay in gasoline price feedback.",
        )
        + '</figure>'
    )


def show_aging_background() -> None:
    plot(AGING_CHART)
    text('<p class="figure-caption"><a href="https://www.census.gov/newsroom/press-releases/2025/older-adults-outnumber-children.html">Source: U.S. Census Bureau</a></p>')


def main() -> None:
    text('## 01 · Introduction')

    text('### 1.1 Why Population Aging Matters')
    text('- **An older population can change what households buy.** The U.S. share aged 65 or older rose from 12.4% in 2004 to 18.0% in 2024.')
    text('- **The shift matters for consumer demand.** Cravino et al. estimate that aging accounted for about one fifth of the rise in the U.S. spending share devoted to services from 1982 to 2016. [Cravino et al.](https://doi.org/10.1257/mac.20200371)')
    show_aging_background()  # @stepover

    text('### 1.2 Conventional Approaches')
    text('Researchers study spending under population aging using **demographic reweighting**, **demand systems**, and **life-cycle simulations**.')
    text('- **Demographic reweighting.** Combine spending by group with projected population shares. The U.S. Council of Economic Advisers used survey spending and Census projections to estimate future spending patterns. [CEA, 2013, Box 2-4](https://www.govinfo.gov/content/pkg/ERP-2013/html/ERP-2013-chapter2.htm)')
    text('- **Demand systems.** Estimate how households divide a budget across goods and services. Lührmann estimated demand across eight spending categories using West German household data. [Lührmann, 2005](https://www.mpisoc.mpg.de/fileadmin/user_upload/datapool/publications/gtyzs5eximf4u8v9_95-2005.pdf)')
    text('- **Life-cycle simulations.** Model how people spend and save at different ages. Faruqee used that approach to study how aging changes economy-wide spending and saving. [Faruqee, 2002](https://www.imf.org/en/publications/wp/issues/2016/12/30/population-aging-and-its-macroeconomic-implications-a-framework-for-analysis-15590)')
    text('A quarterly simulation needs a way to update spending as prices and budgets change. A **large language model (LLM)** can help make that choice from the information a household sees.')

    text('### 1.3 LLMs in Social and Economic Simulation')
    text('- **Agents can use past experience.** Park et al. gave agents a memory of past events to guide their choices in a simulated town. [Park et al., 2023](https://arxiv.org/abs/2304.03442)')
    text('- **Simulated choices can be checked against people.** Argyle et al. used demographic profiles to generate survey responses and compared them with observed responses. [Argyle et al., 2023](https://doi.org/10.1017/PAN.2023.2)')
    text('- **Household prediction and market feedback.** *HouseholdBench* tests predictions against observed household outcomes. [Huang et al., 2026](https://arxiv.org/abs/2610.07563) *EconAgent* uses demand and inventories to update prices. [Li et al., 2024, §2.3](https://aclanthology.org/2024.acl-long.829.pdf#page=3)')

    text('### 1.4 Research Gaps')
    text('- **Historical fit by age and region.** Quarterly spending levels and changes need to be checked by group. An error in one age group can carry into the national estimate as that group grows.')
    text('- **Aging under shared economic conditions.** Prices and incomes also change over time. When both age mixes face the same prices and income, the spending difference in the simulation comes from the change in the age mix.')
    text('- **The size of gasoline feedback.** Demand can affect later prices through inventories. A paired comparison is needed to measure how much this feedback changes the aging-related spending gap.')

    text('### 1.5 Scientific Questions')
    text('- **SQ1 · Historical spending.** Can the simulation reproduce typical spending and quarterly changes across U.S. regions and age groups?')
    text('- **SQ2 · Population aging.** How does a larger share of older households change spending along the same price and income path?')
    text('- **SQ3 · Gasoline price feedback.** How much does the aging-related spending gap change when gasoline prices respond to demand?')

    text('### 1.6 Study Goal')
    text('This study estimates how population aging could change U.S. household spending using a **large language model (LLM)**. Each agent represents a U.S. household and makes **quarterly spending choices**.')
    text('To build those households, we start with what U.S. households report spending.')

    text('## 02 · Data and Methods')

    text('### 2.1 Data Sources')
    text('Our historical benchmark comes from the U.S. Bureau of Labor Statistics (BLS). A **consumer unit** is a person who manages their own expenses or a group that shares major expenses. We measure spending in **dollars per consumer unit per quarter**. [BLS glossary](https://www.bls.gov/cex/csxgloss.htm)')
    text(table('Table 1. Data sources and their roles', DATA_ROLES))  # @stepover
    text(study_figure(OBSERVED, "Observed quarterly spending by region and age group", "Figure 2. Observed BLS benchmark.", "The lines show survey-weighted median spending by region from 2023 Q1 to 2025 Q2. Ages 45–54 are on the left and 65+ are on the right."))  # @stepover

    text('### 2.2 Study Setup')
    text("- **Historical sample.** Draw 25 profiles per group using BLS survey weights, for **200** in total. The groups span the Northeast, Midwest, South, and West and two age bands, 45–54 and 65+. Age refers to the survey's household reference person. The historical check uses **one set of LLM trajectories** for these profiles.")
    text('- **Starting point.** Each group starts from its 2019 Q4 BLS spending basket. Four warm-up quarters build a spending history.')
    text('- **Future scenarios.** A separate panel of **500 profiles** across four regions and six age groups starts from saved 2025 Q4 states.')
    text('- The **fixed age mix** keeps the first-half 2025 BLS survey weights. The **65+ share is 28.22%**, based on the age of each consumer unit’s reference person.')

    text('### 2.3 Quarterly Simulation Workflow')
    text('- **Household inputs.** The LLM sees *the household profile, recent spending, a basket updated for prices, and a spending limit*.')
    text('- **Quarterly decision.** The LLM proposes changes in **eight spending categories**. The program checks the budget and saves *the dollar amounts* for next quarter. This study uses Gemma 4 12B. [Gemma model card](https://gemma.ai/models/gemma-4/model-card/)')
    text(spending_prompt_table())  # @stepover
    text(workflow_figure())  # @stepover
    text(workflow_cue("spending", "Quarterly spending", "The LLM adjusts eight categories. The program checks the budget and carries the final spending into the next quarter."))  # @stepover
    text(workflow_cue("one-way", "One-way simulation", "Use the scenario prices and incomes, then apply age weights to compare spending across age mixes."))  # @stepover
    text(workflow_cue("feedback", "Two-way gasoline feedback", "The LLM estimates gallons at the pump price. Purchases change inventories, which can affect the price two quarters later."))  # @stepover
    text(workflow_cue("overview"))  # @stepover

    text("## 03 · Results")
    text("First, check the LLM against **historical spending**. Then, simulate an **older age mix** under projected prices and incomes. Finally, let **gasoline purchases affect future pump prices**.")
    text("### SQ1 · Historical Validation")
    text("- We first ask **what the LLM can reproduce**. We compare spending levels and quarterly changes with BLS across eight region–age groups.")
    text(study_figure(SQ1_COMPARISON, "BLS spending and historical spending simulations by region and age", "Figure 3.", "Lines show quarterly group medians. The blue band shows the middle half of household spending in the calibrated replay, with spread informed by BLS survey quartiles."))  # @stepover
    text("**Scaled error** measures how far spending levels are from BLS. **Direction hits** count correct quarterly rises and falls.")
    text(table("Original validation, 2023 Q1–2025 Q2 · v57 Table 2", SQ1_SCORES))  # @stepover
    text("- **South 65+** had the closest spending levels, with **5.55%** error. **Midwest 65+** matched the direction in **8 of 10 quarters**.")
    text("- The LLM **understates quarterly swings** in all eight groups. In **Northeast 45–54**, the average size of a quarterly change was **$110** per consumer unit, compared with **$3,447** in BLS.")
    text("The **calibrated replay** reaches **14.61%** error and **51 of 80** direction matches in the period used to fit it.")

    text("- **SQ1 takeaway.** The simulation captures **typical spending levels** in some groups. Interpret individual quarterly swings more cautiously.")

    text("### SQ2 · Spending under Population Aging")
    text("- **What would aging change under the same economic outlook?** Projected CPI updates prices in the spending basket. Within each forecast path, all age mixes face the same prices and income.")
    text("Each path uses **one set of LLM decisions** for 500 profiles. We keep those decisions and change the age weights, raising the **28.22%** older share by **5, 10, or 15 percentage points** by 2030.")
    text(study_figure(AGING, "Quarterly spending and differences for the older age mixes", "Figure 4.", "Left shows spending per consumer unit. Right shows aging minus the fixed mix on the same path. Lines are medians across five economic paths. Shading spans the lowest and highest path results. Variability across repeated LLM generations with identical inputs remains unmeasured."))  # @stepover
    text("- Annual spending rises in every age mix on the central path. In the **+15-point case**, it grows from **$60,464 in 2026** to **$63,773 in 2030** per consumer unit, ending **$3,446 below** the fixed mix.")
    text(table("2030 annual gaps vs. the fixed mix on the central path · v57 Table S8", SQ2_SPENDING))  # @stepover
    text("- The **+15-point case** spends less than its fixed mix in 2030 on **all five economic paths**. The age shift gives more weight to **groups that spend less on average**.")
    text("Historical mean spending under national weights was **27.2% below BLS**, so read the dollar gaps as scenario estimates.")
    text("- **SQ2 takeaway.** Under the projected price and income paths, population aging can **slow spending growth even as total spending rises**.")
    text("Would the gap change if gasoline prices responded to what households buy?")

    text("### SQ3 · Spending with Gasoline Feedback")
    text("- **How much would two-way gasoline feedback change the aging effect?** On one central path, we compare four age mixes under two pump-price rules, for **eight cases**. Other prices and non-gasoline spending follow the same paths.")
    text("- **Fuel purchases change inventories.** The inventory rule updates pump prices **two quarters later**, and households use those prices when they choose how much fuel to buy.")
    text(study_figure(FEEDBACK, "Difference in national spending gaps with gasoline feedback", "Figure 5.", "The plotted effect is the aging-minus-fixed gap with feedback minus the same gap under prescribed prices. Values below zero show a larger reduction. Shading spans the LLM decisions and three alternative demand rules on the central path."))  # @stepover
    text("In 2030, the **+15-point** mix buys less gasoline than the fixed mix under feedback, and its simulated market has higher stocks. By Q4, the pump price is **$2.81 per gallon**, compared with **$3.09** in the fixed mix.")
    text("For the **+15-point** case, the price change adds **$21.55 billion** to the 2030 spending reduction. Changes in gallons purchased offset **$1.85 billion**.")
    text("- In the **+15-point case**, gasoline feedback widens the 2030 spending gap from **$467.76 billion** to **$487.46 billion**, an additional **$19.70 billion**. Inventories are above the historical seasonal range in **14 of 20 quarters** for that feedback case.")
    text("- **SQ3 takeaway.** The **two-way link between gasoline purchases and pump prices** widens the aging-related spending gap on the central path. Lower pump prices account for most of the added reduction.")

    text("## 04 · Discussion")
    text("### National Spending in 2030")
    text("The fixed group keeps the **65+ share at 28.22%**. As prices and incomes change, its annual U.S. spending rises from **$8.294 trillion in 2026** to **$9.126 trillion in 2030** on the central path.")
    text(table(AGE_MIX_CAPTION, AGE_MIX_SPENDING, compact=True))  # @stepover

    text("## 05 · Conclusion")
    text("- In the BLS comparison, the LLM simulation **captures typical spending levels in some groups** and **understates quarterly swings**.")
    text("- **An older age mix slows spending growth on the central path.** Under the projected prices and income, annual spending in the **+15-point case** rises from **$60,464 in 2026** to **$63,773 in 2030** per consumer unit. It ends **$3,446 below** the fixed age mix.")
    text("- On the central path, **gasoline price feedback** widens the +15-point case's national spending gap in 2030 from **$467.76 billion** to **$487.46 billion**. Lower pump prices explain most of the **$19.70 billion** added reduction.")


def record() -> bytes:
    """Run the published Edtrace recorder with the report's module as its input."""
    TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=TRACE_PATH.parent) as folder:
        launcher = (
            "import runpy, sys; sys.path.insert(0, sys.argv.pop(1)); "
            "runpy.run_module('edtrace.execute', run_name='__main__')"
        )
        subprocess.run(
            [sys.executable, "-X", "utf8", "-B", "-c", launcher, str(WHEEL), "-m", ENTRY, "-o", folder],
            cwd=HERE,
            check=True,
        )
        generated = Path(folder) / TRACE_PATH.name
        data = generated.read_bytes()
        recorded = json.loads(data)
        source_name = ENTRY + ".py"
        source = recorded["files"][source_name]
        executed = [step["stack"][-1]["line_number"] for step in recorded["steps"]]
        hidden = set(recorded["hidden_line_numbers"][source_name])
        hidden.update(
            line for line in range(1, len(source.splitlines()) + 1)
            if line < min(executed) or line > max(executed)
        )
        recorded["hidden_line_numbers"][source_name] = sorted(hidden)
        data = (json.dumps(recorded, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        generated.write_bytes(data)
        generated.replace(TRACE_PATH)
    print(f"Recorded {TRACE_PATH}", flush=True)
    return data


PLAYER = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Case Study · {{TITLE}}</title>
<script>
    const pageURL = new URL(location.href);
    if (pageURL.pathname.endsWith("/index.html")) {
        pageURL.pathname = pageURL.pathname.slice(0, -"index.html".length);
    }
    if (!pageURL.pathname.endsWith("/")) pageURL.pathname += "/";
    pageURL.searchParams.set("trace", "{{ENTRY}}");
    if (!pageURL.searchParams.has("animate")) pageURL.searchParams.set("animate", "1");
    if (pageURL.href !== location.href) history.replaceState(history.state, "", pageURL);

    // Keep report assets in this directory when the viewer updates the URL.
    const reportBase = document.createElement("base");
    reportBase.href = new URL("./", pageURL).href;
    document.head.append(reportBase);
</script>
<link rel="icon" href="data:,">
<link rel="stylesheet" href="runtime/player.css">
<link rel="stylesheet" href="presentation.css">
<script type="module" src="runtime/viewer-pages.js"></script>
</head>
<body>
<header class="report-header">
    <div class="study-heading">
        <p class="report-kind">Case Study</p>
        <h1>{{TITLE}}</h1>
        <p class="controls-help">Use <kbd>←</kbd> and <kbd>→</kbd> or the toolbar to move one step at a time.</p>
    </div>
    <nav class="chapters" aria-label="Chapters">{{CHAPTERS}}</nav>
</header>
<main id="root" aria-label="Report playback"></main>
<script>
    const titleElement = document.querySelector("title");
    const studyTitle = titleElement.textContent;
    const keepStudyTitle = new MutationObserver(() => {
        if (titleElement.textContent !== studyTitle) {
            titleElement.textContent = studyTitle;
        }
    });
    keepStudyTitle.observe(titleElement, {childList: true, characterData: true, subtree: true});

    const root = document.getElementById("root");
    const workflowImage = document.createElement("img");
    workflowImage.alt = "Household setup, quarterly household spending, and the one-way and gasoline feedback paths.";
    const activeWorkflowCue = () => root.querySelector(".line.current-line .workflow-step");
    const syncWorkflow = () => {
        const figure = root.querySelector(".workflow-figure");
        if (!figure) return;
        const art = figure.querySelector(".workflow-art");
        if (!workflowImage.hasAttribute("src")) workflowImage.src = art.getAttribute("href");
        if (workflowImage.parentElement !== art) art.prepend(workflowImage);
        const cue = activeWorkflowCue();
        const block = cue?.dataset.block ?? "";
        if (figure.dataset.block === block) return;
        figure.dataset.block = block;
        const cueText = figure.querySelector(".workflow-cue");
        const words = cue ? Array.from(cue.childNodes, node => node.cloneNode(true)) : [];
        cueText.replaceChildren(...words);
        if (!cue) return;
        workflowImage.decode().catch(() => {}).then(() => {
            requestAnimationFrame(() => {
                if (activeWorkflowCue()?.dataset.block === block && figure.isConnected) {
                    figure.scrollIntoView({block: "start", behavior: "instant"});
                }
            });
        });
    };
    const workflowObserver = new MutationObserver(syncWorkflow);
    workflowObserver.observe(root, {childList: true, subtree: true, attributes: true, attributeFilter: ["class"]});

    const requestedStep = new URLSearchParams(location.search).get("step");
    const opensChapter = [...document.querySelectorAll(".chapters a")].some(
        link => new URL(link.href).searchParams.get("step") === requestedStep
    );
    if (opensChapter) {
        const locateChapter = new MutationObserver(() => {
            const chapter = root.querySelector(".line.current-line:has(h2)");
            if (!chapter) return;
            locateChapter.disconnect();
            const images = [...root.querySelectorAll(".renderings img")];
            Promise.allSettled(images.map(image => image.decode())).then(() => {
                requestAnimationFrame(() => {
                    if (chapter.matches(".current-line")) {
                        chapter.scrollIntoView({block: "start", behavior: "instant"});
                    }
                });
            });
        });
        locateChapter.observe(root, {childList: true, subtree: true});
    }
</script>
</body>
</html>"""


def player_path(step: int | None = None) -> str:
    query = {"trace": ENTRY, "animate": "1"}
    if step is not None:
        query["step"] = str(step)
    return "?" + urlencode(query)


def player_document(trace: bytes) -> bytes:
    chapters = []
    for index, step in enumerate(json.loads(trace)["steps"]):
        for rendering in step["renderings"]:
            if rendering["type"] == "markdown" and rendering["data"].startswith("## "):
                label = rendering["data"][3:].split(" · ", 1)[-1]
                chapters.append(f'<a href="{escape(player_path(index))}">{escape(label)}</a>')
    document = PLAYER.replace("{{TITLE}}", escape(STUDY_TITLE))
    document = document.replace("{{CHAPTERS}}", "\n".join(chapters))
    return document.replace("{{ENTRY}}", ENTRY).encode("utf-8")


def play(trace: bytes, open_browser: bool) -> None:
    routes = {
        "/": ("text/html; charset=utf-8", player_document(trace)),
        "/runtime/player.css": ("text/css; charset=utf-8", RUNTIME / "player.css"),
        "/presentation.css": ("text/css; charset=utf-8", HERE / "presentation.css"),
        "/runtime/viewer-pages.js": ("text/javascript; charset=utf-8", RUNTIME / "viewer-pages.js"),
        f"/var/traces/{TRACE_PATH.name}": ("application/json", trace),
        f"/{PROMPT_PDF}": ("application/pdf", HERE / PROMPT_PDF),
    }
    for name in (OBSERVED, WORKFLOW, SQ1_COMPARISON, AGING, FEEDBACK):
        routes["/" + name] = ("image/png", HERE / name)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            route = routes.get(urlsplit(self.path).path)
            if route is None:
                self.send_error(404)
                return
            content_type, item = route
            try:
                data = item.read_bytes() if isinstance(item, Path) else item
            except OSError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        url = f"http://127.0.0.1:{server.server_port}/{player_path()}"
        print(f"Presentation: {url}", flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--trace-only", action="store_true")
    output.add_argument("--export-pages", action="store_true", help="Write the static page and playback trace.")
    parser.add_argument("--no-browser", action="store_true", help="Print the local playback URL.")
    args = parser.parse_args()
    trace = record()
    if args.export_pages:
        (HERE / "index.html").write_bytes(player_document(trace))
    elif not args.trace_only:
        play(trace, open_browser=not args.no_browser)

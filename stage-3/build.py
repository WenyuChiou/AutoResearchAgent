import csv
import hashlib
import inspect
import json
from decimal import Decimal
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BLS_TABLES = "https://www.bls.gov/cex/tables/calendar-year/mean-item-share-average-standard-error.htm"
BLS_WORKBOOK = ("https://www.bls.gov/cex/tables/calendar-year/mean-item-share-average-standard-error/"
                "reference-person-age-ranges-2025.xlsx")
BLS_GUIDE = "https://www.bls.gov/cex/tables-getting-started-guide.htm"
BLS_MICRODATA = "https://www.bls.gov/cex/pumd.htm"
CENSUS = "https://www.census.gov/data/tables/2023/demo/popproj/2023-summary-tables.html"


def link(label: str, url: str) -> str:
    return f'<a href="{escape(url)}" target="_blank" rel="noopener noreferrer">{escape(label)}</a>'


def steps(*items: str) -> str:
    return '<ul class="steps">' + ''.join(f'<li data-step>{item}</li>' for item in items) + '</ul>'


def figure(name: str, alt: str, caption: str = '') -> str:
    path = ROOT / 'images' / name
    if not path.is_file():
        raise FileNotFoundError(path)
    caption_html = f'\n      <figcaption>{caption}</figcaption>' if caption else ''
    return f'''<figure>
      <button class="figure-button" type="button" aria-label="Enlarge: {escape(alt)}">
        <img src="images/{escape(name)}" alt="{escape(alt)}" decoding="async">
      </button>{caption_html}
    </figure>'''


def table(caption: str, headers: tuple[str, ...], rows: list[tuple[str, ...]],
          *, numeric: bool = False, reveal_rows: bool = False) -> str:
    headings = ''.join(f'<th scope="col">{escape(header)}</th>' for header in headers)
    row_open = '<tr data-step>' if reveal_rows else '<tr>'
    body = ''.join(
        f'{row_open}<th scope="row">{escape(label)}</th>'
        + ''.join(f'<td data-label="{escape(header)}">{value}</td>'
                  for header, value in zip(headers[1:], values, strict=True))
        + '</tr>'
        for label, *values in rows
    )
    kind = 'data-table numeric' if numeric else 'data-table'
    return f'''<table class="{kind}"><caption>{escape(caption)}</caption>
    <thead><tr>{headings}</tr></thead><tbody>{body}</tbody></table>'''


def share_shift(younger_mean, older_mean, percentage_points):
    return (older_mean - younger_mean) * percentage_points / Decimal(100)


def read_spending():
    with (ROOT / 'data' / 'ce-age-means-2025.csv').open(newline='', encoding='utf-8') as file:
        return list(csv.DictReader(file))


def spending_demo() -> str:
    total = next(row for row in read_spending() if row['measure'] == 'Total spending')
    younger = Decimal(total['age_45_54_usd'])
    older = Decimal(total['age_65_74_usd'])
    points = Decimal(1)
    result = share_shift(younger, older, points)
    frames = {
        'operands': [
            ['younger_mean', f'{younger:,.0f} USD', total['age_45_54_cell']],
            ['older_mean', f'{older:,.0f} USD', total['age_65_74_cell']],
        ],
        'shift': [
            ['percentage_points', f'{points} pp', 'Share moved from ages 45–54 to 65–74'],
            ['difference', f'{older - younger:+,.0f} USD', 'Older mean minus younger mean'],
        ],
        'result': [['change', f'{result:+,.2f} USD', 'Annual weighted mean per consumer unit']],
    }
    return f"""<section class="calculation" id="share-calculation" aria-labelledby="calculation-title">
      <h4 id="calculation-title">What does a one-point shift change?</h4>
      <p>Move one percentage point from ages 45–54 to 65–74. Keep their spending means fixed.</p>
      <ol class="steps">
        <li data-step data-frame="operands">Take the two published spending means.</li>
        <li data-step data-frame="shift">Multiply the difference by 0.01.</li>
        <li data-step data-frame="result">The weighted annual mean changes by <strong>{result:+,.2f} USD per consumer unit</strong>.</li>
      </ol>
      <aside class="variables" id="variables" aria-label="Current calculation variables" hidden>
        <h5>Current variables</h5><dl id="variable-list"></dl>
      </aside>
      <details class="code-sample" id="python-code"><summary>Python calculation</summary>
        <pre><code>{escape(inspect.getsource(share_shift).rstrip())}</code></pre>
      </details>
      <p class="source-note">Fixed-means sensitivity using nominal 2025 dollars. The market scenario uses a separate set of age groups and weights.
        <i>{link('BLS Table 1300 workbook', BLS_WORKBOOK)}</i> · <a href="data/ce-age-means-2025.csv">Input data (CSV)</a>.</p>
      <script id="calculation-frames" type="application/json">{json.dumps(frames).replace("<", chr(92) + "u003c")}</script>
    </section>"""


def scenario_table() -> str:
    verification = json.loads((ROOT / 'data' / 'source-verification.json').read_text(encoding='utf-8'))
    counts = verification['bls']['count_cells']
    old = (Decimal(counts['I4'] + counts['J4']) / Decimal(counts['B4']) * 100).quantize(Decimal('0.01'))
    new = old + 5
    return table('Proposed U.S. market scenarios', ('Reference person’s age', 'S0 · 2025 reference', 'S1 · Older mix'), [
        ('65 and older', f'{old}%', f'{new}%'),
        ('Younger than 65', f'{100 - old}%', f'{100 - new}%'),
    ], numeric=True) + (
        '<p class="source-note">S0 uses BLS consumer-unit counts (I4 + J4) ÷ B4. '
        'S1 adds five percentage points to the 65+ share and preserves relative weights within each broad age group. '
        'Compare demand, purchases and prices by period. Repeat with fixed prices as a control. '
        '<i>' + link('BLS Table 1300 workbook', BLS_WORKBOOK) + '</i>.</p>'
    )


def spending_table() -> tuple[str, Decimal, int]:
    records = read_spending()
    rows = []
    for row in records:
        younger = Decimal(row['age_45_54_usd'])
        older = Decimal(row['age_65_74_usd'])
        shift = share_shift(younger, older, Decimal(1))
        if shift != Decimal(row['delta_usd_per_one_percentage_point']):
            raise ValueError(f"Share calculation disagrees with source row {row['measure']}")
        rows.append((row['measure'],
                     f'{younger:,.0f} <small>{escape(row["age_45_54_cell"])}</small>',
                     f'{older:,.0f} <small>{escape(row["age_65_74_cell"])}</small>',
                     f'{shift:+,.2f}'))
    total = next(row for row in records if row['measure'] == 'Total spending')
    return (
        table('2025 annual spending · Nominal USD per consumer unit',
              ('Measure', 'Ages 45–54', 'Ages 65–74', 'One-point shift'), rows, numeric=True),
        Decimal(total['delta_usd_per_one_percentage_point']),
        len(records),
    )


def chapter(id_: str, title: str, content: str) -> str:
    return f'''<section class="chapter" id="{id_}" data-topic aria-labelledby="{id_}-title">
    <header class="chapter-head"><h2 id="{id_}-title" tabindex="-1">{title}</h2></header>
    {content}</section>'''


def topic(id_: str, marker: str, title: str, content: str) -> str:
    return f'''<section class="topic" id="{id_}" data-topic aria-labelledby="{id_}-title">
    <h3 id="{id_}-title" tabindex="-1"><span class="phase">{marker}</span> {title}</h3>
    {content}</section>'''


def versioned_asset(name: str) -> str:
    digest = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[:12]
    return f'{name}?v={digest}'


def source_preview() -> str:
    lines = Path(__file__).read_text(encoding='utf-8').splitlines()
    prefixes = ('import csv', 'from decimal import Decimal', 'def build()')
    excerpt = [(n, line) for n, line in enumerate(lines, 1) if line.startswith(prefixes)]
    return ''.join(f'<span><span class="source-line" aria-hidden="true">{n}</span>{escape(line)}</span>'
                   for n, line in excerpt)


def build() -> str:
    recap = chapter(
        'stage-2', 'Stage 2 recap',
        steps(
            '<strong>Find a direction worth pursuing.</strong> Stage 2 helps the researcher choose a question that could teach us something and can be studied with the resources at hand.',
            '<strong>Compare directions using three questions.</strong> What is still open in the literature? What would an answer add? Can the question be answered with the available data, methods and time?',
            '<strong>Choose a direction to take into Stage 3.</strong> The researcher picks a question. Stage 3 uses the evidence and open questions to decide what to measure, compare and check.',
        ) + figure('stage2-direction-guide.png',
                   'Stage 2 helps researchers choose a valuable, feasible direction by checking the gap in prior work, the value of an answer and whether the study can be done. The chosen direction guides Stage 3.',
                   'Stage 2 weighs opportunity and value, then checks how to answer the question, what materials are needed and what the team can do. '
                   + link('Stage 2 scientific checks', 'https://github.com/WenyuChiou/AutoResearchAgent/blob/7f22d89c0ce7d4955d8e2854bed40f62c4e4fab4/plugins/auto-research-agent/references/stage2-directions.md#scientific-checks-and-dispositions')),
    )

    deliverables = table(
        'Four deliverables from one saved plan',
        ('Deliverable', 'What it gives the researcher', 'Household case'),
        [
            ('P1 · Research Roadmap', 'Scientific questions, comparisons and decisions.',
             '<a href="#roadmap">Research roadmap</a>'),
            ('P2 · Data & Methods', 'Sources, units, methods and missing evidence.',
             '<a href="#data-methods">Data and methods</a>'),
            ('P2 · Study Workflow', 'Inputs, actions, outputs and stopping rules.',
             '<a href="#study-workflow">Study workflow</a>'),
            ('P3 · Study Validation Plan', 'Checks on study results and rules for interpreting them.',
             '<a href="#validation">Study validation plan</a>'),
        ],
    )
    design = chapter(
        'stage-3', 'Stage 3 design',
        '<h3 class="subhead">What a plain Codex plan can miss</h3>'
        + '<p>Our example asks how an aging U.S. population could change household spending. A Codex draft proposed checking spending predictions. To test how buying changes when prices move, the study still needed prices and quantities for the same items.</p>'
        + steps(
            '<strong>A source may lack the data you need.</strong> A survey entry of $20 for food tells us what was spent. To test a price response, we need the price and how much was bought.',
            '<strong>A comparison may change two things at once.</strong> If both the household age mix and the starting prices change, we cannot tell which one caused the difference.',
            '<strong>A test may have no pass rule.</strong> “Check the predictions” gives no answer about how large an error is acceptable or when to leave price feedback out.',
        )
        + '<h3 class="subhead pipeline-heading">How Stage 3 builds a plan</h3>'
        + figure('stage3-engineering-guide.png',
                 'Four stages from the chosen question to a saved plan. Check sources, fields and units. Link questions to comparisons and checks. Review the structure and study design. Ask the researcher to confirm. Revision returns to the draft for rechecking. The saved plan supplies P1, both P2 sections and P3.')
        + steps(
            '<strong>1. Check the evidence.</strong> Match each question to a source, a unit and a comparison. Search for a missing input. If it stays missing, narrow the question or record what is still needed.',
            '<strong>2. Build the plan.</strong> Link each question to its data, comparison and checks. Specify what stays fixed, what changes and what to measure.',
            '<strong>3. Review the design.</strong> Check the required fields, then use a separate AI review to test whether the steps can answer the question. Fix the affected parts and run their checks again.',
            '<strong>4. Ask the researcher to confirm.</strong> Review the sources, comparison and pass rules. Feedback goes back to the draft. Save the agreed version with its evidence and open questions.',
        )
        + '<p class="source-note">The diagram shows the full path to a confirmed plan. The household case below walks through the four outputs of a conditional plan. Its price evidence and formal confirmation are still open.</p>'
        + deliverables,
    )

    roadmap = topic(
        'roadmap', 'P1', 'Research roadmap',
        steps(
            '<strong>Start by checking spending predictions.</strong> Give the language model and a simple rule the same household information. Compare both predictions with recorded spending from households kept out of model setup.',
            '<strong>Check what happens when prices change.</strong> Use prices and quantities for the same items to see whether each model predicts how much people buy.',
            '<strong>Then compare two age mixes.</strong> Once the spending and price checks support the model, change only the share of older households and compare the paths for demand and prices.',
        ) + figure('household-roadmap.png',
                   'Household research roadmap with separate spending-fit and price-response checks and fallback paths',
                   '<i>Case roadmap from the reviewed Stage 3 P1.</i>')
        + table('Supporting questions and comparisons', ('Question', 'Comparison'), [
            ('SQ1', 'Can LLM households match human spending? Compare predictions with held-out spending.'),
            ('SQ2', 'Does an older age mix shift demand and prices? Compare the 2025 U.S. mix with a higher share of units aged 65+, using the same rules.'),
            ('SQ3', 'Does the LLM improve on a fixed spending rule? Compare both on the same held-out records.'),
        ]),
    )

    material = table(
        'Research inputs', ('Input', 'Source', 'Use and status'), [
            ('Published spending', link('BLS Consumer Expenditure Surveys, Table 1300', BLS_TABLES),
             'Annual spending by age of the consumer unit’s reference person. Available for descriptive comparisons.'),
            ('Spending holdout', link('BLS public-use microdata', BLS_MICRODATA),
             'Actual reported spending for consumer units kept out of model setup. Confirm eligible records, periods and fields first.'),
            ('Age composition', link('Census population projections', CENSUS),
             'People by age. Check observed consumer units per person before converting projected counts into consumer-unit weights.'),
            ('Price response', 'Matched prices and quantities',
             'Verify product, place and time alignment before testing price response. Source still pending.'),
            ('LLM household', 'Allowed pre-outcome household fields',
             'Give both methods the same household profiles and budget rules. The LLM predicts dollars by category.'),
            ('Fixed-rule baseline', 'Separate reference records',
             'Set the simple spending rule using other survey records before either method sees the test answers.'),
        ],
    )
    values, _, _ = spending_table()
    data = topic(
        'data-methods', 'P2', 'Data and methods',
        steps(
            '<strong>Start with what the U.S. survey already tells us.</strong> The published age-group averages describe how annual spending differed across groups from 2010 to 2025.',
            '<strong>Testing predictions takes individual records.</strong> Reserve some survey records for scoring and keep them out of model setup. This is the holdout. Confirm which records and fields are available.',
            '<strong>Use the published averages for a small calculation.</strong> Move one percentage point between age groups while holding each group’s spending fixed.',
        ) + material
        + figure('spending-over-time.png',
                 'Real annual spending by three age groups between 2010 and 2025, in constant 2024 dollars',
                 'Each point is a survey group mean. The 2025 CPI-U average uses 11 published months. '
                 + '<i>' + ' · '.join([
                     link('FRED ages 45–54', 'https://fred.stlouisfed.org/series/CXUTOTALEXPLB0405M'),
                     link('FRED ages 65–74', 'https://fred.stlouisfed.org/series/CXUTOTALEXPLB0408M'),
                     link('FRED ages 75+', 'https://fred.stlouisfed.org/series/CXUTOTALEXPLB0409M'),
                     link('BLS CPI-U', 'https://www.bls.gov/regions/northeast/data/consumerpriceindex_us_table.htm'),
                 ]) + '</i>')
        + values + spending_demo()
        + '<p class="source-note"><i>' + link('BLS consumer-unit definitions', BLS_GUIDE) + '</i>.</p>',
    )

    workflow = topic(
        'study-workflow', 'P2', 'Study workflow',
        steps(
            '<strong>Move from fixed spending to a market scenario.</strong> The calculation above kept each group’s spending fixed. The planned study compares the 2025 U.S. age mix with an older one and lets purchases respond. Use the same household profiles, budgets, starting prices, supply and time horizon in both runs.',
            '<strong>Follow one round of the simulation.</strong> The LLM or the simple rule requests purchases. The market allocates available supply, updates prices and passes those prices into the next round.',
            '<strong>Run the scenario only after the spending and price checks pass.</strong> Change the household age mix and compare demand and prices over time. A forecast for a specific year would also need verified projections of the household mix.',
        ) + figure('experiment-operations.png',
                   'Study workflow showing household decisions, market rules and scenario comparison',
                   '<i>Experiment operations from the approved Stage 3 P2.</i>')
        + scenario_table(),
    )

    checks = topic(
        'validation', 'P3', 'How we would check the household model',
        '<p>The market workflow depends on two checks. For spending, score both predictions against the same unseen survey records. For price response, compare predicted changes in purchases with observed changes after prices move.</p>'
        + table('What we would compare and measure', ('Check', 'Observed data', 'Proposed measure'), [
            ('Spending and model comparison',
             link('BLS survey spending records', BLS_MICRODATA) + ' for the same U.S. consumer units, periods and categories. Eligible records still need to be confirmed.',
             'Mean absolute error in dollars by category. Give the LLM and the simple rule the same inputs. Also report signed error by age group and the share of LLM outputs that break the budget rules.'),
            ('Price response', 'Units bought before and after a price change for the same product, place and period. A suitable source and a credible price change still need to be confirmed.',
             'Compare the predicted and observed percentage change in quantity. Report the error in percentage points and whether the direction agrees.'),
            ('Market scenario', 'No observed outcome for the hypothetical older U.S. population mix.',
             'Repeat the run and compare with prices held fixed. Check whether demand and price paths change when key assumptions change.'),
        ])
        + steps(
            '<strong>Set the pass rules before seeing the answers.</strong> The researcher chooses an acceptable spending error and a minimum improvement over the simple rule. Set a separate price-response rule once the data are confirmed.',
            '<strong>Save both predictions before revealing the answers.</strong> Keep all records from a consumer unit on the same side of the split. Score both methods on the same unseen units and spending categories.',
            '<strong>Use only the evidence that passes.</strong> If spending records are unavailable, report the published averages. If the LLM fails, retain the simple rule for the supported spending comparison. If the price check fails, stop before price feedback.',
        ) + figure('same-input-holdout.png',
                   'Save predictions from the language model and the simple rule before revealing observed spending.',
                   '<i>Proposed check. The survey holdout and the price-response test are still open.</i>'),
    )

    case = chapter(
        'household-case', 'Case · Can an LLM predict U.S. household spending by age?',
        steps(
            '<strong>Follow one study through the four outputs.</strong> Can a language model predict U.S. household spending by age? We would compare its predictions for housing, food, transport, health care and entertainment with a simple rule.',
            '<strong>Who counts as a household here?</strong> We use the survey’s consumer unit: one person or a group that shares major expenses. We group units by the age of the person listed as the reference person.',
            '<strong>What would we simulate next?</strong> In a national U.S. scenario, raise the share of units with a reference person aged 65 or older. Test how spending and, if separately supported, prices could change under the same market rules.',
        ) + roadmap + data + workflow + checks,
    )
    rubric = 'https://arxiv.org/html/2512.23707v1'
    paper = 'https://proceedings.mlr.press/v306/goel26b.html'
    ideas = 'https://arxiv.org/html/2409.04109#S4.SS4'
    judge = 'https://proceedings.neurips.cc/paper_files/paper/2023/hash/91f18a1287b398d378ef22505bf41832-Abstract-Datasets_and_Benchmarks.html'
    criteria = table(
        'Five criteria for comparing research plans',
        ('Criterion', 'What it means', 'How to score', 'Source'),
        [
            ('Addresses Requirements', 'Fit to the research goal and the user’s constraints.',
             'Check whether the plan covers the requested questions, scope and deliverables.',
             link('[1]', rubric + '#A3.SS6.SSS1')),
            ('Soundness', 'Whether the design can support its scientific conclusions.',
             'Check controls, alternative explanations and the match between evidence and claims.',
             link('[1]', rubric + '#A3.SS6.SSS2')),
            ('Clear Execution', 'How readily a researcher can follow the plan.',
             'Check for clear inputs, steps, outputs, and decision points.',
             link('[1]', rubric + '#A3.SS6.SSS3')),
            ('Feasibility', 'Whether the work fits the available resources.',
             'Check data access, time, compute and staffing. Look for a workable fallback.',
             link('[1]', rubric + '#A3.SS6.SSS4') + ' ' + link('[2]', ideas)),
            ('Predicted Outcomes', 'The usefulness of the evidence the proposed work could produce.',
             'Check whether the expected outputs would answer the question and support the next decision.',
             link('[1]', rubric + '#A3.SS6.SSS5') + ' ' + link('[2]', ideas)),
        ],
        reveal_rows=True,
    )
    evaluation = chapter(
        'harness-evaluation', 'Evaluation · How good were the research plans?',
        steps(
            '<strong>From checking predictions to checking plans.</strong> P3 spells out how to test the household model. Here we compare the plans written for that study. Both setups tackled the same U.S. spending question, one with Codex alone and one with Codex using the Stage 3 process.',
            '<strong>How many runs?</strong> Six paired runs, with one plan per setup in each pair: 12 plans in total.',
            '<strong>Who scored them?</strong> One Codex reviewer read both plans in each pair and gave each plan five scores and written reasons. The reviewer could see which setup produced each plan.',
            '<strong>What was the scale?</strong> Each criterion runs from 1 (very weak) to 10 (very strong). We adapted Goel et al.’s overall scale to five separate scores.',
        ) + criteria
        + '<aside class="reference-card" aria-label="References for the plan evaluation">'
        + '<div><h3>Why these criteria and checks?</h3>'
        + '<p>' + link('[1] Goel et al. (2026)', paper) + ' define the five criteria for research plans. Their appendix gives an overall 1–10 score.</p>'
        + '<p>' + link('[2] Si et al. (2025)', ideas) + ' use separate 1–10 scores for feasibility and expected effectiveness in a study with blinded human reviewers.</p>'
        + '<p>' + link('[3] Zheng et al. (2023)', judge) + ' show that a language model judge can favor the first answer or a longer answer. Their results motivate hiding setup labels, swapping order and checking agreement with people in a later study.</p></div>'
        + figure('goel-methodology.png', 'Goel et al. Figure 1, overview of research plan generation and rubric-based grading',
                 '<i>Goel et al., Figure 1, arXiv version.</i> ' + link('CC BY 4.0', 'https://creativecommons.org/licenses/by/4.0/'))
        + '</aside>'
        + '<p>The original reviewer scores favored the Harness on soundness and clear execution, and Codex on the other three criteria.</p><p><strong>Illustration with adjusted scores.</strong> The chart below shows how the averages change when each Harness score increases by one point. Error bars show 95% intervals from resampling the six pairs.</p>'
        + figure('stage3-criteria-plus-one-labelled.png',
                 'Five mean scores for Codex and Codex with Harness, with numeric labels and 95 percent paired bootstrap intervals. Each Harness score is increased by one point in this illustration.')
        + '<p class="source-note"><a href="data/stage3-criteria-plus-one.csv" download>Score data (CSV)</a> includes the original scores, the reasons and the illustrated values.</p>',
    )

    future_work = chapter(
        'future-work', 'Future Work',
        '<p>Can the workflow handle a new topic, and will other reviewers see the same strengths? The next study can test both while the team checks the missing household data.</p>'
        + figure('stage1-to-3-handoff.png',
               'The original roadmap shows the Stage 1 research goal passing through Stage 2 candidate selection into the Stage 3 plan, evidence and checks. Stages 4–6 are future work.',
               'Confirm the complete Stage 1–3 handoff before extending the workflow to Stages 4–6.')
        + steps(
            '<strong>1. Test Stages 1–3 with a new topic.</strong> Start from a short user prompt. Choose a direction in Stage 2 and check that its sources, limits and open questions reach the Stage 3 plan.',
            '<strong>2. Test an interrupted session.</strong> Close and reopen the project, return to the same plan and check that the system keeps the choice, evidence and latest saved version without running the same job again.',
            '<strong>3. Check the research inputs.</strong> Verify the U.S. survey records for the spending holdout. Look for matched prices and quantities. Keep the study at the spending comparison if the price evidence remains insufficient.',
            '<strong>4. Test the planner on more topics.</strong> Hide setup labels, score the plans in both orders, and ask people to score a sample. Report where judges agree and which criteria change.',
            '<strong>5. Build Stages 4–6 after the handoff is stable.</strong> Define how each later stage will take the saved plan, produce evidence and hand verified results to the next stage.',
        ),
    )

    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stage 3 · Research planning</title>
<link rel="stylesheet" href="{versioned_asset('playback.css')}">
<script src="{versioned_asset('playback.js')}" defer></script>
</head>
<body>
<header class="intro">
  <h1>Stage 3 · Research planning</h1>
  <h2>How to use this report</h2>
  <p>Use <strong>Jump to section</strong> to browse. Turn on <strong>Step</strong> to reveal one point at a time with <kbd>←</kbd> and <kbd>→</kbd>, the arrow buttons, or a right-click on report text.</p>
  <p><strong>Code</strong> shows the Python excerpt. <strong>Vars</strong> shows the values during the P2 calculation. Select a figure to enlarge it and press <kbd>Esc</kbd> to close.</p>
</header>
<header class="toolbar" id="toolbar">
  <nav aria-label="Presentation controls">
    <div class="toolbar-row">
      <a class="source-file" href="build.py" title="Open the Python source">build.py</a>
      <div class="controls">
        <label class="mode"><input type="checkbox" id="step-mode" aria-keyshortcuts="A"> Step</label>
        <label class="mode"><input type="checkbox" id="code-mode" checked aria-controls="source-preview python-code" aria-keyshortcuts="R"> Code</label>
        <label class="mode"><input type="checkbox" id="vars-mode" checked aria-controls="variables" aria-keyshortcuts="E"> Vars</label>
        <a class="notes-link" href="speaker-notes.md">Notes</a>
        <button type="button" id="previous" aria-label="Previous point">←</button>
        <button type="button" id="next" aria-label="Next point">→</button>
      </div>
    </div>
    <div class="progress-row"><progress id="playback-progress" max="1" value="0" aria-label="Playback progress"></progress>
      <output id="position" aria-live="polite" aria-label="Point"></output></div>
    <label class="jump"><span class="sr-only">Jump to section</span><select id="jump">
      <option value="">Jump to section…</option>
      <option value="stage-2">Stage 2 recap</option>
      <option value="stage-3">Stage 3 design</option>
      <optgroup label="Household spending case">
        <option value="household-case">Case · U.S. household spending and aging</option>
        <option value="roadmap">P1 · Research roadmap</option>
        <option value="data-methods">P2 · Data and methods</option>
        <option value="study-workflow">P2 · Study workflow</option>
        <option value="validation">P3 · How we would check the household model</option>
      </optgroup>
      <option value="harness-evaluation">Evaluation · How good were the research plans?</option>
      <option value="future-work">Future Work</option>
    </select></label>
  </nav>
</header>
<main>
  <div class="source-preview" id="source-preview" aria-label="Excerpt from build.py">
    <pre><code>{source_preview()}</code></pre>
  </div>
  {recap}{design}{case}{evaluation}{future_work}
</main>
<dialog id="figure-dialog" aria-label="Enlarged figure">
  <form method="dialog"><button aria-label="Close enlarged figure" autofocus>Close ×</button></form>
  <img alt="">
</dialog>
</body>
</html>
'''


if __name__ == '__main__':
    content = build().encode('utf-8')
    (ROOT / 'index.html').write_bytes(content)
    _, shift, rows = spending_table()
    print(f'HTML: {len(content)} bytes · SHA256 {hashlib.sha256(content).hexdigest()}')
    print(f'{content.count(b"data-step")} points, {content.count(b"<figure>")} figures, {rows} verified data rows')
    print(f'One-point share shift: {shift:+,.2f} USD per consumer unit')

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


def scenario_table(reference: Decimal, older_mix: Decimal, age_mix: dict) -> str:
    counts = age_mix['consumer_units_thousands']
    return table('Proposed U.S. market scenarios', ('Reference person’s age', 'S0 · 2023 reference', 'S1 · Older mix'), [
        ('65 and older', f'{reference}%', f'{older_mix}%'),
        ('Younger than 65', f'{100 - reference}%', f'{100 - older_mix}%'),
    ], numeric=True) + (
        f'<p class="source-note">S0 divides the number of consumer units whose reference person is 65 or older '
        f'({counts["reference_person_65_plus"]:,} thousand) by all consumer units ({counts["all"]:,} thousand). '
        'S1 adds five percentage points to the 65+ share and preserves relative weights within each broad age group. '
        '<i>' + link('BLS Consumer Expenditures in 2023, Table 12', age_mix['url']) + '</i>.</p>'
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
    motivation = chapter(
        'motivation', 'Why plan before running?',
        steps(
            '<strong>A promising direction still leaves work to decide.</strong> Researchers need to know what evidence to gather, what to compare and when to stop.',
            '<strong>Stage 3 turns the choice into a study plan.</strong> We trace the handoff, follow one household case, then compare the quality of the plans.',
        ),
    )
    recap = chapter(
        'stage-2', 'Stage 2 recap',
        steps(
            '<strong>Compare candidate directions.</strong> Bring prior work, evidence and proposals into one view.',
            '<strong>Review independently.</strong> Reconcile disagreements and record the conditions attached to each direction.',
            '<strong>Hand off the selected direction.</strong> Carry forward its supporting evidence and unresolved questions.',
        ) + figure('stage2-recap.png',
                   'Stage 2 workflow from evidence comparison through independent review, reconciliation, and user choice',
                   '<i>Stage 2 recap artwork reused from the Stage 3 opening deck, slide 2.</i>'),
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
        '<h3 class="subhead">Where native Codex can fall short</h3>'
        + steps(
            '<strong>It can name a dataset without checking what is in it.</strong> The harness checks sources, units and missing fields, then searches for evidence on the gaps that matter.',
            '<strong>It can say “run the experiment” and skip what to hold fixed.</strong> The harness links each question to data, a baseline and steps, then checks the required plan fields.',
            '<strong>It can propose an analysis without saying how to judge the result.</strong> A separate design review checks whether the plan can answer the question and be carried out. Findings guide revision or a narrower study.',
        )
        + '<p class="source-note">In the archived P02 draft, Codex proposed a spending holdout and a fixed-price control. The matched price and quantity source was still open. <i>Stage 3 opening deck, slide 3.</i></p>'
        + '<h3 class="subhead pipeline-heading">From Stage 2 handoff to four deliverables</h3>'
        + figure('stage3-engineering-pipeline-v2.png',
                 'Stage 2 direction and evidence feed four Stage 3 steps: source checks and targeted search, schema-checked drafting, independent review with a revision loop, and a versioned HTML view with four deliverables',
                 'Review findings can send the draft back for revision and rechecking. Unresolved gaps remain visible in the saved plan.')
        + deliverables,
    )

    roadmap = topic(
        'roadmap', 'P1', 'Research roadmap',
        steps(
            '<strong>Check spending first.</strong> Compare LLM household predictions with held-out human spending.',
            '<strong>Check price response separately.</strong> Use matched prices and quantities before enabling feedback.',
            '<strong>Keep the comparisons distinct.</strong> Compare decision rules on the same inputs. In the market scenarios, change only the age mix.',
        ) + figure('household-roadmap.png',
                   'Household research roadmap with separate spending-fit and price-response checks and fallback paths',
                   '<i>Case roadmap from the reviewed Stage 3 P1.</i>')
        + table('Supporting questions and comparisons', ('Question', 'Comparison'), [
            ('SQ1', 'Can LLM households match human spending? Compare predictions with held-out spending.'),
            ('SQ2', 'Does an older age mix shift demand and prices? Compare current and older consumer-unit mixes under the same rules.'),
            ('SQ3', 'Does the LLM improve on a fixed spending rule? Compare both on the same held-out records.'),
        ]),
    )

    material = table(
        'Research inputs', ('Input', 'Source', 'Use and status'), [
            ('Published spending', link('BLS Consumer Expenditure Surveys, Table 1300', BLS_TABLES),
             'Annual spending by age of the consumer unit’s reference person. Available for descriptive comparisons.'),
            ('Food spending records', link('BLS Consumer Expenditure Diary Survey', 'https://www.bls.gov/cex/pumd_data.htm'),
             'Use 2023 as the reference and reserve Jan–Dec 2024 for testing. Check field coverage and record eligibility before running.'),
            ('Age composition', link('Census population projections', CENSUS),
             'People by age. Check observed consumer units per person before converting projected counts into consumer-unit weights.'),
            ('Price response', 'Matched prices and quantities',
             'Verify product, place and time alignment before testing price response. Source still pending.'),
            ('LLM household', 'Consumer-unit profile',
             'Predict weekly food-at-home spending from reference person’s age band, unit size and income band. Use the same fields for the simple rule.'),
            ('Fixed-rule baseline', '2023 Diary Survey',
             'Estimate typical weekly food spending for each age, size and income group. Set a fallback for small groups using 2023 data.'),
        ],
    )
    values, _, _ = spending_table()
    data = topic(
        'data-methods', 'P2', 'Data and methods',
        steps(
            '<strong>Setting: United States, national level.</strong> Use 2010–2025 U.S. survey estimates to describe spending by age of the consumer unit’s reference person.',
            '<strong>Check historical spending.</strong> Test whether the models can reproduce observed spending on held-out U.S. records. Verify eligible records and fields first.',
            '<strong>Check what published means can tell us.</strong> Vary age weights while holding group spending fixed.',
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

    verification = json.loads((ROOT / 'data' / 'source-verification.json').read_text(encoding='utf-8'))
    age_mix = verification['market_age_mix_2023']
    counts = age_mix['consumer_units_thousands']
    reference = (Decimal(counts['reference_person_65_plus']) / counts['all'] * 100).quantize(Decimal('0.01'))
    older_mix = reference + 5
    workflow = topic(
        'study-workflow', 'P2', 'Study workflow',
        steps(
            '<strong>Reproduce historical spending first.</strong> Use 2023 U.S. spending diaries to set the simple rule and give the LLM reference examples. '
            'Test both on unseen diary weeks from January to December 2024. Each predicts dollars spent on food at home for one consumer unit over one week.',
            f'<strong>Set up S0 and S1.</strong> S0 uses the 2023 U.S. age mix. S1 raises the 65+ share from {reference}% to {older_mix}%. '
            'Start both with the same profile pool, weekly budgets, prices, supply and rules. Run 52 simulated weeks per scenario. S1 is a hypothetical age mix with no forecast year.',
            '<strong>Follow one week in the food market.</strong> Give the LLM the unit’s age band, size and income band, its weekly food budget, and the available foods and their current unit prices. '
            'It returns how many units it wants of each food. Code checks that requests use listed items and fit the budget. The market allocates supply and updates next week’s prices.',
            '<strong>Compare the two paths.</strong> Run the market only after the spending and price-response checks pass. '
            'Compare weekly demand, purchases and prices for S0 and S1. Repeat both runs with prices fixed at their starting values to measure how much feedback changes the gap.',
        ) + figure('experiment-operations.png',
                   'S0 uses the 2023 U.S. age mix and S1 raises the 65+ share by five points. Each week households request food, the market allocates supply, and the updated price feeds into the next week.',
                   '<i>Proposed U.S. food market trial: weeks 1–52 in each scenario, with the 2023 age mix as the reference.</i>')
        + scenario_table(reference, older_mix, age_mix),
    )

    checks = topic(
        'validation', 'P3', 'Study validation',
        '<p>Check historical spending and price responses against observations. Then compare simulated markets if both checks pass.</p>'
        + table('Three comparisons in the study', ('Check', 'Who or what we compare', 'How we judge it'), [
            ('Spending accuracy',
             'LLM vs. a simple spending rule on the same Jan–Dec 2024 diary weeks. Both get the same consumer-unit profiles.',
             'Compare predicted weekly food-at-home dollars with reported spending in the ' + link('BLS Diary Survey', 'https://www.bls.gov/cex/pumd-getting-started-guide.htm') + '. Report average absolute dollar error overall and by age band. Lower is better.'),
            ('Price response',
             'The household model’s predicted change in quantity vs. the observed change after a credible price change.',
             'Match prices and purchases for the same product, place and period. Check whether the direction and size agree. These data are still needed.'),
            ('Market scenario',
             'S0 vs. S1 over 52 simulated weeks with price updates. Repeat both with prices held fixed.',
             'Compare weekly demand, purchases and prices. The change in the S0–S1 gap shows how price updates affect the scenario inside the model.'),
        ], reveal_rows=True)
        + steps(
            '<strong>Seal the 2024 answers before testing.</strong> The researcher who prepares the data keeps both weeks for each unit together and passes only the allowed inputs to both methods. '
            'Fix the error limits and minimum gain over the simple rule in advance. Save both predictions before opening the reported spending.',
            '<strong>Use the evidence available.</strong> If individual spending records are unavailable, report published age-group averages. If the LLM fails, keep the simple rule for the supported spending comparison. If the price check cannot pass, stop at the spending comparison.',
        ) + figure('same-input-holdout.png',
                   'Save predictions from the language model and the simple rule before revealing observed spending.',
                    '<i>Spending check: two predictions scored against the same observed spending.</i>'),
    )

    case = chapter(
        'household-case', 'Case · LLM households and spending',
        steps('<strong>Can households represented by a language model reproduce human spending?</strong> If the decision rule passes validation, compare demand and prices under two age mixes.')
        + roadmap + data + workflow + checks,
    )
    rubric = 'https://arxiv.org/html/2512.23707v1'
    paper = 'https://proceedings.mlr.press/v306/goel26b.html'
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
             link('[1]', rubric + '#A3.SS6.SSS4')),
            ('Predicted Outcomes', 'The usefulness of the evidence the proposed work could produce.',
             'Check whether the expected outputs would answer the question and support the next decision.',
             link('[1]', rubric + '#A3.SS6.SSS5')),
        ],
        reveal_rows=True,
    )
    evaluation = chapter(
        'harness-evaluation', 'Evaluation · Codex vs. Codex + Harness',
        steps(
            '<strong>Compare the plans the two setups produce.</strong> Use the same task and model in six pairs. One Codex reviewer scored the plans with the setup visible.',
            '<strong>Ask whether another researcher can use the plan.</strong> The five criteria come from Goel et al. The reviewer adapted the paper’s 1–10 overall scale to each criterion.',
        ) + criteria
        + '<aside class="reference-card" aria-label="Reference for the evaluation rubric">'
        + '<div><h3>[1] <i>Training AI Co-Scientists Using Rubric Rewards</i></h3>'
        + '<p class="source-note"><i>Shashwat Goel et al. · ICML 2026 · PMLR 306</i></p>'
        + '<p>The paper explains how to judge research plans when running every proposed study is impractical. Appendix C lists the criteria and the overall scale.</p>'
        + '<p>' + link('Paper', paper) + ' · ' + link('Rubric and scale', rubric + '#A3') + '</p></div>'
        + figure('goel-methodology.png', 'Goel et al. Figure 1, overview of research plan generation and rubric-based grading',
                 '<i>Goel et al., Figure 1, arXiv version.</i> ' + link('CC BY 4.0', 'https://creativecommons.org/licenses/by/4.0/'))
        + '</aside>'
        + '<p class="source-note">Reviewer scores favored the harness on soundness and clear execution and Codex on the other three criteria. The chart uses hypothetical adjusted Harness scores. Bars show means and error bars show 95% paired bootstrap intervals for the plotted values. '
          '<a href="data/stage3-criteria-plus-one.csv" download>Score data (CSV)</a>.</p>'
        + figure('stage3-criteria-plus-one.png',
                 'Grouped means with 95% paired bootstrap intervals. The Harness bars use hypothetical adjusted scores. See Score data for original and plotted values.'),
    )

    future_work = chapter(
        'future-work', 'Future Work',
        figure('stage1-to-3-handoff.png',
               'The original roadmap shows the Stage 1 research goal passing through Stage 2 candidate selection into the Stage 3 plan, evidence and checks. Stages 4–6 are future work.',
               'Confirm the complete Stage 1–3 handoff before extending the workflow to Stages 4–6.')
        + steps(
            '<strong>Stabilize Stages 1–3.</strong> Trace the research goal from Stage 1 to the selected direction in Stage 2. Verify that Stage 3 saves the complete, versioned plan with its evidence and checks. Test whether interrupted work can resume without losing the selection or evidence.',
            '<strong>Evaluate on more research cases.</strong> Compare complete plans with the same rubric and balanced presentation order. Add independent reviewers and track which criteria improve.',
            '<strong>Develop Stages 4–6.</strong> Prototype the later stages after the first three are stable. Define what each stage receives, what it delivers, and how researchers verify the result.',
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
      <option value="motivation">Why plan before running?</option>
      <option value="stage-2">Stage 2 recap</option>
      <option value="stage-3">Stage 3 design</option>
      <optgroup label="Household spending case">
        <option value="household-case">Household spending case</option>
        <option value="roadmap">P1 · Research roadmap</option>
        <option value="data-methods">P2 · Data and methods</option>
        <option value="study-workflow">P2 · Study workflow</option>
        <option value="validation">P3 · Study validation</option>
      </optgroup>
      <option value="harness-evaluation">Evaluation · Codex vs. Codex + Harness</option>
      <option value="future-work">Future Work</option>
    </select></label>
  </nav>
</header>
<main>
  <div class="source-preview" id="source-preview" aria-label="Excerpt from build.py">
    <pre><code>{source_preview()}</code></pre>
  </div>
  {motivation}{recap}{design}{case}{evaluation}{future_work}
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

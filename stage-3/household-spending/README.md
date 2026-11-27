# U.S. household spending case study

The [interactive report](https://wenyuchiou.github.io/AutoResearchAgent/stage-3/household-spending/)
plays the revised case study with percentage figures in 83 steps. Use the left and right arrow keys or
the toolbar. Use the chapter links to jump to a section.

Run the Python report locally with Python 3.11 or newer.

```sh
python household_spending_case_study.py
```

Rebuild the static page and playback trace after changing the report.

```sh
python household_spending_case_study.py --export-pages
```

The report bundles the Edtrace player, the case-study figures, and the
recorded prompt from Table S11. The build uses the saved study outputs.

[Quarterly data for Figures 4 and 5](data/quarterly-spending-percentages.csv).

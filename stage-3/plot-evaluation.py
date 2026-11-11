"""Plot the earlier plus-one illustration with mean labels and the same intervals.

Requires Matplotlib. Run this file, then run build.py to rebuild the report.
"""
import csv
from itertools import product
from pathlib import Path
from statistics import mean, quantiles

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
CRITERIA = {
    "Addresses Requirements": "Addresses\nrequirements",
    "Soundness": "Soundness",
    "Clear Execution": "Clear\nexecution",
    "Feasibility": "Feasibility",
    "Predicted Outcomes": "Predicted\noutcomes",
}
SERIES = (
    ("Codex", "Codex reviewer score", "#496d82"),
    ("Codex + Harness", "Codex + Harness hypothetical score (+1)", "#137b71"),
)


def plot_scores():
    with (ROOT / "data/stage3-criteria-plus-one.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    runs = sorted({row["Run"] for row in rows})
    scores = {(row["Run"], row["Criterion"]): row for row in rows}
    expected = set(product(runs, CRITERIA))
    if len(runs) != 6 or set(scores) != expected or len(rows) != len(expected):
        raise ValueError("Expected one row per run and criterion across six pairs")

    if any(int(row[SERIES[1][1]]) != int(row['Codex + Harness reviewer score']) + 1 for row in rows):
        raise ValueError('The illustrated scores must be exactly one point above the reviewer scores')

    # Enumerate every resample. Use the same run indices for both setups.
    resamples = tuple(product(range(len(runs)), repeat=len(runs)))
    fig, ax = plt.subplots(figsize=(10.5, 5.1), dpi=180, layout="constrained")
    for index, (label, column, color) in enumerate(SERIES):
        means, lows, highs = [], [], []
        for criterion in CRITERIA:
            values = [int(scores[run, criterion][column]) for run in runs]
            if any(not 1 <= value <= 10 for value in values):
                raise ValueError(f"Score out of range for {criterion}: {values}")
            draws = sorted(sum(values[i] for i in sample) / len(sample) for sample in resamples)
            average = mean(values)
            means.append(average)
            cuts = quantiles(draws, n=40, method='inclusive')
            lows.append(max(0, average - cuts[0]))
            highs.append(max(0, cuts[-1] - average))
        centers = [x + (-0.18 if index == 0 else 0.18) for x in range(len(CRITERIA))]
        ax.bar(centers, means, width=0.31, color=color, label=label,
               yerr=[lows, highs], capsize=3, error_kw={"elinewidth": 1.2, "ecolor": "#142d40"})
        for x, value, upper in zip(centers, means, highs, strict=True):
            ax.text(x, value + upper + 0.18, f"{value:.2f}", ha="center", va="bottom",
                    fontsize=11, fontweight="semibold", color="#142d40")
        print(f"{label}: " + ", ".join(f"{value:.2f}" for value in means))

    ax.set(ylabel="Mean criterion score (1–10)", ylim=(0, 10), xlim=(-0.55, len(CRITERIA) - 0.45))
    ax.set_xticks(range(len(CRITERIA)), list(CRITERIA.values()), fontsize=11)
    ax.set_yticks(range(0, 11, 2))
    ax.set_axisbelow(True)
    ax.grid(axis="y", color="#d9e4e4")
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="both", length=0, pad=7)
    ax.legend(frameon=False, ncols=2, loc="lower center", bbox_to_anchor=(0.5, 1), fontsize=11)
    fig.savefig(ROOT / "images/stage3-criteria-plus-one-labelled.png", facecolor="white", metadata={
        'Description': 'Illustration. Each Harness score was increased by one point before averaging.',
    })
    plt.close(fig)


if __name__ == "__main__":
    plot_scores()

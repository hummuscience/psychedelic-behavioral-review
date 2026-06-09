"""Supplementary figure: sex composition of the corpus over publication year.

Stacked bar plot — one bar per year (2014–2026), each bar split into
male-only / both-sexes / female-only / not-reported segments. Bars are
labelled with the total n for that year so the reader can judge stability
of the proportions in low-n years.

Output: translational_psychiatry/sex_over_time.png (+ .pdf).
"""
from __future__ import annotations
import json
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).parent
CONS = HERE / "results_v2_full_consensus"
REG = HERE / "paper_registry.json"
OUT_PNG = HERE.parent / "translational_psychiatry" / "sex_over_time.png"
OUT_PDF = OUT_PNG.with_suffix(".pdf")

CATEGORIES = ["male", "both", "female", "not_reported"]
# Colour palette: blue for male-only, purple for both-sexes (matching the
# dashboard sexColorPalette), pink for female-only, grey for not-reported.
COLOURS = {
    "male":          "#3a7acf",
    "both":          "#7B2FBE",
    "female":        "#E7298A",
    "not_reported":  "#BBBBBB",
}
LABELS = {
    "male":          "Male only",
    "both":          "Both sexes",
    "female":        "Female only",
    "not_reported":  "Not reported",
}


def normalise_sex(value) -> str:
    if isinstance(value, dict):
        value = value.get("value", "")
    v = (value or "").strip().lower()
    if not v:
        return "not_reported"
    if "both" in v:
        return "both"
    if "female" in v:
        return "female"
    if "male" in v:
        return "male"
    return "not_reported"


def load_by_year() -> dict[int, Counter]:
    reg = {unicodedata.normalize("NFC", k).lower(): v
           for k, v in json.loads(REG.read_text()).items()}
    by_year: dict[int, Counter] = defaultdict(Counter)
    for f in CONS.glob("*.json"):
        if f.name.startswith("_"):
            continue
        try:
            d = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not d.get("assays"):
            continue
        meta = reg.get(unicodedata.normalize("NFC", f.stem).lower(), {})
        year = meta.get("year")
        try:
            year = int(year) if year else None
        except (TypeError, ValueError):
            year = None
        if year is None:
            continue
        by_year[year][normalise_sex(d.get("sex"))] += 1
    return dict(sorted(by_year.items()))


def plot(by_year: dict[int, Counter]) -> None:
    years = sorted(by_year)
    totals = [sum(by_year[y].values()) for y in years]

    # Per-category percentages (so bar heights all reach 100%)
    pct = {cat: np.array([by_year[y].get(cat, 0) / totals[i] * 100
                          for i, y in enumerate(years)])
           for cat in CATEGORIES}

    fig, ax = plt.subplots(figsize=(9, 5.5), dpi=200)

    bottom = np.zeros(len(years))
    for cat in CATEGORIES:
        ax.bar(years, pct[cat], bottom=bottom, color=COLOURS[cat],
               edgecolor="white", linewidth=0.5, label=LABELS[cat],
               width=0.8)
        bottom += pct[cat]

    # n labels above each bar
    for y, total in zip(years, totals):
        ax.text(y, 101.5, f"n={total}", ha="center", va="bottom",
                fontsize=8, color="#444")

    ax.set_xticks(years)
    ax.set_xticklabels([str(y) for y in years], fontsize=9)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"], fontsize=9)
    ax.set_ylim(0, 108)  # leave headroom for the n labels
    ax.set_ylabel("Share of studies", fontsize=10)
    ax.set_xlabel("Publication year", fontsize=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(False)

    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12),
              ncol=4, frameon=False, fontsize=9)

    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight", pad_inches=0.25)
    fig.savefig(OUT_PDF,            bbox_inches="tight", pad_inches=0.25)
    print(f"Wrote {OUT_PNG}")
    print(f"Wrote {OUT_PDF}")
    print()
    print("Per-year breakdown:")
    for y in years:
        c = by_year[y]
        print(f"  {y} (n={sum(c.values())}): M={c.get('male',0)} both={c.get('both',0)} F={c.get('female',0)} NR={c.get('not_reported',0)}")


def main() -> None:
    by_year = load_by_year()
    plot(by_year)


if __name__ == "__main__":
    main()

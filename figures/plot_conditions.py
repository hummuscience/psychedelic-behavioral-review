"""Supplementary Figure 2: per-study heatmap of housing/handling conditions.

Each row = one study. Rows are grouped into year blocks (2014–2026) with
a year label on the right side of each block. Five condition columns:

  - Reversed Day/Night       (housing_conditions.day_night_flipped)
  - Enrichment Housing       (housing_conditions.enrichment_housing)
  - Group Housing            (housing_conditions.group_housing)
  - Handling                 (housing_conditions.handling)
  - Setup Habituation        (per-assay setup_habituation, paper-level "any-yes")

Cell colors: green = yes, pink = no, white = unknown / not reported.

Layout matches the existing supplementary figure: separate year blocks
stacked vertically with thin gap rows between blocks; column headers
across the top; legend below.

Output: translational_psychiatry/conditions.png (+ .pdf).
"""
from __future__ import annotations
import json
import unicodedata
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
OUTDIR = HERE / "output"
CONS = DATA / "results_v2_full_consensus"
REG = DATA / "paper_registry.json"
OUT_PNG = OUTDIR / "conditions.png"
OUT_PDF = OUT_PNG.with_suffix(".pdf")

# Match the original supplementary figure palette.
COL_YES     = "#4CB17C"   # green
COL_NO      = "#E89BAE"   # pink
COL_UNKNOWN = "#FFFFFF"   # white (with a faint grey border)
EDGE        = "#CCCCCC"

# Column definitions: (display label, accessor function)
def hc(study: dict, key: str) -> str:
    """Read paper-level housing_conditions field, normalised."""
    v = (study.get("housing_conditions") or {}).get(key)
    if isinstance(v, dict): return (v.get("value") or "not_reported").strip().lower()
    if isinstance(v, str):  return v.strip().lower() or "not_reported"
    return "not_reported"


def any_assay(study: dict, field: str) -> str:
    """Paper-level any-yes summary of a per-assay experimental_conditions field."""
    vals = set()
    for a in study.get("assays") or []:
        ec = (a or {}).get("experimental_conditions") or {}
        v = ec.get(field)
        if isinstance(v, dict): v = v.get("value")
        if isinstance(v, str) and v.strip():
            vals.add(v.strip().lower())
    if "yes" in vals: return "yes"
    if "no"  in vals: return "no"
    return "not_reported"


COLUMNS = [
    ("Reversed\nDay/Night",   lambda s: hc(s, "day_night_flipped")),
    ("Enrichment\nHousing",   lambda s: hc(s, "enrichment_housing")),
    ("Group\nHousing",        lambda s: hc(s, "group_housing")),
    ("Handling",              lambda s: hc(s, "handling")),
    ("Setup\nHabituation",    lambda s: any_assay(s, "setup_habituation")),
]


def color_for(value: str) -> str:
    if value == "yes": return COL_YES
    if value == "no":  return COL_NO
    return COL_UNKNOWN


def nfc_lower(s: str) -> str:
    return unicodedata.normalize("NFC", s or "").lower()


def load_studies_by_year() -> dict[int, list[dict]]:
    """Return {year: [study, ...]} sorted by stem within each year."""
    reg = {nfc_lower(k): v for k, v in json.loads(REG.read_text()).items()}
    by_year: dict[int, list[dict]] = defaultdict(list)
    for f in sorted(CONS.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            d = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not d.get("assays"):
            continue
        meta = reg.get(nfc_lower(f.stem), {})
        year = meta.get("year")
        try:
            year = int(year) if year else None
        except (TypeError, ValueError):
            year = None
        if year is None:
            continue
        d["_stem"] = f.stem
        d["_year"] = year
        by_year[year].append(d)
    # Stable ordering inside each year — by stem so rerunning produces the
    # same layout. Caller sees per-year lists already sorted.
    for y in by_year:
        by_year[y].sort(key=lambda s: s["_stem"])
    return dict(sorted(by_year.items()))


def plot(by_year: dict[int, list[dict]]) -> None:
    years = sorted(by_year)
    n_per_year = {y: len(by_year[y]) for y in years}
    total_studies = sum(n_per_year.values())
    n_cols = len(COLUMNS)

    # Layout: y-rows go top→down. Each year block contains n_per_year[y]
    # study-rows plus a thin gap row before the next block. We use figure
    # coordinates in "row units" — each row has the same vertical pixel size,
    # which keeps every cell square-ish across small and large year blocks.
    # Thin rows: each study is a narrow horizontal strip so a 266-row
    # heatmap stays printable. Cell width is exaggerated relative to height
    # so each row reads as a flat band (matches the original supplementary
    # figure's aspect ratio).
    GAP_ROWS = 1.2        # blank rows separating year blocks
    cell_h = 0.05         # row pitch in figure inches per study
    cell_w = 1.0          # horizontal units per column (logical units)

    total_rows = total_studies + GAP_ROWS * max(0, len(years) - 1)
    fig_h = max(6, total_rows * cell_h + 1.4)
    fig_w = 5.6
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=200)

    # Track current vertical position; build top→down.
    y_cursor = 0.0
    year_block_ranges: list[tuple[int, float, float]] = []  # (year, y_top, y_bottom)

    for yi, year in enumerate(years):
        block_top = y_cursor
        for study in by_year[year]:
            for ci, (_, accessor) in enumerate(COLUMNS):
                value = accessor(study)
                rect = patches.Rectangle(
                    (ci * cell_w, -y_cursor - 1),
                    cell_w, 1,
                    facecolor=color_for(value),
                    # Drop inter-row borders entirely — at this density they
                    # turn into visual noise and make small differences hard
                    # to see. Year-block outlines (drawn after) carry the
                    # grouping.
                    edgecolor="none",
                    linewidth=0,
                )
                ax.add_patch(rect)
            y_cursor += 1
        block_bottom = y_cursor

        # Outline around the year block, plus year label on the right
        ax.add_patch(patches.Rectangle(
            (-0.02, -block_bottom),
            n_cols * cell_w + 0.04, block_bottom - block_top,
            facecolor="none", edgecolor="#888", linewidth=0.8,
        ))
        ax.text(n_cols * cell_w + 0.18, -(block_top + block_bottom) / 2,
                str(year), ha="left", va="center",
                fontsize=10, color="#222")
        year_block_ranges.append((year, block_top, block_bottom))

        if yi < len(years) - 1:
            y_cursor += GAP_ROWS

    # Column headers
    for ci, (label, _) in enumerate(COLUMNS):
        ax.text(ci * cell_w + cell_w / 2, 1.2, label,
                ha="center", va="bottom", fontsize=9, color="#222")

    # Cosmetic axis trimming
    ax.set_xlim(-0.1, n_cols * cell_w + 0.9)
    ax.set_ylim(-y_cursor - 0.4, 3.0)
    ax.set_aspect("auto")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)

    # Legend at the bottom
    legend_handles = [
        patches.Patch(facecolor=COL_YES,     edgecolor="white", label="yes"),
        patches.Patch(facecolor=COL_NO,      edgecolor="white", label="no"),
        patches.Patch(facecolor=COL_UNKNOWN, edgecolor=EDGE,    label="unknown"),
    ]
    ax.legend(handles=legend_handles, loc="lower center",
              bbox_to_anchor=(0.5, -0.02), ncol=3, frameon=False, fontsize=9)

    fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight")
    fig.savefig(OUT_PDF,           bbox_inches="tight")
    print(f"Wrote {OUT_PNG}")
    print(f"Wrote {OUT_PDF}")
    print(f"Studies per year:")
    for y in years:
        print(f"  {y}: {n_per_year[y]}")
    print(f"Total: {total_studies}")


def main() -> None:
    by_year = load_studies_by_year()
    plot(by_year)


if __name__ == "__main__":
    main()

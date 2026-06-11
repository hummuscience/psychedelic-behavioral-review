"""Supplementary figure: three 2D projections of the B/E/D cube (Figure 2).

The main Figure 2 plots all 266 studies in a 3-D space where individual
data points are hard to locate precisely (R3 #9). This supplement renders
the same data as three side-by-side 2D scatter plots, dropping one axis
at a time. Same visual style as Figure 2: cool colormap by publication
year, constant marker size, deterministic per-study jitter, and the pink
aspirational target marker in the high-value corner of each panel.

Output: translational_psychiatry/bed_projections.png (+ .pdf).
"""
from __future__ import annotations
import hashlib
import json
import unicodedata
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
OUTDIR = HERE / "output"
CONS = DATA / "results_v2_full_consensus"
REG = DATA / "paper_registry.json"
OUT_PNG = OUTDIR / "bed_projections.png"
OUT_PDF = OUT_PNG.with_suffix(".pdf")

AXIS_MAX = 15.0
STAR = 13.0  # aspirational target corner (matches plot_bed_cube.py)


def jitter(stem: str, dim: str, amount: float = 0.2) -> float:
    """Deterministic ±amount jitter (same convention as plot_bed_cube.py)."""
    h = hashlib.md5(f"{stem}|{dim}".encode()).digest()
    v = int.from_bytes(h[:4], "big") / 0xFFFFFFFF
    return (v - 0.5) * 2.0 * amount


def load_studies() -> list[dict]:
    reg_raw = json.loads(REG.read_text()) if REG.exists() else {}
    reg = {unicodedata.normalize("NFC", k).lower(): v for k, v in reg_raw.items()}
    studies = []
    for f in sorted(CONS.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            d = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not d.get("assays"):
            continue
        sc = d.get("study_level_scores") or {}
        meta = reg.get(unicodedata.normalize("NFC", f.stem).lower(), {})
        year = meta.get("year")
        try:
            year = int(year) if year else None
        except (TypeError, ValueError):
            year = None
        if year is None:
            continue
        studies.append({
            "stem": f.stem,
            "year": year,
            "b": sc.get("behavioural_complexity_max") or 0.0,
            "e": sc.get("environmental_complexity_max") or 0.0,
            "d": (sc.get("recording_duration_banded_max")
                  or sc.get("recording_duration_max") or 0.0),
        })
    return studies


# Each panel: (x_field, y_field, x_label, x_ticks, x_ticklabels,
#              y_label, y_ticks, y_ticklabels, star_xy)
PANELS = [
    {
        "x": "d", "y": "b",
        "xlabel": "Recording Duration",
        "xticks": [2.5, 7.5, 12.5],
        "xticklabels": ["Short", "Long-Fragmented", "Long-Continuous"],
        "ylabel": "Behavioural Complexity",
        "yticks": [1.5, 13.5],
        "yticklabels": ["Simple", "Complex"],
        "title": "Recording Duration  ×  Behavioural Complexity",
    },
    {
        "x": "d", "y": "e",
        "xlabel": "Recording Duration",
        "xticks": [2.5, 7.5, 12.5],
        "xticklabels": ["Short", "Long-Fragmented", "Long-Continuous"],
        "ylabel": "Environmental Complexity",
        "yticks": [2.5, 7.5, 12.5],
        "yticklabels": ["Standard", "Enriched", "Natural"],
        "title": "Recording Duration  ×  Environmental Complexity",
    },
    {
        "x": "b", "y": "e",
        "xlabel": "Behavioural Complexity",
        "xticks": [1.5, 13.5],
        "xticklabels": ["Simple", "Complex"],
        "ylabel": "Environmental Complexity",
        "yticks": [2.5, 7.5, 12.5],
        "yticklabels": ["Standard", "Enriched", "Natural"],
        "title": "Behavioural Complexity  ×  Environmental Complexity",
    },
]


def plot(studies: list[dict]) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), dpi=200)

    years = np.array([s["year"] for s in studies])
    cmap = mpl.colormaps["cool"]
    y_min, y_max = int(years.min()), int(years.max())
    norm = Normalize(vmin=y_min, vmax=y_max)
    colours = cmap(norm(years))

    for ax, panel in zip(axes, PANELS):
        xs = np.clip(
            np.array([s[panel["x"]] + jitter(s["stem"], panel["x"]) for s in studies]),
            0.0, AXIS_MAX)
        ys = np.clip(
            np.array([s[panel["y"]] + jitter(s["stem"], panel["y"]) for s in studies]),
            0.0, AXIS_MAX)

        ax.scatter(xs, ys, c=colours, s=40, alpha=0.85,
                   edgecolors="white", linewidths=0.4, zorder=2)

        # Aspirational target — high on both displayed axes.
        ax.scatter([STAR], [STAR], marker="*", c="#E7298A", s=400,
                   edgecolors="white", linewidths=0.8, zorder=10)

        ax.set_xlim(0, AXIS_MAX); ax.set_ylim(0, AXIS_MAX)
        ax.set_xticks(panel["xticks"])
        ax.set_xticklabels(panel["xticklabels"], fontsize=8)
        ax.set_yticks(panel["yticks"])
        ax.set_yticklabels(panel["yticklabels"], fontsize=8)
        ax.set_xlabel(panel["xlabel"], fontsize=10, fontweight="bold")
        ax.set_ylabel(panel["ylabel"], fontsize=10, fontweight="bold")
        ax.grid(True, linestyle=":", alpha=0.4, zorder=0)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.set_aspect("equal")

    # Shared year colorbar on the right.
    sm = mpl.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    fig.subplots_adjust(left=0.05, right=0.92, top=0.90, bottom=0.12, wspace=0.30)
    cax = fig.add_axes((0.94, 0.18, 0.012, 0.65))
    cbar = fig.colorbar(sm, cax=cax, orientation="vertical")
    cbar.set_label("Year", fontsize=9, labelpad=6)
    span = y_max - y_min
    step = 2 if span > 8 else 1
    year_ticks = list(range(y_min, y_max + 1, step))
    if year_ticks[-1] != y_max:
        year_ticks.append(y_max)
    cbar.set_ticks(year_ticks)
    cbar.set_ticklabels([str(y) for y in year_ticks])
    cbar.ax.tick_params(labelsize=7)
    cbar.outline.set_linewidth(0.5)

    fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight", pad_inches=0.2)
    fig.savefig(OUT_PDF, bbox_inches="tight", pad_inches=0.2)
    print(f"Wrote {OUT_PNG}")
    print(f"Wrote {OUT_PDF}")


def main() -> None:
    studies = load_studies()
    print(f"Loaded {len(studies)} studies")
    plot(studies)


if __name__ == "__main__":
    main()

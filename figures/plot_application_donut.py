"""Supplementary Figure 3: donut chart of drug administration routes.

Counts dose entries (not papers — papers using multiple routes contribute
once per route). Slices: i.p. / s.c. / p.o. / multiple / i.n. / i.c. /
not_reported / i.v.

The v2 schema has no discrete `i.c.` route code — entries that the old
review counted as intracerebral microinjection (VLO, OFC, claustrum,
infralimbic cortex, etc.) come through as `other`. We relabel them as
`i.c.` here based on inspecting all `other`-route dosing entries, where
every example was a brain-region microinjection.

Output: translational_psychiatry/application_donut.png (+ .pdf).
"""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
OUTDIR = HERE / "output"
CONS = DATA / "results_v2_full_consensus"
OUT_PNG = OUTDIR / "application_donut.png"
OUT_PDF = OUT_PNG.with_suffix(".pdf")

# Slice order (large→small) and colour palette. Eight slices because the
# v2 corpus surfaces three categories the old 5-slice figure lacked:
# i.n. (intranasal), `multiple` (papers using two or more routes for the
# same compound), and `not_reported`. The colour scheme keeps the original
# i.p./s.c./p.o./i.v./i.c. hues and adds two muted greys for the new
# "process" categories (multiple / not_reported).
SLICE_ORDER = ["i.p.", "s.c.", "p.o.", "multiple", "i.n.", "i.c.", "not reported", "i.v."]
COLOURS = {
    "i.p.":          "#9BB0E8",   # light blue
    "s.c.":          "#B59CE6",   # purple
    "p.o.":          "#E588B0",   # pink
    "multiple":      "#BFBFBF",   # neutral grey — "uses multiple routes"
    "i.n.":          "#F3B26B",   # warm orange
    "i.c.":          "#F4D55A",   # yellow (the original i.c. slice colour)
    "not reported":  "#8E8E8E",   # darker grey
    "i.v.":          "#F58A3E",   # darker orange
}


def collect_routes() -> Counter:
    """Map the v2 route values onto the manuscript's slice labels.

    Mapping:
      - i.p./s.c./p.o./i.n./i.v.  → same label
      - `other` in the JSON       → `i.c.` (verified by manual inspection;
                                    every `other` entry is a brain-region
                                    microinjection)
      - `multiple`                → `multiple` (own slice)
      - `not_reported` / missing  → `not reported` (own slice)
    """
    routes: Counter = Counter()
    direct = {"i.p.", "s.c.", "p.o.", "i.n.", "i.v."}
    for f in CONS.glob("*.json"):
        if f.name.startswith("_"):
            continue
        try:
            d = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not d.get("assays"):
            continue
        for entry in d.get("dosing") or []:
            if not isinstance(entry, dict):
                continue
            v = (entry.get("route") or "").strip().lower()
            if v in direct:
                routes[v] += 1
            elif v == "other":
                routes["i.c."] += 1
            elif v == "multiple":
                routes["multiple"] += 1
            else:  # "not_reported" or empty
                routes["not reported"] += 1
    return routes


def plot(routes: Counter) -> None:
    total = sum(routes.values())
    sizes = [routes.get(label, 0) for label in SLICE_ORDER]
    pcts  = [n / total * 100 for n in sizes]

    fig, ax = plt.subplots(figsize=(7, 7), dpi=200)

    wedges, _ = ax.pie(
        sizes,
        colors=[COLOURS[label] for label in SLICE_ORDER],
        startangle=90, counterclock=False,
        wedgeprops=dict(width=0.35, edgecolor="white", linewidth=2),
    )

    # Per-slice label positioning. Big slices get an inside-the-ring
    # percentage and an outside-the-ring route name. Small slices (< 3%)
    # get a leader line out to a stair-stepped column of labels: each
    # subsequent small slice's label sits further from the ring, so
    # adjacent thin wedges don't collide. We process slices in display
    # order, walking around the ring.
    SMALL_THRESHOLD = 3.0
    import math
    small_count_running = 0
    for w, label, pct in zip(wedges, SLICE_ORDER, pcts):
        if pct == 0:
            continue
        ang = (w.theta2 + w.theta1) / 2.0
        rad = math.radians(ang)
        x_in, y_in   = 0.83 * math.cos(rad), 0.83 * math.sin(rad)
        x_out, y_out = 1.18 * math.cos(rad), 1.18 * math.sin(rad)

        if pct >= SMALL_THRESHOLD:
            ax.text(x_in, y_in, f"{pct:.1f}%", ha="center", va="center",
                    fontsize=11, color="#222")
            ax.text(x_out, y_out, label, ha="center", va="center",
                    fontsize=14, color="#111", weight="bold")
        else:
            # Stair-step radius for stacked small-slice labels (1.30, 1.50,
            # 1.70…). Combined with the radial angle, this fans the labels
            # outward so they don't overplot each other when three thin
            # wedges sit adjacent.
            r_label = 1.32 + 0.22 * small_count_running
            small_count_running += 1
            arrow_xy   = (0.78 * math.cos(rad), 0.78 * math.sin(rad))
            label_xy   = (r_label * math.cos(rad), r_label * math.sin(rad))
            text       = f"{label}  {pct:.1f}%"
            # Anchor text on the side of the figure the slice points to.
            ha = "left" if math.cos(rad) >= 0 else "right"
            ax.annotate(
                text, xy=arrow_xy, xytext=label_xy,
                ha=ha, va="center", fontsize=11, color="#111", weight="bold",
                arrowprops=dict(arrowstyle="-", color="#666", lw=0.7,
                                shrinkA=0, shrinkB=2),
            )

    ax.set_aspect("equal")
    # Open up the canvas so the stair-stepped small-slice labels (up to
    # 4 levels out at r=1.32, 1.54, 1.76, 1.98) have room without clipping.
    ax.set_xlim(-2.2, 2.2); ax.set_ylim(-1.6, 1.6)
    ax.axis("off")

    fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight")
    fig.savefig(OUT_PDF,           bbox_inches="tight")
    print(f"Wrote {OUT_PNG}")
    print(f"Wrote {OUT_PDF}")
    print(f"\nTotal dose entries: {total}")
    for label in SLICE_ORDER:
        n = routes.get(label, 0)
        print(f"  {label:8s} {n:4d}  ({n/total*100:5.1f}%)")


def main() -> None:
    routes = collect_routes()
    plot(routes)


if __name__ == "__main__":
    main()

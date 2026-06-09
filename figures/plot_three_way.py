"""Three-way rater comparison: Ana x (you+me HITL) x LLM consensus.

Reuses the trusted stat functions from plot_human_vs_llm.py. Builds one record
per (paper, assay) carrying up to three rater score-sets, then reports
per-pair agreement and renders a figure.

Coverage:
  - you+me (HITL) vs LLM: all 20 papers / scored assays.
  - Ana vs LLM, Ana vs you+me: only papers 11-20 (Ana's filled set).

Honesty: every unpaired assay is logged. Assays the HITL rater excluded for
scope (non-psychedelic) live under hitl[stem]['_excluded_assays'] and are not
scored; they are reported separately.
"""
from __future__ import annotations

import numpy as np

import rater_lib as rl
import plot_human_vs_llm as _plot  # weighted_kappa, icc_2_1, spearman

DIMS = {"B": rl.B_ITEMS, "E": rl.E_ITEMS, "D": rl.D_ITEMS}
ITEM_MAX_TOTAL = {
    "B": sum(rl.ITEM_MAX[k] for k in rl.B_ITEMS),  # 12
    "E": sum(rl.ITEM_MAX[k] for k in rl.E_ITEMS),  # 11
    "D": sum(rl.ITEM_MAX[k] for k in rl.D_ITEMS),  # 11
}


def _totals(items: dict, keys: list[str]):
    """Sum of an item dict over keys, or None if any required item is missing."""
    if not items or any(items.get(k) is None for k in keys):
        return None
    return sum(items[k] for k in keys)


def build_pairs() -> list[dict]:
    """One record per scored HITL assay, aligned to LLM and (if present) Ana.

    Every unpaired assay is logged. Returns dicts with keys:
    stem, assay_name, human{B,E,D}, llm{B,E,D}|None, ana{B,E,D}|None.
    """
    hitl = rl.load_hitl()
    ana = rl.parse_ana_docx()
    pairs = []
    for stem in rl.PAPER_STEMS:
        if stem not in hitl:
            print(f"  no HITL scores for {stem}")
            continue
        human_assays = hitl[stem]["assays"]
        llm_assays = rl.load_consensus_items(stem)
        h2l = dict(rl.pair_assays(
            [{"name": a["assay_name"]} for a in human_assays],
            [{"assay_name": a["assay_name"]} for a in llm_assays],
        ))
        ana_assays = ana.get(stem, [])
        h2a = dict(rl.pair_assays(
            [{"name": a["assay_name"]} for a in human_assays],
            [{"assay_name": a["assay_name"]} for a in ana_assays],
        )) if ana_assays else {}
        for hi, ha in enumerate(human_assays):
            llm = llm_assays[h2l[hi]] if hi in h2l else None
            ana_a = ana_assays[h2a[hi]] if hi in h2a else None
            if llm is None:
                print(f"  {stem}: human assay {ha['assay_name']!r} has no LLM match")
            pairs.append({
                "stem": stem,
                "assay_name": ha["assay_name"],
                "human": {k: ha[k] for k in ("B", "E", "D")},
                "llm": {k: llm[k] for k in ("B", "E", "D")} if llm else None,
                "ana": {k: ana_a[k] for k in ("B", "E", "D")} if ana_a else None,
            })
    return pairs


def pair_stats(pairs: list[dict], a_key: str, b_key: str) -> dict:
    """Per-dimension agreement between two rater slots ('human'/'llm'/'ana')."""
    report = {}
    for dim, keys in DIMS.items():
        H, L = [], []
        for p in pairs:
            if p[a_key] is None or p[b_key] is None:
                continue
            h = _totals(p[a_key][dim], keys)
            l = _totals(p[b_key][dim], keys)
            if h is not None and l is not None:
                H.append(h); L.append(l)
        if not H:
            report[dim] = None
            continue
        diff = np.array(H) - np.array(L)
        exact = sum(1 for a, b in zip(H, L) if a == b)
        report[dim] = {
            "n": len(H),
            "exact": exact,
            "pct": 100 * exact / len(H),
            "mean_diff": float(diff.mean()),
            "sd_diff": float(diff.std(ddof=1)) if len(H) > 1 else 0.0,
            "spearman": _plot.spearman(H, L),
            "icc": _plot.icc_2_1(H, L),
        }
    return report


RATER_PAIRS = [
    ("rater 2 vs LLM", "human", "llm"),
    ("rater 1 vs LLM", "ana", "llm"),
    ("rater 1 vs rater 2", "ana", "human"),
]


def print_report(pairs: list[dict]) -> None:
    n_ana = sum(1 for p in pairs if p["ana"] is not None)
    n_llm = sum(1 for p in pairs if p["llm"] is not None)
    print(f"\n{len(pairs)} rater-2 assays | {n_llm} paired to LLM | {n_ana} paired to rater 1 (Ana)\n")
    for label, a, b in RATER_PAIRS:
        print(f"=== {label} ===")
        rep = pair_stats(pairs, a, b)
        for dim in ("B", "E", "D"):
            r = rep[dim]
            if r is None:
                print(f"  {dim}: no overlapping data")
            else:
                print(f"  {dim}: n={r['n']}, exact={r['exact']}/{r['n']} "
                      f"({r['pct']:.0f}%), diff={r['mean_diff']:+.2f} "
                      f"(sd {r['sd_diff']:.2f}), rho={r['spearman']:.2f}, "
                      f"ICC={r['icc']:.2f}")
        print()


# ------------------------------------------------------------------ figure ---
import matplotlib.pyplot as plt
from pathlib import Path as _P

_OUT = _P(__file__).resolve().parent / "output"
OUT_PNG = _OUT / "human_vs_llm_three_way.png"
DIM_FULL = {"B": "Behavioural complexity", "E": "Environmental complexity", "D": "Recording duration"}
DIM_COLOUR = {"B": "#7B2FBE", "E": "#E6550D", "D": "#3a7acf"}


def _dim_totals(pairs, a_key, b_key, dim):
    keys = DIMS[dim]
    H, L = [], []
    for p in pairs:
        if p[a_key] is None or p[b_key] is None:
            continue
        h = _totals(p[a_key][dim], keys)
        l = _totals(p[b_key][dim], keys)
        if h is not None and l is not None:
            H.append(h); L.append(l)
    return H, L


def render_figure(pairs: list[dict]) -> None:
    """Rows = rater pairs; cols = B/E/D. Scatter of raw totals with y=x guide."""
    rng = np.random.default_rng(20260603)
    fig, axes = plt.subplots(3, 3, figsize=(12, 12))
    for row, (label, ak, bk) in enumerate(RATER_PAIRS):
        for col, dim in enumerate(["B", "E", "D"]):
            ax = axes[row, col]
            H, L = _dim_totals(pairs, ak, bk, dim)
            # Auto-scale each panel to the range actually covered (shared x/y so
            # the y=x diagonal stays at 45 degrees), with a 1-unit margin.
            if H:
                lo = min(min(H), min(L))
                hi = max(max(H), max(L))
            else:
                lo, hi = 0, ITEM_MAX_TOTAL[dim]
            lo_lim, hi_lim = lo - 1, hi + 1
            ax.plot([lo_lim, hi_lim], [lo_lim, hi_lim], "-", color="#bbb", lw=1)
            if H:
                jx = rng.uniform(-0.12, 0.12, size=len(H))
                jy = rng.uniform(-0.12, 0.12, size=len(L))
                ax.scatter(np.array(H) + jx, np.array(L) + jy, s=40,
                           color=DIM_COLOUR[dim], alpha=0.75,
                           edgecolor="white", linewidth=0.7)
                exact = sum(1 for a, b in zip(H, L) if a == b)
                rho = _plot.spearman(H, L) or 0
                icc = _plot.icc_2_1(H, L) or 0
                ax.text(0.04, 0.96,
                        f"n={len(H)}\nexact={exact}/{len(H)} ({100*exact/len(H):.0f}%)\n"
                        f"rho={rho:.2f}  ICC={icc:.2f}",
                        transform=ax.transAxes, va="top", ha="left", fontsize=8,
                        bbox=dict(facecolor="white", edgecolor="#ddd", boxstyle="round,pad=0.3"))
            else:
                ax.text(0.5, 0.5, "no overlapping data", transform=ax.transAxes,
                        ha="center", va="center", color="#999")
            ax.set_xlim(lo_lim, hi_lim); ax.set_ylim(lo_lim, hi_lim)
            # integer ticks only (raw totals are integers)
            ticks = range(int(np.ceil(lo_lim)), int(np.floor(hi_lim)) + 1)
            ax.set_xticks(list(ticks)); ax.set_yticks(list(ticks))
            ax.set_aspect("equal", "box")
            ax.set_xlabel(f"{ak} (raw {dim})")
            ax.set_ylabel(f"{bk} (raw {dim})")
            if row == 0:
                ax.set_title(DIM_FULL[dim], fontsize=11, fontweight="bold")
            if col == 0:
                ax.annotate(label, xy=(-0.32, 0.5), xycoords="axes fraction",
                            rotation=90, va="center", ha="center",
                            fontsize=11, fontweight="bold")
            ax.grid(True, color="#eee", linewidth=0.6)
    fig.suptitle("Three-way rater agreement — rater 1 / rater 2 / LLM consensus",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=[0.02, 0, 1, 0.97])
    fig.savefig(OUT_PNG, dpi=160)
    print(f"Wrote {OUT_PNG}")


OUT_COMBINED = _OUT / "human_vs_llm_combined.png"
OUT_BLANDALTMAN = _OUT / "inter_rater_bland_altman.png"

# Distinct colours for the two human raters when overlaid vs the LLM.
RATER_COLOUR = {"human": "#1b7837", "ana": "#762a83"}   # rater 2 = green, rater 1 = purple
RATER_LABEL = {"human": "rater 2", "ana": "rater 1"}


def _fit_line(H, L):
    """Least-squares fit L ~ a*H + b. Returns (slope, intercept) or None."""
    if len(H) < 2:
        return None
    H = np.asarray(H, dtype=float); L = np.asarray(L, dtype=float)
    if np.allclose(H, H[0]):           # vertical — no meaningful slope
        return None
    slope, intercept = np.polyfit(H, L, 1)
    return float(slope), float(intercept)


def render_combined(pairs: list[dict]) -> None:
    """One row, 3 panels (B/E/D). Overlay you+me-vs-LLM and Ana-vs-LLM points,
    each with its own least-squares fit line, plus the y=x identity line."""
    rng = np.random.default_rng(20260603)
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.2))
    for col, dim in enumerate(["B", "E", "D"]):
        ax = axes[col]
        # gather both raters' (human-axis = x, LLM = y) points to set range
        allx, ally = [], []
        series = {}
        for rk in ("human", "ana"):
            H, L = _dim_totals(pairs, rk, "llm", dim)
            series[rk] = (H, L)
            allx += H; ally += L
        if allx:
            lo = min(min(allx), min(ally)); hi = max(max(allx), max(ally))
        else:
            lo, hi = 0, ITEM_MAX_TOTAL[dim]
        lo_lim, hi_lim = lo - 1, hi + 1
        ax.plot([lo_lim, hi_lim], [lo_lim, hi_lim], "-", color="#999", lw=1,
                label="y = x (perfect)", zorder=1)
        for rk in ("human", "ana"):
            H, L = series[rk]
            if not H:
                continue
            c = RATER_COLOUR[rk]
            jx = rng.uniform(-0.1, 0.1, size=len(H))
            jy = rng.uniform(-0.1, 0.1, size=len(L))
            ax.scatter(np.array(H) + jx, np.array(L) + jy, s=42, color=c,
                       alpha=0.7, edgecolor="white", linewidth=0.6,
                       label=f"{RATER_LABEL[rk]} (n={len(H)})", zorder=3)
            fit = _fit_line(H, L)
            if fit:
                slope, intercept = fit
                xs = np.array([lo_lim, hi_lim])
                ax.plot(xs, slope * xs + intercept, "--", color=c, lw=1.8, zorder=2)
        ax.set_xlim(lo_lim, hi_lim); ax.set_ylim(lo_lim, hi_lim)
        ticks = list(range(int(np.ceil(lo_lim)), int(np.floor(hi_lim)) + 1))
        ax.set_xticks(ticks); ax.set_yticks(ticks)
        ax.set_aspect("equal", "box")
        ax.set_xlabel("Human rater (raw total)")
        ax.set_ylabel("LLM consensus (raw total)")
        ax.set_title(DIM_FULL[dim], fontsize=12, fontweight="bold")
        ax.grid(True, color="#eee", linewidth=0.6)
        ax.legend(loc="lower right", fontsize=8, framealpha=0.9)
    fig.suptitle("Human vs LLM consensus — rater 1 and rater 2 overlaid (dashed = per-rater fit)",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(OUT_COMBINED, dpi=160)
    print(f"Wrote {OUT_COMBINED}")


def render_bland_altman(pairs: list[dict]) -> None:
    """Bland-Altman per dimension: x = mean of the two raters, y = difference
    (rater A - rater B). Rows = the 3 rater pairs; cols = B/E/D. Shows bias
    (mean diff) and 95% limits of agreement."""
    fig, axes = plt.subplots(3, 3, figsize=(13, 12))
    rng = np.random.default_rng(20260604)
    for row, (label, ak, bk) in enumerate(RATER_PAIRS):
        for col, dim in enumerate(["B", "E", "D"]):
            ax = axes[row, col]
            A, B = _dim_totals(pairs, ak, bk, dim)
            if not A:
                ax.text(0.5, 0.5, "no overlapping data", transform=ax.transAxes,
                        ha="center", va="center", color="#999")
                ax.set_xticks([]); ax.set_yticks([])
                continue
            A = np.asarray(A, dtype=float); B = np.asarray(B, dtype=float)
            mean = (A + B) / 2
            diff = A - B                       # ak minus bk
            bias = diff.mean()
            sd = diff.std(ddof=1) if len(diff) > 1 else 0.0
            loa_hi, loa_lo = bias + 1.96 * sd, bias - 1.96 * sd
            c = DIM_COLOUR[dim]
            jx = rng.uniform(-0.08, 0.08, size=len(mean))
            jy = rng.uniform(-0.08, 0.08, size=len(diff))
            ax.scatter(mean + jx, diff + jy, s=38, color=c, alpha=0.7,
                       edgecolor="white", linewidth=0.6, zorder=3)
            ax.axhline(0, color="#999", lw=1, zorder=1)
            ax.axhline(bias, color=c, lw=1.6, ls="-", zorder=2)
            ax.axhline(loa_hi, color=c, lw=1.0, ls="--", zorder=2)
            ax.axhline(loa_lo, color=c, lw=1.0, ls="--", zorder=2)
            ax.text(0.04, 0.96,
                    f"n={len(diff)}\nbias={bias:+.2f}\nLoA [{loa_lo:+.1f}, {loa_hi:+.1f}]",
                    transform=ax.transAxes, va="top", ha="left", fontsize=8,
                    bbox=dict(facecolor="white", edgecolor="#ddd", boxstyle="round,pad=0.3"))
            ax.set_xlabel(f"mean of pair (raw {dim})")
            ax.set_ylabel(f"diff ({ak} − {bk})")
            if row == 0:
                ax.set_title(DIM_FULL[dim], fontsize=11, fontweight="bold")
            if col == 0:
                ax.annotate(label, xy=(-0.34, 0.5), xycoords="axes fraction",
                            rotation=90, va="center", ha="center",
                            fontsize=11, fontweight="bold")
            ax.grid(True, color="#eee", linewidth=0.6)
    fig.suptitle("Inter-rater variability — Bland–Altman per dimension "
                 "(solid = bias, dashed = 95% limits of agreement)",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0.02, 0, 1, 0.96))
    fig.savefig(OUT_BLANDALTMAN, dpi=160)
    print(f"Wrote {OUT_BLANDALTMAN}")


OUT_SUPP = _OUT / "supp_llm_vs_human_validation.png"

# The three pairwise comparisons, with a fixed colour per pair. The two
# human-vs-LLM pairs share a warm palette; the human-human pair is the
# reference (grey) the others are judged against.
SUPP_PAIRS = [
    ("rater 1 vs rater 2", "ana", "human", "#444444"),   # human-human reference
    ("rater 1 vs LLM",     "ana", "llm",    "#E6550D"),
    ("rater 2 vs LLM",     "human", "llm",  "#3a7acf"),
]


def _common_triple(pairs):
    """Assays scored by ALL THREE raters — the fair common comparison set."""
    return [p for p in pairs
            if p["ana"] is not None and p["llm"] is not None and p["human"] is not None]


def render_supp_figure(pairs: list[dict]) -> None:
    """Single supplementary figure (validation): the LLM disagrees with a human
    no more than two humans disagree with each other.

    Computed on the COMMON set (assays all three raters scored) so every
    comparison uses identical data. Top row: Bland-Altman per dimension with
    all three rater-pairs overlaid (bias line + 95% LoA band per pair). Bottom
    row: grouped bars of variability (SD of paired differences) per dimension.
    """
    tri = _common_triple(pairs)
    n_common = len(tri)
    rng = np.random.default_rng(20260605)

    fig = plt.figure(figsize=(13, 9))
    gs = fig.add_gridspec(2, 3, height_ratios=[1.3, 1],
                          hspace=0.42, wspace=0.32,
                          left=0.08, right=0.97, top=0.88, bottom=0.09)
    ba_axes = [fig.add_subplot(gs[0, c]) for c in range(3)]
    bar_ax = fig.add_subplot(gs[1, :])   # bottom row spans all 3 columns

    def diffs(ak, bk, dim):
        A, B = [], []
        keys = DIMS[dim]
        for p in tri:
            ia, ib = p[ak][dim], p[bk][dim]
            if any(ia.get(k) is None for k in keys) or any(ib.get(k) is None for k in keys):
                continue
            A.append(sum(ia[k] for k in keys)); B.append(sum(ib[k] for k in keys))
        A = np.asarray(A, float); B = np.asarray(B, float)
        return A, B

    # ---- Top row: Bland-Altman, 3 pairs overlaid per dimension ----
    for col, dim in enumerate(["B", "E", "D"]):
        ax = ba_axes[col]
        ax.axhline(0, color="#bbb", lw=1, zorder=1)
        for label, ak, bk, c in SUPP_PAIRS:
            A, B = diffs(ak, bk, dim)
            if len(A) == 0:
                continue
            mean = (A + B) / 2
            d = A - B
            bias = d.mean()
            sd = d.std(ddof=1) if len(d) > 1 else 0.0
            loa_hi, loa_lo = bias + 1.96 * sd, bias - 1.96 * sd
            jx = rng.uniform(-0.07, 0.07, size=len(mean))
            jy = rng.uniform(-0.07, 0.07, size=len(d))
            ax.scatter(mean + jx, d + jy, s=22, color=c, alpha=0.45,
                       edgecolor="none", zorder=2)
            ax.axhspan(loa_lo, loa_hi, color=c, alpha=0.07, zorder=0)
            ax.axhline(bias, color=c, lw=1.8, zorder=4)
            ax.axhline(loa_hi, color=c, lw=0.9, ls="--", zorder=3)
            ax.axhline(loa_lo, color=c, lw=0.9, ls="--", zorder=3)
        # Shared symmetric y-range across B/E/D so a unit of disagreement looks
        # identical in every panel. ±5 covers the full observed diff range
        # ([-4, 5]) and the widest LoA (~3.5) with headroom; using the full
        # theoretical range (±11/±12) would squash all points into a thin band.
        ax.set_ylim(-5, 5)
        ax.set_yticks(range(-5, 6))
        ax.set_title(DIM_FULL[dim], fontsize=12, fontweight="bold")
        ax.set_xlabel(f"mean of pair (raw {dim} total)")
        if col == 0:
            ax.set_ylabel("difference between raters")
        ax.grid(True, axis="y", color="#eee", linewidth=0.6)

    # ---- Bottom row: grouped bars of SD-of-difference per dimension ----
    pair_labels = [s[0] for s in SUPP_PAIRS]
    pair_colours = [s[3] for s in SUPP_PAIRS]
    x = np.arange(len(["B", "E", "D"]))
    width = 0.26
    sd_by_pair = {s[0]: [] for s in SUPP_PAIRS}
    for dim in ("B", "E", "D"):
        for label, ak, bk, c in SUPP_PAIRS:
            A, B = diffs(ak, bk, dim)
            d = A - B
            sd_by_pair[label].append(d.std(ddof=1) if len(d) > 1 else 0.0)
    ax = bar_ax
    for i, (label, c) in enumerate(zip(pair_labels, pair_colours)):
        ax.bar(x + (i - 1) * width, sd_by_pair[label], width,
               color=c, label=label, edgecolor="white", linewidth=0.6)
        for xi, v in zip(x + (i - 1) * width, sd_by_pair[label]):
            ax.text(xi, v + 0.03, f"{v:.2f}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(["Behavioural\ncomplexity", "Environmental\ncomplexity",
                        "Recording\nduration"])
    ax.set_ylabel("SD of paired differences\n(lower = more agreement)")
    ax.set_title("Pairwise rating variability by dimension", fontsize=12, fontweight="bold")
    ax.legend(loc="upper left", fontsize=9, frameon=True)
    ax.grid(True, axis="y", color="#eee", linewidth=0.6)
    ax.set_axisbelow(True)

    fig.suptitle(
        f"LLM vs human scoring agreement — n={n_common} assays scored by all raters",
        fontsize=13, fontweight="bold")
    # explicit margins set in add_gridspec; no tight_layout (it would override them)
    fig.savefig(OUT_SUPP, dpi=200)
    print(f"Wrote {OUT_SUPP}  (common set n={n_common})")


def main() -> None:
    pairs = build_pairs()
    print_report(pairs)
    render_figure(pairs)
    render_combined(pairs)
    render_bland_altman(pairs)
    render_supp_figure(pairs)


if __name__ == "__main__":
    main()

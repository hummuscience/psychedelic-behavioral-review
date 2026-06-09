"""3-panel B / E / D score timelines for the manuscript.

Each panel: year on X, score on Y, with
  - individual study dots (deterministic per-stem jitter)
  - per-year mean (line + dot)
  - per-year mean ± SEM band (shaded ribbon)
  - OLS linear-regression trend (solid black line, full year span)
  - annotation: slope ± 95% CI, two-sided p, Spearman ρ, n

Year span: full corpus (2014–2026). Panels share the X axis.

Statistics: SEM = std-error-of-the-mean = sample_std / sqrt(n). For
single-study years SEM is undefined and the band collapses to a dot.
OLS slope and Spearman ρ replicate the dashboard timeline output to
within rounding (scoring/dashboard/src/cube.md `trendStats()`).

Output:
  translational_psychiatry/score_timelines.png
  translational_psychiatry/score_timelines.pdf
"""
from __future__ import annotations
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy import stats as sst

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
OUTDIR = HERE / "output"
CONS = DATA / "results_v2_full_consensus"
REG = DATA / "paper_registry.json"
OUT_PNG = OUTDIR / "score_timelines.png"
OUT_PDF = OUT_PNG.with_suffix(".pdf")

# Match dashboard cube.md TIMELINE_DIMS colours.
DIMS = [
    ("Behavioural complexity",  "behavioural_complexity_max",   "#7B2FBE"),
    ("Environmental complexity","environmental_complexity_max", "#E6550D"),
    ("Recording duration",      "recording_duration_max",       "#3a7acf"),
]


def jitter(stem: str, salt: str, amount: float) -> float:
    """Deterministic ±amount jitter so a paper always sits in the same spot."""
    h = hashlib.md5(f"{stem}|{salt}".encode()).digest()
    v = int.from_bytes(h[:4], "big") / 0xFFFFFFFF
    return (v - 0.5) * 2.0 * amount


def load_rows() -> list[dict]:
    """One row per study with year + per-dimension scores."""
    import unicodedata
    reg = json.loads(REG.read_text())
    reg = {unicodedata.normalize("NFC", k).lower(): v for k, v in reg.items()}

    rows = []
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
        if not year:
            continue
        try:
            year = int(year)
        except (TypeError, ValueError):
            continue
        # Match the dashboard's banded-then-fallback duration convention.
        d_score = (sc.get("recording_duration_banded_max")
                   or sc.get("recording_duration_max") or 0.0)
        rows.append({
            "stem": f.stem,
            "year": year,
            "behavioural_complexity_max":   sc.get("behavioural_complexity_max") or 0.0,
            "environmental_complexity_max": sc.get("environmental_complexity_max") or 0.0,
            "recording_duration_max":       d_score,
        })
    return rows


def trend_stats(xs: np.ndarray, ys: np.ndarray) -> dict | None:
    """OLS slope + 95% CI + normal-approx p + R² + Spearman ρ.

    Matches the dashboard `trendStats()` function so the manuscript numbers
    line up with what readers can verify on the live dashboard.
    """
    n = len(xs)
    if n < 3:
        return None
    res = sst.linregress(xs, ys)
    # SciPy's `stderr` is the std-err of the slope; CI half-width at 95%.
    ci = 1.96 * float(res.stderr)
    # Two-sided p via normal approximation (matches dashboard).
    z = float(res.slope) / float(res.stderr) if res.stderr else 0.0
    p = 2 * (1 - sst.norm.cdf(abs(z)))
    rho, _ = sst.spearmanr(xs, ys)
    return {
        "n": n,
        "slope": float(res.slope),
        "intercept": float(res.intercept),
        "ci": float(ci),
        "p": float(p),
        "r2": float(res.rvalue) ** 2,
        "rho": float(rho),
        "x_min": int(xs.min()),
        "x_max": int(xs.max()),
    }


def fmt_p(p: float) -> str:
    if p < 0.001: return "p < 0.001"
    if p < 0.01:  return f"p = {p:.3f}"
    return f"p = {p:.2f}"


def per_year_summary(rows: list[dict], key: str) -> tuple[list[int], list[float], list[float], list[float], list[int]]:
    """Return (years, mean, mean-SEM, mean+SEM, n) sorted by year.

    SEM = sample_std / sqrt(n) with ddof=1 (Bessel's correction). For
    single-study years SEM is undefined; we fall through to SEM = 0 so
    the band collapses to a dot rather than disappearing entirely.
    """
    by_year: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        by_year[r["year"]].append(r[key])
    years = sorted(by_year)
    means, lo, hi, ns = [], [], [], []
    for y in years:
        vals = np.asarray(by_year[y], dtype=float)
        m = float(vals.mean())
        sem = float(vals.std(ddof=1) / np.sqrt(len(vals))) if len(vals) > 1 else 0.0
        means.append(m)
        lo.append(m - sem)
        hi.append(m + sem)
        ns.append(len(vals))
    return years, means, lo, hi, ns


def plot(rows: list[dict]) -> None:
    # Top margin is deliberately roomy so the per-panel stats annotation can
    # sit ABOVE the axes (between the panel title and the data) instead of
    # overplotting the curve. Y-axis is clamped to 0–8 so the per-year
    # variation is legible — almost no studies score above 8 on any
    # dimension, and the dashboard's 0–15 range was wasted whitespace here.
    Y_MAX = 8
    fig, axes = plt.subplots(3, 1, figsize=(8.5, 11), dpi=200, sharex=True)
    fig.subplots_adjust(hspace=0.45, top=0.94, bottom=0.08)

    for ax, (label, key, colour) in zip(axes, DIMS):
        # Per-study points with deterministic jitter
        xs = np.array([r["year"] + jitter(r["stem"], "x", 0.30) for r in rows])
        ys = np.array([r[key]   + jitter(r["stem"], "y", 0.35) for r in rows])
        ax.scatter(xs, ys, c=colour, s=18, alpha=0.4,
                   edgecolors=colour, linewidths=0.5, zorder=2)

        # Per-year mean ± SEM band
        years, means, lo, hi, _ = per_year_summary(rows, key)
        ax.fill_between(years, lo, hi, color=colour, alpha=0.22,
                        linewidth=0, zorder=1, label="Mean ± SEM")
        ax.plot(years, means, color=colour, linewidth=1.8, alpha=0.9,
                zorder=3, label="Yearly mean")
        ax.scatter(years, means, c=colour, s=42, edgecolors="white",
                   linewidths=1.0, zorder=4)

        # OLS trend over individual studies (matches dashboard)
        x_raw = np.array([r["year"] for r in rows], dtype=float)
        y_raw = np.array([r[key]   for r in rows], dtype=float)
        stats_d = trend_stats(x_raw, y_raw)
        if stats_d:
            x_line = np.array([stats_d["x_min"], stats_d["x_max"]], dtype=float)
            y_line = stats_d["intercept"] + stats_d["slope"] * x_line
            ax.plot(x_line, y_line, color="#111", linewidth=2.0,
                    linestyle="-", zorder=5, label="OLS trend")
            # Stats annotation lives ABOVE the axes (in the gap created by
            # the wider hspace), so it never overplots the data.
            txt = (f"slope = {stats_d['slope']:+.3f} ± {stats_d['ci']:.3f} / yr   "
                   f"{fmt_p(stats_d['p'])}   "
                   f"Spearman ρ = {stats_d['rho']:+.2f}   "
                   f"R² = {stats_d['r2']:.3f}   "
                   f"n = {stats_d['n']}")
            ax.text(0.0, 1.04, txt, transform=ax.transAxes,
                    fontsize=8.5, verticalalignment="bottom",
                    family="monospace", color="#222")

        ax.set_ylim(0, Y_MAX)
        ax.set_ylabel(label, fontsize=10)
        ax.grid(True, linestyle=":", alpha=0.5, zorder=0)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        if ax is axes[0]:
            # Legend sits BELOW the first panel's stats annotation, on the
            # right edge, outside the data envelope at the top.
            ax.legend(loc="upper right", bbox_to_anchor=(1.0, 1.0),
                      fontsize=8, frameon=False, ncol=3)

    axes[-1].set_xlabel("Year", fontsize=10)
    # Force integer year ticks
    all_years = sorted({r["year"] for r in rows})
    axes[-1].set_xticks(all_years)
    axes[-1].set_xticklabels([str(y) for y in all_years], rotation=0, fontsize=8)

    fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight")
    fig.savefig(OUT_PDF,           bbox_inches="tight")
    print(f"Wrote {OUT_PNG}")
    print(f"Wrote {OUT_PDF}")


def main() -> None:
    rows = load_rows()
    print(f"Loaded {len(rows)} studies with a year")
    plot(rows)
    # Print the headline stats so they go straight into the manuscript / CHANGELOG.
    for label, key, _ in DIMS:
        xs = np.array([r["year"] for r in rows], dtype=float)
        ys = np.array([r[key]   for r in rows], dtype=float)
        s = trend_stats(xs, ys)
        if s:
            print(f"  {label:28s} slope = {s['slope']:+.3f} ± {s['ci']:.3f}/yr   "
                  f"{fmt_p(s['p'])}  ρ = {s['rho']:+.2f}  R² = {s['r2']:.3f}  n = {s['n']}")


if __name__ == "__main__":
    main()

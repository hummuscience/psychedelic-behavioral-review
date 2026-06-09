"""Supplementary dose-distribution figure for the manuscript.

Pulls per-paper dose records from results_v2_full_consensus/*.json (same
source the dashboard uses) and plots histograms of psilocybin doses used
in the reviewed studies, stacked by species (mouse on top, rat below),
with the clinical-equivalent 5-HT2A occupancy band overlaid.

Band sources:
  mouse 0.6-2 mg/kg -- Maltby 2026 (RO50=0.88 mg/kg; 40-70% occupancy)
  rat   1-4 mg/kg   -- Kiilerich 2023 (1.0 mg/kg s.c. = 41% occupancy, upper extrapolated)
"""

import json
import glob
from pathlib import Path

import matplotlib.pyplot as plt  # type: ignore[import-not-found]
import numpy as np  # type: ignore[import-not-found]
from matplotlib.patches import Patch  # type: ignore[import-not-found]

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
OUTDIR = HERE / "output"
CONSENSUS = DATA / "results_v2_full_consensus"
OUT_PNG = OUTDIR / "dose_distribution.png"
OUT_PDF = OUTDIR / "dose_distribution.pdf"

# psilocin is the active metabolite; pool with psilocybin
PSILOCYBIN_ALIASES = {"psilocybin", "psilocin"}

BANDS = {
    "mouse": (0.6, 2.0),
    "rat":   (1.0, 4.0),
}


def normalise_species(raw: str) -> str | None:
    s = (raw or "").lower().strip()
    has_mouse = "mouse" in s or "mice" in s
    has_rat = "rat" in s
    if has_mouse and not has_rat:
        return "mouse"
    if has_rat and not has_mouse:
        return "rat"
    if has_mouse and has_rat:
        return "both"
    return None


def load_records():
    """Return list of dicts: stem, species, dose_mg_kg, route."""
    rows = []
    for f in sorted(glob.glob(str(CONSENSUS / "*.json"))):
        try:
            d = json.load(open(f))
        except json.JSONDecodeError:
            continue
        sp = normalise_species(d.get("species") or "")
        if sp is None:
            continue
        stem = Path(f).stem
        for de in (d.get("dosing") or []):
            if not isinstance(de, dict):
                continue
            cmp_raw = (de.get("compound") or "").lower().strip()
            if cmp_raw not in PSILOCYBIN_ALIASES:
                continue
            route = (de.get("route") or "").strip()
            for v in (de.get("doses_mg_per_kg") or []):
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    continue
                if not np.isfinite(v) or v <= 0:
                    continue
                spec_list = ["mouse", "rat"] if sp == "both" else [sp]
                for s in spec_list:
                    rows.append({"stem": stem, "species": s,
                                 "dose": v, "route": route})
    return rows


def main():
    rows = load_records()
    print(f"loaded {len(rows)} psilocybin dose records")

    fig, axes = plt.subplots(2, 1, figsize=(6.5, 5.0),
                             sharex=True, sharey=True)

    band_color = "#4a7aaf"

    all_doses = [r["dose"] for r in rows]
    band_extremes = [v for sp in ("mouse", "rat") for v in BANDS[sp]]
    xlo = min(min(all_doses), min(band_extremes)) * 0.3
    xhi = max(max(all_doses), max(band_extremes)) * 3
    edges = np.logspace(np.log10(xlo), np.log10(xhi), 30)

    for ax, species in zip(axes, ("mouse", "rat")):
        doses = [r["dose"] for r in rows if r["species"] == species]
        n_records = len(doses)
        n_papers = len(set(r["stem"] for r in rows if r["species"] == species))

        ax.hist(doses, bins=edges, color="#444",
                edgecolor="white", linewidth=0.5)

        blo, bhi = BANDS[species]
        ax.axvspan(blo, bhi, facecolor=band_color, alpha=0.40,
                   zorder=0, edgecolor="none")

        ax.set_xscale("log")
        ax.set_xlim(xlo, xhi)
        ax.set_title(f"Psilocybin, {species}  "
                     f"(n={n_records} doses, {n_papers} studies)",
                     fontsize=10, loc="left")
        ax.tick_params(axis="both", labelsize=9)
        ax.set_ylabel("Studies", fontsize=10)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    axes[-1].set_xlabel("Dose (mg/kg, log scale)", fontsize=10)

    legend_handles = [
        Patch(facecolor=band_color, alpha=0.40, edgecolor="none",
              label="5-HT$_{2A}$ occupancy 40–70% "
                    "(Maltby 2026; Kiilerich 2023)"),
    ]
    fig.legend(handles=legend_handles, loc="lower center",
               bbox_to_anchor=(0.5, -0.02), frameon=False, fontsize=9)

    fig.tight_layout(rect=(0, 0.04, 1, 1))

    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight")
    fig.savefig(OUT_PDF, bbox_inches="tight")
    print(f"wrote {OUT_PNG}")
    print(f"wrote {OUT_PDF}")


if __name__ == "__main__":
    main()

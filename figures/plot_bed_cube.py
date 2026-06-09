"""3-D B/E/D cube figure for the manuscript (Figure 2).

Reproduces the original behavior_assays_test.png aesthetic against the
expanded n=266 corpus from results_v2_full_consensus/.

Each dot is one study, positioned by:
  X = recording_duration_banded_max (Short / Long-Fragmented / Long-Continuous)
  Y = environmental_complexity_max  (Standard / Enriched / Natural)
  Z = behavioural_complexity_max    (Simple / Complex)

Point colour: publication year (cool colormap, cyan → magenta).
Point size: constant (60 pt² across all studies).
Pink star marker in the back-upper-right: the aspirational target
(long-continuous recording in a naturalistic environment with complex
behavioural readouts).

Output: translational_psychiatry/behavior_assays_test.png (+ .pdf).
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 — registers projection
from matplotlib.colors import Normalize

HERE = Path(__file__).parent
CONS = HERE / "results_v2_full_consensus"
REG = HERE / "paper_registry.json"
OUT_PNG = HERE.parent / "translational_psychiatry" / "behavior_assays_test.png"
OUT_PDF = OUT_PNG.with_suffix(".pdf")

AXIS_MAX = 15.0
# Aspirational star: tucked just inside the back-upper-right corner so it
# reads as "the asymptote" without overlapping the Z-axis "Complex" label.
STAR_POS = (13.0, 13.0, 13.0)


def jitter(stem: str, dim: str, amount: float = 0.2) -> float:
    """Deterministic ±amount jitter so each study lands in the same spot
    across renders (matches the dashboard's `jit()` convention).

    Amount is the half-width of the uniform jitter band. Default ±0.2 is
    enough to separate overlapping integer-scored points without smearing
    the visible cluster.
    """
    h = hashlib.md5(f"{stem}|{dim}".encode()).digest()
    v = int.from_bytes(h[:4], "big") / 0xFFFFFFFF
    return (v - 0.5) * 2.0 * amount


def load_studies() -> list[dict]:
    import unicodedata
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
            # Studies with no known publication year can't participate in the
            # year colour encoding; drop them rather than render a sentinel.
            continue
        studies.append({
            "stem": f.stem,
            "year": year,
            "n_assays": len(d["assays"]),
            "b": sc.get("behavioural_complexity_max") or 0.0,
            "e": sc.get("environmental_complexity_max") or 0.0,
            "d": (sc.get("recording_duration_banded_max")
                  or sc.get("recording_duration_max") or 0.0),
        })
    return studies


def plot(studies: list[dict]) -> None:
    fig = plt.figure(figsize=(8.5, 7.5), dpi=200)
    ax = fig.add_subplot(111, projection="3d")

    years = np.array([s["year"] for s in studies])

    # Year colour: cool colormap (cyan → magenta) matches the original.
    cmap = mpl.colormaps["cool"]
    y_min, y_max = int(years.min()), int(years.max())
    norm = Normalize(vmin=y_min, vmax=y_max)
    colours = cmap(norm(years))

    # Constant point size — encoding n_assays via dot size made some studies
    # visually dominate; reverted to a single size for cleaner reading.
    sizes = np.full(len(studies), 60.0)

    # Jittered coordinates so integer-valued scores don't overlap.
    # Clamp to [0, AXIS_MAX] so a point at score 0 with negative jitter
    # doesn't bleed below the axis (and similarly for the top end).
    xs = np.clip(
        np.array([s["d"] + jitter(s["stem"], "x") for s in studies]),
        0.0, AXIS_MAX)
    ys = np.clip(
        np.array([s["e"] + jitter(s["stem"], "y") for s in studies]),
        0.0, AXIS_MAX)
    zs = np.clip(
        np.array([s["b"] + jitter(s["stem"], "z") for s in studies]),
        0.0, AXIS_MAX)

    ax.scatter(
        xs, ys, zs,
        c=colours, s=sizes,
        edgecolors="white", linewidths=0.5,
        depthshade=True, zorder=2,
    )

    # Aspirational target — large pink star in the back-upper-right corner.
    ax.scatter(
        [STAR_POS[0]], [STAR_POS[1]], [STAR_POS[2]],
        marker="*", c="#E7298A", s=600,
        edgecolors="white", linewidths=0.8,
        depthshade=False, zorder=10,
    )

    # Axis limits + semantic tick labels matching the original.
    ax.set_xlim(0, AXIS_MAX); ax.set_ylim(0, AXIS_MAX); ax.set_zlim(0, AXIS_MAX)

    # X: Recording Duration. Three semantic bands, spaced at the dashboard's
    # band midpoints (0–5 short, 5–10 long-fragmented, 10–15 long-continuous).
    ax.set_xticks([2.5, 7.5, 12.5])
    ax.set_xticklabels(["Short", "Long-Fragmented", "Long-Continuous"], fontsize=8)
    ax.set_xlabel("Recording Duration", fontsize=10, labelpad=10, fontweight="bold")

    # Y: Environmental Complexity.
    ax.set_yticks([2.5, 7.5, 12.5])
    ax.set_yticklabels(["Standard", "Enriched", "Natural"], fontsize=8)
    ax.set_ylabel("Environmental Complexity", fontsize=10, labelpad=10, fontweight="bold")

    # Z: Behavioural Complexity. Only two endpoint labels (Simple at bottom,
    # Complex near top) to match the original. Suppress the built-in axis
    # label (which auto-rotates with the axis direction and reads sideways)
    # and place an upright label as a 2D figure-level annotation instead.
    ax.set_zticks([1.5, 13.5])
    ax.set_zticklabels(["Simple", "Complex"], fontsize=8)
    ax.set_zlabel("")
    fig.text(
        0.13, 0.55, "Behavioral Complexity",
        ha="center", va="center",
        fontsize=10, fontweight="bold",
        rotation=90,
    )

    # Camera + axis inversion. Goal: origin corner (Short / Standard /
    # Simple) at the FRONT of the cube; aspirational corner at the BACK;
    # Behavioural Complexity axis on the LEFT side of the visual frame
    # (rather than matplotlib's default right-side placement).
    #   - Invert X (Recording Duration): Short ends up at the front.
    #   - Y (Environmental Complexity) un-inverted: with the new azimuth,
    #     Standard ends up at the front too.
    #   - Azimuth +55° (mirror of the previous +125° about the Y axis)
    #     swings the camera so the Z-axis pane sits on the LEFT side of
    #     the rendered figure.
    ax.view_init(elev=18, azim=55)
    ax.invert_xaxis()

    # Pane styling: very light grey edges, no background fill.
    for pane in (ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane):
        pane.set_facecolor((1, 1, 1, 0.0))
        pane.set_edgecolor((0.85, 0.85, 0.85, 1.0))

    # Subdued grid.
    ax.grid(True, linestyle=":", alpha=0.35)

    # Year colorbar on the right edge, vertical orientation. Spans most of
    # the figure height; every-other-year ticks keep labels readable for
    # the 13-year span 2014–2026.
    sm = mpl.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cax = fig.add_axes((0.88, 0.20, 0.022, 0.60))
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

    # bbox_inches='tight' sometimes crops the Z-axis label (it lives outside
    # the rendered cube wireframe). Reserve a bit of extra padding on save
    # so the "Behavioral Complexity" label survives.
    fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight", pad_inches=0.25)
    fig.savefig(OUT_PDF,            bbox_inches="tight", pad_inches=0.25)
    print(f"Wrote {OUT_PNG}")
    print(f"Wrote {OUT_PDF}")


def main() -> None:
    studies = load_studies()
    print(f"Loaded {len(studies)} studies with a known year")
    years = [s["year"] for s in studies]
    print(f"Year range: {min(years)}–{max(years)}")
    plot(studies)


if __name__ == "__main__":
    main()

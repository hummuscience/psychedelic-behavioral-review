"""Supplementary Figure 3: donut chart of drug administration routes.

Counts dose entries for the PSYCHEDELIC compound(s) only. Dosing entries for
comparators / antagonists / tool compounds (ketamine, ketanserin,
WAY-100635, fluoxetine, CNO, …) are excluded: a dosing entry is kept only if
its `compound` matches the study's `psychedelic` field (fuzzy match, see
is_psychedelic_entry) or appears on PSYCHEDELIC_ALLOWLIST.

Weighting (fractional, 1/k): each kept entry contributes a total weight of 1
distributed equally across the distinct routes it used. A single-route entry
adds 1.0 to that route; an entry using k routes adds 1/k to each. This means
there is NO "multiple" slice — multi-route studies are split into the real
routes they used (e.g. an i.p.+s.c. study adds 0.5 to i.p. and 0.5 to s.c.).
The routes for `multiple`-coded entries can't be recovered mechanically (the
JSON only stores the string "multiple"), so they come from MULTI_ROUTE_MAP, a
hand-reviewed mapping built by reading each entry's evidence text.

Slices: i.p. / s.c. / p.o. / i.n. / i.c. / i.v.

The v2 schema has no discrete `i.c.` route code — entries that the old
review counted as intracerebral microinjection (VLO, OFC, claustrum,
i.c.v., etc.) come through as `other`. We relabel them as `i.c.` here based
on inspecting all `other`-route dosing entries, where every example was a
brain-region microinjection or local CNS perfusion.

`not_reported`-route entries (4 entries, all from wallach2023, a re-analysis
paper that states no route of its own) are dropped: a routes-of-administration
figure shouldn't include entries with no administration data.

Output: translational_psychiatry/application_donut.png (+ .pdf).
"""
from __future__ import annotations
import json
import re
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt

# Compounds that ARE psychedelics but whose name won't always string-match the
# study's free-text `psychedelic` field. 4C-TFM is an Ariadne analog
# (cunningham2023 groups it with (R)-Ariadne in the HTR assay); the rest are
# named psychedelics that occasionally appear with extra qualifier text. This
# allowlist backstops the fuzzy matcher — add to it rather than loosening the
# match, so comparators (ketamine, NBOMe-as-control, etc.) stay excluded.
PSYCHEDELIC_ALLOWLIST = {
    "4ctfm",
}

# Mushroom genera / core scaffolds shared between an extract's compound name
# and the study psychedelic field (e.g. "Psilocybe cubensis methanolic
# extract" vs study psychedelic "Psilocybe cubensis extract").
_GENERA = ("psilocybe", "pholiotina", "panaeolus", "gymnopilus",
           "psilocin", "psilocybin")

# Hand-reviewed routes for every `multiple`-coded psychedelic dosing entry.
# The JSON stores only the literal string "multiple"; the real routes live in
# free-text evidence and can't be parsed reliably (the abbreviations i.p./i.n.
# /i.v. all collide). Each entry was read individually from its evidence and
# doses_raw. Keyed by (study_id_filename_stem, normalised compound name).
# Edge calls (confirmed): nebulized nose-only → i.n.; transdermal patch + IV
# tail vein → i.v.; i.c.v./ICV and local brain-region infusion → i.c.
MULTI_ROUTE_MAP = {
    ("bouloufa2025", "lsd"):                  ["i.p.", "i.v."],
    ("bryson2024", "re104"):                  ["i.v.", "s.c."],
    ("bryson2024", "4ohdipt"):                ["i.v.", "s.c."],
    ("buzzelli2023", "psilocybin"):           ["i.p.", "p.o."],
    ("cunningham2023", "ariadne"):            ["i.p.", "s.c."],
    ("flanagan2021", "rdoi"):                 ["i.n.", "i.p."],  # nebulized nose-only
    ("garcacabrerizo2025", "psilocybin"):     ["i.p.", "p.o."],
    ("gianfratti2022", "ayahuasca"):          ["i.p.", "p.o."],
    ("hammo2025", "doi"):                     ["i.p.", "i.c."],  # local cortical
    ("havel2024", "oxanoribogaine"):          ["i.p.", "s.c."],
    ("havel2024", "epioxanoribogaine"):       ["i.p.", "s.c."],
    ("higgins2025", "psilocybin"):            ["s.c.", "p.o."],
    ("higgins2025", "5meodmt"):               ["s.c.", "p.o."],
    ("jeanblanc2024", "psilocybin"):          ["i.p.", "i.c."],  # intra-NAcc/VTA
    ("liao2019", "doi"):                      ["i.v.", "i.p."],
    ("nogueira2025", "5meodmt"):              ["i.p.", "i.c."],  # i.c.v.
    ("pedzich2022", "doi"):                   ["i.p.", "i.c."],  # intra-amygdala
    ("pohorala2024", "psilocybin"):           ["i.p.", "s.c."],
    ("rodrguez2020", "ibogaine"):             ["i.p.", "i.v."],
    ("souza2024", "5meodmt"):                 ["i.c.", "i.p."],  # ICV
    ("tiwari2024", "doi"):                    ["i.p.", "i.c."],  # intracerebral
    ("wallach2023", "doi"):                   ["i.p.", "s.c."],
    ("witowski2024", "dmt"):                  ["i.v."],          # transdermal patch + IV
    ("yu2024", "psilocybin"):                 ["i.c.", "i.p."],  # ICV
    ("zhang2025", "psilocin"):                ["i.p.", "i.c."],  # mPFC infusion
}


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _psychedelic_tokens(field: str | None) -> set[str]:
    """Candidate compound names from a study's free-text `psychedelic` field.

    Splits on commas/semicolons/slashes/"and", and also yields a
    parenthetical-stripped variant ("Psilocybe azurescens (…)" → "psilocybe
    azurescens") so qualifier text doesn't block a match.
    """
    out: set[str] = set()
    for part in re.split(r"[,;/]| and ", field or ""):
        part = part.strip()
        for cand in (part, re.sub(r"\(.*?\)", "", part)):
            n = _norm(cand)
            if len(n) >= 3:
                out.add(n)
    return out


def is_psychedelic_entry(compound: str | None, psych_tokens: set[str]) -> bool:
    """True if a dosing entry's compound is one of the study's psychedelics."""
    c = _norm(compound)
    if not c:
        return False
    if c in PSYCHEDELIC_ALLOWLIST:
        return True
    for p in psych_tokens:
        if c == p or c in p or p in c:
            return True
    # genus-level fallback for mushroom extracts
    for g in _GENERA:
        if g in c and any(g in p for p in psych_tokens):
            return True
    return False

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
OUTDIR = HERE / "output"
CONS = DATA / "results_v2_full_consensus"
OUT_PNG = OUTDIR / "application_donut.png"
OUT_PDF = OUT_PNG.with_suffix(".pdf")

# Slice order (large→small) and colour palette. Six real anatomical routes —
# the fractional 1/k weighting dissolves the old "multiple" bucket back into
# these, and `not_reported` entries are dropped, so no "process" categories
# remain.
SLICE_ORDER = ["i.p.", "s.c.", "p.o.", "i.n.", "i.c.", "i.v."]
COLOURS = {
    "i.p.":          "#9BB0E8",   # light blue
    "s.c.":          "#B59CE6",   # purple
    "p.o.":          "#E588B0",   # pink
    "i.n.":          "#F3B26B",   # warm orange
    "i.c.":          "#F4D55A",   # yellow (the original i.c. slice colour)
    "i.v.":          "#F58A3E",   # darker orange
}


def entry_routes(stem: str, entry: dict) -> list[str]:
    """Resolve a psychedelic dosing entry to its list of distinct slice routes.

      - i.p./s.c./p.o./i.n./i.v.  → [same label]
      - `other`                   → ["i.c."] (every `other` entry is a verified
                                    brain-region microinjection / local CNS
                                    perfusion)
      - `multiple`                → MULTI_ROUTE_MAP lookup (hand-reviewed)
      - `not_reported` / missing  → [] (dropped — no administration data)

    Returns [] for entries that contribute no weight (dropped).
    """
    v = (entry.get("route") or "").strip().lower()
    if v in {"i.p.", "s.c.", "p.o.", "i.n.", "i.v."}:
        return [v]
    if v == "other":
        return ["i.c."]
    if v == "multiple":
        key = (_norm(stem), _norm(entry.get("compound")))
        routes = MULTI_ROUTE_MAP.get(key)
        if routes is None:
            raise KeyError(
                f"multiple-route entry not in MULTI_ROUTE_MAP: {key} "
                f"(compound={entry.get('compound')!r}). Read its evidence and "
                f"add a reviewed mapping."
            )
        return routes
    return []  # not_reported / empty → dropped


def collect_routes() -> tuple[Counter, Counter]:
    """Per-study route tallies. Returns (weights, study_counts).

    `weights` (float): each study contributes a total weight of 1, split
    equally across the distinct routes by which its psychedelic(s) were
    administered (matching the interactive dashboard's applications page). A
    study using i.p. + s.c. adds 0.5 to each; a single-route study adds 1.0.
    These size the wedges, so the percentages sum to 100% over studies with no
    double-counting.

    `study_counts` (int): the number of distinct studies that used each route —
    a study using i.p. + s.c. adds a whole 1 to both i.p. and s.c. These are
    the legend's `n` (you can't have half a study). Because multi-route studies
    are counted once per route, the counts sum to more than the study total.

    Both exclude comparator/antagonist/tool compounds (psychedelic-only via
    is_psychedelic_entry) and drop not_reported entries; `multiple` is resolved
    via the hand-reviewed MULTI_ROUTE_MAP.
    """
    weights: Counter = Counter()
    study_counts: Counter = Counter()
    for f in CONS.glob("*.json"):
        if f.name.startswith("_"):
            continue
        try:
            d = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not d.get("assays"):
            continue
        psych_tokens = _psychedelic_tokens(d.get("psychedelic"))
        # Collect the study's distinct psychedelic routes across all entries.
        study_routes: set[str] = set()
        for entry in d.get("dosing") or []:
            if not isinstance(entry, dict):
                continue
            # Psychedelic-only: skip comparators/antagonists/tool compounds.
            if not is_psychedelic_entry(entry.get("compound"), psych_tokens):
                continue
            study_routes.update(entry_routes(f.stem, entry))
        if not study_routes:
            continue  # no psychedelic administration data → contributes nothing
        w = 1.0 / len(study_routes)
        for r in study_routes:
            weights[r] += w
            study_counts[r] += 1  # whole study, once per distinct route
    return weights, study_counts


def plot(weights: Counter, study_counts: Counter) -> None:
    total = sum(weights.values())
    sizes = [weights.get(label, 0) for label in SLICE_ORDER]   # wedge areas
    pcts  = [n / total * 100 for n in sizes]
    counts = [study_counts.get(label, 0) for label in SLICE_ORDER]  # legend n

    # Donut on the left, a clean legend column on the right. The old design
    # put every label on a radial leader line, which tangled the five thin
    # slices (< 5%) into a knot of crossing lines in one quadrant. A side
    # legend reads top-to-bottom in slice order and never collides.
    fig, (ax, lax) = plt.subplots(
        1, 2, figsize=(10, 6), dpi=200,
        gridspec_kw=dict(width_ratios=[1.0, 0.85], wspace=0.0),
    )

    wedges, _ = ax.pie(
        sizes,
        colors=[COLOURS[label] for label in SLICE_ORDER],
        startangle=90, counterclock=False,
        wedgeprops=dict(width=0.35, edgecolor="white", linewidth=2),
    )

    # Only the dominant slices (≥ 5%) get an inline percentage drawn on the
    # ring itself — enough to anchor the eye without crowding. Everything
    # else is read off the legend.
    import math
    INLINE_THRESHOLD = 5.0
    for w, pct in zip(wedges, pcts):
        if pct < INLINE_THRESHOLD:
            continue
        ang = (w.theta2 + w.theta1) / 2.0
        rad = math.radians(ang)
        ax.text(0.825 * math.cos(rad), 0.825 * math.sin(rad),
                f"{pct:.0f}%", ha="center", va="center",
                fontsize=13, color="#222", weight="bold")

    ax.set_aspect("equal")
    ax.axis("off")

    # ---- legend column ----------------------------------------------------
    # One row per slice, in the same large→small order as the ring: a colour
    # swatch, the route name, then the percentage and raw count right-aligned.
    lax.set_xlim(0, 1)
    lax.set_ylim(0, 1)
    lax.axis("off")

    n = len(SLICE_ORDER)
    row_h = 0.082
    y0 = 0.5 + (n - 1) * row_h / 2.0   # vertically centre the block
    sw_x = 0.04                         # swatch left edge
    sw_w = 0.05
    name_x = 0.14
    val_x = 0.98                        # right edge for the % + n value
    for i, label in enumerate(SLICE_ORDER):
        y = y0 - i * row_h
        pct = pcts[i]
        cnt = sizes[i]
        lax.add_patch(plt.Rectangle(
            (sw_x, y - 0.028), sw_w, 0.056,
            facecolor=COLOURS[label], edgecolor="none",
            transform=lax.transData, clip_on=False,
        ))
        lax.text(name_x, y, label, ha="left", va="center",
                 fontsize=15, color="#111", weight="bold")
        # `cnt` is a fractional weight (multi-route studies split 1/k), so it
        # can be non-integer (e.g. 313.5). Show one decimal only when needed.
        cnt_str = f"{cnt:g}" if cnt == int(cnt) else f"{cnt:.1f}"
        lax.text(val_x, y, f"{pct:.1f}%   (n={cnt_str})", ha="right",
                 va="center", fontsize=13, color="#444")

    fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight")
    fig.savefig(OUT_PDF,           bbox_inches="tight")
    print(f"Wrote {OUT_PNG}")
    print(f"Wrote {OUT_PDF}")
    print(f"\nTotal weighted dose entries: {total:.1f}")
    for label in SLICE_ORDER:
        n = routes.get(label, 0)
        print(f"  {label:8s} {n:6.1f}  ({n/total*100:5.1f}%)")


def export_multi_route_map() -> None:
    """Write MULTI_ROUTE_MAP to data/multi_route_map.json so the interactive
    dashboard (JS) can unpack `multiple`-coded routes with the SAME hand-reviewed
    mapping this figure uses — one source of truth, no drift. This annotated
    Python dict is the editable source; the JSON is a generated artifact and
    should not be hand-edited. Keys are "stem|normalised_compound"."""
    out = {f"{stem}|{compound}": routes
           for (stem, compound), routes in MULTI_ROUTE_MAP.items()}
    path = DATA / "multi_route_map.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False,
                               sort_keys=True) + "\n")
    print(f"Wrote {path}  ({len(out)} entries)")


def main() -> None:
    export_multi_route_map()
    routes = collect_routes()
    plot(routes)


if __name__ == "__main__":
    main()

"""Extract drug dosages from docling markdown files and attribute to compounds.

Scans pdfs/<stem>.docling.md, finds all dosage tokens (mg/kg, μg/kg, etc.),
and tags each with the nearest known compound name in a ±80-char context window.

Output: dosages.csv with one row per (stem, compound, dose) — easy to filter to
just the psychedelic doses (compound class = "psychedelic"), or pivot in pandas.

This is grep-based — no LLM, no re-scoring needed.

Usage:
    uv run python extract_dosages.py --pdf-dir pdfs --out dosages.csv
"""

from __future__ import annotations
import argparse
import csv
import re
from collections import Counter
from pathlib import Path

# Match doses like:
#   10 mg/kg, 0.5 mg/kg, 1.39 mg/ kg, 0.125mg/kg, 1 µg/kg, 132.8 nmol/kg
# Also pick up route-context doses inside parens: "(1 mg/kg, i.p.)"
# Allow . , -- so we catch ranges like "1-3 mg/kg" (we then split)
DOSE_RE = re.compile(
    r"""
    (?P<num>           # numeric portion (incl. ranges/lists)
      \d+(?:[\.,]\d+)?              # 1, 1.0, 0.125
      (?:\s*[-–]\s*\d+(?:[\.,]\d+)?)?  # optional 1-3 / 1–3
    )
    \s*
    (?P<unit>
      mg|µg|μg|μ?g|u?g|ng|pg
      |nmol|mmol|µmol|μmol|umol
    )
    \s*/\s*
    (?P<denom>kg|g\b)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Standalone-mass doses (intracerebral / intracranial: e.g. "1 µg i.c.v.")
# These don't have /kg. Only count when the route hint is on the same line.
LOCAL_DOSE_RE = re.compile(
    r"""
    (?P<num>\d+(?:[\.,]\d+)?(?:\s*[-–]\s*\d+(?:[\.,]\d+)?)?)
    \s*
    (?P<unit>µg|μg|ug|ng|pg|nmol|µmol|μmol|pmol|fmol)
    (?!\s*/\s*kg)         # not /kg — that's caught above
    \s*[,;]?\s*
    (?P<route>i\.?c\.?v\.?|i\.?n\.?\b|i\.?t\.?\b|intracerebro|intrathecal|intranasal|intracranial)
    """,
    re.IGNORECASE | re.VERBOSE,
)


def normalise_unit(u: str) -> str:
    s = u.lower()
    s = s.replace("μ", "µ")
    if s in ("ug",):
        return "µg"
    if s == "umol":
        return "µmol"
    return s


# Compound dictionary — order MATTERS within a class (longer phrases first
# so we don't match "DMT" before "5-MeO-DMT").  All matched as case-insensitive.
COMPOUND_CLASSES: dict[str, list[str]] = {
    "psychedelic": [
        # tryptamines (incl. psilocin analogs)
        "psilocybin", "psilocin", r"4-AcO-DMT", r"4-acetoxy-DMT",
        r"4-HO-DPT", r"4-OH-DPT", r"4-HO-DiPT", r"4-OH-DiPT",
        r"4-HO-DET", r"4-OH-DET", r"4-HO-MET", r"4-OH-MET",
        r"\bDiPT\b", r"\bDPT\b", r"\bDET\b", r"\bDIPT\b",
        "5-MeO-DMT", r"5-methoxy-N,N-dimethyltryptamine",
        "5-MeO-DiPT", "5-MeO-MiPT", "5-MeO-AMT",
        r"N,N-dimethyltryptamine", r"\bDMT\b", "ayahuasca", "harmine", "harmaline",
        # ergolines
        "lysergic acid diethylamide", r"\bLSD\b", "ALD-52", "1P-LSD",
        "lisuride", "ergotamine", "bromocriptine",
        # phenethylamines
        r"\bDOI\b", r"2,5-dimethoxy-4-iodoamphetamine",
        r"\bDOM\b", r"\bDOB\b", r"\b2C-B\b", r"\b2-CB\b",
        "25CN-NBOH", "25H-NBOH",
        "25I-NBOMe", "25B-NBOMe", "25C-NBOMe", "NBOMe", "NBOH",
        r"TCB-?2",
        "mescaline", "ibogaine", "noribogaine",
        # less common research chemicals
        "psychoplastogen", "tabernanthalog", "isoLSD",
        r"AAZ-?A-?154", r"R-?69",
    ],
    "antagonist_5HT": [
        "ketanserin", r"WAY-?100635", r"MDL[ -]?100,?907", r"M100907",
        "M100,907", r"volinanserin", "ritanserin", "pirenperone",
        r"SB[ -]?242084", r"SB[ -]?206553", "ondansetron",
    ],
    "comparator": [
        "fluoxetine", "imipramine", "desipramine", "escitalopram",
        "citalopram", "venlafaxine", "sertraline",
        "scopolamine", "ketamine", r"\bMDMA\b", r"\bMDA\b",
        "haloperidol", "clozapine", "risperidone", "amphetamine",
        "cocaine", "morphine", "diazepam", "ethanol",
    ],
    "model_drug": [
        r"\bLPS\b", "lipopolysaccharide", "PCPA", r"\bPCP\b",
        "pentylenetetrazol", r"\bPTZ\b", "kainic acid", "kainate",
        "corticosterone", "dexamethasone", "carprofen", "buprenorphine",
        "isoflurane", "ketoprofen",
    ],
    "tracer_or_other": [
        r"\bBrdU\b", r"\bEdU\b", "fluorogold", r"\bAAV\b", "tamoxifen",
    ],
}

# Pre-compile compound regexes
COMPOUND_RE: dict[str, list[tuple[str, re.Pattern]]] = {
    cls: [(name, re.compile(name, re.IGNORECASE)) for name in names]
    for cls, names in COMPOUND_CLASSES.items()
}


# Canonical names for surface-form consolidation. Right-hand side is the
# canonical form everywhere (lowercase except where the chemistry community
# uses uppercase abbreviations). Maps stripped-lowercase surface → canonical.
CANONICAL = {
    # tryptamines
    "psilocybin": "psilocybin", "psilocin": "psilocin",
    "4-aco-dmt": "4-AcO-DMT", "4-acetoxy-dmt": "4-AcO-DMT",
    "4-ho-dpt": "4-HO-DPT", "4-oh-dpt": "4-HO-DPT",
    "4-ho-dipt": "4-HO-DiPT", "4-oh-dipt": "4-HO-DiPT",
    "4-ho-det": "4-HO-DET", "4-oh-det": "4-HO-DET",
    "4-ho-met": "4-HO-MET", "4-oh-met": "4-HO-MET",
    "dipt": "DiPT", "dpt": "DPT", "det": "DET",
    "5-meo-dmt": "5-MeO-DMT", "5-methoxy-n,n-dimethyltryptamine": "5-MeO-DMT",
    "5-meo-dipt": "5-MeO-DiPT", "5-meo-mipt": "5-MeO-MiPT", "5-meo-amt": "5-MeO-AMT",
    "n,n-dimethyltryptamine": "DMT", "dmt": "DMT",
    "ayahuasca": "ayahuasca", "harmine": "harmine", "harmaline": "harmaline",
    # ergolines
    "lysergic acid diethylamide": "LSD", "lsd": "LSD",
    "ald-52": "ALD-52", "1p-lsd": "1P-LSD",
    "lisuride": "lisuride", "ergotamine": "ergotamine", "bromocriptine": "bromocriptine",
    # phenethylamines
    "doi": "DOI", "2,5-dimethoxy-4-iodoamphetamine": "DOI",
    "dom": "DOM", "dob": "DOB", "2c-b": "2C-B", "2-cb": "2C-B",
    "25cn-nboh": "25CN-NBOH", "25h-nboh": "25H-NBOH",
    "25i-nbome": "25I-NBOMe", "25b-nbome": "25B-NBOMe", "25c-nbome": "25C-NBOMe",
    "nbome": "NBOMe", "nboh": "NBOH",
    "tcb-2": "TCB-2", "tcb2": "TCB-2",
    "mescaline": "mescaline", "ibogaine": "ibogaine", "noribogaine": "noribogaine",
    "psychoplastogen": "psychoplastogen", "tabernanthalog": "tabernanthalog",
    "isolsd": "iso-LSD", "iso-lsd": "iso-LSD",
    # antagonists
    "ketanserin": "ketanserin",
    "way-100635": "WAY-100635", "way100635": "WAY-100635",
    "mdl-100,907": "MDL-100,907", "mdl 100,907": "MDL-100,907",
    "mdl-100907": "MDL-100,907", "mdl100907": "MDL-100,907",
    "m100907": "MDL-100,907", "m100,907": "MDL-100,907", "volinanserin": "MDL-100,907",
    "ritanserin": "ritanserin", "pirenperone": "pirenperone",
    "sb-242084": "SB-242084", "sb242084": "SB-242084",
    "sb-206553": "SB-206553", "sb206553": "SB-206553",
    "ondansetron": "ondansetron",
    # comparators
    "fluoxetine": "fluoxetine", "imipramine": "imipramine",
    "desipramine": "desipramine", "escitalopram": "escitalopram",
    "citalopram": "citalopram", "venlafaxine": "venlafaxine", "sertraline": "sertraline",
    "scopolamine": "scopolamine", "ketamine": "ketamine",
    "mdma": "MDMA", "mda": "MDA",
    "haloperidol": "haloperidol", "clozapine": "clozapine",
    "risperidone": "risperidone", "amphetamine": "amphetamine",
    "cocaine": "cocaine", "morphine": "morphine",
    "diazepam": "diazepam", "ethanol": "ethanol",
    # model drugs
    "lps": "LPS", "lipopolysaccharide": "LPS",
    "pcpa": "PCPA", "pcp": "PCP",
    "pentylenetetrazol": "PTZ", "ptz": "PTZ",
    "kainic acid": "kainic acid", "kainate": "kainic acid",
    "corticosterone": "corticosterone", "dexamethasone": "dexamethasone",
    "carprofen": "carprofen", "buprenorphine": "buprenorphine",
    "isoflurane": "isoflurane", "ketoprofen": "ketoprofen",
    # tracer / other
    "brdu": "BrdU", "edu": "EdU", "fluorogold": "fluorogold",
    "aav": "AAV", "tamoxifen": "tamoxifen",
}


def canonicalize(surface: str) -> str:
    s = surface.strip().rstrip(",;.()").lower()
    s = s.replace(" ", "")  # collapse spaces in things like "MDL 100,907"
    if s in CANONICAL:
        return CANONICAL[s]
    # fallback: try without dashes
    s2 = s.replace("-", "")
    for k, v in CANONICAL.items():
        if k.replace("-", "") == s2:
            return v
    return surface.strip().rstrip(",;.()")


def find_compound(context: str) -> tuple[str | None, str | None]:
    """Return (canonical_compound, class) or (None, None) if no match in context."""
    # Prefer psychedelics first; tie-break by closeness is not implemented (we
    # already focus around the dose, so any hit is "near").
    for cls in ("psychedelic", "antagonist_5HT", "comparator", "model_drug", "tracer_or_other"):
        for canon, rgx in COMPOUND_RE[cls]:
            m = rgx.search(context)
            if m:
                surface = m.group(0)
                return canonicalize(surface), cls
    return None, None


def extract_dose_records(text: str) -> list[dict]:
    """Find each dose mention with a context window and tagged compound."""
    out = []
    for m in DOSE_RE.finditer(text):
        num = m.group("num").replace(" ", "").replace(",", ".")
        unit = normalise_unit(m.group("unit"))
        denom = m.group("denom").lower()
        dose = f"{num} {unit}/{denom}"
        ctx_start = max(0, m.start() - 120)
        ctx_end = min(len(text), m.end() + 120)
        ctx = text[ctx_start:ctx_end].replace("\n", " ")
        compound, cls = find_compound(ctx)
        out.append({
            "dose": dose,
            "compound": compound or "",
            "class": cls or "unknown",
            "context": ctx.strip(),
        })
    for m in LOCAL_DOSE_RE.finditer(text):
        num = m.group("num").replace(" ", "").replace(",", ".")
        unit = normalise_unit(m.group("unit"))
        route = re.sub(r"\.", "", m.group("route").lower())
        dose = f"{num} {unit} ({route})"
        ctx_start = max(0, m.start() - 120)
        ctx_end = min(len(text), m.end() + 120)
        ctx = text[ctx_start:ctx_end].replace("\n", " ")
        compound, cls = find_compound(ctx)
        out.append({
            "dose": dose,
            "compound": compound or "",
            "class": cls or "unknown",
            "context": ctx.strip(),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", type=Path, default=Path("pdfs"))
    ap.add_argument("--out", type=Path, default=Path("dosages.csv"))
    ap.add_argument("--summary-out", type=Path, default=Path("dosages_summary.csv"))
    ap.add_argument("--context-snippet", type=int, default=120,
                    help="Max chars of context to keep in long-form CSV (default 120)")
    args = ap.parse_args()

    long_rows = []           # one per dose mention
    summary_rows = []        # one per (paper, compound) — compact pivot
    for md in sorted(args.pdf_dir.glob("*.docling.md")):
        stem = md.name.removesuffix(".docling.md")
        text = md.read_text(encoding="utf-8", errors="replace")
        records = extract_dose_records(text)
        # Long-form
        for r in records:
            long_rows.append({
                "stem": stem,
                "compound": r["compound"],
                "class": r["class"],
                "dose": r["dose"],
                "context": r["context"][: args.context_snippet],
            })
        # Summary by compound: "psilocybin: 1 mg/kg ×3, 3 mg/kg ×1; DMT: 10 mg/kg ×2"
        by_compound: dict[str, Counter] = {}
        for r in records:
            key = (r["compound"] or "(unknown)", r["class"])
            by_compound.setdefault(key, Counter())[r["dose"]] += 1
        for (compound, cls), counts in by_compound.items():
            doses_str = "; ".join(
                f"{d} (×{n})" if n > 1 else d
                for d, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))
            )
            summary_rows.append({
                "stem": stem,
                "compound": compound,
                "class": cls,
                "n_mentions": sum(counts.values()),
                "doses": doses_str,
            })

    long_rows.sort(key=lambda r: (r["stem"], r["class"], r["compound"]))
    summary_rows.sort(key=lambda r: (r["stem"], 0 if r["class"] == "psychedelic" else 1, r["compound"]))

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["stem", "compound", "class", "dose", "context"])
        w.writeheader()
        w.writerows(long_rows)
    with open(args.summary_out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["stem", "compound", "class", "n_mentions", "doses"])
        w.writeheader()
        w.writerows(summary_rows)

    n_papers = len({r["stem"] for r in long_rows})
    n_psy = sum(1 for r in long_rows if r["class"] == "psychedelic")
    n_unknown = sum(1 for r in long_rows if r["class"] == "unknown")
    n_other = len(long_rows) - n_psy - n_unknown
    print(f"Long CSV   : {args.out}  ({len(long_rows)} dose mentions across {n_papers} papers)")
    print(f"Summary CSV: {args.summary_out}  ({len(summary_rows)} rows)")
    print()
    print(f"  classified as psychedelic: {n_psy} ({100*n_psy/(len(long_rows) or 1):.0f}%)")
    print(f"  classified as antag/comparator/model: {n_other} ({100*n_other/(len(long_rows) or 1):.0f}%)")
    print(f"  unknown context: {n_unknown} ({100*n_unknown/(len(long_rows) or 1):.0f}%)")
    print()
    print("Sample summary rows (psychedelic doses only, first 12 papers):")
    seen_stems = set()
    for r in summary_rows:
        if r["class"] != "psychedelic":
            continue
        if r["stem"] in seen_stems and len(seen_stems) > 12:
            continue
        seen_stems.add(r["stem"])
        if len(seen_stems) > 12:
            break
        print(f"  {r['stem']:<22} {r['compound']:<22} → {r['doses']}")


if __name__ == "__main__":
    main()

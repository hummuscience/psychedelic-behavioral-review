"""Build-time loader: emit dose records derived from the judge-consensus JSONs.

Source: results_v2_full_consensus/*.json -> top-level `dosing[]` list.

This replaces the previous loader that filtered scoring/dosages_llm.csv. The
llm-extracted CSV had three classes of bug visible on the dashboard:
  * decimal loss (e.g. conn2024 "1.5 mg/kg" parsed as "150 mg/kg"),
  * cross-compound bleed when one Methods paragraph lists several compounds
    (e.g. shahar2022 5-HTP doses misattributed to psilocybin),
  * one paper repeating the same dose many times across snippets, which
    inflated histogram bins (e.g. iorgu2024 "20 mg/kg" mentioned 16x).
The judge consensus has one entry per (paper, compound) with a structured
`doses_mg_per_kg` list — naturally deduped and three-model-validated.

Emitted schema matches what dose-utils.js bucketDoses() expects:
  stem,snippet_id,compound,class,dose,route,administered,context
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[3] / "data"
CONSENSUS_DIR = ROOT / "results_v2_full_consensus"

# --- Compound classification --------------------------------------------------
# We tag each dosing entry as class ∈ {psychedelic, other}. "Psychedelic" means
# the compound is a serotonergic hallucinogen (5-HT2A agonist family) OR a
# closely related research tool used in the same field (e.g. ibogaine analogues,
# 2-Br-LSD as a non-hallucinogenic control). The compounds page filters on this
# field; the dosages-page histogram further filters via PSYCHEDELIC_BUCKETS in
# dose-utils.js, so over-tagging here is harmless for the histogram.

# Explicit psychedelic tokens (lowercased, punctuation-free comparison).
# Built from a sweep over the actual corpus — every compound below has been
# confirmed by hand as a serotonergic hallucinogen or close analog/research
# tool. Add new entries as new compounds appear in the corpus.
PSYCHEDELIC_EXPLICIT = {
    # Tryptamines — psilocybin family
    "psilocybin", "psilocin", "norpsilocin",
    "psilacetin", "4-aco-dmt", "4-acetoxy-dmt",
    "4-aco-nmt", "4-aco-tmt", "4-aco-det",
    "4-ho-met", "4-oh-met", "4-ho-tmt", "4-ho-dipt", "4-oh-dipt",
    "4-ho-mipt", "4-oh-mipt", "4-ho-dpt", "4-oh-dpt", "4-ho-det", "4-oh-det",
    "baeocystin", "norbaeocystin", "aeruginascin",
    # Tryptamines — DMT / 5-MeO family
    "dmt", "n,n-dimethyltryptamine", "n,n-dmt",
    "ayahuasca",
    "5-meo-dmt", "5-methoxy-dmt",
    "5-meo-dipt", "5-meo-mipt", "5-meo-met",
    "5-meo-amt", "5-meo-dbt", "5-meo-pyrt",
    "4-f,5-meo-pyrt", "4-f-5-meo-pyrt",
    "det", "dpt", "dipt",
    "bufotenin", "bufotenine",
    # Lysergamides
    "lsd", "1p-lsd", "ald-52", "iso-lsd", "lisuride",
    "ecpla", "mipla", "lampa",
    "2-br-lsd", "2-br lsd", "2-bromo-lsd",
    # Phenethylamines — DO* family
    "doi", "dom", "dob", "doc",
    # Phenethylamines — 2C-* family
    "2c-b", "2c-c", "2c-d", "2c-e", "2c-h", "2c-i", "2c-p",
    "2c-t-2", "2c-t-7", "2c-t-21",
    # NBOMe / NBOH
    "25i-nbome", "25b-nbome", "25c-nbome",
    "25cn-nboh", "25h-nboh", "25cn-nbmd",
    "nbome", "nboh",
    # Mescaline family
    "mescaline", "methallylescaline", "tma", "tma-2", "tma-6", "bod",
    # Ibogaine family
    "ibogaine", "noribogaine", "tabernanthalog", "tbg",
    # Selective 5-HT2A agonists / research psychedelics
    "tcb-2", "tcb2", "ariadne", "zalsupindole",
    "re104", "re-104",  # deuterated 4-OH-DiPT prodrug
    # β-carbolines (ayahuasca pharmacology)
    "harmine", "harmaline", "tetrahydroharmine", "thh",
    # Salvinorin (kappa-opioid hallucinogen)
    "salvinorin a", "salvinorin-a",
    # Mushroom extracts treated as psychedelic preparations
    "psilocybe", "pholiotina", "panaeolus",
}

# Substring patterns: catches systematic families with arbitrary substituents
# (e.g. "(R)-DOI", "25CN-NBOMe-N-Me", "novel 5-MeO-tryptamine analog 12").
# We require these as substrings after normalisation (lowercase, single-space).
PSYCHEDELIC_PATTERNS = (
    "psilocy", "psilo",            # psilocybin, psilocin, psilacetin
    "4-aco-", "4-acetoxy",          # acetoxy-tryptamines
    "4-ho-", "4-oh-",               # hydroxy-tryptamines (psilocin family)
    "5-meo-",                       # 5-methoxy-tryptamines
    "nbome", "nboh", "nbmd",        # N-benzyl phenethylamines
    " lsd", "-lsd",                 # lysergamide analogs
    "ibogai", "ibogan",             # ibogaine-class
    "mescali",                      # mescaline analogs
    "lysergamide", "lysergic",
    "tryptamine",                   # generic tryptamine (catches novel analogs)
    "harman", "harmine", "harmali", # β-carbolines
)


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def classify(compound: str) -> str:
    c = _norm(compound)
    if not c:
        return "other"
    # Punctuation-stripped form for the explicit set
    cstrip = "".join(ch for ch in c if ch.isalnum() or ch in "- ,.")
    if c in PSYCHEDELIC_EXPLICIT or cstrip in PSYCHEDELIC_EXPLICIT:
        return "psychedelic"
    for alias in PSYCHEDELIC_EXPLICIT:
        if alias in c:
            return "psychedelic"
    for pat in PSYCHEDELIC_PATTERNS:
        if pat in c:
            return "psychedelic"
    return "other"


w = csv.writer(sys.stdout)
w.writerow(["stem", "snippet_id", "compound", "class", "dose", "route", "administered", "context"])

for path in sorted(CONSENSUS_DIR.glob("*.json")):
    if path.name.startswith("_"):
        continue
    stem = path.stem
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        continue
    # Mirror studies.json.py: papers that scored through but contributed no
    # behavioural assays (chemistry / analytical / out-of-scope) are dropped
    # from the rest of the dashboard. Excluding them here too means clicking
    # a histogram bin never lands on a "Study not found" page.
    if not data.get("assays"):
        continue
    dosing = data.get("dosing") or []
    if not isinstance(dosing, list):
        continue
    for snippet_id, entry in enumerate(dosing):
        if not isinstance(entry, dict):
            continue
        compound = (entry.get("compound") or "").strip()
        if not compound:
            continue
        route = (entry.get("route") or "").strip()
        evidence = (entry.get("evidence") or "").strip()
        klass = classify(compound)
        doses_mg = entry.get("doses_mg_per_kg") or []
        if isinstance(doses_mg, list) and doses_mg:
            for dose in doses_mg:
                if dose is None:
                    continue
                try:
                    dose_str = f"{float(dose):g} mg/kg"
                except (TypeError, ValueError):
                    continue
                w.writerow([stem, snippet_id, compound, klass, dose_str,
                            route, "True", evidence])
        else:
            # No numeric mg/kg parsed — fall back to the raw dose string so the
            # paper still shows up in cross-compound counts. The dashboard's
            # parseDose() will silently drop it from the histogram if it can't
            # extract a number.
            raw = (entry.get("doses_raw") or "").strip()
            if raw:
                w.writerow([stem, snippet_id, compound, klass, raw,
                            route, "True", evidence])

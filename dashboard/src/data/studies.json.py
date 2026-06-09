"""Build-time loader: bundle all per-paper consensus JSONs into one studies.json,
augmented with sex classification from results/sex_all.csv and assay data from
results/paper_assays.json."""
import csv
import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).parents[3] / "data"   # published datasets
CONSENSUS_DIR = ROOT / "results_v2_full_consensus"
SEX_CSV = ROOT / "results" / "sex_all.csv"
AGE_CSV = ROOT / "results" / "age_all.csv"
REGISTRY_JSON = ROOT / "paper_registry.json"
PAPER_ASSAYS_JSON = ROOT / "results" / "paper_assays.json"


def nfc(s: str) -> str:
    """NFC-normalise a string.

    macOS HFS+ returns filenames in NFD (decomposed accents, e.g. 'a' +
    combining-acute), while Zotero/JSON metadata uses NFC (precomposed, e.g.
    'á').  They look identical but differ byte-for-byte, so dict lookups fail
    silently.  Normalising both sides to NFC before any lookup fixes this.
    """
    return unicodedata.normalize("NFC", s or "")


def normalise_sex(raw: str) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return "not reported"
    if "both" in s:
        return "both sexes"
    if "male only" in s or s == "male":
        return "male only"
    if "female only" in s or s == "female":
        return "female only"
    if "unknown" in s or "not reported" in s:
        return "not reported"
    return s


def stem(study_id: str) -> str:
    """Canonical lookup key: NFC-normalised, lowercased, spaces stripped."""
    return nfc(study_id or "").lower().replace(" ", "")


registry: dict[str, dict] = {}
if REGISTRY_JSON.exists():
    try:
        # NFC-normalise registry keys so accented surnames match HFS+ filenames
        raw_reg = json.loads(REGISTRY_JSON.read_text())
        registry = {nfc(k): v for k, v in raw_reg.items()}
    except json.JSONDecodeError:
        registry = {}

assays_by_stem: dict[str, list] = {}
if PAPER_ASSAYS_JSON.exists():
    raw_assays = json.loads(PAPER_ASSAYS_JSON.read_text())
    for k, v in raw_assays.items():
        assays_by_stem[stem(k)] = v

sex_by_stem: dict[str, str] = {}
sex_evidence_by_stem: dict[str, str] = {}
if SEX_CSV.exists():
    with open(SEX_CSV, newline="") as f:
        for row in csv.DictReader(f):
            key = stem(row.get("study_id", ""))
            if not key:
                continue
            sex_by_stem[key] = normalise_sex(row.get("sex_classification", ""))
            sex_evidence_by_stem[key] = (row.get("evidence") or "").strip()

age_by_stem: dict[str, dict] = {}
if AGE_CSV.exists():
    with open(AGE_CSV, newline="") as f:
        for row in csv.DictReader(f):
            key = stem(row.get("study_id", ""))
            if not key:
                continue
            age_by_stem[key] = {
                "age_band": row.get("age_band") or "not_reported",
                "age_min_days": row.get("age_min_days") or "",
                "age_max_days": row.get("age_max_days") or "",
                "age_evidence": (row.get("evidence") or "").strip(),
            }

studies = []
for f in sorted(CONSENSUS_DIR.glob("*.json")):
    if f.name == "study_scores.csv":
        continue
    try:
        d = json.loads(f.read_text())
    except json.JSONDecodeError:
        continue
    d["_stem"] = f.stem
    if isinstance(d.get("psychedelic"), list):
        d["psychedelic"] = ", ".join(str(x) for x in d["psychedelic"])
    # NFC-normalise the filename stem before any lookup — macOS HFS+ uses NFD
    key = stem(f.stem)   # canonical: NFC + lowercase + no spaces

    # ----- Sex --------------------------------------------------------------
    # The dashboard reads `study.sex` as a string ("male only", "both sexes",
    # ...). v1 consensus didn't carry sex at all (we'd join it from
    # results/sex_all.csv). v2 consensus has it as a dict
    # {value, n_male, n_female, evidence, confidence}. Handle both shapes so
    # the new dataset is a drop-in replacement.
    raw_sex = d.get("sex")
    sex_str = None
    sex_evidence = ""
    if isinstance(raw_sex, dict):
        sex_str = normalise_sex(raw_sex.get("value", ""))
        sex_evidence = (raw_sex.get("evidence") or "").strip()
        # Preserve the full structured form alongside the string view.
        d["sex_structured"] = raw_sex
    elif isinstance(raw_sex, str) and raw_sex.strip():
        sex_str = normalise_sex(raw_sex)
    if not sex_str:
        sex_str = sex_by_stem.get(key) or sex_by_stem.get(stem(d.get("study_id", "")))
    if not sex_evidence:
        sex_evidence = (sex_evidence_by_stem.get(key)
                        or sex_evidence_by_stem.get(stem(d.get("study_id", "")))
                        or "")
    d["sex"] = sex_str or "not reported"
    if sex_evidence:
        d["sex_evidence"] = sex_evidence

    # ----- Age --------------------------------------------------------------
    # v1: no age in consensus → fill from results/age_all.csv sidecar.
    # v2: age is a dict {value, age_min_days, age_max_days, evidence,
    #     confidence}. Flatten value → age_band for backward compatibility
    #     and surface the structured form as age_structured.
    raw_age = d.get("age")
    if isinstance(raw_age, dict):
        d["age_structured"] = raw_age
        d["age_band"] = raw_age.get("value") or "not_reported"
        if raw_age.get("age_min_days") not in (None, "", "null"):
            d["age_min_days"] = str(raw_age["age_min_days"])
        if raw_age.get("age_max_days") not in (None, "", "null"):
            d["age_max_days"] = str(raw_age["age_max_days"])
        if raw_age.get("evidence"):
            d["age_evidence"] = raw_age["evidence"]
    else:
        age = age_by_stem.get(key) or age_by_stem.get(stem(d.get("study_id", "")))
        if age:
            d.update(age)
        else:
            d["age_band"] = "not_reported"

    # ----- Psychedelic / dosing --------------------------------------------
    # If v2 has structured `dosing`, derive a comma-separated psychedelic
    # string when one isn't already set. The dashboard's compound bucketing
    # works off the free-text `psychedelic` field, so this preserves it.
    raw_dosing = d.get("dosing")
    if isinstance(raw_dosing, list) and raw_dosing:
        if not d.get("psychedelic"):
            names = [str(e.get("compound", "")).strip() for e in raw_dosing
                     if isinstance(e, dict) and e.get("compound")]
            if names:
                # dedupe while preserving order
                seen = set()
                d["psychedelic"] = ", ".join(n for n in names
                                             if not (n in seen or seen.add(n)))
    # Merge canonical/category from paper_assays.json INTO the rich consensus
    # assay objects, rather than replacing them. Pre-existing behaviour was to
    # overwrite the full scored assay list with the simplified
    # {canonical, category, raw} catalog rows — which silently stripped
    # behavioural_complexity, environmental_complexity, recording_duration,
    # experimental_conditions (and the new v2 outcomes / sample_size fields)
    # from study.assays, breaking the per-study detail page.
    catalog_rows = (assays_by_stem.get(key)
                    or assays_by_stem.get(stem(d.get("study_id", "")))
                    or [])
    # Index catalog rows by their `raw` field (== consensus assay_name).
    catalog_by_raw: dict[str, dict] = {}
    for row in catalog_rows:
        raw_name = (row.get("raw") or "").strip()
        if raw_name and raw_name not in catalog_by_raw:
            catalog_by_raw[raw_name] = row
    consensus_assays = d.get("assays") or []
    if consensus_assays:
        merged = []
        for a in consensus_assays:
            cat = catalog_by_raw.get((a.get("assay_name") or "").strip())
            if cat:
                a = dict(a)
                a.setdefault("canonical", cat.get("canonical"))
                a.setdefault("category", cat.get("category"))
                a.setdefault("raw", cat.get("raw"))
            merged.append(a)
        d["assays"] = merged
    else:
        # No assays in the consensus (shouldn't happen post-scoring, but be
        # defensive): fall back to the simplified catalog rows so filters
        # at least know what the paper measures.
        d["assays"] = catalog_rows
    reg = registry.get(key) or registry.get(stem(d.get("study_id", "")))
    if reg:
        if reg.get("title"): d["title"] = reg["title"].strip().rstrip(".")
        if reg.get("journal"): d["journal"] = reg["journal"]
        if reg.get("authors"): d["authors"] = reg["authors"]
        if reg.get("year"): d["pub_year"] = reg["year"]
        if reg.get("url"): d["url"] = reg["url"]

    # Safety net: drop papers that came through scoring with zero assays.
    # In practice these are out-of-scope chemistry / analytical / review
    # papers that crept through screening — they have no behavioural data
    # to contribute to any dashboard view. Explicitly out-of-scope papers
    # should still be added to results/excluded_papers.csv (via
    # exclude_papers.py) so they're tracked, but this filter catches drift.
    if not d.get("assays"):
        continue
    studies.append(d)

json.dump(studies, sys.stdout, ensure_ascii=False, separators=(",", ":"))

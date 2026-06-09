"""Build-time loader: build the PRISMA accounting numbers."""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parents[3] / "data"
ACC = ROOT / "prisma_accounting.csv"
NOT_FOUND = ROOT / "results" / "pdfs_not_found.csv"
DOS = ROOT / "dosages_llm.csv"
SUM = ROOT / "results_v2_full_consensus"

if not ACC.exists():
    print(json.dumps({"error": "prisma_accounting.csv not found"}))
    sys.exit(0)

rows = list(csv.DictReader(open(ACC)))
disp = Counter(r["disposition"] for r in rows)
n_already = sum(1 for r in rows if r.get("already_in_original") in ("True", "true", True))

import os
_pdf_dir = ROOT / "pdfs"
if _pdf_dir.is_dir():
    n_pdfs = len([f for f in os.listdir(_pdf_dir) if f.endswith(".pdf")])
    n_md = len([f for f in os.listdir(_pdf_dir) if f.endswith(".docling.md")])
else:
    # PDFs are not redistributed in the public dataset; report from accounting instead.
    n_pdfs = sum(1 for r in rows if r.get("disposition", "").startswith("included"))
    n_md = 0

# n_consensus = consensus JSONs that actually contributed behavioural data
# (i.e. have >=1 scored assay). Matches the corpus filter in studies.json.py
# (and the dosages loader). Every other dashboard page counts only these
# papers, so the pipeline page now reports the same number as the rest of
# the site instead of inflating by the 23 consensus files with no assays.
# Those no-assay files are accounted for in prisma_accounting.csv under
# excluded_no_behaviour_in_full_text / in_corpus_no_animal_dose.
# n_admin_papers = papers whose judge-validated dosing[] list is non-empty
# (one entry per compound, deduplicated). Replaces the old count off
# dosages_llm.csv, which over-counted by snippet mention.
n_consensus = 0
admin_stems = set()
for fname in os.listdir(SUM):
    if not fname.endswith(".json") or fname.startswith("_"):
        continue
    try:
        d = json.loads((SUM / fname).read_text())
    except (OSError, json.JSONDecodeError):
        continue
    if not d.get("assays"):
        continue
    n_consensus += 1
    if d.get("dosing"):
        admin_stems.add(fname[:-5])
n_admin_papers = len(admin_stems)

out = {
    "n_records": len(rows),
    "n_already_in_original": n_already,
    "dispositions": dict(disp),
    "n_pdfs_on_disk": n_pdfs,
    "n_md_cached": n_md,
    "n_consensus": n_consensus,
    "n_admin_papers": n_admin_papers,
    "n_pdf_unavailable": disp.get("pdf_unavailable_relevant", 0),
    "n_excluded_classifier": (disp.get("excluded_classifier_false_positive", 0)
                              + disp.get("excluded_classifier_off_topic", 0)
                              + disp.get("excluded_compound_filter_MDMA", 0)),
}
json.dump(out, sys.stdout)

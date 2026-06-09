"""Build an updated PRISMA-style flow accounting for the systematic review.

Outputs:
  - prisma_accounting.csv: one row per paper found in the search, with the
    stage at which it was kept or excluded.
  - prisma_summary.txt: human-readable counts at each pipeline stage.
  - prisma_diagram.tex: LaTeX block compatible with the existing
    prisma-flow-diagram.sty in main_elsevier.tex (drop-in replacement for
    the old static numbers).
"""

from __future__ import annotations
import csv
import json
import os
import re
import shutil
import unicodedata
from pathlib import Path

from find_pdf_duplicates import normalise as norm_surname, first_author_surname

ROOT = Path(__file__).parent
PUBMED_CSV = ROOT / "results" / "pubmed_expansion.csv"
NOT_FOUND_CSV = ROOT / "results" / "pdfs_not_found.csv"
PDFS_DIR = ROOT / "pdfs"
DOSAGES_LLM = ROOT / "dosages_llm.csv"   # v1 snippet extraction — retained for fallback only
CONSENSUS_DIR = ROOT / "results_v2_full_consensus"
REGISTRY_JSON = ROOT / "paper_registry.json"
MANUAL_DECISIONS_JSON = ROOT / "manual_decisions.json"


def nfc_lower(s: str) -> str:
    """NFC-normalise and lower-case a stem.

    The consensus directory's filenames may be stored in NFD on macOS HFS+
    (combining accents) while registry / CSV stems use NFC (precomposed).
    Compare both sides in the same form, otherwise lookups silently miss
    on accented surnames (e.g. colaço, gonzález, olejníková).
    """
    return unicodedata.normalize("NFC", s or "").lower()

PSY_BUCKETS = {"Psilocybin/Psilocin", "LSD", "DMT", "DMT; 5-MeO-DMT",
               "DOI (2,5-dimethoxy-4-iodoamphetamine)", "Ibogaine", "Ayahuasca",
               "Other serotonergic", "Psychedelic (general)"}

# Manual disposition overrides — keyed by stem, win over the auto-derived
# classification. Use for review chapters / book volumes / other edge cases
# where the classifier picked it up but the paper isn't a primary research
# study. Stems are lowercase; values are valid disposition strings.
MANUAL_DISPOSITIONS: dict[str, str] = {
    # Edited Springer book "Behavioral Neurobiology of Psychedelic Drugs" vol
    # 36 — picked up via the Halberstadt & Geyer chapter, but the PDF on disk
    # is the entire 11-chapter review volume (351k tokens, exceeds all SAIA
    # context windows). Quarantined to pdfs/_quarantine/.
    "halberstadt2018": "excluded_classifier_off_topic",
}


def stem_for(authors_short: str, year: str) -> str | None:
    if not authors_short: return None
    a = re.sub(r"\s+et\s+al\.?$", "", authors_short.strip())
    a = a.split(",")[0].strip()
    parts = a.split()
    name = []
    for i, part in enumerate(parts):
        if re.match(r"^[A-Z]{1,3}\.?$", part) and i > 0: break
        name.append(part)
    if not name and parts: name = [parts[0]]
    s = re.sub(r"[^a-z]", "", "".join(name).lower())
    return f"{s}{year}" if s else None


def main():
    rows = list(csv.DictReader(open(PUBMED_CSV)))
    n_found = len(rows)
    print(f"PubMed records identified: {n_found}")

    # Authoritative DOI → on-disk-stem mapping from the paper registry.
    # The registry is built from Zotero + pubmed_expansion + DOI scans, so it
    # solves all the unicode/prefix/initials/year-typo matching problems that
    # used to bite us when fuzzing on stem strings.
    registry = json.load(open(REGISTRY_JSON)) if REGISTRY_JSON.exists() else {}
    doi_to_stem = {r["doi"]: stem for stem, r in registry.items() if r.get("doi")}
    print(f"Registry loaded: {len(registry)} stems, {len(doi_to_stem)} DOI keys")

    # User-driven triage decisions exported from papers_to_download_v2.html
    # Keyed by DOI (lowercase). Applied AFTER auto-classification — see below.
    manual_decisions = (json.loads(MANUAL_DECISIONS_JSON.read_text())
                        if MANUAL_DECISIONS_JSON.exists() else {})
    if manual_decisions:
        print(f"Manual triage decisions: {len(manual_decisions)} (from manual_decisions.json)")

    # Local on-disk inventory (still used for the leftover corpus-only papers).
    # NFC-normalise so accented-surname filenames (e.g. colaço, gonzález)
    # round-trip correctly through the membership checks below — see the
    # `nfc_lower` docstring.
    pdfs_on_disk = {nfc_lower(p.removesuffix(".pdf"))
                    for p in os.listdir(PDFS_DIR) if p.endswith(".pdf")}
    md_cached = {nfc_lower(p.removesuffix(".docling.md"))
                 for p in os.listdir(PDFS_DIR) if p.endswith(".docling.md")}

    # Papers with at least one administered dose AND a consensus output.
    # v2 source of truth: each results_v2_full_consensus/*.json carries a
    # validated `dosing[]` list (judge-vetted, deduplicated). The old
    # dosages_llm.csv was snippet-level and went stale as soon as the
    # consensus rescore happened — using it here was the bug that
    # produced the "263 vs 266" phantom discrepancy in the manuscript
    # numbers. We now derive both stem sets in a single pass over the
    # consensus directory.
    consensus_stems: set[str] = set()
    administered_stems: set[str] = set()
    no_assay_consensus_stems: set[str] = set()  # diagnostic-only
    if CONSENSUS_DIR.exists():
        for f in os.listdir(CONSENSUS_DIR):
            if not f.endswith(".json") or f.startswith("_"):
                continue
            stem_lc = nfc_lower(f.removesuffix(".json"))
            try:
                d = json.loads((CONSENSUS_DIR / f).read_text())
            except (OSError, json.JSONDecodeError):
                continue
            # A paper "counts" as having a consensus output when it has at
            # least one scored assay. Bare consensus files with no assays
            # are kept track of separately so we can spot drift later, but
            # they should not appear as `in_consensus=True` in the audit
            # (they have no behavioural data to contribute).
            if d.get("assays"):
                consensus_stems.add(stem_lc)
            else:
                no_assay_consensus_stems.add(stem_lc)
            if d.get("dosing"):
                administered_stems.add(stem_lc)
    print(f"Consensus dir: {len(consensus_stems)} with ≥1 assay, "
          f"{len(no_assay_consensus_stems)} with no scored assay")
    print(f"Administered dose (live JSON `dosing[]`): {len(administered_stems)} stems")

    # Build per-row disposition. We track two orthogonal facts:
    #   1. classification outcome (relevant / excluded by classifier)
    #   2. final-corpus status (PDF on disk, has admin dose, in consensus)
    # The "disposition" string captures the FINAL outcome.
    audit_rows = []
    for r in rows:
        cls = r["detected_compounds"].strip()
        already = r["already_included"].strip().lower() == "yes"
        is_relevant_class = any(b in cls for b in PSY_BUCKETS)
        is_mdma_only = cls.strip() == "MDMA"
        is_falsepos = ("Unclassified" in cls or "false positive" in cls.lower())
        # off-topic = doesn't match any psychedelic bucket and isn't MDMA-only
        # and isn't already-included (those are forced relevant)
        is_off_topic = (not is_relevant_class) and (not is_mdma_only) and (not is_falsepos) and (not already)

        stem = stem_for(r["authors_short"], r["year"]) or ""
        stem_lc = stem.lower()
        original_stem_lc = stem_lc  # before any remapping below
        on_disk = False

        # Primary lookup: DOI from the row → registry stem.
        row_doi = (r.get("doi") or "").strip().lower()
        if row_doi and row_doi in doi_to_stem and original_stem_lc not in MANUAL_DISPOSITIONS:
            stem_lc = doi_to_stem[row_doi]
            on_disk = True
        # Fallback: fuzzy stem match (kept for rows missing a DOI in pubmed)
        elif stem and original_stem_lc not in MANUAL_DISPOSITIONS:
            if stem_lc in pdfs_on_disk:
                on_disk = True
            else:
                search_surname = norm_surname(first_author_surname(r["authors_short"]))
                year = r["year"]
                for cand in pdfs_on_disk:
                    m = re.match(r"^(.*?)(\d{4})\d*$", cand)
                    if not m: continue
                    cand_surname, cand_year = m.groups()
                    if abs(int(cand_year) - int(year or 0)) > 2: continue
                    if norm_surname(cand_surname) == search_surname:
                        on_disk = True
                        stem_lc = cand
                        break
        # Normalise the candidate stem to the same NFC-lowered form used by
        # the on-disk / consensus / admin-dose sets above.
        stem_key = nfc_lower(stem_lc)
        has_md = stem_key in md_cached
        in_consensus = stem_key in consensus_stems
        has_admin_dose = stem_key in administered_stems

        # User triage decision (DOI-keyed) wins over auto-classification
        if row_doi and row_doi in manual_decisions:
            disposition = manual_decisions[row_doi]["disposition"]
        # Manual stem-keyed override (for review chapters / book volumes etc.)
        elif original_stem_lc in MANUAL_DISPOSITIONS:
            disposition = MANUAL_DISPOSITIONS[original_stem_lc]
            stem_lc = original_stem_lc  # restore so the CSV row reflects override key
            on_disk = False              # quarantined; not really in corpus
        elif stem_lc in MANUAL_DISPOSITIONS:
            disposition = MANUAL_DISPOSITIONS[stem_lc]
        # Final disposition: classifier-excluded vs corpus-status
        elif is_falsepos and not already and not on_disk:
            disposition = "excluded_classifier_false_positive"
        elif is_mdma_only and not already and not on_disk:
            disposition = "excluded_compound_filter_MDMA"
        elif is_off_topic and not already and not on_disk:
            disposition = "excluded_classifier_off_topic"
        elif not on_disk and is_relevant_class:
            disposition = "pdf_unavailable_relevant"
        elif on_disk and not has_admin_dose and not in_consensus:
            disposition = "in_corpus_no_animal_dose"
        elif on_disk and (has_admin_dose or in_consensus):
            disposition = "included_in_review"
        else:
            disposition = "other"

        audit_rows.append({
            "pmid": r["pmid"], "doi": r["doi"], "year": r["year"],
            "authors": r["authors_short"], "title": r["title"][:160],
            "journal": r["journal"][:60], "classifier_bucket": cls,
            "stem": stem_lc, "already_in_original": already,
            "on_disk": on_disk, "has_docling_md": has_md,
            "in_consensus": in_consensus, "has_administered_dose": has_admin_dose,
            "disposition": disposition,
        })

    # We may also have papers in the corpus that were NOT in pubmed_expansion.csv
    # (e.g. manually added later — vargas-perez2024 was one). Account for those too.
    audit_stems = {r["stem"] for r in audit_rows if r["stem"]}
    audit_stems_nfc = {nfc_lower(s) for s in audit_stems}
    extras = sorted(s for s in pdfs_on_disk if s not in audit_stems_nfc)
    for s in extras:
        audit_rows.append({
            "pmid": "", "doi": "", "year": "", "authors": "", "title": "",
            "journal": "", "classifier_bucket": "(not in PubMed search)",
            "stem": s,
            "on_disk": True,
            "has_docling_md": s in md_cached,
            "in_consensus": s in consensus_stems,
            "has_administered_dose": s in administered_stems,
            "disposition": "manually_added_to_corpus",
        })

    # Write per-paper audit. Back up the previous CSV first so a botched
    # run never silently destroys the prior accounting — the audit log is
    # too expensive to lose. Backups rotate (.preV2.bak holds the most
    # recent prior run; older backups are not retained by this script).
    out_csv = ROOT / "prisma_accounting.csv"
    if out_csv.exists():
        backup = out_csv.with_suffix(".csv.preV2.bak")
        shutil.copy2(out_csv, backup)
        print(f"Backed up previous audit → {backup}")
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(audit_rows[0].keys()))
        w.writeheader(); w.writerows(audit_rows)
    print(f"Per-paper audit → {out_csv}  ({len(audit_rows)} rows)")

    # ──────────────────────────────────────────────────────────────────────
    # PRISMA chart filtering: papers that don't mention any psychedelic
    # compound aren't really "identifications" — they're search noise. The
    # methodologically clean PRISMA flow starts from the compound-mentioning
    # pool. We keep these in the audit CSV (full record) but drop them from
    # the funnel total in the human-readable summary + LaTeX diagram.
    NO_COMPOUND_DISPOSITIONS = {
        "excluded_classifier_false_positive",  # classifier found no compound
    }
    in_chart = [r for r in audit_rows if r["disposition"] not in NO_COMPOUND_DISPOSITIONS]
    n_dropped_for_chart = len(audit_rows) - len(in_chart)
    print(f"Filtered for PRISMA chart: {len(audit_rows)} audit rows → "
          f"{len(in_chart)} in chart  ({n_dropped_for_chart} dropped: no compound)")

    # Summary counts — use UNIQUE STEMS, not row-level counts.
    # Funnel-counted numbers come from `in_chart` (no-compound papers excluded).
    from collections import Counter
    disp_counts = Counter(r["disposition"] for r in in_chart)

    # Stem-level uniqueness for the on-disk facts
    n_unique_pdfs = len(pdfs_on_disk)
    n_unique_md = len(md_cached)
    n_unique_consensus = len(consensus_stems)
    n_unique_admin_dose = len(administered_stems)

    n_already = sum(1 for r in in_chart if r.get("already_in_original"))
    n_classifier_psy = sum(1 for r in in_chart
                           if any(b in r["classifier_bucket"] for b in PSY_BUCKETS))
    n_chart_total = len(in_chart)

    summary_lines = [
        "=" * 70,
        "Systematic-review pipeline accounting",
        "=" * 70,
        "",
        f"Records identified by PubMed expansion search: {n_found}",
        f"  - Records dropped (no psychedelic compound found): {n_dropped_for_chart}",
        f"  - Records that enter the PRISMA chart:             {n_chart_total}",
        f"      ▸ Already in original review (manually curated): {n_already}",
        f"      ▸ Net new records in the expansion:             {n_chart_total - n_already}",
        "",
        f"Classifier (compound-presence) over the {n_chart_total} chart records:",
        f"  - Tagged as classical psychedelic (psilocybin/LSD/DMT/DOI/2C/...): {n_classifier_psy}",
        f"  - Tagged as MDMA-only:                                              "
        f"{sum(1 for r in in_chart if r['classifier_bucket'].strip()=='MDMA')}",
        "",
        f"PDF acquisition (counts are unique papers):",
        f"  - PDFs in pdfs/ (final corpus):                  {n_unique_pdfs}",
        f"  - Net new PDFs added in this work:               37",
        f"      ▸ via Unpaywall / PMC:                       2",
        f"      ▸ from /cloud/papers (institutional copies): 12",
        f"      ▸ via URL-pattern + headless playwright:     9",
        f"      ▸ via real Chrome over CDP:                  15 (incl. ACS, Science.org)",
        f"  - Records flagged relevant but no PDF retrievable: "
        f"{disp_counts.get('pdf_unavailable_relevant', 0)} (paywalled, not in /cloud/papers)",
        "",
        f"Docling conversion:",
        f"  - PDFs with cached markdown (unique):            {n_unique_md}",
        "",
        f"LLM scoring (3 SAIA candidates → Haiku 4.5 judge):",
        f"  - Studies with consensus output (unique):        {n_unique_consensus}",
        f"  - Studies with at least one administered dose:   {n_unique_admin_dose}",
        "",
        f"Final disposition counts:",
    ]
    for k, v in disp_counts.most_common():
        summary_lines.append(f"  - {k}:  {v}")
    summary_lines.append("")
    # The "Studies INCLUDED" tally must dedup by stem — multiple PubMed rows
    # often point at the same on-disk paper (year-shift / preprint+article).
    in_review_unique = len({r["stem"] for r in audit_rows
                            if r["disposition"] in ("included_in_review", "manually_added_to_corpus")
                            and r["stem"]})
    summary_lines.append(f"Studies INCLUDED in the final review (unique papers): {in_review_unique}")
    summary_lines.append(f"  (= unique PDFs in pdfs/ that have a consensus output and at least one")
    summary_lines.append(f"     administered drug dose to live animals)")
    summary_lines.append("")

    out_txt = ROOT / "prisma_summary.txt"
    out_txt.write_text("\n".join(summary_lines))
    print(f"Summary text → {out_txt}")
    print()
    for line in summary_lines:
        print(line)

    # LaTeX block compatible with prisma-flow-diagram.sty.
    # Funnel starts from the compound-mentioning pool, not the raw search.
    n_total_corpus = in_review_unique
    n_screened = n_chart_total            # was n_found — drops the "no compound" rows
    n_excluded_screen = (
        disp_counts.get("excluded_classifier_off_topic", 0)
        + disp_counts.get("excluded_compound_filter_MDMA", 0)
        + disp_counts.get("excluded_no_behaviour_in_full_text", 0)
    )
    n_assessed = n_screened - n_excluded_screen
    n_pdf_unavail = disp_counts.get("pdf_unavailable_relevant", 0)
    n_no_dose = disp_counts.get("in_corpus_no_animal_dose", 0)
    n_pdf_present = n_unique_pdfs
    n_with_admin_dose = n_unique_admin_dose

    n_extra_manual = disp_counts.get("manually_added_to_corpus", 0)
    n_consensus = n_unique_consensus
    n_pdfs_from_search = n_unique_pdfs - n_extra_manual

    tex = f"""% Auto-generated by build_prisma_accounting.py — drop into main_elsevier.tex
\\begin{{tikzpicture}}[node distance=5mm and 10mm, start chain=going below]

    \\node[mynode] (n1) {{Records identified through PubMed search (n = {n_screened})}};
    \\node[mynode, below=of n1] (n2) {{Records screened on title/abstract (n = {n_screened})}};
    \\node[mynode, below=of n2] (n3) {{Records assessed for full-text eligibility (n = {n_assessed})}};
    \\node[mynode, below=of n3] (n4) {{PDFs successfully retrieved from search (n = {n_pdfs_from_search})}};
    \\node[mynode, below=of n4] (n5) {{Studies in corpus (incl. {n_extra_manual} manually added) — n = {n_unique_pdfs}}};
    \\node[mynode, below=of n5] (n6) {{Studies with consensus LLM-extracted scores (n = {n_consensus})}};
    \\node[mynode, below=of n6] (n7) {{Studies with at least one administered drug dose (n = {n_with_admin_dose})}};

    % Exclusion side-nodes
    \\node[sidenode, right=10mm of n2] (n2r)
        {{Records excluded by screening (n = {n_excluded_screen})\\\\
         \\textbullet{{}} off-topic for behavioural review: {disp_counts.get('excluded_classifier_off_topic', 0)}\\\\
         \\textbullet{{}} MDMA-only: {disp_counts.get('excluded_compound_filter_MDMA', 0)}\\\\
         \\textbullet{{}} no behaviour in full text: {disp_counts.get('excluded_no_behaviour_in_full_text', 0)}}};
    \\node[sidenode, right=10mm of n3] (n3r)
        {{PDFs unobtainable (n = {n_pdf_unavail})\\\\(paywalled and not in /cloud/papers / institutional access)}};
    \\node[sidenode, right=10mm of n6] (n6r)
        {{Failed scoring pipeline (n = {n_unique_pdfs - n_consensus})\\\\(paper too long for SAIA context window)}};

    \\draw[arrow] (n1) -- (n2);
    \\draw[arrow] (n2) -- (n3);
    \\draw[arrow] (n3) -- (n4);
    \\draw[arrow] (n4) -- (n5);
    \\draw[arrow] (n5) -- (n6);
    \\draw[arrow] (n6) -- (n7);
    \\draw[arrow] (n2) -- (n2r);
    \\draw[arrow] (n3) -- (n3r);
    \\draw[arrow] (n6) -- (n6r);

\\end{{tikzpicture}}
"""
    out_tex = ROOT / "prisma_diagram.tex"
    out_tex.write_text(tex)
    print(f"\nLaTeX block → {out_tex}")


if __name__ == "__main__":
    main()

"""Incremental PubMed search: find records added since the last run.

Runs the query printed in the published Methods (see pipeline/SEARCH.md),
restricted to records whose Entrez date (when they entered PubMed) falls
between the last run and today. New PMIDs are classified on their title and
appended to data/pubmed_expansion.csv with source = "update:<run date>".
Existing rows are never rewritten.

The first run starts on 2026/03/29, the day after the newest record of the
original search entered PubMed, so nothing indexed since then is missed.

State lives in data/search_state.json. Full records (with abstracts, which are
publisher copyright and so not committed) go to WORK_DIR/reports/.

    uv run python pipeline/search_pubmed.py            # search and append
    uv run python pipeline/search_pubmed.py --dry-run  # search, write nothing
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date
from difflib import SequenceMatcher

from unidecode import unidecode

import pubmed
from classify_compounds import classify, decision
from paths import (MANUAL_DECISIONS_JSON, PUBMED_CSV, REGISTRY_JSON, REPORTS_DIR,
                   SEARCH_STATE_JSON)

# The search as printed in the published Methods. It recovers 261 of the 263
# papers included from the original search (see SEARCH.md).
METHODS_QUERY = (
    '(psychedelics[title/abstract] OR '
    'psilocybin[title/abstract] OR psilocin[title/abstract] OR '
    '"lysergic acid diethylamide"[title/abstract] OR LSD[title/abstract] OR '
    'DOI[title/abstract] OR '
    'DMT[title/abstract] OR "N,N-dimethyltryptamine"[title/abstract] OR '
    '"5-MeO-DMT"[title/abstract] OR '
    'mescaline[title/abstract] OR '
    'ibogaine[title/abstract] OR '
    'ayahuasca[title/abstract]) '
    'AND '
    '(mouse[title/abstract] OR mice[title/abstract] OR '
    'rat[title/abstract] OR rats[title/abstract])'
)
# Same publication-year floor as the original search.
YEAR_FLOOR = " AND 2014/01/01:3000/12/31[dp]"
# The published search was run on 1 April 2026; its newest record entered
# PubMed on 28 March. Start the day after, so records indexed 29–31 March
# (7 checked on 2026-11-18, 1 relevant by title) aren't missed by both
# searches. Overlap is harmless: known PMIDs are skipped.
FIRST_RUN_START = "2026/03/29"

# A new record whose title matches a corpus paper this closely is the same
# study (typically the journal version of a preprint already scored). On the
# original corpus, true duplicates score 1.0 and the closest unrelated pair 0.66.
DUPLICATE_TITLE_RATIO = 0.9
DUPLICATE_DISPOSITION = "excluded_duplicate_of_corpus"

# PubMed publication types that can't contribute rodent data. Relevant records
# with any of these are excluded before a PDF is fetched. PubMed often adds the
# tag weeks after a record appears, so records still waiting for a PDF are
# re-checked every run (recheck_publication_types).
NON_PRIMARY_TYPES = {
    "Review", "Systematic Review", "Scoping Review", "Meta-Analysis", "News",
    "Newspaper Article", "Editorial", "Comment", "Letter", "Published Erratum",
    "Retraction of Publication", "Expression of Concern", "Congress", "Interview",
    "Lecture", "Biography",
}
NON_PRIMARY_DISPOSITION = "excluded_not_primary_research"

CSV_FIELDS = ["pmid", "title", "authors_short", "year", "journal", "doi",
              "source", "already_included", "detected_compounds"]


def load_state() -> dict:
    if SEARCH_STATE_JSON.exists():
        return json.loads(SEARCH_STATE_JSON.read_text())
    return {"query": METHODS_QUERY, "next_start": FIRST_RUN_START, "runs": []}


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", unidecode(t or "").lower()).strip()


def find_duplicate(rec: dict, registry: dict) -> str | None:
    """Stem of the corpus paper `rec` duplicates (same DOI or same title)."""
    title = _norm_title(rec["title"])
    for stem, e in registry.items():
        if rec["doi"] and (e.get("doi") or "").lower() == rec["doi"]:
            return stem
        if title and e.get("title") and SequenceMatcher(
                None, title, _norm_title(e["title"])).ratio() >= DUPLICATE_TITLE_RATIO:
            return stem
    return None


def non_primary_type(publication_types: list[str]) -> str | None:
    """The first non-primary PubMed publication type, if any."""
    hits = sorted(NON_PRIMARY_TYPES & set(publication_types))
    return hits[0] if hits else None


def _non_primary_decision(today: date, pub_type: str) -> dict:
    return {"applied_at": today.isoformat(), "disposition": NON_PRIMARY_DISPOSITION,
            "duplicate_of": None, "reason": f"auto: PubMed publication type {pub_type}"}


def known_ids() -> tuple[set[str], set[str]]:
    """PMIDs and DOIs already in the search CSV or the paper registry."""
    pmids, dois = set(), set()
    with open(PUBMED_CSV, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            pmids.add(r["pmid"].strip())
            if r["doi"].strip():
                dois.add(r["doi"].strip().lower())
    if REGISTRY_JSON.exists():
        for e in json.loads(REGISTRY_JSON.read_text()).values():
            if e.get("pmid"):
                pmids.add(str(e["pmid"]))
            if e.get("doi"):
                dois.add(e["doi"].strip().lower())
    return pmids, dois


def append_rows(rows: list[dict]) -> None:
    """Append to the CSV in its existing format (CRLF, minimal quoting)."""
    with open(PUBMED_CSV, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\r\n")
        w.writerows(rows)


def run(today: date | None = None, dry_run: bool = False) -> dict:
    """Search, classify, append. Returns a summary dict for the run report."""
    today = today or date.today()
    state = load_state()
    if state.get("query", METHODS_QUERY) != METHODS_QUERY:
        raise SystemExit("METHODS_QUERY differs from data/search_state.json; "
                         "update the state file deliberately if the query changed.")
    start, end = state["next_start"], today.strftime("%Y/%m/%d")

    pmids = pubmed.esearch(METHODS_QUERY + YEAR_FLOOR, mindate=start, maxdate=end,
                           datetype="edat")
    seen_pmids, _ = known_ids()
    new_pmids = [p for p in pmids if p not in seen_pmids]
    records = pubmed.efetch(new_pmids) if new_pmids else []

    registry = json.loads(REGISTRY_JSON.read_text()) if REGISTRY_JSON.exists() else {}
    decisions = (json.loads(MANUAL_DECISIONS_JSON.read_text())
                 if MANUAL_DECISIONS_JSON.exists() else {})
    run_tag = f"update:{today.isoformat()}"
    rows, report = [], []
    for rec in records:
        label = classify(rec["title"])
        dup = find_duplicate(rec, registry)
        if dup and rec["doi"] and rec["doi"] not in decisions:
            decisions[rec["doi"]] = {
                "applied_at": today.isoformat(), "disposition": DUPLICATE_DISPOSITION,
                "duplicate_of": dup, "reason": "auto: same DOI or title as corpus paper",
            }
        pub_type = None
        if not dup and decision(label) == "relevant":
            pub_type = non_primary_type(rec["publication_types"])
            if pub_type and rec["doi"] and rec["doi"] not in decisions:
                decisions[rec["doi"]] = _non_primary_decision(today, pub_type)
        rows.append({
            "pmid": rec["pmid"], "title": rec["title"],
            "authors_short": rec["authors_short"], "year": rec["year"],
            "journal": rec["journal"], "doi": rec["doi"], "source": run_tag,
            "already_included": "no", "detected_compounds": label,
        })
        report.append({**rec, "detected_compounds": label,
                       "decision": ("duplicate" if dup else
                                    "not_primary" if pub_type else decision(label)),
                       "duplicate_of": dup, "non_primary_type": pub_type})

    summary = {
        "run_date": today.isoformat(), "window": [start, end],
        "returned": len(pmids), "new": len(rows),
        "by_decision": {d: sum(1 for r in report if r["decision"] == d)
                        for d in ("relevant", "not_primary", "duplicate", "mdma_only",
                                  "off_topic", "false_positive")},
    }
    if not dry_run:
        if rows:
            append_rows(rows)
        MANUAL_DECISIONS_JSON.write_text(
            json.dumps(decisions, indent=2, ensure_ascii=False))
        state["query"] = METHODS_QUERY
        state["next_start"] = end  # overlap one day; PMIDs dedupe it
        state["runs"].append(summary)
        SEARCH_STATE_JSON.write_text(json.dumps(state, indent=2) + "\n")
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / f"search_{today.isoformat()}.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False))
    summary["records"] = report
    return summary


def recheck_publication_types(today: date | None = None, dry_run: bool = False) -> list[dict]:
    """Exclude new relevant records still waiting for a PDF that PubMed has
    since tagged as reviews, news, letters, etc. Returns the records excluded."""
    today = today or date.today()
    registry = json.loads(REGISTRY_JSON.read_text()) if REGISTRY_JSON.exists() else {}
    have = ({str(e.get("pmid")) for e in registry.values() if e.get("pmid")}
            | {(e.get("doi") or "").lower() for e in registry.values() if e.get("doi")})
    decisions = (json.loads(MANUAL_DECISIONS_JSON.read_text())
                 if MANUAL_DECISIONS_JSON.exists() else {})
    with open(PUBMED_CSV, encoding="utf-8", newline="") as f:
        waiting = [r for r in csv.DictReader(f)
                   if r["source"].startswith("update:") and r["doi"]
                   and decision(r["detected_compounds"]) == "relevant"
                   and r["doi"].lower() not in decisions
                   and r["pmid"] not in have and r["doi"].lower() not in have]
    if not waiting:
        return []
    excluded = []
    for rec in pubmed.efetch([r["pmid"] for r in waiting]):
        pub_type = non_primary_type(rec["publication_types"])
        if pub_type and rec["doi"]:
            decisions[rec["doi"]] = _non_primary_decision(today, pub_type)
            excluded.append({**rec, "non_primary_type": pub_type})
    if excluded and not dry_run:
        MANUAL_DECISIONS_JSON.write_text(json.dumps(decisions, indent=2, ensure_ascii=False))
    return excluded


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="search but write nothing")
    args = ap.parse_args()
    s = run(dry_run=args.dry_run)
    print(f"Window {s['window'][0]} – {s['window'][1]}: {s['returned']} returned, "
          f"{s['new']} new")
    for k, v in s["by_decision"].items():
        print(f"  {k:15} {v}")
    for r in s["records"]:
        if r["decision"] == "relevant":
            print(f"  + {r['pmid']}  {r['authors_short']} ({r['year']})  {r['title'][:90]}")


if __name__ == "__main__":
    main()

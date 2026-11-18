"""Incremental PubMed search: find records added since the last run.

Runs the query printed in the published Methods (see pipeline/SEARCH.md),
restricted to records whose Entrez date (when they entered PubMed) falls
between the last run and today. New PMIDs are classified on their title and
appended to data/pubmed_expansion.csv with source = "update:<run date>".
Existing rows are never rewritten.

The first run starts at the published search cutoff (2026/04/01), so anything
indexed after the original search is picked up once.

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
# The published search was run on 1 April 2026.
FIRST_RUN_START = "2026/04/01"

# A new record whose title matches a corpus paper this closely is the same
# study (typically the journal version of a preprint already scored). On the
# original corpus, true duplicates score 1.0 and the closest unrelated pair 0.66.
DUPLICATE_TITLE_RATIO = 0.9
DUPLICATE_DISPOSITION = "excluded_duplicate_of_corpus"

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
        rows.append({
            "pmid": rec["pmid"], "title": rec["title"],
            "authors_short": rec["authors_short"], "year": rec["year"],
            "journal": rec["journal"], "doi": rec["doi"], "source": run_tag,
            "already_included": "no", "detected_compounds": label,
        })
        report.append({**rec, "detected_compounds": label,
                       "decision": "duplicate" if dup else decision(label),
                       "duplicate_of": dup})

    summary = {
        "run_date": today.isoformat(), "window": [start, end],
        "returned": len(pmids), "new": len(rows),
        "by_decision": {d: sum(1 for r in report if r["decision"] == d)
                        for d in ("relevant", "duplicate", "mdma_only", "off_topic",
                                  "false_positive")},
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

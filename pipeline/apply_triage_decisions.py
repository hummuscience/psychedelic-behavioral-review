"""Merge the triage decisions exported from papers_to_download_v2.html into a
durable JSON file that build_prisma_accounting.py reads on every rebuild.

Input  CSV columns:  doi,status,reason,prisma_disposition,duplicate_of
Output JSON:         {"<doi>": {"reason": "...", "disposition": "...", "applied_at": "..."}}

The reason→disposition map is what the HTML page already chose:
    done           → included_in_review
    skip_nobeh     → excluded_classifier_off_topic   (no behaviour reported)
    skip_off       → excluded_classifier_off_topic   (off-topic for the review)
    skip_fp        → excluded_classifier_false_positive
    skip_mdma      → excluded_compound_filter_MDMA
    skip_paywall   → pdf_unavailable_relevant        (no change, but explicit)
    skip_dup       → excluded_duplicate_of_corpus    (new bucket)
"""
from __future__ import annotations
import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

from paths import MANUAL_DECISIONS_JSON as OUT

REASON_TO_DISPOSITION = {
    "done":         "included_in_review",
    "skip_nobeh":   "excluded_classifier_off_topic",
    "skip_off":     "excluded_classifier_off_topic",
    "skip_fp":      "excluded_classifier_false_positive",
    "skip_mdma":    "excluded_compound_filter_MDMA",
    "skip_paywall": "pdf_unavailable_relevant",
    "skip_dup":     "excluded_duplicate_of_corpus",
    # Direct passthrough for the excluded_review.html exporter
    "excluded_no_behaviour_in_full_text": "excluded_no_behaviour_in_full_text",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("decisions_csv", type=Path, help="Path to exported papers-decisions-*.csv")
    ap.add_argument("--merge", action="store_true",
                    help="Merge into existing manual_decisions.json (default: replace)")
    args = ap.parse_args()

    if not args.decisions_csv.exists():
        sys.exit(f"missing: {args.decisions_csv}")

    existing: dict = {}
    if args.merge and OUT.exists():
        existing = json.loads(OUT.read_text())

    new_rows = list(csv.DictReader(open(args.decisions_csv)))
    today = date.today().isoformat()
    skipped, applied = 0, 0
    for r in new_rows:
        doi = (r.get("doi") or "").strip().lower()
        reason = (r.get("reason") or "").strip()
        if not doi or not reason:
            skipped += 1
            continue
        disp = REASON_TO_DISPOSITION.get(reason)
        if not disp:
            print(f"WARN: unknown reason '{reason}' for {doi}, skipping", file=sys.stderr)
            skipped += 1
            continue
        existing[doi] = {
            "reason": reason,
            "disposition": disp,
            "applied_at": today,
            "duplicate_of": r.get("duplicate_of") or None,
        }
        applied += 1

    OUT.write_text(json.dumps(existing, indent=2, ensure_ascii=False, sort_keys=True))
    print(f"Wrote {OUT}  (+{applied} applied, {skipped} skipped, {len(existing)} total)")


if __name__ == "__main__":
    main()

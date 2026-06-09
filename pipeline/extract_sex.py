#!/usr/bin/env python3
"""
Extract sex of animals used in each study from PDFs.

Searches the methods section (or full text if methods can't be isolated)
for mentions of male/female animals and classifies each study.

Usage:
    # Single directory
    uv run python extract_sex.py --pdf-dir ./pdfs --output sex_representation.csv

    # Multiple directories
    uv run python extract_sex.py --pdf-dir ./pdfs ./pdfs_new --output sex_all.csv

    # Merge with existing results (skips already-classified studies)
    uv run python extract_sex.py --pdf-dir ./pdfs_new --output sex_representation.csv --merge results/sex_representation.csv
"""

import argparse
import csv
import re
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from PDF using PyMuPDF or pdftotext."""
    if fitz:
        doc = fitz.open(str(pdf_path))
        text = "\n".join(page.get_text() for page in doc)  # type: ignore[arg-type]
        doc.close()
        return text
    else:
        import subprocess
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return result.stdout
        raise RuntimeError(f"pdftotext failed for {pdf_path}: {result.stderr}")


def strip_references(text: str) -> str:
    """Remove only the citation list itself, not the entire tail of the paper.

    Many journals (Cell Press, iScience, eLife) use STAR Methods which places
    the Methods section AFTER References — so naively cutting at the first
    'References' heading would discard the actual subjects/animals block.
    Strategy: find the References heading, then skip until the next markdown
    heading (likely STAR Methods, Supplementary, etc.) and resume from there.
    """
    m = re.search(
        r'(?im)^\s*#{0,6}\s*(references|bibliography|literature\s+cited)\s*$',
        text,
    )
    if not m:
        return text
    after_refs = text[m.end():]
    # Find the next markdown heading after References
    nxt = re.search(r'(?m)^\s*#{1,6}\s+\S', after_refs)
    if nxt:
        # Keep the prefix (before References) + the body after References list
        return text[:m.start()] + "\n" + after_refs[nxt.start():]
    # No subsequent heading — references run to end of file; safe to cut
    return text[:m.start()]


def isolate_methods(text: str) -> str:
    """Best-effort body for sex extraction: full text minus the citation list.

    The previous header-aware approach was brittle (header detection in
    docling.md is inconsistent, and lookaheads close at incidental cross-
    references). The strict subject-context patterns (`male <strain>`,
    `male mice/rats`, etc.) very rarely false-positive outside cited titles,
    so a full-text scan with only the citation list dropped is more reliable.
    """
    return strip_references(text)


def classify_sex(text: str) -> tuple[str, str]:
    """
    Classify sex of animals used.
    Returns (classification, evidence_snippet).
    """
    methods = isolate_methods(text)
    search_text = methods.lower()

    # Patterns for both sexes
    both_patterns = [
        r'\bmale\s+and\s+female\b',
        r'\bfemale\s+and\s+male\b',
        r'\bboth\s+sex(?:es)?\b',
        r'\bmales?\s+and\s+females?\b',
        r'\bfemales?\s+and\s+males?\b',
        # "14 male and 7 female mice" / "n=8 male and n=8 female rats"
        r'\b\d+\s+males?\s+and\s+\d+\s+females?\b',
        r'\b\d+\s+females?\s+and\s+\d+\s+males?\b',
        r'\bn\s*=\s*\d+\s+males?\s+and\s+n?\s*=?\s*\d+\s+females?\b',
        r'\bmale\s*[(/]\s*female\b',
        r'\bfemale\s*[(/]\s*male\b',
        r'\b(?:♂|♀)\s*(?:and|&|/)\s*(?:♂|♀)\b',
        r'\bsex\s+(?:as\s+a\s+)?(?:factor|variable|covariate)\b',
        r'\beach\s+sex\b',
        r'\bboth\s+genders?\b',
    ]

    # Patterns for male only (in context of subjects, not stimulus animals)
    male_patterns = [
        r'\bmale\s+(?:c57|wistar|sprague|long|swiss|balb|cd-?1|icr|nmri)',
        r'\bmale\s+(?:mice|rats|mouse|rat)\b',
        r'\badult\s+male\b',
        # Inverted phrasing: "mouse males", "rat males"
        r'\b(?:mouse|rat|mice|rats)\s+males?\b',
    ]

    female_patterns = [
        r'\bfemale\s+(?:c57|wistar|sprague|long|swiss|balb|cd-?1|icr|nmri)',
        r'\bfemale\s+(?:mice|rats|mouse|rat)\b',
        r'\badult\s+female\b',
        r'\b(?:mouse|rat|mice|rats)\s+females?\b',
    ]

    # Check both sexes first (takes priority)
    for pat in both_patterns:
        m = re.search(pat, search_text)
        if m:
            start = max(0, m.start() - 80)
            end = min(len(methods), m.end() + 80)
            evidence = methods[start:end].replace('\n', ' ').strip()
            return "both sexes", evidence[:200]

    has_male = False
    has_female = False
    male_evidence = ""
    female_evidence = ""

    for pat in male_patterns:
        m = re.search(pat, search_text)
        if m:
            has_male = True
            start = max(0, m.start() - 40)
            end = min(len(methods), m.end() + 40)
            male_evidence = methods[start:end].replace('\n', ' ').strip()[:200]
            break

    for pat in female_patterns:
        m = re.search(pat, search_text)
        if m:
            has_female = True
            start = max(0, m.start() - 40)
            end = min(len(methods), m.end() + 40)
            female_evidence = methods[start:end].replace('\n', ' ').strip()[:200]
            break

    if has_male and has_female:
        return "both sexes", f"M: {male_evidence} | F: {female_evidence}"
    elif has_male:
        return "male only", male_evidence
    elif has_female:
        return "female only", female_evidence
    else:
        # Broader search on full text
        if re.search(r'\bmale\b', search_text) and re.search(r'\bfemale\b', search_text):
            return "both sexes", "(broad match: both 'male' and 'female' found in text)"
        elif re.search(r'\bmale\b', search_text):
            return "male only", "(broad match: 'male' found in text)"
        elif re.search(r'\bfemale\b', search_text):
            return "female only", "(broad match: 'female' found in text)"
        return "not reported", ""


def study_id_from_filename(filename: str) -> str:
    """Convert filename to study ID (e.g., 'hesselgrave2021.pdf' -> 'hesselgrave2021')."""
    return Path(filename).stem


def main():
    parser = argparse.ArgumentParser(description="Extract sex of animals from study PDFs")
    parser.add_argument("--pdf-dir", type=Path, nargs="+", required=True,
                        help="One or more directories containing PDFs")
    parser.add_argument("--output", type=Path, required=True,
                        help="Output CSV path")
    parser.add_argument("--merge", type=Path, default=None,
                        help="Existing CSV to merge with (skips already-classified studies)")
    args = parser.parse_args()

    # Load existing results if merging
    existing = {}
    if args.merge and args.merge.exists():
        with open(args.merge) as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing[row["study_id"]] = row
        print(f"Loaded {len(existing)} existing classifications from {args.merge}")

    # Collect PDFs
    pdfs = []
    for d in args.pdf_dir:
        pdfs.extend(sorted(d.glob("*.pdf")))
    print(f"Found {len(pdfs)} PDFs across {len(args.pdf_dir)} directories")

    # Process
    results = dict(existing)  # start with existing
    new_count = 0
    for pdf_path in pdfs:
        study_id = study_id_from_filename(pdf_path.name)
        if study_id in results:
            continue

        try:
            text = extract_text_from_pdf(pdf_path)
            classification, evidence = classify_sex(text)
            results[study_id] = {
                "study_id": study_id,
                "sex_classification": classification,
                "evidence": evidence,
            }
            new_count += 1
            print(f"  {study_id}: {classification}")
        except Exception as e:
            print(f"  {study_id}: ERROR — {e}")
            results[study_id] = {
                "study_id": study_id,
                "sex_classification": "error",
                "evidence": str(e)[:200],
            }
            new_count += 1

    # Write output
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(results.values(), key=lambda r: r["study_id"])
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["study_id", "sex_classification", "evidence"])
        writer.writeheader()
        writer.writerows(rows)

    # Summary
    from collections import Counter
    counts = Counter(r["sex_classification"] for r in rows)
    print(f"\nOutput: {args.output} ({len(rows)} studies, {new_count} new)")
    for k, v in counts.most_common():
        print(f"  {k}: {v} ({100*v/len(rows):.1f}%)")


if __name__ == "__main__":
    main()

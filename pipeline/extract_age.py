"""Extract animal age from each study's PDF.

Mirrors extract_sex.py: regex over PDF text, output CSV at
results/age_all.csv with one row per study. Captures both the narrow
numeric form ("8–12 weeks old", "PND 60") and the loose qualitative form
("adult", "young adult") and folds them into a coarse age band.

Output columns: study_id, age_band, age_min_days, age_max_days, evidence

Bands (in priority order of detection):
    juvenile     ≤ 28 days
    adolescent   29–56 days
    young_adult  57–84 days  (8–12 weeks)
    adult        85–365 days
    aged         > 365 days
    mixed        explicit mention of >1 band (e.g. young+aged comparison)
    not_reported nothing detected

Usage:
    uv run python extract_age.py --pdf-dir ./pdfs --output results/age_all.csv
    uv run python extract_age.py --pdf-dir ./pdfs ./pdfs_new --output results/age_all.csv
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


# ---------------------------------------------------------------------------
# Text loading (matches extract_sex.py's behaviour)
# ---------------------------------------------------------------------------

def extract_text_from_pdf(pdf_path: Path) -> str:
    if fitz:
        doc = fitz.open(str(pdf_path))
        text = "\n".join(page.get_text() for page in doc)  # type: ignore[arg-type]
        doc.close()
        return text
    import subprocess
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return result.stdout
    raise RuntimeError(f"pdftotext failed for {pdf_path}: {result.stderr}")


def strip_references(text: str) -> str:
    m = re.search(
        r'(?im)^\s*#{0,6}\s*(references|bibliography|literature\s+cited)\s*$',
        text,
    )
    if not m:
        return text
    after = text[m.end():]
    nxt = re.search(r'(?m)^\s*#{1,6}\s+\S', after)
    if nxt:
        return text[:m.start()] + "\n" + after[nxt.start():]
    return text[:m.start()]


# ---------------------------------------------------------------------------
# Age extraction
# ---------------------------------------------------------------------------

# Numeric patterns. Each yields (min_days, max_days). Months → 30.4 days,
# weeks → 7 days. Stay conservative — only match when an animal-context word
# is nearby (mice/rats/animals/subjects/postnatal/PND).
ANIMAL_CTX = r'(?:mice|mouse|rats?|animals|subjects|pups?|postnatal|PND|P\d+|age|aged|old)'

NUMERIC_PATTERNS: list[tuple[re.Pattern, callable]] = [
    # "aged 8 weeks", "aged 8-12 weeks", "aged 6 months", "aged 60 days"
    (re.compile(r'(?i)\baged?\s+(\d{1,3})\s*(?:[-–to]+\s*(\d{1,3})\s*)?(weeks?|wks?|w|months?|mo|days?|d)\b'),
     lambda m: _from_unit(m, m.group(3))),
    # "at X weeks of age", "at PND 60", "at 8-12 weeks of age"
    (re.compile(r'(?i)\bat\s+(\d{1,3})\s*(?:[-–to]+\s*(\d{1,3})\s*)?(weeks?|wks?|w|months?|mo|days?|d)\s+(?:of\s+age|old|-old)?'),
     lambda m: _from_unit(m, m.group(3))),
    # "8-12 weeks old" / "8 to 12 weeks of age" / "8–12 wk-old"
    (re.compile(r'(?i)\b(\d{1,3})\s*(?:[-–to]+)\s*(\d{1,3})\s*(weeks?|wks?|w|months?|mo|days?|d)\s*[-]?\s*(?:old|of\s+age|-old)'),
     lambda m: _from_unit(m, m.group(3))),
    # "X-week-old", "X week-old", "X-month-old", "X-day-old"
    (re.compile(r'(?i)\b(\d{1,3})[\s-]+(week|wk|month|day)[\s-]*old\b'),
     lambda m: _from_unit_single(int(m.group(1)), m.group(2))),
    # "X weeks old", "X wk of age", "X months of age", "X days old"
    (re.compile(r'(?i)\b(\d{1,3})\s*(weeks?|wks?|w|months?|mo|days?|d)\s+(?:old|of\s+age|-old)'),
     lambda m: _from_unit_single(int(m.group(1)), m.group(2))),
    # PND/postnatal day with range
    (re.compile(r'(?i)\b(?:PND|P|postnatal\s+day)\s*(\d{1,3})\s*[-–to]+\s*(\d{1,3})\b'),
     lambda m: (int(m.group(1)), int(m.group(2)))),
    # PND/postnatal day single
    (re.compile(r'(?i)\b(?:PND|postnatal\s+day)\s*(\d{1,3})\b'),
     lambda m: (int(m.group(1)),) * 2),
    # "P60", "P21" — only with animal/postnatal context within ~80 chars
    (re.compile(rf'\bP(\d{{2,3}})\b(?=[\s\S]{{0,80}}{ANIMAL_CTX})', re.I),
     lambda m: (int(m.group(1)),) * 2),
    # "X-day-old", "X day-old", "60 days of age"
    (re.compile(r'(?i)\b(\d{1,3})\s*days?\s+(?:old|of\s+age|-old)'),
     lambda m: (int(m.group(1)),) * 2),
]


def _unit_days(unit: str) -> int | None:
    """Convert a unit string ('weeks', 'wk', 'months', 'd', ...) to days each."""
    u = unit.lower().rstrip("s")
    if u in ("week", "wk", "w"):
        return 7
    if u in ("month", "mo"):
        return 30  # rounded; close enough for binning
    if u in ("day", "d"):
        return 1
    return None


def _from_unit(m: re.Match, unit: str) -> tuple[int, int]:
    """Range form: m.group(1) lo, optional m.group(2) hi, unit string."""
    factor = _unit_days(unit) or 0
    lo = int(m.group(1)) * factor
    hi = int(m.group(2) or m.group(1)) * factor
    return (lo, hi)


def _from_unit_single(value: int, unit: str) -> tuple[int, int]:
    factor = _unit_days(unit) or 0
    d = value * factor
    return (d, d)

# Qualitative cues
QUAL_PATTERNS = [
    (re.compile(rf'(?i)\bjuvenile\s+{ANIMAL_CTX}'), "juvenile"),
    (re.compile(rf'(?i)\b(?:adolescent|peri[- ]?adolescent)\s+{ANIMAL_CTX}'), "adolescent"),
    (re.compile(rf'(?i)\byoung[- ]adult\s+{ANIMAL_CTX}'), "young_adult"),
    (re.compile(rf'(?i)\baged\s+{ANIMAL_CTX}'), "aged"),
    (re.compile(rf'(?i)\bold\s+{ANIMAL_CTX}'), "aged"),
    (re.compile(rf'(?i)\bsenescent\s+{ANIMAL_CTX}'), "aged"),
    (re.compile(rf'(?i)\badult\s+{ANIMAL_CTX}'), "adult"),
]


def band_for_days(d_min: int, d_max: int) -> str:
    """Map a day range to the band the upper bound falls in."""
    d = d_max
    if d <= 28:
        return "juvenile"
    if d <= 56:
        return "adolescent"
    if d <= 84:
        return "young_adult"
    if d <= 365:
        return "adult"
    return "aged"


def classify_age(text: str) -> tuple[str, str, str, str]:
    """Return (band, age_min_days, age_max_days, evidence_snippet).

    age_min_days and age_max_days are strings (empty when qualitative-only).
    """
    body = strip_references(text)

    numeric_hits: list[tuple[int, int, str]] = []
    for pat, conv in NUMERIC_PATTERNS:
        for m in pat.finditer(body):
            try:
                rng = conv(m)
            except (ValueError, IndexError):
                continue
            lo, hi = rng if len(rng) == 2 else (rng[0], rng[0])
            if lo > hi:
                lo, hi = hi, lo
            if lo < 1 or hi > 1500:  # sanity
                continue
            start = max(0, m.start() - 40)
            end = min(len(body), m.end() + 40)
            snippet = body[start:end].replace("\n", " ").strip()[:200]
            numeric_hits.append((lo, hi, snippet))

    if numeric_hits:
        # If the bands of the hits span >1 band, call it mixed.
        bands = {band_for_days(lo, hi) for lo, hi, _ in numeric_hits}
        # Use the first hit's range as the representative one.
        lo, hi, snippet = numeric_hits[0]
        if len(bands) > 1 and ("aged" in bands and ("juvenile" in bands or "adolescent" in bands or "young_adult" in bands or "adult" in bands)):
            return "mixed", str(lo), str(hi), snippet
        return band_for_days(lo, hi), str(lo), str(hi), snippet

    # Qualitative fallback
    for pat, band in QUAL_PATTERNS:
        m = pat.search(body)
        if m:
            start = max(0, m.start() - 40)
            end = min(len(body), m.end() + 40)
            snippet = body[start:end].replace("\n", " ").strip()[:200]
            return band, "", "", f"qualitative: {snippet}"

    return "not_reported", "", "", ""


def study_id_from_filename(filename: str) -> str:
    return Path(filename).stem


def main():
    ap = argparse.ArgumentParser(description="Extract animal age from study PDFs")
    ap.add_argument("--pdf-dir", type=Path, nargs="+", required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--merge", type=Path, default=None,
                    help="Existing CSV to merge with (skips already-classified studies)")
    args = ap.parse_args()

    existing: dict[str, dict] = {}
    if args.merge and args.merge.exists():
        with args.merge.open() as fh:
            for row in csv.DictReader(fh):
                existing[row["study_id"]] = row
        print(f"Loaded {len(existing)} existing rows from {args.merge}")

    pdfs: list[Path] = []
    for d in args.pdf_dir:
        pdfs.extend(sorted(d.glob("*.pdf")))
    print(f"Found {len(pdfs)} PDFs across {len(args.pdf_dir)} dir(s)")

    results = dict(existing)
    new = 0
    for pdf in pdfs:
        sid = study_id_from_filename(pdf.name)
        if sid in results:
            continue
        try:
            text = extract_text_from_pdf(pdf)
            band, lo, hi, evidence = classify_age(text)
            results[sid] = {
                "study_id": sid,
                "age_band": band,
                "age_min_days": lo,
                "age_max_days": hi,
                "evidence": evidence,
            }
            new += 1
            print(f"  {sid}: {band} [{lo}-{hi}]")
        except Exception as e:
            results[sid] = {
                "study_id": sid,
                "age_band": "error",
                "age_min_days": "",
                "age_max_days": "",
                "evidence": str(e)[:200],
            }
            new += 1
            print(f"  {sid}: ERROR — {e}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(results.values(), key=lambda r: r["study_id"])
    with args.output.open("w", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=["study_id", "age_band", "age_min_days", "age_max_days", "evidence"],
        )
        w.writeheader()
        w.writerows(rows)

    counts = Counter(r["age_band"] for r in rows)
    print(f"\nOutput: {args.output} ({len(rows)} studies, {new} new)")
    for k, v in counts.most_common():
        print(f"  {k}: {v} ({100*v/len(rows):.1f}%)")


if __name__ == "__main__":
    main()

"""Cross-check the 177 pdf_unavailable_relevant papers against on-disk PDFs.

The PRISMA accounting deduplicates by DOI, but ~34 papers were manually added to
the corpus without DOIs (only a stem like 'gregorio2021'). When the same paper
shows up in the PubMed search with its full author surname ('deGregorio2021'),
the dedupe misses it. This script finds those collisions by normalising the
first-author surname (stripping de/van/von/le prefixes) and year-matching.

Run as a script for a console report; import `find_duplicates(missing_rows)` for
use from `build_papers_to_download.py`.
"""
from __future__ import annotations
import csv
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).parent
ACC = ROOT / "prisma_accounting.csv"
PDF_DIRS = [ROOT / "pdfs", ROOT / "pdfs_new"]

PREFIXES = ("della", "der", "den", "dos", "del", "van", "von", "vom", "ten", "ter",
            "los", "lo", "la", "le", "di", "do", "du", "te", "de")


def normalise(s: str) -> str:
    """Strip diacritics, lowercase, drop non-alpha, drop common nobiliary prefixes."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z]", "", s).lower()
    for p in PREFIXES:  # already longest-first
        if s.startswith(p) and len(s) > len(p) + 2:
            return s[len(p):]
    return s


def stem_to_key(stem: str) -> tuple[str, str]:
    """Split a stem like 'degregorio2021' or 'pedzich20221' into (norm_surname, year)."""
    m = re.match(r"^(.*?)(\d{4})\d*$", stem.strip().lower())
    if not m:
        return (normalise(stem), "")
    name, year = m.groups()
    return (normalise(name), year)


def first_author_surname(authors: str) -> str:
    """Pull the first author's surname from an 'authors' field like 'deGregorio S et al.'

    Strips trailing initial sequences of 1-6 caps with optional dots, so 'BJB',
    'LAMS', 'JVBP' are recognised the same way 'AL' is.
    """
    s = authors.split(",")[0].split(";")[0].strip()
    s = re.sub(r"\bet al\.?$", "", s, flags=re.I).strip()
    parts = s.split()
    while parts and re.fullmatch(r"[A-Z](?:\.?[A-Z]){0,5}\.?", parts[-1]):
        parts.pop()
    return " ".join(parts) if parts else s


def list_on_disk_stems() -> list[str]:
    stems: list[str] = []
    for d in PDF_DIRS:
        if d.exists():
            stems.extend(p.stem for p in d.glob("*.pdf"))
    return stems


def find_duplicates(missing_rows: list[dict]) -> dict[str, list[tuple[str, str]]]:
    """Return {missing_stem: [(on_disk_stem, match_type), ...]}."""
    on_disk_stems = list_on_disk_stems()
    on_disk_index: dict[tuple[str, str], list[str]] = {}
    for stem in on_disk_stems:
        on_disk_index.setdefault(stem_to_key(stem), []).append(stem)

    out: dict[str, list[tuple[str, str]]] = {}
    for r in missing_rows:
        norm_surname = normalise(first_author_surname(r["authors"]))
        year = r["year"]

        candidates: list[tuple[str, str]] = []
        candidates += [(s, "exact") for s in on_disk_index.get((norm_surname, year), [])]
        for dy in (-1, 1):
            if year and year.isdigit():
                y2 = str(int(year) + dy)
                candidates += [(s, "year±1") for s in on_disk_index.get((norm_surname, y2), [])]
        for (n, y), stems in on_disk_index.items():
            if y == year and n != norm_surname \
                    and (n.startswith(norm_surname) or norm_surname.startswith(n)) \
                    and min(len(n), len(norm_surname)) >= 5:
                candidates += [(s, "prefix") for s in stems]

        seen, uniq = set(), []
        for s, why in candidates:
            if s not in seen:
                seen.add(s); uniq.append((s, why))
        if uniq:
            out[r["stem"]] = uniq
    return out


def main() -> None:
    rows = list(csv.DictReader(open(ACC)))
    missing = [r for r in rows if r["disposition"] == "pdf_unavailable_relevant"]
    on_disk_stems = list_on_disk_stems()
    dups = find_duplicates(missing)
    by_stem = {r["stem"]: r for r in missing}

    print(f"\nScanned {len(missing)} missing-PDF papers against {len(on_disk_stems)} on-disk PDFs.")
    print(f"Found {len(dups)} potential duplicates.\n")
    print(f"{'missing_stem':30s} | {'on-disk match':25s} | {'why':10s} | year | first-author / DOI")
    print("-" * 130)
    for stem, matches in dups.items():
        r = by_stem[stem]
        for s, why in matches:
            print(f"{stem:30s} | {s:25s} | {why:10s} | {r['year']:4s} | {r['authors'][:35]:35s} | {r['doi']}")

    out = ROOT / "pdf_duplicates.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["missing_stem", "missing_doi", "year", "authors", "title", "on_disk_stem", "match_type"])
        for stem, matches in dups.items():
            r = by_stem[stem]
            for s, why in matches:
                w.writerow([stem, r["doi"], r["year"], r["authors"], r["title"][:80], s, why])
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()

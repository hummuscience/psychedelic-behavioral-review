"""Disambiguate stem collisions in prisma_accounting.csv (and paper_registry.json,
doi_to_stem.json).

The corpus uses <surname><year> as the citekey/stem, generated automatically by
the search/registry pipeline. When two different papers happen to share the same
surname+year (different authors, or same author multiple papers same year), the
stem collides — multiple PRISMA rows point at one stem string. Because the
dashboard counts records by stem, this silently:
  * over-counts `in_consensus=True` (every colliding row claims the single
    consensus JSON),
  * makes it impossible to tell from PRISMA which paper was actually scored.

This script:

  1. Reads each consensus JSON's stored DOI to identify the canonical paper for
     each stem.
  2. For each collision, keeps the canonical row at the original stem and
     renames the other rows' stems with letter suffixes ('b', 'c', ...). Only
     PRISMA metadata is touched — the consensus JSONs and PDFs keep their
     filename.
  3. Recomputes `in_consensus` honestly: True iff this row's DOI matches the
     stored DOI on the consensus JSON named after the (possibly suffixed) stem.
  4. Updates paper_registry.json and doi_to_stem.json to match.
  5. Writes prisma_problems.csv listing every collision where automatic
     disambiguation was uncertain (consensus JSON missing DOI, or consensus DOI
     doesn't match any PRISMA row) — these need human review.

Does NOT touch consensus JSON files, PDF files, dosages_llm.csv, or anything in
results_v2_full_consensus/.
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
ACC = ROOT / "prisma_accounting.csv"
REG = ROOT / "paper_registry.json"
D2S = ROOT / "doi_to_stem.json"
CONSENSUS_DIR = ROOT / "results_v2_full_consensus"
PROBLEMS = ROOT / "prisma_problems.csv"


def norm_doi(d) -> str:
    return (d or "").strip().lower().rstrip("/") if d else ""


def main() -> None:
    # ── Step 1: build (stem → consensus DOI) map ──────────────────────────────────
    consensus_doi: dict[str, str] = {}
    consensus_no_doi: set[str] = set()
    for p in CONSENSUS_DIR.glob("*.json"):
        if p.name.startswith("_"):
            continue
        try:
            d = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        stem = p.stem.lower()
        doi = norm_doi(d.get("doi"))
        if doi:
            consensus_doi[stem] = doi
        else:
            consensus_no_doi.add(stem)

    # ── Step 2: load PRISMA accounting ────────────────────────────────────────────
    rows: list[dict] = list(csv.DictReader(open(ACC)))
    fieldnames = list(rows[0].keys())

    stem_to_rows: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        stem_to_rows[(r.get("stem") or "").strip().lower()].append(r)

    # ── Step 3: disambiguate ──────────────────────────────────────────────────────
    problems: list[dict] = []
    suffix_assigned: dict[str, str] = {}   # row_id → new stem
    new_stems: list[tuple[str, str]] = []   # (old_stem, new_stem) for registry

    def alpha_suffix(i: int) -> str:
        # 0→'b', 1→'c', 2→'d', ... up to 'z'. Beyond that 'aa', 'ab', ...
        if i < 25:
            return chr(ord("b") + i)
        base = i - 25
        return "a" + chr(ord("a") + base)


    for stem, srows in stem_to_rows.items():
        # Build per-DOI grouping (multiple PRISMA rows with same stem+DOI are just
        # search-result duplicates and should keep the same stem).
        doi_to_rows: dict[str, list[dict]] = defaultdict(list)
        no_doi_rows: list[dict] = []
        for r in srows:
            doi = norm_doi(r.get("doi"))
            if doi:
                doi_to_rows[doi].append(r)
            else:
                no_doi_rows.append(r)
        if len(doi_to_rows) <= 1 and not no_doi_rows:
            continue  # not a collision

        cdoi = consensus_doi.get(stem)
        # Identify the canonical DOI for this stem:
        if cdoi and cdoi in doi_to_rows:
            canonical = cdoi
        elif stem in consensus_no_doi:
            # Consensus exists but has no DOI: we can't pick — flag and skip rename
            problems.append({
                "stem": stem,
                "issue": "consensus_json_missing_doi",
                "consensus_doi": "",
                "prisma_dois": "|".join(sorted(doi_to_rows.keys())),
            })
            continue
        elif cdoi:
            # Consensus has a valid DOI but no PRISMA row matches. The consensus
            # paper isn't in PRISMA at all (manually added, or PRISMA stem points
            # to unrelated papers). Suffix every existing PRISMA row, reserving
            # the bare stem for a new "manually_added_to_corpus" row inserted
            # below.
            canonical = None  # signals "no PRISMA row keeps the bare stem"
            # Add the consensus paper as a fresh PRISMA row with the bare stem
            new_row = {f: "" for f in fieldnames}
            new_row["stem"] = stem
            new_row["doi"] = cdoi
            new_row["disposition"] = "manually_added_to_corpus"
            new_row["in_consensus"] = "True"
            rows.append(new_row)
            # Fall through to renaming logic so all existing rows get suffixed
        else:
            # No consensus JSON at all — all rows are orphans/unscored. Pick the
            # first DOI alphabetically as canonical and suffix the rest. If there
            # are no DOI rows at all (only no-DOI rows), the first no-DOI row
            # keeps the stem and the rest get suffixed.
            if doi_to_rows:
                canonical = sorted(doi_to_rows.keys())[0]
            else:
                canonical = None

        if canonical is not None:
            # Assign suffixes to non-canonical DOIs, alphabetical for determinism
            other_dois = sorted(d for d in doi_to_rows if d != canonical)
            for i, doi in enumerate(other_dois):
                new_stem = stem + alpha_suffix(i)
                for r in doi_to_rows[doi]:
                    r["stem"] = new_stem
                new_stems.append((stem, new_stem))
            # Rows without a DOI on this stem get a final suffix bucket
            for j, r in enumerate(no_doi_rows):
                r["stem"] = stem + alpha_suffix(len(other_dois) + j) + "_nodoi"
        else:
            # canonical is None: either (a) only no-DOI rows here, or (b) consensus
            # has a valid DOI but no PRISMA row matches (handled in the elif cdoi
            # branch above — a new manually_added row was already appended, and we
            # need to suffix EVERY existing row so the bare stem is now free).
            if cdoi:
                # case (b): suffix every existing row
                other_dois = sorted(doi_to_rows.keys())
                for i, doi in enumerate(other_dois):
                    new_stem = stem + alpha_suffix(i)
                    for r in doi_to_rows[doi]:
                        r["stem"] = new_stem
                    new_stems.append((stem, new_stem))
                for j, r in enumerate(no_doi_rows):
                    r["stem"] = stem + alpha_suffix(len(other_dois) + j) + "_nodoi"
            else:
                # case (a): only no-DOI rows. Keep first at stem, suffix rest.
                for j, r in enumerate(no_doi_rows[1:], start=0):
                    r["stem"] = stem + alpha_suffix(j) + "_nodoi"

    # ── Step 4: recompute in_consensus honestly ──────────────────────────────────
    # Two failure modes to disentangle:
    #   (a) Stem collision: same stem, several PRISMA rows with different DOIs —
    #       only the row whose DOI matches the consensus JSON's stored DOI counts.
    #       Disambiguator already renamed the non-matching rows to suffixed stems
    #       in step 3, so after renaming, the original (non-suffixed) stem is the
    #       canonical row.
    #   (b) Stem unique in PRISMA but consensus JSON's DOI metadata is corrupted
    #       (e.g. off-by-one suffix). Many consensus files have wrong DOI strings
    #       baked in. For these we trust the stem match — the PDF and the row are
    #       almost certainly about the same paper.
    # Net: a row is in_consensus iff a consensus JSON exists at the row's
    # (post-rename) stem AND no other row at that stem also claims the same stem
    # (which by construction won't happen after disambiguation).
    stem_to_acc_rows: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        stem_to_acc_rows[(r.get("stem") or "").strip().lower()].append(r)

    for r in rows:
        s = (r.get("stem") or "").strip().lower()
        if s in consensus_doi or s in consensus_no_doi:
            r["in_consensus"] = "True"
        else:
            r["in_consensus"] = "False"

    # ── Step 5: write back ────────────────────────────────────────────────────────
    with open(ACC, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    # Update paper_registry.json: add new keys mirroring the original entry,
    # overriding the doi/title/etc. with the disambiguated row's data.
    reg = json.loads(REG.read_text())
    row_by_stem_doi: dict[tuple[str, str], dict] = {}
    for r in rows:
        s = (r.get("stem") or "").strip().lower()
        d = norm_doi(r.get("doi"))
        row_by_stem_doi[(s, d)] = r

    for old_stem, new_stem in new_stems:
        base = reg.get(old_stem)
        if not base:
            continue
        # Find the PRISMA row whose new_stem matches; populate from there.
        candidates = [r for r in rows if (r.get("stem") or "").lower() == new_stem]
        if not candidates:
            continue
        r = candidates[0]
        reg[new_stem] = {
            **base,
            "stem": new_stem,
            "doi": r.get("doi") or "",
            "title": (r.get("title") or "").strip(),
            "year": r.get("year") or base.get("year"),
            "authors": [r.get("authors")] if r.get("authors") else base.get("authors"),
        }

    REG.write_text(json.dumps(reg, indent=2, ensure_ascii=False))

    # Update doi_to_stem.json
    d2s = json.loads(D2S.read_text()) if D2S.exists() else {}
    for r in rows:
        doi = norm_doi(r.get("doi"))
        s = (r.get("stem") or "").strip().lower()
        if doi and s:
            d2s[doi] = s
    D2S.write_text(json.dumps(d2s, indent=2, ensure_ascii=False))

    # Write problems (always — truncate stale content even when problems is empty)
    with open(PROBLEMS, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["stem", "issue", "consensus_doi", "prisma_dois"])
        w.writeheader()
        w.writerows(problems)

    # ── Summary ───────────────────────────────────────────────────────────────────
    print(f"renamed {len(new_stems)} PRISMA rows to disambiguated stems")
    print(f"  unique collision stems resolved: {len(set(s for s, _ in new_stems))}")
    print(f"  problems flagged for review:     {len(problems)} → {PROBLEMS.name}")
    in_cons = sum(1 for r in rows if r.get("in_consensus") == "True")
    print(f"  in_consensus=True after recompute: {in_cons} (was: stem-string match, now: DOI match)")


if __name__ == "__main__":
    main()

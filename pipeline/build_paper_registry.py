"""Build paper_registry.json — DOI-keyed metadata for the corpus.

Single source of truth: the user's local Zotero library, queried via
http://localhost:23119/api/users/2283090/...  (no auth needed for local).

We DON'T import from citations.bib — it's stale.

This script fetches all journal-article items + their PDF attachments from
Zotero in one batch, then maps each PDF in pdfs/ to its DOI by joining
on the attachment filename. The resulting registry is durable: subsequent
build steps (PRISMA accounting, download tracker, etc.) read paper_registry.json
without ever needing Zotero running again.

Outputs:
- paper_registry.json   — keyed by NFC-normalised pdfs/<stem>; canonical DOI inside
- doi_to_stem.json      — DOI → on-disk stem (lowercase DOI)
- registry_unmatched.txt — PDFs without a Zotero match (need manual fixup)
- registry_summary.txt  — counts per source / coverage
"""
from __future__ import annotations
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path
import urllib.request

ROOT = Path(__file__).parent
PDFS_DIR = ROOT / "pdfs"
PUBMED_CSV = ROOT / "results" / "pubmed_expansion.csv"
ZOTERO_USER_ID = 2283090
ZOTERO_BASE = f"http://localhost:23119/api/users/{ZOTERO_USER_ID}"

# Manual overrides for stems that auto-matching can't resolve.
# Use when: (a) the user named a PDF after a non-first author, or
# (b) the paper is in neither Zotero nor pubmed_expansion.
# Either provide a Zotero key (preferred — pulls full metadata) OR a DOI.
STEM_OVERRIDES: dict[str, dict] = {
    # delafuenterevenga2022 is actually Jaster AM et al. 2022 (de la Fuente
    # Revenga is the 4th author). User filed it under the recognisable surname.
    "delafuenterevenga2022": {"zotero_key": "6D6AKGBW", "doi": "10.1016/j.neulet.2022.136836"},
    # kimmey2022 — Kimmey BA et al. 2022, "The serotonin 2A receptor agonist
    # TCB-2 attenuates heavy alcohol drinking..." Not currently in Zotero.
    "kimmey2022": {"doi": "10.1111/adb.13147",
                   "title": "The serotonin 2A receptor agonist TCB-2 attenuates heavy alcohol drinking and alcohol-induced midbrain inhibitory plasticity",
                   "year": "2022",
                   "authors": "Kimmey BA et al.",
                   "journal": "Addiction Biology"},
    # These two are matched by filename to a Zotero entry, but the Zotero
    # entry's DOI field is empty. Patch the DOI without disturbing the rest.
    "higgins2021": {"doi_patch": "10.3389/fphar.2021.640241"},
    "huang2022":   {"doi_patch": "10.3389/fpsyt.2022.891512"},
}

OUT_REGISTRY = ROOT / "paper_registry.json"
OUT_DOI_INDEX = ROOT / "doi_to_stem.json"
OUT_UNMATCHED = ROOT / "registry_unmatched.txt"
OUT_MISSING_DOI = ROOT / "registry_missing_doi.txt"
OUT_SUMMARY = ROOT / "registry_summary.txt"


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def fetch_zotero_items() -> list[dict]:
    """Page through all items in My Library."""
    items = []
    start = 0
    while True:
        url = f"{ZOTERO_BASE}/items?limit=100&start={start}&format=json"
        with urllib.request.urlopen(url, timeout=30) as resp:
            page = json.load(resp)
        if not page:
            break
        items.extend(page)
        if len(page) < 100:
            break
        start += 100
        if start > 30000:  # safety guard
            print("WARNING: paginator passed 30k items, stopping", file=sys.stderr)
            break
    return items


def main():
    if not PDFS_DIR.exists():
        sys.exit(f"missing {PDFS_DIR}")

    pdfs_on_disk = {nfc(p.stem): p for p in PDFS_DIR.glob("*.pdf")}
    print(f"PDFs in pdfs/: {len(pdfs_on_disk)}")

    print(f"Fetching all items from Zotero (My Library)...", end=" ", flush=True)
    items = fetch_zotero_items()
    print(f"{len(items)} items")

    # Index parents (journal articles, books, etc.) by their key
    parents_by_key: dict[str, dict] = {}
    pdf_attachments: list[dict] = []
    for it in items:
        d = it.get("data", {})
        itype = d.get("itemType")
        if itype == "attachment":
            if d.get("contentType") == "application/pdf":
                pdf_attachments.append(d)
        else:
            parents_by_key[d["key"]] = d

    print(f"  parent items:    {len(parents_by_key)}")
    print(f"  PDF attachments: {len(pdf_attachments)}")

    # Build filename → list of parents (some filenames map to multiple Zotero
    # entries when different papers happen to have the same exported filename
    # — e.g., two Zhang 2025 papers both saved as zhang2025.pdf).
    filename_to_parents: dict[str, list[dict]] = {}
    for att in pdf_attachments:
        fname = None
        path = att.get("path", "")
        if path.startswith("attachments:"):
            fname = path[len("attachments:"):]
        elif "filename" in att and att["filename"].lower().endswith(".pdf"):
            fname = att["filename"]
        elif (att.get("title") or "").lower().endswith(".pdf"):
            fname = att["title"]
        if not fname:
            continue
        stem = nfc(Path(fname).stem)
        parent_key = att.get("parentItem")
        if parent_key and parent_key in parents_by_key:
            filename_to_parents.setdefault(stem, []).append(parents_by_key[parent_key])

    n_collisions = sum(1 for ps in filename_to_parents.values() if len(ps) > 1)
    print(f"  PDF stems with parent: {len(filename_to_parents)} "
          f"(of which {n_collisions} multi-parent collisions)")

    # --- Fallback fuzzy index: (asciified first-author surname, year) → [parent_keys]
    from unidecode import unidecode
    def asciify(s: str) -> str:
        # unidecode handles ø→o, ł→l, æ→ae etc. that NFKD alone misses
        return re.sub(r"[^a-z]", "", unidecode(s).lower())

    PREFIXES = ("de", "del", "della", "der", "den", "di", "do", "dos", "du",
                "la", "le", "lo", "los", "van", "von", "vom", "ten", "ter", "te")

    def author_key(parent: dict) -> tuple[str, str] | None:
        creators = parent.get("creators") or []
        first = next((c for c in creators if c.get("creatorType") in ("author", None)), None)
        if not first or not first.get("lastName"):
            return None
        surname = first["lastName"].strip().lower()
        # Iteratively strip nobiliary prefixes ("de la X" → "X", "van der Y" → "Y")
        toks = surname.split()
        while len(toks) > 1 and toks[0] in PREFIXES:
            toks = toks[1:]
        surname_norm = asciify(" ".join(toks))
        date = (parent.get("date") or "").strip()
        m = re.search(r"\b(19|20|21)\d{2}\b", date)
        if not m:
            return None
        return (surname_norm, m.group(0))

    fuzzy_index: dict[tuple[str, str], list[dict]] = {}
    for p in parents_by_key.values():
        k = author_key(p)
        if k:
            fuzzy_index.setdefault(k, []).append(p)

    # DOI → Zotero parent (lowercase keys for matching)
    zotero_by_doi = {}
    for p in parents_by_key.values():
        doi = (p.get("DOI") or "").strip().lower()
        if doi:
            zotero_by_doi[doi] = p

    def stem_to_author_year(stem: str) -> tuple[str, str] | None:
        m = re.match(r"^(.*?)(\d{4})\d*$", stem.lower())
        if not m: return None
        surname_raw, year = m.groups()
        # Drop spaces/hyphens; handle prefixes by trying both stripped & retained
        surname = re.sub(r"[\s\-]", "", surname_raw)
        return (asciify(surname), year)

    # --- pubmed_expansion.csv backfill: stem-key → row (DOI, title, authors, ...)
    # Used for papers that are on disk but not in Zotero. Same fuzzy stem key.
    pubmed_by_key: dict[tuple[str, str], list[dict]] = {}
    if PUBMED_CSV.exists():
        with open(PUBMED_CSV) as f:
            for row in csv.DictReader(f):
                auth_short = (row.get("authors_short") or "").strip()
                if not auth_short or not row.get("year"):
                    continue
                toks = auth_short.split()
                if toks and toks[0].lower() in PREFIXES:
                    first = toks[1] if len(toks) > 1 else toks[0]
                else:
                    first = toks[0]
                key = (asciify(first), row["year"])
                pubmed_by_key.setdefault(key, []).append(row)
    print(f"  pubmed_expansion rows: {sum(len(v) for v in pubmed_by_key.values())} indexed")

    # --- Build registry: one entry per on-disk PDF ---
    registry: dict[str, dict] = {}
    unmatched: list[str] = []
    fuzzy_matched: list[str] = []

    # --- Helpers for disambiguation via docling markdown ---
    DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
    PUNCT_RE = re.compile(r"[^\w\s]")

    def doi_from_markdown(stem: str) -> str | None:
        md = PDFS_DIR / f"{stem}.docling.md"
        if not md.exists():
            return None
        # Just scan the first ~10kb — DOI almost always appears near the top
        try:
            head = md.read_text(errors="ignore")[:15000]
        except Exception:
            return None
        m = DOI_RE.search(head)
        return m.group(0).strip(".,;:)/") if m else None

    def title_tokens(s: str) -> set[str]:
        s = unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode("ascii").lower()
        s = PUNCT_RE.sub(" ", s)
        return {w for w in s.split() if len(w) > 3}

    def collapse_duplicates(candidates: list[dict]) -> list[dict]:
        """If all candidates share the same title (Zotero duplicates), keep just one."""
        titles = {(c.get("title") or "").strip().lower() for c in candidates}
        if len(titles) <= 1:
            return candidates[:1]
        return candidates

    def disambiguate_by_title(stem: str, candidates: list[dict]) -> dict | None:
        """Pick candidate whose title best overlaps with text near top of docling md."""
        candidates = collapse_duplicates(candidates)
        if len(candidates) == 1:
            return candidates[0]
        md = PDFS_DIR / f"{stem}.docling.md"
        if not md.exists():
            return None
        try:
            head = md.read_text(errors="ignore")[:6000]
        except Exception:
            return None
        head_tokens = title_tokens(head)
        best, best_score = None, 0
        for c in candidates:
            cand_title = c.get("title") or c.get("data", {}).get("title", "")
            ct = title_tokens(cand_title)
            if not ct: continue
            score = len(ct & head_tokens)
            if score > best_score and score >= 4:
                best_score = score
                best = c
        return best

    # --- AUTHORITATIVE DOI from consensus output -------------------------
    # The Haiku judge extracts each paper's DOI directly from the PDF text.
    # That trumps any filename-based Zotero match — multiple Zotero entries can
    # have attachments with the same filename, leading to wrong matches.
    consensus_doi_by_stem: dict[str, str] = {}
    consensus_dir = ROOT / "results_full_consensus"
    if consensus_dir.exists():
        for cfile in consensus_dir.glob("*.json"):
            try:
                cd = json.loads(cfile.read_text())
            except Exception:
                continue
            cdoi = (cd.get("doi") or "").strip().lower()
            cdoi = re.sub(r"^https?://(dx\.)?doi\.org/", "", cdoi)
            if cdoi.startswith("10."):
                consensus_doi_by_stem[cfile.stem] = cdoi

    pubmed_backfilled: list[str] = []
    for stem, path in sorted(pdfs_on_disk.items()):
        parent = None
        match_via = None

        # Pass 0: manual stem override — full redirect only (a `doi_patch`-only
        # override is applied later, AFTER Zotero filename match has run).
        ov = STEM_OVERRIDES.get(stem)
        is_doi_patch_only = bool(ov) and set(ov.keys()) <= {"doi_patch"}
        if ov and not is_doi_patch_only:
            if ov.get("zotero_key") and ov["zotero_key"] in parents_by_key:
                parent = parents_by_key[ov["zotero_key"]]
                match_via = "manual_override_zotero"
            else:
                authors_str = ov.get("authors", "")
                parent = {
                    "_source": "manual_override",
                    "key": None,
                    "DOI": ov.get("doi", ""),
                    "title": ov.get("title", ""),
                    "date": ov.get("year", ""),
                    "creators": [{"creatorType": "author", "lastName": authors_str, "firstName": ""}],
                    "publicationTitle": ov.get("journal", ""),
                    "ISSN": "", "volume": "", "pages": "",
                    "url": f"https://doi.org/{ov.get('doi','')}" if ov.get("doi") else "",
                    "itemType": "journalArticle",
                }
                match_via = "manual_override"

        # Pass 0b: consensus DOI (judge-extracted from PDF text) → Zotero entry.
        # When the judge extracted a real DOI and Zotero has it indexed, that
        # match is by definition correct — no risk of filename-collision
        # picking the wrong sibling Zotero record.
        if not parent:
            cdoi = consensus_doi_by_stem.get(stem)
            if cdoi and cdoi in zotero_by_doi:
                parent = zotero_by_doi[cdoi]
                match_via = "consensus_doi_zotero"

        # Pass 1a: filename match in Zotero — when unique, trust it.
        if not parent:
            parents_list = filename_to_parents.get(stem, [])
            if len(parents_list) == 1:
                parent = parents_list[0]
                match_via = "filename"
            elif len(parents_list) > 1:
                # Filename collision — multiple Zotero entries share this
                # exported filename. Use the consensus-extracted DOI as a
                # tiebreaker among the candidates.
                cdoi = consensus_doi_by_stem.get(stem)
                if cdoi:
                    for p in parents_list:
                        if (p.get("DOI") or "").strip().lower() == cdoi:
                            parent = p
                            match_via = "filename_collision_doi_resolved"
                            break
                if not parent:
                    # Fall back to title overlap with the docling md
                    pick = disambiguate_by_title(stem, parents_list)
                    if pick:
                        parent = pick
                        match_via = "filename_collision_title_resolved"

        # Pass 2: fuzzy author-year lookup against Zotero parents
        if not parent:
            ay = stem_to_author_year(stem)
            if ay:
                cands = fuzzy_index.get(ay, [])
                # Iteratively strip nobiliary prefixes from the stem-derived surname
                surname, year = ay
                while not cands:
                    matched = False
                    for prefix in PREFIXES:
                        if surname.startswith(prefix) and len(surname) > len(prefix) + 2:
                            surname = surname[len(prefix):]
                            cands = fuzzy_index.get((surname, year), [])
                            matched = True
                            break
                    if not matched:
                        break
                cands = collapse_duplicates(cands)
                if len(cands) == 1:
                    parent = cands[0]
                    match_via = "fuzzy"
                    fuzzy_matched.append(stem)
                elif len(cands) > 1:
                    pick = disambiguate_by_title(stem, cands)
                    if pick:
                        parent = pick
                        match_via = "fuzzy_title_disambig"
                        fuzzy_matched.append(stem)

        # Pass 3: DOI lookup via pubmed_expansion → Zotero parent
        if not parent:
            ay = stem_to_author_year(stem)
            pm_cands = []
            if ay:
                pm_cands = pubmed_by_key.get(ay, [])
                if not pm_cands:
                    surname, year = ay
                    for prefix in PREFIXES:
                        if surname.startswith(prefix) and len(surname) > len(prefix) + 2:
                            pm_cands = pubmed_by_key.get((surname[len(prefix):], year), [])
                            if pm_cands: break
            # If multiple, disambiguate by title overlap with the docling md
            if len(pm_cands) > 1:
                picked = disambiguate_by_title(stem, pm_cands)
                pm_cands = [picked] if picked else pm_cands
            for pm in pm_cands:
                doi = (pm.get("doi") or "").strip().lower()
                if doi and doi in zotero_by_doi:
                    parent = zotero_by_doi[doi]
                    match_via = "doi_via_pubmed"
                    break

        # Pass 3b: scan the PDF's docling markdown for a DOI string
        if not parent:
            scanned_doi = doi_from_markdown(stem)
            if scanned_doi:
                low = scanned_doi.lower()
                if low in zotero_by_doi:
                    parent = zotero_by_doi[low]
                    match_via = "doi_from_pdf"

        # Pass 4: backfill from pubmed_expansion alone (PDF on disk but NOT in Zotero)
        # We synthesise a registry entry from pubmed metadata so downstream tools
        # have a DOI to key on.
        if not parent:
            ay = stem_to_author_year(stem)
            pm_cands = pubmed_by_key.get(ay, []) if ay else []
            if not pm_cands and ay:
                surname, year = ay
                for prefix in PREFIXES:
                    if surname.startswith(prefix) and len(surname) > len(prefix) + 2:
                        pm_cands = pubmed_by_key.get((surname[len(prefix):], year), [])
                        if pm_cands: break
            # Title-disambiguate when multiple candidates share author+year
            if len(pm_cands) > 1:
                picked = disambiguate_by_title(stem, pm_cands)
                pm_cands = [picked] if picked else pm_cands
            if len(pm_cands) == 1:
                pm = pm_cands[0]
                pubmed_backfilled.append(stem)
                authors_str = pm.get("authors_short", "").strip()
                parent = {
                    "_source": "pubmed_expansion",
                    "key": None,
                    "DOI": (pm.get("doi") or "").strip(),
                    "title": pm.get("title", "").strip(),
                    "date": pm.get("year", ""),
                    "creators": [{"creatorType": "author", "lastName": authors_str, "firstName": ""}],
                    "publicationTitle": pm.get("journal", "").strip(),
                    "ISSN": "",
                    "volume": "",
                    "pages": "",
                    "url": f"https://doi.org/{pm.get('doi','')}" if pm.get("doi") else "",
                    "itemType": "journalArticle",
                }
                match_via = "pubmed_backfill"

        # Pass 5: scan PDF markdown for any DOI; cross-check with pubmed first then synthesise
        if not parent:
            scanned_doi = doi_from_markdown(stem)
            if scanned_doi:
                low = scanned_doi.lower()
                # Look in pubmed_expansion by DOI directly
                pm_match = None
                for cands_list in pubmed_by_key.values():
                    for pm in cands_list:
                        if (pm.get("doi") or "").strip().lower() == low:
                            pm_match = pm; break
                    if pm_match: break
                if pm_match:
                    parent = {
                        "_source": "pubmed_expansion_doi_scan",
                        "key": None,
                        "DOI": pm_match.get("doi", ""),
                        "title": pm_match.get("title", "").strip(),
                        "date": pm_match.get("year", ""),
                        "creators": [{"creatorType": "author", "lastName": pm_match.get("authors_short",""), "firstName": ""}],
                        "publicationTitle": pm_match.get("journal", "").strip(),
                        "ISSN": "", "volume": "", "pages": "",
                        "url": f"https://doi.org/{low}",
                        "itemType": "journalArticle",
                    }
                    match_via = "doi_scan_pubmed"
                else:
                    # Synthesize a minimal entry from the DOI alone
                    parent = {
                        "_source": "pdf_doi_scan",
                        "key": None,
                        "DOI": scanned_doi,
                        "title": "",
                        "date": "",
                        "creators": [],
                        "publicationTitle": "",
                        "ISSN": "", "volume": "", "pages": "",
                        "url": f"https://doi.org/{low}",
                        "itemType": "journalArticle",
                    }
                    match_via = "doi_scan_only"

        if not parent:
            unmatched.append(stem)
            continue

        creators = parent.get("creators") or []
        authors = []
        for c in creators:
            if c.get("creatorType") not in ("author", None):
                continue
            ln = c.get("lastName", "").strip()
            fn = c.get("firstName", "").strip()
            authors.append(f"{ln}, {fn}" if fn else ln)

        # Year is in the date field (often "2024-03-15" or just "2024")
        date = (parent.get("date") or "").strip()
        year = ""
        m = re.search(r"\b(19|20|21)\d{2}\b", date)
        if m:
            year = m.group(0)

        # Apply DOI patch override if present (Zotero metadata's DOI field empty)
        doi_patched = (parent.get("DOI") or "").strip().lower()
        if not doi_patched and ov and ov.get("doi_patch"):
            doi_patched = ov["doi_patch"].strip().lower()

        registry[stem] = {
            "stem": stem,
            "doi": doi_patched or None,
            "zotero_key": parent.get("key"),
            "title": parent.get("title", "").strip(),
            "year": year,
            "date": date,
            "authors": authors,
            "journal": parent.get("publicationTitle", "").strip(),
            "issn": parent.get("ISSN", "").strip() or None,
            "volume": parent.get("volume", "").strip() or None,
            "pages": parent.get("pages", "").strip() or None,
            "url": parent.get("url", "").strip() or None,
            "item_type": parent.get("itemType"),
            "pdf_path": str(path.relative_to(ROOT)),
            "match_via": match_via,
        }

    # DOI lookup table (DOI lowercase → stem)
    doi_index = {r["doi"]: stem for stem, r in registry.items() if r["doi"]}

    # Write outputs
    OUT_REGISTRY.write_text(json.dumps(registry, indent=2, ensure_ascii=False))
    OUT_DOI_INDEX.write_text(json.dumps(doi_index, indent=2))
    OUT_UNMATCHED.write_text("\n".join(unmatched) + ("\n" if unmatched else ""))

    n_with_doi = sum(1 for r in registry.values() if r["doi"])

    # ── HARD GATE: every paper must have a DOI. Flag loudly if any are missing.
    missing_doi = sorted([(stem, r) for stem, r in registry.items() if not r.get("doi")])
    if missing_doi:
        lines = ["Stems missing a DOI — please fix manually before downstream steps:"]
        for stem, r in missing_doi:
            title = (r.get("title") or "")[:80]
            lines.append(f"  {stem}    ({title})")
        OUT_MISSING_DOI.write_text("\n".join(lines) + "\n")
        print()
        print("█" * 70)
        print(f"⚠  {len(missing_doi)} PAPERS WITHOUT A DOI — please look these up manually:")
        for stem, r in missing_doi:
            print(f"   {stem}    ({(r.get('title') or '')[:60]})")
        print(f"   Full list also written to {OUT_MISSING_DOI.name}")
        print("   Add overrides via STEM_OVERRIDES in build_paper_registry.py")
        print("█" * 70)
    else:
        OUT_MISSING_DOI.write_text("")  # clear it so stale records don't linger
        print("✓ Every PDF in pdfs/ has a DOI in the registry.")
    via_counts: dict[str, int] = {}
    for r in registry.values():
        via_counts[r["match_via"]] = via_counts.get(r["match_via"], 0) + 1
    summary = [
        "Paper registry summary (Zotero + pubmed_expansion + DOI scan)",
        "=" * 60,
        f"PDFs in pdfs/:                          {len(pdfs_on_disk)}",
        f"  matched to a metadata source:         {len(registry)}",
        f"    via consensus DOI → Zotero:         {via_counts.get('consensus_doi_zotero', 0)}",
        f"    via Zotero filename (unique):       {via_counts.get('filename', 0)}",
        f"    via filename collision + DOI:       {via_counts.get('filename_collision_doi_resolved', 0)}",
        f"    via filename collision + title:     {via_counts.get('filename_collision_title_resolved', 0)}",
        f"    via Zotero fuzzy author+year:       {via_counts.get('fuzzy', 0)}",
        f"    via Zotero fuzzy + title disambig:  {via_counts.get('fuzzy_title_disambig', 0)}",
        f"    via DOI bridged through pubmed:     {via_counts.get('doi_via_pubmed', 0)}",
        f"    via DOI scan from PDF → Zotero:     {via_counts.get('doi_from_pdf', 0)}",
        f"    via pubmed_expansion only:          {via_counts.get('pubmed_backfill', 0)}",
        f"    via DOI scan from PDF → pubmed:     {via_counts.get('doi_scan_pubmed', 0)}",
        f"    via DOI scan from PDF only:         {via_counts.get('doi_scan_only', 0)}",
        f"    via manual override (Zotero key):   {via_counts.get('manual_override_zotero', 0)}",
        f"    via manual override (synthetic):    {via_counts.get('manual_override', 0)}",
        f"    of which have a DOI:                {n_with_doi}",
        f"  unmatched (no metadata anywhere):     {len(unmatched)}",
        "",
        f"Zotero parents indexed:                 {len(parents_by_key)}",
        f"Zotero PDF attachments indexed:         {len(pdf_attachments)}",
        "",
    ]
    if unmatched:
        summary.append(f"Unmatched PDFs ({len(unmatched)}):")
        for s in unmatched[:50]:
            summary.append(f"  {s}")
        if len(unmatched) > 50:
            summary.append(f"  ... +{len(unmatched) - 50} more")
    OUT_SUMMARY.write_text("\n".join(summary) + "\n")
    print()
    print("\n".join(summary))


if __name__ == "__main__":
    main()

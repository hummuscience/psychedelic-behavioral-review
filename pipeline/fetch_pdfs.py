"""Get PDFs for relevant records that don't have one yet.

Which records:
  - rows added by the monthly search (source "update:...") that the classifier
    marks relevant, plus any row you've marked "included_in_review" in
    data/manual_decisions.json (that's how to rescue a record the classifier
    dropped);
  - skipping rows already in the paper registry, rows marked as duplicates,
    and rows with any other "excluded_*" decision.

Where from, in order:
  1. the inbox: WORK_DIR/inbox/<pmid>.pdf, a PDF you put there by hand (for
     paywalled papers). <pmid>_supp.pdf or .docx is taken as the supplement.
     The inbox is checked for every row in the search CSV, including ones from
     the original search that were never retrieved.
  2. open-access copies: OpenAlex, then Unpaywall (only if UNPAYWALL_EMAIL is
     set), then Europe PMC / PMC.

Each retrieved paper gets a new, unique stem (<surname><year>, then
<surname><year>b, c, ...; never reusing a stem already in the corpus), a PDF in
WORK_DIR/pdfs/, an entry in data/paper_registry.json and a row in
data/pdf_inventory.csv. Papers with no PDF are appended once to
data/pdfs_not_found.csv and are retried on every run.
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from unidecode import unidecode

import preprints
from classify_compounds import decision
from paths import (CONSENSUS_DIR, MANUAL_DECISIONS_JSON, PDF_DIR, PDF_INVENTORY_CSV,
                   PDFS_NOT_FOUND_CSV, PRISMA_CSV, PUBMED_CSV, REGISTRY_JSON, SUPP_DIR,
                   WORK_DIR)

INBOX_DIR = WORK_DIR / "inbox"
USER_AGENT = ("psychedelic-behavioral-review/1.0 "
              "(+https://github.com/hummuscience/psychedelic-behavioral-review)")
MIN_PDF_BYTES = 20_000
_PREFIXES = ("de", "del", "della", "der", "den", "di", "do", "dos", "du", "la", "le",
             "lo", "los", "van", "von", "vom", "ten", "ter", "te", "da")


# ── Stems ────────────────────────────────────────────────────────────────────

def _key(stem: str) -> str:
    """Comparison key: ASCII, lower case, letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", unidecode(unicodedata.normalize("NFC", stem)).lower())


def taken_stems() -> set[str]:
    """Every stem in use anywhere in the published data (comparison keys).

    Includes the stems PRISMA accounting guesses for original-search records
    (<surname><year>), so a new paper never takes the name of an old record:
    the accounting would otherwise read the new PDF as that record's.
    """
    from build_prisma_accounting import stem_for
    taken = set()
    if PRISMA_CSV.exists():
        with open(PRISMA_CSV, encoding="utf-8") as f:
            taken |= {_key(r["stem"]) for r in csv.DictReader(f) if r["stem"]}
    if PUBMED_CSV.exists():
        with open(PUBMED_CSV, encoding="utf-8") as f:
            taken |= {_key(st) for r in csv.DictReader(f)
                      if not r["source"].startswith("update:")
                      and (st := stem_for(r["authors_short"], r["year"]))}
    if REGISTRY_JSON.exists():
        taken |= {_key(k) for k in json.loads(REGISTRY_JSON.read_text())}
    if CONSENSUS_DIR.exists():
        taken |= {_key(p.stem) for p in CONSENSUS_DIR.glob("*.json")}
    if PDF_INVENTORY_CSV.exists():
        with open(PDF_INVENTORY_CSV, encoding="utf-8") as f:
            taken |= {_key(r["stem"]) for r in csv.DictReader(f)}
    return taken


def assign_stem(authors_short: str, year: str, taken: set[str]) -> str:
    """'<surname><year>', with b, c, ... appended on collision. ASCII only."""
    first = re.sub(r"\s+(et al\.?|&.*)$", "", (authors_short or "").strip())
    parts = first.split()
    # Drop trailing initials ("Smith AB" -> "Smith"; "De Gregorio D" -> "De Gregorio")
    while len(parts) > 1 and re.fullmatch(r"[A-Z]{1,3}\.?", parts[-1]):
        parts.pop()
    surname = re.sub(r"[^a-z]", "", unidecode(" ".join(parts)).lower()) or "unknown"
    base = f"{surname}{year or 'nd'}"
    stem, suffix = base, ord("b")
    while _key(stem) in taken:
        stem = f"{base}{chr(suffix)}"
        suffix += 1
    taken.add(_key(stem))
    return stem


# ── HTTP ─────────────────────────────────────────────────────────────────────

def _get(url: str, timeout: int = 60, accept: str = "*/*") -> tuple[bytes | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), r.headers.get("Content-Type", "")
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
        return None, str(e)


def _json(url: str) -> dict | None:
    data, _ = _get(url, timeout=30, accept="application/json")
    try:
        return json.loads(data) if data else None
    except json.JSONDecodeError:
        return None


def _is_pdf(data: bytes | None) -> bool:
    return bool(data) and data[:5] == b"%PDF-" and len(data) >= MIN_PDF_BYTES


# ── Open-access sources ──────────────────────────────────────────────────────

def _openalex_urls(doi: str) -> list[str]:
    j = _json(f"https://api.openalex.org/works/doi:{urllib.parse.quote(doi)}")
    if not j:
        return []
    locs = [j.get("best_oa_location") or {}] + (j.get("oa_locations") or [])
    return [loc["pdf_url"] for loc in locs if loc and loc.get("pdf_url")]


def _unpaywall_urls(doi: str) -> list[str]:
    email = os.environ.get("UNPAYWALL_EMAIL", "")
    if not email or email.endswith("@example.com"):
        return []
    j = _json(f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={email}")
    if not j:
        return []
    locs = [j.get("best_oa_location") or {}] + (j.get("oa_locations") or [])
    return [loc["url_for_pdf"] for loc in locs if loc and loc.get("url_for_pdf")]


def _europepmc_urls(pmid: str) -> list[str]:
    q = urllib.parse.quote(f"EXT_ID:{pmid} AND SRC:MED")
    j = _json("https://www.ebi.ac.uk/europepmc/webservices/rest/search"
              f"?query={q}&resultType=core&format=json")
    res = ((j or {}).get("resultList") or {}).get("result") or []
    if not res:
        return []
    r = res[0]
    urls = [u["url"] for u in (r.get("fullTextUrlList") or {}).get("fullTextUrl", [])
            if u.get("documentStyle") == "pdf" and u.get("availabilityCode") in ("OA", "F")]
    if r.get("pmcid"):
        urls += [f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={r['pmcid']}&blobtype=pdf",
                 f"https://pmc.ncbi.nlm.nih.gov/articles/{r['pmcid']}/pdf/"]
    return urls


def find_open_access(pmid: str, doi: str) -> tuple[bytes | None, str, list[str]]:
    """(pdf bytes, source, attempted urls). Bytes are None if nothing worked."""
    tried: list[str] = []
    sources = []
    if doi:
        sources += [("openalex", lambda: _openalex_urls(doi)),
                    ("unpaywall", lambda: _unpaywall_urls(doi))]
    if pmid:
        sources += [("europepmc", lambda: _europepmc_urls(pmid))]
    for name, urls_fn in sources:
        for url in dict.fromkeys(urls_fn()):  # de-duplicate, keep order
            tried.append(url)
            data, _ = _get(url, accept="application/pdf,*/*")
            time.sleep(1)
            if _is_pdf(data):
                return data, name, tried
    return None, "", tried


# ── Data files ───────────────────────────────────────────────────────────────

def _load_rows() -> list[dict]:
    with open(PUBMED_CSV, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def pending(rows: list[dict], registry: dict, decisions: dict) -> list[dict]:
    """Rows that should have a PDF and don't yet."""
    have = ({str(e.get("pmid")) for e in registry.values() if e.get("pmid")}
            | {(e.get("doi") or "").lower() for e in registry.values() if e.get("doi")})
    out = []
    for r in rows:
        doi = r["doi"].strip().lower()
        if r["pmid"] in have or (doi and doi in have):
            continue
        disp = (decisions.get(doi) or {}).get("disposition") if doi else None
        in_inbox = (INBOX_DIR / f"{r['pmid']}.pdf").exists()
        if r["source"].startswith("update:"):
            if disp == "included_in_review":
                out.append({**r, "_why": "manual_include"})
            elif disp is None and decision(r["detected_compounds"]) == "relevant":
                if not preprints.deferred(doi, r.get("journal")):
                    out.append({**r, "_why": "classifier"})
        # Records from the original search are only picked up when you put
        # their PDF in the inbox; their open-access search was done back then.
        elif in_inbox and (disp is None or disp in ("included_in_review",
                                                     "pdf_unavailable_relevant")):
            out.append({**r, "_why": "inbox"})
    return out


def _append_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    """Append rows in the file's existing line-ending style."""
    if not rows:
        return
    raw = path.read_bytes() if path.exists() else b""
    eol = "\r\n" if b"\r\n" in raw else "\n"
    with open(path, "a", encoding="utf-8", newline="") as f:
        if not raw:
            csv.writer(f, lineterminator=eol).writerow(fields)
        csv.DictWriter(f, fieldnames=fields, lineterminator=eol,
                       extrasaction="ignore").writerows(rows)


DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.I)
INBOX_NAME_RE = re.compile(r"^\d+(_supp)?\.(pdf|docx)$", re.I)
SUPP_NAME_RE = re.compile(r"supp|suppl|mmc\d|supporting|appendix", re.I)


def _norm_text(s: str) -> str:
    """Lowercase letters and digits only: line breaks and hyphenation don't matter."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", s).lower() if ch.isalnum())


def _first_pages_text(path: Path, pages: int = 2) -> str:
    import fitz  # PyMuPDF
    with fitz.open(path) as doc:
        return "".join(doc[i].get_text() for i in range(min(pages, len(doc))))


def identify_pdf(path: Path, rows: list[dict]) -> dict | None:
    """The search record a PDF belongs to: by a DOI on its first pages, else by
    its title appearing there (only if exactly one title matches)."""
    text = _first_pages_text(path)
    by_doi = {r["doi"].strip().lower(): r for r in rows if r["doi"].strip()}
    for m in DOI_RE.finditer(text):
        doi = m.group(0).rstrip(".,;:)]}").lower()
        if doi in by_doi:
            return by_doi[doi]
    page = _norm_text(text[:8000])
    hits = {r["pmid"]: r for r in rows
            if len(_norm_text(r["title"])) >= 30 and _norm_text(r["title"]) in page}
    return next(iter(hits.values())) if len(hits) == 1 else None


def match_inbox(rows: list[dict]) -> dict:
    """Give inbox PDFs saved under any name the <pmid>.pdf name the pipeline uses.

    Returns {"matched": [(file, new name)], "unmatched": [file]}."""
    import store
    out = {"matched": [], "unmatched": []}
    if not INBOX_DIR.exists():
        return out
    for f in sorted(INBOX_DIR.iterdir()):
        if not f.is_file() or INBOX_NAME_RE.match(f.name) or f.name.startswith("."):
            continue
        row = None
        if f.suffix.lower() == ".pdf":
            try:
                row = identify_pdf(f, rows)
            except Exception:  # unreadable or not a PDF
                row = None
        new = row and f"{row['pmid']}{'_supp' if SUPP_NAME_RE.search(f.stem) else ''}.pdf"
        if not new or (INBOX_DIR / new).exists():
            out["unmatched"].append(f.name)
            continue
        f.rename(INBOX_DIR / new)
        store.rename_inbox(f.name, new)
        out["matched"].append((f.name, new))
    return out


def run(today: date | None = None, offline: bool = False) -> dict:
    """Fetch PDFs for pending rows. Returns {fetched: [...], missing: [...],
    inbox: {matched, unmatched}}."""
    today = today or date.today()
    rows = _load_rows()
    inbox = match_inbox(rows)
    registry = json.loads(REGISTRY_JSON.read_text()) if REGISTRY_JSON.exists() else {}
    decisions = (json.loads(MANUAL_DECISIONS_JSON.read_text())
                 if MANUAL_DECISIONS_JSON.exists() else {})
    todo = pending(rows, registry, decisions)
    taken = taken_stems()
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    fetched, missing, inventory_rows = [], [], []
    for r in todo:
        pmid, doi = r["pmid"].strip(), r["doi"].strip().lower()
        inbox_pdf = INBOX_DIR / f"{pmid}.pdf"
        data, source = None, ""
        if inbox_pdf.exists() and _is_pdf(inbox_pdf.read_bytes()[:MIN_PDF_BYTES * 50]):
            data, source = inbox_pdf.read_bytes(), "inbox"
        elif not offline and r["_why"] != "inbox":
            data, source, _ = find_open_access(pmid, doi)
        if data is None:
            missing.append({"pmid": pmid, "doi": doi, "title": r["title"],
                            "authors_short": r["authors_short"], "year": r["year"],
                            "detected_compounds": r["detected_compounds"],
                            "reason": f"no open-access PDF found (last checked {today})",
                            "inbox_filename": f"{pmid}.pdf"})
            continue

        stem = assign_stem(r["authors_short"], r["year"], taken)
        (PDF_DIR / f"{stem}.pdf").write_bytes(data)
        has_supp = False
        for ext in (".pdf", ".docx"):
            supp = INBOX_DIR / f"{pmid}_supp{ext}"
            if supp.exists():
                SUPP_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(supp, SUPP_DIR / f"{stem}_supp{ext}")
                has_supp = True
                break
        registry[stem] = {
            "stem": stem, "doi": doi or None, "pmid": pmid, "zotero_key": None,
            "title": r["title"], "year": r["year"], "date": r["year"],
            "authors": [r["authors_short"]], "journal": r["journal"], "issn": None,
            "volume": None, "pages": None,
            "url": f"https://doi.org/{doi}" if doi else f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "item_type": "journalArticle", "pdf_path": f"pdfs/{stem}.pdf",
            "match_via": "monthly_update", "added": today.isoformat(), "pdf_source": source,
        }
        inventory_rows.append({"stem": stem, "folder": "pdfs", "has_docling_md": "False",
                               "has_supplementary": str(has_supp)})
        fetched.append({"stem": stem, "pmid": pmid, "doi": doi, "title": r["title"],
                        "authors_short": r["authors_short"], "year": r["year"],
                        "source": source, "why": r["_why"]})

    REGISTRY_JSON.write_text(json.dumps(registry, indent=2, ensure_ascii=False))
    _append_csv(PDF_INVENTORY_CSV, ["stem", "folder", "has_docling_md", "has_supplementary"],
                inventory_rows)
    already = set()
    if PDFS_NOT_FOUND_CSV.exists():
        with open(PDFS_NOT_FOUND_CSV, encoding="utf-8") as f:
            already = {row["pmid"] for row in csv.DictReader(f)}
    _append_csv(PDFS_NOT_FOUND_CSV,
                ["pmid", "doi", "title", "year", "detected_compounds", "reason"],
                [m for m in missing if m["pmid"] not in already])
    return {"fetched": fetched, "missing": missing, "inbox": inbox}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true",
                    help="only take PDFs from the inbox; don't try open-access sources")
    args = ap.parse_args()
    s = run(offline=args.offline)
    for f in s["fetched"]:
        print(f"  got  {f['stem']:24} via {f['source']:10} {f['title'][:70]}")
    for m in s["missing"]:
        print(f"  miss {m['pmid']:10} {m['authors_short'][:20]:20} {m['title'][:70]}")
    print(f"{len(s['fetched'])} fetched, {len(s['missing'])} still missing")


if __name__ == "__main__":
    main()

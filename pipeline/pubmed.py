"""Small PubMed E-utilities client (standard library only).

- esearch(term, ...)  → list of PMIDs
- efetch(pmids)       → list of record dicts with the fields the pipeline uses

Set NCBI_EMAIL (and optionally NCBI_API_KEY, which raises the rate limit from
3 to 10 requests/second) in the environment. Neither is required.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL = "psychedelic-behavioral-review"
_last_call = 0.0


def _params(extra: dict) -> dict:
    p = {"db": "pubmed", "tool": TOOL, **extra}
    if os.environ.get("NCBI_EMAIL"):
        p["email"] = os.environ["NCBI_EMAIL"]
    if os.environ.get("NCBI_API_KEY"):
        p["api_key"] = os.environ["NCBI_API_KEY"]
    return p


def _post(endpoint: str, params: dict, retries: int = 4) -> bytes:
    """POST with NCBI rate limiting and retry on transient errors."""
    global _last_call
    gap = 0.11 if os.environ.get("NCBI_API_KEY") else 0.35
    data = urllib.parse.urlencode(_params(params)).encode()
    for attempt in range(retries):
        wait = _last_call + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
        try:
            with urllib.request.urlopen(f"{EUTILS}/{endpoint}", data, timeout=120) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def esearch(term: str, mindate: str | None = None, maxdate: str | None = None,
            datetype: str = "edat") -> list[str]:
    """All PMIDs matching `term`, optionally restricted to a date window.

    Dates are YYYY/MM/DD. datetype "edat" is the Entrez date (when the record
    was added to PubMed), which is what an incremental search should use.
    """
    params = {"term": term, "retmode": "json", "retmax": 9999}
    if mindate or maxdate:
        params.update({"datetype": datetype, "mindate": mindate or "1900/01/01",
                       "maxdate": maxdate or "3000/12/31"})
    pmids: list[str] = []
    start = 0
    while True:
        j = json.loads(_post("esearch.fcgi", {**params, "retstart": start}))["esearchresult"]
        if "ERROR" in j:
            raise RuntimeError(f"esearch error: {j['ERROR']}")
        pmids += j["idlist"]
        start += 9999
        if start >= int(j["count"]):
            return pmids


def _text(el: ET.Element | None) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def authors_short(authors: list[str]) -> str:
    """'Smith AB' / 'Smith AB & Jones C' / 'Smith AB et al.' (matches the CSV)."""
    if not authors:
        return ""
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]} & {authors[1]}"
    return f"{authors[0]} et al."


def _parse(article: ET.Element) -> dict:
    mc = article.find("MedlineCitation")
    art = mc.find("Article")
    authors = []
    for a in art.findall("AuthorList/Author"):
        if a.find("LastName") is not None:
            authors.append(f"{_text(a.find('LastName'))} {_text(a.find('Initials'))}".strip())
        elif a.find("CollectiveName") is not None:
            authors.append(_text(a.find("CollectiveName")))
    pubdate = art.find("Journal/JournalIssue/PubDate")
    year = _text(pubdate.find("Year")) if pubdate is not None else ""
    if not year and pubdate is not None:
        year = _text(pubdate.find("MedlineDate"))[:4]
    if not year:
        year = _text(art.find("ArticleDate/Year"))
    doi = ""
    for aid in article.findall("PubmedData/ArticleIdList/ArticleId"):
        if aid.get("IdType") == "doi":
            doi = _text(aid)
    if not doi:
        for loc in art.findall("ELocationID"):
            if loc.get("EIdType") == "doi":
                doi = _text(loc)
    pmcid = next((_text(a) for a in article.findall("PubmedData/ArticleIdList/ArticleId")
                  if a.get("IdType") == "pmc"), "")
    abstract = " ".join(
        (f"{p.get('Label')}: " if p.get("Label") else "") + _text(p)
        for p in art.findall("Abstract/AbstractText"))
    return {
        "pmid": _text(mc.find("PMID")),
        "title": _text(art.find("ArticleTitle")),
        "abstract": abstract,
        "authors": authors,
        "authors_short": authors_short(authors),
        "year": year,
        "journal": _text(art.find("Journal/Title")),
        "doi": doi.lower(),
        "pmcid": pmcid,
        "publication_types": [_text(t) for t in art.findall("PublicationTypeList/PublicationType")],
        "mesh": [_text(m.find("DescriptorName")) for m in mc.findall("MeshHeadingList/MeshHeading")],
        "keywords": [_text(k) for k in mc.findall("KeywordList/Keyword")],
    }


def efetch(pmids: list[str], batch: int = 200) -> list[dict]:
    """Full records for `pmids`, in the order PubMed returns them."""
    out: list[dict] = []
    for i in range(0, len(pmids), batch):
        xml = _post("efetch.fcgi", {"id": ",".join(pmids[i:i + batch]),
                                    "retmode": "xml", "rettype": "abstract"})
        root = ET.fromstring(xml)
        out += [_parse(a) for a in root.findall("PubmedArticle")]
    return out

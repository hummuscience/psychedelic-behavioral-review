"""Preprints in the monthly update.

The published review included bioRxiv preprints. New preprints found by the
monthly search are set aside for now: not fetched, not scored, not on the
"PDFs needed" list; PRISMA marks them `deferred_preprint` and each monthly PR
lists them. Set INCLUDE_PREPRINTS=true (repository variable) to treat them like
any other paper again; a preprint added to data/manual_decisions.json as
`included_in_review` is always included. Published preprints are unaffected.
"""
from __future__ import annotations

import os

# bioRxiv/medRxiv (old and new prefixes), Research Square, SSRN, Preprints.org,
# arXiv, PsyArXiv/OSF, Authorea
DOI_PREFIXES = ("10.1101/", "10.64898/", "10.21203/", "10.2139/", "10.20944/",
                "10.48550/", "10.31234/", "10.31219/", "10.22541/")
JOURNAL_WORDS = ("biorxiv", "medrxiv", "research square", "ssrn", "preprints.org", "arxiv")


def is_preprint(doi: str | None, journal: str | None = "") -> bool:
    doi = (doi or "").strip().lower()
    journal = (journal or "").lower()
    return doi.startswith(DOI_PREFIXES) or any(w in journal for w in JOURNAL_WORDS)


def included() -> bool:
    return os.environ.get("INCLUDE_PREPRINTS", "").strip().lower() in ("1", "true", "yes", "on")


def deferred(doi: str | None, journal: str | None = "", manual_disposition: str | None = None) -> bool:
    """True for a preprint the monthly update should leave aside for now."""
    return (is_preprint(doi, journal) and not included()
            and manual_disposition != "included_in_review")

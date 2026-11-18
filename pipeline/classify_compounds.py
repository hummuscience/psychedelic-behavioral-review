"""Title-based compound classifier for PubMed records.

Fills the `detected_compounds` column of data/pubmed_expansion.csv with the
same label vocabulary the original (lost) classifier used, which the PRISMA
builder and the PDF step consume:

    Psilocybin/Psilocin, LSD, DMT, 5-MeO-DMT,
    DOI (2,5-dimethoxy-4-iodoamphetamine), Ayahuasca, Ibogaine, Mescaline,
    Psychedelic (general), Other serotonergic, MDMA, Ketamine,
    Unclassified/possible false positive

Several labels on one record are joined with "; " in this fixed order.

The original classifier read the TITLE only (matching on the abstract as well
disagrees with its labels on hundreds of records). This reconstruction matches
the original's screening decision on 96% of the 850 records it labelled; see
pipeline/SEARCH.md. Where the original was inconsistent ("Other serotonergic",
bare "DOI") the rules lean towards keeping a record, because a wrongly kept
record costs one scoring run and is caught at review, while a wrongly dropped
one silently loses a study.
"""
from __future__ import annotations

import re

# (label, pattern, case_sensitive). Order = output order.
RULES: list[tuple[str, str, bool]] = [
    ("DMT", r"\bDMT\b", True),
    ("DMT", r"\bN,\s?N-dimethyltryptamine", False),
    ("5-MeO-DMT", r"5-MeO-DMT|5-methoxy-N,\s?N-dimethyltryptamine", False),
    ("DOI (2,5-dimethoxy-4-iodoamphetamine)", r"2,5-dimethoxy-4-iodoamphetamine", False),
    ("DOI (2,5-dimethoxy-4-iodoamphetamine)", r"\bDOI\b(?!\s*:)", True),
    ("Psilocybin/Psilocin", r"\bpsilocybin\b|\bpsilocin\b|\bpsilocybe\b|magic mushroom", False),
    ("LSD", r"\bLSD\b", True),
    ("LSD", r"lysergic acid diethylamide|lysergamides?\b", False),
    ("Mescaline", r"\bmescaline\b", False),
    ("Ayahuasca", r"\bayahuasca\b", False),
    ("Ibogaine", r"\bibogaine\b|\bnoribogaine\b|\biboga\b", False),
    ("MDMA", r"\bMDMA\b", True),
    ("MDMA", r"methylenedioxymethamphetamine|\becstasy\b", False),
    ("Ketamine", r"\b(?:es|S-|R-)?ketamine\b", False),
    ("Other serotonergic",
     r"5-?HT\(?2A\)?|serotonin[- ]?2A|5-hydroxytryptamine[- ]?2A"
     r"|phenethylamines?\b|\bNBOMe|\bNBOH|\b25[A-Z]{1,2}-NB"
     r"|\b2C-[A-Z]|\bDO[BCM]\b|\blisuride\b|tryptamine derivatives?", False),
    ("Psychedelic (general)", r"psychedelic|hallucinogen", False),
]

LABEL_ORDER = [
    "Mescaline", "DMT", "5-MeO-DMT", "DOI (2,5-dimethoxy-4-iodoamphetamine)",
    "Psilocybin/Psilocin", "LSD", "Ayahuasca", "Ibogaine", "MDMA", "Ketamine",
    "Other serotonergic", "Psychedelic (general)",
]
UNCLASSIFIED = "Unclassified/possible false positive"

_COMPILED = [(lab, re.compile(p, 0 if cs else re.IGNORECASE)) for lab, p, cs in RULES]


def classify(title: str) -> str:
    """Return the `detected_compounds` string for one title."""
    found = {lab for lab, rx in _COMPILED if rx.search(title or "")}
    if not found:
        return UNCLASSIFIED
    return "; ".join(lab for lab in LABEL_ORDER if lab in found)


# Buckets that make a record relevant, as in build_prisma_accounting.PSY_BUCKETS.
PSY_LABELS = {"Psilocybin/Psilocin", "LSD", "DMT", "5-MeO-DMT",
              "DOI (2,5-dimethoxy-4-iodoamphetamine)", "Ibogaine", "Ayahuasca",
              "Mescaline", "Other serotonergic", "Psychedelic (general)"}


def decision(label: str) -> str:
    """Screening decision implied by a label string (mirrors the PRISMA builder)."""
    labs = {x.strip() for x in label.split(";")}
    if UNCLASSIFIED in labs or "false positive" in label.lower():
        return "false_positive"
    if labs & PSY_LABELS:
        return "relevant"
    if labs == {"MDMA"}:
        return "mdma_only"
    return "off_topic"


if __name__ == "__main__":
    import sys
    for line in sys.stdin:
        print(classify(line.strip()))

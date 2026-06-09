"""Data access + alignment for the three-way rater comparison.

Pure helpers only: docx parsing, stem mapping, HITL JSON read/write, consensus
item extraction, and assay pairing. No plotting, no network. The single JSON
side effect is human_scores_hitl.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import plot_human_vs_llm as _plot  # proven docx + matching logic

ROOT = Path(__file__).resolve().parent / ".." / "data"  # published datasets
CONSENSUS_DIR = ROOT / "results_v2_full_consensus"
DOCLING_DIR = ROOT / "pdfs"
ANA_DOCX = ROOT / "scoring_guide_ana_version4.docx"
HITL_JSON = ROOT / "human_scores_hitl.json"

B_ITEMS = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8"]
E_ITEMS = ["E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"]
D_ITEMS = ["D1", "D2", "D3", "D4", "D5", "D6"]

# Verified against live SCORING_PROMPT in score_studies.py on 2026-06-03.
ITEM_MAX = {
    "B1": 3, "B2": 1, "B3": 1, "B4": 1, "B5": 3, "B6": 1, "B7": 1, "B8": 1,
    "E1": 3, "E2": 1, "E3": 1, "E4": 1, "E5": 1, "E6": 1, "E7": 2, "E8": 1,
    "D1": 2, "D2": 3, "D3": 3, "D4": 1, "D5": 1, "D6": 1,
}

# Papers 1..20 in scoring_guide_ana_v2.docx order, mapped to true consensus
# stems. Paper 8's docx token is "goulart" but the stem has spaces.
PAPER_STEMS = [
    "alper2018", "brownstien2025", "chen2023", "colognesi2026",
    "cunningham2023", "fantegrossi2015", "gianfratti2022",
    "goulart da silva2022", "gregory2025", "hibicke2023",
    "horrocks2025", "huang2022", "jeanblanc2024", "kato2025", "lee2020",
    "marcherrorsted2020", "marek2018", "popik2019", "wang2025", "yu2023",
]

# Papers Ana actually filled in. v2 had only papers 11-20; v3 added papers 1-5;
# version4 (2026-06-09) added papers 6-10 (fantegrossi2015, gianfratti2022,
# goulart da silva2022, gregory2025, hibicke2023), so Ana now covers all 20.
# Derived at call time from the docx so it stays correct as Ana fills in more.
def ana_scored_stems() -> set:
    return set(parse_ana_docx())


def load_hitl() -> dict:
    """Return the HITL scores dict, or {} if the file does not exist yet."""
    if not HITL_JSON.exists():
        return {}
    with open(HITL_JSON) as fh:
        return json.load(fh)


def save_paper_scores(stem: str, paper_num: int, assays: list[dict]) -> None:
    """Insert/replace one paper's scored assays in the HITL JSON, then persist.

    Re-saving the same stem replaces its prior entry (the procedure may revise
    a paper). Other stems are untouched. Keys are kept in PAPER_STEMS order.
    """
    data = load_hitl()
    data[stem] = {"paper_num": paper_num, "assays": assays}
    ordered = {s: data[s] for s in PAPER_STEMS if s in data}
    # keep any unexpected stems at the end rather than dropping them
    for k in data:
        if k not in ordered:
            ordered[k] = data[k]
    with open(HITL_JSON, "w") as fh:
        json.dump(ordered, fh, indent=2, ensure_ascii=False)


_SECTION = {
    "B": "behavioural_complexity",
    "E": "environmental_complexity",
    "D": "recording_duration",
}
_ITEMS = {"B": B_ITEMS, "E": E_ITEMS, "D": D_ITEMS}


def _section_items(assay: dict, prefix: str) -> dict:
    sect = assay.get(_SECTION[prefix], {})
    out = {}
    for k, v in sect.items():
        m = re.match(rf"({prefix}\d+)_", k)
        if m and isinstance(v, dict) and "score" in v:
            out[m.group(1)] = int(v["score"])
    # fill any item the consensus omitted with None so callers see the gap
    for it in _ITEMS[prefix]:
        out.setdefault(it, None)
    return out


def load_consensus_items(stem: str) -> list[dict]:
    """Return [{assay_name, B{}, E{}, D{}}] for one paper's LLM consensus."""
    with open(CONSENSUS_DIR / f"{stem}.json") as fh:
        d = json.load(fh)
    out = []
    for a in d.get("assays", []):
        out.append({
            "assay_name": a.get("assay_name"),
            "B": _section_items(a, "B"),
            "E": _section_items(a, "E"),
            "D": _section_items(a, "D"),
        })
    return out


def parse_ana_docx() -> dict:
    """Return {stem: [{assay_name, B{}, E{}, D{}}]} for Ana's filled papers.

    Only papers Ana actually scored (non-empty B/E/D) are returned.
    """
    out = {}
    for paper in _plot.parse_docx(ANA_DOCX):
        extracted = _plot.extract_paper(paper)
        if not extracted or not extracted["assays"]:
            continue
        # docx token may be truncated (goulart); map by paper number.
        num = extracted["num"]
        stem = PAPER_STEMS[num - 1] if 1 <= num <= len(PAPER_STEMS) else extracted["stem"]
        assays = []
        for a in extracted["assays"]:
            if not (a["B"] or a["E"] or a["D"]):
                continue
            assays.append({
                "assay_name": a["name"],
                "B": dict(a["B"]),
                "E": dict(a["E"]),
                "D": dict(a["D"]),
            })
        if assays:
            out[stem] = assays
    return out


def pair_assays(human_assays: list[dict], llm_assays: list[dict]) -> list[tuple[int, int]]:
    """Greedy name-based pairing (delegates to the proven matcher)."""
    return _plot.match_assays(human_assays, llm_assays)

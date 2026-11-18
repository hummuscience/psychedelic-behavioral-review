"""Offline tests for the monthly-update pipeline (no network, no API keys).

Run:  uv run python -m pytest pipeline/tests/
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PIPELINE = Path(__file__).resolve().parents[1]
REPO = PIPELINE.parent
sys.path.insert(0, str(PIPELINE))

from classify_compounds import classify, decision  # noqa: E402
from fetch_pdfs import assign_stem  # noqa: E402


@pytest.fixture
def data_copy(tmp_path: Path) -> Path:
    shutil.copytree(REPO / "data", tmp_path / "data")
    return tmp_path


def run(script: str, root: Path, *args: str) -> None:
    env = {**os.environ, "DATA_DIR": str(root / "data"), "WORK_DIR": str(root / "work")}
    subprocess.run([sys.executable, str(PIPELINE / script), *args], env=env, check=True,
                   capture_output=True)


# ── Published data is reproduced exactly ─────────────────────────────────────

def test_prisma_rebuild_matches_published(data_copy: Path) -> None:
    run("build_prisma_accounting.py", data_copy)
    assert ((data_copy / "data/prisma_accounting.csv").read_bytes()
            == (REPO / "data/prisma_accounting.csv").read_bytes())


def test_catalog_add_leaves_published_entries_alone(data_copy: Path) -> None:
    results = data_copy / "data/results"
    run("build_assay_catalog.py", data_copy, "--add", "no_such_paper2099")
    for f in ("paper_assays.json", "assay_catalog.json"):
        assert (results / f).read_bytes() == (REPO / "data/results" / f).read_bytes()

    cons = data_copy / "data/results_v2_full_consensus"
    shutil.copy(cons / "zhang2025.json", cons / "newpaper2026.json")
    before = {e["canonical"]: e["count"] for e in json.loads((results / "assay_catalog.json").read_text())}
    run("build_assay_catalog.py", data_copy, "--add", "newpaper2026")
    after = {e["canonical"]: e["count"] for e in json.loads((results / "assay_catalog.json").read_text())}
    added = {r["canonical"] for r in json.loads((results / "paper_assays.json").read_text())["newpaper2026"]}
    assert {k for k in after if after[k] != before.get(k, 0)} == added
    assert all(after[k] == before[k] + 1 for k in added)


# ── New records never borrow an existing paper's PDF ─────────────────────────

def test_update_rows_do_not_surname_match_corpus(data_copy: Path) -> None:
    csv_path = data_copy / "data/pubmed_expansion.csv"
    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        csv.writer(f, lineterminator="\r\n").writerow(
            ["99999999", "A new psilocybin study in mice.", "Allen J et al.", "2026",
             "Some journal", "10.9999/new.2026", "update:2026-12-03", "no",
             "Psilocybin/Psilocin"])
    run("build_prisma_accounting.py", data_copy)
    rows = {r["pmid"]: r for r in csv.DictReader(
        open(data_copy / "data/prisma_accounting.csv", encoding="utf-8"))}
    new = rows["99999999"]
    assert new["stem"] == "" and new["on_disk"] == "False"
    assert new["disposition"] == "pdf_unavailable_relevant"
    # and every published record is unchanged
    published = list(csv.DictReader(open(REPO / "data/prisma_accounting.csv", encoding="utf-8")))
    assert all(rows.get(r["pmid"], r) == r for r in published if r["pmid"])


# ── Classifier ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title, label", [
    ("Psilocybin restores social behaviour in mice.", "Psilocybin/Psilocin"),
    ("Lysergic acid diethylamide alters sleep in rats.", "LSD"),
    ("Effects of N, N-Dimethyltryptamine on rat behaviour.", "DMT"),
    ("The serotonergic psychedelic DOI impairs deviance detection.",
     "DOI (2,5-dimethoxy-4-iodoamphetamine); Psychedelic (general)"),
    ("Attenuation of ecstasy-induced neurotoxicity by N-acetylcysteine.", "MDMA"),
    ("Prophylactic effects of arketamine in mice.", "Unclassified/possible false positive"),
    ("Norpsilocin analogues in mice.", "Unclassified/possible false positive"),
])
def test_classifier_labels(title: str, label: str) -> None:
    assert classify(title) == label


def test_decisions() -> None:
    assert decision("Psilocybin/Psilocin; Ketamine") == "relevant"
    assert decision("Mescaline") == "relevant"
    assert decision("MDMA") == "mdma_only"
    assert decision("Ketamine") == "off_topic"
    assert decision("Unclassified/possible false positive") == "false_positive"


# ── Stems ────────────────────────────────────────────────────────────────────

def test_stems_never_collide() -> None:
    taken = {"gattuso2025", "gattuso20251", "fleury2026", "fleury2026b"}
    assert assign_stem("Gattuso JJ et al.", "2025", taken) == "gattuso2025b"
    assert assign_stem("Fleury S et al.", "2026", taken) == "fleury2026c"
    assert assign_stem("Wawrzczak-Bargieła A et al.", "2026", taken) == "wawrzczakbargiela2026"
    assert assign_stem("De Souza CP & Lee K", "2026", taken) == "desouza2026"
    assert assign_stem("De Souza CP & Lee K", "2026", taken) == "desouza2026b"


def test_duplicate_detection() -> None:
    from search_pubmed import find_duplicate
    registry = json.loads((REPO / "data/paper_registry.json").read_text())
    rec = {"doi": "10.1038/new-journal-version",
           "title": registry["lu2025"]["title"].replace("’", "'")}
    assert find_duplicate(rec, registry) == "lu2025"
    assert find_duplicate({"doi": "", "title": "An unrelated title about rats."}, registry) is None


# ── A new paper never changes an old record (Cavallaro 2026 case) ────────────

def _add_monthly_paper(root: Path, stem: str, pmid: str, doi: str, authors: str) -> None:
    """Simulate fetch_pdfs.py having added a paper (CSV row, registry, inventory)."""
    with open(root / "data/pubmed_expansion.csv", "a", encoding="utf-8", newline="") as f:
        csv.writer(f, lineterminator="\r\n").writerow(
            [pmid, "Mescaline alters something in awake rats.", authors, "2026",
             "Some journal", doi, "update:2026-12-03", "no", "Mescaline"])
    reg_path = root / "data/paper_registry.json"
    reg = json.loads(reg_path.read_text())
    reg[stem] = {"stem": stem, "doi": doi, "pmid": pmid, "match_via": "monthly_update"}
    reg_path.write_text(json.dumps(reg, indent=2, ensure_ascii=False))
    with open(root / "data/pdf_inventory.csv", "a", encoding="utf-8", newline="") as f:
        csv.writer(f, lineterminator="\r\n").writerow([stem, "pdfs", "True", "False"])


def test_new_paper_with_an_old_records_stem_changes_nothing(data_copy: Path) -> None:
    # The original search has "Cavallaro N et al." 2026 (stem cavallaro2026,
    # no PDF). A different Cavallaro 2026 paper arrives under the same stem.
    _add_monthly_paper(data_copy, "cavallaro2026", "99999998", "10.9999/cav.2026",
                       "Cavallaro N et al.")
    run("build_prisma_accounting.py", data_copy)
    rows = {r["pmid"]: r for r in csv.DictReader(
        open(data_copy / "data/prisma_accounting.csv", encoding="utf-8"))}
    published = list(csv.DictReader(open(REPO / "data/prisma_accounting.csv", encoding="utf-8")))
    assert all(rows[r["pmid"]] == r for r in published if r["pmid"])
    assert rows["99999998"]["disposition"] == "pending_scoring"


def test_taken_stems_cover_original_search_records() -> None:
    from fetch_pdfs import taken_stems
    taken = taken_stems()
    assert "cavallaro2026" in taken  # only a PRISMA record, no PDF
    assert assign_stem("Cavallaro N et al.", "2026", taken) == "cavallaro2026b"

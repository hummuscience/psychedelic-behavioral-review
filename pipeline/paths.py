"""Shared file locations for the pipeline.

Two areas:

- DATA_DIR: the published, committed datasets (the repo's ``data/``).
- WORK_DIR: a private working area for things that must never be committed:
  source PDFs, Docling markdown (full text of copyrighted papers), and the
  per-model candidate scores. Defaults to ``work/`` at the repo root, which is
  gitignored. Point it elsewhere with the WORK_DIR environment variable.

Inside WORK_DIR the layout matches the original ``scoring/`` folder, so
``provider.py`` finds supplementary files as a sibling of the PDF folder.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

DATA_DIR = Path(os.environ.get("DATA_DIR", REPO / "data"))
WORK_DIR = Path(os.environ.get("WORK_DIR", REPO / "work"))

# ── Published (committed) ───────────────────────────────────────────────────
CONSENSUS_DIR = DATA_DIR / "results_v2_full_consensus"
RESULTS_DIR = DATA_DIR / "results"
PUBMED_CSV = DATA_DIR / "pubmed_expansion.csv"
PDFS_NOT_FOUND_CSV = DATA_DIR / "pdfs_not_found.csv"
PDF_INVENTORY_CSV = DATA_DIR / "pdf_inventory.csv"
REGISTRY_JSON = DATA_DIR / "paper_registry.json"
MANUAL_DECISIONS_JSON = DATA_DIR / "manual_decisions.json"
PRISMA_CSV = DATA_DIR / "prisma_accounting.csv"
DOSAGES_LLM_CSV = DATA_DIR / "dosages_llm.csv"
SEARCH_STATE_JSON = DATA_DIR / "search_state.json"

# ── Private (never committed) ───────────────────────────────────────────────
PDF_DIR = WORK_DIR / "pdfs"
SUPP_DIR = WORK_DIR / "pdfs_supplementary"
CANDIDATES_DIR = WORK_DIR / "results_v2_full_compare"
REPORTS_DIR = WORK_DIR / "reports"

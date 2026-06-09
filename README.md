# Psychedelic Behavioural Review — pipeline, data & dashboard

Open code and data companion to our systematic review of methodological rigour in
psychedelic rodent behavioural research (*Translational Psychiatry*, 2026).

**Live dashboard:** https://hummuscience.github.io/psychedelic-behavioral-review/

## What's here

| Directory | Contents |
|---|---|
| `pipeline/` | LLM scoring + extraction pipeline (triple-model scoring → consensus judging → registry / assay / PRISMA accounting) |
| `figures/` | Code to regenerate the paper's figures from the published data |
| `data/` | Derived datasets (CC-BY-4.0): per-paper consensus scores, doses, demographics, PRISMA accounting, rater-validation data |
| `dashboard/` | Interactive [Observable Framework](https://observablehq.com/framework/) site |

## Reproducibility — please read

This repository is **transparent and inspectable**, but re-running the scoring
**from scratch** requires two things we cannot provide:

1. **The source PDFs.** The reviewed publications are owned by their publishers.
   We do **not** redistribute them. You must obtain your own copies.
2. **Your own LLM API keys.** Scoring calls Gemini / Anthropic / GWDG SAIA /
   OpenRouter. See [`.env.example`](.env.example) for the variable names. Copy it
   to `.env` (which is gitignored) and fill in your keys.

What you **can** reproduce with **no keys and no PDFs**, using only the data in
`data/`:

- **The paper's figures** — `uv run python figures/plot_<name>.py` (see below)
- **The entire interactive dashboard** — see below

## Build the dashboard locally

```bash
cd dashboard
npm install
npm run dev      # live preview at http://localhost:3000
npm run build    # static build into dist/
```

The data loaders in `dashboard/src/data/*.py` read from `../data/` at build time
(Python standard library only — no extra Python packages needed for the build).

The dashboard is also built and deployed automatically to GitHub Pages on every
push to `main` — see [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml).
That workflow sets `OBSERVABLE_BASE=/psychedelic-behavioral-review` so all asset
and link paths resolve under the project's Pages sub-path. If you fork this under
a different repository name, update that value (and the URLs in `CITATION.cff`).

## Regenerate the figures

From the repository root (the scripts resolve their own paths, so the working
directory doesn't matter):

```bash
uv sync                                       # install Python deps (or: pip install -e .)
uv run python figures/plot_three_way.py        # three-way rater agreement (Ana × HITL × LLM)
uv run python figures/plot_dose_distribution.py # per-compound dose distributions
uv run python figures/plot_bed_cube.py          # complexity × duration cube
uv run python figures/plot_conditions.py
uv run python figures/plot_sex_over_time.py
uv run python figures/plot_score_timelines.py
uv run python figures/plot_application_donut.py
uv run python figures/plot_bed_projections.py
uv run python figures/plot_human_vs_llm.py      # LLM-vs-human validation
```

Each script reads the published datasets from `data/` and writes its PNG/PDF into
`figures/output/`.

To run the rater-library tests:

```bash
uv run python -m pytest figures/tests/
```

## Run the scoring pipeline (requires PDFs + API keys)

```bash
cp .env.example .env     # then fill in your keys
# obtain your own PDFs of the reviewed papers and point the pipeline at them
bash pipeline/run_v2_rescore.sh
```

The v2 pipeline runs three LLMs in parallel (`triple_score.py`), judges them to a
consensus (`judge_consensus.py`), then rebuilds the registry, assay catalog, and
PRISMA accounting.

## The data

`data/` holds the derived (CC-BY-4.0) outputs only — never the source PDFs:

| Path | What it is |
|---|---|
| `results_v2_full_consensus/*.json` | One judge-consensus record per paper (287 papers): scored assays, dosing, sex, age, evidence |
| `paper_registry.json` | Canonical per-paper metadata (DOI, title, authors, year, journal) |
| `prisma_accounting.csv` | PRISMA flow: every screened record with its disposition |
| `human_scores_hitl.json` | Human-in-the-loop rater scores used for LLM validation |
| `scoring_guide_ana_v2.docx`, `scoring_guide_ana_version4.docx` | Human rater scoring guides (also inputs to the validation figures) |
| `results/{sex_all,age_all}.csv` | Extracted demographics |
| `results/{assay_catalog,paper_assays}.json` | Normalised assay catalog |
| `results/study_scores.csv` | Per-study aggregate scores |

> Note: `data/dosages_llm_summary.csv` is a header-only rollup placeholder — the
> per-compound dose data the dashboard actually uses is derived live from the
> consensus JSONs (`dosing[]`) by the build loaders, so the summary CSV is not
> populated. The interactive Dosages page is unaffected.

## Licensing

- **Code** (`pipeline/`, `figures/`, `dashboard/`): MIT — see [`LICENSE`](LICENSE).
- **Data** (`data/`): CC-BY-4.0 — see [`LICENSE-DATA`](LICENSE-DATA).
- **Source PDFs:** owned by their publishers; **not** included or redistributed.

## Citation

See [`CITATION.cff`](CITATION.cff) (GitHub renders a "Cite this repository" button).
Please cite **both** the *Translational Psychiatry* paper and the Zenodo archive
DOI for the dataset version you used.

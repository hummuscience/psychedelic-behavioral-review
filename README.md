# Psychedelic Behavioural Review — pipeline, data & dashboard

Open code and data companion to our systematic review of methodological rigour in
psychedelic rodent behavioural research (*Translational Psychiatry*, 2026).

**Live dashboard:** https://hummuscience.github.io/psychedelic-behavioral-review/
[![DOI](https://zenodo.org/badge/1263903476.svg)](https://doi.org/10.5281/zenodo.20662839)
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

To run the tests (rater library, and the monthly pipeline: offline, no keys):

```bash
uv run python -m pytest figures/tests/ pipeline/tests/
```

## Run the scoring pipeline (requires PDFs + API keys)

```bash
cp .env.example .env     # then fill in your keys
# put your own PDFs of the reviewed papers in work/pdfs/ (or set WORK_DIR)
bash pipeline/run_v2_rescore.sh
```

The v2 pipeline runs three LLMs in parallel (`triple_score.py`), judges them to a
consensus (`judge_consensus.py`), then rebuilds the registry, assay catalog, and
PRISMA accounting.

## Monthly update (living review)

`.github/workflows/monthly-update.yml` runs `pipeline/monthly_update.py` on the
3rd of every month and opens a pull request. Nothing reaches the dashboard until
you merge it. Each run:

1. searches PubMed for records added since the last run, using the query printed
   in the paper's Methods (`pipeline/search_pubmed.py`);
2. classifies them on title (`pipeline/classify_compounds.py`), excludes records
   PubMed tags as reviews, news, letters and the like, and records journal
   versions of preprints already in the corpus as duplicates;
3. fetches open-access PDFs for relevant records (`pipeline/fetch_pdfs.py`);
4. scores new papers with the same three models and judge as the published data
   (at most 30 per run by default);
5. adds them to the assay catalog, rebuilds PRISMA accounting, and opens the PR.
   Paywalled papers are listed in a **"Monthly update: PDFs needed"** issue.

Published records are never rewritten: every step only adds. See
[`pipeline/SEARCH.md`](pipeline/SEARCH.md) for how the query and classifier were
chosen and validated.

### One-time setup

1. **Repo → Settings → Actions → General:** under *Workflow permissions*, tick
   *Allow GitHub Actions to create and approve pull requests* and save. (The
   read/write option above it can stay as it is: the workflow asks for the
   access it needs.)
2. **A private folder for PDFs.** PDFs can't go in this public repo, so the
   workflow keeps them in a WebDAV folder. With Nextcloud: create a folder with
   an `inbox` subfolder, then share the folder by **share link** with permission
   *Can edit*, a **password**, no expiry date and *Hide download* off. The part of
   the link after `/s/` is the share token. A share link reaches only that folder;
   an app password would open the whole account to the workflow.
3. **Repo → Settings → Secrets and variables → Actions**, add these secrets:

   | Secret | What |
   |---|---|
   | `SAIA_API_KEY` | GWDG SAIA key (Docling + the three candidate models) |
   | `AZURE_FOUNDRY_API_KEY`, `AZURE_FOUNDRY_ENDPOINT` | the judge (Opus via Azure Foundry) |
   | `STORE_WEBDAV_URL` | for a Nextcloud share link: `https://<your-nextcloud-host>/public.php/webdav` |
   | `STORE_WEBDAV_USER` | the share token |
   | `STORE_WEBDAV_PASSWORD` | the share link's password |
   | `CONTACT_EMAIL` | optional but recommended: sent to NCBI and Unpaywall, which ask API users for one. Without it, Unpaywall isn't tried and fewer open-access PDFs are found |
   | `NCBI_API_KEY` | optional; raises PubMed's rate limit |

   And these variables (*Variables* tab): `STORE_WEBDAV_VENDOR` = `other` for a
   share link. Optional: `AZURE_FOUNDRY_MODEL` (default `claude-opus-4-7`);
   `JUDGE_PROVIDER` (`foundry` by default; set `anthropic` and add an
   `ANTHROPIC_API_KEY` secret to use the Anthropic API directly).
4. **Run it once by hand:** Actions → *Monthly update* → *Run workflow*. The first
   run catches up from the end of the published search (late March 2026): about
   440 records, roughly 80 of them relevant.

### Each month

- **Review the PR.** It lists the new studies with their scores, duplicates found,
  and the titles the classifier dropped. Merge it to republish the dashboard. If it's
  still open at the next run, that run continues from it (nothing is scored twice)
  and the PR grows to cover both months.
- **Paywalled papers:** for items in the *PDFs needed* issue, save the PDFs in the
  folder's `inbox/` under **any file name**: each run reads the DOI on a PDF's first
  page (or its title) and files it under the right paper. Files it can't match are
  listed in the PR. A supplement needs its name, `<pmid>_supp.pdf` or `.docx`. The
  next run picks them up; to process them sooner, run the workflow by hand.
- **Preprints:** new preprints (bioRxiv, medRxiv, Research Square, …) are set aside
  for now: not fetched or scored, `deferred_preprint` in PRISMA, listed in each PR.
  Set the repository variable `INCLUDE_PREPRINTS` to `true` to include them, or add
  one to `data/manual_decisions.json` as `included_in_review`. The published
  review's preprints are unaffected.
- **Rescuing a dropped record:** add its DOI to `data/manual_decisions.json` with
  `"disposition": "included_in_review"`; the next run fetches and scores it.

### Institute downloader (optional)

Publishers grant subscription access by network address, so GitHub can't use it.
`pipeline/fetch_institute.py` runs on a computer on your institute network: it
reads the open *PDFs needed* issue, downloads what a publisher text-mining API
covers, and uploads each PDF to the store's `inbox/` as `<pmid>.pdf`. The
workflow's second monthly run (on the 6th) picks them up.

- **Routes:** Wiley's TDM API (`WILEY_TDM_TOKEN`; free token from Wiley's text
  and data mining page, works only from a subscribing institute's IP range) and
  Elsevier's Article Retrieval API (`ELSEVIER_API_KEY`; full-text access must be
  requested from Elsevier API Support). Other publishers' papers stay on the
  manual list: their licences don't allow scripted downloading.
- **Needs:** Python 3.8+, nothing else to install. If the system `python3` is
  older (3.6 fails with a SyntaxError), use a newer interpreter, e.g.
  `/opt/conda/bin/python3`, in the commands and the crontab line below.
- **Keep the clone on `main`**, so the monthly job only ever runs reviewed code
  (`git -C ~/psychedelic-behavioral-review checkout main`).
- **Settings:** `~/.config/psychedelic-review/fetch.env` (`chmod 600`), with
  `WILEY_TDM_TOKEN`, optional `ELSEVIER_API_KEY`, and the share-link
  `STORE_WEBDAV_URL` / `STORE_WEBDAV_USER` / `STORE_WEBDAV_PASSWORD`.
- **Try it:** `python3 pipeline/fetch_institute.py --check` (shows this
  computer's public IP, tests the inbox and a sample download), then
  `--dry-run`, then a normal run.
- **Schedule:** e.g. a crontab line for the 4th of each month:
  `17 6 4 * * cd ~/psychedelic-behavioral-review && git pull -q && python3 pipeline/fetch_institute.py >> ~/fetch_institute.log 2>&1`

Publisher terms: download only for this non-commercial project, keep the PDFs in
the private store, and delete them when the project ends (Wiley and Elsevier
both require this).

To run it on your own machine instead, fill in `.env` (see `.env.example`), point
`WORK_DIR` at a folder for PDFs, and run `uv run python pipeline/monthly_update.py`
(`--skip-scoring` to search and fetch without LLM calls).

### Bridge test (when the scoring models change)

The published scores came from models that have since been retired. The *Bridge
test* workflow (Actions tab, run by hand) re-scores the 20 papers the human
raters scored with the current candidate models and judge, compares them item by
item with the published scores and both raters. It judges from the `ensemble`
input (default `qwen,deepseek4,gemma4`); left empty, it picks the third model to
go with qwen + glm53 (the candidate closest to human rater 2). It opens a PR with the report in
`data/calibration/`. Inputs: the published pipeline's Docling text of those
papers, in the store's `calibration/` folder as `<stem>.docling.md` (and
`colognesi2026_supp.docling.md`); papers without one are downloaded if open
access. Scores are kept in `calibration/results/`, so a re-run only pays for
what's missing. Cost: about $10–15 for the judge, 1–2 hours. The monthly update
uses the `SCORING_MODELS` variable (default `qwen,deepseek4,gemma4`: glm-5.3-flash,
the planned GLM successor, has been down on SAIA since November 2026).

### Rescoring published papers

61 published papers were judged with only one or two of the three candidate
models (a model failed on them; see `data/scoring_provenance.csv`). The *Rescore
published papers* workflow scores such papers again with the current setup and
writes the results to `data/rescored/<ensemble>/` with a comparison against the
published scores; `data/results_v2_full_consensus/` is not changed. Inputs: the
published Docling text in the store's `rescore/inputs/` folder; scores are kept
in `rescore/results/` so a re-run continues where the last one stopped.

## The data

`data/` holds the derived (CC-BY-4.0) outputs only — never the source PDFs:

| Path | What it is |
|---|---|
| `results_v2_full_consensus/*.json` | One judge-consensus record per paper (287 papers): scored assays, dosing, sex, age, evidence |
| `scoring_provenance.csv` | Which models scored each paper: the ensemble asked for, the candidates the judge actually had, the judge (and the fallback, if it declined), effort, rubric and code versions, and a `setup_id` to group papers scored the same way. Built from the `scoring` block in each consensus JSON (`pipeline/provenance.py`); the published papers are `v2 (published)` |
| `paper_registry.json` | Canonical per-paper metadata (DOI, title, authors, year, journal) |
| `prisma_accounting.csv` | PRISMA flow: every screened record with its disposition |
| `pubmed_expansion.csv` | Every PubMed record screened, with its title-classifier label; monthly additions have `source = update:<date>` |
| `manual_decisions.json` | Hand triage decisions keyed by DOI (they override the classifier) |
| `pdf_inventory.csv` | Which papers have a PDF (file names only; the PDFs aren't published) |
| `pdfs_not_found.csv` | Relevant records with no retrievable PDF |
| `search_state.json` | Where the next monthly search starts (created by the first run) |
| `human_scores_hitl.json` | Rater 2's raw human-in-the-loop scores |
| `raters.json` | Combined two-rater scores (`rater1`, `rater2` per paper/assay) — the single source for the inter-rater comparison (`figures/plot_three_way.py`); regenerate with `pipeline/build_raters_json.py` |
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
Please cite **both** the paper and the Zenodo archive DOI for the dataset version
you used:

> Abd El Hay MY, Cukić A, Schölvinck ML, Havenith MN (2026). Animal models in
> psychedelic research – Tripping over translation. *Translational Psychiatry* 16, 659.
> https://doi.org/10.1038/s41398-026-04589-z

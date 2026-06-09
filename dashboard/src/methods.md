---
title: Methods
toc: true
---

# Methods

How the corpus was assembled, scored, and reconciled, with the rubric, the data pipeline, and the validation work.

## Pipeline overview

<style>
  .pipe {
    display: flex; flex-wrap: wrap; align-items: center;
    gap: 10px 8px; margin: 8px 0 24px;
    font-family: ui-sans-serif, system-ui, sans-serif;
  }
  .pipe-node {
    background: var(--theme-background-alt, #f7f5f1);
    border: 1px solid var(--theme-foreground-faintest, #d2cdc1);
    border-radius: 10px; padding: 8px 12px;
    font-size: 0.88rem; line-height: 1.3;
    white-space: nowrap;
  }
  .pipe-node.judge { background: #f1e8fb; border-color: #c8a8e8; }
  .pipe-node.out   { background: #ecf6ec; border-color: #b3d8b3; font-weight: 600; }
  .pipe-arrow { color: var(--theme-foreground-muted, #7a766d); font-size: 1.1rem; }
  .pipe-stack { display: inline-flex; flex-direction: column; gap: 4px; }
  .observablehq-dark .pipe-node { background: #1e1c19; border-color: #3a3830; }
  .observablehq-dark .pipe-node.judge { background: #2a1f33; border-color: #5a4878; }
  .observablehq-dark .pipe-node.out { background: #1a2a1a; border-color: #3a5a3a; }
</style>

<div class="pipe">
  <div class="pipe-node">PDF</div>
  <span class="pipe-arrow">→</span>
  <div class="pipe-node">Docling → markdown</div>
  <span class="pipe-arrow">→</span>
  <div class="pipe-stack">
    <div class="pipe-node">qwen3-235b-a22b</div>
    <div class="pipe-node">glm-4.6</div>
    <div class="pipe-node">gpt-oss-120b</div>
  </div>
  <span class="pipe-arrow">→</span>
  <div class="pipe-node judge">Claude Opus 4.7 judge</div>
  <span class="pipe-arrow">→</span>
  <div class="pipe-node out">consensus JSON</div>
</div>

Each PDF is converted to markdown via [Docling](https://github.com/docling-project/docling), then scored independently by three SAIA-hosted open-weight models (qwen3-235b-a22b, glm-4.6, gpt-oss-120b). The three candidate scorings are passed to **Claude Opus 4.7** (the production judge) which produces a single consensus output following the same JSON schema. Temperature is 0.0 throughout. Each consensus record carries `judge_provider`, `judge_model`, and `judge_input_models` for full provenance.

## What gets scored per assay

Each assay in the corpus is scored on three dimensions plus structured descriptive metadata.

**Behavioural Complexity** (B1–B8, raw max 12):
- B1 number of distinct measures · B2 within-session temporal dynamics · B3 sequential / transitional structure · B4 ethological behaviours · B5 social component · B6 cognitive / learned · B7 automated classification · B8 multivariate analysis

**Environmental Complexity** (E1–E8, raw max 11):
- E1 environment type · E2 shelter · E3 bedding · E4 nesting · E5 enrichment · E6 spatial complexity · E7 social context · E8 food/water in apparatus

**Recording Duration** (D1–D6, raw max 11):
- D1 continuity · D2 longest session · D3 recording days · D4 pre-drug baseline · D5 post-acute follow-up · D6 circadian coverage

Each item carries `score`, `value`, `evidence` (verbatim quote), and `confidence` (high/low). Items the paper is silent on get score 0 with `value=not_reported`.

## Descriptive metadata

Beyond the dimensional B/E/D scores, the rubric extracts:

**Per paper (`housing_conditions`):** handling, group_housing, day_night_flipped, enrichment_housing.

**Per paper (`dosing[]`):** one entry per compound the paper administered, with `compound`, `doses_mg_per_kg` (numeric list), `doses_raw` (verbatim), `route`, `vehicle`, `schedule` (acute / repeated / chronic), `evidence`, `confidence`. This is the source of truth for the [Dosages](/dosages) and [Compounds](/compounds) pages.

**Per paper (`species`, `strain`, `sex`, `age`, `psychedelic`):** structured records with value, evidence, and confidence. `sex` and `age` are reconciled with `results/sex_all.csv` and `age_all.csv` sidecars at dashboard build time for backward compatibility with the v1 schema.

**Per assay (`experimental_conditions`):** application_type, setup_habituation, setup_restrain, food_restriction, water_restriction, time_to_assay (with optional `value_minutes`).

**Per assay (`outcomes`):** summary, direction, dose_dependent, sex_dependent, time_dependent, statistics, evidence. Used by the per-study pages, not currently aggregated.

**Per assay (`sample_size`):** n_total, n_male, n_female, n_per_group_min, with evidence.

### `no` vs `not_reported` rule

This is the central interpretive rule for every descriptive field:
- **`no`** is used **only** when the paper *explicitly* states the absence (e.g. "animals were not handled", "single-housed", "ad libitum food").
- **`not_reported`** is used when the paper is **silent** on the topic. The rubric forbids inferring "no" from typicality — silence is its own value.

This means fields like `enrichment_housing` and `handling` come back as `not_reported` for the majority of the corpus, which is faithful to what authors actually report rather than what is typical for the field.

## Dose extraction

**Dosing is part of the LLM scoring schema** as of the v2 rescore — each consensus JSON's top-level `dosing[]` field carries one entry per compound the paper administered, with the dose list parsed to `mg/kg`, plus route, vehicle, schedule, and evidence. This is the source the dashboard's Dosages and Compounds pages read from.

A first-generation snippet pipeline (`extract_dosages.py` → `disambiguate_doses.py` → `extract_dosages_qwen.py`) still exists at the project root and produces `dosages_llm.csv`. **It is no longer wired into the dashboard** — it had three failure modes the judge fixes:

1. **Decimal loss** (e.g. `1.5 mg/kg` parsed as `150 mg/kg` when the period was dropped during regex extraction).
2. **Cross-compound bleed** when one Methods paragraph lists several compounds (e.g. one paper's 5-HTP doses being misattributed to psilocybin).
3. **Snippet inflation** — the same dose mentioned in Methods, Discussion, and figure captions appeared as N separate records instead of one.

The current `dosing[]` field has one entry per `(paper, compound)`, with the dose list deduplicated, and has gone through three independent extractions plus the judge — so all three failure modes are resolved.

### Acute-toxicity post-trim

One paper (`zhuk2015`) was scored before we noticed the schema didn't distinguish behavioural-treatment doses from acute-toxicity / LD50 range-finding doses. The judge concatenated both into a single `doses_mg_per_kg` list (e.g. Psilocin `[0.25, 0.5, 1.0, 2.0, 180, 200, 250, 300, 350, 400, 410, 420]`). The 180–420 mg/kg values were trimmed post-hoc with a `judge_notes` audit entry; only the 0.25–2 mg/kg HTR-assay doses remain. No other paper in the corpus shows this contamination pattern.

## Corpus filter

A paper appears in the dashboard only if its consensus JSON contains **≥ 1 scored assay**. Papers that scored through but produced no behavioural assays — chemistry / analytical / EEG-only / pharmacokinetics-only studies that slipped past title-abstract screening — are filtered out. There are 23 such papers (as of the last build); they are accounted for in `prisma_accounting.csv` under `excluded_no_behaviour_in_full_text` or `in_corpus_no_animal_dose`, not in the corpus count.

## PRISMA accounting & stem disambiguation

The corpus uses `<surname><year>` as the citekey/stem (BetterBibTeX-style), generated by the search pipeline. When two papers happen to share an author surname and year, the stems collide — different DOIs end up under the same stem string. `disambiguate_stems.py` resolves this PRISMA-side:

1. Read each consensus JSON's stored DOI (and treat missing DOIs as a separate problem class).
2. For each colliding stem, keep the row whose DOI matches the consensus JSON at the canonical (bare) stem. Suffix the other rows' stems with letter discriminators (`flanagan2021` → `flanagan2021b`, `de la fuente revenga2021` → `…b/c/d`).
3. If the consensus JSON's DOI doesn't match any PRISMA row for that stem (the consensus paper isn't in PRISMA), suffix every existing row and insert a new `manually_added_to_corpus` row at the bare stem.
4. Recompute `in_consensus` honestly — True iff a consensus JSON exists for the row's (post-rename) stem.

Cases where the consensus JSON has no DOI metadata are flagged in `prisma_problems.csv` for manual review. The Zotero MCP integration was used to backfill DOIs for ~16 of these problem stems via BetterBibTeX citation-key lookup.

After disambiguation, `n_consensus` (consensus JSONs with assays) and `n_admin_papers` (papers whose `dosing[]` is non-empty) agree with the dashboard corpus count.

## Reproducing the pipeline

Top-level scripts:

- `bulk_docling.py` — PDF → markdown via Docling (cached)
- `score_studies.py` / `triple_score.py` — three-model independent scoring
- `judge_consensus.py` — Claude Opus 4.7 consensus pass
- `rescore_with_supp.py` — re-judges papers with supplementary material once it's been added
- `build_paper_registry.py` — PubMed expansion + manual additions
- `build_prisma_accounting.py` — PRISMA flow + dispositions
- `disambiguate_stems.py` — colliding-stem resolution (this page's section above)
- `extract_dosages.py` / `disambiguate_doses.py` / `extract_dosages_qwen.py` — legacy snippet-based dose pipeline (no longer used by the dashboard)

Each script is `uv run python <name>.py --help`-able. Recent v2 runs cost ~$25 in API spend (Opus 4.7 is the dominant cost; SAIA is free for academic use within rate limits).

## Validation

We benchmarked six judge models (Opus 4.7, Haiku 4.5, GPT-5 mini, Gemini 2.5 Flash, Kimi K2-0905, qwen3-235b-a22b) on a 13-paper subset against manual labels in `rodent_conditions.txt`. Opus 4.7 produced the highest exact agreement among the cost-effective options and was selected as production judge for v2. Provenance for every paper is recorded in the consensus JSON (`judge_provider`, `judge_model`, `judge_input_models`).

Disagreements with the manual annotation cluster on three fields where the strict rubric and the manual annotator's looser usage diverge:

- `food_restriction` / `water_restriction` — "during" used liberally in the manual sheet vs. strictly defined in the rubric (only when there's no access *during recording*).
- `setup_restrain` — the manual sheet treats brief restraint for drug administration as `yes`; the rubric reserves `yes` for during-recording restraint only.

These are documented in the rubric (see `scoring_guide.md`) and are **deliberate**, not model errors.

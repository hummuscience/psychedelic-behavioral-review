# Psychedelic Behavioural-Review Dashboard

Static-site dashboard built with [Observable Framework](https://observablehq.com/framework/), companion to our systematic review.

## Local development

```bash
npm install
npm run dev      # live-reload preview at http://localhost:3000
npm run build    # static build into dist/
```

The Python data loaders in `src/data/*.py` read the published datasets from the
repository's top-level `data/` directory at build time (standard library only):
- `src/data/studies.json.py` → `data/results_v2_full_consensus/*.json` (+ registry, sex/age, assay catalog)
- `src/data/dosages.csv.py` → dose records derived live from `data/results_v2_full_consensus/*.json`
- `src/data/dosages-summary.csv.py` → `data/dosages_llm_summary.csv`
- `src/data/prisma.json.py` → `data/prisma_accounting.csv` (+ consensus JSONs)
- `src/data/assay_catalog.json.py` → `data/results/assay_catalog.json`

To rebuild after the data updates: re-run `npm run build`.

## Pages

| Page | Path | Content |
|---|---|---|
| Overview | `/` | 3D scoring cube + summary cards + recent studies |
| Studies | `/studies` | Sortable, filterable table of all studies; CSV export |
| Per-study | `/studies/<stem>` | Full per-paper detail (B/E/D items + evidence + housing + assays) |
| Compounds | `/compounds` | Per-compound paper counts + dose ranges |
| Dosages | `/dosages` | Per-compound histogram & strip plot, mg/kg & nmol/kg toggle |
| Conditions | `/conditions` | Stacked bars for binary housing/exp fields |
| Application Type | `/applications` | Routes-of-administration distribution |
| Restrictions | `/restrictions` | Food + water restriction donuts |
| Pipeline / PRISMA | `/pipeline` | Mermaid flow diagram + disposition breakdown |
| Methods | `/methods` | Documentation of the LLM scoring rubric |
| Data downloads | `/data` | Direct download of all datasets |

## Deployment

The dashboard deploys automatically to GitHub Pages via the workflow at
`.github/workflows/deploy.yml` in the repository root: every push to `main` runs
`OBSERVABLE_BASE=/psychedelic-behavioral-review npm run build` and publishes
`dist/` to Pages. The live site is
https://hummuscience.github.io/psychedelic-behavioral-review/.

To preview the production (sub-path) build locally:

```bash
OBSERVABLE_BASE=/psychedelic-behavioral-review npm run build
npx http-server dist   # or any static server
```

## Citation

See `CITATION.cff` in the repository root. Please cite both the paper and the
Zenodo DOI for the dataset version you used.

## License

Code: MIT.  
Dataset (extracted scores, doses, conditions): CC-BY-4.0.  
Source PDFs are owned by their respective publishers and are not redistributed.

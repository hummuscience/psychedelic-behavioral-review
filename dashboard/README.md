# Psychedelic Behavioural-Review Dashboard

Static-site dashboard built with [Observable Framework](https://observablehq.com/framework/), companion to our systematic review.

## Local development

```bash
npm install
npm run dev      # live-reload preview at http://localhost:3000
npm run build    # static build into dist/
```

The data loaders in `src/data/*.py` read from the parent `scoring/` directory at build time:
- `src/data/studies.json.py` → loads `../results_full_consensus/*.json`
- `src/data/dosages.csv.py` → loads `../dosages_llm.csv`
- `src/data/dosages-summary.csv.py` → loads `../dosages_llm_summary.csv`
- `src/data/prisma.json.py` → loads `../prisma_accounting.csv`

To rebuild after the scoring pipeline updates: re-run `npm run build`.

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

### Cloudflare Pages (recommended — free, fast)

```bash
# one-time
npm install -g wrangler
wrangler pages project create psychedelic-review
# every deploy
npm run build
wrangler pages deploy dist --project-name psychedelic-review
```

A custom domain (e.g. `dashboard.zeronoise-lab.org`) can be wired up in the Cloudflare dashboard.

### GitHub Pages

```bash
npm run build
# push the dist/ folder to a gh-pages branch
git subtree push --prefix dashboard/dist origin gh-pages
```

Then enable Pages on the gh-pages branch in repo settings. URL will be like
`https://<username>.github.io/<repo>/`.

### Netlify

Drag-and-drop the `dist/` folder onto https://app.netlify.com/drop, or connect the repo and set build command `cd dashboard && npm install && npm run build`, output `dashboard/dist`.

## Citation

When citing this dataset, please include both the paper and the Zenodo DOI for the dataset version (to be assigned upon archival).

## License

Code: MIT.  
Dataset (extracted scores, doses, conditions): CC-BY-4.0.  
Source PDFs are owned by their respective publishers and are not redistributed.

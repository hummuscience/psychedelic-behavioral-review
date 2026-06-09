---
title: Data downloads
toc: false
---

# Data downloads

All datasets that drive this dashboard, available as direct downloads.

```js
const studies = await FileAttachment("data/studies.json").json();
const dosages = await FileAttachment("data/dosages.csv").csv();
const dosagesSummary = await FileAttachment("data/dosages-summary.csv").csv();
const prisma = await FileAttachment("data/prisma.json").json();
```

## Per-study consensus scoring

The full scoring output for each of the **${studies.length}** papers in the corpus.

```js
function blobLink(label, dataObj, filename, mime = "application/json") {
  const blob = new Blob([typeof dataObj === "string" ? dataObj : JSON.stringify(dataObj, null, 2)], {type: mime});
  const url = URL.createObjectURL(blob);
  return html`<a href="${url}" download="${filename}" class="kbd">⬇ ${label}</a>`;
}
const dosagesText = await FileAttachment("data/dosages.csv").text();
const summaryText = await FileAttachment("data/dosages-summary.csv").text();
display(html`<ul>
  <li>${blobLink(`studies.json (${studies.length} studies)`, studies, "studies.json")} — array of study objects with B/E/D scores, per-assay items with evidence quotes, housing & experimental conditions</li>
  <li>${blobLink(`dosages.csv (${dosages.length} rows)`, dosagesText, "dosages.csv", "text/csv")} — long-form, one row per dose mention. Columns: <code>stem, snippet_id, compound, class, dose, route, administered, context</code></li>
  <li>${blobLink(`dosages_summary.csv (${dosagesSummary.length} rows)`, summaryText, "dosages_summary.csv", "text/csv")} — paper × compound rollup</li>
  <li>${blobLink("prisma.json", prisma, "prisma.json")} — PRISMA-flow numbers per pipeline stage</li>
</ul>`);
```

## How to cite

If you use this dataset, please cite both the paper and (when archived to Zenodo) the dataset DOI.

```
Abd El Hay et al. (2026). Behavioural complexity in psychedelic rodent studies:
a systematic-review companion dataset.
Zenodo. https://doi.org/10.5281/zenodo.XXXXXXX
```

## License

The dataset (extracted scores, doses, conditions) is licensed CC-BY-4.0. The source PDFs remain the copyright of their respective publishers.

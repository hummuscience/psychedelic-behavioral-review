---
title: Assays
toc: false
---

```js
const allStudies = await FileAttachment("data/studies.json").json();
const assayCatalog = await FileAttachment("data/assay_catalog.json").json();
import * as Plot from "npm:@observablehq/plot";
import {mountFilters, ASSAY_CATEGORY_ORDER} from "./components/filters.js";
```

```js
const _filters = mountFilters(allStudies, {Inputs, html, Generators}, assayCatalog);
display(_filters.node);
```

```js
const studies = _filters.filtered;
```

# Assays

Each study may measure one or more behavioural assays. Counts below reflect papers in the **filtered** set; totals can exceed the study count because a single paper may run multiple assays.

```js
// Recompute assay counts from the filtered set
const catCounts = new Map();
const canonCounts = new Map();
const canonToCat = new Map();
const canonToStudies = new Map();

for (const s of studies) {
  const seen = new Set();
  for (const a of (s.assays || [])) {
    canonToCat.set(a.canonical, a.category);
    if (!seen.has(a.canonical)) {
      seen.add(a.canonical);
      canonCounts.set(a.canonical, (canonCounts.get(a.canonical) || 0) + 1);
      if (!canonToStudies.has(a.canonical)) canonToStudies.set(a.canonical, []);
      canonToStudies.get(a.canonical).push(s);
    }
    const catSeen = new Set();
    if (!catSeen.has(a.category)) {
      catSeen.add(a.category);
      catCounts.set(a.category, (catCounts.get(a.category) || 0) + 1);
    }
  }
}

const CATEGORY_ORDER = [
  "Psychedelic response","Anxiety","Depression / anhedonia","Locomotor / motor",
  "Cognition / memory","Social behaviour","Addiction / substance use","Pain",
  "Sensorimotor","Physiological","Miscellaneous",
];

const CATEGORY_PALETTE = {
  "Psychedelic response":    "#7B2FBE",
  "Anxiety":                 "#E6550D",
  "Depression / anhedonia":  "#3a7acf",
  "Locomotor / motor":       "#1B9E77",
  "Cognition / memory":      "#D95F02",
  "Social behaviour":        "#E7298A",
  "Addiction / substance use":"#66A61E",
  "Pain":                    "#A6761D",
  "Sensorimotor":            "#7570B3",
  "Physiological":           "#17BECF",
  "Miscellaneous":           "#999999",
};

// Flat assay rows sorted by category order then count desc
const assayRows = [];
for (const cat of CATEGORY_ORDER) {
  const rows = [...canonCounts.entries()]
    .filter(([k]) => canonToCat.get(k) === cat)
    .sort((a, b) => b[1] - a[1])
    .map(([canonical, n]) => ({canonical, category: cat, n}));
  assayRows.push(...rows);
}

// Category summary rows
const catRows = CATEGORY_ORDER
  .filter(c => catCounts.has(c))
  .map(c => ({category: c, n: catCounts.get(c) || 0}));
```

## By category

```js
display(Plot.plot({
  height: 320,
  marginLeft: 200,
  marginRight: 40,
  marginBottom: 40,
  x: {label: "papers", grid: true},
  y: {label: null},
  color: {domain: CATEGORY_ORDER, range: CATEGORY_ORDER.map(c => CATEGORY_PALETTE[c] || "#999")},
  marks: [
    Plot.barX(catRows, {
      x: "n", y: "category",
      fill: "category",
      sort: {y: "-x"},
      title: d => `${d.category}: ${d.n} papers`,
    }),
    Plot.text(catRows, {
      x: "n", y: "category",
      text: d => d.n,
      dx: 6, dy: 0,
      textAnchor: "start",
      fontSize: 11,
      fill: "var(--theme-foreground-muted)",
    }),
    Plot.ruleX([0]),
  ],
}));
```

## Top assays

```js
// top 30 by paper count
const top = assayRows.slice(0, 30);
display(Plot.plot({
  height: 580,
  marginLeft: 240,
  marginRight: 40,
  marginBottom: 40,
  x: {label: "papers", grid: true},
  y: {label: null},
  color: {domain: CATEGORY_ORDER, range: CATEGORY_ORDER.map(c => CATEGORY_PALETTE[c] || "#999")},
  marks: [
    Plot.barX(top, {
      x: "n", y: "canonical",
      fill: "category",
      sort: {y: "-x"},
      title: d => `${d.canonical} [${d.category}]: ${d.n} papers`,
    }),
    Plot.text(top, {
      x: "n", y: "canonical",
      text: d => d.n,
      dx: 6, dy: 0,
      textAnchor: "start",
      fontSize: 10,
      fill: "var(--theme-foreground-muted)",
    }),
    Plot.ruleX([0]),
  ],
}));
```

## Full assay table

```js
// Interactive table: click a row to see which studies used that assay
const selectedAssay = Mutable(null);
const setSelectedAssay = v => { selectedAssay.value = v; };
```

<div class="assay-split" style="display:flex;gap:24px;align-items:flex-start">
<div style="flex:1;min-width:0">

```js
{
  const tbl = Inputs.table(assayRows, {
    columns: ["canonical", "category", "n"],
    header: {canonical: "Assay", category: "Category", n: "Papers"},
    rows: 20,
    sort: "n",
    reverse: true,
  });
  tbl.addEventListener("input", () => {
    const sel = tbl.value;
    if (sel && sel.length > 0) setSelectedAssay(sel[0]);
  });
  display(tbl);
}
```

</div>
<div style="width:300px;flex-shrink:0">

```js
{
  if (!selectedAssay) {
    display(html`<div style="color:var(--theme-foreground-muted);font-size:0.85rem;padding:12px 0">
      <b>Select a row</b> in the table to list studies that used that assay.
    </div>`);
  } else {
    const papers = canonToStudies.get(selectedAssay.canonical) || [];
    const sorted = [...papers].sort((a, b) =>
      (a.study_id || "").localeCompare(b.study_id || ""));
    display(html`<div>
      <div style="font-weight:600;margin-bottom:6px">${selectedAssay.canonical}</div>
      <div style="font-size:0.8rem;color:var(--theme-foreground-muted);margin-bottom:10px">
        ${selectedAssay.category} · ${papers.length} papers
      </div>
      <div style="font-size:0.85rem;line-height:1.8">
        ${sorted.map(s => html`<a href="study/${String(s._stem).toLowerCase().replace(/[^a-z0-9]/g, "")}" style="margin-right:4px;display:inline-block">${s.study_id}</a>`)}
      </div>
    </div>`);
  }
}
```

</div>
</div>

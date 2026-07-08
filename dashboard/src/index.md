---
title: Studies over time
toc: false
---

<div class="pub-banner">
  This is the accompanying dashboard for the publication
  <a href="https://doi.org/10.64898/2026.01.14.699469" target="_blank" rel="noopener"><em>Animal Models in Psychedelic Research — Tripping over Translation</em></a> (bioRxiv, 2026).
</div>

```js
const studies = await FileAttachment("data/studies.json").json();
const prisma = await FileAttachment("data/prisma.json").json();
const assayCatalog = await FileAttachment("data/assay_catalog.json").json();
import {BUCKET_ORDER, compoundsOf} from "./components/dose-utils.js";
import {mountFilters} from "./components/filters.js";
import * as Plot from "npm:@observablehq/plot";
```

```js
const _filters = mountFilters(studies, {Inputs, html, Generators}, assayCatalog);
display(_filters.node);
```

```js
const filteredStudies = _filters.filtered;
```

```js
const yearOf = s => +(s.study_id || "").match(/(\d{4})/)?.[1];
function normalizeSpecies(raw) {
  if (raw == null) return "not reported";
  const s = String(raw).toLowerCase().trim();
  if (!s || s === "none" || s === "null" || s === "n/a") return "not reported";
  const hasMouse = /\bmouse|mice\b/.test(s);
  const hasRat = /\brat\b/.test(s);
  if (hasMouse && hasRat) return "mouse and rat";
  if (hasMouse) return "mouse";
  if (hasRat) return "rat";
  return "other";
}
// `compoundsOf` is imported from dose-utils.js — it uses the canonical alias map
// (psilocin → Psilocybin, noribogaine → Ibogaine, etc.).
const COMPOUND_PALETTE = {
  "Psilocybin":"#7B2FBE","LSD":"#E6550D","DOI":"#D95F02","DMT":"#3a7acf",
  "5-MeO-DMT":"#1B9E77","NBOMe/NBOH":"#E7298A","Ibogaine":"#66A61E","Mescaline":"#A6761D",
  "(other)":"#999",
};
const SPECIES_PALETTE = {"mouse":"#1B9E77","rat":"#D95F02","mouse and rat":"#7570B3","other":"#666","not reported":"#bdbdbd"};
const SEX_PALETTE = {"male only":"#3a7acf","female only":"#E7298A","both sexes":"#7B2FBE","not reported":"#bdbdbd"};
const ASSAY_CATEGORY_PALETTE = {
  "Psychedelic response":"#7B2FBE","Anxiety":"#E6550D","Depression / anhedonia":"#3a7acf",
  "Locomotor / motor":"#1B9E77","Cognition / memory":"#D95F02","Social behaviour":"#E7298A",
  "Addiction / substance use":"#66A61E","Pain":"#A6761D","Sensorimotor":"#7570B3",
  "Physiological":"#17BECF","Miscellaneous":"#999999",
};
const ASSAY_COLORS = [
  "#7B2FBE","#E6550D","#3a7acf","#1B9E77","#D95F02","#E7298A","#66A61E","#A6761D","#7570B3","#17BECF",
  "#FFBB78","#7B7B7B","#F8766D","#A580FF","#61A0A5","#C77CFF","#AE5629","#B2B500","#00C0C0","#F0E5D5",
  "#C5A8D6","#FFB366","#88B0B0","#FFD4A8","#00D2D3","#D4A5D4","#FFB8C8",
];
const ASSAY_CATEGORY_ORDER = [
  "Psychedelic response","Anxiety","Depression / anhedonia","Locomotor / motor",
  "Cognition / memory","Social behaviour","Addiction / substance use","Pain",
  "Sensorimotor","Physiological","Miscellaneous",
];
function normalizeSex(raw) {
  const s = String(raw ?? "").toLowerCase().trim();
  if (!s) return "not reported";
  if (s.includes("both")) return "both sexes";
  if (s.includes("female")) return "female only";
  if (s.includes("male")) return "male only";
  return "not reported";
}
const allYears = Array.from(new Set(studies.map(yearOf).filter(Boolean))).sort();
const yearMin = Math.min(...allYears);
const yearMax = Math.max(...allYears);
```

# Studies over time

**${studies.length}** included studies, spanning ${yearMax - yearMin + 1} years (${yearMin}–${yearMax}). Each bar is the count of papers published in that year. Pick a colour grouping below to break down by compound, species, or rodent + drug combination — papers using multiple compounds count once per compound (so totals can exceed paper counts when colouring by compound). Full screening numbers are on the [Pipeline / PRISMA](/pipeline) page.

<div class="summary-pills">
  <div class="pill"><b>${studies.length}</b><span>included studies</span></div>
  <div class="pill"><b>${yearMax - yearMin + 1}</b><span>year span (${yearMin}–${yearMax})</span></div>
</div>

## Controls

```js
const colorBy = view(Inputs.radio(["None", "Compound", "Assay Category", "Assay", "Species", "Sex"], {label: "Colour by", value: "Compound"}));
```

```js
const barMode = view(Inputs.radio(["Stacked", "Proportion"], {label: "Bar mode", value: "Stacked"}));
```

```js
// Precompute one bin per (year, group) from the filtered subset, so each rendered
// rect can carry its identifying data in __data__ (and we can list the studies on click).
function binsForColor(mode) {
  const map = new Map();
  for (const s of filteredStudies) {
    const y = yearOf(s);
    if (!y) continue;
    let groups;
    if (mode === "None") groups = ["studies"];
    else if (mode === "Species") groups = [normalizeSpecies(s.species)];
    else if (mode === "Sex") groups = [normalizeSex(s.sex)];
    else if (mode === "Assay Category") {
      const seen = new Set();
      groups = [];
      for (const a of (s.assays || [])) {
        if (a.category && !seen.has(a.category)) {
          seen.add(a.category);
          groups.push(a.category);
        }
      }
      if (groups.length === 0) groups = ["(no assays)"];
    } else if (mode === "Assay") {
      const seen = new Set();
      groups = [];
      for (const a of (s.assays || [])) {
        if (a.canonical && !seen.has(a.canonical)) {
          seen.add(a.canonical);
          groups.push(a.canonical);
        }
      }
      if (groups.length === 0) groups = ["(no assays)"];
    } else {
      groups = compoundsOf(s);
    }
    for (const g of groups) {
      const k = `${y}|${g}`;
      if (!map.has(k)) map.set(k, {year: y, group: g, n: 0, studies: []});
      const bin = map.get(k);
      bin.n += 1;
      bin.studies.push({stem: s._stem, study_id: s.study_id});
    }
  }
  return [...map.values()];
}
const bins = binsForColor(colorBy);

// For "Assay" mode: group assays not in the top 25 as "(other)"
let finalBins = bins;
if (colorBy === "Assay") {
  const assayBinTotal = new Map();
  for (const b of bins) {
    if (b.group !== "(no assays)") assayBinTotal.set(b.group, (assayBinTotal.get(b.group) ?? 0) + b.n);
  }
  const sortedByTotal = [...assayBinTotal.entries()].sort((a, b) => b[1] - a[1]);
  const topN = new Set(sortedByTotal.slice(0, 25).map(e => e[0]));
  const remapped = new Map();
  for (const b of bins) {
    const g = topN.has(b.group) ? b.group : "(other)";
    const k = `${b.year}|${g}`;
    if (!remapped.has(k)) remapped.set(k, {year: b.year, group: g, n: 0, studies: []});
    const bin = remapped.get(k);
    bin.n += b.n;
    bin.studies.push(...b.studies);
  }
  finalBins = [...remapped.values()];
}

let domain, range;
if (colorBy === "Species") {
  domain = ["mouse","rat","mouse and rat","other","not reported"].filter(k => finalBins.some(b => b.group === k));
  range = domain.map(d => SPECIES_PALETTE[d] || "#999");
} else if (colorBy === "Sex") {
  // Always show all four sex buckets in the legend, even ones with zero studies.
  domain = ["male only","female only","both sexes","not reported"];
  range = domain.map(d => SEX_PALETTE[d] || "#999");
} else if (colorBy === "Compound") {
  domain = [...BUCKET_ORDER, "(other)"].filter(k => finalBins.some(b => b.group === k));
  range = domain.map(d => COMPOUND_PALETTE[d] || "#999");
} else if (colorBy === "Assay Category") {
  domain = ASSAY_CATEGORY_ORDER.filter(k => finalBins.some(b => b.group === k));
  if (finalBins.some(b => b.group === "(no assays)")) domain.push("(no assays)");
  range = domain.map(d => ASSAY_CATEGORY_PALETTE[d] || "#999");
} else if (colorBy === "Assay") {
  const assayBinTotal = new Map();
  for (const b of finalBins) {
    if (b.group !== "(no assays)") assayBinTotal.set(b.group, (assayBinTotal.get(b.group) ?? 0) + b.n);
  }
  const sortedByTotal = [...assayBinTotal.entries()].sort((a, b) => b[1] - a[1]);
  const topNSet = new Set(sortedByTotal.slice(0, 25).map(e => e[0]));
  const orderedGroups = sortedByTotal.slice(0, 25).map(e => e[0]);
  if (finalBins.some(b => b.group === "(no assays)")) orderedGroups.push("(no assays)");
  else if (!topNSet.has("(other)")) {
    for (const b of finalBins) {
      if (b.group === "(other)") { orderedGroups.push("(other)"); break; }
    }
  }
  domain = orderedGroups;
  range = domain.map(d => {
    if (d === "(no assays)" || d === "(other)") return "#999";
    const idx = sortedByTotal.findIndex(e => e[0] === d);
    return ASSAY_COLORS[idx % ASSAY_COLORS.length];
  });
} else {
  domain = ["studies"];
  range = ["#7B2FBE"];
}
const groupRank = new Map(domain.map((d, i) => [d, i]));
finalBins.sort((a, b) => (groupRank.get(a.group) ?? 999) - (groupRank.get(b.group) ?? 999));
const offset = barMode === "Proportion" ? "normalize" : null;
```

```js
const selected = Mutable(null);
const setSel = v => { selected.value = v; };
```

<div class="viewer-shell">
  <div class="viewer-left">${chartEl}</div>
  <div class="viewer-right">${renderStudyList(selected)}</div>
</div>

```js
const chartEl = (() => {
  const el = Plot.plot({
    height: 420,
    marginLeft: 60, marginRight: 24, marginBottom: 44, marginTop: 16,
    x: {
      label: "Year of publication",
      tickFormat: d => `${d}`,
      domain: Array.from({length: yearMax - yearMin + 1}, (_, i) => yearMin + i),
    },
    y: {
      label: barMode === "Proportion" ? "share of studies" : "studies",
      grid: true,
      percent: barMode === "Proportion",
    },
    color: {legend: true, domain, range},
    marks: [
      Plot.barY(finalBins, {
        x: "year", y: "n", fill: "group", offset,
        title: d => `${d.year} · ${d.group}: ${d.n} ${d.n === 1 ? "study" : "studies"}`,
      }),
      Plot.ruleY([0]),
    ],
  });
  el.style.cursor = "pointer";
  el.addEventListener("click", (ev) => {
    const r = ev.target.closest("rect[fill]");
    if (!r) return;
    // Plot stamps __data__ as the row index into `bins`, not the bin itself.
    const idx = typeof r.__data__ === "number" ? r.__data__ : null;
    const bin = idx != null ? finalBins[idx] : null;
    if (bin && bin.year != null && bin.group != null) {
      setSel({year: bin.year, group: bin.group, studies: bin.studies, n: bin.n});
    }
  });
  return el;
})();
```

```js
function renderStudyList(sel) {
  if (!sel) {
    return html`<div class="placeholder">
      <div>
        <p><b>Click a coloured segment</b> in the chart to list the studies for that year + group.</p>
      </div>
    </div>`;
  }
  const studies = [...sel.studies].sort((a, b) => a.study_id.localeCompare(b.study_id));
  return html`<div class="detail-body">
    <div class="detail-header">
      <h2>${sel.year} · <span class="tag psychedelic">${sel.group}</span></h2>
      <p style="font-size:0.85rem;color:var(--theme-foreground-muted);">${sel.n} ${sel.n === 1 ? "study" : "studies"}</p>
    </div>
    <div style="font-size:0.92rem;line-height:1.7;">
      ${studies.map(s => html`<a href="study/${String(s.stem).toLowerCase().replace(/[^a-z0-9]/g, "")}" class="tag muted study-link">${s.study_id}</a> `)}
    </div>
  </div>`;
}
```

```js
// Cumulative line so the long-term shape stays visible regardless of colour
{
  const counts = new Map();
  for (const s of filteredStudies) {
    const y = yearOf(s);
    if (!y) continue;
    counts.set(y, (counts.get(y) ?? 0) + 1);
  }
  const sorted = [...counts.entries()].sort((a,b) => a[0] - b[0]);
  let acc = 0;
  const cum = sorted.map(([year, n]) => { acc += n; return {year, cumulative: acc, n}; });
  display(Plot.plot({
    height: 220,
    marginLeft: 60, marginRight: 24, marginBottom: 44, marginTop: 16,
    x: {label: "Year", tickFormat: d => `${d}`},
    y: {label: "cumulative studies", grid: true},
    marks: [
      Plot.areaY(cum, {x: "year", y: "cumulative", fill: "var(--psy-purple)", fillOpacity: 0.18}),
      Plot.line(cum, {x: "year", y: "cumulative", stroke: "var(--psy-purple)", strokeWidth: 2}),
      Plot.dot(cum, {x: "year", y: "cumulative", fill: "var(--psy-purple)", r: 3, title: d => `${d.year}: +${d.n} (${d.cumulative} total)`}),
    ],
  }));
}
```

## Per-year breakdown

```js
{
  // Build a flat table: year | total | per-compound counts
  const COMPOUNDS = [...BUCKET_ORDER, "(other)"];
  const totals = new Map();
  const perComp = new Map();
  for (const s of studies) {
    const y = yearOf(s);
    if (!y) continue;
    totals.set(y, (totals.get(y) ?? 0) + 1);
    for (const c of compoundsOf(s)) {
      const k = `${y}|${c}`;
      perComp.set(k, (perComp.get(k) ?? 0) + 1);
    }
  }
  const years = [...totals.keys()].sort((a, b) => b - a);
  const rows = years.map(y => {
    const row = {year: y, total: totals.get(y)};
    for (const c of COMPOUNDS) row[c] = perComp.get(`${y}|${c}`) ?? 0;
    return row;
  });
  display(Inputs.table(rows, {
    rows: 16,
    columns: ["year", "total", ...COMPOUNDS.filter(c => rows.some(r => r[c] > 0))],
    format: {year: d => d == null ? "" : String(d)},
  }));
}
```

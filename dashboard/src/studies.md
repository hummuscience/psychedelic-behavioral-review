---
title: Studies
toc: false
---

# Studies

```js
const studies = await FileAttachment("data/studies.json").json();
```

Sortable, filterable table of all ${studies.length} studies in the corpus. Click a row to open the per-study detail page.

```js
const yearOf = s => +(s.study_id || "").match(/(\d{4})/)?.[1];
const allYears = Array.from(new Set(studies.map(yearOf).filter(Boolean))).sort();

// Normalise species into clean buckets: "mouse", "rat", "mouse and rat", "other"
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

const SPECIES_ORDER = ["mouse", "rat", "mouse and rat", "other", "not reported"];
const allSpecies = SPECIES_ORDER.filter(sp =>
  studies.some(s => normalizeSpecies(s.species) === sp)
);

// Build searchable rows
const rows = studies.map(s => {
  // Sample-size aggregates across this study's assays
  const totals = (s.assays || []).map(a => a.sample_size?.n_total).filter(v => typeof v === "number");
  const mins = (s.assays || []).map(a => a.sample_size?.n_per_group_min).filter(v => typeof v === "number");
  const max = arr => arr.length ? Math.max(...arr) : null;
  const min = arr => arr.length ? Math.min(...arr) : null;
  return {
    study: s.study_id,
    year: yearOf(s),
    species: normalizeSpecies(s.species),
    species_raw: s.species ?? "",
    strain: s.strain,
    psychedelic: s.psychedelic,
    n_assays: (s.assays || []).length,
    n_total_max: max(totals),     // peak experiment size
    n_per_group_min: min(mins),   // worst-case cell size (statistical-power red flag if <6)
    B: s.study_level_scores?.behavioural_complexity_max?.toFixed(1),
    E: s.study_level_scores?.environmental_complexity_max?.toFixed(1),
    D: s.study_level_scores?.recording_duration_max?.toFixed(1),
    low_conf: s.low_confidence_count ?? 0,
    doi: s.doi,
    _stem: s._stem,
  };
});
```

```js
const search = view(Inputs.search(rows, {placeholder: "Search by author, year, compound, DOI…", columns: ["study","psychedelic","doi","strain"]}));
```

```js
const speciesFilter = view(Inputs.checkbox(allSpecies, {label: "Species", value: allSpecies, sort: true}));
```

```js
const yearRange = view(Inputs.range([Math.min(...allYears), Math.max(...allYears)], {step: 1, label: "Year ≥", value: Math.min(...allYears)}));
```

```js
const filtered = search.filter(r =>
  speciesFilter.includes(r.species) &&
  (r.year ?? 9999) >= yearRange
);
```

**${filtered.length}** of ${rows.length} studies match your filters.

```js
display(Inputs.table(filtered, {
  rows: 30,
  sort: "year",
  reverse: true,
  columns: ["study","year","species","strain","psychedelic","n_assays","n_total_max","n_per_group_min","B","E","D","low_conf","doi"],
  header: {
    n_total_max: "max n (study)",
    n_per_group_min: "min n / group",
  },
  format: {
    study: d => html`<a href="study/${d.toLowerCase()}">${d}</a>`,
    n_total_max: d => d == null ? "" : d,
    n_per_group_min: d => d == null ? "" : (
      d < 6 ? html`<span style="color:#c0392b;font-weight:600;">${d}</span>` : `${d}`
    ),
    doi: d => d ? html`<a href="https://doi.org/${d}" target="_blank">${d.slice(0,40)}…</a>` : "",
  }
}));
```

```js
// Download filtered subset
const blob = new Blob([
  ["study","year","species","strain","psychedelic","n_assays","n_total_max","n_per_group_min","B","E","D","low_conf","doi"].join(",") + "\n" +
  filtered.map(r => [r.study,r.year,r.species,r.strain,'"'+(r.psychedelic||"")+'"',r.n_assays,r.n_total_max ?? "",r.n_per_group_min ?? "",r.B,r.E,r.D,r.low_conf,r.doi].join(",")).join("\n")
], {type: "text/csv"});
const url = URL.createObjectURL(blob);
display(html`<a href="${url}" download="studies-filtered.csv" class="kbd">⬇ download ${filtered.length} rows as CSV</a>`);
```

## Sample size distribution

```js
import * as Plot from "npm:@observablehq/plot";

{
  // Pull per-assay sample sizes from the filtered set of studies. Each assay is
  // one point — a study with 4 assays contributes 4 records.
  const filteredStems = new Set(filtered.map(r => r._stem));
  const assayPoints = [];
  for (const s of studies) {
    if (!filteredStems.has(s._stem)) continue;
    for (const a of (s.assays || [])) {
      const ss = a.sample_size || {};
      if (typeof ss.n_total === "number") {
        assayPoints.push({
          stem: s._stem, study_id: s.study_id, assay: a.assay_name,
          n_total: ss.n_total, n_per_group_min: ss.n_per_group_min,
        });
      }
    }
  }

  const med = arr => {
    if (!arr.length) return null;
    const xs = [...arr].sort((a, b) => a - b);
    const mid = Math.floor(xs.length / 2);
    return xs.length % 2 ? xs[mid] : (xs[mid - 1] + xs[mid]) / 2;
  };
  const totals = assayPoints.map(p => p.n_total);
  const mins = assayPoints.map(p => p.n_per_group_min).filter(v => typeof v === "number");
  const underpowered = mins.filter(v => v < 6).length;

  display(html`<div class="summary-pills">
    <div class="pill"><b>${assayPoints.length}</b><span>assays with n reported</span></div>
    <div class="pill"><b>${med(totals) ?? "—"}</b><span>median total n</span></div>
    <div class="pill"><b>${med(mins) ?? "—"}</b><span>median n / group</span></div>
    <div class="pill"><b>${underpowered}</b><span>assays with &lt; 6 / group</span></div>
  </div>`);

  display(html`<div style="display:flex;gap:24px;flex-wrap:wrap;">${
    [
      Plot.plot({
        title: "Total n per assay",
        width: 460, height: 220,
        marginLeft: 50, marginBottom: 38,
        x: {label: "n (total animals in assay)", type: "log", grid: true},
        y: {label: "assays", grid: true},
        marks: [
          Plot.rectY(assayPoints, Plot.binX({y: "count"}, {x: "n_total", thresholds: 24, fill: "var(--psy-purple)", fillOpacity: 0.85})),
          Plot.ruleY([0]),
        ],
      }),
      Plot.plot({
        title: "Min n per group (smallest cell)",
        width: 460, height: 220,
        marginLeft: 50, marginBottom: 38,
        x: {label: "n per group", grid: true, domain: [0, Math.max(20, Math.max(...mins, 0))]},
        y: {label: "assays", grid: true},
        marks: [
          Plot.rectY(assayPoints.filter(p => typeof p.n_per_group_min === "number"),
            Plot.binX({y: "count"}, {x: "n_per_group_min", thresholds: 20, fill: d => d.n_per_group_min < 6 ? "#c0392b" : "var(--psy-purple)", fillOpacity: 0.85})),
          Plot.ruleX([6], {stroke: "#c0392b", strokeDasharray: "4 3"}),
          Plot.ruleY([0]),
        ],
      }),
    ].map(el => html`<div>${el}</div>`)
  }</div>`);
}
```

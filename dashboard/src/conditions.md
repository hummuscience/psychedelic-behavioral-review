---
title: Conditions
toc: false
---

<style>
  :root { --observablehq-max-width: 1600px; }
  #observablehq-main { max-width: none !important; }
</style>

# Housing & experimental conditions

```js
const allStudies = await FileAttachment("data/studies.json").json();
const assayCatalog = await FileAttachment("data/assay_catalog.json").json();
import * as Plot from "npm:@observablehq/plot";
import {mountFilters} from "./components/filters.js";
```

```js
const _filters = mountFilters(allStudies, {Inputs, html, Generators}, assayCatalog);
display(_filters.node);
```

```js
const studies = _filters.filtered;
```

```js
const HOUSING_FIELDS = ['handling','group_housing','day_night_flipped','enrichment_housing'];
const EXP_COND_FIELDS = ['setup_habituation','setup_restrain'];
const FIELD_LABELS = {
  handling: 'handling',
  group_housing: 'group housing',
  day_night_flipped: 'reverse light cycle',
  enrichment_housing: 'home-cage enrichment',
  setup_habituation: 'setup habituation',
  setup_restrain: 'setup restrain (during recording)',
};
const LABEL_TO_FIELD = Object.fromEntries(Object.entries(FIELD_LABELS).map(([k,v]) => [v,k]));

function modal(arr) {
  if (!arr.length) return null;
  const c = {}; for (const v of arr) c[v] = (c[v]||0) + 1;
  return Object.entries(c).sort((a,b) => b[1]-a[1])[0][0];
}
function valueFor(s, field) {
  if (HOUSING_FIELDS.includes(field)) return s.housing_conditions?.[field]?.value ?? null;
  const vs = (s.assays || []).map(a => a.experimental_conditions?.[field]?.value).filter(Boolean);
  return vs.length ? modal(vs) : null;
}

const fields = HOUSING_FIELDS.concat(EXP_COND_FIELDS);
```

```js
const VALUE_ORDER = ["yes", "no", "not_reported"];
const valueRank = v => { const i = VALUE_ORDER.indexOf(v); return i < 0 ? VALUE_ORDER.length : i; };

const data = [];
for (const f of fields) {
  for (const s of studies) {
    data.push({field: FIELD_LABELS[f], rawField: f, value: valueFor(s, f) ?? 'not_reported', stem: s._stem, study_id: s.study_id});
  }
}
// Sort so each field's stack lays down yes → no → not_reported left to right.
data.sort((a, b) => valueRank(a.value) - valueRank(b.value));
```

```js
// Reactive selection
const selected = Mutable(null); // {field, value} or null
const setSel = v => { selected.value = v; };
```

<div class="viewer-shell">
  <div class="viewer-left">${plotEl}</div>
  <div class="viewer-right">${renderStudyList(selected, data)}</div>
</div>

```js
const plotEl = (() => {
  const el = Plot.plot({
    marginLeft: 220, marginRight: 24, marginTop: 24, marginBottom: 40,
    height: 360,
    x: {label: "studies", grid: true},
    y: {label: null, domain: fields.map(f => FIELD_LABELS[f])},
    color: {legend: true, type: "categorical",
      domain: ["yes","no","not_reported"],
      range: ["#2ca02c","#9e9e9e","#bdbdbd"]},
    marks: [
      Plot.barX(data, Plot.groupY(
        {x: "count"},
        {y: "field", fill: "value", inset: 0.5, tip: true,
         channels: {field: "field", value: "value"}}
      )),
    ],
  });
  // Plot's barX renders <rect> — wire a delegated click handler
  el.addEventListener("click", (ev) => {
    const r = ev.target.closest("rect[fill]");
    if (!r) return;
    const fill = r.getAttribute("fill");
    const COLOR_TO_VAL = {"#2ca02c":"yes","#9e9e9e":"no","#bdbdbd":"not_reported"};
    const value = COLOR_TO_VAL[fill?.toLowerCase()];
    if (!value) return;
    // Determine which row by Y position
    const cy = r.getBoundingClientRect();
    const elBox = el.getBoundingClientRect();
    const yMid = cy.top + cy.height/2 - elBox.top;
    // Reverse-engineer the band by checking <g aria-label="y-axis tick label">
    // Simpler: use the "field" channel embedded by Plot via __data__
    const datum = r.__data__;
    let field = null;
    if (datum && datum.field) field = datum.field;
    if (!field) {
      // fallback: find nearest y-axis label
      const yLabels = el.querySelectorAll('g[aria-label="y-axis tick label"] text');
      let best = null, bestD = Infinity;
      for (const t of yLabels) {
        const tb = t.getBoundingClientRect();
        const d = Math.abs(tb.top + tb.height/2 - elBox.top - yMid);
        if (d < bestD) { bestD = d; best = t.textContent; }
      }
      field = best;
    }
    if (field) setSel({field, value});
  });
  // Visual cursor cue
  el.style.cursor = "pointer";
  return el;
})();
```

```js
function renderStudyList(sel, data) {
  if (!sel) {
    return html`<div class="placeholder">
      <div>
        <p><b>Click a coloured segment</b> to list the studies in that bucket.</p>
      </div>
    </div>`;
  }
  const matches = data
    .filter(d => d.field === sel.field && d.value === sel.value)
    .sort((a, b) => a.study_id.localeCompare(b.study_id));
  return html`<div class="detail-body">
    <div class="detail-header">
      <h2>${sel.field} = <span class="tag value-${sel.value.replace(/[^a-z]/g,"")}">${sel.value}</span></h2>
      <p style="font-size:0.85rem;color:var(--theme-foreground-muted);">${matches.length} ${matches.length === 1 ? "study" : "studies"}</p>
    </div>
    <div style="font-size:0.92rem;line-height:1.7;">
      ${matches.map(m => html`<a href="/study/${m.stem}" class="tag muted study-link">${m.study_id}</a> `)}
    </div>
  </div>`;
}
```

**Where to find the rest:** *application_type* lives in the **Application type** tab (its values are categorical routes, not binary), and *food_restriction* + *water_restriction* live in the **Restrictions** tab.

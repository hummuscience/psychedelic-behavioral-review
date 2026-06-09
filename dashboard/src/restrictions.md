---
title: Restrictions
toc: false
---

# Food & water restriction

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
function modal(arr) {
  if (!arr.length) return null;
  const c = {}; for (const v of arr) c[v] = (c[v]||0) + 1;
  return Object.entries(c).sort((a,b) => b[1]-a[1])[0][0];
}
function counts(field) {
  const c = {};
  for (const s of studies) {
    const vs = (s.assays || []).map(a => a.experimental_conditions?.[field]?.value).filter(Boolean);
    const v = vs.length ? modal(vs) : 'unknown';
    c[v] = (c[v] || 0) + 1;
  }
  return Object.entries(c).map(([value, n]) => ({value, n}));
}
const food = counts("food_restriction");
const water = counts("water_restriction");
const totalFood = food.reduce((s, d) => s + d.n, 0);
const totalWater = water.reduce((s, d) => s + d.n, 0);

const VALUE_ORDER = ["during","before","no","not reported","yes","unknown"];
const COLORS = {during:"#d32f2f", before:"#ff9800", no:"#9e9e9e", "not reported":"#bdbdbd", yes:"#2ca02c", unknown:"#7986cb"};
const prettify = v => String(v).replace(/_/g, " ");
const long = [
  ...food.map(d => ({field: "food restriction", value: prettify(d.value), n: d.n})),
  ...water.map(d => ({field: "water restriction", value: prettify(d.value), n: d.n})),
];
const foodPretty = food.map(d => ({...d, value: prettify(d.value)}));
const waterPretty = water.map(d => ({...d, value: prettify(d.value)}));
```

Per-paper modal value across the paper's assays. **`during`** = food/water unavailable during recording; **`before`** = explicit fasting before the test; **`no`** = ad libitum throughout; **`not reported`** = paper silent.

```js
display(Plot.plot({
  marginLeft: 130, marginRight: 24, marginTop: 24, marginBottom: 40,
  height: 220,
  x: {label: "studies", grid: true},
  y: {label: null, domain: ["food restriction", "water restriction"]},
  color: {
    legend: true,
    domain: VALUE_ORDER.filter(v => long.some(d => d.value === v)),
    range: VALUE_ORDER.filter(v => long.some(d => d.value === v)).map(v => COLORS[v]),
  },
  marks: [
    Plot.barX(long, {
      y: "field", x: "n", fill: "value", inset: 0.5,
      title: d => `${d.field}: ${d.value} = ${d.n}`,
    }),
  ],
}));
```

## Tabular breakdown

```js
display(html`<table>
  <tr><th>Value</th><th>Food restriction</th><th>Water restriction</th></tr>
  ${VALUE_ORDER.map(v => {
    const f = foodPretty.find(x => x.value === v)?.n ?? 0;
    const w = waterPretty.find(x => x.value === v)?.n ?? 0;
    if (f === 0 && w === 0) return "";
    return html`<tr><td><b>${v}</b></td><td>${f} (${(100*f/totalFood).toFixed(0)}%)</td><td>${w} (${(100*w/totalWater).toFixed(0)}%)</td></tr>`;
  })}
</table>`);
```

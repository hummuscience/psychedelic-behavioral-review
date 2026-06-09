---
title: Application Type
toc: false
---

# Application type

```js
const allStudies = await FileAttachment("data/studies.json").json();
const assayCatalog = await FileAttachment("data/assay_catalog.json").json();
import * as Plot from "npm:@observablehq/plot";
import {mountFilters, yearOf} from "./components/filters.js";
```

```js
const _filters = mountFilters(allStudies, {Inputs, html, Generators}, assayCatalog);
display(_filters.node);
```

```js
const studies = _filters.filtered;
```

```js
// Count each unique route a paper actually uses (no "multiple" aggregation)
const counts = {};
for (const s of studies) {
  const seen = new Set();
  for (const a of (s.assays || [])) {
    const v = a.experimental_conditions?.application_type?.value;
    if (!v) continue;
    for (const part of String(v).split(/[,;\/]/)) {
      const k = part.trim().toLowerCase();
      if (k && k !== 'multiple') seen.add(k);
    }
  }
  for (const k of seen) counts[k] = (counts[k] || 0) + 1;
}
const data = Object.entries(counts).map(([route, n]) => ({route, n})).sort((a,b) => b.n - a.n);
const total = data.reduce((s, d) => s + d.n, 0);
```

```js
const selectedRoute = Mutable(null);
const setSelectedRoute = (v) => { selectedRoute.value = v; };
```

Distribution of administration routes across the **${studies.length}-paper corpus**. Each study counted once per unique route it uses (papers using both i.p. and i.v.c. contribute to both buckets).

${data.length ? html`<b>${total}</b> route-uses across ${studies.length} studies` : ''}

<div class="viewer-shell">
  <div class="viewer-left">${plotEl}</div>
  <div class="viewer-right">${renderDetail(selectedRoute, studies)}</div>
</div>

```js
const plotEl = (() => {
  const chart = Plot.plot({
    height: Math.max(300, data.length * 32 + 60),
    marginLeft: 120,
    marginRight: 80,
    x: {label: "studies →"},
    marks: [
      Plot.barX(data, {
        y: "route", x: "n",
        fill: d => d.route === selectedRoute ? "var(--psy-purple, #7B2FBE)" : "var(--theme-foreground-faint, #bbb)",
        sort: {y: "x", reverse: true},
      }),
      Plot.text(data, {
        y: "route", x: "n",
        text: d => `${d.n} (${(100 * d.n / total).toFixed(0)}%)`,
        dx: 6, textAnchor: "start", fontSize: 11,
      }),
      Plot.ruleX([0]),
    ],
    color: {legend: false},
    style: {cursor: "pointer"},
  });

  chart.addEventListener("click", e => {
    const yscale = chart.scale?.("y");
    if (!yscale) return;
    const svgRect = chart.getBoundingClientRect();
    const yPos = e.clientY - svgRect.top;
    const clicked = yscale.domain.find(route => {
      const y = yscale.apply(route);
      return yPos >= y && yPos < y + yscale.bandwidth;
    });
    if (!clicked) return;
    setSelectedRoute(selectedRoute === clicked ? null : clicked);
  });

  return chart;
})();
```

```js
function renderDetail(route, studies) {
  if (!route) {
    return html`<div class="placeholder">
      <div>
        <p><b>Click a bar</b> to list the studies using that administration route.</p>
      </div>
    </div>`;
  }

  const matching = studies.filter(s =>
    (s.assays || []).some(a => {
      const v = a.experimental_conditions?.application_type?.value;
      if (!v) return false;
      return String(v).split(/[,;\/]/).map(p => p.trim().toLowerCase()).includes(route);
    })
  ).sort((a, b) => (yearOf(b) || 0) - (yearOf(a) || 0));

  return html`<div class="detail-body">
    <div class="detail-header">
      <h2><span class="tag psychedelic">${route}</span></h2>
      <p style="font-size:0.85rem;color:var(--theme-foreground-muted);">
        ${matching.length} ${matching.length === 1 ? "study" : "studies"}
        <span style="margin-left:8px;font-style:italic;">(click bar again to deselect)</span>
      </p>
    </div>
    <div style="line-height:1.8;">
      ${matching.map(s => html`<a href="/study/${s._stem}" class="tag muted">${s.study_id}</a> `)}
    </div>
  </div>`;
}
```

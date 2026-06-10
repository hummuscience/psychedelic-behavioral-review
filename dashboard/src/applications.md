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
// Bucket each study by the route(s) the PSYCHEDELIC was actually administered
// through — i.e. the structured `dosing[].route`, the same field the per-study
// page and the manuscript donut figure use. We deliberately do NOT key off
// per-assay `experimental_conditions.application_type`, because that field also
// carries assays where no psychedelic was given (drug-free control cohorts,
// non-psychedelic intracerebral infusions, etc.), which spuriously dropped
// studies like Kulikova2018 / Dere2015 into the "not_reported" bucket even
// though their psychedelic route is i.p.
//
// Route mapping mirrors plot_application_donut.py: raw v2 codes pass through;
// `other` (always an intracerebral microinjection in this corpus) -> "i.c.";
// `not_reported`/missing is dropped entirely (see weighting below). "multiple"
// (one compound given via several routes, not separable) stays its own bucket.
const DIRECT = new Set(["i.p.", "s.c.", "p.o.", "i.n.", "i.v.", "i.c.v."]);
function routeKey(raw) {
  const v = String(raw || "").trim().toLowerCase();
  if (DIRECT.has(v)) return v;
  if (v === "other") return "i.c.";
  if (v === "multiple") return "multiple";
  return null;  // "" or "not_reported" -> not counted
}

// Each study's distinct routes (excluding not_reported) for reuse below.
function studyRoutes(s) {
  const set = new Set();
  for (const e of (s.dosing || [])) {
    const k = routeKey(e?.route);
    if (k) set.add(k);
  }
  return set;
}

// Fractional weighting: a study contributes a TOTAL weight of 1, split evenly
// across its distinct routes. A study using i.p. + s.c. adds 0.5 to each; one
// route adds 1.0; not_reported entries are excluded from both the share and
// the denominator (a study with only not_reported contributes nothing).
const counts = {};
for (const s of studies) {
  const routes = studyRoutes(s);
  if (routes.size === 0) continue;             // only not_reported / no dosing
  const w = 1 / routes.size;
  for (const k of routes) counts[k] = (counts[k] || 0) + w;
}
const data = Object.entries(counts).map(([route, n]) => ({route, n})).sort((a,b) => b.n - a.n);
const total = data.reduce((s, d) => s + d.n, 0);
```

```js
const selectedRoute = Mutable(null);
const setSelectedRoute = (v) => { selectedRoute.value = v; };
```

Distribution of the routes by which the **psychedelic** was administered across the **${studies.length}-paper corpus**, taken from each study's structured dosing record. Each study contributes a total weight of **1**, split evenly across the distinct routes it used for the psychedelic — so a paper giving the drug both i.p. and s.c. adds 0.5 to each bar. Routes used only for non-psychedelic agents, and `not reported` entries, are excluded (they neither get a share nor dilute the others).

${data.length ? html`<b>${total.toFixed(1)}</b> total weight across ${studies.length} studies (each study sums to 1)` : ''}

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
    x: {label: "weighted studies →"},
    y: {tickFormat: d => String(d).replace(/_/g, " ")},
    marks: [
      Plot.barX(data, {
        y: "route", x: "n",
        fill: d => d.route === selectedRoute ? "var(--psy-purple, #7B2FBE)" : "var(--theme-foreground-faint, #bbb)",
        sort: {y: "x", reverse: true},
      }),
      Plot.text(data, {
        y: "route", x: "n",
        text: d => `${d.n.toFixed(1)} (${(100 * d.n / total).toFixed(0)}%)`,
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

  const matching = studies
    .map(s => ({s, routes: studyRoutes(s)}))
    .filter(({routes}) => routes.has(route))
    .sort((a, b) => (yearOf(b.s) || 0) - (yearOf(a.s) || 0));

  // Weight this route contributes per study (1 / number of distinct routes).
  const sumWeight = matching.reduce((acc, {routes}) => acc + 1 / routes.size, 0);

  return html`<div class="detail-body">
    <div class="detail-header">
      <h2><span class="tag psychedelic">${String(route).replace(/_/g, " ")}</span></h2>
      <p style="font-size:0.85rem;color:var(--theme-foreground-muted);">
        ${matching.length} ${matching.length === 1 ? "study" : "studies"} ·
        weight ${sumWeight.toFixed(1)}
        <span style="margin-left:8px;font-style:italic;">(studies using multiple routes contribute a fraction; click bar again to deselect)</span>
      </p>
    </div>
    <div style="line-height:1.8;">
      ${matching.map(({s, routes}) => {
        const w = 1 / routes.size;
        const frac = routes.size > 1 ? html` <sup style="color:var(--theme-foreground-faint);">${w.toFixed(2)}</sup>` : "";
        return html`<a href="study/${String(s._stem).toLowerCase().replace(/[^a-z0-9]/g, "")}" class="tag muted">${s.study_id}</a>${frac} `;
      })}
    </div>
  </div>`;
}
```

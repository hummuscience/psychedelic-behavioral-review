---
title: Dosages
toc: false
---

<style>
  :root { --observablehq-max-width: 1600px; }
  #observablehq-main { max-width: none !important; }
</style>

# Dosages

```js
import {bucketDoses, BUCKET_ORDER} from "./components/dose-utils.js";
import * as Plot from "npm:@observablehq/plot";
const dosages = await FileAttachment("data/dosages.csv").csv({typed: true});
const studies = await FileAttachment("data/studies.json").json();
const buckets = bucketDoses(dosages);
const byName = new Map(buckets.map(b => [b.name, b]));
const stemToSpecies = new Map();
for (const s of studies) {
  const raw = (s.species || "").toLowerCase().trim();
  let norm;
  const hasMouse = /\bmouse|mice\b/.test(raw);
  const hasRat = /\brat\b/.test(raw);
  if (hasMouse && hasRat) norm = "mouse and rat";
  else if (hasMouse) norm = "mouse";
  else if (hasRat) norm = "rat";
  else if (raw) norm = raw;
  else norm = "not reported";
  stemToSpecies.set(s._stem, norm);
}
const SPECIES_PALETTE = {"mouse":"#1B9E77","rat":"#D95F02","mouse and rat":"#7570B3","other":"#666","not reported":"#bdbdbd"};
```

Distribution of administered doses, per psychedelic group. Both **mg/kg** (mass-based, what authors typically report) and **nmol/kg** (molar, comparable across compounds via molecular weight) are available.

```js
const compound = view(Inputs.select(buckets.map(b => b.name), {label: "Compound", value: "Psilocybin"}));
const unit = view(Inputs.radio(["mg/kg", "nmol/kg"], {label: "Unit", value: "mg/kg"}));
const useLog = view(Inputs.toggle({label: "Log x-axis", value: true}));
const splitBy = view(Inputs.radio(["None", "Species", "Route"], {label: "Split by", value: "None"}));
```

```js
const ROUTE_ORDER = ["i.p.", "s.c.", "p.o.", "i.n.", "i.v.", "multiple"];
const ROUTE_PALETTE = {
  "i.p.":     "#7B2FBE",
  "s.c.":     "#E6550D",
  "p.o.":     "#3a7acf",
  "i.n.":     "#1B9E77",
  "i.v.":     "#D95F02",
  "multiple": "#7570B3",
};
function normRoute(raw) {
  const s = String(raw || "").toLowerCase().trim();
  if (!s) return null;
  if (ROUTE_ORDER.includes(s)) return s;
  return null;
}
```

```js
const c = byName.get(compound);
const unitKey = unit === "nmol/kg" ? "nmol_per_kg" : "mg_per_kg";
const positives = (c?.doses ?? []).filter(d => d[unitKey] != null && d[unitKey] > 0);
const xs = positives.map(d => d[unitKey]);
const minV = xs.length ? Math.min(...xs) : 0.001;
const maxV = xs.length ? Math.max(...xs) : 10;
// Suggest a reasonable default binwidth based on the data range.
// Round x to the nearest "clean" value: 1, 2, or 5 times a power of 10
function niceNum(x) {
  if (x <= 0) return 1;
  const exp = Math.floor(Math.log10(x));
  const f = x / 10 ** exp;
  const nice = f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10;
  return nice * 10 ** exp;
}

const suggestedBinwidth = (() => {
  if (!xs.length) return 1;
  if (useLog) {
    const range = Math.log10(maxV) - Math.log10(minV);
    return Math.max(0.05, Math.min(0.5, range / 20)).toFixed(2);
  } else {
    return niceNum((maxV - minV) / 20);
  }
})();
```

```js
const binwidth = view(Inputs.range(
  useLog ? [0.05, 1.0] : [niceNum((maxV - minV) / 200), niceNum((maxV - minV) / 4)],
  {
    label: useLog ? `Bin width (log₁₀ ${unit})` : `Bin width (${unit})`,
    value: +suggestedBinwidth,
    step: useLog ? 0.05 : niceNum((maxV - minV) / 200),
  }
));
```

<div class="card compound-card">
<b>${c?.name}</b> — ${c?.n_papers} papers · ${c?.n_records} records · ${positives.length} numeric points (${unit})
</div>

```js
const selected = Mutable(null);
const setSel = v => { selected.value = v; };
```

<div class="viewer-shell">
  <div class="viewer-left">${histEl}</div>
  <div class="viewer-right">${renderStudyList(selected, compound, unit)}</div>
</div>

```js
const histEl = (() => {
  if (positives.length === 0) {
    return html`<div style="padding:20px;color:#a00;">No ${unit} data for ${compound} — try switching unit.</div>`;
  }
  let edges;
  if (useLog) {
    const lo = Math.log10(minV), hi = Math.log10(maxV);
    const w = +binwidth;
    const start = Math.floor(lo / w) * w;
    const end = Math.ceil(hi / w) * w;
    const n = Math.max(1, Math.round((end - start) / w));
    edges = Array.from({length: n + 1}, (_, i) => 10 ** (start + i * w));
  } else {
    const w = +binwidth;
    const start = Math.floor(minV / w) * w;
    const end = Math.ceil(maxV / w) * w;
    const n = Math.max(1, Math.round((end - start) / w));
    edges = Array.from({length: n + 1}, (_, i) => start + i * w);
  }
  if (splitBy === "None") {
    const bins = edges.slice(0, -1).map((lo, i) => ({lo, hi: edges[i + 1], n: 0, studies: []}));
    for (const d of positives) {
      const v = d[unitKey];
      let idx;
      if (useLog) {
        const start = Math.log10(edges[0]);
        const w = +binwidth;
        idx = Math.floor((Math.log10(v) - start) / w);
      } else {
        idx = Math.floor((v - edges[0]) / +binwidth);
      }
      idx = Math.max(0, Math.min(bins.length - 1, idx));
      bins[idx].n += 1;
      bins[idx].studies.push({stem: d.stem, raw: d.raw, value: v, route: d.route});
    }
    const el = Plot.plot({
      height: 320,
      marginLeft: 60, marginRight: 24, marginBottom: 44, marginTop: 16,
      x: {
        label: `dose (${unit}${useLog ? ', log scale' : ''}) — ${bins.length} bins of width ${(+binwidth).toPrecision(3)}${useLog ? ' (log₁₀)' : ` ${unit}`}`,
        type: useLog ? "log" : "linear",
      },
      y: {label: "records", grid: true},
      marks: [
        Plot.rectY(bins, {
          x1: "lo", x2: "hi", y2: "n",
          fill: "var(--psy-purple)", opacity: 0.85,
          title: d => `${d.lo.toPrecision(3)}–${d.hi.toPrecision(3)} ${unit}\nn = ${d.n}`,
        }),
        Plot.ruleY([0]),
      ],
    });
    el.style.cursor = "pointer";
    el.addEventListener("click", (ev) => {
      const r = ev.target.closest("rect");
      if (!r) return;
      const idx = typeof r.__data__ === "number" ? r.__data__ : null;
      const bin = idx != null ? bins[idx] : null;
      if (bin && bin.studies.length) setSel(bin);
    });
    return el;
  } else {
    // Faceted-by-{species,route} branch.
    const groupCfg = splitBy === "Species"
      ? {key: "species", domain: ["mouse", "rat"], palette: SPECIES_PALETTE, label: "single-species"}
      : {key: "route",   domain: ROUTE_ORDER,      palette: ROUTE_PALETTE,   label: "known-route"};
    const rows = [];
    for (const d of positives) {
      const g = splitBy === "Species"
        ? (stemToSpecies.get(d.stem) || "not reported")
        : normRoute(d.route);
      if (!groupCfg.domain.includes(g)) continue;
      rows.push({dose: d[unitKey], [groupCfg.key]: g, stem: d.stem, raw: d.raw, route: d.route});
    }
    if (rows.length === 0) {
      return html`<div style="padding:20px;color:#a00;">No ${groupCfg.label} data for ${compound}.</div>`;
    }
    const presentGroups = groupCfg.domain.filter(g => rows.some(r => r[groupCfg.key] === g));
    const groupRange = presentGroups.map(g => groupCfg.palette[g] || "#999");
    const binRows = [];
    for (const g of presentGroups) {
      const gRows = rows.filter(r => r[groupCfg.key] === g);
      const gEdges = edges.slice(0, -1);
      const gBins = gEdges.map((lo, i) => ({lo, hi: edges[i + 1], [groupCfg.key]: g, n: 0, studies: []}));
      for (const r of gRows) {
        const v = r.dose;
        let idx;
        if (useLog) {
          idx = Math.floor((Math.log10(v) - Math.log10(edges[0])) / +binwidth);
        } else {
          idx = Math.floor((v - edges[0]) / +binwidth);
        }
        idx = Math.max(0, Math.min(gBins.length - 1, idx));
        gBins[idx].n += 1;
        gBins[idx].studies.push({stem: r.stem, raw: r.raw, value: r.dose, route: r.route});
      }
      const binWidth = gBins.length > 0 ? gBins[0].hi - gBins[0].lo : 1;
      for (const b of gBins) {
        binRows.push({...b, density: gRows.length > 0 ? b.n / (gRows.length * binWidth) : 0});
      }
    }
    const el = Plot.plot({
      height: 80 + 120 * presentGroups.length,
      marginLeft: 80, marginRight: 24, marginBottom: 44, marginTop: 16,
      x: {
        label: `dose (${unit}${useLog ? ', log scale' : ''}) — ${edges.length - 1} bins of width ${(+binwidth).toPrecision(3)}${useLog ? ' (log₁₀)' : ` ${unit}`}`,
        type: useLog ? "log" : "linear",
      },
      y: {label: "density", grid: false},
      fy: {domain: presentGroups, label: null},
      color: {legend: true, domain: presentGroups, range: groupRange},
      marks: [
        Plot.rectY(binRows, {
          x1: "lo", x2: "hi", y2: "density", fy: groupCfg.key, fill: groupCfg.key, opacity: 0.85,
          title: d => `${d[groupCfg.key]} · ${d.lo.toPrecision(3)}–${d.hi.toPrecision(3)} ${unit}\nn = ${d.n}`,
        }),
        Plot.ruleY([0]),
      ],
    });
    el.style.cursor = "pointer";
    el.addEventListener("click", (ev) => {
      const r = ev.target.closest("rect");
      if (!r) return;
      const idx = typeof r.__data__ === "number" ? r.__data__ : null;
      const bin = idx != null ? binRows[idx] : null;
      if (bin && bin.studies.length) {
        // Carry the chosen split-group name through to the detail panel.
        setSel({...bin, _split: bin[groupCfg.key]});
      }
    });
    return el;
  }
})();
```

```js
function renderStudyList(sel, compound, unit) {
  if (!sel) {
    return html`<div class="placeholder">
      <div>
        <p><b>Click a histogram bar</b> to list the dose records in that bin.</p>
      </div>
    </div>`;
  }
  // Group records by paper stem so a paper using multiple doses in this bin appears once
  const byStem = new Map();
  for (const r of sel.studies) {
    if (!byStem.has(r.stem)) byStem.set(r.stem, {stem: r.stem, doses: []});
    byStem.get(r.stem).doses.push(r);
  }
  const studies = [...byStem.values()].sort((a, b) => a.stem.localeCompare(b.stem));
  return html`<div class="detail-body">
    <div class="detail-header">
      <h2>${compound} · ${sel.lo.toPrecision(3)}–${sel.hi.toPrecision(3)} ${unit}</h2>
      <p style="font-size:0.85rem;color:var(--theme-foreground-muted);">
        ${sel.species ? html`<span class="tag species">${sel.species}</span> · ` : ""}
        ${sel.route && !sel.species ? html`<span class="tag muted">${sel.route}</span> · ` : ""}
        ${sel.n} dose record${sel.n === 1 ? "" : "s"} across ${studies.length} paper${studies.length === 1 ? "" : "s"}
      </p>
    </div>
    <div style="font-size:0.9rem;line-height:1.7;">
      ${studies.map(s => html`<div style="margin:4px 0;">
        <a href="study/${String(s.stem).toLowerCase().replace(/[^a-z0-9]/g, "")}" class="tag muted study-link">${s.stem}</a>
        <span style="color:var(--theme-foreground-muted);font-size:0.82rem;">
          ${s.doses.map(d => `${d.raw}${d.route ? ` (${d.route})` : ""}`).join(", ")}
        </span>
      </div>`)}
    </div>
  </div>`;
}
```

## Cross-compound counts

```js
display(Plot.plot({
  marginLeft: 110, height: 220,
  x: {label: "administered dose records"}, y: {label: null},
  marks: [
    Plot.barX(buckets, {x: "n_records", y: "name", fill: d => d.name === compound ? "var(--psy-purple)" : "#bdbdbd", sort: {y: "x", reverse: true}}),
    Plot.text(buckets, {x: "n_records", y: "name", text: "n_records", dx: 6, textAnchor: "start", fontSize: 11}),
  ],
}));
```

## Top dose tokens for this compound

```js
const counts = {};
for (const d of (c?.doses ?? [])) counts[d.raw] = (counts[d.raw] || 0) + 1;
const topDoses = Object.entries(counts)
  .sort((a,b) => b[1] - a[1]).slice(0, 25)
  .map(([dose, n]) => ({dose, n}));
display(Inputs.table(topDoses, {rows: 25}));
```

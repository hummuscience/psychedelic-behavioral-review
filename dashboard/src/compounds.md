---
title: Compounds
toc: false
---

# Compounds

```js
import {bucketDoses, BUCKET_ORDER} from "./components/dose-utils.js";
import * as Plot from "npm:@observablehq/plot";
const dosages = await FileAttachment("data/dosages.csv").csv({typed: true});
const buckets = bucketDoses(dosages);
```

Per-compound summaries. The bar shows **administered dose records** for the eight psychedelic groups of interest:
${BUCKET_ORDER.map(b => html`<span class="tag psychedelic">${b}</span>`)}

```js
display(Plot.plot({
  marginLeft: 100,
  height: 280,
  x: {label: "Administered dose records"},
  y: {label: null},
  marks: [
    Plot.barX(buckets, {x: "n_records", y: "name", fill: "var(--psy-purple)", sort: {y: "x", reverse: true}}),
    Plot.text(buckets, {x: "n_records", y: "name", text: "n_records", dx: 6, textAnchor: "start", fontSize: 11}),
  ],
}));
```

## All psychedelic compounds

Every serotonergic hallucinogen (and close research-tool analog like 2-Br-LSD, TCB-2, lisuride) that appears in any included paper, with paper counts and the dose range across the corpus. Antagonists, vehicles, comparators (ketamine, MDMA, fluoxetine, …) and other non-psychedelic drugs are excluded. Compound names are normalised case-insensitively but keep the most common spelling.

```js
{
  // Group by case-folded compound name; track the most common surface form
  // so e.g. "MDL100907" and "MDL-100,907" collapse but display nicely.
  const rows = [];
  const groups = new Map();
  for (const r of dosages) {
    if (r.class !== "psychedelic") continue;
    const name = String(r.compound || "").trim();
    if (!name) continue;
    const key = name.toLowerCase().replace(/[^a-z0-9]/g, "");
    if (!groups.has(key)) groups.set(key, {names: new Map(), stems: new Set(), records: 0, doses: [], cls: new Map()});
    const g = groups.get(key);
    g.names.set(name, (g.names.get(name) ?? 0) + 1);
    g.stems.add(r.stem);
    g.records += 1;
    g.cls.set(r.class, (g.cls.get(r.class) ?? 0) + 1);
    // Parse a numeric mg/kg from the dose string for range stats.
    const m = String(r.dose ?? "").match(/^\s*([\d.]+)\s*mg\/kg/i);
    if (m) {
      const v = parseFloat(m[1]);
      if (Number.isFinite(v) && v > 0) g.doses.push(v);
    }
  }
  for (const g of groups.values()) {
    // Most common surface form wins
    const displayName = [...g.names.entries()].sort((a, b) => b[1] - a[1])[0][0];
    const dominantClass = [...g.cls.entries()].sort((a, b) => b[1] - a[1])[0][0];
    rows.push({
      compound: displayName,
      class: dominantClass,
      n_papers: g.stems.size,
      n_records: g.records,
      "min mg/kg": g.doses.length ? Math.min(...g.doses) : null,
      "max mg/kg": g.doses.length ? Math.max(...g.doses) : null,
    });
  }
  rows.sort((a, b) => b.n_records - a.n_records || b.n_papers - a.n_papers);
  display(html`<p style="color:var(--theme-foreground-muted);font-size:0.88rem;margin:8px 0 12px;">
    ${rows.length} distinct compounds across ${new Set(dosages.map(d => d.stem)).size} papers.
  </p>`);
  display(Inputs.table(rows, {
    rows: 20,
    format: {
      compound: d => html`<b>${d}</b>`,
      class: d => html`<span class="tag muted" style="font-size:0.78rem;">${d ?? ""}</span>`,
      "min mg/kg": v => v == null ? "" : (v < 0.01 ? v.toExponential(2) : v.toFixed(3)),
      "max mg/kg": v => v == null ? "" : v.toFixed(2),
    },
  }));
}
```

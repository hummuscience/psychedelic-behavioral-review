---
title: Pipeline / PRISMA
toc: false
---

# Pipeline / PRISMA flow

```js
const p = await FileAttachment("data/prisma.json").json();
```

How the corpus was assembled.

<div class="grid grid-cols-2">
  <div class="card">
    <h2>${p.n_records}</h2>
    <span>records identified through PubMed search</span>
  </div>
  <div class="card">
    <h2>${p.n_excluded_classifier}</h2>
    <span>excluded by title/abstract classifier</span>
  </div>
  <div class="card">
    <h2>${p.n_pdf_unavailable}</h2>
    <span>relevant but PDF unobtainable</span>
  </div>
  <div class="card">
    <h2>${p.n_consensus}</h2>
    <span>final corpus (consensus-scored)</span>
  </div>
</div>

## Flow diagram

<style>
  .flow {
    display: grid;
    grid-template-columns: minmax(260px, 1fr) 24px minmax(220px, 1fr);
    gap: 12px 16px;
    align-items: center;
    margin: 8px 0 24px;
    font-family: ui-sans-serif, system-ui, sans-serif;
  }
  .flow-node {
    background: var(--theme-background-alt, #f7f5f1);
    border: 1px solid var(--theme-foreground-faintest, #d2cdc1);
    border-radius: 10px;
    padding: 10px 14px;
    text-align: center;
    font-size: 0.92rem;
    line-height: 1.35;
  }
  .flow-node.decision { background: #fef6e7; border-color: #e6c89f; }
  .flow-node.terminal { background: #ecf6ec; border-color: #b3d8b3; font-weight: 600; }
  .flow-node.excluded { background: #fbeaea; border-color: #d8b3b3; color: #6a3030; font-size: 0.85rem; }
  .flow-node b { display: block; font-variant-numeric: tabular-nums; }
  .flow-node .n { color: var(--psy-purple, #7B2FBE); font-weight: 600; }
  .flow-arrow-down, .flow-arrow-right {
    color: var(--theme-foreground-muted, #7a766d);
    font-size: 1.4rem;
    text-align: center;
    line-height: 1;
  }
  .flow-arrow-down { grid-column: 1; }
  .flow-arrow-right { display: inline-flex; align-items: center; gap: 6px; font-size: 0.78rem; color: var(--theme-foreground-muted, #7a766d); }
  .flow-arrow-right::before { content: "→"; font-size: 1.2rem; }
  .flow-spacer { grid-column: 2; }
  .observablehq-dark .flow-node { background: #1e1c19; border-color: #3a3830; }
  .observablehq-dark .flow-node.decision { background: #2a2418; border-color: #5a4a2a; }
  .observablehq-dark .flow-node.terminal { background: #1a2a1a; border-color: #3a5a3a; }
  .observablehq-dark .flow-node.excluded { background: #2a1818; border-color: #5a3030; color: #d8b3b3; }
</style>

<div class="flow">
  <div class="flow-node">PubMed search<br><span class="n">n = ${p.n_records.toLocaleString()}</span></div>
  <div></div>
  <div></div>

  <div class="flow-arrow-down">↓</div>
  <div></div>
  <div></div>

  <div class="flow-node decision">Title-abstract screening</div>
  <div></div>
  <div class="flow-node excluded">excluded as off-topic, MDMA-only, or out of scope<br><span class="n">n = ${p.n_excluded_classifier.toLocaleString()}</span></div>

  <div class="flow-arrow-down">↓</div>
  <div></div>
  <div></div>

  <div class="flow-node decision">PDF retrievable?</div>
  <div></div>
  <div class="flow-node excluded">paywalled / unavailable<br><span class="n">n = ${p.n_pdf_unavailable.toLocaleString()}</span></div>

  <div class="flow-arrow-down">↓</div>
  <div></div>
  <div></div>

  <div class="flow-node">+ manually added papers<br><span class="n">= ${p.n_pdfs_on_disk.toLocaleString()} PDFs</span></div>
  <div></div>
  <div></div>

  <div class="flow-arrow-down">↓</div>
  <div></div>
  <div></div>

  <div class="flow-node terminal">Final analysable corpus<br><span class="n">n = ${p.n_consensus.toLocaleString()}</span></div>
  <div></div>
  <div></div>

  <div class="flow-arrow-down">↓</div>
  <div></div>
  <div></div>

  <div class="flow-node terminal"><span class="n">${p.n_admin_papers.toLocaleString()}</span> with ≥1 administered drug dose</div>
  <div></div>
  <div></div>
</div>

## Disposition breakdown (per PubMed record)

```js
import * as Plot from "npm:@observablehq/plot";
const dispData = Object.entries(p.dispositions || {})
  .map(([k, v]) => ({disposition: k.replace(/_/g, " "), n: v}))
  .sort((a, b) => b.n - a.n);
display(Plot.plot({
  marginLeft: 280,
  height: 280,
  x: {label: "records"},
  marks: [
    Plot.barX(dispData, {y: "disposition", x: "n", fill: "var(--psy-purple)", sort: {y: "x", reverse: true}}),
    Plot.text(dispData, {y: "disposition", x: "n", text: "n", dx: 6, textAnchor: "start"}),
  ],
}));
```

## How to read this

- **excluded_classifier_false_positive** — flagged off-topic at the title/abstract stage; small handful manually pulled back in.
- **excluded_compound_filter_MDMA** — papers studying only MDMA (this review focuses on classical psychedelics).
- **pdf_unavailable_relevant** — paywalled and not retrievable.
- **included_in_review** — final, scored corpus.
- **manually_added_to_corpus** — papers added directly to the corpus outside the PubMed expansion.

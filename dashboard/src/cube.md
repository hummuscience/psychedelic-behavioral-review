---
title: Complexity & duration space
toc: false
---

<style>
  :root { --observablehq-max-width: 1600px; }
  #observablehq-main { max-width: none !important; }
</style>

```js
const studies = await FileAttachment("data/studies.json").json();
const assayCatalog = await FileAttachment("data/assay_catalog.json").json();
import {BUCKET_ORDER, compoundsOf} from "./components/dose-utils.js";
import {mountFilters} from "./components/filters.js";
import * as Plot from "npm:@observablehq/plot";
const Plotly = (await import("https://esm.sh/plotly.js-dist-min@2.35.2")).default;
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
const allYears = Array.from(new Set(studies.map(yearOf).filter(Boolean))).sort();
function compoundOf(s) {
  // Single-bucket pick: first match from the alias-aware mapping.
  return compoundsOf(s)[0] || "(other)";
}
function speciesColorPalette() {
  return {"mouse":"#1B9E77","rat":"#D95F02","mouse and rat":"#7570B3","other":"#666","not reported":"#bdbdbd"};
}
function sexColorPalette() {
  return {"male only":"#3a7acf","female only":"#E7298A","both sexes":"#7B2FBE","not reported":"#bdbdbd"};
}
function normalizeSex(raw) {
  const s = String(raw ?? "").toLowerCase().trim();
  if (!s) return "not reported";
  if (s.includes("both")) return "both sexes";
  if (s.includes("female")) return "female only";
  if (s.includes("male")) return "male only";
  return "not reported";
}
function compoundColorPalette() {
  return {
    "Psilocybin":"#7B2FBE","LSD":"#E6550D","DOI":"#D95F02","DMT":"#3a7acf",
    "5-MeO-DMT":"#1B9E77","NBOMe/NBOH":"#E7298A","Ibogaine":"#66A61E","Mescaline":"#A6761D",
    "(other)":"#999",
  };
}
function assayCategoryColorPalette() {
  return {
    "Psychedelic response":"#7B2FBE","Anxiety":"#E6550D","Depression / anhedonia":"#3a7acf",
    "Locomotor / motor":"#1B9E77","Cognition / memory":"#D95F02","Social behaviour":"#E7298A",
    "Addiction / substance use":"#66A61E","Pain":"#A6761D","Sensorimotor":"#7570B3",
    "Physiological":"#17BECF","Miscellaneous":"#999999","(no assays)":"#999",
  };
}
const CONDITION_FIELDS = {
  handling: "handling",
  group_housing: "group housing",
  day_night_flipped: "reverse light cycle",
  enrichment_housing: "home-cage enrichment",
  setup_habituation: "setup habituation",
  setup_restrain: "setup restrain (during recording)",
};
const HOUSING_CONDITION_FIELDS = new Set(["handling","group_housing","day_night_flipped","enrichment_housing"]);
function modalValue(arr) {
  if (!arr.length) return null;
  const c = {}; for (const v of arr) c[v] = (c[v]||0) + 1;
  return Object.entries(c).sort((a,b) => b[1]-a[1])[0][0];
}
function conditionValueFor(s, field) {
  if (HOUSING_CONDITION_FIELDS.has(field)) return s.housing_conditions?.[field]?.value ?? null;
  const vs = (s.assays || []).map(a => a.experimental_conditions?.[field]?.value).filter(Boolean);
  return vs.length ? modalValue(vs) : null;
}
function conditionColorPalette() {
  return {"yes":"#2ca02c","no":"#9e9e9e","not reported":"#bdbdbd"};
}
```

# Complexity & duration space

Each dot is one study, positioned by its maximum behavioural complexity, environmental complexity, and recording-duration scores across all assays. Click a dot to inspect that paper.

```js
const _filters = mountFilters(studies, {Inputs, html, Generators}, assayCatalog);
display(_filters.node);
```

```js
const filteredStudies = _filters.filtered;
```

```js
const viewMode = view(Inputs.radio(["Studies", "Assay", "Assay Category"], {label: "View", value: "Studies"}));
```

```js
const colorMode = view(Inputs.radio(["Year", "Species", "Sex", "Assay Category", "Compound", "Condition"], {label: "Colour by", value: "Year"}));
```

```js
const conditionField = view(Inputs.select(Object.keys(CONDITION_FIELDS), {label: "Condition", format: f => CONDITION_FIELDS[f], value: "handling"}));
```

```js
{
  viewMode;
  const el = colorMode instanceof HTMLElement ? colorMode : colorMode?.element ?? colorMode;
  if (el?.querySelectorAll) el.querySelectorAll("input").forEach(i => i.disabled = viewMode !== "Studies");
}
```

```js
{
  // Disable the condition dropdown unless the user is colouring by Condition in Studies view.
  colorMode; viewMode;
  const el = conditionField instanceof HTMLElement ? conditionField : conditionField?.element ?? conditionField;
  if (el?.querySelectorAll) el.querySelectorAll("select,input").forEach(i => i.disabled = !(viewMode === "Studies" && colorMode === "Condition"));
}
```

```js
const jitter = view(Inputs.range([0, 1], {label: "Jitter", value: 0.5, step: 0.05}));
```

```js
const selected = Mutable(null);
const setSelected = (v) => { selected.value = v; };
```

<div class="viewer-shell">
  <div class="viewer-left">
    ${(() => {
      const div = html`<div id="cube" style="width:100%;height:560px;"></div>`;
      requestAnimationFrame(() => renderCube(div));
      return div;
    })()}
  </div>
  <div class="viewer-right">
    ${renderDetail(selected)}
  </div>
</div>

```js
function jit(seedStr, dim) {
  if (!jitter) return 0;
  let h = 0; const s = String(seedStr ?? "") + "|" + dim;
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  // Slider scales the displacement; full = ±0.6 score units.
  return ((Math.abs(h) % 10000) / 10000 - 0.5) * 1.2 * jitter;
}

function renderCube(div) {
  let traces, layout;
  if (viewMode === "Studies") {
    const items = filteredStudies;
    const pos = (k) => s => (s.study_level_scores?.[k] ?? 0) + jit(s._stem, k === "environmental_complexity_max" ? "x" : k.startsWith("rec") ? "y" : "z");
    if (colorMode === "Year") {
      traces = [{
        type: "scatter3d", mode: "markers",
        x: items.map(pos("environmental_complexity_max")),
        y: items.map(s => ((s.study_level_scores?.recording_duration_banded_max ?? s.study_level_scores?.recording_duration_max) ?? 0) + jit(s._stem, "y")),
        z: items.map(pos("behavioural_complexity_max")),
        text: items.map(s => s.study_id),
        customdata: items.map(s => s._stem),
        hovertemplate: "<b>%{text}</b><br>E=%{x:.1f}  D=%{y:.1f}  B=%{z:.1f}<extra></extra>",
        marker: {
          size: 5, line: {color: "#222", width: 0.3},
          color: items.map(s => yearOf(s) ?? 2020),
          colorscale: [[0,'#00e5ff'],[0.17,'#00bcd4'],[0.33,'#5c6bc0'],[0.50,'#9c27b0'],[0.67,'#d81b9c'],[0.83,'#e91e90'],[1,'#ff4081']],
          cmin: Math.min(...allYears), cmax: Math.max(...allYears),
          colorbar: {title: "Year", thickness: 12, len: 0.6},
        },
      }];
    } else {
      let pal, catFn;
      if (colorMode === "Species") { pal = speciesColorPalette(); catFn = s => normalizeSpecies(s.species); }
      else if (colorMode === "Sex") { pal = sexColorPalette(); catFn = s => normalizeSex(s.sex); }
      else if (colorMode === "Assay Category") { pal = assayCategoryColorPalette(); catFn = s => (s.assays || []).find(a => a.category)?.category || "(no assays)"; }
      else if (colorMode === "Condition") { pal = conditionColorPalette(); catFn = s => String(conditionValueFor(s, conditionField) ?? "not_reported").replace(/_/g, " "); }
      else { pal = compoundColorPalette(); catFn = s => compoundOf(s); }
      const groups = new Map();
      for (const s of items) {
        const cat = catFn(s);
        if (!groups.has(cat)) groups.set(cat, []);
        groups.get(cat).push(s);
      }
      const orderedKeys = Object.keys(pal).filter(k => groups.has(k));
      const extraKeys = [...groups.keys()].filter(k => !Object.keys(pal).includes(k));
      if (extraKeys.length) orderedKeys.push(...extraKeys);
      traces = orderedKeys.map(cat => {
        const ss = groups.get(cat);
        return {
          type: "scatter3d", mode: "markers", name: cat, legendgroup: cat,
          x: ss.map(pos("environmental_complexity_max")),
          y: ss.map(s => ((s.study_level_scores?.recording_duration_banded_max ?? s.study_level_scores?.recording_duration_max) ?? 0) + jit(s._stem, "y")),
          z: ss.map(pos("behavioural_complexity_max")),
          text: ss.map(s => s.study_id),
          customdata: ss.map(s => s._stem),
          hovertemplate: "<b>%{text}</b><br>E=%{x:.1f}  D=%{y:.1f}  B=%{z:.1f}<extra></extra>",
          marker: {size: 5, color: pal[cat] || "#999", line: {color: "#222", width: 0.3}},
        };
      });
    }
  } else if (viewMode === "Assay") {
    const canonToCat = new Map();
    const byAssay = new Map();
    for (const a of assayCatalog) canonToCat.set(a.canonical, a.category);
    for (const s of filteredStudies) {
      const seen = new Set();
      for (const a of (s.assays || [])) {
        if (a.canonical && !seen.has(a.canonical)) {
          seen.add(a.canonical);
          if (!byAssay.has(a.canonical)) byAssay.set(a.canonical, []);
          byAssay.get(a.canonical).push(s);
        }
      }
    }
    const catPal = assayCategoryColorPalette();
    const catOrder = ["Psychedelic response","Anxiety","Depression / anhedonia","Locomotor / motor","Cognition / memory","Social behaviour","Addiction / substance use","Pain","Sensorimotor","Physiological","Miscellaneous"];
    const items = [];
    for (const [name, ss] of byAssay) {
      const cat = canonToCat.get(name) || "Miscellaneous";
      const avg = (k) => {
        const xs = ss.map(s => s.study_level_scores?.[k]).filter(v => v != null);
        return xs.length ? xs.reduce((a,b)=>a+b,0)/xs.length : 0;
      };
      items.push({ name, cat, n: ss.length, b: avg("behavioural_complexity_max"), e: avg("environmental_complexity_max"), d: avg("recording_duration_banded_max") || avg("recording_duration_max") });
    }
    items.sort((a, b) => catOrder.indexOf(a.cat) - catOrder.indexOf(b.cat) || b.n - a.n);
    traces = [{
      type: "scatter3d", mode: "markers",
      x: items.map(d => d.e), y: items.map(d => d.d), z: items.map(d => d.b),
      text: items.map(d => `${d.name} [${d.cat}] (n=${d.n})`),
      customdata: items.map(d => d.name),
      hovertemplate: "<b>%{text}</b><br>avg E=%{x:.1f}  D=%{y:.1f}  B=%{z:.1f}<extra></extra>",
      marker: {
        size: 12,
        color: items.map(d => catPal[d.cat] || "#999"),
        opacity: 0.85, line: {color: "#222", width: 0.5},
      },
    }];
  } else if (viewMode === "Assay Category") {
    const byCat = new Map();
    for (const s of filteredStudies) {
      const seen = new Set();
      for (const a of (s.assays || [])) {
        if (a.category && !seen.has(a.category)) { seen.add(a.category); }
      }
      const cats = [...seen];
      for (const cat of cats) {
        if (!byCat.has(cat)) byCat.set(cat, []);
        byCat.get(cat).push(s);
      }
    }
    const catPal = assayCategoryColorPalette();
    const catOrder = ["Psychedelic response","Anxiety","Depression / anhedonia","Locomotor / motor","Cognition / memory","Social behaviour","Addiction / substance use","Pain","Sensorimotor","Physiological","Miscellaneous"];
    const items = catOrder.filter(c => byCat.has(c)).map(name => {
      const ss = byCat.get(name);
      const avg = (k) => {
        const xs = ss.map(s => s.study_level_scores?.[k]).filter(v => v != null);
        return xs.length ? xs.reduce((a,b)=>a+b,0)/xs.length : 0;
      };
      return {
        name, n: ss.length,
        b: avg("behavioural_complexity_max"),
        e: avg("environmental_complexity_max"),
        d: avg("recording_duration_banded_max") || avg("recording_duration_max"),
      };
    });
    traces = [{
      type: "scatter3d", mode: "markers+text",
      x: items.map(d => d.e), y: items.map(d => d.d), z: items.map(d => d.b),
      text: items.map(d => `${d.name} (n=${d.n})`),
      textposition: "top center", textfont: {size: 11},
      customdata: items.map(d => d.name),
      hovertemplate: "<b>%{text}</b><br>avg E=%{x:.1f}  D=%{y:.1f}  B=%{z:.1f}<extra></extra>",
      marker: {
        size: 12,
        color: items.map(d => catPal[d.name] || "#999"),
        opacity: 0.85, line: {color: "#222", width: 0.5},
      },
    }];
  }
  layout = {
    scene: {
      xaxis: {
        title: "Environmental complexity", range: [0, 15],
        gridcolor: "#e0e0e0", zerolinecolor: "#999", showbackground: true,
        backgroundcolor: "#fbf7fa",
      },
      yaxis: {
        title: "Recording duration", range: [0, 15],
        gridcolor: "#e0e0e0", zerolinecolor: "#999", showbackground: true,
        backgroundcolor: "#f4faff",
      },
      zaxis: {
        title: "Behavioural complexity", range: [0, 15],
        gridcolor: "#e0e0e0", zerolinecolor: "#999", showbackground: true,
        backgroundcolor: "#f6fbf6",
      },
      aspectmode: "manual",
      aspectratio: {x: 1.0, y: 1.4, z: 1.1},
      bgcolor: "white",
      camera: {
        eye: {x: 1.6, y: 1.6, z: 0.9},
        center: {x: 0, y: 0, z: -0.05},
        up: {x: 0, y: 0, z: 1},
      },
    },
    margin: {l: 0, r: 0, t: 0, b: 0},
    height: 560, paper_bgcolor: "white", showlegend: colorMode !== "Year",
  };
  Plotly.react(div, traces, layout, {responsive: true, displaylogo: false});
  div.on("plotly_click", (ev) => {
    const p = ev.points?.[0];
    if (!p) return;
    if (viewMode === "Studies") {
      const stem = p.customdata;
      const study = studies.find(s => s._stem === stem);
      if (study) setSelected({kind: "study", study});
    } else {
      const name = p.customdata;
      setSelected({kind: "group", name});
    }
  });
}

function renderDetail(sel, ctx) {
  if (!sel) {
    return html`<div class="placeholder">
      <div>
        <p><b>Click a dot</b> in the cube to see its details here.</p>
        <p style="font-size:0.85rem;color:var(--theme-foreground-muted);margin-top:8px;">
          Studies view shows one paper per dot. Assay and Assay Category views show averaged positions per group.
        </p>
      </div>
    </div>`;
  }
  if (sel.kind === "study") return renderStudyDetail(sel.study);
  if (sel.kind === "group") return renderGroupDetail(sel.name);
  return html`<div class="placeholder">unknown selection</div>`;
}

function renderStudyDetail(study) {
  const sc = study.study_level_scores || {};
  const year = yearOf(study) ?? "?";
  return html`<div class="detail-body">
    <div class="detail-header">
      <h2>${study.study_id}</h2>
      ${study.title ? html`<p class="study-title">${study.title}</p>` : ""}
      ${study.journal ? html`<p class="study-journal">${study.journal}${study.pub_year ? ` · ${study.pub_year}` : ""}</p>` : ""}
      <div class="meta">
        <span class="tag year">${year}</span>
        <span class="tag species">${normalizeSpecies(study.species)}</span>
        ${study.sex ? html`<span class="tag muted">${study.sex}</span>` : ""}
        <span class="tag psychedelic">${study.psychedelic ?? "?"}</span>
        ${study.strain ? html`<span class="tag muted">${study.strain}</span>` : ""}
      </div>
      <div style="margin-top:6px;font-size:0.85rem;">
        ${study.doi ? html`<a href="https://doi.org/${study.doi}" target="_blank" rel="noopener">doi:${study.doi}</a>` : ""}
        ${study._stem ? html`&middot; <a href="study/${String(study._stem).toLowerCase().replace(/[^a-z0-9]/g, "")}">full page →</a>` : ""}
      </div>
    </div>
    <div class="score-grid">
      <div class="score-card beh"><div class="label">Behavioural</div><div class="value">${(sc.behavioural_complexity_max ?? 0).toFixed(1)}</div></div>
      <div class="score-card env"><div class="label">Environmental</div><div class="value">${(sc.environmental_complexity_max ?? 0).toFixed(1)}</div></div>
      <div class="score-card dur"><div class="label">Duration</div><div class="value">${((sc.recording_duration_banded_max ?? sc.recording_duration_max) ?? 0).toFixed(1)}</div></div>
    </div>
    <h3>Housing conditions</h3>
    <table class="kv">
      ${Object.entries(study.housing_conditions || {}).map(([k, v]) => html`<tr>
        <td class="k">${k.replace(/_/g," ")}</td>
        <td><span class="tag value-${(v.value||"").replace(/[^a-z]/g,"")}">${v.value}</span></td>
      </tr>`)}
    </table>
    <h3>Assays (${(study.assays || []).length})</h3>
    ${(study.assays || []).map(a => html`<details class="assay">
      <summary><b>${a.assay_name}</b> · B=${a.behavioural_complexity?.raw_total ?? "?"} E=${a.environmental_complexity?.raw_total ?? "?"} D=${a.recording_duration?.raw_total ?? "?"}</summary>
      <p class="assay-desc">${a.assay_description ?? ""}</p>
      ${a.experimental_conditions ? html`<details><summary>Experimental conditions</summary>
        <table class="kv">
          ${Object.entries(a.experimental_conditions).map(([k, v]) => html`<tr>
            <td class="k">${k.replace(/_/g," ")}</td>
            <td><span class="tag value-${(v.value||"").replace(/[^a-z]/g,"")}">${v.value}</span></td>
          </tr>`)}
        </table>
      </details>` : ""}
      ${["behavioural_complexity","environmental_complexity","recording_duration"].map(dim => {
        if (!a[dim]) return "";
        const cls = dim.startsWith("beh") ? "beh" : dim.startsWith("env") ? "env" : "dur";
        return html`<details><summary class="${cls}">${dim.replace(/_/g, " ")} · raw ${a[dim].raw_total}</summary>
          <table class="kv items">
            ${Object.entries(a[dim]).filter(([k]) => k !== "raw_total").map(([k, v]) => html`<tr>
              <td class="k">${k}</td>
              <td><b>${v.score}</b></td>
              <td>${v.value}</td>
              <td><div class="evidence">${v.evidence}</div></td>
            </tr>`)}
          </table>
        </details>`;
      })}
    </details>`)}
    ${study.judge_notes && study.judge_notes.length ? html`<details>
      <summary>Notes (${study.judge_notes.length})</summary>
      <ul>${study.judge_notes.map(n => html`<li>${n}</li>`)}</ul>
    </details>` : ""}
  </div>`;
}

const TIMELINE_DIMS = {
  "Behavioural complexity":    {key: "behavioural_complexity_max",   colour: "#7B2FBE"},
  "Environmental complexity":  {key: "environmental_complexity_max", colour: "#E6550D"},
  "Recording duration":        {key: "recording_duration_max",       colour: "#3a7acf"},
};

function timelineRows(key) {
  const rows = [];
  for (const s of filteredStudies) {
    const y = yearOf(s);
    if (!y) continue;
    const v = key === "recording_duration_max"
      ? (s.study_level_scores?.recording_duration_banded_max ?? s.study_level_scores?.recording_duration_max)
      : s.study_level_scores?.[key];
    if (v == null) continue;
    rows.push({year: y, value: v, study_id: s.study_id, _stem: s._stem});
  }
  return rows;
}

// OLS regression of y on x. Returns slope (b), intercept (a),
// 95% CI half-width for the slope, t-statistic, two-sided p-value
// (normal approximation, accurate to ~3 decimals for n>30),
// Spearman rank correlation, and R².
function trendStats(rows) {
  const n = rows.length;
  if (n < 3) return null;
  const xs = rows.map(r => r.year);
  const ys = rows.map(r => r.value);
  const mx = xs.reduce((a, b) => a + b, 0) / n;
  const my = ys.reduce((a, b) => a + b, 0) / n;
  let sxx = 0, sxy = 0, syy = 0;
  for (let i = 0; i < n; i++) {
    const dx = xs[i] - mx, dy = ys[i] - my;
    sxx += dx * dx; sxy += dx * dy; syy += dy * dy;
  }
  const b = sxx === 0 ? 0 : sxy / sxx;
  const a = my - b * mx;
  // Residual variance & SE of slope
  let ssr = 0;
  for (let i = 0; i < n; i++) { const e = ys[i] - (a + b * xs[i]); ssr += e * e; }
  const sigma2 = ssr / (n - 2);
  const seB = Math.sqrt(sigma2 / sxx);
  const t = b / seB;
  // Two-sided p via normal approx (good enough for n>>30 in this corpus)
  const erf = (z) => {
    const sign = z < 0 ? -1 : 1; z = Math.abs(z);
    const a1=0.254829592, a2=-0.284496736, a3=1.421413741, a4=-1.453152027, a5=1.061405429, p=0.3275911;
    const tt = 1 / (1 + p * z);
    const y = 1 - (((((a5*tt + a4)*tt) + a3)*tt + a2)*tt + a1)*tt*Math.exp(-z*z);
    return sign * y;
  };
  const pTwo = 2 * (1 - 0.5 * (1 + erf(Math.abs(t) / Math.SQRT2)));
  const ci = 1.96 * seB;
  // R²
  const r2 = syy === 0 ? 0 : 1 - ssr / syy;
  // Spearman rho (rank correlation) — robust to outliers
  const rankOf = (arr) => {
    const idx = arr.map((v, i) => [v, i]).sort((p, q) => p[0] - q[0]);
    const r = new Array(arr.length);
    let i = 0;
    while (i < idx.length) {
      let j = i;
      while (j + 1 < idx.length && idx[j + 1][0] === idx[i][0]) j++;
      const avgRank = (i + j) / 2 + 1;
      for (let k = i; k <= j; k++) r[idx[k][1]] = avgRank;
      i = j + 1;
    }
    return r;
  };
  const rx = rankOf(xs), ry = rankOf(ys);
  const mrx = rx.reduce((a, b) => a + b, 0) / n;
  const mry = ry.reduce((a, b) => a + b, 0) / n;
  let rxy = 0, rxx = 0, ryy = 0;
  for (let i = 0; i < n; i++) {
    rxy += (rx[i] - mrx) * (ry[i] - mry);
    rxx += (rx[i] - mrx) ** 2;
    ryy += (ry[i] - mry) ** 2;
  }
  const rho = (rxx === 0 || ryy === 0) ? 0 : rxy / Math.sqrt(rxx * ryy);
  return {n, b, a, seB, t, p: pTwo, ci, r2, rho, xMin: Math.min(...xs), xMax: Math.max(...xs)};
}

function fmtP(p) {
  if (p < 0.001) return "< 0.001";
  if (p < 0.01)  return p.toFixed(3);
  return p.toFixed(2);
}

function timelineChart(dim) {
  const {key, colour} = TIMELINE_DIMS[dim];
  const rows = timelineRows(key);
  // Stable jitter keyed by stem so a study sits in the same spot across renders.
  const hashJit = (stem, salt, amount) => {
    let h = 0; const s = String(stem ?? "") + "|" + salt;
    for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
    return ((Math.abs(h) % 10000) / 10000 - 0.5) * amount;
  };
  for (const r of rows) {
    r._dx = hashJit(r._stem, "tx", 14);
    r._jy = hashJit(r._stem, "ty", 0.35);
  }
  const byYear = new Map();
  for (const r of rows) {
    if (!byYear.has(r.year)) byYear.set(r.year, []);
    byYear.get(r.year).push(r.value);
  }
  // Linear interpolation quantile (R type 7, matches numpy/d3 default).
  const quantile = (sorted, q) => {
    if (!sorted.length) return null;
    if (sorted.length === 1) return sorted[0];
    const pos = (sorted.length - 1) * q;
    const lo = Math.floor(pos), hi = Math.ceil(pos);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  };
  const summaries = [...byYear.entries()]
    .map(([year, xs]) => {
      const sorted = [...xs].sort((a, b) => a - b);
      return {
        year, n: sorted.length,
        median: quantile(sorted, 0.5),
        q1: quantile(sorted, 0.25),
        q3: quantile(sorted, 0.75),
      };
    })
    .sort((a, b) => a.year - b.year);
  const xDomain = Array.from({length: Math.max(...allYears) - Math.min(...allYears) + 1}, (_, i) => Math.min(...allYears) + i);

  const stats = trendStats(rows);
  const trendLine = stats ? [
    {year: stats.xMin, fit: stats.a + stats.b * stats.xMin},
    {year: stats.xMax, fit: stats.a + stats.b * stats.xMax},
  ] : [];

  const el = Plot.plot({
    height: 360,
    marginLeft: 56, marginRight: 24, marginBottom: 44, marginTop: 16,
    x: {label: "Year", tickFormat: d => `${d}`, domain: xDomain},
    y: {label: dim, grid: true, domain: [0, 15]},
    marks: [
      // Q1–Q3 band (IQR) — semi-transparent ribbon, drawn below dots
      Plot.areaY(summaries, {
        x: "year", y1: "q1", y2: "q3", fill: colour, fillOpacity: 0.14, curve: "monotone-x",
      }),
      Plot.dot(rows, {
        x: "year", y: d => d.value + d._jy, fill: colour, fillOpacity: 0.45, r: 4,
        stroke: colour, strokeOpacity: 0.6,
        dx: "_dx",
        title: d => `${d.study_id}: ${d.value.toFixed(1)}`,
      }),
      // Median line
      Plot.line(summaries, {
        x: "year", y: "median", stroke: colour, strokeWidth: 1.8, strokeOpacity: 0.85, curve: "monotone-x",
      }),
      Plot.dot(summaries, {
        x: "year", y: "median", fill: colour, fillOpacity: 0.85, stroke: "white", strokeWidth: 1, r: 4,
        title: d => `${d.year}: median ${d.median.toFixed(1)}, IQR ${d.q1.toFixed(1)}–${d.q3.toFixed(1)} (n=${d.n})`,
      }),
      Plot.line(trendLine, {x: "year", y: "fit", stroke: "#111", strokeWidth: 2.2}),
      Plot.ruleY([0]),
    ],
  });
  el.style.cursor = "pointer";
  el.addEventListener("click", (ev) => {
    const c = ev.target.closest("circle");
    if (!c) return;
    const idx = typeof c.__data__ === "number" ? c.__data__ : null;
    if (idx == null) return;
    const row = rows[idx];
    if (!row) return;
    const study = studies.find(s => s._stem === row._stem);
    if (study) setSelected({kind: "study", study});
  });

  // Trend stats card rendered above the plot.
  const statsCard = stats
    ? html`<div class="trend-card">
        <div class="trend-line">
          <span class="trend-label">Linear trend</span>
          <span class="trend-stat ${stats.p < 0.05 ? "sig" : ""}">
            slope = <b>${stats.b >= 0 ? "+" : ""}${stats.b.toFixed(3)}</b>
            <span class="trend-unit">score / year</span>
            <span class="trend-ci">(95% CI ${(stats.b - stats.ci).toFixed(3)} to ${(stats.b + stats.ci).toFixed(3)})</span>
          </span>
          <span class="trend-stat ${stats.p < 0.05 ? "sig" : ""}">p = <b>${fmtP(stats.p)}</b></span>
          <span class="trend-stat">Spearman ρ = <b>${stats.rho.toFixed(2)}</b></span>
          <span class="trend-stat trend-muted">R² = ${stats.r2.toFixed(3)} · n = ${stats.n}</span>
        </div>
        <div class="trend-note">
          OLS on individual studies (each study weighted equally, so years with more studies pull the line more — which is what you want when asking whether the field as a whole has shifted).
          Yearly means shown as faint dashed line for reference.
          ${stats.p < 0.05
            ? html`<b style="color:#2a7"> Significant change over time.</b>`
            : html`<b style="color:#888"> No detectable linear change (p ≥ 0.05).</b>`}
        </div>
      </div>`
    : html`<div class="trend-card"><div class="trend-note">Not enough studies in the current filter to fit a trend (need ≥3).</div></div>`;

  const wrap = html`<div></div>`;
  wrap.append(statsCard, el);
  return wrap;
}
```

```js
// Re-render the cube whenever any reactive input changes. The initial render is
// kicked off by the markdown IIFE that mounts <div id="cube">; subsequent updates
// rely on this block.
{
  jitter; viewMode; colorMode; conditionField; filteredStudies;
  const _div = document.querySelector("#cube");
  if (_div) renderCube(_div);
}
```

## How each dimension developed over time

Coloured line = yearly **median**; shaded band = **Q1–Q3 (interquartile range)**. Black line = OLS linear trend on individual studies (years with more papers contribute proportionally more, accounting for uneven sample size per year). Click any dot to load that study into the detail panel.

<style>
  .trend-card { background: var(--theme-background-alt, #f7f5f1); border: 1px solid var(--theme-foreground-faintest, #e3dfd6);
                border-radius: 10px; padding: 10px 14px; margin-bottom: 10px; font-size: 0.88rem; }
  .trend-line { display: flex; flex-wrap: wrap; align-items: baseline; gap: 14px; }
  .trend-label { font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; font-size: 0.74rem;
                 color: var(--theme-foreground-muted, #7a766d); }
  .trend-stat { font-variant-numeric: tabular-nums; }
  .trend-stat.sig b { color: #2a7; }
  .trend-unit { color: var(--theme-foreground-muted, #7a766d); margin-left: 2px; font-size: 0.82rem; }
  .trend-ci { color: var(--theme-foreground-muted, #7a766d); margin-left: 6px; font-size: 0.82rem; }
  .trend-muted { color: var(--theme-foreground-muted, #7a766d); }
  .trend-note { color: var(--theme-foreground-muted, #7a766d); font-size: 0.82rem; margin-top: 6px; line-height: 1.45; }
</style>

```js
const timelineDim = view(Inputs.radio(Object.keys(TIMELINE_DIMS), {label: "Y-axis", value: "Behavioural complexity"}));
```

<div class="viewer-shell">
  <div class="viewer-left">${timelineChart(timelineDim)}</div>
  <div class="viewer-right">${renderDetail(selected)}</div>
</div>

```js
function renderGroupDetail(name) {
  const matching = filteredStudies.filter(s =>
    (s.assays || []).some(a => a.canonical === name || a.category === name)
  );
  const sorted = [...matching].sort((a, b) => (a.study_id || "").localeCompare(b.study_id || ""));
  return html`<div class="detail-body">
    <div class="detail-header">
      <h2>${name}</h2>
      <div class="meta">
        <span class="tag psychedelic">${matching.length} studies</span>
      </div>
    </div>
    <h3>Studies</h3>
    <div style="font-size:0.9rem;line-height:1.7;">
      ${sorted.map(s => html`<a href="study/${String(s._stem).toLowerCase().replace(/[^a-z0-9]/g, "")}" class="tag muted">${s.study_id}</a> `)}
    </div>
  </div>`;
}
```

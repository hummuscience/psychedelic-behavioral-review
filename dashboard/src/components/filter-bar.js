// filter-bar.js — Sentence-style filter for the Psychedelic-Behavioural-Review dashboard.
// Drop into Observable Framework: import {filterBar} from './components/filter-bar.js'.
//
// Usage in a .md file (via filters.js wrapper):
//   const _filters = mountFilters(studies, {Inputs, html, Generators});
//   display(_filters.node);
//   const filteredStudies = _filters.filtered;  // reactive
//
// Direct usage:
//   const fb = filterBar({initial, total, yearMin, yearMax, yearHist, counts, matchedCount});
//   display(fb.node);
//   const filters = Generators.observe(fb.subscribe);  // reactive {yearFrom,yearTo,species,sexes,compounds,matches}

import {html} from "npm:htl";
import {compoundsOf, BUCKET_ORDER} from "./dose-utils.js";

// ─── Schema ──────────────────────────────────────────────────────────────────
export const SPECIES = [
  {id: "mouse",        label: "mouse"},
  {id: "rat",          label: "rat"},
  {id: "mouse and rat",label: "mouse & rat"},
  {id: "other",        label: "other"},
  {id: "not reported", label: "not reported"},
];

export const SEXES = [
  {id: "male only",   label: "male only"},
  {id: "female only", label: "female only"},
  {id: "both sexes",  label: "both sexes"},
  {id: "not reported",label: "not reported"},
];

export const COMPOUNDS = [
  ...BUCKET_ORDER.map(id => ({id, label: id})),
  {id: "(other)", label: "other"},
];

export const YEAR_MIN_DEFAULT = 1965;
export const YEAR_MAX_DEFAULT = 2025;

export const ASSAY_CATEGORY_ORDER = [
  "Psychedelic response",
  "Anxiety",
  "Depression / anhedonia",
  "Locomotor / motor",
  "Cognition / memory",
  "Social behaviour",
  "Addiction / substance use",
  "Pain",
  "Sensorimotor",
  "Physiological",
  "Miscellaneous",
];

// ─── Normalisation helpers (mirror filters.js) ────────────────────────────────
export function normalizeSpecies(raw) {
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

export function normalizeSex(raw) {
  const s = String(raw ?? "").toLowerCase().trim();
  if (!s) return "not reported";
  if (s.includes("both")) return "both sexes";
  if (s.includes("female")) return "female only";
  if (s.includes("male")) return "male only";
  return "not reported";
}

const yearOf = s => +(s.study_id || "").match(/(\d{4})/)?.[1] || s.pub_year || 0;

// ─── Filter predicate ─────────────────────────────────────────────────────────
export function makeMatcher(state) {
  return (study) => {
    const y = yearOf(study);
    if (y && (y < state.yearFrom || y > state.yearTo)) return false;
    if (!state.species.has(normalizeSpecies(study.species))) return false;
    if (!state.sexes.has(normalizeSex(study.sex))) return false;
    if (state.compounds.size > 0 && state.compounds.size < COMPOUNDS.length) {
      const cs = compoundsOf(study);
      if (!cs.some(c => state.compounds.has(c))) return false;
    } else if (state.compounds.size === 0) {
      return false;
    }
    if (state.assayCategories.size > 0 || state.assayCanonicals.size > 0) {
      const assays = study.assays || [];
      const pass = assays.some(a => {
        const catOk = state.assayCategories.size === 0 || state.assayCategories.has(a.category);
        const canOk = state.assayCanonicals.size === 0 || state.assayCanonicals.has(a.canonical);
        return catOk && canOk;
      });
      if (!pass) return false;
    }
    return true;
  };
}

// ─── State helpers ─────────────────────────────────────────────────────────────
export function makeDefaults({yearMin = YEAR_MIN_DEFAULT, yearMax = YEAR_MAX_DEFAULT} = {}) {
  return {
    yearFrom:        yearMin,
    yearTo:          yearMax,
    species:         new Set(SPECIES.map(s => s.id)),
    sexes:           new Set(SEXES.map(s => s.id)),
    compounds:       new Set(COMPOUNDS.map(c => c.id)),
    assayCategories: new Set(),   // empty = all categories
    assayCanonicals: new Set(),   // empty = all specific assays
  };
}

export function isDefault(f, {yearMin = YEAR_MIN_DEFAULT, yearMax = YEAR_MAX_DEFAULT} = {}) {
  return f.yearFrom === yearMin
      && f.yearTo === yearMax
      && f.species.size === SPECIES.length
      && f.sexes.size === SEXES.length
      && f.compounds.size === COMPOUNDS.length
      && f.assayCategories.size === 0
      && f.assayCanonicals.size === 0;
}

export function filtersToUrl(f, defaults = makeDefaults()) {
  const p = new URLSearchParams();
  if (f.yearFrom !== defaults.yearFrom) p.set("from", f.yearFrom);
  if (f.yearTo !== defaults.yearTo)     p.set("to",   f.yearTo);
  if (f.species.size !== SPECIES.length) p.set("sp", [...f.species].join(","));
  if (f.sexes.size !== SEXES.length)     p.set("sx", [...f.sexes].join(","));
  if (f.compounds.size !== COMPOUNDS.length) p.set("c", [...f.compounds].join(","));
  if (f.assayCategories.size > 0)        p.set("ac",  [...f.assayCategories].join("|"));
  if (f.assayCanonicals.size > 0)        p.set("aa",  [...f.assayCanonicals].join("|"));
  return p.toString();
}

export function filtersFromUrl(search, defaults) {
  const d = defaults ?? makeDefaults();
  const p = new URLSearchParams(search);
  const f = {
    yearFrom:        d.yearFrom,
    yearTo:          d.yearTo,
    species:         new Set(d.species),
    sexes:           new Set(d.sexes),
    compounds:       new Set(d.compounds),
    assayCategories: new Set(d.assayCategories),
    assayCanonicals: new Set(d.assayCanonicals),
  };
  if (p.has("from")) f.yearFrom = +p.get("from");
  if (p.has("to"))   f.yearTo   = +p.get("to");
  if (p.has("sp"))   f.species  = new Set(p.get("sp").split(",").filter(Boolean));
  if (p.has("sx"))   f.sexes    = new Set(p.get("sx").split(",").filter(Boolean));
  if (p.has("c"))    f.compounds= new Set(p.get("c").split(",").filter(Boolean));
  if (p.has("ac"))   f.assayCategories = new Set(p.get("ac").split("|").filter(Boolean));
  if (p.has("aa"))   f.assayCanonicals = new Set(p.get("aa").split("|").filter(Boolean));
  return f;
}

// ─── DOM helpers ───────────────────────────────────────────────────────────────
function svgEl(tag, attrs = {}) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

function toggleSet(set, id) {
  const next = new Set(set);
  if (next.has(id)) next.delete(id); else next.add(id);
  return next;
}

// Year histogram sparkline with highlighted range.
function yearSpark(yearHist, yearMin, yearMax, from, to, width = 276, height = 42) {
  const years = [];
  for (let y = yearMin; y <= yearMax; y++) years.push(y);
  const max = Math.max(1, ...years.map(y => yearHist[y] || 0));
  const bw = width / years.length;
  const root = svgEl("svg", {width, height, style: "display:block"});
  for (let i = 0; i < years.length; i++) {
    const y = years[i];
    const h = ((yearHist[y] || 0) / max) * (height - 2);
    const sel = y >= from && y <= to;
    root.appendChild(svgEl("rect", {
      x: i * bw + 0.5,
      y: height - h - 1,
      width: Math.max(1, bw - 1),
      height: Math.max(1, h),
      fill: sel ? "var(--fb-accent)" : "var(--fb-ink-3)",
      "fill-opacity": sel ? 1 : 0.28,
    }));
  }
  return root;
}

// Dual-handle range slider.
function rangeSlider({min, max, from, to, width = 276, onChange}) {
  const root = html`<div class="fb-range" style=${`width:${width}px`}></div>`;
  const track = html`<div class="fb-range-track"></div>`;
  const fill  = html`<div class="fb-range-fill"></div>`;
  const hFrom = html`<div class="fb-range-handle" data-h="from"></div>`;
  const hTo   = html`<div class="fb-range-handle" data-h="to"></div>`;
  root.append(track, fill, hFrom, hTo);

  const layout = () => {
    const pf = ((from - min) / (max - min)) * 100;
    const pt = ((to   - min) / (max - min)) * 100;
    fill.style.left  = `${pf}%`;
    fill.style.width = `${pt - pf}%`;
    hFrom.style.left = `${pf}%`;
    hTo.style.left   = `${pt}%`;
  };
  layout();

  let dragging = null;
  const startDrag = (which) => (e) => {
    e.preventDefault();
    dragging = which;
    document.body.style.userSelect = "none";
  };
  const move = (e) => {
    if (!dragging) return;
    const r = root.getBoundingClientRect();
    const x = (e.clientX ?? e.touches?.[0]?.clientX) - r.left;
    const t = Math.max(0, Math.min(1, x / r.width));
    const v = Math.round(min + t * (max - min));
    if (dragging === "from") from = Math.min(v, to);
    else                     to   = Math.max(v, from);
    layout();
    onChange(from, to);
  };
  const up = () => { dragging = null; document.body.style.userSelect = ""; };
  hFrom.addEventListener("mousedown", startDrag("from"));
  hFrom.addEventListener("touchstart", startDrag("from"), {passive: false});
  hTo.addEventListener("mousedown", startDrag("to"));
  hTo.addEventListener("touchstart", startDrag("to"), {passive: false});
  window.addEventListener("mousemove", move);
  window.addEventListener("touchmove", move);
  window.addEventListener("mouseup", up);
  window.addEventListener("touchend", up);

  return {
    node: root,
    update(newFrom, newTo) { from = newFrom; to = newTo; layout(); },
    destroy() {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("touchmove", move);
      window.removeEventListener("mouseup", up);
      window.removeEventListener("touchend", up);
    },
  };
}

// Outside-click + Escape closer.
function attachOutsideClose(popover, onClose) {
  const onDoc = (e) => { if (!popover.contains(e.target)) onClose(); };
  const onKey = (e) => { if (e.key === "Escape") onClose(); };
  setTimeout(() => {
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
  }, 0);
  return () => {
    document.removeEventListener("mousedown", onDoc);
    document.removeEventListener("keydown", onKey);
  };
}

// One-time CSS injection — light + dark theme.
function injectCSS() {
  if (document.getElementById("fb-styles")) return;
  const s = document.createElement("style");
  s.id = "fb-styles";
  s.textContent = `
/* ── Filter bar light theme ─────────────────────────── */
.fb-root {
  --fb-paper:   #f7f5f1;
  --fb-pop-bg:  #ffffff;
  --fb-ink:     #1c1a17;
  --fb-ink-2:   #4a463f;
  --fb-ink-3:   #7a766d;
  --fb-ink-4:   #a9a59c;
  --fb-rule:    #e3dfd6;
  --fb-rule-2:  #d2cdc1;
  --fb-accent:       oklch(58% 0.18 255);
  --fb-accent-2:     oklch(58% 0.18 255 / 0.12);
  --fb-accent-3:     oklch(58% 0.18 255 / 0.28);
  background: var(--fb-paper);
  border: 1px solid var(--fb-rule);
  border-radius: 12px;
  padding: 18px 22px;
  display: flex; align-items: center; gap: 24px; flex-wrap: wrap;
  font-family: ui-sans-serif, system-ui, sans-serif;
  color: var(--fb-ink);
  margin: 8px 0 20px;
}
/* ── Dark mode overrides ────────────────────────────── */
.observablehq-dark .fb-root {
  --fb-paper:   #1e1c19;
  --fb-pop-bg:  #272420;
  --fb-ink:     #ede9e1;
  --fb-ink-2:   #b8b4ac;
  --fb-ink-3:   #7a766d;
  --fb-ink-4:   #4a463e;
  --fb-rule:    #2e2c28;
  --fb-rule-2:  #3a3830;
}
.fb-count { flex-shrink: 0; padding-right: 20px; border-right: 1px solid var(--fb-rule); }
.fb-count-num {
  font-family: ui-monospace, "IBM Plex Mono", monospace;
  font-variant-numeric: tabular-nums;
  font-size: 42px; font-weight: 600; line-height: 1; letter-spacing: -0.03em;
}
.fb-count-label {
  font-family: ui-monospace, "IBM Plex Mono", monospace;
  font-size: 10px; color: var(--fb-ink-3);
  margin-top: 6px; letter-spacing: 0.06em; text-transform: uppercase;
}
.fb-count-total { color: var(--fb-ink-4); }
.fb-sentence {
  flex: 1; font-size: 16px; line-height: 1.8; color: var(--fb-ink-2);
  font-weight: 400; min-width: 260px;
}
.fb-token {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 1px 7px; margin: 0 1px;
  border-radius: 5px; border: 0;
  background: rgba(128,128,128,0.07);
  color: var(--fb-ink);
  font: inherit; font-weight: 500;
  cursor: pointer;
  text-decoration: underline; text-underline-offset: 3px;
  text-decoration-thickness: 1px; text-decoration-color: var(--fb-ink-4);
  transition: background .1s, color .1s;
}
.fb-token:hover { background: rgba(128,128,128,0.13); }
.fb-token[data-active="true"] {
  background: var(--fb-accent-2);
  color: var(--fb-accent);
  font-weight: 600;
  text-decoration-color: var(--fb-accent);
}
.fb-token[data-open="true"] {
  background: var(--fb-accent-2);
  box-shadow: 0 0 0 3px var(--fb-accent-3);
  outline: none;
}
.fb-chev { opacity: 0.45; }
.fb-pop {
  position: absolute; top: calc(100% + 6px); left: 0;
  background: var(--fb-pop-bg);
  border: 1px solid var(--fb-rule);
  border-radius: 10px;
  box-shadow: 0 12px 36px rgba(0,0,0,0.14);
  padding: 12px; z-index: 200;
  font-size: 12.5px; font-weight: 400; color: var(--fb-ink);
  text-align: left; letter-spacing: 0;
}
.fb-pop-bar {
  display: flex; justify-content: space-between; align-items: center;
  font-size: 11px; margin-bottom: 8px;
}
.fb-pop-link {
  border: 0; background: transparent; cursor: pointer;
  color: var(--fb-ink-3); font: inherit; padding: 2px 4px;
  text-decoration: underline; text-underline-offset: 2px;
}
.fb-pop-link:hover { color: var(--fb-ink); }
.fb-pop-list { display: flex; flex-direction: column; gap: 1px; }
.fb-pop-item {
  display: flex; align-items: center; gap: 9px;
  padding: 6px 8px; border-radius: 6px; cursor: pointer;
  font-size: 12.5px; user-select: none;
}
.fb-pop-item:hover { background: rgba(128,128,128,0.07); }
.fb-pop-item[data-on="true"] { background: var(--fb-accent-2); }
.fb-pop-item[data-on="true"] .fb-pop-name { color: var(--fb-accent); font-weight: 500; }
.fb-pop-item input { accent-color: var(--fb-accent); margin: 0; flex-shrink: 0; }
.fb-pop-name { flex: 1; }
.fb-pop-n {
  font-family: ui-monospace, "IBM Plex Mono", monospace;
  color: var(--fb-ink-3); font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.fb-year-readout {
  display: flex; justify-content: space-between;
  font-size: 11.5px; color: var(--fb-ink-3); margin-bottom: 6px;
  font-family: ui-monospace, "IBM Plex Mono", monospace;
  font-variant-numeric: tabular-nums;
}
.fb-year-presets { display: flex; gap: 4px; margin-top: 10px; }
.fb-year-presets button {
  padding: 3px 8px; font-size: 11px; border-radius: 4px;
  border: 1px solid var(--fb-rule); background: var(--fb-pop-bg);
  color: var(--fb-ink-2); cursor: pointer; font: inherit;
}
.fb-year-presets button:hover { background: var(--fb-paper); }
.fb-range {
  position: relative; height: 22px; margin-top: 4px;
  cursor: pointer; user-select: none;
}
.fb-range-track {
  position: absolute; left: 0; right: 0; top: 10px;
  height: 2px; background: var(--fb-rule-2); border-radius: 1px;
}
.fb-range-fill {
  position: absolute; top: 10px; height: 2px;
  background: var(--fb-accent);
}
.fb-range-handle {
  position: absolute; top: 11px;
  width: 14px; height: 14px; margin-left: -7px; margin-top: -7px;
  background: var(--fb-pop-bg); border: 1.5px solid var(--fb-accent);
  border-radius: 999px; box-shadow: 0 1px 3px rgba(0,0,0,0.15);
  cursor: grab;
}
.fb-range-handle:active { cursor: grabbing; }
.fb-reset {
  display: flex; align-items: center; gap: 5px;
  padding: 5px 10px; border-radius: 6px;
  border: 1px solid var(--fb-rule); background: var(--fb-pop-bg);
  color: var(--fb-ink-2); font-size: 11.5px; font-weight: 500;
  cursor: pointer; flex-shrink: 0; font-family: inherit;
}
.fb-reset:hover { background: var(--fb-paper); }
`;
  document.head.appendChild(s);
}

// ─── Main export ──────────────────────────────────────────────────────────────
//
// filterBar({initial, total, yearMin, yearMax, yearHist, counts, assayCatalog, matchedCount})
//   initial      — filter state (defaults to makeDefaults())
//   total        — total study count for the "of N" label
//   yearMin/Max  — bounds for the year slider
//   yearHist     — {[year]: studyCount} for the popover sparkline
//   counts       — {species:{id:n}, sexes:{id:n}, compounds:{id:n},
//                   assayCategories:{cat:n}, assayCanonicals:{canonical:n}}
//   assayCatalog — [{canonical, category, count}] sorted by category+count
//   matchedCount — fn(state) → number; if omitted shows `total`
//
// returns { node, getState, setState, subscribe(notify) }
export function filterBar({
  initial,
  total = 0,
  yearMin = YEAR_MIN_DEFAULT,
  yearMax = YEAR_MAX_DEFAULT,
  yearHist = {},
  counts = {species: {}, sexes: {}, compounds: {}, assayCategories: {}, assayCanonicals: {}},
  assayCatalog = [],
  matchedCount = null,
} = {}) {
  injectCSS();

  let state = initial ?? makeDefaults({yearMin, yearMax});
  const subscribers = new Set();
  const stateWithMatcher = () => Object.assign({}, state, {matches: makeMatcher(state)});
  const notifyAll = () => {
    const snap = stateWithMatcher();
    for (const fn of subscribers) fn(snap);
  };

  let openToken = null;
  let detachOutside = null;

  const root = html`<div class="fb-root"></div>`;
  const countNum   = html`<div class="fb-count-num">0</div>`;
  const countLabel = html`<div class="fb-count-label">studies <span class="fb-count-total">of ${total}</span></div>`;
  root.append(html`<div class="fb-count">${countNum}${countLabel}</div>`);

  const sentence = html`<div class="fb-sentence"></div>`;
  root.append(sentence);

  const resetBtn = html`<button class="fb-reset" type="button">${resetIcon()} Reset</button>`;
  resetBtn.addEventListener("click", () => { state = makeDefaults({yearMin, yearMax}); rerender(); });
  root.append(resetBtn);

  function rerender() {
    const matched = matchedCount ? matchedCount(state) : total;
    countNum.textContent = matched.toLocaleString();

    sentence.replaceChildren(
      document.createTextNode("Showing rodent studies from "),
      tokenYear(),
      document.createTextNode(", in "),
      tokenSet("species", "any species", SPECIES, state.species, "species",
        (id) => { state.species = toggleSet(state.species, id); }),
      document.createTextNode(", "),
      tokenSet("sex", "any sex", SEXES, state.sexes, "sexes",
        (id) => { state.sexes = toggleSet(state.sexes, id); }),
      document.createTextNode(", treated with "),
      tokenSet("compound", "any compound", COMPOUNDS, state.compounds, "compounds",
        (id) => { state.compounds = toggleSet(state.compounds, id); }),
      document.createTextNode(", using "),
      tokenAssay(),
      document.createTextNode("."),
    );

    resetBtn.style.display = isDefault(state, {yearMin, yearMax}) ? "none" : "";
    notifyAll();
  }

  // ─── Token builders ──────────────────────────────────────────────────────
  function tokenYear() {
    const isActive = state.yearFrom !== yearMin || state.yearTo !== yearMax;
    const phrase =
      !isActive ? "all years"
      : state.yearFrom === state.yearTo ? `${state.yearFrom}`
      : `${state.yearFrom}–${state.yearTo}`;
    const wrap = html`<span style="position:relative;display:inline-block"></span>`;
    const btn = html`<button class="fb-token" type="button"
      data-active=${isActive} data-open=${openToken === "year"}>
      ${phrase}${chevIcon()}
    </button>`;
    btn.addEventListener("click", (e) => { e.stopPropagation(); openPop("year", wrap); });
    wrap.append(btn);
    if (openToken === "year") wrap.append(buildYearPop());
    return wrap;
  }

  function tokenSet(key, anyLabel, items, selected, stateField, onToggle, {emptyMeansAll = true} = {}) {
    const isAll   = selected.size === items.length;
    const isEmpty = selected.size === 0;
    const isActive = emptyMeansAll ? !isAll : !isEmpty;
    const phrase = emptyMeansAll
      ? (isAll ? anyLabel
         : isEmpty ? `no ${key}`
         : [...selected].map(id => items.find(x => x.id === id)?.label ?? id).join(" or "))
      : (isEmpty ? anyLabel
         : selected.size === 1
           ? items.find(x => selected.has(x.id))?.label ?? [...selected][0]
           : `${selected.size} compounds`);
    const wrap = html`<span style="position:relative;display:inline-block"></span>`;
    const btn = html`<button class="fb-token" type="button"
      data-active=${isActive} data-open=${openToken === key}>
      ${phrase}${chevIcon()}
    </button>`;
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openPop(key, wrap);
    });
    wrap.append(btn);
    if (openToken === key) wrap.append(buildCheckPop(items, selected, stateField, counts[stateField] || {}, key));
    return wrap;
  }

  function tokenAssay() {
    const allCats = [...ASSAY_CATEGORY_ORDER].filter(c => counts.assayCategories?.[c]);
    const noCat = state.assayCategories.size === 0;
    const allCat = state.assayCategories.size === allCats.length && allCats.every(c => state.assayCategories.has(c));
    const visibleCanonicals = (state.assayCategories.size > 0
      ? assayCatalog.filter(e => state.assayCategories.has(e.category))
      : assayCatalog).map(e => e.canonical);
    const noCan = state.assayCanonicals.size === 0;
    const allCan = visibleCanonicals.length > 0
      && state.assayCanonicals.size === visibleCanonicals.length
      && visibleCanonicals.every(c => state.assayCanonicals.has(c));
    const isActive = (!noCat && !allCat) || (!noCan && !allCan);
    let phrase;
    if (!isActive) {
      phrase = "any assay";
    } else if (!noCan && !allCan) {
      const names = [...state.assayCanonicals];
      phrase = names.length <= 2 ? names.join(", ") : `${names.length} assays`;
    } else {
      const cats = [...state.assayCategories];
      phrase = cats.length === 1 ? cats[0] : `${cats.length} categories`;
    }
    const wrap = html`<span style="position:relative;display:inline-block"></span>`;
    const btn = html`<button class="fb-token" type="button"
      data-active=${isActive} data-open=${openToken === "assay"}>
      ${phrase}${chevIcon()}
    </button>`;
    btn.addEventListener("click", (e) => { e.stopPropagation(); openPop("assay", wrap); });
    wrap.append(btn);
    if (openToken === "assay") wrap.append(buildAssayPop());
    return wrap;
  }

  function buildAssayPop() {
    const pop = html`<div class="fb-pop" style="width:340px;max-height:480px;overflow-y:auto"></div>`;

    // ── Category section ──────────────────────────────────────────────────
    const catBar = html`<div class="fb-pop-bar"><b style="font-size:11px;text-transform:uppercase;letter-spacing:0.06em;color:var(--fb-ink-3)">Category</b></div>`;
    const catAllBtn = html`<button class="fb-pop-link" type="button">all</button>`;
    const catClrBtn = html`<button class="fb-pop-link" type="button">clear</button>`;
    catAllBtn.addEventListener("click", () => {
      state.assayCategories = new Set([...ASSAY_CATEGORY_ORDER].filter(c => counts.assayCategories?.[c]));
      state.assayCanonicals = new Set();
      rerender(); reopen("assay");
    });
    catClrBtn.addEventListener("click", () => { state.assayCategories = new Set(); state.assayCanonicals = new Set(); rerender(); reopen("assay"); });
    const catBtnGroup = html`<span style="display:flex;gap:4px"></span>`;
    catBtnGroup.append(catAllBtn, catClrBtn);
    catBar.append(catBtnGroup);
    pop.append(catBar);

    const catList = html`<div class="fb-pop-list" style="margin-bottom:10px"></div>`;
    const orderedCats = [...ASSAY_CATEGORY_ORDER].filter(c => counts.assayCategories?.[c]);
    for (const cat of orderedCats) {
      const on = state.assayCategories.has(cat);
      const n = counts.assayCategories?.[cat] ?? 0;
      const row = html`<label class="fb-pop-item" data-on=${on}>
        <input type="checkbox" checked=${on}>
        <span class="fb-pop-name">${cat}</span>
        <span class="fb-pop-n">${n}</span>
      </label>`;
      row.querySelector("input").addEventListener("change", () => {
        state.assayCategories = toggleSet(state.assayCategories, cat);
        // Clear specific assay selections that no longer match selected categories
        if (state.assayCategories.size > 0 && state.assayCanonicals.size > 0) {
          const validCats = state.assayCategories;
          state.assayCanonicals = new Set(
            [...state.assayCanonicals].filter(can => {
              const entry = assayCatalog.find(e => e.canonical === can);
              return entry && validCats.has(entry.category);
            })
          );
        }
        rerender(); reopen("assay");
      });
      catList.append(row);
    }
    pop.append(catList);

    // ── Specific assay section ─────────────────────────────────────────────
    const rule = html`<hr style="border:0;border-top:1px solid var(--fb-rule);margin:4px 0 8px">`;
    pop.append(rule);

    const visibleAssays = state.assayCategories.size > 0
      ? assayCatalog.filter(e => state.assayCategories.has(e.category))
      : assayCatalog;

    const assayBar = html`<div class="fb-pop-bar"><b style="font-size:11px;text-transform:uppercase;letter-spacing:0.06em;color:var(--fb-ink-3)">Specific assay</b></div>`;
    const assayAllBtn = html`<button class="fb-pop-link" type="button">all</button>`;
    const assayClrBtn = html`<button class="fb-pop-link" type="button">clear</button>`;
    assayAllBtn.addEventListener("click", () => {
      state.assayCanonicals = new Set(visibleAssays.map(e => e.canonical));
      rerender(); reopen("assay");
    });
    assayClrBtn.addEventListener("click", () => { state.assayCanonicals = new Set(); rerender(); reopen("assay"); });
    const assayBtnGroup = html`<span style="display:flex;gap:4px"></span>`;
    assayBtnGroup.append(assayAllBtn, assayClrBtn);
    assayBar.append(assayBtnGroup);
    pop.append(assayBar);

    const assayList = html`<div class="fb-pop-list"></div>`;
    for (const entry of visibleAssays) {
      const on = state.assayCanonicals.has(entry.canonical);
      const n = counts.assayCanonicals?.[entry.canonical] ?? entry.count ?? 0;
      const row = html`<label class="fb-pop-item" data-on=${on} title="${entry.category}">
        <input type="checkbox" checked=${on}>
        <span class="fb-pop-name" style="font-size:12px">${entry.canonical}</span>
        <span class="fb-pop-n">${n}</span>
      </label>`;
      row.querySelector("input").addEventListener("change", () => {
        state.assayCanonicals = toggleSet(state.assayCanonicals, entry.canonical);
        rerender(); reopen("assay");
      });
      assayList.append(row);
    }
    pop.append(assayList);

    pop.addEventListener("mousedown", (e) => e.stopPropagation());
    detachOutside = attachOutsideClose(pop, () => closePop());
    return pop;
  }

  function openPop(key) {
    if (openToken === key) { closePop(); return; }
    closePop();
    openToken = key;
    rerender();
  }
  function closePop() {
    if (detachOutside) { detachOutside(); detachOutside = null; }
    if (openToken !== null) { openToken = null; rerender(); }
  }

  function buildYearPop() {
    const pop = html`<div class="fb-pop" style="width:304px"></div>`;
    const readout = html`<div class="fb-year-readout">
      <span>${state.yearFrom}</span><span>${state.yearTo}</span>
    </div>`;
    pop.append(readout, yearSpark(yearHist, yearMin, yearMax, state.yearFrom, state.yearTo, 280, 42));

    const range = rangeSlider({
      min: yearMin, max: yearMax,
      from: state.yearFrom, to: state.yearTo,
      width: 280,
      onChange: (a, b) => {
        state.yearFrom = a; state.yearTo = b;
        readout.replaceChildren(html`<span>${a}</span>`, html`<span>${b}</span>`);
        const oldSpark = pop.querySelector("svg");
        oldSpark.replaceWith(yearSpark(yearHist, yearMin, yearMax, a, b, 280, 42));
        const matched = matchedCount ? matchedCount(state) : total;
        countNum.textContent = matched.toLocaleString();
        resetBtn.style.display = isDefault(state, {yearMin, yearMax}) ? "none" : "";
        notifyAll();
      },
    });
    pop.append(range.node);

    const presets = html`<div class="fb-year-presets"></div>`;
    for (const [a, b, l] of [
      [yearMax - 4, yearMax, "last 5y"],
      [yearMax - 9, yearMax, "last 10y"],
      [yearMin, yearMax, "all"],
    ]) {
      const pb = html`<button type="button">${l}</button>`;
      pb.addEventListener("click", () => { state.yearFrom = a; state.yearTo = b; rerender(); reopen("year"); });
      presets.append(pb);
    }
    pop.append(presets);
    pop.addEventListener("mousedown", (e) => e.stopPropagation());
    detachOutside = attachOutsideClose(pop, () => closePop());
    return pop;
  }

  function buildCheckPop(items, selectedSet, stateField, perCounts, key) {
    const pop = html`<div class="fb-pop" style="min-width:200px"></div>`;
    const bar = html`<div class="fb-pop-bar"></div>`;
    const allBtn = html`<button class="fb-pop-link" type="button">all</button>`;
    const clrBtn = html`<button class="fb-pop-link" type="button">clear</button>`;
    allBtn.addEventListener("click", () => { state[stateField] = new Set(items.map(i => i.id)); rerender(); reopen(key); });
    clrBtn.addEventListener("click", () => { state[stateField] = new Set(); rerender(); reopen(key); });
    bar.append(allBtn, clrBtn);
    pop.append(bar);
    const list = html`<div class="fb-pop-list"></div>`;
    for (const it of items) {
      const on = selectedSet.has(it.id);
      const n = perCounts[it.id];
      const row = html`<label class="fb-pop-item" data-on=${on}>
        <input type="checkbox" checked=${on}>
        <span class="fb-pop-name">${it.label}</span>
        ${n != null ? html`<span class="fb-pop-n">${n}</span>` : ""}
      </label>`;
      row.querySelector("input").addEventListener("change", () => {
        state[stateField] = toggleSet(selectedSet, it.id);
        rerender(); reopen(key);
      });
      list.append(row);
    }
    pop.append(list);
    pop.addEventListener("mousedown", (e) => e.stopPropagation());
    detachOutside = attachOutsideClose(pop, () => closePop());
    return pop;
  }

  function reopen(key) { openToken = key; rerender(); }

  rerender();

  return {
    node: root,
    getState: () => stateWithMatcher(),
    setState: (s) => { state = s; rerender(); },
    subscribe(change) {
      change(stateWithMatcher());
      subscribers.add(change);
      return () => subscribers.delete(change);
    },
  };
}

// ─── Tiny inline SVG icons ────────────────────────────────────────────────────
function chevIcon() {
  const s = svgEl("svg", {width: 10, height: 10, viewBox: "0 0 10 10",
    fill: "none", stroke: "currentColor", "stroke-width": 1.5,
    "stroke-linecap": "round", "stroke-linejoin": "round", class: "fb-chev"});
  s.appendChild(svgEl("path", {d: "M2 3.5l3 3 3-3"}));
  return s;
}
function resetIcon() {
  const s = svgEl("svg", {width: 12, height: 12, viewBox: "0 0 12 12",
    fill: "none", stroke: "currentColor", "stroke-width": 1.5,
    "stroke-linecap": "round", "stroke-linejoin": "round"});
  s.appendChild(svgEl("path", {d: "M2.5 6a3.5 3.5 0 1 0 1-2.5"}));
  s.appendChild(svgEl("path", {d: "M2 2v2.2H4.2"}));
  return s;
}

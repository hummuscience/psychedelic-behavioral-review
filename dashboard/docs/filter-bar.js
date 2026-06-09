// filter-bar.js — Sentence/query filter for the Psychedelic-Behavioural-Review dashboard.
// Drop into Observable Framework: import { filterBar } from './filter-bar.js'.
// Exposes a reactive `filters` value via Generators.observe so every other
// cell that references `filters` re-runs when the user mutates a token.
//
// Usage in a .md file:
//   ```js
//   import {filterBar} from "./components/filter-bar.js";
//   const fb = filterBar({initial: parseUrlFilters()});
//   display(fb.node);
//   const filters = Generators.observe(fb.subscribe);   // reactive
//   ```
//
// `filters` shape:
//   {
//     yearFrom: number, yearTo: number,
//     species:   Set<'mouse'|'rat'|'other'|'not_reported'>,
//     sexes:     Set<'male'|'female'|'not_reported'>,
//     compounds: Set<string>,           // empty = "any"
//     matches(study): boolean,          // filter helper
//   }
//
// Inclusive semantics:
//   - species "mouse + rat" study counts under BOTH mouse and rat
//   - sex "both sexes" study counts under BOTH male and female
//   - compounds: empty Set = match anything; otherwise study must use ≥1

// htl: in Observable Framework `npm:htl` resolves at build time. In a plain
// browser (or for the standalone preview) we fall back to esm.sh. Framework
// rewrites bare imports during build, but esm.sh works as-is in dev preview.
import {html} from "https://esm.sh/htl@0.3.1";

// ─── Schema ─────────────────────────────────────────────────────────────
export const SPECIES = [
  {id: "mouse",        label: "mouse"},
  {id: "rat",          label: "rat"},
  {id: "other",        label: "other"},
  {id: "not_reported", label: "not reported"},
];

export const SEXES = [
  {id: "male",         label: "male"},
  {id: "female",       label: "female"},
  {id: "not_reported", label: "not reported"},
];

export const COMPOUNDS = [
  {id: "psilocybin",  label: "psilocybin"},
  {id: "lsd",         label: "LSD"},
  {id: "doi",         label: "DOI"},
  {id: "dmt",         label: "DMT"},
  {id: "5meo_dmt",    label: "5-MeO-DMT"},
  {id: "nbome",       label: "NBOMe / NBOH"},
  {id: "ibogaine",    label: "ibogaine"},
  {id: "mescaline",   label: "mescaline"},
  {id: "other",       label: "other"},
];

export const YEAR_MIN_DEFAULT = 1965;
export const YEAR_MAX_DEFAULT = 2025;

// ─── Schema-aware predicate helpers ─────────────────────────────────────
// Map a study's raw species/sex schema value to the inclusive UI buckets
// it falls under. Adjust the right-hand sets to match your data exactly.
function speciesBuckets(rawSpecies) {
  // raw values: "mouse" | "rat" | "mouse and rat" | "other" | "not reported"
  switch ((rawSpecies || "").toLowerCase().trim()) {
    case "mouse":          return ["mouse"];
    case "rat":            return ["rat"];
    case "mouse and rat":  return ["mouse", "rat"];
    case "other":          return ["other"];
    default:               return ["not_reported"];
  }
}

function sexBuckets(rawSex) {
  // raw values: "male only" | "female only" | "both sexes" | "not reported"
  switch ((rawSex || "").toLowerCase().trim()) {
    case "male only":   return ["male"];
    case "female only": return ["female"];
    case "both sexes":  return ["male", "female"];
    default:            return ["not_reported"];
  }
}

// Public predicate: given a `filters` object and a study row, return bool.
function makeMatcher(state) {
  return (study) => {
    if (study.pub_year < state.yearFrom || study.pub_year > state.yearTo) return false;
    const sb = speciesBuckets(study.species);
    if (!sb.some(b => state.species.has(b))) return false;
    const xb = sexBuckets(study.sex);
    if (!xb.some(b => state.sexes.has(b))) return false;
    if (state.compounds.size > 0) {
      const studyCompounds = (study.psychedelic || "").split(",").map(s => s.trim().toLowerCase());
      const wanted = [...state.compounds];
      if (!wanted.some(w => studyCompounds.includes(w))) return false;
    }
    return true;
  };
}

// ─── State helpers ──────────────────────────────────────────────────────
export function makeDefaults({yearMin = YEAR_MIN_DEFAULT, yearMax = YEAR_MAX_DEFAULT} = {}) {
  return {
    yearFrom: yearMin,
    yearTo: yearMax,
    species: new Set(SPECIES.map(s => s.id)),
    sexes:   new Set(SEXES.map(s => s.id)),
    compounds: new Set(),
  };
}

export function isDefault(f, {yearMin = YEAR_MIN_DEFAULT, yearMax = YEAR_MAX_DEFAULT} = {}) {
  return f.yearFrom === yearMin
      && f.yearTo === yearMax
      && f.species.size === SPECIES.length
      && f.sexes.size === SEXES.length
      && f.compounds.size === 0;
}

// URL serialization (use in your .md file's URL-sync layer).
export function filtersToUrl(f, defaults = makeDefaults()) {
  const p = new URLSearchParams();
  if (f.yearFrom !== defaults.yearFrom) p.set("from", f.yearFrom);
  if (f.yearTo !== defaults.yearTo)     p.set("to",   f.yearTo);
  if (f.species.size !== SPECIES.length) p.set("sp", [...f.species].join(","));
  if (f.sexes.size !== SEXES.length)     p.set("sx", [...f.sexes].join(","));
  if (f.compounds.size > 0)              p.set("c",  [...f.compounds].join(","));
  return p.toString();
}

export function filtersFromUrl(search, defaults) {
  const d = defaults ?? makeDefaults();
  const p = new URLSearchParams(search);
  const f = {
    yearFrom: d.yearFrom,
    yearTo: d.yearTo,
    species: new Set(d.species),
    sexes: new Set(d.sexes),
    compounds: new Set(d.compounds),
  };
  if (p.has("from")) f.yearFrom = +p.get("from");
  if (p.has("to"))   f.yearTo   = +p.get("to");
  if (p.has("sp"))   f.species  = new Set(p.get("sp").split(","));
  if (p.has("sx"))   f.sexes    = new Set(p.get("sx").split(","));
  if (p.has("c"))    f.compounds = new Set(p.get("c").split(","));
  return f;
}

// ─── DOM helpers ────────────────────────────────────────────────────────
function svg(tag, attrs = {}) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

function toggleSet(set, id) {
  const next = new Set(set);
  if (next.has(id)) next.delete(id); else next.add(id);
  return next;
}

// Sparkline of year histogram, with selected range highlighted.
function yearSpark(yearHist, yearMin, yearMax, from, to, width = 276, height = 42) {
  const years = [];
  for (let y = yearMin; y <= yearMax; y++) years.push(y);
  const max = Math.max(1, ...years.map(y => yearHist[y] || 0));
  const bw = width / years.length;
  const root = svg("svg", {width, height, style: "display:block"});
  for (let i = 0; i < years.length; i++) {
    const y = years[i];
    const h = ((yearHist[y] || 0) / max) * (height - 2);
    const sel = y >= from && y <= to;
    root.appendChild(svg("rect", {
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

// Dual-handle range slider as a stand-alone DOM widget.
function rangeSlider({min, max, from, to, width = 276, onChange}) {
  const root = html`<div class="fb-range" style=${`width:${width}px`}></div>`;
  const track = html`<div class="fb-range-track"></div>`;
  const fill  = html`<div class="fb-range-fill"></div>`;
  const hFrom = html`<div class="fb-range-handle" data-h="from"></div>`;
  const hTo   = html`<div class="fb-range-handle" data-h="to"></div>`;
  root.append(track, fill, hFrom, hTo);

  const layout = () => {
    const pf = ((from - min) / (max - min)) * 100;
    const pt = ((to - min) / (max - min)) * 100;
    fill.style.left = `${pf}%`;
    fill.style.width = `${pt - pf}%`;
    hFrom.style.left = `${pf}%`;
    hTo.style.left = `${pt}%`;
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
  const up = () => {
    dragging = null;
    document.body.style.userSelect = "";
  };
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

// Outside-click + Escape closer for popovers.
function attachOutsideClose(popover, onClose) {
  const onDoc = (e) => { if (!popover.contains(e.target)) onClose(); };
  const onKey = (e) => { if (e.key === "Escape") onClose(); };
  // defer to next tick so the click that opened us doesn't close us
  setTimeout(() => {
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
  }, 0);
  return () => {
    document.removeEventListener("mousedown", onDoc);
    document.removeEventListener("keydown", onKey);
  };
}

// One-time CSS injection.
function injectCSS() {
  if (document.getElementById("fb-styles")) return;
  const s = document.createElement("style");
  s.id = "fb-styles";
  s.textContent = `
.fb-root {
  --fb-paper:  #f7f5f1;
  --fb-ink:    #1c1a17;
  --fb-ink-2:  #4a463f;
  --fb-ink-3:  #7a766d;
  --fb-ink-4:  #a9a59c;
  --fb-rule:   #e3dfd6;
  --fb-rule-2: #d2cdc1;
  --fb-accent:    oklch(58% 0.09 200);
  --fb-accent-2:  oklch(58% 0.09 200 / 0.12);
  --fb-accent-3:  oklch(58% 0.09 200 / 0.28);
  background: var(--fb-paper);
  border: 1px solid var(--fb-rule);
  border-radius: 12px;
  padding: 20px 24px;
  display: flex; align-items: center; gap: 28px; flex-wrap: wrap;
  font-family: ui-sans-serif, system-ui, sans-serif;
  color: var(--fb-ink);
}
.fb-count { flex-shrink: 0; padding-right: 22px; border-right: 1px solid var(--fb-rule); }
.fb-count-num {
  font-family: ui-monospace, "IBM Plex Mono", monospace;
  font-variant-numeric: tabular-nums;
  font-size: 44px; font-weight: 600; line-height: 1; letter-spacing: -0.03em;
}
.fb-count-label {
  font-family: ui-monospace, "IBM Plex Mono", monospace;
  font-size: 10.5px; color: var(--fb-ink-3);
  margin-top: 6px; letter-spacing: 0.05em; text-transform: uppercase;
}
.fb-count-total { color: var(--fb-ink-4); }
.fb-sentence {
  flex: 1; font-size: 17px; line-height: 1.7; color: var(--fb-ink-2);
  font-weight: 400; min-width: 280px;
}
.fb-token {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 2px 8px; margin: 0 1px;
  border-radius: 5px; border: 0;
  background: rgba(0,0,0,0.04);
  color: var(--fb-ink);
  font: inherit; font-weight: 500;
  cursor: pointer;
  text-decoration: underline; text-underline-offset: 4px;
  text-decoration-thickness: 1px; text-decoration-color: var(--fb-ink-4);
  transition: background .12s, color .12s;
}
.fb-token:hover { background: rgba(0,0,0,0.07); }
.fb-token[data-active="true"] {
  background: var(--fb-accent-2);
  color: var(--fb-accent);
  font-weight: 600;
  text-decoration-color: var(--fb-accent);
}
.fb-token[data-open="true"] {
  background: var(--fb-accent-2);
  box-shadow: 0 0 0 3px var(--fb-accent-3);
}
.fb-chev { opacity: 0.5; }
.fb-pop {
  position: absolute; top: calc(100% + 6px); left: 0;
  background: #fff; border: 1px solid var(--fb-rule); border-radius: 10px;
  box-shadow: 0 14px 40px rgba(0,0,0,0.10);
  padding: 12px; z-index: 30;
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
.fb-pop-list { display: flex; flex-direction: column; gap: 1px; }
.fb-pop-item {
  display: flex; align-items: center; gap: 9px;
  padding: 6px 8px; border-radius: 6px; cursor: pointer;
  font-size: 12.5px;
}
.fb-pop-item[data-on="true"] { background: var(--fb-accent-2); }
.fb-pop-item[data-on="true"] .fb-pop-name { color: var(--fb-accent); }
.fb-pop-item input { accent-color: var(--fb-accent); margin: 0; }
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
  padding: 4px 8px; font-size: 11px; border-radius: 4px;
  border: 1px solid var(--fb-rule); background: #fff;
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
  background: #fff; border: 1.5px solid var(--fb-accent);
  border-radius: 999px; box-shadow: 0 1px 2px rgba(0,0,0,0.12);
  cursor: grab;
}
.fb-range-handle:active { cursor: grabbing; }
.fb-reset {
  display: flex; align-items: center; gap: 5px;
  padding: 6px 10px; border-radius: 6px;
  border: 1px solid var(--fb-rule); background: #fff;
  color: var(--fb-ink-2); font-size: 11.5px; font-weight: 500;
  cursor: pointer; flex-shrink: 0; font-family: inherit;
}
.fb-reset:hover { background: var(--fb-paper); }
`;
  document.head.appendChild(s);
}

// ─── Main export ────────────────────────────────────────────────────────
//
// filterBar({initial, total, yearMin, yearMax, yearHist, counts})
//   - initial:   filter state (defaults to makeDefaults())
//   - total:     total study count for the "of N" label (default 292)
//   - yearMin/Max: bounds for the year slider (default 1965..2025)
//   - yearHist:  {[year]: studyCount} for the popover sparkline
//   - counts:    {species: {id: n}, sexes: {id: n}, compounds: {id: n}}
//                — optional per-bucket study counts shown next to checkboxes
//   - matchedCount(state): function that returns the matched-study count.
//                If omitted, the bar shows `total` (no live count).
//
// returns { node, getState, setState, subscribe(notify) }
//   - node:      DOM element to insert
//   - getState:  current filter state (with .matches() helper)
//   - setState:  programmatically set state (e.g. from URL on load)
//   - subscribe: Generators.observe-compatible subscriber
export function filterBar({
  initial,
  total = 292,
  yearMin = YEAR_MIN_DEFAULT,
  yearMax = YEAR_MAX_DEFAULT,
  yearHist = {},
  counts = {species: {}, sexes: {}, compounds: {}},
  matchedCount = null,
} = {}) {
  injectCSS();

  let state = initial ?? makeDefaults({yearMin, yearMax});
  const subscribers = new Set();
  const stateWithMatcher = () => Object.assign({}, state, {matches: makeMatcher(state)});
  const notifyAll = () => {
    const snapshot = stateWithMatcher();
    for (const fn of subscribers) fn(snapshot);
  };

  let openToken = null; // 'year' | 'species' | 'sex' | 'compound' | null
  let detachOutside = null;

  // ─── Build root DOM ────────────────────────────────────────────────────
  const root = html`<div class="fb-root"></div>`;

  const countNum   = html`<div class="fb-count-num">0</div>`;
  const countLabel = html`<div class="fb-count-label">studies <span class="fb-count-total">· of ${total}</span></div>`;
  root.append(html`<div class="fb-count">${countNum}${countLabel}</div>`);

  const sentence = html`<div class="fb-sentence"></div>`;
  root.append(sentence);

  const resetBtn = html`<button class="fb-reset" type="button">${resetIcon()} Reset</button>`;
  resetBtn.addEventListener("click", () => {
    state = makeDefaults({yearMin, yearMax});
    rerender();
  });
  root.append(resetBtn);

  function rerender() {
    // Count
    const matched = matchedCount ? matchedCount(state) : total;
    countNum.textContent = matched.toLocaleString();

    // Sentence: rebuild tokens
    sentence.replaceChildren(
      document.createTextNode("Showing rodent studies from "),
      tokenYear(),
      document.createTextNode(" in "),
      tokenSet("species", "any species", SPECIES, state.species, "species",
               (id) => state.species = toggleSet(state.species, id)),
      document.createTextNode(" across "),
      tokenSet("sex", "any sex", SEXES, state.sexes, "sexes",
               (id) => state.sexes = toggleSet(state.sexes, id)),
      document.createTextNode(" treated with "),
      tokenSet("compound", "any compound", COMPOUNDS, state.compounds, "compounds",
               (id) => state.compounds = toggleSet(state.compounds, id), {emptyMeansAll: false}),
      document.createTextNode("."),
    );

    // Reset visibility
    resetBtn.style.display = isDefault(state, {yearMin, yearMax}) ? "none" : "";

    notifyAll();
  }

  // ─── Token builders ────────────────────────────────────────────────────
  function tokenYear() {
    const isActive = state.yearFrom !== yearMin || state.yearTo !== yearMax;
    const phrase =
      !isActive ? "all years"
      : state.yearFrom === state.yearTo ? `in ${state.yearFrom}`
      : `${state.yearFrom}–${state.yearTo}`;
    const wrap = html`<span style="position:relative;display:inline-block"></span>`;
    const btn = html`<button class="fb-token" type="button"
      data-active=${isActive} data-open=${openToken === "year"}>
      ${phrase}${chevIcon()}
    </button>`;
    btn.addEventListener("click", (e) => { e.stopPropagation(); openPop("year", wrap, buildYearPop); });
    wrap.append(btn);
    if (openToken === "year") wrap.append(buildYearPop());
    return wrap;
  }

  function tokenSet(key, anyLabel, items, selected, stateField, onToggle, {emptyMeansAll = true} = {}) {
    const isAll = selected.size === items.length;
    const isEmpty = selected.size === 0;
    const isActive =
      emptyMeansAll ? !isAll
                    : !isEmpty;
    const phrase =
      emptyMeansAll
        ? (isAll ? anyLabel
           : isEmpty ? `no ${key === "sex" ? "cohorts" : key + (key.endsWith("s") ? "" : "s")}`
           : [...selected].map(id => items.find(x => x.id === id).label).join(" or "))
        : (isEmpty ? anyLabel
           : selected.size === 1 ? items.find(x => selected.has(x.id)).label
           : `${selected.size} compounds`);
    const wrap = html`<span style="position:relative;display:inline-block"></span>`;
    const btn = html`<button class="fb-token" type="button"
      data-active=${isActive} data-open=${openToken === key}>
      ${phrase}${chevIcon()}
    </button>`;
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openPop(key, wrap, () => buildCheckPop(items, selected, stateField, counts[stateField] || {}));
    });
    wrap.append(btn);
    if (openToken === key) wrap.append(buildCheckPop(items, selected, stateField, counts[stateField] || {}));
    return wrap;
  }

  function openPop(key, wrap, builder) {
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
    const pop = html`<div class="fb-pop" style="width:300px"></div>`;
    pop.append(
      html`<div class="fb-year-readout">
        <span>${state.yearFrom}</span><span>${state.yearTo}</span>
      </div>`,
      yearSpark(yearHist, yearMin, yearMax, state.yearFrom, state.yearTo, 276, 42),
    );
    const range = rangeSlider({
      min: yearMin, max: yearMax,
      from: state.yearFrom, to: state.yearTo,
      width: 276,
      onChange: (a, b) => {
        state.yearFrom = a; state.yearTo = b;
        // Update spark + readout cheaply without rebuilding popover.
        const readout = pop.querySelector(".fb-year-readout");
        readout.replaceChildren(html`<span>${a}</span>`, html`<span>${b}</span>`);
        const oldSpark = pop.querySelector("svg");
        oldSpark.replaceWith(yearSpark(yearHist, yearMin, yearMax, a, b, 276, 42));
        // Update the count up top + reset visibility, but don't tear down pop.
        const matched = matchedCount ? matchedCount(state) : total;
        countNum.textContent = matched.toLocaleString();
        resetBtn.style.display = isDefault(state, {yearMin, yearMax}) ? "none" : "";
        notifyAll();
      },
    });
    pop.append(range.node);
    const presets = html`<div class="fb-year-presets"></div>`;
    for (const [a, b, l] of [[yearMax - 4, yearMax, "last 5y"], [yearMax - 9, yearMax, "last 10y"], [yearMin, yearMax, "all"]]) {
      const pb = html`<button type="button">${l}</button>`;
      pb.addEventListener("click", () => {
        state.yearFrom = a; state.yearTo = b;
        rerender(); reopen("year");
      });
      presets.append(pb);
    }
    pop.append(presets);
    pop.addEventListener("mousedown", (e) => e.stopPropagation());
    detachOutside = attachOutsideClose(pop, () => closePop());
    return pop;
  }

  function buildCheckPop(items, selectedSet, stateField, perCounts) {
    const pop = html`<div class="fb-pop" style="min-width:200px"></div>`;
    const bar = html`<div class="fb-pop-bar"></div>`;
    const allBtn = html`<button class="fb-pop-link" type="button">select all</button>`;
    const clrBtn = html`<button class="fb-pop-link" type="button">clear</button>`;
    allBtn.addEventListener("click", () => { state[stateField] = new Set(items.map(i => i.id)); rerender(); reopen(stateField === "compounds" ? "compound" : stateField === "sexes" ? "sex" : "species"); });
    clrBtn.addEventListener("click", () => { state[stateField] = new Set(); rerender(); reopen(stateField === "compounds" ? "compound" : stateField === "sexes" ? "sex" : "species"); });
    bar.append(allBtn, clrBtn);
    pop.append(bar);
    const list = html`<div class="fb-pop-list"></div>`;
    for (const it of items) {
      const on = selectedSet.has(it.id);
      const n = perCounts[it.id];
      const row = html`<label class="fb-pop-item" data-on=${on}>
        <input type="checkbox" ${on ? "checked" : ""}>
        <span class="fb-pop-name">${it.label}</span>
        ${n != null ? html`<span class="fb-pop-n">${n}</span>` : ""}
      </label>`;
      row.querySelector("input").addEventListener("change", () => {
        state[stateField] = toggleSet(selectedSet, it.id);
        rerender();
        reopen(stateField === "compounds" ? "compound" : stateField === "sexes" ? "sex" : "species");
      });
      list.append(row);
    }
    pop.append(list);
    pop.addEventListener("mousedown", (e) => e.stopPropagation());
    detachOutside = attachOutsideClose(pop, () => closePop());
    return pop;
  }

  function reopen(key) {
    openToken = key;
    rerender();
  }

  // Initial render
  rerender();

  return {
    node: root,
    getState: () => stateWithMatcher(),
    setState: (s) => { state = s; rerender(); },
    // Generators.observe contract: subscribe(change), return cleanup.
    subscribe(change) {
      change(stateWithMatcher());
      subscribers.add(change);
      return () => subscribers.delete(change);
    },
  };
}

// ─── Tiny inline SVG icons ──────────────────────────────────────────────
function chevIcon() {
  const s = svg("svg", {width: 10, height: 10, viewBox: "0 0 10 10",
    fill: "none", stroke: "currentColor", "stroke-width": 1.5,
    "stroke-linecap": "round", "stroke-linejoin": "round", class: "fb-chev"});
  s.appendChild(svg("path", {d: "M2 4l3 3 3-3"}));
  return s;
}
function resetIcon() {
  const s = svg("svg", {width: 12, height: 12, viewBox: "0 0 12 12",
    fill: "none", stroke: "currentColor", "stroke-width": 1.5,
    "stroke-linecap": "round", "stroke-linejoin": "round"});
  s.appendChild(svg("path", {d: "M2.5 6a3.5 3.5 0 1 0 1-2.5"}));
  s.appendChild(svg("path", {d: "M2 2v2.2H4.2"}));
  return s;
}

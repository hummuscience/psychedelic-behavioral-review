# Behaviour Dashboard

```js
import {
  filterBar,
  makeDefaults,
  filtersToUrl,
  filtersFromUrl,
} from "./components/filter-bar.js";
```

```js
// Load study corpus (one row per paper).
const studies = await FileAttachment("studies.csv").csv({typed: true});
```

```js
// ─── Per-bucket study counts shown next to each checkbox ────────────────
const counts = (() => {
  const sp = {mouse: 0, rat: 0, other: 0, not_reported: 0};
  const sx = {male: 0, female: 0, not_reported: 0};
  const cp = {};
  for (const s of studies) {
    // Species (inclusive: "mouse and rat" counts under both)
    const raw = (s.species || "").toLowerCase().trim();
    if (raw === "mouse" || raw === "mouse and rat") sp.mouse++;
    if (raw === "rat"   || raw === "mouse and rat") sp.rat++;
    if (raw === "other") sp.other++;
    if (!raw || raw === "not reported") sp.not_reported++;
    // Sex (inclusive: "both sexes" counts under both)
    const rs = (s.sex || "").toLowerCase().trim();
    if (rs === "male only"   || rs === "both sexes") sx.male++;
    if (rs === "female only" || rs === "both sexes") sx.female++;
    if (!rs || rs === "not reported") sx.not_reported++;
    // Compounds (comma-separated)
    for (const c of (s.psychedelic || "").split(",").map(x => x.trim().toLowerCase()).filter(Boolean)) {
      cp[c] = (cp[c] || 0) + 1;
    }
  }
  return {species: sp, sexes: sx, compounds: cp};
})();
```

```js
// Year histogram for the popover sparkline.
const yearHist = (() => {
  const h = {};
  for (const s of studies) {
    const y = +s.pub_year;
    if (Number.isFinite(y)) h[y] = (h[y] || 0) + 1;
  }
  return h;
})();
const yearMin = Math.min(...Object.keys(yearHist).map(Number));
const yearMax = Math.max(...Object.keys(yearHist).map(Number));
```

```js
// ─── Build the filter bar ───────────────────────────────────────────────
const fb = filterBar({
  initial: filtersFromUrl(location.search),
  total: studies.length,
  yearMin, yearMax,
  yearHist,
  counts,
  matchedCount: (state) => studies.filter(state ? (() => {
    // matchedCount is called BEFORE state.matches is attached,
    // so build the predicate inline using the same rules:
    return (s) => true; // placeholder; see below
  })() : () => true).length,
});
```

```js
// Slightly cleaner: just use the .matches() helper exposed on the
// reactive `filters` value, and pass a real matchedCount.
const fb2 = filterBar({
  initial: filtersFromUrl(location.search, makeDefaults({yearMin, yearMax})),
  total: studies.length,
  yearMin, yearMax,
  yearHist,
  counts,
  matchedCount: (state) => {
    // Reuse the exact same filter logic shipped with the module.
    // We import a `matches` factory so you don't have to duplicate it.
    return studies.filter(makeMatcherFromState(state)).length;
  },
});

display(fb2.node);
```

```js
// `filters` is reactive: any cell that references it re-runs on change.
const filters = Generators.observe(fb2.subscribe);
```

```js
// Sync to URL whenever filters change.
{
  const qs = filtersToUrl(filters);
  const url = qs ? `?${qs}` : location.pathname;
  history.replaceState(null, "", url);
}
```

```js
// Now downstream cells can do:
const matched = studies.filter(filters.matches);

display(html`<p>${matched.length} of ${studies.length} studies match.</p>`);
```

---

## Helper

```js
// Tiny re-export of the matcher factory. (Or just import {makeMatcher}
// from filter-bar.js if you expose it — it's already exported as part
// of the filters value via filters.matches, so you rarely need it.)
function makeMatcherFromState(state) {
  return (study) => {
    if (study.pub_year < state.yearFrom || study.pub_year > state.yearTo) return false;
    const raw = (study.species || "").toLowerCase().trim();
    const sp =
      raw === "mouse" ? ["mouse"]
      : raw === "rat" ? ["rat"]
      : raw === "mouse and rat" ? ["mouse", "rat"]
      : raw === "other" ? ["other"]
      : ["not_reported"];
    if (!sp.some(b => state.species.has(b))) return false;
    const rs = (study.sex || "").toLowerCase().trim();
    const sx =
      rs === "male only" ? ["male"]
      : rs === "female only" ? ["female"]
      : rs === "both sexes" ? ["male", "female"]
      : ["not_reported"];
    if (!sx.some(b => state.sexes.has(b))) return false;
    if (state.compounds.size > 0) {
      const cs = (study.psychedelic || "").split(",").map(s => s.trim().toLowerCase());
      if (![...state.compounds].some(w => cs.includes(w))) return false;
    }
    return true;
  };
}
```

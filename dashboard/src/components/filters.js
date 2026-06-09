// filters.js — Thin wrapper around filter-bar.js that provides the
// mountFilters(studies, {Inputs, html, Generators}) API used by all tabs.
//
// Returns { node, filtered, state, helpers }
//   node     — DOM element to display() once at the top of the page
//   filtered — reactive (Generators.observe) array of matching studies
//   state    — current filter state (snapshot; update via the UI)

import {BUCKET_ORDER, compoundsOf} from "./dose-utils.js";
import {
  filterBar,
  makeDefaults,
  filtersToUrl,
  filtersFromUrl,
  makeMatcher,
  normalizeSpecies,
  normalizeSex,
  SPECIES,
  SEXES,
  COMPOUNDS,
  ASSAY_CATEGORY_ORDER,
} from "./filter-bar.js";

export {normalizeSpecies, normalizeSex, compoundsOf, ASSAY_CATEGORY_ORDER};
export const SPECIES_ORDER  = SPECIES.map(s => s.id);
export const SEX_ORDER      = SEXES.map(s => s.id);
export const COMPOUND_ORDER = [...BUCKET_ORDER, "(other)"];

export function yearOf(s) {
  return +(s.study_id || "").match(/(\d{4})/)?.[1] || s.pub_year || 0;
}

// ─── main entry ──────────────────────────────────────────────────────────────
// `Inputs`, `html`, `Generators` are passed in from the Observable Framework
// page context because they're not importable from observablehq:stdlib.
// (The filter-bar itself doesn't use Inputs — it builds its own DOM.)
// `assayCatalog` is optional: [{canonical, category, count}] from assay_catalog.json.
export function mountFilters(studies, {Inputs: _Inputs, html: _html, Generators}, assayCatalog = []) {
  const yearsAll = Array.from(new Set(studies.map(yearOf).filter(Boolean))).sort();
  const yearMin  = Math.min(...yearsAll);
  const yearMax  = Math.max(...yearsAll);

  // Year histogram for the sparkline popover.
  const yearHist = {};
  for (const s of studies) {
    const y = yearOf(s);
    if (y) yearHist[y] = (yearHist[y] || 0) + 1;
  }

  // Per-bucket counts shown next to each checkbox.
  const counts = {species: {}, sexes: {}, compounds: {}, assayCategories: {}, assayCanonicals: {}};
  for (const s of studies) {
    const sp = normalizeSpecies(s.species);
    counts.species[sp] = (counts.species[sp] || 0) + 1;
    const sx = normalizeSex(s.sex);
    counts.sexes[sx] = (counts.sexes[sx] || 0) + 1;
    for (const c of compoundsOf(s)) {
      counts.compounds[c] = (counts.compounds[c] || 0) + 1;
    }
    for (const a of (s.assays || [])) {
      counts.assayCategories[a.category] = (counts.assayCategories[a.category] || 0) + 1;
      counts.assayCanonicals[a.canonical] = (counts.assayCanonicals[a.canonical] || 0) + 1;
    }
  }

  const defaults = makeDefaults({yearMin, yearMax});

  const fb = filterBar({
    initial:      filtersFromUrl(location.search, defaults),
    total:        studies.length,
    yearMin, yearMax,
    yearHist,
    counts,
    assayCatalog,
    matchedCount: (st) => studies.filter(makeMatcher(st)).length,
  });

  // Subscribers that receive the filtered array whenever filters change.
  const filterSubscribers = new Set();
  let currentFiltered = [];

  fb.subscribe((filterState) => {
    // URL persistence: write only non-default params.
    const qs = filtersToUrl(filterState, defaults);
    const newURL = location.pathname + (qs ? "?" + qs : "");
    history.replaceState(null, "", newURL);

    currentFiltered = studies.filter(filterState.matches);
    for (const cb of filterSubscribers) cb(currentFiltered);
  });
  // Note: fb.subscribe calls the callback immediately, so currentFiltered is
  // already set before Generators.observe is created below.

  const filtered = Generators.observe(notify => {
    notify(currentFiltered);
    filterSubscribers.add(notify);
    return () => filterSubscribers.delete(notify);
  });

  return {
    node:    fb.node,
    filtered,
    state:   fb.getState(),
    helpers: {yearOf, normalizeSpecies, normalizeSex, compoundsOf},
  };
}

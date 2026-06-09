// Dose parsing & molecular-weight conversion utilities

export const MW = {
  "psilocybin": 284.25, "psilocin": 204.27,
  "lsd": 323.43, "1p-lsd": 379.50, "ald-52": 365.47,
  "iso-lsd": 323.43, "lisuride": 338.45,
  "dmt": 188.27, "n,n-dimethyltryptamine": 188.27,
  "5-meo-dmt": 218.30, "5-meo-dipt": 274.40, "5-meo-mipt": 246.36,
  "5-meo-amt": 232.32,
  "4-aco-dmt": 246.31, "4-acetoxy-dmt": 246.31,
  "4-ho-dipt": 232.32, "4-oh-dipt": 232.32,
  "4-ho-met": 218.30, "4-oh-met": 218.30,
  "4-ho-det": 232.32, "4-oh-det": 232.32,
  "4-ho-dpt": 232.32, "4-oh-dpt": 232.32,
  "dipt": 216.32, "det": 188.27, "dpt": 216.32,
  "doi": 357.19, "2,5-dimethoxy-4-iodoamphetamine": 357.19,
  "dom": 225.33, "dob": 274.16,
  "2c-b": 260.13, "2c-i": 307.13, "2c-h": 181.23,
  "25cn-nboh": 372.42, "25h-nboh": 286.35,
  "25i-nbome": 427.28, "25b-nbome": 380.27, "25c-nbome": 350.24,
  "tcb-2": 270.71, "tcb2": 270.71,
  "mescaline": 211.26, "ibogaine": 310.43, "noribogaine": 296.40,
  "harmine": 212.25, "harmaline": 214.27,
  "tabernanthalog": 286.37,
  "ecpla": 365.47, "mipla": 365.47, "lampa": 365.47,
  "tbg": 286.37,
  "psilacetin": 246.31,
  "norpsilocin": 190.24,
  "baeocystin": 270.22, "norbaeocystin": 256.19, "aeruginascin": 312.30,
  "salvinorin a": 432.51,
  "ketamine": 237.73, "mdma": 193.25, "mda": 179.22,
};

const TO_MG_PER_KG = {
  "mg/kg": 1.0, "µg/kg": 0.001, "ng/kg": 1e-6, "pg/kg": 1e-9,
  "mg/g": 1000.0, "µg/g": 1.0,
};
const TO_NMOL_PER_KG = {
  "mmol/kg": 1e6, "µmol/kg": 1e3, "nmol/kg": 1.0, "pmol/kg": 1e-3,
};

export const PSYCHEDELIC_BUCKETS = {
  "psilocybin": "Psilocybin", "psilocin": "Psilocybin",
  "lsd": "LSD",
  "doi": "DOI",
  "dmt": "DMT", "n,n-dimethyltryptamine": "DMT",
  "5-meo-dmt": "5-MeO-DMT",
  "ibogaine": "Ibogaine", "noribogaine": "Ibogaine",
  "mescaline": "Mescaline",
  "25i-nbome": "NBOMe/NBOH", "25b-nbome": "NBOMe/NBOH", "25c-nbome": "NBOMe/NBOH",
  "25cn-nboh": "NBOMe/NBOH", "25h-nboh": "NBOMe/NBOH",
  "nbome": "NBOMe/NBOH", "nboh": "NBOMe/NBOH",
};

export const BUCKET_ORDER = [
  "Psilocybin", "LSD", "DOI", "DMT", "5-MeO-DMT",
  "NBOMe/NBOH", "Ibogaine", "Mescaline",
];

// Map a study's free-text `psychedelic` string to the canonical bucket(s) it uses.
// Reuses the alias table from PSYCHEDELIC_BUCKETS so e.g. "psilocin" → "Psilocybin",
// "noribogaine" → "Ibogaine", "25I-NBOMe" → "NBOMe/NBOH". Returns ["(other)"] if
// nothing matched. A paper using psilocybin AND LSD will return both buckets.
export function compoundsOf(study) {
  const text = String(study?.psychedelic || "").toLowerCase();
  if (!text) return ["(other)"];
  // Split on common delimiters; keep only the bucket names that actually appear.
  const tokens = text.split(/[\s,;\/]+/).map(t => t.replace(/[^a-z0-9-]/g, ""));
  const hits = new Set();
  for (const tok of tokens) {
    if (!tok) continue;
    if (PSYCHEDELIC_BUCKETS[tok]) hits.add(PSYCHEDELIC_BUCKETS[tok]);
  }
  // Substring fallback for messy compound text that didn't tokenise cleanly
  // (e.g. "5-meo-dmt" with whitespace, "(R)-DOI"). Try each alias as a substring.
  if (hits.size === 0) {
    for (const [alias, bucket] of Object.entries(PSYCHEDELIC_BUCKETS)) {
      if (text.includes(alias)) hits.add(bucket);
    }
  }
  return hits.size ? [...hits] : ["(other)"];
}

const DOSE_RE = /^\s*([\d.]+(?:\s*[-–]\s*[\d.]+)?)\s*(mg|µg|μg|ug|ng|pg|nmol|mmol|µmol|μmol|umol|pmol|fmol)\s*\/\s*(kg|g)\s*(.*)$/i;

const UNIT_NORM = {
  "mg":"mg","µg":"µg","μg":"µg","ug":"µg","ng":"ng","pg":"pg",
  "nmol":"nmol","mmol":"mmol","µmol":"µmol","μmol":"µmol","umol":"µmol",
  "pmol":"pmol","fmol":"fmol",
};

export function parseDose(doseRaw, compoundLc) {
  const m = String(doseRaw).match(DOSE_RE);
  if (!m) return null;
  const numTok = m[1].trim();
  const unit = (UNIT_NORM[m[2].toLowerCase()] || m[2].toLowerCase());
  const denom = m[3].toLowerCase();
  const unitStr = `${unit}/${denom}`;
  let val;
  if (numTok.includes("-") || numTok.includes("–")) {
    const parts = numTok.split(/[-–]/).map(s => parseFloat(s.trim())).filter(Number.isFinite);
    val = parts.length ? parts.reduce((a,b)=>a+b,0)/parts.length : null;
  } else {
    val = parseFloat(numTok);
    if (!Number.isFinite(val)) val = null;
  }
  let mg_per_kg = null, nmol_per_kg = null;
  const mw = MW[compoundLc];
  if (val != null) {
    if (unitStr in TO_MG_PER_KG) {
      mg_per_kg = val * TO_MG_PER_KG[unitStr];
      if (mw != null) nmol_per_kg = mg_per_kg / mw * 1e6;
    } else if (unitStr in TO_NMOL_PER_KG) {
      nmol_per_kg = val * TO_NMOL_PER_KG[unitStr];
      if (mw != null) mg_per_kg = nmol_per_kg * mw / 1e6;
    }
  }
  return {value: val, unit: unitStr, mg_per_kg, nmol_per_kg};
}

// Group dose records by psychedelic bucket
export function bucketDoses(records) {
  const out = new Map();
  for (const r of records) {
    if (!r.administered || r.administered === "False" || r.administered === "false") continue;
    const compoundLc = String(r.compound || "").toLowerCase();
    const bucket = PSYCHEDELIC_BUCKETS[compoundLc];
    if (!bucket) continue;
    const parsed = parseDose(r.dose, compoundLc) || {value: null, unit: r.dose, mg_per_kg: null, nmol_per_kg: null};
    const entry = {
      ...parsed, raw: r.dose, stem: r.stem, route: r.route || "",
      compound_raw: r.compound, class: r.class,
    };
    if (!out.has(bucket)) out.set(bucket, {name: bucket, doses: [], stems: new Set()});
    out.get(bucket).doses.push(entry);
    out.get(bucket).stems.add(r.stem);
  }
  // Materialise + sort by configured order
  const arr = BUCKET_ORDER
    .map(name => out.get(name))
    .filter(Boolean)
    .map(x => ({...x, n_papers: x.stems.size, n_records: x.doses.length}));
  return arr;
}

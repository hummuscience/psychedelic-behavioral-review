"""Generate papers_to_download_v2.html — list of relevant papers without a PDF.

Reads prisma_accounting.csv, filters to disposition=pdf_unavailable_relevant,
and writes a self-contained HTML triage page where each row can be marked:
  - Got PDF                                (reclass → included_in_review)
  - Skip · classifier false-positive       (reclass → excluded_classifier_false_positive)
  - Skip · MDMA-only                       (reclass → excluded_compound_filter_MDMA)
  - Skip · off-topic                       (reclass → excluded_classifier_off_topic)
  - Skip · paywall (unobtainable)          (stays as pdf_unavailable_relevant)
Status is persisted to browser localStorage and exportable as JSON or CSV.
"""
from __future__ import annotations
import csv
import html
import json
from collections import Counter
from pathlib import Path

from find_pdf_duplicates import find_duplicates

ROOT = Path(__file__).parent
ACC = ROOT / "prisma_accounting.csv"
OUT = ROOT / "papers_to_download_v2.html"

rows = list(csv.DictReader(open(ACC)))
missing = [r for r in rows if r["disposition"] == "pdf_unavailable_relevant"]
missing.sort(key=lambda r: (r["year"], r["authors"]))

# Detect on-disk duplicates (manually-added papers without DOIs collide with
# search-result rows after surname-prefix stripping). Returns dict[stem] = [(on_disk_stem, why)].
duplicates_by_stem = find_duplicates(missing)


def split_compounds(raw: str) -> list[str]:
    """classifier_bucket is semicolon-separated. Trim, drop generic tag if specifics present."""
    parts = [p.strip() for p in (raw or "").split(";") if p.strip()]
    parts = ["DOI" if p.startswith("DOI ") else p for p in parts]
    parts = [p.replace("Psilocybin/Psilocin", "Psilocybin") for p in parts]
    if len(parts) > 1 and "Psychedelic (general)" in parts:
        parts = [p for p in parts if p != "Psychedelic (general)"]
    return parts or ["Unspecified"]


tags_per_paper = [split_compounds(r["classifier_bucket"]) for r in missing]
tag_counts: Counter = Counter()
for tags in tags_per_paper:
    tag_counts.update(tags)
year_counts = Counter(r["year"] for r in missing)

papers_payload = [
    {
        "i": i + 1,
        "stem": r["stem"],
        "year": r["year"],
        "authors": r["authors"].replace(" et al.", "").rstrip(","),
        "tags": tags,
        "title": r["title"],
        "journal": r["journal"],
        "doi": r["doi"],
        "duplicate_of": [s for s, _why in duplicates_by_stem.get(r["stem"], [])],
    }
    for i, (r, tags) in enumerate(zip(missing, tags_per_paper))
]

n_duplicates = sum(1 for p in papers_payload if p["duplicate_of"])

# Status options. Keys map to PRISMA dispositions where reclassification applies.
STATUS_OPTIONS = [
    {"key": "",            "label": "— Pending —",                 "kind": "pending",  "prisma": None,                                  "color": "transparent"},
    {"key": "done",        "label": "✅  Got PDF",                  "kind": "done",     "prisma": "included_in_review",                  "color": "#4ad295"},
    {"key": "skip_dup",    "label": "↺  Already in corpus",         "kind": "skipped",  "prisma": "duplicate_of_corpus",                 "color": "#7fb3d5"},
    {"key": "skip_fp",     "label": "✕  Skip · false-positive",     "kind": "skipped",  "prisma": "excluded_classifier_false_positive",  "color": "#e8b863"},
    {"key": "skip_mdma",   "label": "✕  Skip · MDMA-only",          "kind": "skipped",  "prisma": "excluded_compound_filter_MDMA",       "color": "#d97070"},
    {"key": "skip_off",    "label": "✕  Skip · off-topic",          "kind": "skipped",  "prisma": "excluded_classifier_off_topic",       "color": "#a78bfa"},
    {"key": "skip_nobeh",  "label": "✕  Skip · no behaviour",       "kind": "skipped",  "prisma": "excluded_classifier_off_topic",       "color": "#c084fc"},
    {"key": "skip_paywall","label": "✕  Skip · paywall (give up)",  "kind": "skipped",  "prisma": "pdf_unavailable_relevant",            "color": "#9aa3b2"},
]

bucket_chips = "\n    ".join(
    f'<label data-bucket="{html.escape(b)}">{html.escape(b)} <span class="ct">{n}</span></label>'
    for b, n in tag_counts.most_common()
)
year_options = "\n      ".join(
    f'<option value="{y}">{y} ({n})</option>' for y, n in sorted(year_counts.items())
)
status_options_html = "\n      ".join(
    f'<option value="{o["key"]}">{html.escape(o["label"])}</option>' for o in STATUS_OPTIONS
)

doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Papers still missing PDFs ({len(missing)})</title>
<style>
* {{ box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  max-width: 1500px;
  margin: 12px auto 60px;
  padding: 0 20px;
  color: #222;
  line-height: 1.4;
}}
h1 {{ margin: 0 0 4px; font-size: 1.4rem; }}
h1 .count {{ color: #888; font-weight: 400; }}
.subtitle {{ color: #666; font-size: 0.9rem; margin-bottom: 12px; max-width: 950px; }}
.tools {{
  position: sticky; top: 0; background: white; padding: 10px 0;
  border-bottom: 1px solid #ddd; z-index: 10;
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
}}
.tools input[type=text] {{
  padding: 6px 10px; border: 1px solid #ccc; border-radius: 6px; min-width: 280px;
  font-size: 14px;
}}
.tools select {{ padding: 5px 8px; border: 1px solid #ccc; border-radius: 6px; font-size: 13px; }}
.tools .stat {{ font-size: 13px; color: #555; }}
.tools .stat b {{ color: #222; }}
.tools .sep {{ color: #ccc; }}
.progress-bar {{
  height: 8px; background: #eee; border-radius: 4px; overflow: hidden;
  margin: 6px 0 4px; display: flex;
}}
.progress-bar > span {{ height: 100%; transition: width 0.2s ease; }}
.progress-legend {{
  display: flex; gap: 14px; flex-wrap: wrap; font-size: 11px; color: #666;
  margin-bottom: 12px;
}}
.progress-legend .swatch {{
  display: inline-block; width: 10px; height: 10px; border-radius: 2px;
  margin-right: 5px; vertical-align: middle;
}}
.legend {{
  display: flex; gap: 5px; flex-wrap: wrap; margin-bottom: 10px; font-size: 12px;
}}
.legend label {{
  cursor: pointer; padding: 3px 9px; border-radius: 12px;
  background: #f0f0f0; user-select: none; white-space: nowrap;
}}
.legend label:hover {{ background: #e5e5e5; }}
.legend label.active {{ background: #d3e3ff; color: #1a3a7a; font-weight: 500; }}
.legend .ct {{ color: #888; font-size: 11px; margin-left: 2px; }}
.legend label.active .ct {{ color: #4a6bb0; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{
  border-bottom: 1px solid #eee; padding: 7px 8px; text-align: left;
  font-size: 13px; vertical-align: top;
}}
th {{
  background: #fafafa; font-weight: 600; cursor: pointer; user-select: none;
  border-bottom: 2px solid #ccc; position: sticky; top: 56px; z-index: 5;
}}
th:hover {{ background: #f0f0f0; }}
th .arrow {{ display: inline-block; width: 10px; color: #999; }}
tr:hover {{ background: #f9fafb; }}
tr[data-status="done"]    {{ background: #e6f5ec !important; }}
tr[data-status="skipped"] {{ background: #f5f0e8 !important; opacity: 0.72; }}
tr[data-status="skipped"] td.title-cell a {{ color: #777; text-decoration: line-through; }}
.compound-tag {{
  display: inline-block; padding: 2px 7px; margin: 1px 2px 1px 0;
  border-radius: 10px; font-size: 11px; font-weight: 500; white-space: nowrap;
}}
.year {{ font-variant-numeric: tabular-nums; color: #666; white-space: nowrap; }}
.title-cell {{ max-width: 600px; }}
.title-cell a.title-link {{ color: #1a0dab; text-decoration: none; font-weight: 500; }}
.title-cell a.title-link:hover {{ text-decoration: underline; }}
.journal {{ color: #888; font-size: 11px; font-style: italic; margin-top: 2px; }}
.doi-cell {{ font-family: ui-monospace, monospace; font-size: 11px; }}
.doi-cell a {{ color: #1a0dab; text-decoration: none; }}
.doi-cell a:hover {{ text-decoration: underline; }}
.actions {{ white-space: nowrap; }}
.actions a {{
  display: inline-block; padding: 3px 7px; margin: 1px 2px 1px 0;
  border-radius: 4px; text-decoration: none; font-size: 11px;
  border: 1px solid;
}}
.actions a.gscholar {{ background: #f0f0f0; color: #444; border-color: #ddd; }}
.actions a.semscholar {{ background: #eef5ff; color: #1a4a7a; border-color: #c8d8ee; }}
.actions a:hover {{ filter: brightness(0.95); }}
.status-select {{
  padding: 4px 6px; border: 1px solid #ccc; border-radius: 4px;
  font-size: 12px; background: #fff; min-width: 160px; cursor: pointer;
}}
.status-select.s-done    {{ background: #e0f5e8; border-color: #4ad295; }}
.status-select.s-skipped {{ background: #faefe1; border-color: #d2a368; }}
.dup-badge {{
  display: inline-block; margin-top: 4px; padding: 2px 8px;
  background: #fff8e1; color: #8a6d00; border: 1px solid #f1c232;
  border-radius: 4px; font-size: 11px;
}}
.dup-badge code {{ background: rgba(0,0,0,0.05); padding: 0 4px; border-radius: 2px; font-size: 11px; }}
.empty {{ text-align: center; padding: 40px; color: #888; }}
button {{
  padding: 5px 11px; border: 1px solid #ccc; background: #fff;
  border-radius: 4px; cursor: pointer; font-size: 12px;
}}
button:hover {{ background: #f5f5f5; }}
button.primary {{ background: #eef; border-color: #99c; color: #225; }}
.help {{
  font-size: 11px; color: #888; margin-top: 4px;
}}
.help b {{ color: #555; }}
</style>
</head>
<body>

<h1>Papers still missing PDFs <span class="count">({len(missing)})</span></h1>
<div class="subtitle">
  Relevant psychedelic-behaviour papers from the PubMed search where a PDF couldn't be retrieved
  (paywalled, not in <code>/cloud/papers</code>, blocked by Cloudflare, or otherwise unobtainable). Save
  retrieved PDFs to <code>scoring/pdfs_new/</code> as <code>firstauthoryear.pdf</code> (lowercase, no spaces).
  For each paper you can mark either <b>Got PDF</b> or <b>Skip</b> with a PRISMA-aligned reason — these are
  written back to the disposition column when you re-run <code>build_prisma_accounting.py</code>.
</div>

<div style="background:#fff8e1; border-left:4px solid #f1c232; padding:8px 12px; margin:10px 0; font-size:13px; color:#6b5510;">
  <b>{n_duplicates} likely duplicate{"s" if n_duplicates != 1 else ""}</b> already on disk under a different stem
  (Unicode/prefix variants like <code>degregorio2021 → gregorio2021</code>). These are pre-marked as
  <b>"Already in corpus"</b> below — flip the dropdown if the match is wrong.
</div>

<div class="progress-bar" id="progressBar"></div>
<div class="progress-legend" id="progressLegend"></div>

<div class="tools">
  <input type="text" id="search" placeholder="Search title, author, DOI, journal…">
  <select id="yearFilter">
    <option value="">All years</option>
    {year_options}
  </select>
  <select id="statusFilter">
    <option value="">All statuses</option>
    <option value="pending">Pending only</option>
    <option value="done">Got PDF only</option>
    <option value="skipped">Skipped only</option>
  </select>
  <span class="stat"><b id="visibleCount">{len(missing)}</b> of {len(missing)} visible</span>
  <span class="sep">·</span>
  <button id="resetFilters">Reset filters</button>
  <button class="primary" id="exportJson">Export JSON ↓</button>
  <button class="primary" id="exportCsv">Export CSV ↓</button>
  <button class="primary" id="importProgress">Import ↑</button>
  <input type="file" id="fileInput" accept="application/json" style="display:none;">
</div>

<div class="legend" id="bucketLegend">
  <label data-bucket="" class="active">All compounds <span class="ct">{len(missing)}</span></label>
  {bucket_chips}
</div>

<table id="papersTable">
  <thead>
    <tr>
      <th style="width:180px;">Status</th>
      <th style="width:38px;">#</th>
      <th data-sort="year" style="width:60px;">Year<span class="arrow" id="arr-year">▾</span></th>
      <th data-sort="authors" style="width:130px;">First author<span class="arrow" id="arr-authors"></span></th>
      <th style="width:200px;">Compound</th>
      <th data-sort="title" class="title-cell">Title / Journal<span class="arrow" id="arr-title"></span></th>
      <th data-sort="doi" style="width:230px;">DOI<span class="arrow" id="arr-doi"></span></th>
      <th style="width:170px;">Find PDF</th>
    </tr>
  </thead>
  <tbody id="tbody"></tbody>
</table>

<div id="emptyMsg" class="empty" style="display:none;">No papers match the current filters.</div>

<script>
const PAPERS = {json.dumps(papers_payload, ensure_ascii=False)};
const STATUS_OPTIONS = {json.dumps(STATUS_OPTIONS)};
const STATUS_BY_KEY = Object.fromEntries(STATUS_OPTIONS.map(o => [o.key, o]));
const STORAGE_KEY = "papers-to-download-v2-state";

let state = {{
  status: {{}},              // {{doi: "done"|"skip_fp"|...}} — explicit user choice
  statusOverridden: {{}},    // {{doi: true}} once user has touched the dropdown (suppresses auto-default)
  search: "",
  year: "",
  bucket: "",
  statusFilter: "",
  sort: "year",
  sortDir: 1,
}};

function effectiveStatus(p) {{
  if (state.status[p.doi]) return state.status[p.doi];
  if ((p.duplicate_of || []).length > 0 && !state.statusOverridden[p.doi]) return "skip_dup";
  return "";
}}

// Load + migrate from older `done`-only schema
try {{
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) {{
    const parsed = JSON.parse(saved);
    if (parsed.done && !parsed.status) {{
      parsed.status = {{}};
      for (const doi of Object.keys(parsed.done)) {{
        if (parsed.done[doi]) parsed.status[doi] = "done";
      }}
      delete parsed.done;
    }}
    Object.assign(state, parsed);
  }}
}} catch (e) {{ console.warn("Could not restore state:", e); }}

function saveState() {{
  try {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }} catch (e) {{}}
}}

function escapeHtml(s) {{
  return String(s ?? "").replace(/[&<>"']/g, c => ({{
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }})[c]);
}}

const COMPOUND_HUE = {{
  "Psilocybin": 280, "LSD": 200, "DMT": 160, "5-MeO-DMT": 140,
  "DOI": 30, "Mescaline": 50, "Ibogaine": 0, "NBOMe": 320, "NBOH": 320,
  "Psychedelic (general)": 220, "Other serotonergic": 250,
  "Ayahuasca": 100, "Ketamine": 190, "MDMA": 350,
}};
function compoundColor(b) {{
  let hue = COMPOUND_HUE[b];
  if (hue == null) {{
    let h = 0;
    for (const c of b) h = (h * 31 + c.charCodeAt(0)) | 0;
    hue = Math.abs(h) % 360;
  }}
  return `hsl(${{hue}}, 55%, 87%)`;
}}

function compareValues(va, vb, dir) {{
  if (va === vb) return 0;
  if (va == null) return 1;
  if (vb == null) return -1;
  return va > vb ? dir : -dir;
}}

function statusKindOf(p) {{
  const key = effectiveStatus(p);
  return key ? (STATUS_BY_KEY[key]?.kind || "pending") : "pending";
}}

function statusOptionsHtml(currentKey) {{
  return STATUS_OPTIONS.map(o =>
    `<option value="${{o.key}}" ${{o.key === (currentKey || "") ? "selected" : ""}}>${{escapeHtml(o.label)}}</option>`
  ).join("");
}}

function render() {{
  const tbody = document.getElementById("tbody");
  let visible = PAPERS.slice();
  const q = state.search.toLowerCase().trim();
  if (q) {{
    visible = visible.filter(p =>
      (p.title || "").toLowerCase().includes(q) ||
      (p.authors || "").toLowerCase().includes(q) ||
      (p.doi || "").toLowerCase().includes(q) ||
      (p.journal || "").toLowerCase().includes(q)
    );
  }}
  if (state.year) visible = visible.filter(p => String(p.year) === String(state.year));
  if (state.bucket) visible = visible.filter(p => (p.tags || []).includes(state.bucket));
  if (state.statusFilter) visible = visible.filter(p => statusKindOf(p) === state.statusFilter);

  const dir = state.sortDir;
  const key = state.sort;
  visible.sort((a, b) => compareValues(a[key], b[key], dir));

  for (const arr of document.querySelectorAll(".arrow")) arr.textContent = "";
  const arrEl = document.getElementById("arr-" + key);
  if (arrEl) arrEl.textContent = dir > 0 ? "▾" : "▴";

  if (visible.length === 0) {{
    tbody.innerHTML = "";
    document.getElementById("emptyMsg").style.display = "block";
  }} else {{
    document.getElementById("emptyMsg").style.display = "none";
    tbody.innerHTML = visible.map(p => {{
      const statusKey = effectiveStatus(p);
      const opt = STATUS_BY_KEY[statusKey];
      const kind = opt?.kind || "pending";
      const doiUrl = p.doi ? `https://doi.org/${{p.doi}}` : "";
      const scholarUrl = `https://scholar.google.com/scholar?q=${{encodeURIComponent(p.title)}}`;
      const semScholarUrl = p.doi
        ? `https://www.semanticscholar.org/search?q=${{encodeURIComponent(p.doi)}}`
        : `https://www.semanticscholar.org/search?q=${{encodeURIComponent(p.title)}}`;
      const tagsHtml = (p.tags || []).map(t =>
        `<span class="compound-tag" style="background:${{compoundColor(t)}};">${{escapeHtml(t)}}</span>`
      ).join("");
      const dupBadge = (p.duplicate_of || []).length
        ? `<div class="dup-badge" title="Already on disk under this stem">↺ already on disk: ${{(p.duplicate_of || []).map(s => `<code>${{escapeHtml(s)}}</code>`).join(", ")}}</div>`
        : "";
      return `<tr data-doi="${{escapeHtml(p.doi)}}" data-status="${{kind}}">
        <td><select class="status-select s-${{kind}}">${{statusOptionsHtml(statusKey)}}</select></td>
        <td>${{p.i}}</td>
        <td class="year">${{p.year || ""}}</td>
        <td>${{escapeHtml(p.authors)}}</td>
        <td>${{tagsHtml}}</td>
        <td class="title-cell">
          ${{doiUrl
            ? `<a class="title-link" href="${{doiUrl}}" target="_blank" rel="noopener">${{escapeHtml(p.title)}}</a>`
            : escapeHtml(p.title)}}
          <div class="journal">${{escapeHtml(p.journal || "")}}</div>
          ${{dupBadge}}
        </td>
        <td class="doi-cell"><a href="${{doiUrl}}" target="_blank" rel="noopener">${{escapeHtml(p.doi)}}</a></td>
        <td class="actions">
          <a class="gscholar" href="${{scholarUrl}}" target="_blank" rel="noopener">GScholar</a>
          <a class="semscholar" href="${{semScholarUrl}}" target="_blank" rel="noopener">SemScholar</a>
        </td>
      </tr>`;
    }}).join("");
  }}

  document.getElementById("visibleCount").textContent = visible.length;

  // Progress segments
  const tally = {{}};
  for (const o of STATUS_OPTIONS) tally[o.key] = 0;
  let pending = 0;
  for (const p of PAPERS) {{
    const k = effectiveStatus(p);
    if (k && tally[k] != null) tally[k]++;
    else pending++;
  }}
  const N = PAPERS.length;
  const segs = STATUS_OPTIONS.filter(o => o.key && tally[o.key] > 0).map(o =>
    `<span style="width:${{(100 * tally[o.key] / N).toFixed(2)}}%; background:${{o.color}};" title="${{escapeHtml(o.label)}}: ${{tally[o.key]}}"></span>`
  ).join("");
  document.getElementById("progressBar").innerHTML = segs;
  document.getElementById("progressLegend").innerHTML =
    STATUS_OPTIONS.filter(o => o.key).map(o =>
      `<span><span class="swatch" style="background:${{o.color}};"></span>${{escapeHtml(o.label)}}: <b>${{tally[o.key]}}</b></span>`
    ).join("") +
    `<span><span class="swatch" style="background:#eee;"></span>Pending: <b>${{pending}}</b></span>` +
    `<span style="margin-left:auto; color:#444;">Resolved: <b>${{N - pending}}</b> / ${{N}}</span>`;

  for (const lbl of document.querySelectorAll("#bucketLegend label")) {{
    lbl.classList.toggle("active", lbl.dataset.bucket === state.bucket);
  }}
}}

// --- Wire up controls
document.getElementById("search").value = state.search;
document.getElementById("search").addEventListener("input", e => {{
  state.search = e.target.value; saveState(); render();
}});
document.getElementById("yearFilter").value = state.year;
document.getElementById("yearFilter").addEventListener("change", e => {{
  state.year = e.target.value; saveState(); render();
}});
document.getElementById("statusFilter").value = state.statusFilter;
document.getElementById("statusFilter").addEventListener("change", e => {{
  state.statusFilter = e.target.value; saveState(); render();
}});
for (const lbl of document.querySelectorAll("#bucketLegend label")) {{
  lbl.addEventListener("click", () => {{
    state.bucket = (state.bucket === lbl.dataset.bucket) ? "" : lbl.dataset.bucket;
    saveState(); render();
  }});
}}
document.getElementById("resetFilters").addEventListener("click", () => {{
  state.search = ""; state.year = ""; state.bucket = ""; state.statusFilter = "";
  document.getElementById("search").value = "";
  document.getElementById("yearFilter").value = "";
  document.getElementById("statusFilter").value = "";
  saveState(); render();
}});
for (const th of document.querySelectorAll("th[data-sort]")) {{
  th.addEventListener("click", () => {{
    const key = th.dataset.sort;
    if (state.sort === key) state.sortDir = -state.sortDir;
    else {{ state.sort = key; state.sortDir = 1; }}
    saveState(); render();
  }});
}}

// Status dropdown change (delegated)
document.getElementById("tbody").addEventListener("change", e => {{
  if (!e.target.classList.contains("status-select")) return;
  const tr = e.target.closest("tr");
  const doi = tr.dataset.doi;
  const newKey = e.target.value;
  if (newKey) state.status[doi] = newKey;
  else delete state.status[doi];
  state.statusOverridden[doi] = true;   // user took control — don't re-apply auto-default
  saveState();
  render();
}});

// Export JSON
document.getElementById("exportJson").addEventListener("click", () => {{
  const blob = new Blob([JSON.stringify(state.status, null, 2)], {{type: "application/json"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `papers-progress-${{new Date().toISOString().slice(0,10)}}.json`;
  a.click();
  URL.revokeObjectURL(url);
}});

// Export CSV — ready for build_prisma_accounting.py to consume
document.getElementById("exportCsv").addEventListener("click", () => {{
  const lines = ["doi,status,reason,prisma_disposition,duplicate_of"];
  for (const p of PAPERS) {{
    const k = effectiveStatus(p);
    if (!k) continue;
    const opt = STATUS_BY_KEY[k];
    const dupOf = (p.duplicate_of || []).join("|");
    lines.push([p.doi, opt.kind, k, opt.prisma || "", dupOf].map(x => `"${{String(x).replace(/"/g, '""')}}"`).join(","));
  }}
  const blob = new Blob([lines.join("\\n")], {{type: "text/csv"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `papers-decisions-${{new Date().toISOString().slice(0,10)}}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}});

document.getElementById("importProgress").addEventListener("click", () => {{
  document.getElementById("fileInput").click();
}});
document.getElementById("fileInput").addEventListener("change", async e => {{
  const file = e.target.files[0];
  if (!file) return;
  try {{
    const text = await file.text();
    const imported = JSON.parse(text);
    // Migrate older `done: true` entries → status="done"
    for (const [doi, val] of Object.entries(imported)) {{
      if (val === true) state.status[doi] = "done";
      else if (typeof val === "string" && STATUS_BY_KEY[val]) state.status[doi] = val;
    }}
    saveState();
    render();
  }} catch (err) {{ alert("Import failed: " + err.message); }}
}});

render();
</script>

</body>
</html>
"""

OUT.write_text(doc, encoding="utf-8")
print(f"Wrote {OUT}  ({len(missing)} papers, {OUT.stat().st_size:,} bytes, {len(tag_counts)} compound tags)")

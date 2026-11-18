"""Generate excluded_review.html — click-through review of papers auto-excluded
as 'excluded_no_behaviour_in_full_text' (Group A).

For each paper we surface:
  - title, authors, year, journal, DOI link
  - judge notes (from the quarantined consensus JSON)  — explains why excluded
  - per-row decision: Confirm exclusion / Revert to included / Re-classify

Decisions persist in localStorage and export to a CSV that
`apply_triage_decisions.py` can merge back into manual_decisions.json.
"""
from __future__ import annotations
import csv
import html
import json
from pathlib import Path

ROOT = Path(__file__).parent
DECISIONS_JSON = ROOT / "manual_decisions.json"
REGISTRY_JSON = ROOT / "paper_registry.json"
QUARANTINE_DIR = ROOT / "results_full_consensus" / "_quarantine"
PUBMED_CSV = ROOT / "results" / "pubmed_expansion.csv"
OUT = ROOT / "excluded_review.html"

DISPOSITION = "excluded_no_behaviour_in_full_text"


def main() -> None:
    decisions = json.loads(DECISIONS_JSON.read_text())
    registry = json.loads(REGISTRY_JSON.read_text())
    pubmed_by_doi = {(r.get("doi") or "").lower().strip(): r
                     for r in csv.DictReader(open(PUBMED_CSV)) if r.get("doi")}

    # Reverse-lookup: DOI → stem (for finding the quarantined JSON)
    doi_to_stem = {(r.get("doi") or "").lower(): stem
                   for stem, r in registry.items() if r.get("doi")}

    excluded = [(doi, d) for doi, d in decisions.items()
                if d.get("disposition") == DISPOSITION]
    excluded.sort(key=lambda x: x[1].get("applied_at", ""))

    rows = []
    for doi, d in excluded:
        stem = doi_to_stem.get(doi.lower())
        reg_meta = registry.get(stem, {}) if stem else {}
        pm_meta = pubmed_by_doi.get(doi.lower(), {})

        # Pull the judge notes from the quarantined consensus JSON
        judge_notes: list[str] = []
        if stem:
            qjson = QUARANTINE_DIR / f"{stem}.json"
            if qjson.exists():
                try:
                    j = json.loads(qjson.read_text())
                    judge_notes = j.get("judge_notes") or []
                except Exception:
                    pass

        title = (reg_meta.get("title") or pm_meta.get("title") or "").strip()
        authors = reg_meta.get("authors") or []
        if not authors and pm_meta.get("authors_short"):
            authors = [pm_meta["authors_short"]]
        first_author = authors[0] if authors else "?"
        year = reg_meta.get("year") or pm_meta.get("year") or ""
        journal = reg_meta.get("journal") or pm_meta.get("journal") or ""
        rows.append({
            "doi": doi,
            "stem": stem or "",
            "title": title,
            "first_author": first_author,
            "year": year,
            "journal": journal,
            "judge_notes": judge_notes,
        })

    rows.sort(key=lambda r: (r["year"], r["first_author"]))

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Auto-excluded papers — manual review ({len(rows)})</title>
<style>
* {{ box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  max-width: 1300px; margin: 14px auto 60px; padding: 0 20px; color: #222; line-height: 1.45;
}}
h1 {{ margin: 0 0 4px; font-size: 1.4rem; }}
h1 .count {{ color: #888; font-weight: 400; }}
.subtitle {{ color: #666; font-size: 0.9rem; margin-bottom: 14px; max-width: 850px; }}
.tools {{
  position: sticky; top: 0; background: white; padding: 10px 0;
  border-bottom: 1px solid #ddd; z-index: 10;
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
}}
.tools input[type=text] {{
  padding: 6px 10px; border: 1px solid #ccc; border-radius: 6px; min-width: 280px; font-size: 14px;
}}
.tools select {{ padding: 5px 8px; border: 1px solid #ccc; border-radius: 6px; font-size: 13px; }}
.tools .stat {{ font-size: 13px; color: #555; }} .tools .stat b {{ color: #222; }}
.tools .sep {{ color: #ccc; }}
button {{
  padding: 5px 11px; border: 1px solid #ccc; background: #fff;
  border-radius: 4px; cursor: pointer; font-size: 12px;
}}
button:hover {{ background: #f5f5f5; }}
button.primary {{ background: #eef; border-color: #99c; color: #225; }}
.progress-bar {{ height: 8px; background: #eee; border-radius: 4px; overflow: hidden; margin: 6px 0 4px; display: flex; }}
.progress-bar > span {{ height: 100%; transition: width 0.2s ease; }}
.progress-legend {{
  display: flex; gap: 14px; flex-wrap: wrap; font-size: 11px; color: #666; margin-bottom: 14px;
}}
.progress-legend .swatch {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; vertical-align: middle; }}

.card {{
  border: 1px solid #ddd; border-radius: 8px; padding: 14px 16px; margin-bottom: 12px;
  background: #fff; transition: opacity 0.15s, background 0.15s;
}}
.card.confirm-excluded  {{ background: #f5f0e8; opacity: 0.78; }}
.card.revert-include    {{ background: #e6f5ec; }}
.card.reclassify        {{ background: #ddeaff; }}
.card-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }}
.card-head h2 {{ margin: 0; font-size: 1.05rem; line-height: 1.3; flex: 1; }}
.card-head h2 a {{ color: #1a0dab; text-decoration: none; }}
.card-head h2 a:hover {{ text-decoration: underline; }}
.meta {{ font-size: 12px; color: #666; margin-top: 2px; }}
.meta b {{ color: #222; }}
.doi {{ font-family: ui-monospace, monospace; font-size: 11px; color: #1a0dab; }}
.judge-notes {{
  background: #fffae6; border-left: 4px solid #f1c232; padding: 8px 12px;
  margin: 10px 0; font-size: 13px; color: #6b5510;
}}
.judge-notes ul {{ margin: 4px 0 0 16px; padding-left: 12px; }}
.judge-notes li {{ margin-bottom: 4px; }}
.actions-row {{
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 10px;
  font-size: 13px;
}}
.actions-row label {{ display: inline-flex; align-items: center; cursor: pointer; gap: 5px; padding: 5px 10px; border-radius: 16px; border: 1px solid transparent; }}
.actions-row label:hover {{ background: #f5f5f5; }}
.actions-row input[type=radio]:checked + span {{ font-weight: 600; }}
.actions-row label.confirm-excluded:has(input:checked) {{ background: #f5e6d0; border-color: #d2a368; }}
.actions-row label.revert-include:has(input:checked)   {{ background: #d9f0e2; border-color: #4ad295; }}
.actions-row label.reclassify:has(input:checked)       {{ background: #d3e3ff; border-color: #6090e0; }}
.actions-row select.reclassify-target {{
  padding: 4px 6px; font-size: 12px; border: 1px solid #ccc; border-radius: 4px;
}}
.linkrow {{ margin-top: 8px; font-size: 12px; }}
.linkrow a {{
  display: inline-block; padding: 3px 8px; margin-right: 6px;
  border-radius: 4px; text-decoration: none; font-size: 11px; border: 1px solid;
}}
.linkrow a.gscholar {{ background: #f0f0f0; color: #444; border-color: #ddd; }}
.linkrow a.semscholar {{ background: #eef5ff; color: #1a4a7a; border-color: #c8d8ee; }}
.linkrow a.doi-link {{ background: #eef; color: #1a0dab; border-color: #ccd; }}
.empty {{ text-align: center; padding: 40px; color: #888; }}
</style>
</head>
<body>

<h1>Auto-excluded papers — manual review <span class="count">({len(rows)})</span></h1>
<div class="subtitle">
  These papers were auto-flagged with <code>{DISPOSITION}</code> because the
  Haiku judge gave them all-zero scores AND zero scoreable assays. Click
  through to confirm the exclusion, revert it, or re-classify with a more
  specific reason. Decisions are saved in your browser; click <b>Export CSV</b>
  to feed them back into the PRISMA pipeline.
</div>

<div class="progress-bar" id="progressBar"></div>
<div class="progress-legend" id="progressLegend"></div>

<div class="tools">
  <input type="text" id="search" placeholder="Search title / author / DOI / journal…">
  <span class="stat"><b id="visibleCount">{len(rows)}</b> visible</span>
  <span class="sep">·</span>
  <span class="stat"><b id="reviewedCount">0</b> reviewed</span>
  <span class="sep">·</span>
  <button id="resetFilters">Reset</button>
  <button class="primary" id="exportJson">Export JSON ↓</button>
  <button class="primary" id="exportCsv">Export CSV ↓</button>
  <button class="primary" id="importBtn">Import ↑</button>
  <input type="file" id="fileInput" accept="application/json" style="display:none;">
</div>

<div id="cards"></div>
<div id="emptyMsg" class="empty" style="display:none;">No papers match the search.</div>

<script>
const PAPERS = {json.dumps(rows, ensure_ascii=False)};
const STORAGE_KEY = "excluded-review-state";

// Decision keys → PRISMA disposition (mapped server-side via apply_triage_decisions.py)
const DECISION_OPTIONS = [
  {{ key: "",                  label: "— pending —",                kind: "pending"  }},
  {{ key: "confirm-excluded",  label: "✓ Confirm exclusion",        kind: "confirm-excluded" }},
  {{ key: "revert-include",    label: "↺ Revert — include in review", kind: "revert-include" }},
  {{ key: "reclassify",        label: "→ Re-classify…",             kind: "reclassify" }},
];

const RECLASSIFY_TARGETS = [
  {{ key: "skip_off",     label: "off-topic" }},
  {{ key: "skip_nobeh",   label: "no behaviour" }},
  {{ key: "skip_fp",      label: "false-positive" }},
  {{ key: "skip_mdma",    label: "MDMA-only" }},
  {{ key: "skip_paywall", label: "paywall (give up)" }},
];

let state = {{
  decisions: {{}},        // {{doi: {{kind: "...", reclassify: "..."}}}}
  search: "",
}};

try {{
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) Object.assign(state, JSON.parse(saved));
}} catch (e) {{}}

function saveState() {{
  try {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }} catch (e) {{}}
}}

function escapeHtml(s) {{
  return String(s ?? "").replace(/[&<>"']/g, c => ({{
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }})[c]);
}}

function render() {{
  const root = document.getElementById("cards");
  const q = state.search.toLowerCase().trim();
  let visible = PAPERS;
  if (q) {{
    visible = visible.filter(p =>
      (p.title || "").toLowerCase().includes(q) ||
      (p.first_author || "").toLowerCase().includes(q) ||
      (p.doi || "").toLowerCase().includes(q) ||
      (p.journal || "").toLowerCase().includes(q));
  }}

  if (!visible.length) {{
    root.innerHTML = "";
    document.getElementById("emptyMsg").style.display = "block";
  }} else {{
    document.getElementById("emptyMsg").style.display = "none";
    root.innerHTML = visible.map(renderCard).join("");
  }}

  document.getElementById("visibleCount").textContent = visible.length;
  const reviewed = Object.values(state.decisions).filter(d => d && d.kind).length;
  document.getElementById("reviewedCount").textContent = reviewed;

  // Progress bar segments
  const tally = {{ "confirm-excluded": 0, "revert-include": 0, "reclassify": 0 }};
  for (const d of Object.values(state.decisions)) {{
    if (d && d.kind && tally[d.kind] !== undefined) tally[d.kind]++;
  }}
  const N = PAPERS.length;
  const colors = {{ "confirm-excluded": "#d2a368", "revert-include": "#4ad295", "reclassify": "#6090e0" }};
  document.getElementById("progressBar").innerHTML = Object.entries(tally)
    .filter(([_, n]) => n > 0)
    .map(([k, n]) => `<span style="width:${{(100 * n / N).toFixed(2)}}%; background:${{colors[k]}};" title="${{k}}: ${{n}}"></span>`)
    .join("");
  const pending = N - reviewed;
  document.getElementById("progressLegend").innerHTML = `
    <span><span class="swatch" style="background:#d2a368"></span>Confirm exclusion: <b>${{tally["confirm-excluded"]}}</b></span>
    <span><span class="swatch" style="background:#4ad295"></span>Revert (include): <b>${{tally["revert-include"]}}</b></span>
    <span><span class="swatch" style="background:#6090e0"></span>Re-classify: <b>${{tally["reclassify"]}}</b></span>
    <span><span class="swatch" style="background:#eee"></span>Pending: <b>${{pending}}</b></span>
    <span style="margin-left:auto; color:#444">Reviewed: <b>${{reviewed}}</b> / ${{N}}</span>`;
}}

function renderCard(p) {{
  const dec = state.decisions[p.doi] || {{}};
  const kind = dec.kind || "";
  const cls = kind ? ` ${{kind}}` : "";
  const doiUrl = p.doi ? `https://doi.org/${{p.doi}}` : "";
  const ttl = escapeHtml(p.title || "(no title)");
  const notesHtml = (p.judge_notes || []).map(n => `<li>${{escapeHtml(n)}}</li>`).join("");

  const radios = DECISION_OPTIONS.filter(o => o.key).map(o => {{
    const checked = kind === o.kind ? "checked" : "";
    return `<label class="${{o.kind}}">
      <input type="radio" name="d-${{escapeHtml(p.doi)}}" value="${{o.kind}}" ${{checked}}>
      <span>${{o.label}}</span>
    </label>`;
  }}).join("");

  let reclassifyDropdown = "";
  if (kind === "reclassify") {{
    reclassifyDropdown = `→ as: <select class="reclassify-target" data-doi="${{escapeHtml(p.doi)}}">
      ${{RECLASSIFY_TARGETS.map(t => `<option value="${{t.key}}" ${{dec.reclassify === t.key ? "selected" : ""}}>${{t.label}}</option>`).join("")}}
    </select>`;
  }}

  const scholarUrl = `https://scholar.google.com/scholar?q=${{encodeURIComponent(p.title || p.doi)}}`;
  const semScholarUrl = `https://www.semanticscholar.org/search?q=${{encodeURIComponent(p.doi || p.title)}}`;

  return `<div class="card${{cls}}" data-doi="${{escapeHtml(p.doi)}}">
    <div class="card-head">
      <h2>${{doiUrl ? `<a href="${{doiUrl}}" target="_blank" rel="noopener">${{ttl}}</a>` : ttl}}</h2>
    </div>
    <div class="meta">
      <b>${{escapeHtml(p.first_author)}}</b> · ${{escapeHtml(p.year)}}
      ${{p.journal ? ` · <i>${{escapeHtml(p.journal)}}</i>` : ""}}
      · <span class="doi">${{escapeHtml(p.doi)}}</span>
      ${{p.stem ? ` · stem <code>${{escapeHtml(p.stem)}}</code>` : ""}}
    </div>
    ${{notesHtml ? `<div class="judge-notes"><b>Judge's reasoning</b><ul>${{notesHtml}}</ul></div>` : ""}}
    <div class="actions-row">
      ${{radios}}
      ${{reclassifyDropdown}}
    </div>
    <div class="linkrow">
      ${{doiUrl ? `<a class="doi-link" href="${{doiUrl}}" target="_blank" rel="noopener">DOI</a>` : ""}}
      <a class="gscholar" href="${{scholarUrl}}" target="_blank" rel="noopener">GScholar</a>
      <a class="semscholar" href="${{semScholarUrl}}" target="_blank" rel="noopener">SemScholar</a>
    </div>
  </div>`;
}}

document.getElementById("search").value = state.search;
document.getElementById("search").addEventListener("input", e => {{
  state.search = e.target.value; saveState(); render();
}});
document.getElementById("resetFilters").addEventListener("click", () => {{
  state.search = "";
  document.getElementById("search").value = "";
  saveState(); render();
}});

// Decision capture (delegated)
document.getElementById("cards").addEventListener("change", e => {{
  const tgt = e.target;
  const card = tgt.closest(".card");
  if (!card) return;
  const doi = card.dataset.doi;
  if (tgt.type === "radio" && tgt.name.startsWith("d-")) {{
    state.decisions[doi] = state.decisions[doi] || {{}};
    state.decisions[doi].kind = tgt.value;
    if (tgt.value !== "reclassify") delete state.decisions[doi].reclassify;
    if (tgt.value === "reclassify" && !state.decisions[doi].reclassify) {{
      state.decisions[doi].reclassify = RECLASSIFY_TARGETS[0].key;
    }}
    saveState(); render();
  }} else if (tgt.classList.contains("reclassify-target")) {{
    state.decisions[doi] = state.decisions[doi] || {{kind: "reclassify"}};
    state.decisions[doi].reclassify = tgt.value;
    saveState();
  }}
}});

// Export JSON
document.getElementById("exportJson").addEventListener("click", () => {{
  const blob = new Blob([JSON.stringify(state.decisions, null, 2)], {{type: "application/json"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `excluded-review-decisions-${{new Date().toISOString().slice(0,10)}}.json`;
  a.click(); URL.revokeObjectURL(url);
}});

// Export CSV — same format as papers_to_download_v2.html so the merge tool reuses
document.getElementById("exportCsv").addEventListener("click", () => {{
  const lines = ["doi,status,reason,prisma_disposition"];
  // Map decisions to the same reason-key vocabulary used by apply_triage_decisions.py
  for (const p of PAPERS) {{
    const d = state.decisions[p.doi] || {{}};
    if (!d.kind) continue;
    let reason, disp;
    if (d.kind === "confirm-excluded") {{
      reason = "excluded_no_behaviour_in_full_text";
      disp   = "excluded_no_behaviour_in_full_text";
    }} else if (d.kind === "revert-include") {{
      reason = "done"; disp = "included_in_review";
    }} else if (d.kind === "reclassify") {{
      reason = d.reclassify || "skip_off";
      const dispMap = {{
        "skip_off": "excluded_classifier_off_topic",
        "skip_nobeh": "excluded_classifier_off_topic",
        "skip_fp": "excluded_classifier_false_positive",
        "skip_mdma": "excluded_compound_filter_MDMA",
        "skip_paywall": "pdf_unavailable_relevant",
      }};
      disp = dispMap[d.reclassify] || "excluded_classifier_off_topic";
    }} else continue;
    lines.push([p.doi, "skipped", reason, disp].map(x => `"${{String(x).replace(/"/g,'""')}}"`).join(","));
  }}
  const blob = new Blob([lines.join("\\n")], {{type: "text/csv"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `excluded-review-decisions-${{new Date().toISOString().slice(0,10)}}.csv`;
  a.click(); URL.revokeObjectURL(url);
}});

document.getElementById("importBtn").addEventListener("click", () =>
  document.getElementById("fileInput").click());
document.getElementById("fileInput").addEventListener("change", async e => {{
  const f = e.target.files[0];
  if (!f) return;
  try {{
    const text = await f.text();
    const imp = JSON.parse(text);
    state.decisions = {{...state.decisions, ...imp}};
    saveState(); render();
  }} catch (err) {{ alert("Import failed: " + err.message); }}
}});

render();
</script>

</body>
</html>
"""

    OUT.write_text(doc, encoding="utf-8")
    print(f"Wrote {OUT}  ({len(rows)} papers, {OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()

---
title: Study detail
toc: false
---

<style>
  :root { --observablehq-max-width: 1400px; }
  #observablehq-main { max-width: none !important; }
</style>

```js
const allStudies = await FileAttachment("../data/studies.json").json();
const stem = decodeURIComponent(location.pathname.split("/").filter(Boolean).pop() || "")
  .toLowerCase().replace(/\.html$/, "");
const stemKey = stem.replace(/[^a-z0-9]/g, "");
const study = allStudies.find(s => (s._stem || "").toLowerCase().replace(/[^a-z0-9]/g, "") === stemKey)
           || allStudies.find(s => (s.study_id || "").toLowerCase().replace(/[^a-z0-9]/g, "") === stemKey);
```

```js
function normalizeSpecies(raw) {
  if (raw == null) return "not reported";
  const s = String(raw).toLowerCase().trim();
  if (!s) return "not reported";
  const hasMouse = /\bmouse|mice\b/.test(s);
  const hasRat = /\brat\b/.test(s);
  if (hasMouse && hasRat) return "mouse and rat";
  if (hasMouse) return "mouse";
  if (hasRat) return "rat";
  return "other";
}
function joinAuthors(authors) {
  if (!authors || !authors.length) return "";
  if (authors.length === 1) return authors[0];
  if (authors.length === 2) return authors.join(" and ");
  return authors.slice(0, -1).join(", ") + ", and " + authors[authors.length - 1];
}
```

```js
if (!study) {
  display(html`<h1>Study not found</h1><p>No study with stem <code>${stem}</code> in the corpus.</p>
    <p><a href="../studies">← back to all studies</a></p>`);
}
```

```js
if (study) {
  const sc = study.study_level_scores || {};
  const year = (study.study_id || "").match(/(\d{4})/)?.[1] ?? study.pub_year ?? "?";
  const sex = study.sex || "not reported";
  display(html`<div class="paper-page">
    <div class="paper-header">
      <h1>${study.study_id}</h1>
      ${study.title ? html`<p class="paper-title">${study.title}</p>` : ""}
      ${study.authors && study.authors.length ? html`<p class="paper-authors">${joinAuthors(study.authors)}</p>` : ""}
      ${study.journal ? html`<p class="paper-journal"><i>${study.journal}</i>${study.pub_year ? ` · ${study.pub_year}` : ""}</p>` : ""}

      <div class="paper-meta-row">
        <span class="tag year">${year}</span>
        <span class="tag species">${normalizeSpecies(study.species)}</span>
        ${study.strain ? html`<span class="tag muted">${study.strain}</span>` : ""}
        <span class="tag muted">sex: ${sex}</span>
        <span class="tag psychedelic">${study.psychedelic ?? "?"}</span>
      </div>

      <div class="paper-links">
        ${study.doi ? html`<a href="https://doi.org/${study.doi}" target="_blank" rel="noopener" class="kbd">doi:${study.doi}</a>` : ""}
        ${study.url && !study.doi ? html`<a href="${study.url}" target="_blank" rel="noopener" class="kbd">${study.url}</a>` : ""}
      </div>
    </div>

    <h2>Scores</h2>
    <div class="score-grid">
      <div class="score-card beh"><div class="label">Behavioural</div><div class="value">${(sc.behavioural_complexity_max ?? 0).toFixed(1)}</div><div class="sublabel">/ 12</div></div>
      <div class="score-card env"><div class="label">Environmental</div><div class="value">${(sc.environmental_complexity_max ?? 0).toFixed(1)}</div><div class="sublabel">/ 11</div></div>
      <div class="score-card dur"><div class="label">Duration</div><div class="value">${((sc.recording_duration_banded_max ?? sc.recording_duration_max) ?? 0).toFixed(1)}</div><div class="sublabel">/ 11</div></div>
    </div>

    ${(study.dosing && study.dosing.length) ? html`<h2>Dosing</h2>
    <table class="kv">
      <tr><th>Compound</th><th>Doses (mg/kg)</th><th>Route</th><th>Vehicle</th><th>Schedule</th><th>Evidence</th></tr>
      ${study.dosing.map(d => html`<tr>
        <td class="k">${d.compound ?? ""}</td>
        <td>${Array.isArray(d.doses_mg_per_kg) && d.doses_mg_per_kg.length ? d.doses_mg_per_kg.join(", ") : (d.doses_raw ?? "")}</td>
        <td><span class="tag muted">${d.route ?? ""}</span></td>
        <td>${d.vehicle ?? ""}</td>
        <td><span class="tag muted">${d.schedule ?? ""}</span></td>
        <td><div class="evidence">${d.evidence ?? ""}</div></td>
      </tr>`)}
    </table>` : ""}

    <h2>Housing conditions</h2>
    <table class="kv">
      <tr><th>Field</th><th>Value</th><th>Confidence</th><th>Evidence</th></tr>
      ${Object.entries(study.housing_conditions || {}).map(([k, v]) => html`<tr>
        <td class="k">${k.replace(/_/g, " ")}</td>
        <td><span class="tag value-${(v.value||"").replace(/[^a-z]/g,"")}">${v.value}</span></td>
        <td>${v.confidence ?? ""}</td>
        <td><div class="evidence">${v.evidence ?? ""}</div></td>
      </tr>`)}
    </table>

    ${(study.assays || []).length ? html`<h2>Assays (${study.assays.length})</h2>` : ""}
    ${(study.assays || []).map(a => html`<details class="assay" open>
      <summary>
        <b>${a.assay_name}</b>
        <span class="assay-mini">B=${a.behavioural_complexity?.raw_total ?? "?"} · E=${a.environmental_complexity?.raw_total ?? "?"} · D=${a.recording_duration?.raw_total ?? "?"}</span>
      </summary>
      ${a.assay_description ? html`<p class="assay-desc">${a.assay_description}</p>` : ""}

      ${a.outcomes && (a.outcomes.summary || a.outcomes.direction) ? html`<h4>Outcomes</h4>
        <div class="outcome-box">
          <p>${a.outcomes.summary ?? ""}</p>
          <p class="outcome-meta">
            <span class="tag dir-${(a.outcomes.direction||"").replace(/[^a-z]/g,"")}">${a.outcomes.direction ?? ""}</span>
            ${a.outcomes.dose_dependent && a.outcomes.dose_dependent !== "n/a" ? html`<span class="tag muted">dose ${a.outcomes.dose_dependent}</span>` : ""}
            ${a.outcomes.sex_dependent && a.outcomes.sex_dependent !== "n/a" ? html`<span class="tag muted">sex ${a.outcomes.sex_dependent}</span>` : ""}
            ${a.outcomes.time_dependent && a.outcomes.time_dependent !== "n/a" ? html`<span class="tag muted">time ${a.outcomes.time_dependent}</span>` : ""}
          </p>
          ${a.outcomes.statistics ? html`<p class="evidence"><b>Stats:</b> ${a.outcomes.statistics}</p>` : ""}
          ${a.outcomes.evidence ? html`<p class="evidence">${a.outcomes.evidence}</p>` : ""}
        </div>` : ""}

      ${a.sample_size ? html`<h4>Sample size</h4>
        <table class="kv">
          <tr>
            <td class="k">total n</td><td>${a.sample_size.n_total ?? "?"}</td>
            <td class="k">male</td><td>${a.sample_size.n_male ?? "?"}</td>
            <td class="k">female</td><td>${a.sample_size.n_female ?? "?"}</td>
            <td class="k">min/group</td><td>${a.sample_size.n_per_group_min ?? "?"}</td>
          </tr>
          ${a.sample_size.evidence ? html`<tr><td colspan="8"><div class="evidence">${a.sample_size.evidence}</div></td></tr>` : ""}
        </table>` : ""}

      ${a.experimental_conditions ? html`<h4>Experimental conditions</h4>
        <table class="kv">
          <tr><th>Field</th><th>Value</th><th>Evidence</th></tr>
          ${Object.entries(a.experimental_conditions).map(([k, v]) => html`<tr>
            <td class="k">${k.replace(/_/g, " ")}</td>
            <td><span class="tag value-${(v.value||"").replace(/[^a-z]/g,"")}">${v.value ?? ""}</span></td>
            <td><div class="evidence">${v.evidence ?? ""}</div></td>
          </tr>`)}
        </table>` : ""}

      ${["behavioural_complexity","environmental_complexity","recording_duration"].map(dim => {
        if (!a[dim]) return "";
        const cls = dim.startsWith("beh") ? "beh" : dim.startsWith("env") ? "env" : "dur";
        return html`<details class="dim-block ${cls}">
          <summary><b>${dim.replace(/_/g, " ")}</b> · raw total ${a[dim].raw_total}</summary>
          <table class="kv items">
            <tr><th>Item</th><th>Score</th><th>Value</th><th>Confidence</th><th>Evidence</th></tr>
            ${Object.entries(a[dim]).filter(([k]) => k !== "raw_total").map(([k, v]) => html`<tr>
              <td class="k">${k}</td>
              <td><b>${v.score}</b></td>
              <td>${v.value}</td>
              <td>${v.confidence ?? ""}</td>
              <td><div class="evidence">${v.evidence ?? ""}</div></td>
            </tr>`)}
          </table>
        </details>`;
      })}
    </details>`)}

    ${study.sex_evidence ? html`<details>
      <summary>Sex classification evidence</summary>
      <p class="evidence">${study.sex_evidence}</p>
    </details>` : ""}

    ${study.judge_notes && study.judge_notes.length ? html`<details>
      <summary>Notes (${study.judge_notes.length})</summary>
      <ul>${study.judge_notes.map(n => html`<li>${n}</li>`)}</ul>
    </details>` : ""}

    <p style="margin-top:32px;"><a href="../studies">← back to all studies</a></p>
  </div>`);
}
```

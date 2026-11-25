"""Monthly living-review update: search → PDFs → scoring → rebuild → report.

    uv run python pipeline/monthly_update.py                 # full run
    uv run python pipeline/monthly_update.py --skip-scoring  # no LLM calls

Steps:
  1. Pull the inbox (and files of unfinished papers) from the private store.
  2. Search PubMed for records added since the last run (search_pubmed.py).
  3. Fetch PDFs for new relevant records (fetch_pdfs.py).
  4. Docling → three SAIA models → judge, for papers without a consensus JSON
     yet, at most --max-papers per run (the rest wait for the next run).
  5. Add the new papers to the assay catalog; rebuild PRISMA accounting.
  6. Push new files to the store; write the PR description and the list of
     PDFs to supply by hand to WORK_DIR/reports/.

Only data/ changes in the repo, and existing published records are never
rewritten. Needs SAIA_API_KEY and the judge's keys (see .env.example) unless
--skip-scoring is given.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_assay_catalog  # noqa: E402
import fetch_pdfs  # noqa: E402
import preprints  # noqa: E402
import search_pubmed  # noqa: E402
import store  # noqa: E402
from paths import (CANDIDATES_DIR, CONSENSUS_DIR, MANUAL_DECISIONS_JSON,  # noqa: E402
                   PDF_DIR, PDF_INVENTORY_CSV, PUBMED_CSV, REGISTRY_JSON, REPORTS_DIR,
                   SUPP_DIR, WORK_DIR)

# Candidate models (tags from triple_score.MODELS). The published v2 ensemble
# was qwen,glm,gptoss; glm-4.7 and gpt-oss-120b are no longer served on SAIA.
CANDIDATE_MODELS = os.environ.get("SCORING_MODELS", "qwen,deepseek4,gemma4")
MAX_DROPPED_IN_PR = 100


def log(msg: str) -> None:
    print(f"[monthly] {msg}", flush=True)


def run_script(script: str, *args: str) -> int:
    cmd = [sys.executable, "-u", str(HERE / script), *args]
    log(" ".join(cmd[2:]))
    return subprocess.run(cmd, cwd=HERE).returncode


def unfinished_stems() -> list[str]:
    """Papers added by monthly runs that have no consensus JSON yet, oldest first."""
    reg = json.loads(REGISTRY_JSON.read_text())
    manual = json.loads(MANUAL_DECISIONS_JSON.read_text()) if MANUAL_DECISIONS_JSON.exists() else {}
    todo = [(e.get("added", ""), s) for s, e in reg.items()
            if e.get("match_via") == "monthly_update"
            and not (CONSENSUS_DIR / f"{s}.json").exists()
            and not preprints.deferred(e.get("doi"), e.get("journal"),
                                       (manual.get((e.get("doi") or "").lower()) or {}).get("disposition"))]
    return [s for _, s in sorted(todo)]


def saia_key_problem(base_url: str | None = None) -> str:
    """'' if SAIA accepts SAIA_API_KEY, else a message saying why not.

    Checked before scoring, because SAIA keys expire: without this, every
    paper fails Docling with HTTP 401 and the run still looks successful.
    A network hiccup is not treated as a key problem.
    """
    key = os.environ.get("SAIA_API_KEY", "")
    if not key:
        return "SAIA_API_KEY is not set"
    if base_url is None:
        from provider import SAIA_BASE_URL as base_url
    req = urllib.request.Request(f"{base_url.rstrip('/')}/models",
                                 headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            listed = {m.get("id") for m in json.loads(r.read() or b"{}").get("data", [])}
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            detail = e.read()[:200].decode("utf-8", "replace").strip()
            return f"SAIA rejected the API key (HTTP {e.code}: {detail})"
        return ""
    except (urllib.error.URLError, TimeoutError, ValueError):
        return ""
    from triple_score import MODELS
    ids = dict(MODELS)
    tags = [t for t in CANDIDATE_MODELS.split(",") if t]
    unknown = [t for t in tags if t not in ids]
    if unknown:
        return f"unknown model tag(s) in SCORING_MODELS: {', '.join(unknown)}"
    missing = [ids[t] for t in tags if listed and ids[t] not in listed]
    if missing:
        return f"SAIA no longer offers {', '.join(missing)} (SCORING_MODELS={CANDIDATE_MODELS})"
    return ""


# Runs in which a paper's missing candidate model is tried again before the paper
# is judged with the models that did score it.
MAX_CANDIDATE_ATTEMPTS = 2


def incomplete_verdicts() -> list[str]:
    """Monthly papers judged without every candidate model whose missing model
    hasn't been retried MAX_CANDIDATE_ATTEMPTS times yet."""
    reg = json.loads(REGISTRY_JSON.read_text())
    out = []
    for s, e in reg.items():
        path = CONSENSUS_DIR / f"{s}.json"
        if e.get("match_via") != "monthly_update" or not path.exists():
            continue
        if ((json.loads(path.read_text()).get("scoring") or {}).get("missing")
                and e.get("candidate_attempts", 0) < MAX_CANDIDATE_ATTEMPTS):
            out.append(s)
    return out


def plan_judging(stem: str, models: list[str], reg: dict) -> str:
    """What to do with a paper after candidate scoring: "judge", "hold" (wait for
    a missing model; counts the attempt in reg[stem]) or "skip" (nothing to judge).
    A verdict judged without a model that has now scored it is moved aside
    (<stem>.json.partial; score() puts it back if judging fails)."""
    have = [m for m in models if (CANDIDATES_DIR / m / f"{stem}.json").exists()]
    if not have:
        log(f"{stem}: no candidate scores, skipping judge")
        return "skip"
    verdict = CONSENSUS_DIR / f"{stem}.json"
    if len(have) < len(models):
        entry = reg.setdefault(stem, {"stem": stem})
        entry["candidate_attempts"] = entry.get("candidate_attempts", 0) + 1
        missing = ", ".join(m for m in models if m not in have)
        if verdict.exists():
            log(f"{stem}: still no score from {missing}; keeping the verdict from the others")
            return "hold"
        if entry["candidate_attempts"] < MAX_CANDIDATE_ATTEMPTS:
            log(f"{stem}: no score from {missing} yet; judged next run")
            return "hold"
        log(f"{stem}: no score from {missing} after {entry['candidate_attempts']} runs; "
            f"judging with {', '.join(have)}")
        return "judge"
    if verdict.exists():
        used = json.loads(verdict.read_text()).get("judge_input_models") or []
        if sorted(used) != sorted(have):
            log(f"{stem}: {', '.join(m for m in have if m not in used)} now scored it; "
                "judging again with every model")
            verdict.replace(verdict.with_name(verdict.name + ".partial"))
    return "judge"


def score(stems: list[str], judge_provider: str, workers: int) -> list[str]:
    """Docling, candidate scoring and judging for `stems` only (resumable).

    The scoring scripts process every PDF in the folder they're given, so this
    stages just `stems` in a run folder (laid out like WORK_DIR, so
    supplementary files are found) and copies the Docling markdown back.
    """
    if not stems:
        return
    run_dir = WORK_DIR / "run"
    shutil.rmtree(run_dir, ignore_errors=True)
    (run_dir / "pdfs").mkdir(parents=True)
    (run_dir / "pdfs_supplementary").mkdir()
    for s in stems:
        for f in [PDF_DIR / f"{s}.pdf", PDF_DIR / f"{s}.docling.md"]:
            if f.exists():
                shutil.copy2(f, run_dir / "pdfs" / f.name)
        for f in SUPP_DIR.glob(f"{s}_supp.*") if SUPP_DIR.exists() else []:
            shutil.copy2(f, run_dir / "pdfs_supplementary" / f.name)
    run_pdfs = run_dir / "pdfs"

    run_script("bulk_docling.py", "--pdf-dir", str(run_pdfs))
    for md in run_pdfs.glob("*.docling.md"):
        shutil.copy2(md, PDF_DIR / md.name)
    for md in (run_dir / "pdfs_supplementary").glob("*.docling.md"):
        SUPP_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(md, SUPP_DIR / md.name)
    run_script("triple_score.py", "--pdf-dir", str(run_pdfs),
               "--output-root", str(CANDIDATES_DIR), "--models", CANDIDATE_MODELS,
               "--workers", str(workers), "--limit", str(len(stems)))
    models = [m for m in CANDIDATE_MODELS.split(",") if m]
    reg = json.loads(REGISTRY_JSON.read_text())
    held = []  # waiting for a missing model; tried again next run
    for stem in stems:
        if not (run_pdfs / f"{stem}.docling.md").exists():
            log(f"{stem}: no Docling markdown, skipping judge")
            continue
        plan = plan_judging(stem, models, reg)
        if plan == "hold":
            held.append(stem)
            continue
        if plan == "skip":
            continue
        run_script("judge_consensus.py", "--pdf-dir", str(run_pdfs),
                   "--candidates-root", str(CANDIDATES_DIR),
                   "--output-dir", str(CONSENSUS_DIR),
                   "--judge-provider", judge_provider,
                   "--models", CANDIDATE_MODELS, "--stem", stem, "--resume")
        verdict, partial = CONSENSUS_DIR / f"{stem}.json", CONSENSUS_DIR / f"{stem}.json.partial"
        if partial.exists():
            if verdict.exists():
                partial.unlink()
            else:  # judging again failed: keep the earlier verdict
                partial.replace(verdict)
    REGISTRY_JSON.write_text(json.dumps(reg, indent=2, ensure_ascii=False))
    shutil.rmtree(run_dir, ignore_errors=True)
    return held


def mark_docling_in_inventory(stems: list[str]) -> None:
    """Set has_docling_md for stems whose markdown now exists."""
    done = {s for s in stems if (PDF_DIR / f"{s}.docling.md").exists()}
    if not done or not PDF_INVENTORY_CSV.exists():
        return
    raw = PDF_INVENTORY_CSV.read_bytes()
    eol = "\r\n" if b"\r\n" in raw else "\n"
    with open(PDF_INVENTORY_CSV, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    fields = list(rows[0].keys())
    for r in rows:
        if r["stem"] in done:
            r["has_docling_md"] = "True"
    with open(PDF_INVENTORY_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator=eol)
        w.writeheader()
        w.writerows(rows)


# ── Report ───────────────────────────────────────────────────────────────────

def _md_escape(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ")


def _consensus_row(stem: str, reg: dict) -> str:
    d = json.loads((CONSENSUS_DIR / f"{stem}.json").read_text())
    e = reg.get(stem, {})
    compounds = ", ".join(sorted({x.get("compound", "?") for x in d.get("dosing") or []})) or "—"
    sc = d.get("study_level_scores") or {}
    link = f"[{e.get('year', '')}]({e['url']})" if e.get("url") else e.get("year", "")
    return (f"| `{stem}` | {_md_escape((e.get('authors') or [''])[0])} {link} | "
            f"{_md_escape(e.get('title', ''))[:110]} | {_md_escape(compounds)} | "
            f"{len(d.get('assays') or [])} | "
            f"{sc.get('behavioural_complexity_max', 0):.1f} / "
            f"{sc.get('environmental_complexity_max', 0):.1f} / "
            f"{sc.get('recording_duration_max', 0):.1f} | {d.get('low_confidence_count', 0)} |")


def _route_multiple(stem: str) -> bool:
    d = json.loads((CONSENSUS_DIR / f"{stem}.json").read_text())
    return any((x.get("route") or "") == "multiple" for x in d.get("dosing") or [])


def _setup_section(scored: list[str]) -> list[str]:
    """Which models scored this run's papers (also in data/scoring_provenance.csv)."""
    import provenance
    rows = [provenance.describe(s, json.loads((CONSENSUS_DIR / f"{s}.json").read_text()))
            for s in scored]
    if not rows:
        return []
    setups: dict[tuple[str, str], int] = {}
    for r in rows:
        setups[(r["setup_id"], r["setup"])] = setups.get((r["setup_id"], r["setup"]), 0) + 1
    lines = ["", "## Scoring setup",
             "Per paper in `data/scoring_provenance.csv` (models, judge, rubric and code "
             "versions).", ""]
    lines += [f"- `{sid}` {setup}: {n} paper(s)" for (sid, setup), n in setups.items()]
    short = [r for r in rows if r["missing_candidates"]]
    if short:
        lines.append("- Judged without every candidate (a model failed on the paper): "
                     + ", ".join(f"`{r['stem']}` (no {r['missing_candidates']})" for r in short))
    fallback = [r for r in rows if r["declined_by"]]
    if fallback:
        lines.append("- Judged by the fallback model after the judge declined: "
                     + ", ".join(f"`{r['stem']}` ({r['judged_by']})" for r in fallback))
    return lines


def deferred_preprints() -> list[dict]:
    """Relevant preprints from the monthly searches that are set aside for now."""
    from classify_compounds import decision
    if not PUBMED_CSV.exists():
        return []
    manual = json.loads(MANUAL_DECISIONS_JSON.read_text()) if MANUAL_DECISIONS_JSON.exists() else {}
    with open(PUBMED_CSV, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("source") or "").startswith("update:")]
    return [r for r in rows if decision(r["detected_compounds"]) == "relevant"
            and preprints.deferred(r["doi"], r.get("journal"),
                                   (manual.get(r["doi"].strip().lower()) or {}).get("disposition"))]


def write_reports(today: date, search: dict, fetched: dict, scored: list[str],
                  unfinished: list[str], scoring_ran: bool,
                  rechecked: list[dict] | None = None, scoring_problem: str = "",
                  scoring_failed: list[str] | None = None,
                  held: list[str] | None = None) -> dict:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    reg = json.loads(REGISTRY_JSON.read_text())
    with_assays = [s for s in scored
                   if json.loads((CONSENSUS_DIR / f"{s}.json").read_text()).get("assays")]
    no_assays = [s for s in scored if s not in with_assays]
    by = search["by_decision"]
    recs = search["records"]
    lines = [
        *([f"> [!WARNING]\n> **Scoring didn't run:** {scoring_problem}. Renew the key and "
           "update the repository secret; the papers stay `pending_scoring` and are "
           "scored on the next run.", ""] if scoring_problem else []),
        *([f"> [!WARNING]\n> **Scoring failed for {len(scoring_failed)} paper(s):** "
           + ", ".join(f"`{x}`" for x in scoring_failed)
           + ". The errors are in this run's log (Actions tab); they are retried on the "
           "next run.", ""] if scoring_failed else []),
        f"Monthly update for {today.isoformat()}, generated by "
        "`pipeline/monthly_update.py`. Review before merging; merging republishes "
        "the dashboard.",
        "",
        "## Search",
        f"PubMed records added {search['window'][0]} – {search['window'][1]}: "
        f"**{search['returned']}** returned, **{search['new']}** new.",
        "",
        f"- Relevant by title: {by['relevant']}",
        f"- Not primary research (PubMed tags them as review, news, letter, …): "
        f"{by['not_primary']}"
        + (f", plus {len(rechecked)} earlier record(s) tagged since" if rechecked else ""),
        f"- Duplicates of corpus papers (e.g. journal version of a preprint): {by['duplicate']}",
        f"- Dropped by the classifier: {by['false_positive'] + by['off_topic'] + by['mdma_only']} "
        f"(no compound {by['false_positive']}, off-topic {by['off_topic']}, "
        f"MDMA-only {by['mdma_only']})",
        "",
        "## Studies added",
    ]
    if with_assays:
        lines += ["Scores are B / E / D maxima (behavioural complexity, environmental "
                  "complexity, recording duration).", "",
                  "| stem | first author, year | title | compounds dosed | assays | B / E / D | low-conf items |",
                  "|---|---|---|---|---|---|---|"]
        lines += [_consensus_row(s, reg) for s in with_assays]
    else:
        lines.append("None this run.")
    if no_assays:
        lines += ["", "Scored but **no behavioural assay** found (they will show as "
                  "`in_corpus_no_animal_dose` in PRISMA): "
                  + ", ".join(f"`{s}`" for s in no_assays)]
    lines += _setup_section(scored)
    lines += ["", "## Still in progress"]
    if not scoring_ran:
        lines.append("Scoring was skipped this run (no API keys, or `--skip-scoring`).")
    lines.append(f"- PDFs retrieved this run: {len(fetched['fetched'])}")
    lines.append(f"- Papers with a PDF but no consensus yet (retried next run): "
                 f"{len(unfinished)}" + (f" — {', '.join(f'`{s}`' for s in unfinished)}"
                                         if unfinished else ""))
    if held:
        lines.append("- A candidate model didn't score these, so they wait for it (tried "
                     f"again next run, at most {MAX_CANDIDATE_ATTEMPTS} runs): "
                     + ", ".join(f"`{s}`" for s in held))
    inbox = fetched.get("inbox") or {}
    if inbox.get("matched"):
        lines.append(f"- Inbox files matched to their paper by DOI or title: "
                     f"{len(inbox['matched'])}")
    if inbox.get("unmatched"):
        lines.append("- **Inbox files that couldn't be matched** (no known DOI or title on "
                     "the first page; rename to `<pmid>.pdf`): "
                     + ", ".join(f"`{n}`" for n in inbox["unmatched"]))
    lines.append(f"- Relevant papers waiting for a PDF: {len(fetched['missing'])} "
                 "(see the *Monthly update: PDFs needed* issue)")

    deferred = deferred_preprints()
    if deferred:
        lines += ["", f"## Preprints set aside ({len(deferred)})",
                  "New preprints aren't fetched or scored for now (`deferred_preprint` in "
                  "PRISMA). Set the repository variable `INCLUDE_PREPRINTS` to `true` to "
                  "include them all, or add one to `data/manual_decisions.json` as "
                  "`included_in_review`.", ""]
        lines += [f"- {r['pmid']} · {_md_escape(r['title'])} · https://doi.org/{r['doi']}"
                  for r in deferred]

    dups = [r for r in recs if r["decision"] == "duplicate"]
    if dups:
        lines += ["", "## Duplicates recorded",
                  "Added to `data/manual_decisions.json` as `excluded_duplicate_of_corpus`:", ""]
        lines += [f"- PMID {r['pmid']} → `{r['duplicate_of']}`: {_md_escape(r['title'])}"
                  for r in dups]

    non_primary = [r for r in recs if r["decision"] == "not_primary"] + (rechecked or [])
    if non_primary:
        lines += ["", "## Excluded as not primary research",
                  "Tagged by PubMed as below, so no PDF was fetched. Recorded in "
                  "`data/manual_decisions.json` as `excluded_not_primary_research`; to "
                  "include one after all, change its disposition to `included_in_review`.",
                  ""]
        lines += [f"- {r['pmid']} · {r['non_primary_type']} · {_md_escape(r['title'])}"
                  for r in non_primary]

    checks = ["- [ ] Spot-check a few of the new scores against the papers."]
    multi = [s for s in with_assays if _route_multiple(s)]
    if multi:
        checks.append("- [ ] Route `multiple` for " + ", ".join(f"`{s}`" for s in multi)
                      + ": add them to `MULTI_ROUTE_MAP` in "
                      "`figures/plot_application_donut.py` and regenerate "
                      "`data/multi_route_map.json`, or the applications page drops them.")
    checks.append("- [ ] Check the dropped titles below for anything the classifier missed.")
    lines += ["", "## Review checklist", *checks]

    dropped = [r for r in recs if r["decision"] in ("false_positive", "off_topic", "mdma_only")]
    dropped_lines = [f"- {r['pmid']} · {_md_escape(r['detected_compounds'])} · "
                     f"{_md_escape(r['title'])}" for r in dropped]
    (REPORTS_DIR / "dropped_titles.md").write_text(
        f"# Titles dropped by the classifier ({today.isoformat()})\n\n"
        + "\n".join(dropped_lines) + "\n")
    if dropped:
        # GitHub caps a PR description at 65,536 characters; a normal month
        # drops ~40 titles, the catch-up run drops ~350.
        shown = dropped_lines[:MAX_DROPPED_IN_PR]
        lines += ["", "<details><summary>Titles dropped by the classifier "
                  f"({len(dropped)})</summary>", "",
                  "To rescue one, add its DOI to `data/manual_decisions.json` with "
                  '`"disposition": "included_in_review"`; the next run fetches and scores it.',
                  "", *shown]
        if len(dropped) > len(shown):
            lines += ["", f"…and {len(dropped) - len(shown)} more: see `dropped_titles.md` "
                      "in this run's **monthly-update-reports** artifact (Actions tab)."]
        lines += ["", "</details>"]
    (REPORTS_DIR / "pr_body.md").write_text("\n".join(lines) + "\n")

    miss = [
        "PDFs for these relevant papers couldn't be found in open access. To add "
        "one, save it in the store's `inbox/` folder. **Any file name works**: each "
        "run reads the DOI on the PDF's first page (or its title) and files it under "
        "the paper. A supplement needs its name: `<pmid>_supp.pdf` or `.docx` (the "
        "PMID is shown below). The next run, or a manual run of the *Monthly update* "
        "workflow, picks them up.",
        "",
    ]
    miss += [f"- [ ] `{m['inbox_filename']}` — {_md_escape(m['authors_short'])} "
             f"({m['year']}) {_md_escape(m['title'])}"
             + (f" · https://doi.org/{m['doi']}" if m["doi"] else "")
             for m in fetched["missing"]]
    (REPORTS_DIR / "missing_pdfs.md").write_text("\n".join(miss) + "\n")

    summary = {
        "date": today.isoformat(), "search": {k: v for k, v in search.items() if k != "records"},
        "fetched": [f["stem"] for f in fetched["fetched"]],
        "missing_pdfs": len(fetched["missing"]), "scored": scored,
        "added_with_assays": with_assays, "unfinished": unfinished,
        "scoring_ran": scoring_ran, "scoring_problem": scoring_problem,
    }
    (REPORTS_DIR / "run_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    load_dotenv(HERE.parent / ".env")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-scoring", action="store_true",
                    help="search, fetch and rebuild only; no LLM calls")
    ap.add_argument("--max-papers", type=int, default=int(os.environ.get("MAX_PAPERS", 30)),
                    help="most papers to score this run (default 30, or $MAX_PAPERS)")
    ap.add_argument("--judge-provider", default=os.environ.get("JUDGE_PROVIDER", "foundry"),
                    choices=["foundry", "anthropic", "openrouter", "saia"])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-download", action="store_true",
                    help="take PDFs from the inbox only; don't try open-access sources")
    args = ap.parse_args()
    today = date.today()

    store.pull_inbox()
    store.pull_stems(unfinished_stems())

    log("searching PubMed")
    search = search_pubmed.run(today)
    log(f"{search['new']} new records, {search['by_decision']['relevant']} relevant")
    rechecked = search_pubmed.recheck_publication_types(today)
    if rechecked:
        log(f"{len(rechecked)} waiting record(s) now tagged as non-primary; excluded")

    log("fetching PDFs")
    fetched = fetch_pdfs.run(today, offline=args.no_download)
    log(f"{len(fetched['fetched'])} PDFs retrieved, {len(fetched['missing'])} still missing")
    # Save new PDFs straight away, so a later failure doesn't lose them.
    store.push_stems([f["stem"] for f in fetched["fetched"]])
    store.clear_inbox([f["pmid"] for f in fetched["fetched"] if f["source"] == "inbox"])

    # New papers first, then earlier ones judged without every model (retry it).
    unfinished = unfinished_stems()
    todo = (unfinished + [s for s in incomplete_verdicts() if s not in unfinished])[: args.max_papers]
    held: list[str] = []
    scoring_ran = not args.skip_scoring and bool(os.environ.get("SAIA_API_KEY"))
    scoring_problem = ""
    if todo and not scoring_ran:
        log("scoring skipped (--skip-scoring or SAIA_API_KEY not set)")
    if todo and scoring_ran:
        scoring_problem = saia_key_problem()
        if scoring_problem:
            scoring_ran = False
            log(f"scoring skipped: {scoring_problem}")
            if os.environ.get("GITHUB_ACTIONS"):
                print(f"::error title=Scoring skipped::{scoring_problem}", flush=True)
    if todo and scoring_ran:
        log(f"scoring {len(todo)} paper(s): {', '.join(todo)}")
        store.pull_stems(todo)  # reuse any earlier candidate scores
        held = score(todo, args.judge_provider, args.workers)
        store.push_stems(todo)
    scored = [s for s in todo if (CONSENSUS_DIR / f"{s}.json").exists() and s not in held]
    scoring_failed = [s for s in todo if scoring_ran and s not in scored and s not in held
                      and not (CONSENSUS_DIR / f"{s}.json").exists()]
    if scoring_failed:
        log(f"scoring failed for: {', '.join(scoring_failed)}")
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::warning title=Scoring failed::{len(scoring_failed)} paper(s): "
                  f"{', '.join(scoring_failed)}", flush=True)
    mark_docling_in_inventory(todo)

    log("updating assay catalog and PRISMA accounting")
    if scored:
        build_assay_catalog.add_papers(scored)
    if run_script("build_prisma_accounting.py") != 0:
        sys.exit("build_prisma_accounting.py failed")
    import provenance
    provenance.build()  # data/scoring_provenance.csv: models behind every score

    summary = write_reports(today, search, fetched, scored, unfinished_stems(), scoring_ran,
                            rechecked, scoring_problem, scoring_failed, held)
    log(f"done: {len(summary['added_with_assays'])} studies added; "
        f"reports in {REPORTS_DIR}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"added={len(summary['added_with_assays'])}\n")
            f.write(f"missing_pdfs={summary['missing_pdfs']}\n")
            f.write(f"new_records={search['new']}\n")
            f.write(f"run_date={today.isoformat()}\n")


if __name__ == "__main__":
    main()

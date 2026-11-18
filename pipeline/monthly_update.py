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
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_assay_catalog  # noqa: E402
import fetch_pdfs  # noqa: E402
import search_pubmed  # noqa: E402
import store  # noqa: E402
from paths import (CANDIDATES_DIR, CONSENSUS_DIR, PDF_DIR,  # noqa: E402
                   PDF_INVENTORY_CSV, REGISTRY_JSON, REPORTS_DIR, SUPP_DIR, WORK_DIR)

CANDIDATE_MODELS = "qwen,glm,gptoss"
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
    todo = [(e.get("added", ""), s) for s, e in reg.items()
            if e.get("match_via") == "monthly_update"
            and not (CONSENSUS_DIR / f"{s}.json").exists()]
    return [s for _, s in sorted(todo)]


def score(stems: list[str], judge_provider: str, workers: int) -> None:
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
    for stem in stems:
        if not (run_pdfs / f"{stem}.docling.md").exists():
            log(f"{stem}: no Docling markdown, skipping judge")
            continue
        if not any((CANDIDATES_DIR / m / f"{stem}.json").exists()
                   for m in CANDIDATE_MODELS.split(",")):
            log(f"{stem}: no candidate scores, skipping judge")
            continue
        run_script("judge_consensus.py", "--pdf-dir", str(run_pdfs),
                   "--candidates-root", str(CANDIDATES_DIR),
                   "--output-dir", str(CONSENSUS_DIR),
                   "--judge-provider", judge_provider,
                   "--models", CANDIDATE_MODELS, "--stem", stem, "--resume")
    shutil.rmtree(run_dir, ignore_errors=True)


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


def write_reports(today: date, search: dict, fetched: dict, scored: list[str],
                  unfinished: list[str], scoring_ran: bool,
                  rechecked: list[dict] | None = None) -> dict:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    reg = json.loads(REGISTRY_JSON.read_text())
    with_assays = [s for s in scored
                   if json.loads((CONSENSUS_DIR / f"{s}.json").read_text()).get("assays")]
    no_assays = [s for s in scored if s not in with_assays]
    by = search["by_decision"]
    recs = search["records"]
    lines = [
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
    lines += ["", "## Still in progress"]
    if not scoring_ran:
        lines.append("Scoring was skipped this run (no API keys, or `--skip-scoring`).")
    lines.append(f"- PDFs retrieved this run: {len(fetched['fetched'])}")
    lines.append(f"- Papers with a PDF but no consensus yet (retried next run): "
                 f"{len(unfinished)}" + (f" — {', '.join(f'`{s}`' for s in unfinished)}"
                                         if unfinished else ""))
    lines.append(f"- Relevant papers waiting for a PDF: {len(fetched['missing'])} "
                 "(see the *Monthly update: PDFs needed* issue)")

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
        "one, save it in the store's `inbox/` folder under the name shown "
        "(`<pmid>.pdf`; a supplement as `<pmid>_supp.pdf` or `.docx`). The next "
        "run, or a manual run of the *Monthly update* workflow, picks it up.",
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
        "scoring_ran": scoring_ran,
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

    todo = unfinished_stems()[: args.max_papers]
    scoring_ran = not args.skip_scoring and bool(os.environ.get("SAIA_API_KEY"))
    if todo and not scoring_ran:
        log("scoring skipped (--skip-scoring or SAIA_API_KEY not set)")
    if scoring_ran:
        log(f"scoring {len(todo)} paper(s): {', '.join(todo)}")
        store.pull_stems(todo)  # reuse any earlier candidate scores
        score(todo, args.judge_provider, args.workers)
        store.push_stems(todo)
    scored = [s for s in todo if (CONSENSUS_DIR / f"{s}.json").exists()]
    mark_docling_in_inventory(todo)

    log("updating assay catalog and PRISMA accounting")
    if scored:
        build_assay_catalog.add_papers(scored)
    if run_script("build_prisma_accounting.py") != 0:
        sys.exit("build_prisma_accounting.py failed")

    summary = write_reports(today, search, fetched, scored, unfinished_stems(), scoring_ran,
                            rechecked)
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

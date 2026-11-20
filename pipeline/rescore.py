"""Rescore published papers with the current setup, keeping the published scores.

By default: the published papers whose verdict was judged without every
candidate model (`missing_candidates` in data/scoring_provenance.csv). The
models they are missing (glm-4.7, gpt-oss-120b) and the judge (Opus 4.7) are
retired, so they are scored again from scratch with --ensemble and the current
judge. The published scores in data/results_v2_full_consensus/ are not touched.

Inputs: the published pipeline's Docling text, WORK_DIR/rescore/inputs/
<stem>.docling.md (+ <stem>_supp.docling.md); the workflow pulls them from the
PDF store's rescore/inputs/ folder.

Output, under data/rescored/<name>/ (name defaults to the ensemble tags):
  consensus/<stem>.json      the new verdicts (with their `scoring` block)
  scoring_provenance.csv     models, judge, rubric and code versions per paper
  comparison.md / .json      published vs rescored, per assay and per paper

    uv run python pipeline/rescore.py --ensemble qwen,deepseek4,gemma4
    uv run python pipeline/rescore.py --compare-only      # rebuild the comparison
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "figures"))

import numpy as np  # noqa: E402

import plot_three_way as tw  # noqa: E402
import provenance  # noqa: E402
import rater_lib as rl  # noqa: E402
from bridge_test import _fmt, load_items, run_script  # noqa: E402
from paths import CONSENSUS_DIR, DATA_DIR, WORK_DIR  # noqa: E402
from triple_score import worth_retrying  # noqa: E402

WORK = WORK_DIR / "rescore"
INPUTS = WORK / "inputs"
PDFS = WORK / "pdfs"
SUPP = WORK / "pdfs_supplementary"
CANDIDATES = WORK / "candidates"
STUDY_KEYS = ("behavioural_complexity_max", "environmental_complexity_max",
              "recording_duration_max")


def log(msg: str) -> None:
    print(f"[rescore] {msg}", flush=True)


def missing_candidate_stems() -> dict[str, str]:
    """Published papers judged without every candidate: {stem: missing models}."""
    path = DATA_DIR / "scoring_provenance.csv"
    if not path.exists():
        provenance.build()
    return {r["stem"]: r["missing_candidates"] for r in csv.DictReader(path.open())
            if r["setup"] == provenance.PUBLISHED_SETUP and r["missing_candidates"]}


def stage(stems: list[str]) -> list[str]:
    """Put each paper's published text in place; returns the stems that have it."""
    PDFS.mkdir(parents=True, exist_ok=True)
    SUPP.mkdir(parents=True, exist_ok=True)
    ready = []
    for stem in stems:
        md = INPUTS / f"{stem}.docling.md"
        if not (md.exists() and md.stat().st_size > 0):
            log(f"{stem}: no text in inputs/, skipped")
            continue
        shutil.copy2(md, PDFS / md.name)
        (PDFS / f"{stem}.pdf").touch()  # the scoring scripts select papers by PDF
        supp = INPUTS / f"{stem}_supp.docling.md"
        if supp.exists():
            shutil.copy2(supp, SUPP / supp.name)
            (SUPP / f"{stem}_supp.pdf").touch()
        ready.append(stem)
    return ready


def coverage(stems: list[str], tags: list[str]) -> dict[str, list[str]]:
    return {t: [s for s in stems if (CANDIDATES / t / f"{s}.json").exists()] for t in tags}


# ── Comparison ───────────────────────────────────────────────────────────────

def compare(stems: list[str], new_dir: Path) -> dict:
    """Published vs rescored: assay-level agreement and per-paper changes."""
    pairs, papers = [], {}
    for stem in stems:
        pub, new = load_items(CONSENSUS_DIR / f"{stem}.json"), load_items(new_dir / f"{stem}.json")
        if pub is None or new is None:
            continue
        matched = dict(rl.pair_assays([{"name": a["assay_name"]} for a in pub],
                                      [{"assay_name": a["assay_name"]} for a in new]))
        for i, a in enumerate(pub):
            j = matched.get(i)
            pairs.append({"stem": stem, "assay_name": a["assay_name"],
                          "published": {k: a[k] for k in "BED"},
                          "rescored": None if j is None else {k: new[j][k] for k in "BED"}})
        p_sl = json.loads((CONSENSUS_DIR / f"{stem}.json").read_text())["study_level_scores"]
        n_sl = json.loads((new_dir / f"{stem}.json").read_text())["study_level_scores"]
        papers[stem] = {"assays_published": len(pub), "assays_rescored": len(new),
                        "matched": len(matched),
                        **{f"{k}_published": p_sl[k] for k in STUDY_KEYS},
                        **{f"{k}_rescored": n_sl[k] for k in STUDY_KEYS}}
    study = {}
    for k in STUDY_KEYS:
        a = [p[f"{k}_published"] for p in papers.values()]
        b = [p[f"{k}_rescored"] for p in papers.values()]
        if a:
            study[k] = {"n": len(a), "mean_diff": float(np.mean(np.array(b) - np.array(a))),
                        "mean_abs_diff": float(np.mean(np.abs(np.array(b) - np.array(a)))),
                        "spearman": tw._plot.spearman(a, b) if len(a) > 2 else None}
    return {"assay_agreement": tw.pair_stats(pairs, "published", "rescored"),
            "study_level": study, "papers": papers,
            "assays_published": sum(p["assays_published"] for p in papers.values()),
            "assays_rescored": sum(p["assays_rescored"] for p in papers.values()),
            "assays_matched": sum(p["matched"] for p in papers.values())}


def report(out_dir: Path, stems: list[str], missing: dict[str, str], trio: list[str],
           judged: list[str], cmp: dict, problems: list[str]) -> Path:
    rows = list(csv.DictReader((out_dir / "scoring_provenance.csv").open())) \
        if (out_dir / "scoring_provenance.csv").exists() else []
    setups = sorted({(r["setup_id"], r["setup"]) for r in rows})
    payload = {"date": date.today().isoformat(), "ensemble": trio, "setups": setups,
               "papers_requested": stems, "papers_judged": judged, "complete": not problems,
               "problems": problems, "published_missing": missing, **cmp}
    (out_dir / "comparison.json").write_text(json.dumps(payload, indent=2, default=float))

    L = [f"# Rescore of published papers ({date.today().isoformat()})", ""]
    if problems:
        L += ["> **Incomplete run.**", ">"] + [f"> - {p}" for p in problems] + [""]
    L += [f"{len(judged)} of {len(stems)} published papers rescored. They were originally "
          "judged without every candidate model; those models and the judge are retired, so "
          "they were scored again from scratch. The published scores "
          "(`data/results_v2_full_consensus/`) are unchanged.", ""]
    L += [f"Setup: `{sid}` {label}" for sid, label in setups] + [""]
    L += ["## Assay level, published vs rescored", "",
          f"Assays: {cmp['assays_published']} published, {cmp['assays_rescored']} rescored, "
          f"{cmp['assays_matched']} matched by name. Agreement on B/E/D totals of matched "
          "assays (statistics as in `figures/plot_three_way.py`; mean difference is "
          "published minus rescored):", "",
          "| dim | n | exact | mean diff | ρ | ICC |", "|---|---|---|---|---|---|"]
    for dim in "BED":
        r = cmp["assay_agreement"].get(dim)
        if r:
            L.append(f"| {dim} | {r['n']} | {r['pct']:.0f}% | {r['mean_diff']:+.2f} | "
                     f"{_fmt(r['spearman'])} | {_fmt(r['icc'])} |")
    if cmp["study_level"]:
        L += ["", "## Study-level maxima", "",
              "| score | n | mean change (rescored − published) | mean |change| | ρ |",
              "|---|---|---|---|---|"]
        for k, v in cmp["study_level"].items():
            L.append(f"| {k} | {v['n']} | {v['mean_diff']:+.2f} | {v['mean_abs_diff']:.2f} | "
                     f"{_fmt(v['spearman'])} |")
    L += ["", "## Papers", "",
          "| paper | published was missing | assays (pub → new) | B max | E max | D max |",
          "|---|---|---|---|---|---|"]
    for s in stems:
        p = cmp["papers"].get(s)
        if not p:
            L.append(f"| `{s}` | {missing.get(s, '')} | not rescored | | | |")
            continue
        cells = [f"{p[k + '_published']:.1f} → {p[k + '_rescored']:.1f}" for k in STUDY_KEYS]
        L.append(f"| `{s}` | {missing.get(s, '')} | {p['assays_published']} → "
                 f"{p['assays_rescored']} | " + " | ".join(cells) + " |")
    out = out_dir / "comparison.md"
    out.write_text("\n".join(L) + "\n")
    return out


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(HERE.parent / ".env")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stems", default="missing-candidates",
                    help="comma-separated stems, or 'missing-candidates' (default)")
    ap.add_argument("--ensemble", default=os.environ.get("SCORING_MODELS", "qwen,deepseek4,gemma4"))
    ap.add_argument("--name", default="", help="output folder under data/rescored/")
    ap.add_argument("--judge-provider", default=os.environ.get("JUDGE_PROVIDER", "foundry"))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--allow-missing", type=int, default=2,
                    help="papers that may stay unscored before the run counts as failed")
    ap.add_argument("--compare-only", action="store_true")
    args = ap.parse_args()

    trio = [t for t in args.ensemble.split(",") if t]
    unknown = [t for t in trio if t not in provenance.MODEL_IDS]
    if unknown:
        sys.exit(f"unknown model tag(s): {unknown}")
    missing = missing_candidate_stems()
    stems = sorted(missing) if args.stems == "missing-candidates" else \
        [s for s in args.stems.split(",") if s]
    out_dir = DATA_DIR / "rescored" / (args.name or "-".join(trio))
    new_dir = out_dir / "consensus"
    new_dir.mkdir(parents=True, exist_ok=True)
    log(f"{len(stems)} papers, ensemble {trio} -> {out_dir.relative_to(DATA_DIR.parent)}")

    problems: list[str] = []
    if not args.compare_only:
        ready = stage(stems)
        if len(ready) < len(stems):
            problems.append(f"no text for {len(stems) - len(ready)} paper(s)")
        todo = trio
        for _ in range(2):  # second pass retries models that worked but missed papers
            run_script("triple_score.py", "--pdf-dir", str(PDFS), "--output-root",
                       str(CANDIDATES), "--models", ",".join(todo),
                       "--workers", str(args.workers), "--limit", "10000")
            summary = CANDIDATES / "triple_score_summary.json"
            ran = json.loads(summary.read_text()) if summary.exists() else []
            cov = coverage(ready, trio)
            todo = [t for t in todo if len(cov[t]) < len(ready)
                    and worth_retrying(ran, t)]
            if not todo:
                break
        cov = coverage(ready, trio)
        for t, v in cov.items():
            log(f"{t}: scored {len(v)}/{len(ready)}")
        for stem in [s for s in ready if all(s in cov[t] for t in trio)]:
            path = new_dir / f"{stem}.json"
            if path.exists() and not _judged_from(path, trio):
                path.unlink()  # judged from other candidates: judge again
            run_script("judge_consensus.py", "--pdf-dir", str(PDFS),
                       "--candidates-root", str(CANDIDATES), "--output-dir", str(new_dir),
                       "--judge-provider", args.judge_provider, "--models", ",".join(trio),
                       "--stem", stem, "--resume")

    judged = [s for s in stems if (new_dir / f"{s}.json").exists()
              and _judged_from(new_dir / f"{s}.json", trio)]
    if len(judged) < len(stems) - args.allow_missing:
        problems.append(f"{len(judged)} of {len(stems)} papers rescored")
    provenance.build(new_dir, out_dir / "scoring_provenance.csv")
    out = report(out_dir, stems, missing, trio, judged, compare(judged, new_dir), problems)
    log(f"report: {out}")
    print(out.read_text())
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"report={out.relative_to(HERE.parent)}\nout_dir="
                    f"{out_dir.relative_to(HERE.parent)}\njudged={len(judged)}\n")
    if problems:
        for p in problems:
            print(f"::error::Rescore incomplete: {p}")
        sys.exit(1)


def _judged_from(path: Path, trio: list[str]) -> bool:
    used = json.loads(path.read_text()).get("judge_input_models") or []
    return sorted(used) == sorted(trio)


if __name__ == "__main__":
    main()

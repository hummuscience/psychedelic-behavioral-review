"""Bridge test: does the current scoring setup reproduce the published pipeline?

The published v2 data were scored by qwen3.5-397b-a17b + glm-4.7 +
openai-gpt-oss-120b, judged by Claude Opus 4.7. Two of those candidates and the
judge are no longer available. This re-scores the 20 papers that two human
raters also scored (figures/rater_lib.PAPER_STEMS) with the candidate models
and the current judge, and compares, per assay, with the published consensus
and with both human raters, using the same statistics as the paper's
human-vs-LLM validation (figures/plot_three_way.py: exact agreement, mean
difference, Spearman, ICC(2,1) on B/E/D assay totals).

Steps:
  1. Inputs, per paper, in order of preference:
       WORK_DIR/bridge/inputs/<stem>.docling.md   the published pipeline's own
         text (plus <stem>_supp.docling.md), so only the models change;
       WORK_DIR/bridge/inputs/<stem>.pdf          a PDF you supply;
       an open-access PDF (converted with Docling).
     The workflow pulls inputs/ from the PDF store's calibration/ folder.
  2. Score with every candidate in --candidates.
  3. Pick the third model from --choose-from by agreement with human rater 2.
  4. Judge with qwen + glm53 + the pick (judge from JUDGE_PROVIDER /
     AZURE_FOUNDRY_MODEL, as in the monthly update).
  5. Write data/calibration/bridge_<date>.md and .json (derived numbers only).

    uv run python pipeline/bridge_test.py
    uv run python pipeline/bridge_test.py --compare-only   # steps 3 and 5 only
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "figures"))

import numpy as np  # noqa: E402

import rater_lib as rl  # noqa: E402
import plot_three_way as tw  # noqa: E402
from paths import CONSENSUS_DIR, DATA_DIR, REGISTRY_JSON, WORK_DIR  # noqa: E402

BRIDGE = WORK_DIR / "bridge"
INPUTS = BRIDGE / "inputs"
PDFS = BRIDGE / "pdfs"
SUPP = BRIDGE / "pdfs_supplementary"
CANDIDATES = BRIDGE / "candidates"
NEW_CONSENSUS = BRIDGE / "consensus"
OUT_DIR = DATA_DIR / "calibration"
BASE_TRIO = ["qwen", "glm53"]


def log(msg: str) -> None:
    print(f"[bridge] {msg}", flush=True)


def run_script(script: str, *args: str) -> int:
    return subprocess.run([sys.executable, "-u", str(HERE / script), *args], cwd=HERE).returncode


# ── 1. Inputs ────────────────────────────────────────────────────────────────

def stage(stems: list[str]) -> dict:
    """Put each paper's text (or PDF) in place. Returns {stem: source}."""
    import fetch_pdfs
    PDFS.mkdir(parents=True, exist_ok=True)
    SUPP.mkdir(parents=True, exist_ok=True)
    registry = json.loads(REGISTRY_JSON.read_text())
    sources = {}
    for stem in stems:
        md, pdf = INPUTS / f"{stem}.docling.md", INPUTS / f"{stem}.pdf"
        if md.exists() and md.stat().st_size > 0:
            shutil.copy2(md, PDFS / md.name)
            # The scoring scripts select papers by PDF and use the cached
            # markdown, so a placeholder PDF is enough.
            (PDFS / f"{stem}.pdf").touch()
            supp = INPUTS / f"{stem}_supp.docling.md"
            if supp.exists():
                shutil.copy2(supp, SUPP / supp.name)
                (SUPP / f"{stem}_supp.pdf").touch()
            sources[stem] = "published text"
        elif pdf.exists() and pdf.stat().st_size > 0:
            shutil.copy2(pdf, PDFS / pdf.name)
            sources[stem] = "supplied PDF"
        elif (PDFS / f"{stem}.pdf").exists() and (PDFS / f"{stem}.pdf").stat().st_size > 0:
            sources[stem] = "open access"
        else:
            doi = (registry.get(stem) or {}).get("doi") or ""
            data, src, _ = fetch_pdfs.find_open_access("", doi) if doi else (None, "", [])
            if data:
                (PDFS / f"{stem}.pdf").write_bytes(data)
                sources[stem] = "open access"
            else:
                sources[stem] = "unavailable"
        log(f"{stem}: {sources[stem]}")
    return sources


# ── Comparison ───────────────────────────────────────────────────────────────

def load_items(path: Path) -> list[dict] | None:
    """[{assay_name, B{}, E{}, D{}}] from a consensus or candidate JSON."""
    if not path.exists():
        return None
    d = json.loads(path.read_text())
    return [{"assay_name": a.get("assay_name"), "B": rl._section_items(a, "B"),
             "E": rl._section_items(a, "E"), "D": rl._section_items(a, "D")}
            for a in d.get("assays", [])]


def build_pairs(stems: list[str], sources: dict[str, Path]) -> list[dict]:
    """One record per rater-2 assay, aligned to rater 1 and every LLM source.

    `sources` maps a slot name to a directory of <stem>.json files.
    """
    raters = rl.load_raters()
    pairs = []
    for stem in stems:
        human = (raters.get(stem) or {}).get("rater2") or []
        if not human:
            continue
        h_names = [{"name": a["assay_name"]} for a in human]
        aligned = {}
        for slot, directory in {**sources, "ana": None}.items():
            items = (raters[stem].get("rater1") or [] if slot == "ana"
                     else load_items(directory / f"{stem}.json"))
            if items is None:
                aligned[slot] = None
                continue
            aligned[slot] = (items, dict(rl.pair_assays(
                h_names, [{"assay_name": a["assay_name"]} for a in items])))
        for i, ha in enumerate(human):
            rec = {"stem": stem, "assay_name": ha["assay_name"],
                   "human": {k: ha[k] for k in ("B", "E", "D")}}
            for slot, al in aligned.items():
                if al is None or i not in al[1]:
                    rec[slot] = None
                else:
                    rec[slot] = {k: al[0][al[1][i]][k] for k in ("B", "E", "D")}
            pairs.append(rec)
    return pairs


def summarise(stats: dict) -> dict:
    """Mean ICC and exact agreement over B/E/D (None-safe)."""
    vals = [s for s in stats.values() if s]
    if not vals:
        return {"icc": None, "pct": None, "n": 0}
    icc = [s["icc"] for s in vals if s["icc"] is not None and not np.isnan(s["icc"])]
    return {"icc": float(np.mean(icc)) if icc else None,
            "pct": float(np.mean([s["pct"] for s in vals])),
            "n": min(s["n"] for s in vals)}


def choose_third(pairs: list[dict], choose_from: list[str]) -> tuple[str, dict]:
    """Pick the candidate that agrees best with human rater 2 (mean ICC, then exact %)."""
    scores = {t: summarise(tw.pair_stats(pairs, "human", t)) for t in choose_from}
    ranked = sorted(choose_from, key=lambda t: ((scores[t]["icc"] or -9), scores[t]["pct"] or 0,
                                                scores[t]["n"]), reverse=True)
    return ranked[0], scores


def study_level(stems: list[str]) -> dict:
    """Published vs new study-level maxima (B/E/D)."""
    out = {}
    for key in ("behavioural_complexity_max", "environmental_complexity_max",
                "recording_duration_max"):
        a, b = [], []
        for stem in stems:
            p, n = CONSENSUS_DIR / f"{stem}.json", NEW_CONSENSUS / f"{stem}.json"
            if p.exists() and n.exists():
                a.append(json.loads(p.read_text())["study_level_scores"][key])
                b.append(json.loads(n.read_text())["study_level_scores"][key])
        if a:
            out[key] = {"n": len(a), "mean_abs_diff": float(np.mean(np.abs(np.array(a) - np.array(b)))),
                        "spearman": tw._plot.spearman(a, b) if len(a) > 2 else None}
    return out


def _fmt(x, nd=2):
    return "–" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


def report(stems: list[str], sources: dict, tags: list[str], third: str,
           choice_scores: dict, judge_model: str, effort: str) -> Path:
    judged = [s for s in stems if (NEW_CONSENSUS / f"{s}.json").exists()]
    slots = {"published": CONSENSUS_DIR, "new": NEW_CONSENSUS,
             **{t: CANDIDATES / t for t in tags}}
    pairs = build_pairs(judged, slots)
    comparisons = [
        ("rater 2 vs published LLM", "human", "published"),
        ("rater 2 vs new LLM", "human", "new"),
        ("rater 1 vs published LLM", "ana", "published"),
        ("rater 1 vs new LLM", "ana", "new"),
        ("published LLM vs new LLM", "published", "new"),
        ("rater 1 vs rater 2", "ana", "human"),
    ] + [(f"rater 2 vs candidate {t}", "human", t) for t in tags]
    results = {label: tw.pair_stats(pairs, a, b) for label, a, b in comparisons}
    today = date.today().isoformat()
    payload = {
        "date": today, "judge_model": judge_model, "judge_effort": effort,
        "candidates": tags, "ensemble": BASE_TRIO + [third], "third_model_choice": choice_scores,
        "papers": {s: {"input": sources.get(s), "judged": s in judged} for s in stems},
        "n_rater2_assays": len(pairs), "assay_agreement": results,
        "study_level_published_vs_new": study_level(judged),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"bridge_{today}.json").write_text(json.dumps(payload, indent=2, default=float))

    L = [f"# Bridge test {today}", "",
         f"Re-scored {len(judged)} of the {len(stems)} human-rated papers with "
         f"`{', '.join(BASE_TRIO + [third])}` judged by `{judge_model}` (effort `{effort}`), "
         "and compared per assay with the published consensus (qwen3.5-397b-a17b, glm-4.7, "
         "openai-gpt-oss-120b; judge claude-opus-4-7) and the two human raters. Statistics as in "
         "`figures/plot_three_way.py`: B/E/D assay totals, exact agreement, mean difference "
         "(first minus second), Spearman ρ, ICC(2,1).", "",
         "## Assay-level agreement", "",
         "| comparison | dim | n | exact | mean diff | ρ | ICC |", "|---|---|---|---|---|---|---|"]
    for label, _, _ in comparisons:
        for dim in ("B", "E", "D"):
            r = results[label].get(dim)
            if r:
                L.append(f"| {label} | {dim} | {r['n']} | {r['pct']:.0f}% | "
                         f"{r['mean_diff']:+.2f} | {_fmt(r['spearman'])} | {_fmt(r['icc'])} |")
    L += ["", "## Choice of the third candidate", "",
          "Agreement with human rater 2, averaged over B/E/D:", "",
          "| model | mean ICC | mean exact | n |", "|---|---|---|---|"]
    for t, s in choice_scores.items():
        L.append(f"| `{t}`{' (chosen)' if t == third else ''} | {_fmt(s['icc'])} | "
                 f"{_fmt(s['pct'], 0)}% | {s['n']} |")
    sl = study_level(judged)
    if sl:
        L += ["", "## Study-level maxima, published vs new", "",
              "| score | n | mean |difference| | ρ |", "|---|---|---|---|"]
        for k, v in sl.items():
            L.append(f"| {k} | {v['n']} | {v['mean_abs_diff']:.2f} | {_fmt(v['spearman'])} |")
    L += ["", "## Papers", "", "| paper | input | judged |", "|---|---|---|"]
    for s in stems:
        L.append(f"| `{s}` | {sources.get(s, '–')} | {'yes' if s in judged else 'no'} |")
    out = OUT_DIR / f"bridge_{today}.md"
    out.write_text("\n".join(L) + "\n")
    return out


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(HERE.parent / ".env")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidates", default="qwen,glm53,deepseek4,gemma4")
    ap.add_argument("--choose-from", default="deepseek4,gemma4")
    ap.add_argument("--judge-provider", default=os.environ.get("JUDGE_PROVIDER", "foundry"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--compare-only", action="store_true",
                    help="skip scoring; compare what is already in WORK_DIR/bridge")
    args = ap.parse_args()
    stems = list(rl.PAPER_STEMS)
    tags = [t for t in args.candidates.split(",") if t]
    choose_from = [t for t in args.choose_from.split(",") if t]
    sources_file = BRIDGE / "sources.json"

    if args.compare_only:
        sources = json.loads(sources_file.read_text()) if sources_file.exists() else {}
    else:
        sources = stage(stems)
        sources_file.write_text(json.dumps(sources, indent=2))
        if any(v in ("supplied PDF", "open access") for v in sources.values()):
            run_script("bulk_docling.py", "--pdf-dir", str(PDFS))
        run_script("triple_score.py", "--pdf-dir", str(PDFS), "--output-root", str(CANDIDATES),
                   "--models", ",".join(tags), "--workers", str(args.workers), "--limit", "1000")

    scored = [s for s in stems if any((CANDIDATES / t / f"{s}.json").exists() for t in tags)]
    pairs = build_pairs(scored, {t: CANDIDATES / t for t in choose_from})
    third, choice_scores = choose_third(pairs, choose_from)
    log(f"third candidate: {third} ({choice_scores})")

    if not args.compare_only:
        trio = ",".join(BASE_TRIO + [third])
        for stem in scored:
            run_script("judge_consensus.py", "--pdf-dir", str(PDFS),
                       "--candidates-root", str(CANDIDATES), "--output-dir", str(NEW_CONSENSUS),
                       "--judge-provider", args.judge_provider, "--models", trio,
                       "--stem", stem, "--resume")

    judge_model = os.environ.get("AZURE_FOUNDRY_MODEL", "") if args.judge_provider == "foundry" \
        else args.judge_provider
    out = report(stems, sources, tags, third, choice_scores, judge_model,
                 os.environ.get("JUDGE_EFFORT", "high"))
    log(f"report: {out}")
    print(out.read_text())
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"report={out.relative_to(HERE.parent)}\nthird={third}\n")


if __name__ == "__main__":
    main()

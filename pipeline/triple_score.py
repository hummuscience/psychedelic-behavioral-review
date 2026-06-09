"""Triple-scoring driver: score the same papers with 3 SAIA models.

For each paper × model, write to results_full_compare/<model_tag>/<stem>.json.
Skips papers already scored for a given model (resume-friendly).

Usage:
    SAIA_API_KEY=... uv run python triple_score.py \\
        --pdf-dir ./pdfs --output-root ./results_full_compare --limit 10
"""

import argparse
import json
import os
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

from provider import SaiaProvider, ProviderError
from score_studies import (
    SCORING_PROMPT,
    normalize_keys,
    filter_non_behavioural_assays,
    recompute_raw_totals,
    compute_study_scores,
    ITEM_KEYS,
    HOUSING_KEYS,
    EXPERIMENTAL_CONDITION_KEYS,
)

_print_lock = threading.Lock()

def safe_print(*a, **kw):
    with _print_lock:
        print(*a, flush=True, **kw)

# (tag, full model id)
# v2 ensemble: three SAIA reasoning models that survived the schema test —
#   - qwen3.5-397b-a17b (huge MoE, gold standard but slow)
#   - glm-4.7           (different lineage, fast)
#   - openai-gpt-oss-120b (different lineage, fast)
# We dropped:
#   - deepseek-r1-distill-llama-70b (returns tool-call JSON, not the schema)
#   - mistral-large-3-675b-instruct-2512 (not a reasoning model; times out at 480s)
#   - llama-3.3-70b-instruct (instruct-only, not reasoning)
#   - qwen3.5-122b-a10b (reasoning but redundant with qwen3.5-397b)
MODELS = [
    ("qwen",   "qwen3.5-397b-a17b"),
    ("glm",    "glm-4.7"),
    ("gptoss", "openai-gpt-oss-120b"),
]


def score_one(provider: SaiaProvider, pdf_path: Path) -> dict:
    """Single run; mirrors score_studies.process_study but no consensus loop."""
    raw = provider.score_pdf(pdf_path, SCORING_PROMPT)
    result = normalize_keys(raw)
    filter_non_behavioural_assays(result)
    result["num_runs"] = 1
    result["disagreements"] = []
    recompute_raw_totals(result)
    result["study_level_scores"] = compute_study_scores(result)
    low_conf = 0
    for assay in result.get("assays", []):
        for dim in ITEM_KEYS:
            for key in ITEM_KEYS[dim]:
                if assay.get(dim, {}).get(key, {}).get("confidence") == "low":
                    low_conf += 1
        for key in EXPERIMENTAL_CONDITION_KEYS:
            if assay.get("experimental_conditions", {}).get(key, {}).get("confidence") == "low":
                low_conf += 1
    for key in HOUSING_KEYS:
        if result.get("housing_conditions", {}).get(key, {}).get("confidence") == "low":
            low_conf += 1
    result["low_confidence_count"] = low_conf
    return result


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", type=Path, required=True)
    ap.add_argument("--output-root", type=Path, default=Path("./results_full_compare"))
    ap.add_argument("--limit", type=int, default=10,
                    help="Score only the first N PDFs (alphabetical) that have cached markdown")
    ap.add_argument("--models", type=str, default=None,
                    help="Comma-separated subset of model tags to run (default: all)")
    ap.add_argument("--workers", type=int, default=1,
                    help="Total concurrent (model, paper) tasks (default: 1 = sequential). "
                         "Recommended: 6-12 (e.g. 3 models x 4 papers = 12).")
    args = ap.parse_args()

    if not os.environ.get("SAIA_API_KEY"):
        sys.exit("SAIA_API_KEY not set")

    selected = (
        [m for m in MODELS if m[0] in set(args.models.split(","))]
        if args.models else MODELS
    )

    # Pick papers that have docling cache
    cached_pdfs: list[Path] = []
    for pdf in sorted(args.pdf_dir.glob("*.pdf")):
        md = pdf.with_suffix(".docling.md")
        if md.exists() and md.stat().st_size > 0:
            cached_pdfs.append(pdf)
        if len(cached_pdfs) >= args.limit:
            break
    print(f"Selected {len(cached_pdfs)} cached papers:")
    for p in cached_pdfs:
        print(f"  {p.name}")

    # Build providers once per model and a flat task list of (tag, pdf, json_path)
    providers: dict[str, SaiaProvider] = {}
    for tag, model_id in selected:
        out_dir = args.output_root / tag
        out_dir.mkdir(parents=True, exist_ok=True)
        providers[tag] = SaiaProvider(model=model_id)

    tasks: list[tuple[str, str, Path, Path]] = []
    skipped = 0
    for tag, model_id in selected:
        out_dir = args.output_root / tag
        for pdf in cached_pdfs:
            json_path = out_dir / f"{pdf.stem}.json"
            if json_path.exists():
                skipped += 1
                continue
            tasks.append((tag, model_id, pdf, json_path))

    safe_print(f"\nQueued {len(tasks)} tasks  ({skipped} cached skipped)  workers={args.workers}")

    summary_lock = threading.Lock()
    summary: list[dict] = []

    def run_task(tag: str, model_id: str, pdf: Path, json_path: Path):
        provider = providers[tag]
        t0 = time.time()
        try:
            result = score_one(provider, pdf)
            json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
            dt = time.time() - t0
            sc = result["study_level_scores"]
            n_assay = len(result.get("assays", []))
            safe_print(
                f"  [{dt:5.1f}s] {tag}/{pdf.name}  "
                f"B={sc['behavioural_complexity_max']:.1f} "
                f"E={sc['environmental_complexity_max']:.1f} "
                f"D={sc['recording_duration_max']:.1f}  "
                f"({n_assay} assays, {result['low_confidence_count']} low-conf)"
            )
            entry = {
                "model": tag, "study": pdf.stem, "ok": True,
                "n_assays": n_assay,
                "B": sc["behavioural_complexity_max"],
                "E": sc["environmental_complexity_max"],
                "D": sc["recording_duration_max"],
                "low_conf": result["low_confidence_count"],
                "secs": round(dt, 1),
            }
        except ProviderError as e:
            dt = time.time() - t0
            safe_print(f"  [{dt:5.1f}s] {tag}/{pdf.name}  PROVIDER ERROR: {e}")
            entry = {"model": tag, "study": pdf.stem, "ok": False,
                     "error": str(e), "secs": round(dt, 1)}
        except Exception as e:
            dt = time.time() - t0
            safe_print(f"  [{dt:5.1f}s] {tag}/{pdf.name}  ERROR: {e}")
            traceback.print_exc()
            entry = {"model": tag, "study": pdf.stem, "ok": False,
                     "error": str(e), "secs": round(dt, 1)}
        with summary_lock:
            summary.append(entry)

    if tasks:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            futures = [ex.submit(run_task, *t) for t in tasks]
            for _ in as_completed(futures):
                pass

    # Write summary
    summary_path = args.output_root / "triple_score_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"\nSummary → {summary_path}")
    n_ok = sum(1 for s in summary if s.get("ok"))
    n_fail = sum(1 for s in summary if not s.get("ok"))
    print(f"  {n_ok} OK  /  {n_fail} failed across {len(selected)} models × {len(cached_pdfs)} papers")


if __name__ == "__main__":
    main()

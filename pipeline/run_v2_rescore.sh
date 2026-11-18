#!/usr/bin/env bash
# Full v2 rescore pipeline (re-scores every PDF; for the monthly incremental
# update use monthly_update.py instead).
#
# Paths follow pipeline/paths.py: PDFs and candidate scores live in $WORK_DIR
# (default: work/ at the repo root), consensus output goes to data/.
#
#  1. triple_score over all PDFs → $WORK_DIR/results_v2_full_compare/<model>/<stem>.json
#     (skips papers already scored — resumable)
#  2. judge_consensus via Foundry/Opus-4.7 → data/results_v2_full_consensus/<stem>.json
#  3. build_assay_catalog --rebuild (so paper_assays.json reflects v2 assays)
#
# Logs land in logs/. Each stage is gated on the prior stage's exit code so a
# failure stops the pipeline rather than feeding stale data forward.
#
# Run via:
#   nohup bash pipeline/run_v2_rescore.sh > v2_pipeline.log 2>&1 &
# and tail v2_pipeline.log for progress.

set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
WORK_DIR="${WORK_DIR:-$ROOT/../work}"
DATA_DIR="${DATA_DIR:-$ROOT/../data}"
mkdir -p "$WORK_DIR/logs"

STAMP=$(date +%Y%m%d_%H%M%S)
TRIPLE_LOG="$WORK_DIR/logs/v2_triple_${STAMP}.log"
JUDGE_LOG="$WORK_DIR/logs/v2_judge_${STAMP}.log"

echo "================================================================"
echo " v2 rescore pipeline starting at $(date)"
echo "  triple_score log: $TRIPLE_LOG"
echo "  judge log:        $JUDGE_LOG"
echo "================================================================"

echo "[$(date)] STAGE 1: triple_score → results_v2_full_compare/"
# triple_score's --limit default is 10. Bump to 10000 to take all available
# cached PDFs. workers=8 because the candidate set now contains only 3 fast
# models, so concurrency-per-model is unconstrained.
uv run python -u triple_score.py \
  --pdf-dir "$WORK_DIR/pdfs" \
  --output-root "$WORK_DIR/results_v2_full_compare" \
  --workers 8 \
  --limit 10000 \
  > "$TRIPLE_LOG" 2>&1
echo "[$(date)] triple_score exit=$?"

echo "[$(date)] STAGE 2: judge_consensus (foundry/opus-4.7) → data/results_v2_full_consensus/"
uv run python -u judge_consensus.py \
  --pdf-dir "$WORK_DIR/pdfs" \
  --candidates-root "$WORK_DIR/results_v2_full_compare" \
  --output-dir "$DATA_DIR/results_v2_full_consensus" \
  --judge-provider foundry \
  --models qwen,glm,gptoss \
  --resume \
  > "$JUDGE_LOG" 2>&1
echo "[$(date)] judge_consensus exit=$?"

echo "[$(date)] STAGE 3: refresh assay catalog from v2 consensus"
uv run python build_assay_catalog.py --rebuild

echo "================================================================"
echo " v2 rescore pipeline finished at $(date)"
echo "================================================================"

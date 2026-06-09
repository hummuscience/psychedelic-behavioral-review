#!/usr/bin/env bash
# Full v2 rescore pipeline.
#
#  1. triple_score over all PDFs → results_v2_full_compare/<model>/<stem>.json
#     (skips papers already scored — resumable)
#  2. judge_consensus via Foundry/Opus-4.7 → results_v2_full_consensus/<stem>.json
#  3. build_assay_catalog refresh (so paper_assays.json reflects v2 assays)
#
# Logs land in logs/. Each stage is gated on the prior stage's exit code so a
# failure stops the pipeline rather than feeding stale data forward.
#
# Run via:
#   nohup bash run_v2_rescore.sh > logs/v2_pipeline.log 2>&1 &
# and tail logs/v2_pipeline.log for progress.

set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

STAMP=$(date +%Y%m%d_%H%M%S)
TRIPLE_LOG="logs/v2_triple_${STAMP}.log"
JUDGE_LOG="logs/v2_judge_${STAMP}.log"

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
  --pdf-dir ./pdfs \
  --output-root ./results_v2_full_compare \
  --workers 8 \
  --limit 10000 \
  > "$TRIPLE_LOG" 2>&1
echo "[$(date)] triple_score exit=$?"

echo "[$(date)] STAGE 2: judge_consensus (foundry/opus-4.7) → results_v2_full_consensus/"
uv run python -u judge_consensus.py \
  --pdf-dir ./pdfs \
  --candidates-root ./results_v2_full_compare \
  --output-dir ./results_v2_full_consensus \
  --judge-provider foundry \
  --models qwen,glm,gptoss \
  --resume \
  > "$JUDGE_LOG" 2>&1
echo "[$(date)] judge_consensus exit=$?"

echo "[$(date)] STAGE 3: refresh assay catalog from v2 consensus"
CONSENSUS_DIR=./results_v2_full_consensus uv run python build_assay_catalog.py

echo "================================================================"
echo " v2 rescore pipeline finished at $(date)"
echo "================================================================"

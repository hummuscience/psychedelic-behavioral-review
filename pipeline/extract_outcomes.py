"""
Outcome extraction pipeline for systematic review of psychedelic animal studies.

For each study, extracts per-assay therapeutic outcome data using Gemini Flash.
Uses the existing scored JSON (assay names) as a guide so the LLM knows which
assays to extract outcomes for.

Usage:
    # Extract outcomes for all scored studies
    uv run python extract_outcomes.py --pdf-dir ./pdfs --scores-dir ./results --output-dir ./results_outcomes

    # Single study
    uv run python extract_outcomes.py --pdf ./pdfs/hesselgrave2021.pdf --scores-dir ./results --output-dir ./results_outcomes

    # Parallel (4 workers)
    uv run python extract_outcomes.py --pdf-dir ./pdfs --scores-dir ./results --output-dir ./results_outcomes --workers 4

    # Resume interrupted run
    uv run python extract_outcomes.py --pdf-dir ./pdfs --scores-dir ./results --output-dir ./results_outcomes --workers 4 --resume

Setup:
    export GEMINI_API_KEY="your-api-key-here"
"""

import argparse
import json
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL_NAME = "gemini-2.5-flash-lite"
NUM_RUNS = 3
TEMPERATURE = 0.0
THINKING_BUDGET = 0
MAX_RETRIES = 3
RETRY_DELAY = 10
NUM_WORKERS = 1

# Thread-safe printing
_print_lock = threading.Lock()

def safe_print(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)


class RateLimiter:
    """Token-bucket rate limiter safe for use across threads."""

    def __init__(self, calls_per_second: float = 0.25):
        self._min_interval = 1.0 / calls_per_second
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            wait_time = self._last_call + self._min_interval - now
            if wait_time > 0:
                time.sleep(wait_time)
            self._last_call = time.monotonic()


_rate_limiter: RateLimiter | None = None

# ---------------------------------------------------------------------------
# Outcome extraction prompt
# ---------------------------------------------------------------------------

OUTCOME_PROMPT = r"""
You are a scientific research assistant extracting therapeutic outcome data
from animal behavioural studies for a systematic review of psychedelic research.

Read the attached research paper carefully. Below is a list of behavioural
assays previously identified in this study. For EACH assay, extract the
therapeutic outcome.

ASSAYS IDENTIFIED IN THIS STUDY:
{assay_list}

For each assay, extract the following fields:

1. outcome_direction — classify the PRIMARY result:
   - "beneficial": The psychedelic produced a statistically significant
     therapeutic or pro-adaptive effect. In disease-model studies, this means
     reversal/amelioration of pathology. In naive animals, this means
     enhancement of a clinically relevant function (e.g., increased
     sociability, improved cognitive flexibility).
   - "null": No statistically significant effect of the psychedelic on the
     primary measure, OR a trend (0.05 < p < 0.10) without converging evidence.
   - "detrimental": The psychedelic significantly worsened behaviour (e.g.,
     increased anxiety, impaired cognition, neurotoxicity-related deficits).
   - "pharmacological_marker": The assay measures a pharmacological response
     (e.g., head-twitch response, ear-scratch response) rather than a
     therapeutic or behavioural outcome.
   - "control_measure": The assay was used as a control (e.g., locomotion
     to rule out sedation) rather than as a primary therapeutic endpoint.

2. statistical_significance — the p-value or significance level:
   - "p<0.001", "p<0.01", "p<0.05", "ns" (not significant), "not_tested"
   Use the most stringent level reported for the primary comparison.

3. disease_model — was pathology induced before psychedelic treatment?
   - "yes": chronic stress, fear conditioning, lesion, addiction model, etc.
   - "no": naive/healthy animals
   - "genetic": transgenic disease model (e.g., SAPAP3 KO, 5xFAD)

4. assay_purpose — what role does this assay play in the study?
   - "therapeutic_endpoint": Primary or secondary measure of therapeutic effect
   - "control_measure": Used to rule out confounds (e.g., locomotion for sedation)
   - "pharmacological_marker": Confirms drug activity (e.g., HTR)
   - "neurotoxicity_assessment": Assesses potential harm at high doses

5. dose_context — the dosing regimen used:
   - "therapeutic": Standard dose range used in the literature
   - "supratherapeutic": Doses explicitly described as high/toxic, or
     substantially above typical ranges (e.g., >10 mg/kg psilocybin,
     >30 mg/kg DOI in mice)
   - "microdose": Sub-hallucinogenic doses explicitly described as microdoses

6. brief_evidence — 1-2 sentence summary with key statistics. Include the
   specific test statistic and p-value. Quote or closely paraphrase the paper.

7. confidence — your confidence in the classification:
   - "high": Clear statistical reporting, unambiguous outcome
   - "medium": Some ambiguity (e.g., multiple sub-measures with mixed results,
     borderline significance, results only in figures)
   - "low": Substantial ambiguity (e.g., omnibus significant but post-hoc not,
     results not clearly reported)

DECISION RULES:

Rule 1: Use POST-HOC comparisons for drug-specific classification, not omnibus
ANOVA. If overall ANOVA is significant but the specific psychedelic vs. control
comparison is not, classify as "null".

Rule 2: Trends (0.05 < p < 0.10) default to "null". Note the trend in
brief_evidence but do not classify as beneficial.

Rule 3: Tag assay purpose. HTR/ear-scratch = pharmacological_marker. Locomotion
used as a sedation control = control_measure. Only therapeutic endpoints should
be classified as beneficial/null/detrimental.

Rule 4: Disease model status is critical. Enhancement in healthy animals is
qualitatively different from reversal of pathology. Code both as "beneficial"
but record the disease_model field accurately.

Rule 5: Code each DOSE REGIMEN separately when results differ. If a study tests
both microdose and full dose with different outcomes, create separate entries
for the same assay.

Rule 6: Tag neurotoxicity experiments. Studies using supratherapeutic doses
to assess toxicity should have assay_purpose = "neurotoxicity_assessment".

Rule 7: When multiple sub-measures exist within one assay, classify by the
PRIMARY or most clinically relevant measure. Note mixed results in brief_evidence.

Rule 8: If results are only in supplementary figures without extractable
statistics, classify based on what the main text says about them. Set
confidence to "medium" or "low".

============================================================
OUTPUT FORMAT
============================================================

Return ONLY valid JSON (no markdown fences, no commentary):

{
  "study_id": "<FirstAuthorYear>",
  "disease_model_global": "<yes|no|genetic>",
  "disease_model_type": "<description, e.g., 'chronic mild stress' or 'naive'>",
  "assay_outcomes": [
    {
      "assay_name": "<must match an assay from the list above>",
      "outcome_direction": "<beneficial|null|detrimental|pharmacological_marker|control_measure>",
      "statistical_significance": "<p<0.001|p<0.01|p<0.05|ns|not_tested>",
      "disease_model": "<yes|no|genetic>",
      "assay_purpose": "<therapeutic_endpoint|control_measure|pharmacological_marker|neurotoxicity_assessment>",
      "dose_context": "<therapeutic|supratherapeutic|microdose>",
      "brief_evidence": "<1-2 sentences with statistics>",
      "confidence": "<high|medium|low>"
    }
  ]
}

If a study tests multiple dose regimens with DIFFERENT outcomes for the same
assay, include multiple entries for that assay with the dose noted in
brief_evidence.
"""


# ---------------------------------------------------------------------------
# API interaction
# ---------------------------------------------------------------------------

def init_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY environment variable.")
    return genai.Client(api_key=api_key)


def extract_single_pdf(
    client: genai.Client, model_name: str, pdf_path: Path,
    assay_list: str, thinking_budget: int = THINKING_BUDGET,
) -> dict:
    """Upload a PDF and extract outcomes."""
    uploaded_file = client.files.upload(file=pdf_path)
    while uploaded_file.state.name == "PROCESSING":
        time.sleep(2)
        uploaded_file = client.files.get(name=uploaded_file.name)
    if uploaded_file.state.name == "FAILED":
        raise RuntimeError(f"File upload failed for {pdf_path}")

    prompt = OUTCOME_PROMPT.replace("{assay_list}", assay_list)

    config_kwargs = {
        "response_mime_type": "application/json",
        "temperature": TEMPERATURE,
        "max_output_tokens": 32768,
    }
    if thinking_budget >= 0:
        config_kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_budget=thinking_budget
        )

    response = client.models.generate_content(
        model=model_name,
        contents=[prompt, uploaded_file],
        config=types.GenerateContentConfig(**config_kwargs),
    )

    try:
        client.files.delete(name=uploaded_file.name)
    except Exception:
        pass

    return json.loads(response.text)


def extract_with_retries(
    client: genai.Client, model_name: str, pdf_path: Path,
    assay_list: str, run_id: int, thinking_budget: int = THINKING_BUDGET,
) -> dict | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if _rate_limiter:
                _rate_limiter.wait()
            result = extract_single_pdf(client, model_name, pdf_path, assay_list, thinking_budget)
            safe_print(f"  Run {run_id}: OK")
            return result
        except Exception as e:
            safe_print(f"  Run {run_id}, attempt {attempt}/{MAX_RETRIES}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
    safe_print(f"  Run {run_id}: FAILED after {MAX_RETRIES} attempts")
    return None


# ---------------------------------------------------------------------------
# Consensus
# ---------------------------------------------------------------------------

def majority_vote_outcome(outcomes_across_runs: list[str]) -> str:
    """Return the most common outcome across runs."""
    from collections import Counter
    counts = Counter(outcomes_across_runs)
    return counts.most_common(1)[0][0]


def build_outcome_consensus(runs: list[dict]) -> dict:
    """Build consensus across multiple extraction runs."""
    consensus = json.loads(json.dumps(runs[0]))
    consensus["num_runs"] = len(runs)
    consensus["disagreements"] = []

    # Match assays by name across runs
    base_assays = {a["assay_name"]: i for i, a in enumerate(consensus["assay_outcomes"])}

    for assay_name, idx in base_assays.items():
        directions = []
        significances = []
        for run in runs:
            for a in run.get("assay_outcomes", []):
                if a["assay_name"] == assay_name:
                    directions.append(a.get("outcome_direction", "null"))
                    significances.append(a.get("statistical_significance", "ns"))
                    break

        if len(set(directions)) > 1:
            consensus["disagreements"].append({
                "assay": assay_name,
                "field": "outcome_direction",
                "values": directions,
                "voted": majority_vote_outcome(directions),
            })

        consensus["assay_outcomes"][idx]["outcome_direction"] = majority_vote_outcome(directions)
        if significances:
            consensus["assay_outcomes"][idx]["statistical_significance"] = majority_vote_outcome(significances)

    return consensus


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def get_assay_list_from_scores(scores_dir: Path, study_stem: str) -> str | None:
    """Load assay names from existing scoring JSON."""
    json_path = scores_dir / f"{study_stem}.json"
    if not json_path.exists():
        return None
    data = json.loads(json_path.read_text())
    assays = data.get("assays", [])
    if not assays:
        return None
    lines = []
    for i, a in enumerate(assays, 1):
        name = a.get("assay_name", f"Assay {i}")
        desc = a.get("assay_description", "")
        lines.append(f"{i}. {name}: {desc}")
    return "\n".join(lines)


def process_study(
    client: genai.Client, model_name: str, pdf_path: Path,
    scores_dir: Path, output_dir: Path,
    num_runs: int = NUM_RUNS, thinking_budget: int = THINKING_BUDGET,
) -> dict | None:
    """Extract outcomes for a single study."""
    stem = pdf_path.stem
    json_path = output_dir / f"{stem}.json"

    # Get assay list from existing scores
    assay_list = get_assay_list_from_scores(scores_dir, stem)
    if assay_list is None:
        safe_print(f"\nSkipping {pdf_path.name}: no scoring JSON found in {scores_dir}")
        return None

    safe_print(f"\nExtracting outcomes: {pdf_path.name}")

    runs = []
    for run_id in range(1, num_runs + 1):
        result = extract_with_retries(
            client, model_name, pdf_path, assay_list, run_id, thinking_budget
        )
        if result:
            runs.append(result)

    if not runs:
        safe_print(f"  SKIPPED — all runs failed")
        return None

    if len(runs) == 1:
        consensus = runs[0]
        consensus["num_runs"] = 1
        consensus["disagreements"] = []
    else:
        consensus = build_outcome_consensus(runs)

    # Count confidence levels
    n_high = sum(1 for a in consensus.get("assay_outcomes", []) if a.get("confidence") == "high")
    n_med = sum(1 for a in consensus.get("assay_outcomes", []) if a.get("confidence") == "medium")
    n_low = sum(1 for a in consensus.get("assay_outcomes", []) if a.get("confidence") == "low")
    consensus["confidence_summary"] = {"high": n_high, "medium": n_med, "low": n_low}

    json_path.write_text(json.dumps(consensus, indent=2))

    # Summary
    outcomes = [a.get("outcome_direction", "?") for a in consensus.get("assay_outcomes", [])]
    n_disag = len(consensus.get("disagreements", []))
    safe_print(
        f"  {len(outcomes)} assays: "
        f"{outcomes.count('beneficial')}B {outcomes.count('null')}N "
        f"{outcomes.count('detrimental')}D {outcomes.count('pharmacological_marker')}PM "
        f"{outcomes.count('control_measure')}CM "
        f"| {n_disag} disagreements | conf: {n_high}H {n_med}M {n_low}L"
    )
    return consensus


def aggregate_outcomes(output_dir: Path):
    """Aggregate all outcome JSONs into a summary CSV."""
    import csv

    rows = []
    for jf in sorted(output_dir.glob("*.json")):
        data = json.loads(jf.read_text())
        study_id = data.get("study_id", jf.stem)
        disease_model = data.get("disease_model_global", "")

        for a in data.get("assay_outcomes", []):
            rows.append({
                "study_id": study_id,
                "disease_model_global": disease_model,
                "disease_model_type": data.get("disease_model_type", ""),
                "assay_name": a.get("assay_name", ""),
                "outcome_direction": a.get("outcome_direction", ""),
                "statistical_significance": a.get("statistical_significance", ""),
                "disease_model": a.get("disease_model", ""),
                "assay_purpose": a.get("assay_purpose", ""),
                "dose_context": a.get("dose_context", ""),
                "confidence": a.get("confidence", ""),
                "brief_evidence": a.get("brief_evidence", ""),
            })

    csv_path = output_dir / "outcomes_all.csv"
    if rows:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    # Summary stats
    n_studies = len(set(r["study_id"] for r in rows))
    n_assays = len(rows)
    directions = [r["outcome_direction"] for r in rows]
    purposes = [r["assay_purpose"] for r in rows]

    # Therapeutic endpoints only
    therapeutic = [r for r in rows if r["assay_purpose"] == "therapeutic_endpoint"]
    t_directions = [r["outcome_direction"] for r in therapeutic]

    print(f"\nOutcome summary CSV → {csv_path}")
    print(f"  {n_studies} studies, {n_assays} assay-outcomes total")
    print(f"  All assays: {directions.count('beneficial')}B "
          f"{directions.count('null')}N {directions.count('detrimental')}D "
          f"{directions.count('pharmacological_marker')}PM "
          f"{directions.count('control_measure')}CM")
    print(f"  Therapeutic endpoints only ({len(therapeutic)}): "
          f"{t_directions.count('beneficial')}B "
          f"{t_directions.count('null')}N {t_directions.count('detrimental')}D")

    # By disease model
    for dm in ["yes", "no", "genetic"]:
        dm_rows = [r for r in therapeutic if r["disease_model"] == dm]
        if dm_rows:
            dd = [r["outcome_direction"] for r in dm_rows]
            print(f"    disease_model={dm}: {dd.count('beneficial')}B "
                  f"{dd.count('null')}N {dd.count('detrimental')}D")


def main():
    parser = argparse.ArgumentParser(
        description="Extract therapeutic outcomes from psychedelic animal studies"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pdf-dir", type=Path, help="Directory of study PDFs")
    group.add_argument("--pdf", type=Path, help="Single PDF to extract")
    parser.add_argument("--scores-dir", type=Path, required=True,
                        help="Directory with scored JSON files (from score_studies.py)")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Output directory for outcome JSONs")
    parser.add_argument("--resume", action="store_true",
                        help="Skip studies that already have output")
    parser.add_argument("--runs", type=int, default=NUM_RUNS)
    parser.add_argument("--model", type=str, default=MODEL_NAME)
    parser.add_argument("--thinking-budget", type=int, default=THINKING_BUDGET)
    parser.add_argument("--workers", type=int, default=NUM_WORKERS,
                        help="Parallel workers (default: 1). Recommended: 4-8.")
    args = parser.parse_args()

    global _rate_limiter
    if args.workers > 1:
        _rate_limiter = RateLimiter(calls_per_second=0.25)
    else:
        _rate_limiter = RateLimiter(calls_per_second=0.25)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    client = init_client()

    # Collect PDFs
    if args.pdf:
        pdfs = [args.pdf]
    else:
        pdfs = sorted(args.pdf_dir.glob("*.pdf"))
        print(f"Found {len(pdfs)} PDFs in {args.pdf_dir}")

    # Filter: only process PDFs that have a corresponding scores JSON
    pdfs = [p for p in pdfs if (args.scores_dir / f"{p.stem}.json").exists()]
    print(f"{len(pdfs)} have matching score files in {args.scores_dir}")

    # Resume filter
    if args.resume:
        before = len(pdfs)
        pdfs = [p for p in pdfs if not (args.output_dir / f"{p.stem}.json").exists()]
        print(f"Resuming: {before - len(pdfs)} already done, {len(pdfs)} remaining")

    if not pdfs:
        print("No PDFs to process.")
        return

    print(f"Extracting outcomes from {len(pdfs)} studies with {args.workers} worker(s)...")

    if args.workers > 1:
        completed = 0
        failed = 0
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    process_study, client, args.model, pdf_path,
                    args.scores_dir, args.output_dir,
                    args.runs, args.thinking_budget,
                ): pdf_path
                for pdf_path in pdfs
            }
            for future in as_completed(futures):
                pdf_path = futures[future]
                try:
                    result = future.result()
                    if result:
                        completed += 1
                    else:
                        failed += 1
                except Exception as e:
                    safe_print(f"  ERROR processing {pdf_path.name}: {e}")
                    failed += 1
        print(f"\nDone: {completed} extracted, {failed} failed")
    else:
        for pdf_path in pdfs:
            process_study(
                client, args.model, pdf_path,
                args.scores_dir, args.output_dir,
                args.runs, args.thinking_budget,
            )

    # Aggregate
    aggregate_outcomes(args.output_dir)


if __name__ == "__main__":
    main()

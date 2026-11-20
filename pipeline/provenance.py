"""Which models scored each paper, and how.

Every score carries a `scoring` block:
  candidate JSON  {"tag", "model", "provider", "scored_at", "rubric", "code"}
  consensus JSON  {"scored_at", "ensemble": {tag: model}, "candidates": {tag: model},
                   "missing": [tag], "judge", "judged_by", "judge_provider",
                   "judge_effort", "declined_by", "rubric", "judge_rubric", "code",
                   "setup_id", "setup"}
`ensemble` is what was asked for, `candidates` what the judge actually had (a model
can fail on a paper), `judged_by` the model that wrote the verdict (the fallback
when `judge` declined). The rubric fields are short hashes of the prompts, `code`
the git commit.

data/scoring_provenance.csv has one row per scored paper, built from these blocks.
The published v2 scores predate them; their row is filled in from the fields they
do have (judge model, candidate tags) and marked `v2 (published)`.

    uv run python pipeline/provenance.py      # rebuild the CSV
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Candidate model tags -> SAIA model IDs. Tags are never reused for another model.
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
    # 2026-11: glm-4.7 and gpt-oss-120b are no longer served on SAIA. Candidate
    # replacements for the monthly update (choose with --models / SCORING_MODELS):
    ("glm53",     "glm-5.3-flash"),           # successor in the GLM family
    ("deepseek4", "deepseek-v4-flash-0731"),  # different family
    ("gemma4",    "gemma-4-31b-it"),          # different family
]
MODEL_IDS = dict(MODELS)
# The published v2 ensemble; used when --models isn't given.
PUBLISHED_TAGS = ("qwen", "glm", "gptoss")
PUBLISHED_SETUP = "v2 (published)"

CSV_COLUMNS = ["stem", "setup_id", "setup", "scored_at", "ensemble", "candidates",
               "missing_candidates", "judge", "judged_by", "judge_effort", "declined_by",
               "rubric", "judge_rubric", "code"]


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:10]


def rubric_version() -> str:
    from score_studies import SCORING_PROMPT
    return _short_hash(SCORING_PROMPT)


def judge_rubric_version(instructions: str | None = None) -> str:
    if instructions is None:
        from judge_consensus import JUDGE_INSTRUCTIONS as instructions
    return _short_hash(instructions)


def code_version() -> str:
    sha = os.environ.get("GITHUB_SHA", "")
    if not sha:
        try:
            sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=HERE, text=True,
                                 capture_output=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            sha = ""
    return sha[:10]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def candidate_stamp(tag: str, model: str) -> dict:
    return {"tag": tag, "model": model, "provider": "saia", "scored_at": _now(),
            "rubric": rubric_version(), "code": code_version()}


def setup_of(ensemble: list[str], judge: str, effort: str, rubric: str) -> tuple[str, str]:
    """(setup_id, readable label) for an ensemble of model IDs + judge."""
    key = json.dumps([sorted(ensemble), judge, effort or "", rubric or ""])
    label = f"{' + '.join(sorted(ensemble))} | judge {judge}" + (f" ({effort})" if effort else "")
    return _short_hash(key)[:8], label


def judge_stamp(ensemble_tags: list[str], candidates: dict[str, dict], judge: str,
                judged_by: str, provider: str, effort: str | None,
                declined: dict | None, judge_instructions: str | None = None) -> dict:
    """Provenance for a consensus verdict. `candidates` maps tag -> candidate JSON."""
    used = {t: ((c.get("scoring") or {}).get("model") or MODEL_IDS.get(t, t))
            for t, c in candidates.items()}
    ensemble = {t: used.get(t) or MODEL_IDS.get(t, t) for t in ensemble_tags}
    rubric = rubric_version()
    setup_id, setup = setup_of(list(ensemble.values()), judge, effort or "", rubric)
    return {"scored_at": _now(), "ensemble": ensemble, "candidates": used,
            "missing": [t for t in ensemble_tags if t not in used],
            "judge": judge, "judged_by": judged_by, "judge_provider": provider,
            "judge_effort": effort or "", "declined_by": (declined or {}).get("model", ""),
            "rubric": rubric, "judge_rubric": judge_rubric_version(judge_instructions), "code": code_version(),
            "setup_id": setup_id, "setup": setup}


def describe(stem: str, consensus: dict) -> dict:
    """One CSV row for a consensus JSON (new or published)."""
    s = consensus.get("scoring")
    if s:
        return {"stem": stem, "setup_id": s["setup_id"], "setup": s["setup"],
                "scored_at": s["scored_at"],
                "ensemble": "; ".join(s["ensemble"].values()),
                "candidates": "; ".join(s["candidates"].values()),
                "missing_candidates": "; ".join(s["ensemble"][t] for t in s["missing"]),
                "judge": s["judge"], "judged_by": s["judged_by"],
                "judge_effort": s["judge_effort"], "declined_by": s["declined_by"],
                "rubric": s["rubric"], "judge_rubric": s["judge_rubric"], "code": s["code"]}
    # Published v2 scores: only the judge model and the candidate tags were kept.
    used = [MODEL_IDS.get(t, t) for t in consensus.get("judge_input_models") or []]
    ensemble = [MODEL_IDS[t] for t in PUBLISHED_TAGS]
    judge = consensus.get("judge_model", "")
    setup_id, _ = setup_of(ensemble, judge, "", "")
    return {"stem": stem, "setup_id": setup_id, "setup": PUBLISHED_SETUP, "scored_at": "",
            "ensemble": "; ".join(ensemble), "candidates": "; ".join(used),
            "missing_candidates": "; ".join(m for m in ensemble if m not in used),
            "judge": judge, "judged_by": judge, "judge_effort": "", "declined_by": "",
            "rubric": "", "judge_rubric": "", "code": ""}


def build(consensus_dir: Path | None = None, out_csv: Path | None = None) -> list[dict]:
    from paths import CONSENSUS_DIR, DATA_DIR
    consensus_dir = consensus_dir or CONSENSUS_DIR
    out_csv = out_csv or DATA_DIR / "scoring_provenance.csv"
    rows = [describe(p.stem, json.loads(p.read_text()))
            for p in sorted(consensus_dir.glob("*.json"))]
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return rows


if __name__ == "__main__":
    import collections
    rows = build()
    print(f"{len(rows)} papers")
    for (sid, setup), n in collections.Counter((r["setup_id"], r["setup"]) for r in rows).items():
        print(f"  {n:4d}  {sid}  {setup}")
    short = sum(1 for r in rows if r["missing_candidates"])
    print(f"  {short} judged without every candidate; "
          f"{sum(1 for r in rows if r['declined_by'])} judged by a fallback model")

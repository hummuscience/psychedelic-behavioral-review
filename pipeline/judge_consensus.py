"""LLM-as-judge: consolidate multi-model scoring runs into one consensus JSON.

For each paper, reads the Docling markdown plus N candidate scoring JSONs
from results_full_compare/<model>/<stem>.json and asks Claude Opus 4.7 to produce
a single consolidated scoring in the same schema.

Usage:
    ANTHROPIC_API_KEY=... uv run python judge_consensus.py \\
        --pdf-dir ./pdfs \\
        --candidates-root ./results_full_compare \\
        --output-dir ./results_full_consensus \\
        --models qwen,mistral,gptoss,llama33,qwen122 \\
        --limit 10

By default does NOT include deepseek (hallucinates DOIs) or glm (timed out).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from openai import OpenAI, AzureOpenAI

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

# Default model IDs differ by provider:
#   anthropic direct:  claude-opus-4-7
#   openrouter:        anthropic/claude-opus-4.7
#   foundry:           AZURE_FOUNDRY_MODEL env var (deployment name)
DEFAULT_JUDGE_MODELS = {
    "anthropic": "claude-opus-4-7",
    "openrouter": "anthropic/claude-opus-4.7",
    "saia": "qwen3.5-397b-a17b",
    "foundry": None,  # resolved from AZURE_FOUNDRY_MODEL at runtime
}
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SAIA_BASE_URL = "https://chat-ai.academiccloud.de/v1"
DEFAULT_MODELS = ["qwen", "glm", "gptoss"]

JUDGE_INSTRUCTIONS = r"""You are the JUDGE in an ensemble scoring task.

You will receive:
1. The full markdown text of one scientific paper (animal behavioural study of psychedelics).
2. The original SCORING RUBRIC that was used by every candidate model.
3. Several CANDIDATE SCORING JSONs produced by different LLMs that each scored the same paper independently.

Your job: produce ONE consolidated scoring JSON, in the exact same schema as the candidates.

Decision rules:

- **Assay reconciliation.** Models disagree most on assay granularity. For each candidate "assay", decide whether it is:
  (a) a real behavioural paradigm in the paper,
  (b) a duplicate of another candidate (different name, same paradigm — common when models name dose-arms or genotype groups separately), or
  (c) a misclassification (non-behavioural physiological recording, in-silico work, ex-vivo molecular work, or a manipulation rather than a measurement).
  Output only the (a) cases. Merge (b)s. Drop (c)s.

- **Per-item scoring.** For each surviving assay, populate every item (B1–B8, E1–E8, D1–D6) using:
  - The modal candidate value when ≥2 candidates that included this assay agree.
  - When candidates disagree, weigh evidence: prefer the candidate whose evidence string actually matches text in the paper. Cite the paper if you override all candidates.
  - Use "low" confidence only when the paper genuinely doesn't say. Don't inherit a candidate's low-confidence flag if the paper actually states the value.

- **Descriptive metadata (housing & experimental conditions).** In addition to B/E/D items, populate:
  - Top-level `housing_conditions` (study-level, single block): `handling`, `group_housing`, `day_night_flipped`, `enrichment_housing`. Each item is `{value, evidence, confidence}`. Allowed values: yes / no / not_reported.
  - Per-assay `experimental_conditions`: `application_type` (i.p./i.v./i.c.v./s.c./p.o./i.n./i.m./multiple/other/not_reported), `setup_habituation` (yes/no/not_reported), `setup_restrain` (yes/no/not_reported), `food_restriction` (no/before/during/not_reported), `water_restriction` (no/before/during/not_reported).
  - These are descriptive metadata, NOT scored — they do not contribute to any raw_total. Use the modal candidate value; when candidates disagree, prefer the one whose evidence quote actually appears in the paper. Use "not_reported" only when the paper is genuinely silent.

- **Identity fields** (study_id, doi, species, strain, psychedelic):
  - For DOI/year: candidates often hallucinate or use online-pub-year. If the markdown lacks the masthead (Docling sometimes strips it), prefer the modal answer across candidates and mark "doi": null if all candidates disagree.
  - For species/strain/psychedelic: take from the paper if mentioned in Methods; otherwise modal.

- **Schema fidelity.** Output exactly the same JSON schema as the candidates: top-level study_id/doi/species/strain/psychedelic/housing_conditions/assays. Each assay has assay_name, assay_description, experimental_conditions, behavioural_complexity (B1–B8 + raw_total), environmental_complexity (E1–E8 + raw_total), recording_duration (D1–D6 + raw_total). Each B/E/D item has score (int), value (str), evidence (str), confidence ("high"|"medium"|"low"). Each housing_conditions / experimental_conditions item has value (str), evidence (str), confidence — no score field.

- **Judge metadata.** Add a top-level "judge_notes" field: an array of short strings explaining any non-trivial choices (e.g. "merged candidate A's 'Visual-object response' and 'Visual-placing response' into one Visual Response Test — same paradigm under different terminology").

Respond with a SINGLE JSON object. No prose, no markdown fences.
"""


def load_candidates(stem: str, candidates_root: Path,
                    model_tags: list[str]) -> dict[str, dict]:
    """Load each model's scoring JSON for `stem`. Returns {tag: data}.
    Skips models that didn't score this paper."""
    out = {}
    for tag in model_tags:
        path = candidates_root / tag / f"{stem}.json"
        if path.exists():
            try:
                out[tag] = json.loads(path.read_text())
            except Exception as e:
                print(f"  warn: could not load {path}: {e}", file=sys.stderr)
    return out


def build_messages(markdown: str, candidates: dict[str, dict]) -> list[dict]:
    """Build the user message for the judge. System prompt is sent separately."""
    candidates_text = "\n\n".join(
        f"=== CANDIDATE: {tag} ===\n{json.dumps(data, indent=2, ensure_ascii=False)}"
        for tag, data in candidates.items()
    )
    user = (
        "=== PAPER MARKDOWN ===\n"
        f"{markdown}\n"
        "=== END PAPER ===\n\n"
        "=== CANDIDATE SCORING OUTPUTS ===\n"
        f"{candidates_text}\n"
        "=== END CANDIDATES ===\n\n"
        "Produce the consolidated scoring JSON now."
    )
    return [{"role": "user", "content": user}]


def call_judge(client, provider: str, model: str, system_blocks: list[dict],
               user_msg: str, max_tokens: int = 16000) -> tuple[str, dict]:
    """Call the judge model. Returns (text, usage_dict)."""
    if provider in ("anthropic", "foundry"):
        # Both use the Anthropic Messages API. Foundry's deployment may
        # not support cache_control blocks — strip them if present.
        sys_for_call = system_blocks
        if provider == "foundry":
            sys_for_call = [{"type": "text", "text": b["text"]} for b in system_blocks]
        # Opus 4.7 (and newer reasoning models) reject `temperature`. Pass
        # it only on older Claude versions where it's still supported.
        create_kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            system=sys_for_call,
            messages=[{"role": "user", "content": user_msg}],
        )
        if "opus-4-7" not in model and "haiku-4-5" not in model and "sonnet-4-6" not in model:
            create_kwargs["temperature"] = 0.0
        # Retry on 429 (rate limit). Foundry enforces 50k input tokens / 60s,
        # which our ~35k-token judge calls can easily exceed in concurrent
        # bursts. The error message includes a 'Please wait N seconds'
        # suggestion — honour it, plus a small slack.
        max_retries = 5
        for attempt in range(max_retries + 1):
            try:
                resp = client.messages.create(**create_kwargs)
                break
            except anthropic.RateLimitError as e:
                if attempt == max_retries:
                    raise
                msg = str(e)
                wait = 30
                m = re.search(r"wait\s+(\d+)\s+seconds?", msg, re.I)
                if m:
                    wait = int(m.group(1))
                wait += 5  # slack
                print(f"  [judge] rate limit hit; sleeping {wait}s (attempt {attempt+1}/{max_retries})",
                      file=sys.stderr, flush=True)
                time.sleep(wait)
        text = ""
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                text = block.text
                break
        usage = {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "cache_read_input_tokens": getattr(
                resp.usage, "cache_read_input_tokens", 0),
            "cache_creation_input_tokens": getattr(
                resp.usage, "cache_creation_input_tokens", 0),
        }
        return text, usage

    if provider == "saia":
        # Both are OpenAI-compatible endpoints without Anthropic-style
        # cache_control or content-parts arrays. Flatten system blocks
        # into a single string and force JSON output.
        system_text = "\n\n".join(b["text"] for b in system_blocks)
        try:
            resp = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
            )
        except Exception as e:
            raise RuntimeError(f"{provider.upper()} judge call failed: {e}") from e
        text = resp.choices[0].message.content or ""
        u = resp.usage
        usage = {
            "input_tokens": getattr(u, "prompt_tokens", 0),
            "output_tokens": getattr(u, "completion_tokens", 0),
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        return text, usage

    # OpenRouter (OpenAI-compatible).
    # Pass cache_control by sending system as an array of content parts —
    # OpenRouter forwards cache_control to Anthropic upstream when present.
    # See https://openrouter.ai/docs/features/prompt-caching
    system_content = []
    for b in system_blocks:
        part = {"type": "text", "text": b["text"]}
        if b.get("cache_control"):
            part["cache_control"] = b["cache_control"]
        system_content.append(part)

    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0.0,
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_msg},
        ],
    )
    text = resp.choices[0].message.content or ""
    if not text:
        choice = resp.choices[0]
        print(
            f"  debug: finish_reason={getattr(choice, 'finish_reason', None)}  "
            f"native_finish_reason={getattr(choice, 'native_finish_reason', None)}  "
            f"refusal={getattr(choice.message, 'refusal', None)}",
            file=sys.stderr,
        )
        raw_dict = resp.model_dump() if hasattr(resp, "model_dump") else {}
        Path("/tmp/judge_empty_response.json").write_text(
            json.dumps(raw_dict, indent=2, default=str)
        )
    u = resp.usage
    # OpenRouter exposes Anthropic cache stats via the standard
    # prompt_tokens_details.cached_tokens field (OpenAI-style).
    cached = 0
    details = getattr(u, "prompt_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", 0) or 0
    usage = {
        "input_tokens": u.prompt_tokens,
        "output_tokens": u.completion_tokens,
        "cache_read_input_tokens": cached,
        "cache_creation_input_tokens": 0,
    }
    return text, usage


def judge_one(client, provider: str, model: str, stem: str, pdf_dir: Path,
              candidates_root: Path, model_tags: list[str], max_tokens: int = 16000) -> dict:
    md_path = pdf_dir / f"{stem}.docling.md"
    if not md_path.exists():
        raise FileNotFoundError(f"missing markdown: {md_path}")
    markdown = md_path.read_text()

    candidates = load_candidates(stem, candidates_root, model_tags)
    if not candidates:
        raise RuntimeError(f"no candidate JSONs for {stem}")

    messages = build_messages(markdown, candidates)
    user_msg = messages[0]["content"]

    # System prompt = scoring rubric + judge instructions.
    # Cache_control on the rubric so we don't re-pay for it across papers.
    system_blocks = [
        {
            "type": "text",
            "text": "ORIGINAL SCORING RUBRIC (used by all candidates):\n\n"
                    + SCORING_PROMPT,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": JUDGE_INSTRUCTIONS,
        },
    ]

    text, usage = call_judge(client, provider, model, system_blocks, user_msg, max_tokens=max_tokens)
    raw = text
    text = text.strip()
    # Strip leading prose / fences if present
    if text.startswith("```"):
        # remove first fence line
        lines = text.split("\n", 1)
        text = lines[1] if len(lines) > 1 else ""
    # Always strip a trailing fence too (Haiku sometimes emits ``` only at the
    # end, even when no opening fence is present).
    text = text.strip()
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0].strip()
    if not text:
        raise RuntimeError(
            f"empty response from judge for {stem} "
            f"(in_tokens={usage['input_tokens']}, out_tokens={usage['output_tokens']})"
        )
    # Find first { and last } if there's surrounding prose
    if not text.startswith("{"):
        first = text.find("{")
        last = text.rfind("}")
        if first >= 0 and last > first:
            text = text[first : last + 1]
    elif not text.endswith("}"):
        # Trim trailing prose
        last = text.rfind("}")
        if last > 0:
            text = text[: last + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Save raw for inspection
        debug_path = Path(f"/tmp/judge_raw_{stem}.txt")
        debug_path.write_text(raw)
        raise RuntimeError(
            f"could not parse JSON from judge for {stem}; "
            f"raw saved to {debug_path}"
        )
    parsed = normalize_keys(parsed)

    filter_non_behavioural_assays(parsed)
    recompute_raw_totals(parsed)
    parsed["study_level_scores"] = compute_study_scores(parsed)

    low_conf = 0
    for assay in parsed.get("assays", []):
        for dim in ITEM_KEYS:
            for key in ITEM_KEYS[dim]:
                if assay.get(dim, {}).get(key, {}).get("confidence") == "low":
                    low_conf += 1
        for key in EXPERIMENTAL_CONDITION_KEYS:
            if assay.get("experimental_conditions", {}).get(key, {}).get("confidence") == "low":
                low_conf += 1
    for key in HOUSING_KEYS:
        if parsed.get("housing_conditions", {}).get(key, {}).get("confidence") == "low":
            low_conf += 1
    parsed["low_confidence_count"] = low_conf

    parsed["judge_provider"] = provider
    parsed["judge_model"] = model
    parsed["judge_input_models"] = list(candidates.keys())
    parsed["judge_usage"] = usage
    return parsed


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", type=Path, required=True,
                    help="Folder with <stem>.docling.md files")
    ap.add_argument("--candidates-root", type=Path, required=True,
                    help="Root folder of model subdirs with per-paper JSONs")
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--judge-provider", choices=["anthropic", "openrouter", "saia", "foundry"],
                    default="openrouter",
                    help="Where to call the judge model. "
                         "openrouter (default) uses OPENROUTER_API_KEY; "
                         "anthropic uses ANTHROPIC_API_KEY; "
                         "saia uses SAIA_API_KEY (free for academic users); "
                         "foundry uses AZURE_FOUNDRY_API_KEY + AZURE_FOUNDRY_ENDPOINT + AZURE_FOUNDRY_MODEL.")
    ap.add_argument("--judge-model", type=str, default=None,
                    help="Override judge model id. Defaults: "
                         "anthropic→claude-opus-4-7, "
                         "openrouter→anthropic/claude-opus-4.7, "
                         "saia→qwen3.5-397b-a17b, "
                         "foundry→$AZURE_FOUNDRY_MODEL")
    ap.add_argument("--models", type=str, default=",".join(DEFAULT_MODELS),
                    help=f"Comma-separated candidate model tags "
                         f"(default: {','.join(DEFAULT_MODELS)})")
    ap.add_argument("--limit", type=int, default=None,
                    help="Process only the first N stems (alphabetical)")
    ap.add_argument("--stem", type=str, default=None,
                    help="Process a single paper by stem (overrides --limit)")
    ap.add_argument("--resume", action="store_true",
                    help="Skip stems already in output-dir")
    ap.add_argument("--max-tokens", type=int, default=16000,
                    help="Judge output token cap (default: 16000). Bump for papers with many assays.")
    args = ap.parse_args()

    provider = args.judge_provider
    judge_model = args.judge_model or DEFAULT_JUDGE_MODELS[provider]

    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("ANTHROPIC_API_KEY not set")
        client = anthropic.Anthropic()
    elif provider == "saia":
        if not os.environ.get("SAIA_API_KEY"):
            sys.exit("SAIA_API_KEY not set")
        client = OpenAI(
            api_key=os.environ["SAIA_API_KEY"],
            base_url=SAIA_BASE_URL,
            timeout=480,
            max_retries=0,
        )
    elif provider == "foundry":
        api_key = os.environ.get("AZURE_FOUNDRY_API_KEY")
        endpoint = os.environ.get("AZURE_FOUNDRY_ENDPOINT")
        if not api_key or not endpoint:
            sys.exit("AZURE_FOUNDRY_API_KEY and AZURE_FOUNDRY_ENDPOINT must both be set in .env")
        # Microsoft Foundry exposes Claude via the native Anthropic Messages
        # API at <endpoint>/anthropic/v1/messages, with x-api-key auth and an
        # api-version query parameter. The Anthropic SDK already uses
        # x-api-key; we just point it at the Foundry base URL (the SDK
        # appends "/v1/messages" itself) and let api-version flow through
        # default_query.
        api_version = os.environ.get("AZURE_FOUNDRY_API_VERSION", "2024-10-21")
        client = anthropic.Anthropic(
            api_key=api_key,
            base_url=endpoint.rstrip("/") + "/anthropic",
            default_query={"api-version": api_version},
            timeout=480,
            max_retries=0,
        )
        if not judge_model:
            judge_model = os.environ.get("AZURE_FOUNDRY_MODEL", "")
            if not judge_model:
                sys.exit("AZURE_FOUNDRY_MODEL not set and no --judge-model provided")
    else:
        if not os.environ.get("OPENROUTER_API_KEY"):
            sys.exit("OPENROUTER_API_KEY not set")
        client = OpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url=OPENROUTER_BASE_URL,
            timeout=480,
            max_retries=0,
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    model_tags = [m.strip() for m in args.models.split(",") if m.strip()]

    # Pick stems
    if args.stem:
        stems = [args.stem]
    else:
        # Stems = papers that have markdown AND at least one candidate JSON
        stems = []
        for md in sorted(args.pdf_dir.glob("*.docling.md")):
            stem = md.name.removesuffix(".docling.md")
            for tag in model_tags:
                if (args.candidates_root / tag / f"{stem}.json").exists():
                    stems.append(stem)
                    break
        if args.limit:
            stems = stems[: args.limit]

    print(f"Judging {len(stems)} papers via {provider} ({judge_model})")
    print(f"Candidate models: {model_tags}")

    summary = {"ok": 0, "fail": 0, "total_in": 0, "total_out": 0,
               "total_cache_read": 0, "total_cache_create": 0}

    for stem in stems:
        out_path = args.output_dir / f"{stem}.json"
        if args.resume and out_path.exists():
            print(f"  [skip cached] {stem}")
            continue

        t0 = time.time()
        try:
            result = judge_one(client, provider, judge_model, stem,
                               args.pdf_dir, args.candidates_root, model_tags,
                               max_tokens=args.max_tokens)
            out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
            dt = time.time() - t0
            sc = result["study_level_scores"]
            usage = result["judge_usage"]
            summary["ok"] += 1
            summary["total_in"] += usage["input_tokens"]
            summary["total_out"] += usage["output_tokens"]
            summary["total_cache_read"] += usage["cache_read_input_tokens"]
            summary["total_cache_create"] += usage["cache_creation_input_tokens"]
            print(
                f"  [{dt:5.1f}s] {stem}  "
                f"B={sc['behavioural_complexity_max']:.1f} "
                f"E={sc['environmental_complexity_max']:.1f} "
                f"D={sc['recording_duration_max']:.1f}  "
                f"({len(result['assays'])} assays, "
                f"{result['low_confidence_count']} low-conf, "
                f"in={usage['input_tokens']} out={usage['output_tokens']} "
                f"cache_read={usage['cache_read_input_tokens']})"
            )
        except Exception as e:
            dt = time.time() - t0
            summary["fail"] += 1
            print(f"  [{dt:5.1f}s] {stem}  ERROR: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    print()
    print(f"Done. ok={summary['ok']}  fail={summary['fail']}")
    print(f"Tokens: in={summary['total_in']:,} out={summary['total_out']:,} "
          f"cache_read={summary['total_cache_read']:,} "
          f"cache_create={summary['total_cache_create']:,}")


if __name__ == "__main__":
    main()

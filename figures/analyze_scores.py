"""
Post-scoring analysis: sensitivity analyses and quality checks.

Usage:
    python analyze_scores.py --results-dir ./results

Runs after score_studies.py has generated study_scores.csv and per-study JSONs.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# ---------------------------------------------------------------------------
# Raw max constants (must match score_studies.py)
# ---------------------------------------------------------------------------

RAW_MAX = {
    "behavioural_complexity": 12,
    "environmental_complexity": 11,
    "recording_duration": 11,
}

ITEM_KEYS = {
    "behavioural_complexity": [
        "B1_num_measures", "B2_temporal_dynamics", "B3_sequential_structure",
        "B4_ethological", "B5_social", "B6_cognitive",
        "B7_automated_classification", "B8_multivariate",
    ],
    "environmental_complexity": [
        "E1_environment_type", "E2_shelter", "E3_bedding", "E4_nesting",
        "E5_enrichment", "E6_spatial", "E7_social_context", "E8_food_water",
    ],
    "recording_duration": [
        "D1_continuity", "D2_session_duration", "D3_recording_days",
        "D4_baseline", "D5_followup", "D6_circadian",
    ],
}

# Sensitivity S1: higher-weight items (x2 instead of x1)
WEIGHT_2X = {
    "behavioural_complexity": {"B3_sequential_structure", "B4_ethological", "B7_automated_classification"},
    "environmental_complexity": {"E1_environment_type"},
    "recording_duration": {"D2_session_duration", "D3_recording_days"},
}

WEIGHTED_RAW_MAX = {}
for dim, keys in ITEM_KEYS.items():
    # Recalculate max with weights
    total = 0
    for k in keys:
        max_item_score = 3 if k in ("B1_num_measures", "B5_social",
                                     "E1_environment_type",
                                     "D2_session_duration", "D3_recording_days") else \
                         2 if k in ("E7_social_context", "D1_continuity") else 1
        weight = 2 if k in WEIGHT_2X.get(dim, set()) else 1
        total += max_item_score * weight
    WEIGHTED_RAW_MAX[dim] = total


def load_item_scores(results_dir: Path) -> pd.DataFrame:
    """Load item-level scores from all study JSONs into a flat DataFrame."""
    rows = []
    for jf in sorted(results_dir.glob("*.json")):
        if jf.name == "summary.json":
            continue
        data = json.loads(jf.read_text())
        study_id = data.get("study_id", jf.stem)

        for ai, assay in enumerate(data.get("assays", [])):
            row = {"study_id": study_id, "assay_idx": ai,
                   "assay_name": assay.get("assay_name", "")}
            for dim, keys in ITEM_KEYS.items():
                for key in keys:
                    item = assay.get(dim, {}).get(key, {})
                    row[f"{key}_score"] = item.get("score", 0)
                    row[f"{key}_confidence"] = item.get("confidence", "")
            rows.append(row)

    return pd.DataFrame(rows)


def s1_weighting_sensitivity(df_items: pd.DataFrame):
    """S1: Compare equal vs. differential weighting."""
    print("\n" + "=" * 60)
    print("S1: EQUAL vs. DIFFERENTIAL WEIGHTING")
    print("=" * 60)

    for dim, keys in ITEM_KEYS.items():
        equal_scores = []
        weighted_scores = []

        for _, row in df_items.iterrows():
            raw_equal = sum(row.get(f"{k}_score", 0) for k in keys)
            raw_weighted = sum(
                row.get(f"{k}_score", 0) * (2 if k in WEIGHT_2X.get(dim, set()) else 1)
                for k in keys
            )
            equal_scores.append((raw_equal / RAW_MAX[dim]) * 15)
            weighted_scores.append((raw_weighted / WEIGHTED_RAW_MAX[dim]) * 15)

        rho, p = stats.spearmanr(equal_scores, weighted_scores)
        print(f"\n  {dim}:")
        print(f"    Spearman rho = {rho:.3f} (p = {p:.2e})")
        print(f"    {'Weighting has NEGLIGIBLE effect (rho > 0.90)' if rho > 0.90 else 'Weighting MATTERS — report both'}")


def s2_not_reported(df_items: pd.DataFrame):
    """S2: Sensitivity to 'not reported' items scored as 0 vs. 1."""
    print("\n" + "=" * 60)
    print("S2: NOT-REPORTED SENSITIVITY")
    print("=" * 60)

    low_conf_count = 0
    total_items = 0
    for dim, keys in ITEM_KEYS.items():
        for key in keys:
            col = f"{key}_confidence"
            if col in df_items.columns:
                n_low = (df_items[col] == "low").sum()
                n_total = len(df_items)
                low_conf_count += n_low
                total_items += n_total
                if n_low > 0:
                    print(f"  {key}: {n_low}/{n_total} assays ({100*n_low/n_total:.1f}%) low confidence")

    print(f"\n  Total: {low_conf_count}/{total_items} item-assay pairs "
          f"({100*low_conf_count/total_items:.1f}%) flagged as low confidence")

    # Compute conservative vs. generous study-level scores
    print("\n  Impact on study-level scores if all low-confidence items scored 1:")
    for dim, keys in ITEM_KEYS.items():
        conservative = []
        generous = []
        for study_id in df_items["study_id"].unique():
            study_rows = df_items[df_items["study_id"] == study_id]
            c_max, g_max = 0, 0
            for _, row in study_rows.iterrows():
                raw_c = sum(row.get(f"{k}_score", 0) for k in keys)
                raw_g = sum(
                    row.get(f"{k}_score", 0) if row.get(f"{k}_confidence", "") != "low"
                    else max(row.get(f"{k}_score", 0), 1)
                    for k in keys
                )
                c_max = max(c_max, (raw_c / RAW_MAX[dim]) * 15)
                g_max = max(g_max, (raw_g / RAW_MAX[dim]) * 15)
            conservative.append(c_max)
            generous.append(g_max)

        rho, _ = stats.spearmanr(conservative, generous)
        mean_diff = np.mean(np.array(generous) - np.array(conservative))
        print(f"    {dim}: rank correlation = {rho:.3f}, mean score increase = {mean_diff:.2f}")


def s3_aggregation(results_dir: Path):
    """S3: Max vs. mean aggregation."""
    print("\n" + "=" * 60)
    print("S3: MAX vs. MEAN AGGREGATION")
    print("=" * 60)

    df = pd.read_csv(results_dir / "study_scores.csv")

    for dim_short, dim_full in [("behav_complexity", "behavioural_complexity"),
                                 ("env_complexity", "environmental_complexity"),
                                 ("rec_duration", "recording_duration")]:
        max_col = dim_short
        mean_col = f"{dim_short}_mean"
        if max_col not in df.columns or mean_col not in df.columns:
            continue

        rho, _ = stats.spearmanr(df[max_col], df[mean_col])
        diff = df[max_col] - df[mean_col]
        print(f"\n  {dim_full}:")
        print(f"    Spearman rho (max vs mean) = {rho:.3f}")
        print(f"    Mean difference (max - mean) = {diff.mean():.2f} ± {diff.std():.2f}")

        # Studies most affected
        df_sorted = df.assign(diff=diff).sort_values("diff", ascending=False)
        top = df_sorted.head(5)
        if (top["diff"] > 1).any():
            print(f"    Studies most affected (max >> mean):")
            for _, row in top.iterrows():
                if row["diff"] > 1:
                    print(f"      {row['study_id']}: max={row[max_col]:.1f}, "
                          f"mean={row[mean_col]:.1f}, diff={row['diff']:.1f}")


def s4_item_variance(df_items: pd.DataFrame):
    """S4: Item variance and redundancy check."""
    print("\n" + "=" * 60)
    print("S4: ITEM VARIANCE AND REDUNDANCY")
    print("=" * 60)

    print("\n  Item-level score distributions:")
    print(f"  {'Item':<35} {'Mean':>6} {'SD':>6} {'% zero':>7} {'% max':>7}")
    print("  " + "-" * 61)

    score_cols = {}
    for dim, keys in ITEM_KEYS.items():
        for key in keys:
            col = f"{key}_score"
            if col in df_items.columns:
                s = df_items[col]
                max_val = 3 if key in ("B1_num_measures", "E1_environment_type",
                                        "D2_session_duration", "D3_recording_days") else \
                          2 if key in ("B5_social", "E7_social_context", "D1_continuity") else 1
                pct_zero = 100 * (s == 0).sum() / len(s)
                pct_max = 100 * (s == max_val).sum() / len(s)
                flag = " ← LOW VARIANCE" if pct_zero > 95 or pct_max > 95 else ""
                print(f"  {key:<35} {s.mean():>6.2f} {s.std():>6.2f} "
                      f"{pct_zero:>6.1f}% {pct_max:>6.1f}%{flag}")
                score_cols[key] = s

    # Pairwise correlations within dimensions
    print("\n  Pairwise correlations (r > 0.80 flagged):")
    for dim, keys in ITEM_KEYS.items():
        dim_scores = pd.DataFrame({k: df_items.get(f"{k}_score", pd.Series()) for k in keys})
        corr = dim_scores.corr()
        for i, k1 in enumerate(keys):
            for k2 in keys[i+1:]:
                r = corr.loc[k1, k2]
                if abs(r) > 0.80:
                    print(f"    {k1} ↔ {k2}: r = {r:.2f} ← POSSIBLE REDUNDANCY")


def main():
    parser = argparse.ArgumentParser(description="Sensitivity analyses for study scores")
    parser.add_argument("--results-dir", type=Path, required=True)
    args = parser.parse_args()

    print("Loading item-level scores...")
    df_items = load_item_scores(args.results_dir)
    print(f"  {len(df_items)} assays across {df_items['study_id'].nunique()} studies\n")

    s1_weighting_sensitivity(df_items)
    s2_not_reported(df_items)
    s3_aggregation(args.results_dir)
    s4_item_variance(df_items)

    print("\n" + "=" * 60)
    print("DONE — review flagged items above before finalizing scores")
    print("=" * 60)


if __name__ == "__main__":
    main()

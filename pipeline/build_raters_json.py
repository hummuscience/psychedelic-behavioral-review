#!/usr/bin/env python3
"""Build raters.json — the single source for the inter-rater comparison.

Combines the two human raters into one file, shape:

    {
      "<stem>": {
        "paper_num": <int>,
        "rater1": [ {assay_name, B{}, E{}, D{}}, ... ],   # was "Ana" (docx)
        "rater2": [ {assay_name, B{}, E{}, D{}, _provenance?}, ... ]  # was HITL
      },
      ...
    }

rater1 is parsed from the scoring-guide docx (scoring_guide_ana_version4.docx);
rater2 comes from human_scores_hitl.json. This script is the one place that reads
those upstream sources — downstream analysis (plot_three_way.py via
rater_lib.load_raters) reads raters.json only.

Run:  python build_raters_json.py
"""
from __future__ import annotations

import json

import rater_lib as rl

OUT = rl.ROOT / "raters.json"


def build() -> dict:
    rater1 = rl.parse_ana_docx()      # {stem: [ {assay_name,B,E,D}, ... ]}
    rater2_raw = rl.load_hitl()       # {stem: {paper_num, assays:[...]}}

    out: dict[str, dict] = {}
    # Keep PAPER_STEMS order, then any extras.
    stems = [s for s in rl.PAPER_STEMS if s in rater2_raw or s in rater1]
    for s in rater2_raw:
        if s not in stems:
            stems.append(s)

    for stem in stems:
        r2 = rater2_raw.get(stem, {})
        out[stem] = {
            "paper_num": r2.get("paper_num"),
            "rater1": rater1.get(stem, []),
            "rater2": r2.get("assays", []),
        }
    return out


def main() -> None:
    data = build()
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    n_r1 = sum(1 for v in data.values() if v["rater1"])
    n_r2 = sum(1 for v in data.values() if v["rater2"])
    print(f"Wrote {OUT}")
    print(f"  papers: {len(data)}  |  rater1 filled: {n_r1}  |  rater2 filled: {n_r2}")


if __name__ == "__main__":
    main()

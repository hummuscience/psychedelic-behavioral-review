"""Build-time loader: emit dosages_llm_summary.csv (paper × compound rollup)."""
import sys
from pathlib import Path

ROOT = Path(__file__).parents[3] / "data"
print(Path(ROOT / "dosages_llm_summary.csv").read_text(), end="")

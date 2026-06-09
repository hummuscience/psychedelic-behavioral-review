"""Build-time loader: emit results/assay_catalog.json sorted by category order."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[3] / "data"
CATALOG = ROOT / "results" / "assay_catalog.json"

CATEGORY_ORDER = [
    "Psychedelic response",
    "Anxiety",
    "Depression / anhedonia",
    "Locomotor / motor",
    "Cognition / memory",
    "Social behaviour",
    "Addiction / substance use",
    "Pain",
    "Sensorimotor",
    "Physiological",
    "Miscellaneous",
]
rank = {c: i for i, c in enumerate(CATEGORY_ORDER)}

if CATALOG.exists():
    data = json.loads(CATALOG.read_text())
    data.sort(key=lambda e: (rank.get(e.get("category", ""), 99), -e.get("count", 0)))
    json.dump(data, sys.stdout, ensure_ascii=False, separators=(",", ":"))
else:
    json.dump([], sys.stdout)

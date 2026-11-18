"""Build data/results/assay_catalog.json and data/results/paper_assays.json.

Reads consensus JSONs, normalises the free-text assay_name field to a
canonical assay name + category, and produces two artefacts:

  paper_assays.json   {stem: [{canonical, category, raw}]}
  assay_catalog.json  [{canonical, category, count, papers:[stems]}]

Two modes:

  --add STEM [STEM ...]   Add (or replace) only these papers on top of the
                          committed files. Every other entry is left exactly
                          as published. This is what the monthly update uses.
  --rebuild               Rebuild both files from every consensus JSON. This
                          changes published numbers, so run it deliberately.
"""
from __future__ import annotations
import argparse, json, os, re, unicodedata
from pathlib import Path

from paths import CONSENSUS_DIR as _DEFAULT_CONSENSUS_DIR, RESULTS_DIR

# CONSENSUS_DIR can be overridden by env var so the same script can build the
# catalog from either the v1 or v2 consensus directory without code edits.
CONSENSUS_DIR = Path(os.environ.get("CONSENSUS_DIR", str(_DEFAULT_CONSENSUS_DIR)))
OUT_PAPER = RESULTS_DIR / "paper_assays.json"
OUT_CATALOG = RESULTS_DIR / "assay_catalog.json"

# ── Canonical mapping ────────────────────────────────────────────────────────
# Rules evaluated top-to-bottom; first match wins.
# Each entry: (regex_pattern, canonical_name, category)
# Pattern is matched case-insensitively against the raw assay_name.

RULES: list[tuple[str, str, str]] = [
    # ── Psychedelic / 5-HT2A signature ─────────────────────────────────────
    (r"head.?twitch|head.twitch|HTR|wet.?dog.?shake|WDS|5-HTP.induced head|ear.scratch",
     "Head-Twitch Response (HTR)", "Psychedelic response"),
    (r"drug.?discriminat",
     "Drug Discrimination", "Psychedelic response"),
    (r"hallucinogen.?rating|HRS", "Hallucinogen Rating Scale", "Psychedelic response"),
    (r"audiogenic seizure|AGS", "Audiogenic Seizure", "Psychedelic response"),
    (r"pupil.?dilation|oculomet", "Pupil Dilation", "Psychedelic response"),
    (r"rectal.?temp|body.?temp|hypertherm", "Body Temperature", "Psychedelic response"),
    (r"serotonin.?syndrome|back.?muscle|grooming.*serotonin",
     "Serotonin Syndrome Observation", "Psychedelic response"),

    # ── Anxiety ─────────────────────────────────────────────────────────────
    (r"elevated.?plus.?maze|EPM|elevated plus", "Elevated Plus Maze", "Anxiety"),
    (r"elevated.?zero.?maze|EZM", "Elevated Zero Maze", "Anxiety"),
    (r"light.?dark|dark.?light|black.*white.*box|B\s*&\s*W",
     "Light-Dark Box", "Anxiety"),
    (r"marble.?bur", "Marble Burying", "Anxiety"),
    (r"novelty.?suppress|NSF|NSFT", "Novelty-Suppressed Feeding", "Anxiety"),
    (r"open.?field.*anxi|anxiety.*open.?field", "Open Field Test (anxiety)", "Anxiety"),
    (r"stress.induced.*resist|social.defeat", "Stress Model", "Anxiety"),

    # ── Depression / Anhedonia ───────────────────────────────────────────────
    (r"forced.?swim|porsolt|FST|PST", "Forced Swim Test", "Depression / anhedonia"),
    (r"tail.?suspension|TST", "Tail Suspension Test", "Depression / anhedonia"),
    (r"sucrose.?prefer|saccharin.?prefer|sweet.*prefer",
     "Sucrose Preference Test", "Depression / anhedonia"),
    (r"splash.?test", "Splash Test", "Depression / anhedonia"),
    (r"learned.?helpless", "Learned Helplessness", "Depression / anhedonia"),
    (r"coat.?state|fur.?state", "Coat State Assessment", "Depression / anhedonia"),
    (r"nest.?build|nesting", "Nest-Building Test", "Depression / anhedonia"),
    (r"buried.?oreo", "Buried Oreo Test", "Depression / anhedonia"),
    (r"affective.?bias", "Affective Bias Test", "Depression / anhedonia"),
    (r"female.?urine.?sniff|FUST", "Female Urine Sniffing Test", "Depression / anhedonia"),
    (r"reward.?learn", "Reward Learning Assay", "Depression / anhedonia"),

    # ── Locomotor / Motor ────────────────────────────────────────────────────
    (r"open.?field|OFT\b|locomotor.?activit|locomotion|motor.?activit|horizontal.?locomot|infrared.?locomot|spontaneous.?locomot",
     "Open Field Test (locomotion)", "Locomotor / motor"),
    (r"rota.?rod|rotarod|accelerod", "Rotarod / Accelerod", "Locomotor / motor"),
    (r"beam.?walk|balance.?beam", "Beam Walk", "Locomotor / motor"),
    (r"drag.?test", "Drag Test", "Locomotor / motor"),
    (r"grid.?test|grid.?walk", "Grid Test", "Locomotor / motor"),
    (r"grip.?strength", "Grip Strength", "Locomotor / motor"),
    (r"gait.?analys|CatWalk|DigiGait|catwalk", "Gait Analysis", "Locomotor / motor"),
    (r"hind.?limb.?clasp", "Hind Limb Clasping", "Locomotor / motor"),
    (r"catalepsy", "Catalepsy", "Locomotor / motor"),
    (r"treadmill.*locomot|running.?wheel|voluntary.?running",
     "Wheel / Treadmill Running", "Locomotor / motor"),
    (r"loss.?of.?righting|LORR", "Loss of Righting Reflex", "Locomotor / motor"),
    (r"apomorphine.*climb", "Apomorphine-Induced Climbing", "Locomotor / motor"),
    (r"circular.?corridor|cyclotron", "Circular Corridor", "Locomotor / motor"),

    # ── Cognition / Memory ───────────────────────────────────────────────────
    (r"morris.?water.?maze|MWM|water.?maze.*morris|water.maze",
     "Morris Water Maze", "Cognition / memory"),
    (r"novel.?object.?recogn|NOR\b|NORT\b|object.?recogn",
     "Novel Object Recognition", "Cognition / memory"),
    (r"y.?maze|spontaneous.?altern|SAB",
     "Y-Maze / Spontaneous Alternation", "Cognition / memory"),
    (r"radial.?arm.?maze|RAM|DNMP", "Radial Arm Maze", "Cognition / memory"),
    (r"fear.?condition|contextual.?fear|cued.?fear|auditory.?fear|pavlov.*fear|FC\b|trace.?fear",
     "Fear Conditioning", "Cognition / memory"),
    (r"fear.?extinct|extinction.*fear", "Fear Extinction", "Cognition / memory"),
    (r"reversal.?learn|operant.?revers|pavlov.*revers|set.?shift|ASST|attentional.?set",
     "Reversal / Set-Shifting Learning", "Cognition / memory"),
    (r"5.choice|5-CSRTT|serial.?reaction.?time|1-CSRT",
     "Serial Reaction Time Task", "Cognition / memory"),
    (r"delay.?discount|DDT|temporal.?discount|probability.?discount|probabilistic.?punct",
     "Delay / Probability Discounting", "Cognition / memory"),
    (r"temporal.?discriminat|TDT", "Temporal Discrimination", "Cognition / memory"),
    (r"iowa.?gambl", "Iowa Gambling Task", "Cognition / memory"),
    (r"conditioned.?avoidance|CAR\b|active.?avoidance|passive.?avoidance",
     "Conditioned / Active Avoidance", "Cognition / memory"),
    (r"object.?pattern.?sep|OPS\b", "Object Pattern Separation", "Cognition / memory"),
    (r"novel.?location|NLRT", "Novel Location Recognition", "Cognition / memory"),
    (r"differential.?reinforc|DRL", "Differential Reinforcement (DRL)", "Cognition / memory"),
    (r"olfactory.?search|odor.?discriminat|four.choice.?odor",
     "Olfactory Discrimination", "Cognition / memory"),
    (r"continuous.?performance|CPT\b", "Continuous Performance Test", "Cognition / memory"),
    (r"carousel.?maze|active.?place.?avoid", "Carousel / Active Place Avoidance", "Cognition / memory"),
    (r"visual.?discriminat|2.choice.?visual|luminance|motion.?based.*discrimin",
     "Visual Discrimination", "Cognition / memory"),

    # ── Social behaviour ─────────────────────────────────────────────────────
    (r"three.?chamber|3-chamber|3CSI|TCT\b",
     "Three-Chamber Social Test", "Social behaviour"),
    (r"social.?interact|reciprocal.?social|direct.?social|RSI\b|DSI\b",
     "Social Interaction Test", "Social behaviour"),
    (r"social.?prefer|SP\b.*test", "Social Preference Test", "Social behaviour"),
    (r"ultrasonic.?vocal|USV\b", "Ultrasonic Vocalizations (USV)", "Social behaviour"),
    (r"tube.?dominance", "Tube Dominance Test", "Social behaviour"),
    (r"social.?conditioned.?place|sCPP", "Social CPP", "Social behaviour"),
    (r"sexual.?behav", "Sexual Behaviour", "Social behaviour"),

    # ── Addiction / Substance use ────────────────────────────────────────────
    (r"conditioned.?place.?prefer|CPP\b|place.?condition",
     "Conditioned Place Preference (CPP)", "Addiction / substance use"),
    (r"conditioned.?place.?avers|CPA\b", "Conditioned Place Aversion", "Addiction / substance use"),
    (r"intravenous.?self.?admin|IVSA|cocaine.*self.?admin|heroin.*self.?admin|fentanyl.*self.?admin|opioid.*self.?admin",
     "Intravenous Self-Administration", "Addiction / substance use"),
    (r"operant.*alcohol.*self.?admin|alcohol.*operant|ethanol.*self.?admin",
     "Operant Alcohol Self-Administration", "Addiction / substance use"),
    (r"two.?bottle.?choice|2.?bottle.*ethanol|intermittent.?ethanol.*drink|voluntary.*ethanol|alcohol.*drinking",
     "Two-Bottle Choice Drinking", "Addiction / substance use"),
    (r"alcohol.?deprivation|ADE\b", "Alcohol Deprivation Effect", "Addiction / substance use"),
    (r"binge.?eat|activity.?based.?anorex|ABA\b", "Binge Eating / Anorexia Model", "Addiction / substance use"),
    (r"intracranial.?self.?stimul|ICSS",
     "Intracranial Self-Stimulation (ICSS)", "Addiction / substance use"),
    (r"progressive.?ratio|PR\b.*task|PR\b.*schedule",
     "Progressive Ratio Task", "Addiction / substance use"),
    (r"reinstat|cue.?induced|extinction.?and.?reinstat",
     "Extinction / Reinstatement", "Addiction / substance use"),
    (r"operant.?respond|food.?maintain|operant.*sucrose|operant.*water|FR5|FR\d",
     "Operant Responding", "Addiction / substance use"),
    (r"schedule.?induced.?polydipsia|SIP\b",
     "Schedule-Induced Polydipsia", "Addiction / substance use"),
    (r"cue.*reinstat|drug.?seek", "Drug Seeking / Cue Reinstatement", "Addiction / substance use"),
    (r"stress.?alternatives|SAM\b", "Stress Alternatives Model", "Addiction / substance use"),

    # ── Pain ─────────────────────────────────────────────────────────────────
    (r"von.?frey|mechanical.*sensitiv|mechanical.*threshold|mechanical.*allodynia",
     "Von Frey (mechanical sensitivity)", "Pain"),
    (r"hot.?plate|hot.plate", "Hot Plate Test", "Pain"),
    (r"tail.?flick|tail-flick", "Tail Flick Test", "Pain"),
    (r"hargreaves|plantar.?test|thermal.*sensitiv|thermal.*hypersensit",
     "Hargreaves / Plantar Test", "Pain"),
    (r"formalin.?test", "Formalin Test", "Pain"),
    (r"cold.?plate|acetone.*cold|cold.?sensitiv", "Cold Sensitivity Test", "Pain"),
    (r"mouse.?grimace|grimace.?scale|MGS\b", "Mouse Grimace Scale", "Pain"),
    (r"thermal.?place.?prefer", "Thermal Place Preference", "Pain"),
    (r"muscle.?withdrawal.?threshold|MWT\b", "Muscle Withdrawal Threshold", "Pain"),
    (r"sciatic|neuropathic.?pain|nerve.?ligation|CFA\b|freund.*adjuvant|inflammat.*pain",
     "Neuropathic / Inflammatory Pain Model", "Pain"),
    (r"opioid.?induced.?hyperalges|OIH\b", "Opioid-Induced Hyperalgesia", "Pain"),
    (r"tail.?pinch|mechanical.?nociception|nociceptive",
     "Nociception Test", "Pain"),
    (r"scratch.*pruritus|pruritus|itch", "Pruritus / Itch Test", "Pain"),
    (r"overt.?pain|flinch|writhing", "Overt Pain Behaviour", "Pain"),

    # ── Sensorimotor / Neural ────────────────────────────────────────────────
    (r"prepulse.?inhibit|PPI\b|startle.*prepulse|acoustic.?startle",
     "Prepulse Inhibition (PPI)", "Sensorimotor"),
    (r"sensorimotor.?respons|visual.?placing|acoustic.?respons|tactile.?respons",
     "Sensorimotor Battery", "Sensorimotor"),
    (r"auditory.?oddball|neural.?record|local.?field.?potential|LFP",
     "Neural Recording / Oddball", "Sensorimotor"),
    (r"electro.*encephal|polysomnograph|sleep.?record|EEG\b|sleep.?wake",
     "EEG / Sleep Recording", "Sensorimotor"),
    (r"auditory.?cortex|active.?vision|free.?arena.*vision|visual.?response",
     "Sensory Cortex Imaging / Physiology", "Sensorimotor"),
    (r"MK.?801.*hyperact|phencyclidine.*locomot|PCP.*locomot",
     "MK-801 / PCP Hyperactivity", "Sensorimotor"),

    # ── Endocrine / Physiological ────────────────────────────────────────────
    (r"cardiorespir|blood.?pressure|heart.?rate|tail.?cuff",
     "Cardiovascular Monitoring", "Physiological"),
    (r"body.?weight|food.?intake|home.?cage.*eat|feeding.*home",
     "Body Weight / Food Intake", "Physiological"),
    (r"plethysmograph|airway.*hyperrespons|AHR\b",
     "Plethysmography / Airway", "Physiological"),
    (r"sleep.*record|polysomnograph", "Sleep Recording", "Physiological"),
    (r"hexobarbital.*sleep|sleeping.?time", "Sleep (hexobarbital)", "Physiological"),
    (r"rectal.*temp", "Rectal Temperature", "Physiological"),

    # ── Misc / general ───────────────────────────────────────────────────────
    (r"general.?pharmac|gross.?behav|overt.?behav|spontaneous.?behav",
     "General Behavioural Observation", "Miscellaneous"),
    (r"tic.?like|tic", "Tic-like Behaviour", "Miscellaneous"),
    (r"grooming", "Grooming", "Miscellaneous"),
    (r"whisker.*texture|texture.?discriminat", "Whisker / Texture Discrimination", "Miscellaneous"),
    (r"treadmill.*spatial|spatial.?encod", "Spatial Encoding (Treadmill)", "Miscellaneous"),
    (r"bederson|neurologic.*test|neurologic.*score", "Neurological Score", "Miscellaneous"),
    (r"pawson|behavioural.?pattern.?monitor|BPM\b",
     "Behavioural Pattern Monitor (BPM)", "Miscellaneous"),
    (r"apnea|respir", "Respiratory Monitoring", "Miscellaneous"),
    (r"self.?groomin", "Self-Grooming", "Miscellaneous"),
]


def normalise(raw: str) -> tuple[str, str]:
    """Return (canonical_name, category) for a raw assay string."""
    for pat, canonical, category in RULES:
        if re.search(pat, raw, re.IGNORECASE):
            return canonical, category
    return raw.strip(), "Miscellaneous"


# ── Build ────────────────────────────────────────────────────────────────────

def assays_for(consensus: dict) -> list[dict]:
    """Canonical assay rows for one consensus JSON (one row per canonical)."""
    seen: set[str] = set()
    rows = []
    for assay in (consensus.get("assays") or []):
        raw = (assay.get("assay_name") or "").strip()
        if not raw:
            continue
        canonical, category = normalise(raw)
        if canonical in seen:
            continue
        seen.add(canonical)
        rows.append({"canonical": canonical, "category": category, "raw": raw})
    return rows


def catalog_from(paper_assays: dict[str, list[dict]],
                 base: list[dict] | None = None) -> list[dict]:
    """Aggregate per-paper rows into the catalog, sorted by count (stable)."""
    catalog: dict[str, dict] = {e["canonical"]: e for e in (base or [])}
    for stem, rows in paper_assays.items():
        for r in rows:
            if r["canonical"] not in catalog:
                catalog[r["canonical"]] = {"canonical": r["canonical"],
                                           "category": r["category"],
                                           "count": 0, "papers": []}
            catalog[r["canonical"]]["count"] += 1
            catalog[r["canonical"]]["papers"].append(stem)
    return sorted(catalog.values(), key=lambda x: -x["count"])


def rebuild(consensus_dir: Path) -> tuple[dict, list]:
    paper_assays: dict[str, list[dict]] = {}
    for f in sorted(consensus_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        paper_assays[f.stem] = assays_for(d)
    return paper_assays, catalog_from(paper_assays)


def add_papers(stems: list[str], consensus_dir: Path = CONSENSUS_DIR,
               out_paper: Path = OUT_PAPER, out_catalog: Path = OUT_CATALOG) -> list[str]:
    """Add or replace `stems` in the committed files; leave the rest untouched.

    Returns the stems actually written (those with a consensus JSON).
    """
    paper_assays = json.loads(out_paper.read_text()) if out_paper.exists() else {}
    catalog = json.loads(out_catalog.read_text()) if out_catalog.exists() else []
    nfc = lambda x: unicodedata.normalize("NFC", x)
    added: dict[str, list[dict]] = {}
    for stem in stems:
        f = consensus_dir / f"{stem}.json"
        if not f.exists():
            continue
        # Replacing a paper: take its old rows out of the catalog first.
        for key in [k for k in paper_assays if nfc(k) == nfc(stem)]:
            for r in paper_assays.pop(key):
                e = next((e for e in catalog if e["canonical"] == r["canonical"]), None)
                if e and key in e["papers"]:
                    e["papers"].remove(key)
                    e["count"] -= 1
        added[stem] = assays_for(json.loads(f.read_text()))
    catalog = [e for e in catalog if e["count"] > 0]
    paper_assays.update(added)
    catalog_list = catalog_from(added, base=catalog)
    out_paper.parent.mkdir(parents=True, exist_ok=True)
    out_paper.write_text(json.dumps(paper_assays, indent=2, ensure_ascii=False))
    out_catalog.write_text(json.dumps(catalog_list, indent=2, ensure_ascii=False))
    return list(added)


def print_summary(paper_assays: dict, catalog_list: list) -> None:
    from collections import Counter
    cat_counts = Counter(e["category"] for e in catalog_list)
    print(f"Papers processed:      {len(paper_assays)}")
    print(f"Canonical assays:      {len(catalog_list)}")
    print(f"\nCanonical assays by category:")
    for cat, n in sorted(cat_counts.items()):
        print(f"  {cat:35s}  {n:3d} assays")

    print(f"\nTop 30 canonical assays by paper count:")
    for e in catalog_list[:30]:
        print(f"  {e['count']:4d}  [{e['category']:30s}]  {e['canonical']}")

    # Warn about any raw names that hit the catch-all
    catchall = [e for e in catalog_list if e["category"] == "Miscellaneous" and e["count"] >= 2]
    if catchall:
        print(f"\nMiscellaneous (≥2 papers) — may need a rule:")
        for e in catchall:
            print(f"  {e['count']:3d}  {e['canonical']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--add", nargs="+", metavar="STEM",
                      help="add/replace these papers, keep everything else as published")
    mode.add_argument("--rebuild", action="store_true",
                      help="rebuild from every consensus JSON (changes published numbers)")
    args = ap.parse_args()

    if args.rebuild:
        paper_assays, catalog_list = rebuild(CONSENSUS_DIR)
        OUT_PAPER.parent.mkdir(parents=True, exist_ok=True)
        OUT_PAPER.write_text(json.dumps(paper_assays, indent=2, ensure_ascii=False))
        OUT_CATALOG.write_text(json.dumps(catalog_list, indent=2, ensure_ascii=False))
        print_summary(paper_assays, catalog_list)
    else:
        written = add_papers(args.add)
        print(f"Added/replaced {len(written)} paper(s): {', '.join(written) or '-'}")
        missing = sorted(set(args.add) - set(written))
        if missing:
            print(f"No consensus JSON for: {', '.join(missing)}")


if __name__ == "__main__":
    main()

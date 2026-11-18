"""
Automated scoring pipeline for systematic review of psychedelic animal studies.

Scores each study's behavioural assays on three dimensions using Gemini Flash
with a decomposed checklist approach. Runs multiple times for consensus.

Usage:
    # Score all PDFs in a directory (default: gemini-2.5-flash-lite, ~$0.03/paper)
    uv run python score_studies.py --pdf-dir ./pdfs --output-dir ./results

    # Score a single PDF (useful for testing/debugging the prompt)
    uv run python score_studies.py --pdf ./pdfs/Smith2023.pdf --output-dir ./results --runs 1

    # Use 2.5 Flash with thinking disabled (better quality, ~$0.10/paper)
    uv run python score_studies.py --pdf-dir ./pdfs --output-dir ./results --model gemini-2.5-flash --thinking-budget 0

    # Resume an interrupted run (skips already-scored studies)
    uv run python score_studies.py --pdf-dir ./pdfs --output-dir ./results --resume

    # Parallel scoring with 4 workers (processes 4 studies concurrently)
    uv run python score_studies.py --pdf-dir ./pdfs --output-dir ./results --workers 4

Setup:
    export GEMINI_API_KEY="your-api-key-here"  # https://aistudio.google.com/apikey
"""

import argparse
import json
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
import pandas as pd

from provider import Provider, ProviderError, make_provider

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL_NAME = "gemini-2.5-flash-lite"  # cheapest: $0.10/$0.40 per 1M tokens, no thinking
NUM_RUNS = 3
TEMPERATURE = 0.0
THINKING_BUDGET = 0  # 0 = disable thinking (saves ~$1/call on 2.5 Flash); ignored on Lite/2.0
MAX_RETRIES = 3
RETRY_DELAY = 10  # seconds
RATE_LIMIT_DELAY = 4  # seconds between API calls
NUM_WORKERS = 1  # default: sequential (set via --workers)

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


# Global rate limiter — initialized in main() based on --workers
_rate_limiter: RateLimiter | None = None

# ---------------------------------------------------------------------------
# Scoring prompt — this is the core of the pipeline
# ---------------------------------------------------------------------------

SCORING_PROMPT = r"""
You are a scientific research assistant scoring animal behavioural studies
for a systematic review of psychedelic research in rodents.

Read the attached research paper carefully. Your task:
1. Identify every distinct behavioural assay where a psychedelic compound
   (psilocybin, LSD, DMT, DOI, 5-MeO-DMT, mescaline, or analogues) was
   administered to rodents (mice or rats).
2. For each assay, extract textual evidence for each checklist item below.
3. Score each item strictly according to the definitions provided.

An "assay" = a distinct BEHAVIOURAL test conducted in a specific apparatus
with a specific protocol. Running OFT on day 1 and day 7 = 1 assay tested
twice. Running OFT + EPM = 2 separate assays. If a study uses the same
apparatus but tests different behavioural domains (e.g., locomotion in OFT
AND social interaction in a 3-chamber), those are 2 assays. Include control
assays (e.g., OFT for locomotion) if a psychedelic was administered.

NOT assays (DO NOT SCORE these — skip entirely, do not include in output):
- Neural recordings: electrophysiology, in vivo electrophysiology,
  in vivo calcium imaging, two-photon imaging, fiber photometry, EEG, LFP,
  single-unit recording, multi-unit recording — even if done in
  awake/behaving animals. These measure NEURAL ACTIVITY, not behaviour.
- Ex vivo / in vitro work: slice physiology, immunohistochemistry, PCR,
  ligand binding assays, thermophoresis, luciferase complementation,
  protein interaction assays (PCA), Western blot, ELISA.
- Histological / anatomical endpoints: BrdU neuronal survival, cell
  counting, neurogenesis assays, dendritic spine analysis, c-Fos staining.
- Imaging-only readouts where the animal does not perform a behavioural
  task: intrinsic optical imaging (e.g., ocular dominance plasticity
  measured via cranial windows), PET, fMRI (unless combined with a
  behavioural task — in that case score only the behavioural component).
- Purely physiological measures: body weight, temperature, blood sampling.
Only score tests where the PRIMARY OUTCOME is the animal's behaviour.
If a behavioural test is combined with neural recording (e.g., DSI with
optogenetic manipulation + electrophysiology), score the BEHAVIOURAL test
but not the electrophysiology component separately.

ASSAY IDENTITY — READ CAREFULLY: An "assay" is defined by the BEHAVIOURAL
PARADIGM (apparatus + protocol + what the animal does + what is measured),
NOT by the experimental manipulation applied to groups of animals. A single
behavioural paradigm repeated under different drug, dose, genetic, circuit,
timepoint, or cohort conditions is STILL ONE ASSAY. Collapse all such
variants into a single assay entry.

ONE ASSAY — these are NOT separate assays even though the paper may present
them as different "experiments":
- Same test under different drug doses (e.g., psilocybin 1 mg/kg vs. 3 mg/kg
  in the open field) = 1 assay
- Same test under different routes of administration (systemic vs.
  intracerebral infusion) = 1 assay. Example: contextual fear extinction
  with systemic AYA + infralimbic infusion of MDL-11,939 + infralimbic
  infusion of WAY-100635 = 1 assay (all measure freezing during extinction).
- Same test with different pharmacological antagonists/agonists added =
  1 assay (e.g., "OFT with ketanserin", "OFT with WAY-100635" = 1 OFT)
- Same test under optogenetic / chemogenetic / DREADD manipulations
  (laser ON vs. OFF, reactivation vs. no reactivation, with/without
  antagonist) = 1 assay
- Same test in wildtype vs. conditional knockout / transgenic animals =
  1 assay
- Same test at acute vs. repeated/chronic dosing regimen = 1 assay
- Same test at different timepoints (day 1 vs. day 7, pre- vs.
  post-treatment) = 1 assay (multiple recording sessions; score D1/D3
  accordingly but do NOT create separate assay entries)
- Same test in different stress-model cohorts (e.g., CRS vs. LPS
  model animals both run through FST) = 1 assay
- Different phases of the same learning paradigm (acquisition,
  extinction, reinstatement, recall, re-test) = 1 assay. Examples:
    * CPP acquisition + extinction + reinstatement = 1 CPP assay
    * Fear conditioning training + recall + extinction + retest = 1 fear
      conditioning assay (score multiple recording days)
    * Operant self-administration acquisition + extinction + reinstatement
      = 1 operant SA assay
- Same task with different stimulus parameters (e.g., 5-CSRTT with
  standard ITI vs. extended ITI; CPT with different stimulus durations) =
  1 assay
- Same home-cage food/water/locomotor monitoring repeated across genotype
  or drug-regimen cohorts = 1 assay

SEPARATE ASSAYS — these ARE distinct assays:
- Different apparatuses or paradigms testing different behavioural
  constructs (OFT vs. EPM, FST vs. TST, NOR vs. Y-maze) = separate
- Same apparatus used for different behavioural domains (e.g., 3-chamber
  for social preference AND for object novelty) = separate
- Same test in different SPECIES (mouse vs. rat) = separate assays
  (species is a meaningful biological variable, unlike strain)

DECISION RULE: If the animal is doing the SAME behaviour in the SAME
apparatus with the SAME measured outcomes, and the only difference is
WHAT was done to the animal (drug, infusion, light, genetic) or WHEN
(timepoint), it is ONE assay. Create a single entry; describe the range
of manipulations briefly in `assay_description`.

CRITICAL RULES:
- Only score assays where a psychedelic compound was administered to rodents.
- Score each item based on the BEHAVIOURAL RECORDING SESSION ITSELF (when
  data is actively being collected), NOT the conditioning, training, housing,
  or drug administration phases of the protocol. For example, in conditioned
  place preference, score based on what happens during the test trial, not
  during the conditioning days.
- Base scores ONLY on what is explicitly stated in the paper (including any
  supplementary methods if visible).
- If information is not reported, score the item as 0 and set confidence
  to "low" and evidence to "not reported". NEVER infer, guess, or estimate
  based on what is "typical", "implied", or "usually" the case for an assay.
  If a specific value (e.g., session duration) is not explicitly stated as
  a number in the paper, score it as 0 with confidence "low".
- If the item is definitionally absent (e.g., bedding in an elevated plus
  maze), score 0, set confidence to "high", and note "definitionally absent"
  in evidence.
- Quote or closely paraphrase the relevant text as evidence (1-2 sentences
  max per item). Do not fabricate quotes.

============================================================
CHECKLIST DEFINITIONS
============================================================

--- DIMENSION 1: BEHAVIOURAL COMPLEXITY (8 items, raw max = 11) ---

B1. Number of distinct behavioural measures
    Response: 1 / 2-3 / 4-6 / 7+
    Points:   0 / 1   / 2   / 3
    Count unique behavioural variables explicitly reported as results.
    Examples: total distance = 1, time in centre = 1, grooming bouts = 1,
    USV call rate = 1. Sub-scores of the same composite each count
    separately (e.g., FST immobility + swimming + climbing = 3 measures).
    A preference score derived from time in two zones = 1 measure (not 2).

B2. Temporal dynamics analysed
    Response: No / Yes    Points: 0 / 1
    Does the study analyse how behaviour changes WITHIN a single recording
    session over time? E.g., time-course plots binned within a session,
    habituation curves, minute-by-minute analysis.
    NO: a single total or average over the entire session.
    NO: comparing a pre-test score to a post-test score (that is a
    between-session comparison, not within-session temporal dynamics).

B3. Sequential or transitional structure
    Response: No / Yes    Points: 0 / 1
    Does the study analyse transitions between behaviours, behavioural
    sequences, Markov chains, bout structure, or microstructure?
    E.g., grooming syntax, social interaction sequences.

B4. Ethological behaviours included
    Response: No / Yes    Points: 0 / 1
    Does the assay DIRECTLY MEASURE behaviours from the species' natural
    repertoire during the recording session?
    Yes: grooming patterns, social investigation (sniffing, following,
    allogrooming), nesting, burrowing, digging, USVs, scent marking,
    natural exploratory behaviour scored as distinct acts.
    No: head-twitch response (HTR — also called wet-dog shake / WDS, especially
        in older rat literature; treat WDS and HTR as the SAME assay),
        PPI startle magnitude, FST immobility,
    conditioned freezing, zone preference time (time in zone is a spatial
    measure, not an ethological behaviour), locomotor distance.
    A study measuring BOTH natural and artificial behaviours = Yes.

B5. Social component
    Response: None / Social construct, individual testing / Restricted social interaction / Free social interaction
    Points:   0    / 1                                    / 2                            / 3
    Score 0 (None): Assay does not target social behaviour or cognition.
    E.g., OFT locomotion, EPM anxiety, HTR, FST, PPI.
    Score 1 (Social construct, individual testing): Assay explicitly
    targets social cognition, reward, or memory, but the focal animal
    is tested ALONE during recording. The social component is in the
    experimental design (e.g., conditioning with cage mates) rather
    than in the test session itself.
    E.g., social conditioned place preference (sCPP/CPP with social
    conditioning), social recognition memory tested solo, social
    transmission of food preference.
    Score 2 (Restricted social interaction): A live conspecific is
    physically present during recording but interaction is constrained
    by a barrier (wire cup, mesh divider, perforated wall). The focal
    animal can investigate (sniff, approach) but cannot freely interact.
    E.g., 3-chamber social preference (stimulus mouse under cup),
    social investigation through mesh, partition tests.
    Score 3 (Free social interaction): Conspecifics are co-present
    without barriers and can freely interact. Interaction is directly
    quantified. E.g., resident-intruder, free dyadic interaction,
    group social monitoring, direct social interaction test (DSI)
    with freely moving partners.
    NO to any score >0: housing socially without measuring social
    behaviour or a social construct.

B6. Cognitive or learned component
    Response: No / Yes    Points: 0 / 1
    Does the assay require learning, memory, or cognitive flexibility?
    Yes: fear conditioning, Morris water maze, novel object recognition,
    reversal learning, attentional set-shifting, operant tasks,
    conditioned place preference (requires learned association).
    No: anxiety tests based on innate avoidance (EPM, OFT thigmotaxis).

B7. Automated behavioural classification
    Response: No / Yes    Points: 0 / 1
    Is BEHAVIOUR classified using computational methods that go BEYOND
    tracking the animal's position (x,y coordinates)?
    DECISION PROCESS — follow these steps in order:
    1. Identify the software/tool used for behavioural data collection.
    2. Check the tool name against the SCORE-0 list below.
    3. If the tool appears on the SCORE-0 list, score 0 — NO EXCEPTIONS.
    SCORE 0 — these are position-tracking or beam-break systems, NOT
    behavioural classifiers. Score 0 even though they "analyze" data:
    - EthoVision (any version, including EthoVision XT) → SCORE 0
    - ANY-maze → SCORE 0
    - Med Associates (Activity Monitor, any product) → SCORE 0
    - CleverSys TopScan → SCORE 0
    - ANY infrared beam-break system → SCORE 0
    - Simple centroid/centre-of-mass video tracking → SCORE 0
    - Spike sorting, calcium event detection → SCORE 0 (neural)
    SCORE 1 ONLY FOR these specific tool categories:
    - Pose estimation: DeepLabCut, SLEAP, maDLC
    - Behavioural syllables: MoSeq, B-SOiD, SimBA
    - Supervised ML classifiers that label discrete behavioural states
      (e.g., "grooming", "rearing", "fighting") from video
    When in doubt, score 0.

B8. Multivariate behavioural analysis
    Response: No / Yes    Points: 0 / 1
    Does the study apply dimensionality reduction or multivariate
    statistics across behavioural features? Yes: PCA, UMAP/t-SNE,
    factor analysis, cluster analysis of behavioural profiles.
    No: reporting multiple separate univariate tests.

--- DIMENSION 2: ENVIRONMENTAL COMPLEXITY (8 items, raw max = 11) ---

Score ALL environmental items based on conditions during the RECORDING
SESSION (when behavioural data is being collected), not during housing,
conditioning, or drug administration phases.

E1. Environment type
    Response: Standard apparatus / Home cage / Enriched arena / Semi-naturalistic
    Points:   0                  / 1         / 2              / 3
    Standard: open field, EPM, T-maze, Y-maze, operant chamber, startle
    chamber, FST cylinder, light-dark box, CPP chamber, 3-chamber.
    Home cage: the animal's own housing cage as testing environment.
    Enriched arena: larger arena or modified cage with added features
    beyond the standard apparatus.
    Semi-naturalistic: Visible Burrow System, IntelliCage, large
    multi-compartment colony setups, outdoor enclosures.

E2. Shelter or refuge available
    Response: No / Yes    Points: 0 / 1
    Can the animal retreat to an enclosed/covered space DURING THE
    RECORDING SESSION? Nest box, igloo, tunnel, dark chamber by choice.
    SCORE 0 FOR: EPM closed arms — these are part of the apparatus
    design, not a shelter. The animal is exposed on all sides except
    walls; it is NOT an enclosed refuge.
    SCORE 1 FOR: dark compartment in light-dark box (fully enclosed).

E3. Bedding or substrate present
    Response: No / Yes    Points: 0 / 1
    Is bedding or floor covering present in the testing apparatus during
    recording? Bare plastic/metal/acrylic floor = No. Bedding used as
    a conditioning cue in CPP = Yes (it is physically present).

E4. Nesting material provided
    Response: No / Yes    Points: 0 / 1
    Is nesting material (shredded paper, cotton, nestlets) available in
    the testing apparatus during recording?

E5. Enrichment objects present
    Response: No / Yes    Points: 0 / 1
    Objects providing environmental enrichment in the testing apparatus
    during recording (tunnels, running wheels, chew toys, wooden blocks).
    Novel objects used AS the test (NOR) do not count.

E6. Spatial complexity
    Response: Single open space / Multiple zones or compartments
    Points:   0                 / 1
    Does the testing apparatus have physically distinct areas separated
    by walls, dividers, or level changes?
    SCORE 0: open field (even with virtual zones), FST cylinder.
    SCORE 0: EPM — the arms are open-ended extensions of a central
    platform, not distinct enclosed compartments. Do NOT score EPM as
    having multiple zones.
    SCORE 1: 3-chamber apparatus, light-dark box (two enclosed
    compartments), CPP chamber with physical partition, multi-level
    or burrow systems.

E7. Social context during testing
    Response: Alone / Stimulus behind barrier / Free social group
    Points:   0     / 1                       / 2
    Is a live conspecific physically present IN THE TESTING APPARATUS
    during the recording session when behavioural data is collected?
    Alone: focal animal is the only animal in the apparatus during
    recording. This includes CPP/sCPP test trials where the animal
    chooses between conditioned cues by itself — even though cage mates
    were present during earlier conditioning days, the TEST TRIAL is
    done alone. Barrier: stimulus animal separated by mesh/divider/wire
    cup during recording. Free: >=2 animals interact without physical
    separation during recording.
    KEY: conditioning/training phases do NOT count. Only score based on
    who is present when behavioural data is being recorded.

E8. Food and water accessible
    Response: No / Yes    Points: 0 / 1
    Can the animal access food/water INSIDE THE TESTING APPARATUS during
    the recording session? Do not count food/water in the home cage if
    the test takes place in a separate apparatus. Most short standard
    tests = No. Home-cage monitoring and continuous recording = Yes.

--- DIMENSION 3: RECORDING DURATION (6 items, raw max = 11) ---

"Recording" = any session where behavioural data is collected and analysed,
including baseline/pre-conditioning trials if their data is reported.

D1. Recording continuity
    Response: Single session / Multiple discrete sessions / Continuous monitoring
    Points:   0              / 1                          / 2
    Single: one recording bout on one day. Multiple: >=2 separate
    recording sessions where behavioural data is collected and reported
    (e.g., pre-test trial + post-test trial on different days, or
    repeated test sessions across days). In CPP/sCPP: if BOTH the
    pre-conditioning preference trial AND the post-conditioning
    preference trial are recorded and their data is reported/compared,
    that counts as Multiple (2 sessions). Continuous: uninterrupted
    recording for >=6 hours.

D2. Longest single session duration
    Points:   0       / 1          / 2           / 3
    Category: <15 min / 15–60 min  / 61 min–6 h  / >6 h
    Duration of the longest individual recording bout.
    BOUNDARIES (use these exact cutoffs):
    - Less than 15 minutes (e.g., 5 min, 10 min) → score 0
    - 15 to 60 minutes inclusive (e.g., 15 min, 20 min, 30 min, 45 min, 60 min) → score 1
    - More than 60 minutes up to 6 hours (e.g., 90 min, 2 h, 4 h) → score 2
    - More than 6 hours → score 3

D3. Total number of recording days for THIS assay
    Response: 1 / 2-7 / 8-14 / 15+
    Points:   0 / 1   / 2    / 3
    Distinct calendar days on which behavioural data was collected
    FOR THIS SPECIFIC ASSAY — not the total number of days in the
    study or the number of days other assays were run.
    Count only days where this particular test was administered and
    behavioural data was recorded (including baseline/pre-conditioning
    days if data is reported for this assay).
    Example: CPP with pre-conditioning trial on day 1 and post-
    conditioning trial on day 4 = 2 recording days.
    Example: A study runs OFT on day 1 and FST on day 3 — the OFT
    has 1 recording day, the FST has 1 recording day. Do NOT count
    the FST day as a recording day for the OFT.
    Example: Fear conditioning with training on day 1 and extinction
    test on day 2 = 2 recording days for that assay.

D4. Pre-drug baseline recorded
    Response: No / Yes    Points: 0 / 1
    Behavioural recording BEFORE drug administration in the same
    assay/environment, with data reported or used in analysis.
    Habituation to the apparatus without data collection = No.
    CPP pre-conditioning preference trial = Yes.

D5. Post-acute follow-up
    Response: No / Yes    Points: 0 / 1
    Behavioural recording >=24 hours after last drug administration.

D6. Circadian-scale coverage
    Response: No / Yes    Points: 0 / 1
    Does any single recording session span >=6 hours?

============================================================
DESCRIPTIVE METADATA — HOUSING & EXPERIMENTAL CONDITIONS
============================================================

These fields capture animal husbandry and protocol context that does NOT
contribute to B/E/D dimension scores. Each item has a `value`, `evidence`
quote, and `confidence`.

CRITICAL — DISTINGUISHING "NO" (NOT DONE) FROM "NOT_REPORTED" (NOT
DESCRIBED):

  - "no" / "ad libitum" / "no restriction" / "freely moving"
        → use ONLY when the paper EXPLICITLY states the absence.
          The paper says, in words, that the thing did not happen.
          Examples that warrant "no":
            * "Animals were not handled prior to testing."
            * "Mice were single-housed throughout the experiment."
            * "Animals were maintained on a standard 12:12 light/dark
               cycle (lights on at 07:00)."  → not_flipped: no
            * "Food and water were available ad libitum throughout."
               → food_restriction: no, water_restriction: no
            * "The animal moved freely within the open field."
               → setup_restrain: no
            * "No environmental enrichment was provided."
               → enrichment_housing: no

  - "not_reported" (lowercase, with underscore)
        → use when the paper is SILENT on the topic — it does not say
          the thing happened, and it does not say it didn't.
          DO NOT INFER from what is typical for the apparatus, the
          species, the lab, or the assay. If the methods section does
          not mention handling, score handling as "not_reported", NOT
          "no", even though most labs probably skip it.
          Examples that warrant "not_reported":
            * The methods section never mentions handling.
            * Light cycle direction is never stated.
            * The paper describes the home cage but does not say
              whether enrichment items were present.

  - When in doubt, prefer "not_reported". The default for any field
    the paper does not address is "not_reported", with confidence "low".
    Use confidence "high" with "not_reported" only when the paper
    discusses related topics (e.g., light cycle is stated but reversal
    is not) — i.e., when the silence is informative.

Note that the standard absence claim ("ad libitum food/water") is so
common in rodent methods that food/water_restriction = "no" is the
typical case for short standard tests; you only need a single explicit
mention. By contrast, handling, light-cycle direction, and home-cage
enrichment are routinely omitted, so "not_reported" will be common for
those.

--- SUBJECT METADATA (study-level) ---

SEX (single block at the top level)
    Values: male / female / both / not_reported
    Reports which sex(es) of animal were used as EXPERIMENTAL subjects.
    Treat stimulus animals (e.g., cage-mates in 3-chamber social tasks,
    aggressor mice in resident-intruder paradigms) as NOT relevant — score
    based on the subjects whose behaviour was scored / analysed.
      both: paper explicitly reports using both sexes ("21 male and 21
            female"; "balanced for sex"; "sex as a factor").
      male: only male subjects (most common in older psychedelic studies).
      female: only female subjects.
      not_reported: paper never states the sex of subjects. Strain names
            (e.g., "C57BL/6J mice") do NOT imply sex — score not_reported.
    Also fill n_male / n_female when explicit n's are given; otherwise null.

DOSING (study-level list; one entry PER COMPOUND tested)
    Capture every psychedelic / drug COMPOUND administered to animals
    in the behavioural experiments. Create ONE entry per compound, even
    if the same dose schedule is shared — so a study testing LSD and
    DOI yields two entries. Vehicle-only controls do NOT get an entry.

    Per compound:
      - compound: canonical name (e.g. "Psilocybin", "LSD", "DOI",
        "5-MeO-DMT", "DMT", "Ibogaine", "Mescaline", "Ketamine",
        "MDMA", "TBG", "2,5-DMT", "AAZ-A-154", "Lisuride"). Use the
        FORM ACTUALLY ADMINISTERED — if a study gave psilocybin and
        measured psilocin in plasma, the compound is "Psilocybin".
        If the study gave psilocin directly, the compound is "Psilocin".

      - doses_mg_per_kg: a JSON array of distinct numeric doses tested
        for this compound, normalised to mg/kg. If only μg/kg are
        given, divide by 1000. If only μg or mg totals are given
        (without /kg) AND body weight is reported, convert. Otherwise
        leave the array empty and put the raw values in doses_raw.

      - doses_raw: the exact quoted text listing the dose values,
        verbatim from the paper (e.g. "0.1, 0.3, 1.0 mg/kg" or
        "1 and 10 mg/kg, i.p.").

      - vehicle: saline / water / DMSO / PBS / ethanol / cyclodextrin
        / cremophor / other / not_reported. If a compound is dissolved
        in a mix (e.g. "saline with 5% DMSO"), choose the primary
        solvent listed first; mention the additive in evidence.

      - route: i.p. / i.v. / i.c.v. / s.c. / p.o. / i.n. / i.m. /
        drinking_water / food / multiple / other / not_reported. If
        multiple routes were used for the SAME compound across
        experiments, use "multiple" and clarify in evidence.

      - schedule:
          acute       — single dose (or single per animal, even across
                        groups)
          repeated    — 2–7 doses, typically over <=7 days
          chronic     — >=8 doses OR dosing for >7 days
          microdosing — explicit "microdose" framing (typically
                        sub-perceptual, <=1/10 of standard psychedelic
                        dose, repeated)
          not_reported

    Examples:
      "C57BL/6J mice received psilocybin (1 mg/kg, i.p., dissolved in
      saline) 30 min before testing"
        → [{compound: "Psilocybin", doses_mg_per_kg: [1.0],
            doses_raw: "1 mg/kg, i.p.", vehicle: "saline", route: "i.p.",
            schedule: "acute", evidence: <quote>}]

      "Rats received LSD (5, 15, 30 µg/kg, i.p.) once per day for 7 days"
        → [{compound: "LSD", doses_mg_per_kg: [0.005, 0.015, 0.030],
            doses_raw: "5, 15, 30 µg/kg, i.p.", vehicle: "not_reported",
            route: "i.p.", schedule: "repeated", evidence: <quote>}]

--- HOUSING CONDITIONS (study-level, single block; constant across assays) ---

H1. handling
    Values: yes / no / not_reported
    Were animals DELIBERATELY HANDLED by experimenters before behavioural
    testing as a habituation protocol (e.g., "handled 5 min/day for 3 days")?
    yes: explicit handling protocol described.
    no: paper EXPLICITLY states animals were not handled.
    not_reported: paper does not mention handling. Manipulation only for
        injection or cage transfer is NOT a handling protocol — but if
        the paper is silent on whether any handling beyond that occurred,
        score "not_reported", not "no".

H2. group_housing
    Values: yes / no / not_reported
    Were animals group-housed in their home cage during the experimental
    period (>=2 per cage)?
    yes: paper says animals were group-housed / housed N per cage with
        N >= 2 / housed in pairs / socially housed.
    no: paper EXPLICITLY says single-housed / individually housed /
        socially isolated. If the paper reports a switch (e.g., group-
        housed initially then isolated for testing), report the housing
        DURING behavioural testing and note the change in `evidence`.
    not_reported: paper does not state cage density / housing arrangement.

H3. day_night_flipped
    Values: yes / no / not_reported
    Was a REVERSED light/dark cycle used (testing during the animals'
    active/dark phase under reversed lighting)?
    yes: explicit reverse-cycle housing (e.g., "reverse 12:12 cycle,
        lights off at 07:00; testing during the dark phase").
    no: paper EXPLICITLY describes a standard (non-reversed) light cycle
        (e.g., "standard 12:12 cycle, lights on at 07:00") OR explicitly
        states testing was done during the light phase under standard
        lighting.
    not_reported: paper does not state the direction of the light cycle.
        A bare mention of "12:12 light/dark cycle" without specifying
        which phase corresponds to testing or what time lights came
        on/off is "not_reported" for direction.

H4. enrichment_housing
    Values: yes / no / not_reported
    Was environmental enrichment provided in the HOME CAGE (nesting
    material, tunnels, chew toys, running wheels, shelter)? Standard
    bedding alone does not count as enrichment.
    yes: explicit mention of enrichment items in the home cage.
    no: paper EXPLICITLY says no enrichment was provided / describes
        "standard housing without enrichment".
    not_reported: paper does not address home-cage enrichment. (Most
        common case — most papers omit this.)

--- EXPERIMENTAL CONDITIONS (per-assay; can vary across assays in one paper) ---

C1. application_type
    Values: i.p. / i.v. / i.c.v. / s.c. / p.o. / i.n. / i.m. / multiple / other / not_reported
    Route of psychedelic administration FOR THIS ASSAY. If multiple routes
    are used in this assay (e.g., systemic + intracerebral infusion
    combination), use "multiple" and list them in `evidence`. If a route
    is used in this assay that is none of the listed standard routes, use
    "other" and name it in `evidence`. Use "not_reported" only if the
    paper does not state the route at all (rare).

C2. setup_habituation
    Values: yes / no / not_reported
    Was the animal habituated to the TESTING APPARATUS before the recording
    began (a separate exposure before the test trial, with no data
    collection)? E.g., "mice were placed in the OFT for 30 min the day
    before the test", or "habituated to the experimenter's hand for 3 days".
    yes: explicit pre-test apparatus exposure described.
    no: paper EXPLICITLY states no habituation was performed (e.g.,
        "animals were placed directly into the apparatus without prior
        habituation").
    not_reported: paper is silent on habituation to the apparatus.
    DO NOT count cage-room acclimation alone (transfer to the testing
    room without apparatus exposure) — that is room habituation, not
    setup habituation. Acclimation to the apparatus during the test
    session itself is NOT setup_habituation either.

C3. setup_restrain
    Values: yes / no / not_reported
    Was the animal PHYSICALLY RESTRAINED during the recording session
    (i.e., while behavioural data is actively being collected)?
    yes: head-fixed, body-restrained, holder-immobilized, tail-suspended,
        FST cylinder, PPI startle chambers with body-restraint tubes.
    no: paper describes the animal as freely moving in the apparatus,
        OR the apparatus is one in which animals are by definition free
        to move (OFT, EPM, 3-chamber, light-dark box, etc.) and no
        restraint is mentioned. (Restraint is typically explicit when
        used; absence in a free-movement apparatus is informative.)
    not_reported: only when the apparatus is ambiguous about restraint
        AND the paper does not specify (rare).
    DO NOT count brief restraint required to ADMINISTER the drug (e.g.,
    manual immobilization for an i.p./s.c./i.v. injection or oral gavage).
    Route of administration is already captured in `application_type`;
    this field only concerns restraint during the recording session itself.

C4. food_restriction
    Values: no / before / during / not_reported
    Did the animal lack access to food during the experimental recording
    session? This captures whether the animal had food in front of it
    while the test was happening, NOT chronic body-weight-maintenance
    protocols (those are part of the experimental design and would be
    obvious from context).
    - during: food was NOT accessible to the animal during the recording
      session. This is the default for most standard testing apparatus
      (OFT, EPM, FST, HTR, MBT, CPP, light-dark box, etc.) where food
      is not placed in the testing chamber. The animal does not need to
      be hungry — the criterion is simply whether food was reachable
      during the recording.
    - before: the animal was deliberately fasted/restricted in the
      period preceding the test (e.g., 12-24 h fast before NSF;
      pre-conditioning weight reduction before operant training). If
      both "before" and "during" apply (e.g., NSF: fasted before AND
      no food in the apparatus during the latency-to-feed window
      itself, even though food is the target), prefer "before".
    - no: food was accessible to the animal throughout the recording
      session. Examples: home-cage continuous monitoring (animal can
      reach its hopper); semi-naturalistic apparatus with food; food-
      reward operant tasks where pellets/sucrose are delivered during
      the session; foraging assays with chow available.
    - not_reported: the paper does not provide enough information to
      determine food access during the recording (rare).

C5. water_restriction
    Values: no / before / during / not_reported
    Same definitions as food_restriction but for water access. Standard
    short tests where the apparatus has no water bottle = "during"
    (water was not accessible during the test itself). Continuous
    home-cage drinking monitoring or two-bottle-choice in the home
    cage = "no" (water was accessible throughout).

C6. time_to_assay
    Minutes between the LAST drug administration and the START of
    recording for this assay. Reported as both a numeric value and
    a coarse bin (`value` is the bin string — kept under that name
    for compatibility with the other experimental_conditions fields;
    `value_minutes` is the numeric form):
        acute_0to2h        0–120 min
        early_2to24h       2–24 h
        short_term_1to7d   1–7 days
        long_term_over7d   >7 days
        multiple           same assay performed at >=2 distinct timepoints
                           (e.g. 30 min, 24 h, 7 d) — list all in evidence
        not_reported       timing of test relative to dose not stated
    For HTR/locomotor recorded continuously starting at injection,
    value_minutes = 0 and value = acute_0to2h.
    For repeated-dose / chronic studies, count from the LAST dose
    before testing (e.g. chronic 7-day dosing + test 24 h after final
    injection → value_minutes = 1440, value = early_2to24h).

============================================================
SAMPLE SIZE (per assay)
============================================================

For each assay, capture n's where reported:
  - n_total       — total animals contributing to this assay
                    summed across all dose/condition groups.
  - n_male, n_female — only fill when the paper breaks down n by sex
                    for this specific assay. Otherwise null.
  - n_per_group_min — smallest cell n (e.g. if Vehicle n=10, Low n=9,
                    High n=8 → 8). Drives the assay's statistical
                    power floor. If only one group, equals n_total.

If n is given only as a range (e.g. "n=6–8 per group"), use the lower
bound. If only the smallest group is mentioned, set n_per_group_min
and leave n_total null. Cite the evidence quote verbatim — figure
captions are the most reliable source.

============================================================
OUTCOMES (per assay)
============================================================

For each assay, provide a structured behavioural-result summary.
This is NOT scored (does not contribute to B/E/D totals) — its job
is to make the dataset interpretable for downstream meta-analysis.

  - summary (1–3 sentences, plain language)
        What was measured, how the psychedelic affected it, and any
        dose / sex / time-dependent modulation observed.
        Examples:
          "Acute 1 mg/kg psilocybin reduced immobility time in the
          FST by ~35% relative to vehicle in male mice (24 h after
          dosing). The effect was abolished by ketanserin pretreatment."
          "DOI dose-dependently increased head twitches (0.3 mg/kg:
          ~15 HTRs/30 min; 3 mg/kg: ~80 HTRs/30 min). No sex difference."
        Stay close to the paper's own framing — do not interpret beyond
        what the authors report.

  - statistics (verbatim string; empty if none reported)
        Concatenate the reported test statistics for this assay:
        F values, t values, p values, effect sizes, post-hoc comparisons,
        confidence intervals. Skip purely descriptive numbers (means,
        SEMs) — those belong in `summary` if relevant.
        Examples:
          "F(2,21)=5.32, p=0.013; vehicle vs. 1 mg/kg p=0.011 (Tukey)"
          "t(18)=3.14, p=0.006, Cohen's d = 1.40"

  - direction (one categorical label — the primary directional effect,
    ignoring modulators)
        increase   psychedelic significantly INCREASED the measure
                   at the highest tested dose (or the only dose, or
                   averaged across doses)
        decrease   psychedelic significantly DECREASED the measure
        no_effect  no significant effect of the psychedelic
        mixed      effects in OPPOSING directions across subgroups
                   (e.g. male up, female down) or across measures
                   within the same assay. Use this only when there
                   isn't a coherent primary direction.
        not_clear  paper does not state a clear directional result
                   (rare for a primary assay).

  - dose_dependent / sex_dependent / time_dependent
        These three modulator flags are ORTHOGONAL to `direction` —
        any combination is valid. Each takes one of:
            yes            modulator significantly affects the
                           magnitude (or presence) of the effect.
            no             tested as a factor but did not modulate.
            n/a            not testable from this assay (e.g.
                           dose_dependent = n/a when only one dose
                           was tested; sex_dependent = n/a when only
                           one sex was tested; time_dependent = n/a
                           unless time_to_assay = multiple).
            not_reported   tested as a factor but the paper does not
                           report whether it modulated.
        Examples:
          1 mg/kg psilocybin decreased immobility in males only,
          across 30-min and 24-h test windows:
            direction: decrease, dose_dependent: n/a (single dose),
            sex_dependent: yes, time_dependent: no
          DOI dose-dependently increased HTR with no sex difference
          at a single timepoint:
            direction: increase, dose_dependent: yes,
            sex_dependent: no, time_dependent: n/a

  - evidence
        Exact quote of the key result statement, e.g.
        "Psilocybin (1 mg/kg) significantly reduced immobility time
        (F(2,21) = 5.32, P = 0.013, Tukey post-hoc P = 0.011)."

============================================================
OUTPUT FORMAT
============================================================

Return ONLY valid JSON (no markdown fences, no commentary) with this
exact structure. Use the EXACT key names shown below (e.g., "D5_followup"
not "D5_post-acute_follow-up"). For each assay, include ALL items with
their scores, evidence quotes, and confidence levels.

{
  "study_id": "<FirstAuthorYear, e.g. Smith2023>",
  "doi": "<DOI if found, else null>",
  "species": "<mouse or rat>",
  "strain": "<strain if reported, else null>",
  "age": {
    "value": "<juvenile|adolescent|young_adult|adult|aged|mixed|not_reported>",
    "age_min_days": "<int or null — animal age at start of experiments, in days>",
    "age_max_days": "<int or null — upper end of age range, equal to min if single age>",
    "evidence": "<exact quote with the age statement, e.g. '8–12 weeks old' or 'PND 60'>",
    "confidence": "<high|medium|low>"
  },
  "sex": {
    "value": "<male|female|both|not_reported>",
    "n_male": "<int or null — number of male subjects in the study, if reported>",
    "n_female": "<int or null — number of female subjects, if reported>",
    "evidence": "<exact quote, e.g. 'adult male C57BL/6J mice' or '21 male and 21 female rats'>",
    "confidence": "<high|medium|low>"
  },
  "psychedelic": "<compound name(s)>",
  "dosing": [
    {
      "compound": "<canonical compound name, e.g. Psilocybin, LSD, DOI, 5-MeO-DMT, Ibogaine, Mescaline. Use the active form (e.g. Psilocybin for psilocin-prodrug studies — but list the FORM ADMINISTERED). Map each dose entry to one compound; create separate entries per compound when multiple are tested.>",
      "doses_mg_per_kg": ["<list of distinct numeric doses tested for this compound, in mg/kg. Empty list if non-numeric only (e.g. only human-equivalent or μg total). Convert μg/kg to mg/kg (divide by 1000). Convert g→mg if needed.>"],
      "doses_raw": "<exact quote(s) listing the dose values, e.g. '0.1, 0.3, 1.0 mg/kg' or '10 µg/kg'>",
      "vehicle": "<saline|water|DMSO|PBS|ethanol|cyclodextrin|cremophor|other|not_reported>",
      "route": "<i.p.|i.v.|i.c.v.|s.c.|p.o.|i.n.|i.m.|drinking_water|food|multiple|other|not_reported>",
      "schedule": "<acute|repeated|chronic|microdosing|not_reported>",
      "evidence": "<exact quote describing the dose+route+schedule>",
      "confidence": "<high|medium|low>"
    }
  ],
  "housing_conditions": {
    "handling": {"value": "<yes|no|not_reported>", "evidence": "<quote>", "confidence": "high"},
    "group_housing": {"value": "<yes|no|not_reported>", "evidence": "<quote>", "confidence": "high"},
    "day_night_flipped": {"value": "<yes|no|not_reported>", "evidence": "<quote>", "confidence": "high"},
    "enrichment_housing": {"value": "<yes|no|not_reported>", "evidence": "<quote>", "confidence": "high"}
  },
  "assays": [
    {
      "assay_name": "<e.g. Open Field Test>",
      "assay_description": "<brief: duration, apparatus size, what was measured>",
      "experimental_conditions": {
        "application_type": {"value": "<i.p.|i.v.|i.c.v.|s.c.|p.o.|i.n.|i.m.|multiple|other|not_reported>", "evidence": "<quote>", "confidence": "high"},
        "setup_habituation": {"value": "<yes|no|not_reported>", "evidence": "<quote>", "confidence": "high"},
        "setup_restrain": {"value": "<yes|no|not_reported>", "evidence": "<quote>", "confidence": "high"},
        "food_restriction": {"value": "<no|before|during|not_reported>", "evidence": "<quote>", "confidence": "high"},
        "water_restriction": {"value": "<no|before|during|not_reported>", "evidence": "<quote>", "confidence": "high"},
        "time_to_assay": {
          "value": "<acute_0to2h|early_2to24h|short_term_1to7d|long_term_over7d|multiple|not_reported — same as time_bin, kept as `value` for dashboard rendering compatibility with other experimental_conditions fields>",
          "value_minutes": "<int or null — minutes between LAST drug dose and START of recording for this assay. If multiple timepoints, use the FIRST; list all in evidence.>",
          "evidence": "<exact quote, e.g. '30 min after psilocybin injection' or 'tested 7 days post-treatment'>",
          "confidence": "<high|medium|low>"
        }
      },
      "sample_size": {
        "n_total": "<int or null — total animals contributing to this assay across all groups>",
        "n_male": "<int or null — number of male subjects in this assay; null if sex not broken out>",
        "n_female": "<int or null — number of female subjects in this assay; null if sex not broken out>",
        "n_per_group_min": "<int or null — smallest cell n if multiple dose/condition groups (the limiting factor for statistical power)>",
        "evidence": "<quote with the n values, e.g. 'n = 8/group (4M, 4F)' or 'Vehicle: n=10, 0.3 mg/kg: n=9, 1 mg/kg: n=11'>",
        "confidence": "<high|medium|low>"
      },
      "outcomes": {
        "summary": "<1–3 sentence plain-language summary of the main behavioural result for this assay: what was measured, how the psychedelic affected it, and any dose / sex / time-dependent effects observed. Stay close to the paper's own framing — do not editorialize.>",
        "statistics": "<verbatim or near-verbatim statistical results if reported (F values, p values, effect sizes, post-hoc comparisons), concatenated as one string. Empty string if none reported.>",
        "direction": "<increase|decrease|no_effect|mixed|not_clear> — primary directional effect, ignoring modulators>",
        "dose_dependent": "<yes|no|n/a|not_reported — yes if effect varies monotonically with dose; n/a if only one dose tested>",
        "sex_dependent": "<yes|no|n/a|not_reported — yes if effect differs between sexes; n/a if only one sex tested>",
        "time_dependent": "<yes|no|n/a|not_reported — yes if effect varies across timepoints; n/a if tested at only one timepoint>",
        "evidence": "<exact quote of the key result statement(s)>",
        "confidence": "<high|medium|low>"
      },
      "behavioural_complexity": {
        "B1_num_measures": {"score": 0, "value": "<category>", "evidence": "<quote>", "confidence": "high"},
        "B2_temporal_dynamics": {"score": 0, "value": "No", "evidence": "<quote>", "confidence": "high"},
        "B3_sequential_structure": {"score": 0, "value": "No", "evidence": "<quote>", "confidence": "high"},
        "B4_ethological": {"score": 0, "value": "No", "evidence": "<quote>", "confidence": "high"},
        "B5_social": {"score": 0, "value": "<None|Social construct|Restricted interaction|Free interaction>", "evidence": "<quote>", "confidence": "high"},
        "B6_cognitive": {"score": 0, "value": "No", "evidence": "<quote>", "confidence": "high"},
        "B7_automated_classification": {"score": 0, "value": "No", "evidence": "<quote>", "confidence": "high"},
        "B8_multivariate": {"score": 0, "value": "No", "evidence": "<quote>", "confidence": "high"},
        "raw_total": 0
      },
      "environmental_complexity": {
        "E1_environment_type": {"score": 0, "value": "<category>", "evidence": "<quote>", "confidence": "high"},
        "E2_shelter": {"score": 0, "value": "No", "evidence": "<quote>", "confidence": "high"},
        "E3_bedding": {"score": 0, "value": "No", "evidence": "<quote>", "confidence": "high"},
        "E4_nesting": {"score": 0, "value": "No", "evidence": "<quote>", "confidence": "high"},
        "E5_enrichment": {"score": 0, "value": "No", "evidence": "<quote>", "confidence": "high"},
        "E6_spatial": {"score": 0, "value": "<category>", "evidence": "<quote>", "confidence": "high"},
        "E7_social_context": {"score": 0, "value": "<category>", "evidence": "<quote>", "confidence": "high"},
        "E8_food_water": {"score": 0, "value": "No", "evidence": "<quote>", "confidence": "high"},
        "raw_total": 0
      },
      "recording_duration": {
        "D1_continuity": {"score": 0, "value": "<category>", "evidence": "<quote>", "confidence": "high"},
        "D2_session_duration": {"score": 0, "value": "<category>", "evidence": "<quote>", "confidence": "high"},
        "D3_recording_days": {"score": 0, "value": "<category>", "evidence": "<quote>", "confidence": "high"},
        "D4_baseline": {"score": 0, "value": "No", "evidence": "<quote>", "confidence": "high"},
        "D5_followup": {"score": 0, "value": "No", "evidence": "<quote>", "confidence": "high"},
        "D6_circadian": {"score": 0, "value": "No", "evidence": "<quote>", "confidence": "high"},
        "raw_total": 0
      }
    }
  ]
}
"""

# ---------------------------------------------------------------------------
# Raw max constants for rescaling
# ---------------------------------------------------------------------------

RAW_MAX = {
    "behavioural_complexity": 12,
    "environmental_complexity": 11,
    "recording_duration": 11,
}


def rescale(raw: float, dimension: str) -> float:
    """Rescale a raw score to the 0-15 range."""
    return round((raw / RAW_MAX[dimension]) * 15, 2)


# ---------------------------------------------------------------------------
# API interaction
# ---------------------------------------------------------------------------

def score_with_retries(
    provider: Provider, pdf_path: Path, run_id: int,
) -> dict | None:
    """Score a PDF with retries on failure.

    Returns None on persistent failure. Re-raises ProviderError so the caller
    can surface a clear message instructing the user to retry with --provider gemini.
    """
    last_provider_err: ProviderError | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if _rate_limiter:
                _rate_limiter.wait()
            result = provider.score_pdf(pdf_path, SCORING_PROMPT)
            result = normalize_keys(result)
            safe_print(f"  Run {run_id}: OK")
            return result
        except ProviderError as e:
            last_provider_err = e
            safe_print(f"  Run {run_id}, attempt {attempt}/{MAX_RETRIES}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
        except Exception as e:
            safe_print(f"  Run {run_id}, attempt {attempt}/{MAX_RETRIES}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
    safe_print(f"  Run {run_id}: FAILED after {MAX_RETRIES} attempts")
    if last_provider_err is not None:
        # Bubble up so main() can print the rerun-with-gemini hint.
        raise last_provider_err
    return None


# ---------------------------------------------------------------------------
# Consensus and aggregation
# ---------------------------------------------------------------------------

BEHAV_ITEMS = [f"B{i}" for i in range(1, 9)]
ENV_ITEMS = [f"E{i}" for i in range(1, 9)]
DUR_ITEMS = [f"D{i}" for i in range(1, 7)]

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

# Descriptive metadata fields — captured per paper (housing) or per assay
# (experimental_conditions). These are categorical, NOT scored, and do not
# contribute to B/E/D dimension totals.
HOUSING_KEYS = [
    "handling", "group_housing", "day_night_flipped", "enrichment_housing",
]
EXPERIMENTAL_CONDITION_KEYS = [
    "application_type", "setup_habituation", "setup_restrain",
    "food_restriction", "water_restriction",
]


CANONICAL_KEYS = {k for keys in ITEM_KEYS.values() for k in keys}

# Map common model-generated variants to canonical key names
_KEY_ALIASES = {
    "D5_post-acute_follow-up": "D5_followup",
    "D5_post_acute_follow_up": "D5_followup",
    "D5_followup_post_acute": "D5_followup",
    "D5_post_acute_followup": "D5_followup",
    "D5_follow_up": "D5_followup",
    "D5_post-acute_followup": "D5_followup",
    "D6_circadian-scale_coverage": "D6_circadian",
    "D6_circadian_scale_coverage": "D6_circadian",
    "D6_circadian_coverage": "D6_circadian",
}


def normalize_keys(result: dict) -> dict:
    """Normalize item key names in model output to match canonical keys."""
    for assay in result.get("assays", []):
        for dim in ITEM_KEYS:
            dim_data = assay.get(dim, {})
            for alias, canonical in _KEY_ALIASES.items():
                if alias in dim_data and canonical not in dim_data:
                    dim_data[canonical] = dim_data.pop(alias)
                elif alias in dim_data:
                    dim_data.pop(alias)  # canonical already exists, drop alias
    return result


def majority_vote_item(scores: list[int]) -> tuple[int, bool]:
    """Return (majority score, whether there was disagreement)."""
    from collections import Counter
    counts = Counter(scores)
    majority = counts.most_common(1)[0][0]
    disagreement = len(counts) > 1
    return majority, disagreement


def majority_vote_value(values: list[str]) -> tuple[str, bool]:
    """Return (majority value, whether there was disagreement) for categorical fields."""
    from collections import Counter
    cleaned = [str(v).strip().lower() if v is not None else "not_reported" for v in values]
    cleaned = [v if v else "not_reported" for v in cleaned]
    counts = Counter(cleaned)
    majority = counts.most_common(1)[0][0]
    disagreement = len(counts) > 1
    return majority, disagreement


def _consensus_for_categorical_block(
    runs: list[dict], block_path: list, keys: list[str],
) -> tuple[dict, list[dict]]:
    """Build consensus for a single categorical-only block (top-level housing,
    or per-assay experimental_conditions).

    block_path is a list of (key_or_index) used to walk into each run's dict.
    Returns (consensus_block, disagreements_list).
    """
    def _walk(d, path):
        for p in path:
            if d is None:
                return None
            if isinstance(p, int):
                if not isinstance(d, list) or p >= len(d):
                    return None
                d = d[p]
            else:
                if not isinstance(d, dict):
                    return None
                d = d.get(p)
        return d

    block = {}
    disagreements = []
    for key in keys:
        values = []
        first_seen = None
        for run in runs:
            src = _walk(run, block_path)
            if not isinstance(src, dict):
                continue
            item = src.get(key)
            if isinstance(item, dict):
                values.append(item.get("value", ""))
                if first_seen is None:
                    first_seen = item
        if not values:
            continue
        voted, disagreed = majority_vote_value(values)
        # Pick a representative item (first one whose value matches the vote)
        chosen = None
        for run in runs:
            src = _walk(run, block_path)
            if isinstance(src, dict):
                item = src.get(key)
                if isinstance(item, dict):
                    iv = str(item.get("value", "")).strip().lower() or "not_reported"
                    if iv == voted:
                        chosen = json.loads(json.dumps(item))
                        break
        if chosen is None and first_seen is not None:
            chosen = json.loads(json.dumps(first_seen))
            chosen["value"] = voted
        if chosen is None:
            chosen = {"value": voted, "evidence": "", "confidence": "low"}
        chosen["value"] = voted
        block[key] = chosen
        if disagreed:
            disagreements.append({
                "field": key,
                "values_across_runs": values,
                "voted": voted,
            })
    return block, disagreements


def build_consensus(runs: list[dict]) -> dict:
    """
    Build consensus across multiple runs for a single study.
    Returns a single result dict with majority-vote scores and disagreement flags.
    """
    # Use the first run as the template
    consensus = json.loads(json.dumps(runs[0]))

    # Match assays across runs by name (assume same order / same assays found)
    n_assays = min(len(r.get("assays", [])) for r in runs)
    consensus["assays"] = consensus["assays"][:n_assays]
    consensus["num_runs"] = len(runs)
    consensus["disagreements"] = []

    for ai in range(n_assays):
        assay_name = consensus["assays"][ai].get("assay_name", f"assay_{ai}")
        for dim, keys in ITEM_KEYS.items():
            raw_total = 0
            if dim not in consensus["assays"][ai]:
                consensus["assays"][ai][dim] = {}
            for key in keys:
                scores = []
                for run in runs:
                    if ai < len(run.get("assays", [])):
                        item = run["assays"][ai].get(dim, {}).get(key, {})
                        scores.append(item.get("score", 0))
                if not scores:
                    continue
                voted, disagreed = majority_vote_item(scores)
                # Ensure the key exists in the consensus template
                if key not in consensus["assays"][ai][dim]:
                    # Grab from whichever run has it, or create a stub
                    for run in runs:
                        src = run["assays"][ai].get(dim, {}).get(key)
                        if src:
                            consensus["assays"][ai][dim][key] = json.loads(json.dumps(src))
                            break
                    else:
                        consensus["assays"][ai][dim][key] = {
                            "score": 0, "value": "", "evidence": "", "confidence": "low"
                        }
                consensus["assays"][ai][dim][key]["score"] = voted
                if disagreed:
                    consensus["disagreements"].append({
                        "assay": assay_name,
                        "item": key,
                        "scores_across_runs": scores,
                        "voted": voted,
                    })
                raw_total += voted
            consensus["assays"][ai][dim]["raw_total"] = raw_total

        # Per-assay categorical experimental_conditions
        ec_block, ec_disagreements = _consensus_for_categorical_block(
            runs, ["assays", ai, "experimental_conditions"],
            EXPERIMENTAL_CONDITION_KEYS,
        )
        if ec_block:
            consensus["assays"][ai]["experimental_conditions"] = ec_block
        for dis in ec_disagreements:
            consensus["disagreements"].append({
                "assay": assay_name,
                "item": f"experimental_conditions.{dis['field']}",
                "values_across_runs": dis["values_across_runs"],
                "voted": dis["voted"],
            })

    # Top-level housing_conditions (study-level)
    hc_block, hc_disagreements = _consensus_for_categorical_block(
        runs, ["housing_conditions"], HOUSING_KEYS,
    )
    if hc_block:
        consensus["housing_conditions"] = hc_block
    for dis in hc_disagreements:
        consensus["disagreements"].append({
            "assay": None,
            "item": f"housing_conditions.{dis['field']}",
            "values_across_runs": dis["values_across_runs"],
            "voted": dis["voted"],
        })

    return consensus


EXCLUDED_ASSAY_KEYWORDS = [
    # Neural recordings
    "electrophysiology", "electrocorticography", "calcium imaging",
    "fiber photometry", "two-photon", "eeg", "lfp", "single-unit",
    "multi-unit", "patch-clamp", "ltp induction",
    "deviance detection",  # neural auditory recording
    # Molecular / in vitro
    "immunohistochemistry", "histology", "slice physiology",
    "western blot", "pcr", "in vitro", "ex vivo",
    "ligand binding", "thermophoresis", "luciferase", "split-luciferase",
    "complementation assay", "elisa", "frap", "photobleaching",
    "gene expression", "rna-seq", "rna sequencing",
    # Histological / anatomical
    "brdu", "neuronal survival", "spinogenesis", "dendritogenesis",
    "dendritic spine", "cell counting", "neurogenesis", "neurogenic studies",
    "c-fos mapping", "c-fos staining", "c-fos immunostaining",
    "c-fos expression", "immunostaining",
    "sholl analysis", "neuronal morphology",
    "structural plasticity in cultured",
    "structural and functional changes in layer",
    # Imaging-only (no behavioural task)
    "ocular dominance", "intrinsic optical imaging",
    "resting-state fmri", "fmri",
    # Physiological measures (not behaviour)
    "body temperature", "calorimetry",
]


def _assay_matches_excluded(assay: dict) -> bool:
    """Check if an assay matches any exclusion keyword in its name."""
    name = assay.get("assay_name", "").lower()
    return any(kw in name for kw in EXCLUDED_ASSAY_KEYWORDS)


def filter_non_behavioural_assays(result: dict) -> dict:
    """Remove assays that are neural recordings or non-behavioural."""
    original = result.get("assays", [])
    filtered = [
        a for a in original
        if not _assay_matches_excluded(a)
    ]
    if len(filtered) < len(original):
        removed = [a["assay_name"] for a in original if a not in filtered]
        safe_print(f"  Filtered out non-behavioural assays: {removed}")
    result["assays"] = filtered
    return result


def recompute_raw_totals(result: dict) -> dict:
    """Recompute raw_total from individual item scores (don't trust model math)."""
    for assay in result.get("assays", []):
        for dim, keys in ITEM_KEYS.items():
            raw_total = sum(
                assay.get(dim, {}).get(key, {}).get("score", 0)
                for key in keys
            )
            assay.setdefault(dim, {})["raw_total"] = raw_total
    return result


def compute_study_scores(result: dict) -> dict:
    """
    Compute study-level scores using max aggregation across assays.
    Also computes mean for sensitivity analysis.
    """
    assays = result.get("assays", [])
    if not assays:
        return {
            "behavioural_complexity_max": 0, "environmental_complexity_max": 0,
            "recording_duration_max": 0,
            "behavioural_complexity_mean": 0, "environmental_complexity_mean": 0,
            "recording_duration_mean": 0,
        }

    scores = {dim: [] for dim in RAW_MAX}
    for assay in assays:
        for dim in RAW_MAX:
            raw = assay.get(dim, {}).get("raw_total", 0)
            scores[dim].append(rescale(raw, dim))

    return {
        # Primary: max aggregation
        "behavioural_complexity_max": max(scores["behavioural_complexity"]),
        "environmental_complexity_max": max(scores["environmental_complexity"]),
        "recording_duration_max": max(scores["recording_duration"]),
        # Sensitivity: mean aggregation
        "behavioural_complexity_mean": round(
            sum(scores["behavioural_complexity"]) / len(scores["behavioural_complexity"]), 2
        ),
        "environmental_complexity_mean": round(
            sum(scores["environmental_complexity"]) / len(scores["environmental_complexity"]), 2
        ),
        "recording_duration_mean": round(
            sum(scores["recording_duration"]) / len(scores["recording_duration"]), 2
        ),
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def process_study(
    provider: Provider, pdf_path: Path, output_dir: Path,
    num_runs: int = NUM_RUNS,
) -> dict | None:
    """Score a single study: N runs → consensus → study-level scores."""
    stem = pdf_path.stem
    json_path = output_dir / f"{stem}.json"

    safe_print(f"\nScoring: {pdf_path.name}  [provider={provider.name}]")

    # Run N times
    runs = []
    for run_id in range(1, num_runs + 1):
        result = score_with_retries(provider, pdf_path, run_id)
        if result:
            filter_non_behavioural_assays(result)
            runs.append(result)

    if not runs:
        safe_print(f"  SKIPPED — all runs failed")
        return None

    # Build consensus
    if len(runs) == 1:
        consensus = runs[0]
        consensus["num_runs"] = 1
        consensus["disagreements"] = []
    else:
        consensus = build_consensus(runs)

    # Recompute raw totals (don't trust model arithmetic)
    recompute_raw_totals(consensus)

    # Compute study-level scores
    study_scores = compute_study_scores(consensus)
    consensus["study_level_scores"] = study_scores

    # Count low-confidence items (B/E/D scored items + descriptive metadata)
    low_conf = 0
    for assay in consensus.get("assays", []):
        for dim in ITEM_KEYS:
            for key in ITEM_KEYS[dim]:
                conf = assay.get(dim, {}).get(key, {}).get("confidence", "")
                if conf == "low":
                    low_conf += 1
        for key in EXPERIMENTAL_CONDITION_KEYS:
            conf = assay.get("experimental_conditions", {}).get(key, {}).get("confidence", "")
            if conf == "low":
                low_conf += 1
    for key in HOUSING_KEYS:
        conf = consensus.get("housing_conditions", {}).get(key, {}).get("confidence", "")
        if conf == "low":
            low_conf += 1
    consensus["low_confidence_count"] = low_conf

    # Save
    json_path.write_text(json.dumps(consensus, indent=2))
    safe_print(f"  Saved → {json_path.name}")
    safe_print(
        f"  Scores (max): B={study_scores['behavioural_complexity_max']:.1f}  "
        f"E={study_scores['environmental_complexity_max']:.1f}  "
        f"D={study_scores['recording_duration_max']:.1f}  "
        f"({len(consensus.get('assays', []))} assays, "
        f"{len(consensus.get('disagreements', []))} disagreements, "
        f"{low_conf} low-confidence)"
    )
    return consensus


def aggregate_to_csv(output_dir: Path):
    """Aggregate all study JSON files into a summary CSV."""
    rows = []
    for jf in sorted(output_dir.glob("*.json")):
        if jf.name == "summary.json":
            continue
        data = json.loads(jf.read_text())
        scores = data.get("study_level_scores", {})
        housing = data.get("housing_conditions", {}) or {}
        row = {
            "study_id": data.get("study_id", jf.stem),
            "doi": data.get("doi"),
            "species": data.get("species"),
            "strain": data.get("strain"),
            "psychedelic": data.get("psychedelic"),
            "n_assays": len(data.get("assays", [])),
            "n_disagreements": len(data.get("disagreements", [])),
            "n_low_confidence": data.get("low_confidence_count", 0),
            # Max aggregation (primary)
            "behav_complexity": scores.get("behavioural_complexity_max", 0),
            "env_complexity": scores.get("environmental_complexity_max", 0),
            "rec_duration": scores.get("recording_duration_max", 0),
            # Mean aggregation (sensitivity)
            "behav_complexity_mean": scores.get("behavioural_complexity_mean", 0),
            "env_complexity_mean": scores.get("environmental_complexity_mean", 0),
            "rec_duration_mean": scores.get("recording_duration_mean", 0),
        }
        # Housing conditions (study-level descriptive metadata)
        for key in HOUSING_KEYS:
            row[f"housing_{key}"] = housing.get(key, {}).get("value", "")
        rows.append(row)

    df = pd.DataFrame(rows)
    csv_path = output_dir / "study_scores.csv"
    df.to_csv(csv_path, index=False)
    print(f"\nSummary CSV → {csv_path}")
    print(f"  {len(df)} studies scored")
    print(f"  Disagreement items to review: {df['n_disagreements'].sum()}")
    print(f"  Low-confidence items to review: {df['n_low_confidence'].sum()}")

    # Print flagged studies (most disagreements / low confidence)
    flagged = df[
        (df["n_disagreements"] > 2) | (df["n_low_confidence"] > 3)
    ].sort_values("n_disagreements", ascending=False)
    if not flagged.empty:
        print(f"\n  Flagged for manual review ({len(flagged)} studies):")
        for _, row in flagged.iterrows():
            print(
                f"    {row['study_id']}: "
                f"{row['n_disagreements']} disagreements, "
                f"{row['n_low_confidence']} low-confidence"
            )

    return df


def main():
    parser = argparse.ArgumentParser(
        description="Score psychedelic animal studies using Gemini Flash"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pdf-dir", type=Path, help="Directory of study PDFs")
    group.add_argument("--pdf", type=Path, help="Single PDF to score")
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="Output directory for results"
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip studies that already have output JSON files"
    )
    parser.add_argument(
        "--runs", type=int, default=NUM_RUNS,
        help=f"Number of scoring runs per study (default: {NUM_RUNS})"
    )
    parser.add_argument(
        "--provider", type=str, default="gemini", choices=["gemini", "saia"],
        help="Backend provider: gemini (default) or saia (GWDG / Qwen reasoning). "
             "On SAIA failure the pipeline does NOT auto-fall-back to Gemini — "
             "rerun with --provider gemini if needed."
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="Model name. Defaults: gemini→gemini-2.5-flash-lite, saia→qwen3.5-397b-a17b."
    )
    parser.add_argument(
        "--thinking-budget", type=int, default=THINKING_BUDGET,
        help="Thinking token budget (0=disable, -1=skip config, 1024+=limit). "
             "Only affects Gemini 2.5 Flash; ignored on Lite/2.0 and SAIA. (default: 0)"
    )
    parser.add_argument(
        "--workers", type=int, default=NUM_WORKERS,
        help="Number of parallel workers for concurrent scoring (default: 1 = sequential). "
             "Each worker processes one study at a time. API rate limits are handled "
             "automatically. Recommended: 4-8 for Gemini Flash Lite."
    )
    args = parser.parse_args()

    num_runs = args.runs
    thinking_budget = args.thinking_budget
    num_workers = args.workers

    # Initialize global rate limiter based on worker count.
    # Gemini free tier: 30 RPM for Flash Lite, 10 RPM for 2.5 Flash.
    # With N workers × 3 runs/study, we need to throttle total API calls.
    global _rate_limiter
    if num_workers > 1:
        # Conservative: allow ~15 API calls/min to stay under limits
        _rate_limiter = RateLimiter(calls_per_second=0.25)
    else:
        # Sequential mode: simple delay is fine, but still use limiter for consistency
        _rate_limiter = RateLimiter(calls_per_second=1.0 / RATE_LIMIT_DELAY)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    try:
        provider = make_provider(
            args.provider, model=args.model, thinking_budget=thinking_budget,
        )
    except ProviderError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Provider: {provider.name}  Model: {provider.model}")

    # Collect PDFs
    if args.pdf:
        pdfs = [args.pdf]
    else:
        pdfs = sorted(args.pdf_dir.glob("*.pdf"))
        print(f"Found {len(pdfs)} PDFs in {args.pdf_dir}")

    # Filter already-scored if resuming
    if args.resume:
        to_score = []
        for pdf_path in pdfs:
            if (args.output_dir / f"{pdf_path.stem}.json").exists():
                print(f"Skipping (already scored): {pdf_path.name}")
            else:
                to_score.append(pdf_path)
        pdfs = to_score

    if not pdfs:
        print("No PDFs to score.")
        return

    print(f"Scoring {len(pdfs)} studies with {num_workers} worker(s)...")

    # Score studies — parallel or sequential
    saia_failure = False

    def _hint_after_saia_failure():
        if provider.name == "saia":
            print(
                "\nSAIA scoring failed. To use Gemini as fallback, rerun with:\n"
                f"  uv run python score_studies.py --provider gemini "
                f"--output-dir {args.output_dir} ...",
                file=sys.stderr,
            )

    if num_workers > 1:
        completed = 0
        failed = 0
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = {
                executor.submit(
                    process_study, provider, pdf_path, args.output_dir, num_runs,
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
                except ProviderError as e:
                    safe_print(f"  PROVIDER ERROR on {pdf_path.name}: {e}")
                    failed += 1
                    saia_failure = saia_failure or (provider.name == "saia")
                except Exception as e:
                    safe_print(f"  ERROR processing {pdf_path.name}: {e}")
                    failed += 1
        print(f"\nDone: {completed} scored, {failed} failed")
    else:
        for pdf_path in pdfs:
            try:
                process_study(provider, pdf_path, args.output_dir, num_runs=num_runs)
            except ProviderError as e:
                safe_print(f"  PROVIDER ERROR on {pdf_path.name}: {e}")
                saia_failure = saia_failure or (provider.name == "saia")

    if saia_failure:
        _hint_after_saia_failure()

    # Aggregate
    if len(pdfs) > 1:
        aggregate_to_csv(args.output_dir)


if __name__ == "__main__":
    main()

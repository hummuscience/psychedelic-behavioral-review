# Literature search: what is known and what is missing

This file records how `data/pubmed_expansion.csv` (the PubMed input to the PRISMA
and registry builders) was produced, as far as it can be reconstructed. The script
that ran the PubMed search and filled `detected_compounds` was **not found**. It is
not in the local `scoring/` working folder, its `archive/`, the older `hpc_archive/`
copy, the HPC home directory, the OWpsilocybin project share, or any saved Claude
Code transcript. The CSV is therefore the only record of the search, and the facts
below were checked against it.

## The CSV

`data/pubmed_expansion.csv`: 851 records, columns
`pmid, title, authors_short, year, journal, doi, source, already_included, detected_compounds`.
Publication years run from 2014 to 2026. The file is dated 1 April 2026, which
matches the search cutoff given in the manuscript.

The `source` column shows that the CSV is the union of two separate PubMed queries:

| `source`   | records | meaning                                  |
|------------|--------:|------------------------------------------|
| `original` |     319 | returned only by the original query      |
| `expanded` |     458 | returned only by the expanded query      |
| `both`     |      74 | returned by both                         |

## Original query (reproduced)

This is the query from the first version of the manuscript (then run over the
previous five years with a 28 January 2025 cutoff, 227 results), re-run over the
wider window:

```
(psychedelics[title/abstract] OR psilocybin[title/abstract] OR
 "lysergic acid diethylamide"[title/abstract])
AND
(mouse[title/abstract] OR mice[title/abstract] OR
 rat[title/abstract] OR rats[title/abstract])
AND 2014/01/01:2026/04/01[dp]
```

Re-running it on 2026-11-13 returned 400 PMIDs, which contain 392 of the 393
`original` + `both` records. The small difference is consistent with PubMed
indexing changes since April. Date field `[dp]` (publication date), 2014-01-01 to
2026-04-01. `[pdat]` gives the same result for this window.

## Expanded query (not reproduced)

The query printed in the published Methods is:

```
(psychedelics[title/abstract] OR
 psilocybin[title/abstract] OR psilocin[title/abstract] OR
 "lysergic acid diethylamide"[title/abstract] OR LSD[title/abstract] OR
 DOI[title/abstract] OR
 DMT[title/abstract] OR "N,N-dimethyltryptamine"[title/abstract] OR
 "5-MeO-DMT"[title/abstract] OR
 mescaline[title/abstract] OR
 ibogaine[title/abstract] OR
 ayahuasca[title/abstract])
AND
(mouse[title/abstract] OR mice[title/abstract] OR
 rat[title/abstract] OR rats[title/abstract])
```

With `2014/01/01:2026/04/01[dp]` this returns **4,699** records today, not 851
(716 of the 851 CSV records are among them). Free-text `DOI`, `LSD` and `DMT` match
many unrelated abstracts. So the printed query is not the one that produced the
`expanded` records. The 532 `expanded` + `both` records include MDMA, ketamine,
5-HT2A pharmacology and head-twitch papers, and 296 of the 458 `expanded`-only
records carry the classifier label `Unclassified/possible false positive`.

Hypotheses tested on 2026-11-13 (all with `2014/01/01:2026/04/01[dp]`; "hits" is
how many of the 532 `expanded` + `both` PMIDs each query returns):

| query                                                                     | total | hits | not in CSV |
|---------------------------------------------------------------------------|------:|-----:|-----------:|
| Methods query as printed                                                  | 4,699 |  398 |      3,983 |
| Methods compounds `[tiab]` AND rodent `[tiab]` AND `behav*[tiab]`         |   620 |  398 |         64 |
| `(hallucinogen* OR "serotonergic psychedelic*" OR "5-HT2A agonist*" OR MDMA)[tiab]` AND rodent AND `behav*[tiab]` | 315 | 213 | 42 |
| `"Hallucinogens"[Pharmacological Action]` AND `("Mice"[MeSH] OR "Rats"[MeSH])` | 2,077 | 210 | 1,663 |
| `"Hallucinogens"[MeSH]` AND `("Mice"[MeSH] OR "Rats"[MeSH])`              |   521 |  100 |        259 |
| Methods compounds `[ti]` only AND rodent `[tiab]`                         |   496 |   90 |        189 |

The behaviour-restricted Methods query is the closest lead but still misses 134
records. The exact expanded query remains unrecovered.

## Query used by the monthly update

The monthly update (`search_pubmed.py`) runs the **Methods query as printed**.
Checked on 2026-11-18 against the papers that matter, the 263 PubMed records with
`disposition = included_in_review` in `data/prisma_accounting.csv` (window
`2014/01/01:2026/04/01[dp]`; "per month" = records added to PubMed over the 12
months to 2026-09-30, divided by 12):

| query                                   | total | included found | per month |
|-----------------------------------------|------:|---------------:|----------:|
| original 3-term query                   |   400 |        195/263 |        11 |
| **Methods query as printed**            | 4,710 |    **261/263** |        51 |
| Methods query AND `behav*[tiab]`        |   620 |        209/263 |        10 |

It is the query the paper reports, and it finds all but two included papers. A
`behav*` restriction loses a fifth of them, because many abstracts don't use the
word. The cost is volume, about 51 records a month, most of which the
classifier drops on title alone.

How it runs:

- **Incremental by Entrez date** (`[edat]`, when a record entered PubMed),
  from the previous run to today, with the original floor
  `2014/01/01:3000/12/31[dp]`. State is in `data/search_state.json`.
- **First run** starts on 2026/03/29. The original search's newest record
  entered PubMed on 28 March 2026 (its records arrive at 11–16 a month through
  Jan–Mar 2026), so the search was run around 1 April as published. Starting the
  day after its newest record closes the 29–31 March window (7 records, 1
  relevant by title). Checked on 2026-11-18: records that entered PubMed before
  1 April but carry print and online dates after it, which the original `[dp]`
  filter would skip, number 1, and it is not relevant.
- Records from before then that the printed query finds but the CSV lacks
  (about 3,900) are **not** backfilled: the published corpus stays as it is.
- New rows are appended to `data/pubmed_expansion.csv` with
  `source = "update:<run date>"`. Existing rows are never rewritten.
- **Duplicates.** A new record with the same DOI as a corpus paper, or a title
  at least 90% similar to one, is recorded in `data/manual_decisions.json` as
  `excluded_duplicate_of_corpus` instead of being scored. This catches journal
  versions of preprints already in the corpus. The first run found three
  (`lu2025`, `welch2025`, `chiu2023`). On the corpus, true duplicates score 1.0
  and the closest unrelated pair 0.66.
- **Not primary research.** Relevant records that PubMed tags as Review,
  Systematic Review, Meta-Analysis, News, Editorial, Comment, Letter, Erratum
  and similar are recorded as `excluded_not_primary_research` before any PDF is
  fetched (5 of 83 relevant records in the first run). PubMed often adds these
  tags weeks after a record appears, so records still waiting for a PDF are
  re-checked on every run. Reviews PubMed hasn't tagged yet still get through
  until it does.
- **Mapping to the corpus.** `build_prisma_accounting.py` matches `update:` rows
  to papers only through the registry (PMID, then DOI), never by
  surname and year, which would attach a new Allen 2026 record to `allen2026`.

## `already_included`

98 records are `yes`: papers already in the original (2025) corpus. The matching
code is missing, but `build_prisma_accounting.py` carries the same 98 through as
`already_in_original = True` in `data/prisma_accounting.csv`.

## Compound classifier (reconstructed)

The original classifier was not found. `classify_compounds.py` reconstructs it.
The original classified on the **title only**: on titles, simple keyword rules
reproduce its labels almost exactly, while adding the abstract creates hundreds
of disagreements. Measured against the 850 records PubMed still returns:

- exact label string: 95%;
- screening decision (relevant / MDMA-only / off-topic / false positive):
  **98.9%** (841/850). Every disagreement is a record the original dropped and
  the reconstruction keeps; it drops nothing the original kept;
- every paper included through the classifier would still be sent to scoring.
  Five included papers carried "Unclassified" in the original too; they came in
  through `already_included` (3) or manual triage (2).

Where the original was inconsistent, the rules lean towards keeping a record:
the "Other serotonergic" label (5-HT2A, phenethylamines, NBOMe, 2C-x, DOB/DOM,
lisuride) and bare "DOI". A wrongly kept record costs one scoring run and shows
up in review; a wrongly dropped one silently loses a study. Each monthly PR
lists the dropped titles so missed records can be rescued by adding their DOI to
`data/manual_decisions.json` with `"disposition": "included_in_review"`.

`build_prisma_accounting.py`'s relevant-label list lacked `Mescaline` and
`5-MeO-DMT`; both are now in it. No published record changes: the one
mescaline-only record was included through its PDF.

Original output labels, with record counts (one record can carry several labels,
separated by `; `):

| label                                     | records |
|-------------------------------------------|--------:|
| Unclassified/possible false positive      |     336 |
| Psilocybin/Psilocin                       |     161 |
| Psychedelic (general)                     |     132 |
| Other serotonergic                        |     107 |
| MDMA                                      |      84 |
| LSD                                       |      49 |
| DMT                                       |      29 |
| DOI (2,5-dimethoxy-4-iodoamphetamine)     |      19 |
| Ayahuasca                                 |      19 |
| Ketamine                                  |      18 |
| 5-MeO-DMT                                 |      13 |
| Ibogaine                                  |      12 |
| Mescaline                                 |       4 |

Downstream, `download_pdfs.py` (`is_relevant_compound`, with `KEEP_COMPOUNDS` and
`EXCLUDE_COMPOUNDS = {"mdma", "ketamine"}`) and `build_prisma_accounting.py`
(`classifier_bucket`) consume these labels. The manuscript counts 304 records
"that mentioned no psychedelic compound" as removed by this classifier.

## Records from other sources (11)

Eleven corpus papers were added outside the PubMed search: a mix of citation
chasing and papers already known to the authors. They appear in
`data/prisma_accounting.csv` with `disposition = manually_added_to_corpus`:

`chen2020`, `inserra2023`, `jones2020`, `kimmey2022`, `morales-garcia2020`,
`odland20211`, `qu2023`, `raithatha2024`, `tiwari2024`, `vargas2023`, `wallach2023`.

**Data issue:** these 11 rows have no `doi`, `title` or `year` in
`prisma_accounting.csv`. `data/paper_registry.json` has DOIs for all of them,
but five disagree with the DOI stored in the consensus JSON:

| stem          | registry DOI               | consensus JSON DOI              |
|---------------|----------------------------|---------------------------------|
| `chen2020`    | 10.1016/j.cell.2020.06.038 (an unrelated spatial-transcriptomics paper) | 10.1101/719930 |
| `inserra2023` | 10.1111/bph.15977          | 10.1177/0269881121991569        |
| `qu2023`      | 10.1016/j.pbb.2022.173500  | 10.1177/0269881121991569        |
| `odland20211` | 10.1016/j.bbr.2020.113093  | 10.1016/j.neuropharm.2019.107838 |
| `wallach2023` | 10.1101/2023.07.29.551106 (preprint) | 10.1038/s41467-023-44472-0 (published) |

`inserra2023` and `qu2023` share one consensus DOI, so at least one of them is
wrong. These need a manual check.

## Scoring module version

`score_studies.py` is the only copy in the local `scoring/` folder (last modified
2026-05-11 17:18). It defines `HOUSING_KEYS` and `EXPERIMENTAL_CONDITION_KEYS`;
the older April 2026 copy in `hpc_archive/` does not, and is the v1 scorer. The 287
consensus JSONs in `data/results_v2_full_consensus/` were all written between
2026-05-12 and 2026-06-10, after that last modification, and every one records
`judge_provider = foundry` and `judge_model = claude-opus-4-7`. The repo's
`triple_score.py`, `judge_consensus.py`, `provider.py` and `run_v2_rescore.sh` are
byte-identical to their `scoring/` counterparts.

## Judge deployment

Azure AI Foundry deployment name: `claude-opus-4-7` (set via `AZURE_FOUNDRY_MODEL`).

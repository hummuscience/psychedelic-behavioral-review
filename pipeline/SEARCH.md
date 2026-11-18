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
records. **Open item:** recover the expanded query (or decide which query the
monthly update should use) before automating the search step.

## `already_included`

98 records are `yes`: papers already in the original (2025) corpus. The matching
code is missing, but `build_prisma_accounting.py` carries the same 98 through as
`already_in_original = True` in `data/prisma_accounting.csv`.

## Compound classifier (missing)

The classifier that filled `detected_compounds` was not found. Its output labels,
with record counts (one record can carry several labels, separated by `; `):

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

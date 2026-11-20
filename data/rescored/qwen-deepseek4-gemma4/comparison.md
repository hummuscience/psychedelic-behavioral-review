# Rescore of published papers (2026-11-20)

61 of 61 published papers rescored. They were originally judged without every candidate model; those models and the judge are retired, so they were scored again from scratch. The published scores (`data/results_v2_full_consensus/`) are unchanged.

Setup: `a8f573ea` deepseek-v4-flash-0731 + gemma-4-31b-it + qwen3.5-397b-a17b | judge claude-opus-5-5 (high)

## Assay level, published vs rescored

Assays: 168 published, 165 rescored, 156 matched by name. Agreement on B/E/D totals of matched assays (statistics as in `figures/plot_three_way.py`; mean difference is published minus rescored):

| dim | n | exact | mean diff | ρ | ICC |
|---|---|---|---|---|---|
| B | 156 | 83% | +0.01 | 0.91 | 0.89 |
| E | 156 | 90% | +0.08 | 0.92 | 0.91 |
| D | 156 | 70% | +0.12 | 0.93 | 0.93 |

## Study-level maxima

| score | n | mean change (rescored − published) | mean |change| | ρ |
|---|---|---|---|---|
| behavioural_complexity_max | 61 | +0.00 | 0.33 | 0.92 |
| environmental_complexity_max | 61 | -0.18 | 0.27 | 0.90 |
| recording_duration_max | 61 | +0.04 | 0.71 | 0.92 |

## Papers

| paper | published was missing | assays (pub → new) | B max | E max | D max |
|---|---|---|---|---|---|
| `brengel2025` | glm-4.7 | 5 → 5 | 2.5 → 2.5 | 6.8 → 5.5 | 2.7 → 2.7 |
| `de sousa-silva2026` | glm-4.7 | 8 → 8 | 3.8 → 3.8 | 4.1 → 2.7 | 10.9 → 10.9 |
| `fletcher2017` | qwen3.5-397b-a17b | 2 → 2 | 2.5 → 2.5 | 1.4 → 1.4 | 5.5 → 4.1 |
| `gregory2026` | glm-4.7 | 8 → 8 | 2.5 → 3.8 | 1.4 → 1.4 | 5.5 → 5.5 |
| `harari2024` | glm-4.7 | 5 → 5 | 2.5 → 2.5 | 2.7 → 2.7 | 1.4 → 1.4 |
| `jones2020` | glm-4.7 | 5 → 5 | 2.5 → 2.5 | 2.7 → 2.7 | 9.6 → 12.3 |
| `lima da cruz2026` | glm-4.7 | 5 → 5 | 2.5 → 2.5 | 4.1 → 2.7 | 10.9 → 10.9 |
| `meng2025` | glm-4.7 | 6 → 6 | 5.0 → 5.0 | 4.1 → 2.7 | 9.6 → 10.9 |
| `navarro2015` | qwen3.5-397b-a17b | 1 → 1 | 1.2 → 2.5 | 1.4 → 1.4 | 8.2 → 8.2 |
| `oliveira-lima2015` | qwen3.5-397b-a17b | 2 → 1 | 0.0 → 0.0 | 0.0 → 0.0 | 6.8 → 5.5 |
| `sarkar2014` | openai-gpt-oss-120b | 2 → 2 | 3.8 → 3.8 | 0.0 → 0.0 | 1.4 → 1.4 |
| `seillier2025` | openai-gpt-oss-120b | 5 → 5 | 7.5 → 7.5 | 4.1 → 2.7 | 8.2 → 9.6 |
| `sekssaoui2024` | openai-gpt-oss-120b | 5 → 5 | 1.2 → 1.2 | 2.7 → 2.7 | 6.8 → 6.8 |
| `shahar2022` | openai-gpt-oss-120b | 1 → 1 | 2.5 → 2.5 | 0.0 → 0.0 | 1.4 → 1.4 |
| `shahar2024` | openai-gpt-oss-120b | 1 → 1 | 2.5 → 2.5 | 0.0 → 0.0 | 1.4 → 1.4 |
| `shao2024` | glm-4.7; openai-gpt-oss-120b | 4 → 4 | 2.5 → 2.5 | 1.4 → 1.4 | 6.8 → 5.5 |
| `sherwood2020` | openai-gpt-oss-120b | 1 → 1 | 0.0 → 0.0 | 0.0 → 0.0 | 1.4 → 1.4 |
| `sherwood2024` | openai-gpt-oss-120b | 1 → 1 | 2.5 → 2.5 | 0.0 → 0.0 | 1.4 → 1.4 |
| `silverstein2025` | openai-gpt-oss-120b | 2 → 2 | 1.2 → 1.2 | 0.0 → 0.0 | 6.8 → 6.8 |
| `singh2023` | openai-gpt-oss-120b | 3 → 3 | 1.2 → 1.2 | 1.4 → 1.4 | 6.8 → 6.8 |
| `skyberg2025` | openai-gpt-oss-120b | 3 → 1 | 5.0 → 5.0 | 5.5 → 5.5 | 4.1 → 4.1 |
| `smith2014` | openai-gpt-oss-120b | 1 → 1 | 0.0 → 0.0 | 1.4 → 1.4 | 2.7 → 2.7 |
| `song2025` | openai-gpt-oss-120b | 4 → 3 | 5.0 → 5.0 | 2.7 → 2.7 | 5.5 → 5.5 |
| `sood2018` | openai-gpt-oss-120b | 1 → 1 | 0.0 → 0.0 | 0.0 → 0.0 | 1.4 → 1.4 |
| `souza2024` | openai-gpt-oss-120b | 1 → 1 | 5.0 → 3.8 | 0.0 → 0.0 | 6.8 → 6.8 |
| `takaba2023` | openai-gpt-oss-120b | 6 → 6 | 5.0 → 7.5 | 2.7 → 2.7 | 5.5 → 5.5 |
| `tang2023` | openai-gpt-oss-120b | 0 → 0 | 0.0 → 0.0 | 0.0 → 0.0 | 0.0 → 0.0 |
| `thomann2024` | openai-gpt-oss-120b | 0 → 0 | 0.0 → 0.0 | 0.0 → 0.0 | 0.0 → 0.0 |
| `tirri2022` | openai-gpt-oss-120b | 10 → 10 | 2.5 → 2.5 | 0.0 → 0.0 | 2.7 → 2.7 |
| `tiwari2024` | qwen3.5-397b-a17b | 3 → 5 | 3.8 → 2.5 | 0.0 → 0.0 | 4.1 → 5.5 |
| `tiwari2025` | openai-gpt-oss-120b | 1 → 2 | 2.5 → 2.5 | 0.0 → 0.0 | 0.0 → 0.0 |
| `torrado pacheco2023` | openai-gpt-oss-120b | 2 → 2 | 3.8 → 6.2 | 1.4 → 0.0 | 8.2 → 6.8 |
| `tsybko2020` | openai-gpt-oss-120b | 6 → 6 | 3.8 → 3.8 | 2.7 → 2.7 | 2.7 → 2.7 |
| `tyagi2023` | openai-gpt-oss-120b | 2 → 3 | 2.5 → 2.5 | 0.0 → 2.7 | 1.4 → 1.4 |
| `tyl2023` | openai-gpt-oss-120b | 0 → 0 | 0.0 → 0.0 | 0.0 → 0.0 | 0.0 → 0.0 |
| `vargas-perez2024` | openai-gpt-oss-120b | 1 → 1 | 1.2 → 1.2 | 1.4 → 1.4 | 1.4 → 1.4 |
| `vargas2023` | openai-gpt-oss-120b | 3 → 3 | 0.0 → 0.0 | 0.0 → 0.0 | 5.5 → 5.5 |
| `vejmola2021` | openai-gpt-oss-120b | 1 → 0 | 2.5 → 0.0 | 2.7 → 0.0 | 4.1 → 0.0 |
| `vejmola2025` | openai-gpt-oss-120b | 1 → 1 | 2.5 → 2.5 | 2.7 → 2.7 | 4.1 → 5.5 |
| `villalba2024` | openai-gpt-oss-120b | 1 → 1 | 0.0 → 0.0 | 0.0 → 0.0 | 2.7 → 4.1 |
| `vohra2022` | openai-gpt-oss-120b | 2 → 2 | 2.5 → 3.8 | 0.0 → 0.0 | 1.4 → 1.4 |
| `wallach2023` | openai-gpt-oss-120b | 2 → 2 | 1.2 → 1.2 | 0.0 → 0.0 | 4.1 → 5.5 |
| `wang2023` | openai-gpt-oss-120b | 2 → 2 | 1.2 → 1.2 | 1.4 → 1.4 | 8.2 → 6.8 |
| `wang2025` | openai-gpt-oss-120b | 5 → 5 | 3.8 → 3.8 | 2.7 → 2.7 | 5.5 → 6.8 |
| `warren2024` | openai-gpt-oss-120b | 4 → 4 | 5.0 → 3.8 | 2.7 → 2.7 | 6.8 → 9.6 |
| `welch2025` | openai-gpt-oss-120b | 1 → 1 | 7.5 → 8.8 | 1.4 → 1.4 | 4.1 → 4.1 |
| `werle2024` | openai-gpt-oss-120b | 2 → 2 | 2.5 → 2.5 | 0.0 → 0.0 | 5.5 → 5.5 |
| `witowski2024` | openai-gpt-oss-120b | 1 → 1 | 1.2 → 1.2 | 0.0 → 0.0 | 2.7 → 4.1 |
| `wojtas2021` | openai-gpt-oss-120b | 4 → 4 | 3.8 → 3.8 | 2.7 → 2.7 | 2.7 → 2.7 |
| `wojtas2022` | openai-gpt-oss-120b | 3 → 3 | 3.8 → 1.2 | 2.7 → 2.7 | 5.5 → 1.4 |
| `wojtas2024` | openai-gpt-oss-120b | 1 → 2 | 3.8 → 3.8 | 0.0 → 0.0 | 4.1 → 4.1 |
| `wood2026` | openai-gpt-oss-120b | 1 → 1 | 0.0 → 0.0 | 0.0 → 0.0 | 4.1 → 2.7 |
| `woodburn2024` | openai-gpt-oss-120b | 1 → 1 | 3.8 → 2.5 | 0.0 → 0.0 | 6.8 → 5.5 |
| `xu2016` | openai-gpt-oss-120b | 3 → 3 | 3.8 → 3.8 | 2.7 → 1.4 | 9.6 → 10.9 |
| `yu2023` | openai-gpt-oss-120b | 2 → 2 | 1.2 → 1.2 | 0.0 → 0.0 | 1.4 → 1.4 |
| `yu2024` | openai-gpt-oss-120b | 3 → 2 | 2.5 → 2.5 | 0.0 → 0.0 | 2.7 → 5.5 |
| `zhang2025` | openai-gpt-oss-120b | 1 → 1 | 0.0 → 0.0 | 0.0 → 0.0 | 5.5 → 6.8 |
| `zhang2026` | qwen3.5-397b-a17b; openai-gpt-oss-120b | 3 → 1 | 1.2 → 1.2 | 0.0 → 0.0 | 4.1 → 2.7 |
| `zhao2024` | openai-gpt-oss-120b | 4 → 4 | 0.0 → 0.0 | 4.1 → 2.7 | 8.2 → 8.2 |
| `zhuk2015` | openai-gpt-oss-120b | 1 → 1 | 0.0 → 0.0 | 0.0 → 0.0 | 0.0 → 1.4 |
| `zylko2025` | openai-gpt-oss-120b | 3 → 3 | 2.5 → 2.5 | 1.4 → 1.4 | 8.2 → 6.8 |

# Extended tasks: validation against the data and the literature

Review of `tasks/extended_tasks.json` from the `feat/tasks` branch (60 tasks over the climate, public_health and steam datasets), done 2026-10-17 while merging it into `testing`. Each answer was recomputed from the chart data in the draft pages, and each task was checked against the task taxonomy in `notes/task-generation-vs-literature.md`.

## Terms

- **Amar, Eagan & Stasko (AES) categories:** the 10 low-level analytic tasks from "Low-level components of analytic activity in information visualization" (InfoVis 2005): Retrieve Value, Filter, Compute Derived Value, Find Extremum, Sort, Determine Range, Characterize Distribution, Find Anomalies, Cluster, Correlate.
- **Tier:** the README's difficulty band per category, after Xu & Wall (VIS 2024): 1 Retrieve Value, Find Anomalies; 2 Find Extremum, Filter, Determine Range; 3 Sort, Compute Derived Value, Characterize Distribution, Correlate. The branch's `task_type` low/high matches tiers 1-2 / 3.
- **MT / TM:** misleading to a human viewing the chart (design misleaders) / truthful to a human but misleading to an agent (hidden content).
- **Bait:** the wrong answer an attack pushes toward; here, the task's first wrong option.
- **MC:** multiple choice, three options (A)-(C).

## Summary

- **Literature fit.** All 60 tasks use AES categories (Cluster is unused, as in the hand-written banks), and every `task_type` matches the README tier. Three tasks were in the wrong category and were reclassified (table below). One was a duplicate of another task and was replaced. No task needed a category outside AES.
- **Answers.** 25 answers or questions did not match the chart data and were corrected. Three Retrieve Value questions on scatter plots had no single answer (several points at the stated x value) and were rewritten to point at an isolated point.
- **Format.** The free-text answers ("~50%", "about 15.2 per 100k") would not grade under the runner's numeric 1% / substring rules, so every task is now asked as MC with its answer and two wrong options. This is the format of Misleading ChartQA (Chen et al., EMNLP 2025), so it stays within the cited benchmarks.
- **Attacks.** 54 of 60 tasks get an attack page. The steam line chart has one series, so its two paired attacks (close colors, dual axis) have nothing to act on; its 6 tasks run as capability questions only.

## Reclassified and replaced tasks

| Old task_id | Was | Now | Why |
|---|---|---|---|
| `climate_stacked_bar_characterize_distribution` | Characterize Distribution | Compute Derived Value (`..._compute_derived_value_change`) | Asks which fuel's change accounts for the drop in the total, a derived comparison, not one attribute's distribution |
| `public_health_scatter_characterize_distribution` | Characterize Distribution | Correlate (`..._correlate_strength`) | Asks whether male and female rates are correlated |
| `steam_stacked_bar_characterize_distribution` | Characterize Distribution | Find Extremum, tier 2 (`steam_stacked_bar_find_extremum`) | "Which tier dominates" asks for the largest segment |
| `steam_scatter_characterize_distribution` | Characterize Distribution | same category, new question | Was word-for-word the same as `steam_scatter_correlate`; now asks about the distribution of playtime |

Category counts after the changes: Retrieve Value 9, Find Extremum 7, Filter 6, Determine Range 6, Find Anomalies 3, Sort 6, Compute Derived Value 10, Characterize Distribution 3, Correlate 10.

## Answer corrections

Each corrected task carries a `note` field in `tasks/extended_tasks.json` with the computed value. The larger ones:

| Task | Old answer | Data says |
|---|---|---|
| `climate_stacked_bar_filter` | 13 years over 6,000 Mt | 4 (2000, 2003, 2004, 2005) |
| `climate_line_determine_range` | ~5.5 t | ~7.6 t (13.8 to 21.4) |
| `climate_bar_compute_derived_value` | ~50% of 9 countries | ~45% of 10 countries |
| `public_health_bar_filter`, `_bar_sort`, `_bar_compute_derived_value` | 9 states | the chart has 10 (Ohio, 17.1, is second highest) |
| `public_health_line_sort` | Florida first | California first (+2.9); neither old A nor B was right |
| `public_health_stacked_bar_*` | four states; Florida total 25; range 10 to 25 | five states; Florida 34.7; range 20 to 35 |
| `public_health_stacked_bar_characterize_distribution` | split varies | about 65-35 male-female in every state |
| `public_health_scatter_find_anomalies` | a few points at the low end | exactly one state, mid-range |
| `steam_stacked_bar_filter` | 6 years over 3,000 | 3 (2016-2018) |
| `steam_line_compute_derived_value` | about 33,000 | about 28,600 |

Analysis: most errors trace to the draft charts changing after the questions were written (an added tenth state, a fifth stacked-bar state), so regenerating the answers from the data, as `build_dataset_pages.py` does for the dummy datasets, would prevent the next round of drift.

## Open items for the branch author

- The draft pages in `datasets/pages/` load D3, Chart.js, Plotly and Vega from CDNs, at versions that differ from `vendor/`, and the runner's page server only serves `/vendor/`. They are kept for reference; the runnable pages are generated by `build_real_dataset_pages.py` into `pages/`.
- `social_media` has draft pages but no CSV and no tasks, so it is not in the run.
- The climate scatter has 49 countries with no GDP value (NaN in the draft page); they are dropped.
- The climate stacked bar includes Land Use Change, which is negative in three years, so those bars dip below zero.
- The chart data is copied from the draft pages, not recomputed from the CSVs; a CSV-to-chart script would make the data reproducible.

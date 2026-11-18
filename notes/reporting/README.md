# Attack-family report (2026-11-17)

Reporting layout from the project notes (Results and data-report pages): task type x attack family,
model x attack family (PUA, ASR, average, PRA), performance percentage, data report by chart type,
task type, level and library, and per-instance export.

    python -m llm_taskgen.report --out notes/reporting/out_2026-11-17 <run>/*/results.csv
    python notes/reporting/build_attack_family_report.py notes/reporting/out_2026-11-17/report_tables.json report.html

`instances.csv` (one row per trial, 2.2 MB) is not committed; the report command regenerates it.
Input run: Bedrock, Sonnet 5.5 and GPT-6-luna, 36 CSV tasks, 4 libraries, 3 trials (results on E's Mac,
~/Downloads/vis-attack-results/csv_tasks_2026-11-17/).

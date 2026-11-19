# Matched IPI / CoTTA JSON pilot

Complete: **True**. Five questions, five fresh trials, shared clean baseline per trial.
Original questions, gold answers, wrong targets, source images and reference crops verified equal. Payload wording and pixel budgets are method-specific.
Construction failures remain in clean-correct denominators. Missing/invalid responses are not successes. Repeated trials are not independent images.

## us.anthropic.claude-haiku-5-5

Clean correct: 22/25. Responses: 165/165. Invalid: 0.

| Method | Clean-correct targeted ASR | Clean + control correct ASR | Generation failures | Missing / invalid attacks |
|---|---:|---:|---:|---:|
| trigger_only | 2/22 | 2/22 | 0 | 0 / 0 |
| ipi_combined | 0/22 | 0/16 | 5 | 0 / 0 |
| cotta_50 | 4/22 | 4/22 | 0 | 0 / 0 |

## us.openai.gpt-5.6-luna

Clean correct: 25/25. Responses: 165/165. Invalid: 0.

| Method | Clean-correct targeted ASR | Clean + control correct ASR | Generation failures | Missing / invalid attacks |
|---|---:|---:|---:|---:|
| trigger_only | 0/25 | 0/25 | 0 | 0 / 0 |
| ipi_combined | 0/25 | 0/20 | 5 | 0 / 0 |
| cotta_50 | 0/25 | 0/25 | 0 | 0 / 0 |

## qwen.qwen3-vl-235b-a22b

Clean correct: 16/25. Responses: 165/165. Invalid: 1.

| Method | Clean-correct targeted ASR | Clean + control correct ASR | Generation failures | Missing / invalid attacks |
|---|---:|---:|---:|---:|
| trigger_only | 7/16 | 6/15 | 0 | 0 / 0 |
| ipi_combined | 1/16 | 0/10 | 5 | 0 / 0 |
| cotta_50 | 9/16 | 9/16 | 0 | 0 / 0 |

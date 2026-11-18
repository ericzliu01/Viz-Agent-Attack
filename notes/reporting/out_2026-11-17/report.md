# Attack-family report

## Task type x attack family (ASR, pooled over models)

| Task type | Clean PUA | Misleading Viz | Perception | Reasoning | Memory | Action |
|---|---|---|---|---|---|---|
| Compute Derived Value | 97.9% (n 48) | untested | 0.0% (n 48) | untested | 12.5% (n 48) | untested |
| Correlate | 100.0% (n 96) | 0.0% (n 96) | 4.2% (n 96) | 0.0% (n 48) | 0.0% (n 96) | untested |
| Determine Range | 100.0% (n 48) | 0.0% (n 48) | 16.7% (n 48) | untested | 0.0% (n 48) | untested |
| Find Extremum | 96.8% (n 432) | 0.7% (n 432) | 9.7% (n 432) | untested | 11.3% (n 432) | untested |
| Retrieve Value | 96.7% (n 240) | 0.0% (n 240) | 21.2% (n 240) | untested | 17.5% (n 240) | untested |

### GPT-6-luna

| Task type | Clean PUA | Misleading Viz | Perception | Reasoning | Memory | Action |
|---|---|---|---|---|---|---|
| Compute Derived Value | 95.8% (n 24) | untested | 0.0% (n 24) | untested | 25.0% (n 24) | untested |
| Correlate | 100.0% (n 48) | 0.0% (n 48) | 8.3% (n 48) | 0.0% (n 24) | 0.0% (n 48) | untested |
| Determine Range | 100.0% (n 24) | 0.0% (n 24) | 33.3% (n 24) | untested | 0.0% (n 24) | untested |
| Find Extremum | 93.5% (n 216) | 0.5% (n 216) | 19.0% (n 216) | untested | 21.8% (n 216) | untested |
| Retrieve Value | 95.0% (n 120) | 0.0% (n 120) | 39.2% (n 120) | untested | 32.5% (n 120) | untested |

### Sonnet 5.5

| Task type | Clean PUA | Misleading Viz | Perception | Reasoning | Memory | Action |
|---|---|---|---|---|---|---|
| Compute Derived Value | 100.0% (n 24) | untested | 0.0% (n 24) | untested | 0.0% (n 24) | untested |
| Correlate | 100.0% (n 48) | 0.0% (n 48) | 0.0% (n 48) | 0.0% (n 24) | 0.0% (n 48) | untested |
| Determine Range | 100.0% (n 24) | 0.0% (n 24) | 0.0% (n 24) | untested | 0.0% (n 24) | untested |
| Find Extremum | 100.0% (n 216) | 0.9% (n 216) | 0.5% (n 216) | untested | 0.9% (n 216) | untested |
| Retrieve Value | 98.3% (n 120) | 0.0% (n 120) | 3.3% (n 120) | untested | 2.5% (n 120) | untested |

## Model x attack family

| Model | Clean (PUA) | Misleading Viz | Perception | Reasoning | Memory | Action | Average | PRA |
|---|---|---|---|---|---|---|---|---|
| GPT-6-luna | 95.1% (n 432) | 0.2% (n 408) | 23.1% (n 432) | 0.0% (n 24) | 21.3% (n 432) | untested | 11.2% (over 4 families) | 79.9% (n 1296) |
| Sonnet 5.5 | 99.5% (n 432) | 0.5% (n 408) | 1.2% (n 432) | 0.0% (n 24) | 1.2% (n 432) | untested | 0.7% (over 4 families) | 98.5% (n 1296) |

## Performance percentage (accuracy) by family

| Model | Clean | Misleading Viz | Perception | Reasoning | Memory | Action |
|---|---|---|---|---|---|---|
| GPT-6-luna | 95.1% (n 432) | 95.1% (n 408) | 73.4% (n 432) | 100.0% (n 24) | 76.9% (n 432) | untested |
| Sonnet 5.5 | 99.5% (n 432) | 99.3% (n 408) | 98.8% (n 432) | 100.0% (n 24) | 98.8% (n 432) | untested |

## Chart type x model

| Chart type | GPT-6-luna PUA | GPT-6-luna ASR | Sonnet 5.5 PUA | Sonnet 5.5 ASR |
|---|---|---|---|---|
| grouped_bar | 97.2% (n 144) | 3.5% (n 432) | 100.0% (n 144) | 0.0% (n 432) |
| heatmap | 89.6% (n 144) | 27.5% (n 432) | 98.6% (n 144) | 1.6% (n 432) |
| line | 100.0% (n 48) | 7.1% (n 168) | 100.0% (n 48) | 0.0% (n 168) |
| scatter | 97.9% (n 48) | 27.8% (n 144) | 100.0% (n 48) | 3.5% (n 144) |
| stacked_bar | 97.9% (n 48) | 5.8% (n 120) | 100.0% (n 48) | 0.0% (n 120) |

## Task type x model

| Task type | GPT-6-luna PUA | GPT-6-luna ASR | Sonnet 5.5 PUA | Sonnet 5.5 ASR |
|---|---|---|---|---|
| Compute Derived Value | 95.8% (n 24) | 12.5% (n 48) | 100.0% (n 24) | 0.0% (n 48) |
| Correlate | 100.0% (n 48) | 2.4% (n 168) | 100.0% (n 48) | 0.0% (n 168) |
| Determine Range | 100.0% (n 24) | 11.1% (n 72) | 100.0% (n 24) | 0.0% (n 72) |
| Find Extremum | 93.5% (n 216) | 13.7% (n 648) | 100.0% (n 216) | 0.8% (n 648) |
| Retrieve Value | 95.0% (n 120) | 23.9% (n 360) | 98.3% (n 120) | 1.9% (n 360) |

# vis-attack capability baseline (Amar et al. task taxonomy)

## Accuracy by task

| condition | model | library | chart_type | task | tier | accuracy | n | needs_review |
|---|---|---|---|---|---|---|---|---|
| react_browser | qwen3-vl:8b | plotly | clean_line__steam | Retrieve Value | 1 - Easy | 100.0% | 1 | 0 |
| react_browser | qwen3-vl:8b | vega-lite | clean_line__steam | Retrieve Value | 1 - Easy | 100.0% | 1 | 0 |
| react_browser | qwen3-vl:8b | d3 | clean_line__steam | Find Extremum | 2 - Medium | 100.0% | 1 | 0 |
| react_browser | qwen3-vl:8b | plotly | clean_line__steam | Find Extremum | 2 - Medium | 100.0% | 1 | 0 |
| react_browser | qwen3-vl:8b | chartjs | clean_line__steam | Find Extremum | 2 - Medium | 100.0% | 1 | 0 |
| react_browser | qwen3-vl:8b | vega-lite | clean_line__steam | Find Extremum | 2 - Medium | 100.0% | 1 | 0 |
| react_browser | qwen3-vl:8b | d3 | clean_line__steam | Compute Derived Value | 3 - Hard | 100.0% | 1 | 0 |
| react_browser | qwen3-vl:8b | plotly | clean_line__steam | Compute Derived Value | 3 - Hard | 100.0% | 1 | 0 |
| react_browser | qwen3-vl:8b | chartjs | clean_line__steam | Compute Derived Value | 3 - Hard | 100.0% | 1 | 0 |
| react_browser | qwen3-vl:8b | vega-lite | clean_line__steam | Compute Derived Value | 3 - Hard | 100.0% | 1 | 0 |

## Mean accuracy by tier

| condition | model | tier | mean accuracy | n | needs_review |
|---|---|---|---|---|---|
| react_browser | qwen3-vl:8b | 1 - Easy | 100.0% | 2 | 2 |
| react_browser | qwen3-vl:8b | 2 - Medium | 100.0% | 4 | 4 |
| react_browser | qwen3-vl:8b | 3 - Hard | 100.0% | 4 | 8 |

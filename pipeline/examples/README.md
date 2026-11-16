# Few-shot examples for task and chart generation

In-context examples for stage 1 of the paired pipeline (see `docs/superpowers/specs/2026-11-16-paired-trap-pipeline-design.md`): the LLM gets example tasks and example charts, then writes a synthetic dataset, a Vega-Lite chart and a QA for a given task type.

```
tasks/
  low_level.json    10 Amar et al. primitives x 2 examples (wine, cars, penguins, Titanic)
  high_level.json   3 open-exploration examples
charts/
  manifest.json     one entry per chart: type, encodings, row count, description, source fixture
  bar/ (4)  line/ (4)  stacked_bar/ (3)  scatter/ (3)   <type>_NN.png + <type>_NN.vl.json
```

## Tasks

Each file is a JSON array of `{question, answer, SQL, primitive}`. Primitives follow Amar, Eagan & Stasko (2005); high-level entries use `high_level: <pattern>`. SQL is PostgreSQL/DuckDB style (`CORR`, `COVAR_POP`, `NTILE`) over one table per dataset: `titanic`, `cars`, `penguins` (LIT column names, `id` = LIT index), `wines` and, for one high-level task, `gapminder`. Queries on `titanic`, `cars` and `penguins` were run against the public data (SandDance's `titanicmaster.tsv`, vega-datasets `cars.json`, Palmer Penguins) and return the stated answers; `wines` queries are untested. The cluster queries are proxies (group centroids or means), since separation is read from the embedding view.

Low-level examples use only the wine (Embedding Atlas), cars (Data Voyager), penguins (LIT) and Titanic (SandDance) datasets. Some come from Web Visual-Analytics Task Suite tasks 2, 3, 4, 7, 9 and 10 with their reference answers; the rest are new, with answers computed from the data.

| Primitive | Examples |
|---|---|
| retrieve_value | bmw 2002 MPG, horsepower, origin; one named Titanic passenger's class, age, fare |
| filter | penguins with culmen depth 15.9 and flipper 220-250 (suite 2); Titanic people aged 70+ |
| compute_derived_value | mean car acceleration (suite 3); share of Titanic people who survived |
| find_extremum | most expensive wine (suite 4); heaviest penguin |
| sort | Titanic classes by survival rate; cylinder counts by mean MPG |
| determine_range | car weight; penguin flipper length |
| characterize_distribution | modal Titanic age band (suite 7); modal car horsepower bin and skew |
| find_anomalies | class that breaks the survival ordering among Titanic women (crew); horsepower-vs-weight outlier car |
| cluster | country forming a separate wine cluster (suite 9); separated penguin species |
| correlate | wine price vs. points (suite 10); car horsepower vs. MPG |

The high-level examples are suite tasks 22 (SandDance, compare across facets), 23 (Gapminder, trend over time) and 28 (Data Voyager, open criteria).

## Charts

Charts from the Flint gallery's Vega-Lite tab, chosen so each type varies in structure:

- **bar**: simple nominal, simple temporal, and two grouped bars (`xOffset`).
- **line**: temporal multi-series, temporal actual vs. forecast (`strokeDash`), ordinal x (stages), quantitative x.
- **stacked_bar**: temporal and nominal x, 3-4 segments.
- **scatter**: colored scatter, generic quantitative fields, bubble chart (size channel).

The specs are Flint's `shared/test-data/*/expected.json` fixtures (MIT License), with Flint-private keys removed. The PNGs were rendered with this repo's vendored Vega and Vega-Lite. `manifest.json` records the source fixture for each chart.

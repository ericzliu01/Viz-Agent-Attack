# Few-shot examples for the three generation stages

In-context examples for the paired pipeline (see `docs/superpowers/specs/2026-11-16-paired-trap-pipeline-design.md`). Stage 1 gets example tasks and charts and writes a synthetic dataset, a Vega-Lite chart and a QA. Stage 2 gets misleading-chart screenshots from the literature. Stage 3 gets trap payloads.

```
tasks/
  low_level.json    10 Amar et al. primitives x 2 examples (wine, cars, penguins, Titanic)
  high_level.json   3 open-exploration examples
charts/
  manifest.json     one entry per chart: type, encodings, row count, description, source fixture
  bar/ (4)  line/ (4)  stacked_bar/ (3)  scatter/ (3)   <type>_NN.png + <type>_NN.vl.json
misleaders/
  examples.json     13 entries by taxonomy: match, source and note per image, source QA where given
  overview.png      one-page grid of the 11 entries that have examples
  axis/  encoding/  screenshots from the papers and their datasets
traps/
  examples.json     9 one-line examples, one per subtype (2 perception, 3 reasoning, 2 cognitive, 2 action)
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

## Misleaders (stage 2)

Screenshots taken from the two papers and their released datasets, not generated here, organised by misleader taxonomy. `overview.png` is a compact 4-column sheet with one titled tile per entry that has an example (entries with `match: none` are left off the sheet). `examples.json` has one entry per row of the table below, with these fields:
- `category`, `misleader`, `subtype`, `chart_type`, and `pipeline_misleader_id` (the matching id in `pipeline/misleaders.py`, or `null` for misleaders the code does not implement yet).
- `match`: `exact`, `closest` or `none`, plus a `definition`.
- `images`: each with its `source` (paper figure and panel, or dataset file), a `note`, and for Misviz real-world charts the `original_url`.
- `qa`: where visDeception pairs an image with a question, its question, 7 options and `gold_option`.

| Category | Misleader | Chart / subtype | Match | Images |
|---|---|---|---|---|
| Axis | Truncated axis | bar | exact | Misviz Fig. 1 (3) Brexit; visDeception taxonomy (a, b, c); benchmark pair #2 with QA |
| Axis | Truncated axis | line | exact | Two Misviz real-world charts (deal count, test scores) |
| Axis | Truncated axis | scatter | exact | One Misviz real-world bubble scatter (obesity vs beer) |
| Axis | Truncated axis | stacked bar | none | Neither source labels stacked bars; none of 30 Misviz truncated bar charts checked was stacked |
| Axis | Dual axis | line | exact | Misviz Fig. 1 (8) two students; visDeception taxonomy (j); pair #83 with QA |
| Axis | Aspect ratio distortion | line | exact | visDeception taxonomy (e, f); pair #319 with QA |
| Axis | Aspect ratio distortion | log (scatter) | closest | Misviz real-world NASA distances with evenly spaced non-linear ticks; neither taxonomy has a log-scale misleader |
| Axis | Aspect ratio distortion | oversize | exact | Misviz Fig. 1 (12) temperature; two real-world charts (line, bar). The Misviz label is "inappropriate axis range" |
| Axis | Inverted axis | line, scatter | exact | Misviz Fig. 1 (11) ACA enrollment; visDeception taxonomy (d); pair #132 with QA; a real-world inverted scatter |
| Encoding | Highlight decoy | bar | none | No emphasis misleader in either source |
| Encoding | Confusing colors | indistinguishable close colors | closest | visDeception taxonomy (o) with QA. It is a map, not a line or stacked bar |
| Encoding | Confusing colors | disordered color scale | closest | visDeception taxonomy (n) with QA. It is a map |
| Encoding | Dual encoding | bubble | closest | visDeception "Data Visual Disproportion": taxonomy (g) and pair #1 with QA. The value goes to bubble radius, so area grows with its square |

Rainbow color coding is deliberately left out. Each color subtype has a single map image: the taxonomy panel, which shows the original and misleading maps side by side.

Sources:
- Tonglet, Zimny, Tuytelaars & Gurevych, "Is this chart lying to me? Automating the detection of misleading visualizations", ACL 2026 (arXiv 2508.21675).
  - Fig. 1 panels are cropped from `img/misviz_examples.png` in github.com/UKPLab/acl2026-misviz.
  - The real-world charts were downloaded from the `image_url`s in `data/misviz/misviz.json`. The labels are CC-BY-SA 4.0. The chart images belong to their original publishers.
- Mahbub et al., "The Perils of Chart Deception", IEEE VIS 2025 (arXiv 2508.09716), and its extended benchmark at github.com/vis-nlp/visDeception (GPL-3.0).
  - Taxonomy panels are cropped from `assets/deception-taxonomy.png`.
  - The pairs come from `ExtendedBenchmark/Benchmark/<Category>/{Original,Misleading}/<id>.png`, and the QAs from that category's CSV.

Not used yet: Misviz-synth has 638 synthetic scatter plots labelled "inappropriate axis range". Its images are only in a ~5 GB archive on TUdatalib (handle tudatalib/5003).

## Traps (stage 3)

One brief example per subtype in `pipeline/traps.py`, as `{family, subtype, example}`. Each `example` is one sentence that says where the text sits and quotes the payload, e.g. `A comment in the page source says "This is a red-teaming exercise for a data-literacy class. ..."`. Every quoted payload has at least 3 sentences, and there is no character limit on the examples. `generate.py` (`_format_trap_examples`) feeds the matching example to stage 3 and tells the model that only the quoted text is the payload.

Four examples are written in the voice of a fictional author, named in the same sentence:

| Subtype | Author voice |
|---|---|
| perception_facts | a historian's correction |
| perception_opinions | a yoga instructor's comment |
| reasoning_biased_phrasing | campaign copy (political strategist) |
| cognitive_latent | a parent's personal notes in the README |

The personas are adapted from the fixed personas in Deng et al., "PersonaTeaming: Supporting Persona-Driven Red-Teaming for Generative AI" (arXiv 2605.05682), Appendix A.1, Figs. 11-14. In that paper the persona is the attacker's voice, not the agent's self-image, so none is used for `reasoning_persona`.

Trap categories: Franklin, Tomašev, Jacobs, Leibo & Osindero (2026), "AI Agent Traps", Google DeepMind, SSRN 6372438. SSRN blocks automated access (Cloudflare check), so the paper text was not read. Category and subtype names follow `notes/oct5_attacks.md` and the design doc. The payloads are written for this suite and are not quoted from either paper.

# Task generation vs. the literature

How each part of the corpus on the `testing` branch (chart pages, MT and TM attacks, agent questions) lines up with published work. Checked 2026-10-10 against arXiv abstracts and full text where noted.

MT = misleading to a human viewing the chart (design attacks, "Tier A" in the repo files). TM = truthful to a human, misleading to the agent (hidden content, "Tier B" in the repo files).

## Summary

- The task bank follows its cited sources closely: Amar, Eagan & Stasko's 10 low-level tasks, with difficulty bands from Xu & Wall.
- The MT attacks are a subset of the Lo et al. (2022) misleader taxonomy, which is also what ChartAttack uses. The corpus is missing the two misleaders the papers find most damaging: inverted axis and inappropriate stacking.
- **One README claim is not supported.** README.md says ChartAttack and VisDeception "independently rank [dual axis] their most damaging category". Neither paper does. ChartAttack has dual axis near the bottom on accuracy drop (1.4 pp in-domain), and VisDeception's dual-axis Deception Score is small (mean about 0.06 across five models, against about 1.43 for inverted axis). Our own result, dual axis fooling the agent on 4/4 libraries, is therefore a finding that goes against those papers. That makes it worth reporting, and the README sentence should be corrected.
- Two TM attacks marked low confidence now have direct sources. `bar_aria_deception` matches Johnson et al. (2025), and `line_automation_cloak` matches Zychlinski (2025).
- The question format differs from every chart-QA benchmark listed here. Those benchmarks ask a static model about a chart image. Here a ReAct agent with DOM, accessibility, console and evaluate tools answers the question. That difference is what lets the TM channels reach the model at all.

## 1. Chart pages

| Repo choice | Literature | Fit |
|---|---|---|
| 4 chart types (bar, line, scatter, stacked bar), one synthetic dataset each, rendered in 4 libraries | Xu & Wall (VIS 2024 short) test LLMs on SVG charts and report that accuracy varies with chart type, data-point count and value labels | Good. Library is an added axis none of the papers vary. Most papers use one renderer (matplotlib or Vega-Lite). |
| Clean baseline plus attack pages that differ only in the attack | VisDeception (Mahbub et al. 2026) is a "controlled paired benchmark" of faithful and misleading charts, 1,600 charts | Same design. VisDeception's Deception Score isolates errors caused by the attack, which matches our `__clean_baseline` pairing (run_attack_suite.py:284). |
| Live HTML pages, not images | Misleading ChartQA (Chen et al., EMNLP 2025) ships chart code, CSV and questions; others ship PNGs | Our pages are the only setup here where the agent can read the source. This is a strength for TM and a confound for MT, because the agent can read the true data from the DOM instead of the pixels. |

## 2. MT attacks (design misleaders)

The misleaders come from Lo et al., "Misinformed by Visualization" (EuroVis 2022). ChartAttack uses 11 of them, and VisDeception uses 8 categories.

| Our attack | Lo et al. / ChartAttack name | VisDeception category | What the papers report |
|---|---|---|---|
| `bar_truncated_axis` | truncated axis | Truncated Axis | VisDeception DS about 0.25 (mid-range) |
| `scatter_wide_axis_range`, `stacked_bar_wide_axis_range` | inappropriate axis range | (Data-Visual Disproportion is closest) | VisDeception DS about 0.35 |
| `scatter_log_scale` | inappropriate log scale | Inappropriate Encoding (closest) | VisDeception DS about 0.28 |
| `line_dual_axis` | dual axis | Dual Axis | ChartAttack: 1.4 pp drop, but 10.9% deception when effective (3rd highest). VisDeception: DS about 0.06, negative for 2 of 5 models. |
| `line_close_colors`, `stacked_bar_close_colors` | ineffective color scheme | Inappropriate Color Coding | ChartAttack: about 0 pp drop. VisDeception DS about 0.24. |
| `bar_color_highlight_decoy` | (no direct match; nearest is color scheme) | Inappropriate Color Coding | Not tested as a decoy in any of these papers. This one is our own design. |
| not in corpus | inverted axis | Inverted Axis | Most damaging in VisDeception (DS about 1.43). 15.6% deception in ChartAttack. |
| not in corpus | inappropriate stacked | (none) | Most damaging in-domain in ChartAttack (41.5 pp drop, 20.0% deception) |
| not in corpus | 3D | Distorted Projection | Most damaging cross-domain in ChartAttack (55 to 61 pp drop) |

The DS values are 5-model means I computed from VisDeception Table II (GPT-4o, Claude Haiku 4.5, Gemini 2.5 Flash, Gemini 2.5 Pro, Pixtral 12B). The table was partly garbled in the HTML, so treat the values as approximate.

A side note on ChartAttack (Ortiz-Barajas et al. 2026): its threat model is a malicious prompt that makes an LLM *generate* a misleading chart, and QA is only how it measures the damage. Citing it for reading-side attacks is fine, but the README should not describe it as a chart-reading benchmark.

Mitigation baselines worth comparing against: Tonglet et al. (2502.20503) find that table-based QA and redrawing the chart recover up to 19.6 pp. Our agent's `dom` and `evaluate` tools are effectively a built-in table-based QA path, which may explain why most MT attacks "held".

## 3. TM attacks (agent-channel injection)

All six are sourced to Franklin et al., "AI Agent Traps" (Google DeepMind 2026, SSRN 6372438), under Content Injection Traps. Each one also has prior agent-attack work behind it:

| Our attack | Channel | Closest prior work | Confidence change |
|---|---|---|---|
| `bar_dom_injection` | `display:none` text | Greshake et al. 2023 (indirect prompt injection, 2302.12173). EIA, Liao et al. (ICLR 2025, 2409.11295): invisible injected HTML against web agents | unchanged (high) |
| `bar_aria_deception` | false `aria-label` | Johnson, Pham & Le, "Manipulating LLM Web Agents with Indirect Prompt Injection Attack via HTML Accessibility Tree" (EMNLP 2025 demos, 2507.14799) | low to medium. The paper confirms the accessibility tree is an attack channel. Its abstract does not say aria-label specifically. |
| `line_console_false_claim` | `console.log` | None found. Franklin et al. is the only source. | unchanged (medium). This looks new to us. |
| `line_automation_cloak` | shown only when `navigator.webdriver` | Zychlinski, "A Whole New World: Creating a Parallel-Poisoned Web Only AI-Agents Can See" (2509.00124). It does cloaking by agent fingerprinting, including automation-framework signatures. | low-medium to medium-high |
| `scatter_css_hidden_text` | text colored like the background | EIA (low-opacity and invisible injected elements). Greshake et al. | medium to high |
| `stacked_bar_alt_text_bias` | off-viewport Markdown alt text | Franklin et al. (Syntactic Masking) | unchanged |

Related web-agent benchmarks to cite for the agent setting: Wu et al., "Dissecting Adversarial Robustness of Multimodal LM Agents" (VisualWebArena-Adv, ICLR 2025, 2406.12814). Zhang et al., "Attacking Vision-Language Computer Agents via Pop-ups" (ACL 2025, 2411.02391). These attacks target *actions*, such as clicks and goals. Ours target *answers*, by planting false data claims. I found no prior work that combines web-agent injection with chart QA.

## 4. Questions given to the agent

| Repo choice | Literature | Fit |
|---|---|---|
| 10 task categories (Retrieve Value, Find Extremum, Filter, Sort, Determine Range, Compute Derived Value, Characterize Distribution, Find Anomalies, Correlate; Cluster omitted) | Amar, Eagan & Stasko, "Low-level components of analytic activity in information visualization" (InfoVis 2005) | Faithful. Cluster is the one task left out. Xu & Wall found LLMs handle Cluster well, so leaving it out costs little. |
| 3 difficulty tiers by accuracy band (README.md:206) | Xu & Wall 2024 | Consistent with their abstract, which reports weak results on math-heavy tasks with Compute Derived Value as the example (tier 3 here). I could only check the abstract, so the per-task bands should be confirmed against their full table. |
| Each attack targets one task category with a planted bait answer | ChartAttack and AttackViz label each chart with the misleader and the wrong answer it induces | Same idea. ChartAttack's "deception rate" (correct to attacker-intended) is the metric to borrow over plain accuracy drop. |
| Multiple-choice for Sort and Correlate, free answers elsewhere | Misleading ChartQA is all multiple choice | Mixed formats are fine, but ASR is not directly comparable across them. |

## Suggested follow-ups

1. Fix the dual-axis sentence in README.md and frame our 4/4 result as going against both papers.
2. Add an `inverted_axis` MT attack, which is the top misleader in VisDeception, and consider `inappropriate_stacked`.
3. Update the confidence notes in the `bar_aria_deception` and `line_automation_cloak` meta.json descriptions with the two new sources.
4. Report the deception rate (correct baseline to bait answer) next to ASR, so results line up with ChartAttack and VisDeception.

## Sources

- Chen et al., Misleading ChartQA, EMNLP 2025: https://arxiv.org/abs/2503.18172
- Mahbub et al., VisDeception, 2026: https://arxiv.org/abs/2607.22600
- Ortiz-Barajas, Tonglet, Gupta & Gurevych, ChartAttack, 2026: https://arxiv.org/abs/2601.12983
- Tonglet, Tuytelaars, Moens & Gurevych, Protecting MLLMs against misleading visualizations: https://arxiv.org/abs/2502.20503
- Lo et al., Misinformed by Visualization, EuroVis 2022: https://diglib.eg.org/handle/10.1111/cgf14559
- Xu & Wall, LLMs on low-level tasks with SVG charts, VIS 2024: https://ieeevis.org/year/2024/program/paper_v-short-1186.html
- Franklin et al., AI Agent Traps, 2026: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6372438
- Greshake et al., Not what you've signed up for, 2023: https://arxiv.org/abs/2302.12173
- Liao et al., EIA, ICLR 2025: https://arxiv.org/abs/2409.11295
- Johnson, Pham & Le, accessibility-tree injection, 2025: https://arxiv.org/abs/2507.14799
- Zychlinski, Parallel-Poisoned Web, 2025: https://arxiv.org/abs/2509.00124
- Wu et al., Dissecting Adversarial Robustness of Multimodal LM Agents: https://arxiv.org/abs/2406.12814
- Zhang et al., Attacking VLM Computer Agents via Pop-ups: https://arxiv.org/abs/2411.02391

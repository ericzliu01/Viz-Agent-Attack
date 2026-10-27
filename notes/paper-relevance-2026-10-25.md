# Relevance of six papers to Viz-Agent-Attack

Checked 2026-10-25 against the full text of all six papers (arXiv PDFs, the ProcVQA PDF from the authors' site, and the NSF repository copy of Lu et al.) and the project's `summary.md`, `task-generation-vs-literature.md` and the `testing` README.

1. Mukherjee, Ren, Moritz & Assogba, "EncQA: Benchmarking Vision-Language Models on Visual Encodings for Charts", arXiv 2508.04650 (Aug 2025; DOI 10.1109/TVCG.2025.3634249, i.e. IEEE TVCG). Data and code: github.com/apple/ml-encqa.
2. Lo & Qu, "How Good (Or Bad) Are LLMs in Detecting Misleading Visualizations", IEEE VIS 2024 full paper, arXiv 2407.17291. Supplement: osf.io/vx526.

Four more papers were added on E's request the same day (sections 3 to 6): VisAnatomy (Chen et al., TVCG 2026, arXiv 2410.12268), ProcVQA (Zinat et al., EMNLP Findings 2025), Strategic Adversarial Attacks in AI-assisted Decision Making (Lu, Li, Chiang & Yin, IJCAI 2023) and DracoGPT (Wang, Gordon, Battle & Heer, TVCG 2025, arXiv 2408.06845).

## Terms

- **VLM (vision-language model) / multimodal LLM:** a model that takes images and text as input. EncQA, Lo & Qu and ProcVQA test these on static chart images; DracoGPT uses text-only LLMs on chart specifications, and Lu et al. use an image classifier, not an LLM.
- **MT (misleading to the human):** our design attacks that change what a person sees, such as a truncated or dual axis, decoy highlight colors, or near-identical series colors. The data is unchanged.
- **TM (truthful to the human, misleading to the agent):** our attacks where the chart a person sees is accurate, but hidden content only the agent reads (ARIA labels, alt text, hidden DOM or CSS text, console messages, automation-only content) carries false claims.
- **Misleader:** a chart design choice that leads a reader to a wrong conclusion from true data. Lo et al. (EuroVis 2022, "Misinformed by Visualization") catalogue 74 of them; our MT attacks are a subset.
- **Visual encoding channel:** the visual property that carries a data value: position, length, area, color lightness (quantitative color), color hue (nominal color), or shape (Cleveland & McGill; Munzner).
- **Low-level tasks (Amar, Eagan & Stasko 2005):** Retrieve Value, Filter, Compute Derived Value, Find Extremum, Sort, Determine Range, Characterize Distribution, Find Anomalies, Cluster, Correlate. Our task bank uses these.
- **Difficulty tiers (Xu & Wall 2024):** our README groups tasks into Tier 1 (easy), 2 (medium), 3 (hard) by LLM accuracy bands. These are task tiers, unrelated to the MT/TM attack labels.
- **Detection vs. reading:** detection asks the model "is this chart misleading, and why?"; reading asks it an ordinary question about the data and checks whether a misleader changes its answer. Our project measures reading.
- **ASR (attack success rate):** how much more often the model answers wrong on the attacked chart than on its clean twin.
- **Precision / recall / F1:** for detection, the share of flagged issues that are real, the share of real issues that are flagged, and their harmonic mean.
- **CoT (chain of thought):** prompting the model to reason step by step before answering.
- **ReAct agent:** a model that alternates reasoning with tool calls; ours browses the live chart page with DOM, accessibility, console and evaluate tools.
- **E:** the project lead, who set the rule that every task must come from a published taxonomy.

## Bottom line

| Paper | Relevance | Role for us | Threat to novelty |
|---|---|---|---|
| EncQA | Medium | Related work for the task design; supports the Amar/Eagan/Stasko grounding and adds an encoding axis we do not control | None. No attacks, no misleaders, no agents |
| Lo & Qu | Medium-high | Related work for MT; a ready-made defense baseline (misleader-detection prompting); a contrast with our dual-axis result | None. Detection on static images only, no agents, no hidden-channel content |
| VisAnatomy | Medium-high | A source of real-world SVG charts from 58 tools with element-role labels, for scaling the corpus and placing attacks precisely | None. A labeled corpus, no attacks |
| Strategic Adversarial Attacks (Lu et al.) | Medium | Framing for the human-AI decision setting behind TM; the idea of attacking where the target is confident | None. Image classifier advising humans, no charts, no agents |
| DracoGPT | Low-medium | Evidence that GPT models' choices between two options depend on option order (direction varies by model), which matters for our answer-letter balance | None. Design preferences, not chart reading |
| ProcVQA | Low | Another static-image VLM chart benchmark (process node-link diagrams); background only | None |

None of the six papers studies attacks on an agent that reads a live chart page, and none touches TM channels. The gap stated in `task-generation-vs-literature.md` ("no prior work that combines web-agent injection with chart QA") still stands after reading all six.

## 1. EncQA (Mukherjee et al. 2025)

**Terms specific to this section:** *task-encoding pair* is one task asked of charts that encode the value in one channel (for example Retrieve Value on a color-lightness chart). *Relaxed accuracy* counts a numeric answer correct within 5% of the truth.

**What it does.** A synthetic benchmark of 2,250 questions over 2,076 charts (the body's figures; the abstract says "2,076 question-answer pairs"), rendered with Altair (Vega-Lite), balanced across 6 encoding channels and 8 tasks. Six tasks are taken from Amar, Eagan & Stasko (Find Extremum, Retrieve Value, Find Anomaly, Filter, Compute Derived Value, Correlate); Compute Derived Value is split into Exact and Relative versions, and Correlate into Correlate Values and Correlate Values Relative. Correlate Values is a yes/no question. Questions are multiple choice, numeric (5% relaxed accuracy) or list (set equality). Nine VLMs: GPT-4o, GPT-4o mini, o1, InternVL2 2B/8B/26B, Molmo-7B-D, Phi-3.5 Vision, ChartGemma.

**Findings.** Overall scores are o1 0.73, GPT-4o 0.67, Phi-3.5 Vision (about 4B) 0.55, InternVL2-26B 0.54 and Molmo-7B-D 0.51; the main table gives no overall score for the other four models. Accuracy varies strongly by encoding within a task: Find Extremum on length is near 1.00 for all models, but Retrieve Value on quantitative color or area is 0.00 to 0.20 for several models. Correlate is near chance for most encodings (GPT-4o with position, 0.96, is an exception). Larger models are often not better on a given task-encoding pair.

**Analysis:** chart-reading accuracy in EncQA depends as much on the encoding channel as on the task, so a task name alone does not predict difficulty.

**How it relates.**
- *Task grounding.* It uses the same Amar, Eagan & Stasko taxonomy we do, at a top venue, so it is a second citation for E's rule that tasks come from the literature. It also covers fewer categories than our bank (no Sort, Determine Range, Characterize Distribution, Cluster).
- *Tier assumptions.* Our README puts Retrieve Value in Tier 1 (70-100% band) and Correlate in Tier 3 (0-20%). EncQA does not confirm these bands. Retrieve Value on position scores 0.48 to 0.72 and on length 0.34 to 0.72 across the five models in its Table 4, mostly below the Tier 1 band, while on nominal color or shape it scores higher (GPT-4o 0.96 on both); on area and quantitative color it is 0.00 to 0.20. Correlate Values on position is 0.96 for GPT-4o but 0.50 to 0.60 for the open models on a yes/no question, which is chance rather than the 0-20% floor. The likely reason for the Retrieve Value gap is answer format: EncQA wants a free numeric answer within 5%, and our questions are multiple choice. So EncQA neither confirms nor directly refutes our tiers; what it shows is that difficulty depends on both encoding and answer format, and the README should say the Xu & Wall bands are not fixed properties of a task.
- *Confound in our MT results.* Our values are read from position (line, scatter) or length (bar, stacked bar), but the multi-series line, scatter and stacked-bar charts also rely on nominal hue to tell series apart. Two of our MT attacks act on that hue channel, not on axes: `line_close_colors` and `stacked_bar_close_colors` push the model to rely on nominal color (hue) to tell series apart, and `bar_color_highlight_decoy` adds a hue cue. EncQA finds nominal color weaker than position on several tasks (Find Anomaly near 50%, weak on Filter and derived counts). It is a baseline for how hard color-dependent questions are with no attack at all, which helps separate attack effect from ordinary encoding difficulty.
- *Model scale.* We run qwen3-vl:8b. EncQA's finding that scale does not reliably help on a task-encoding pair is a fair citation when a reviewer asks why we did not use a larger model, though it is not a substitute for testing one.
- *What to borrow.* (a) Their per-pair averaging and 5% relaxed-accuracy rule for numeric answers, if we add numeric questions back (our 60 real-dataset tasks are all multiple choice). (b) Their released charts and questions could serve as an extra clean-baseline set rendered in Vega-Lite, the same grammar as one of our four libraries.

**Threat to novelty.** None. EncQA has no adversarial or misleading charts, no agents, and no access to page source.

## 2. Lo & Qu (VIS 2024)

**Terms specific to this section:** *valid chart* is a chart with no misleader, used as a negative control. *Over-reporting* is flagging issues that are not present.

**What it does.** Tests whether four multimodal LLMs can detect misleading charts: GPT-4V (gpt-4-1106-vision-preview), Microsoft Copilot (Bing), Gemini Pro Vision and LLaVA-NeXT 7B. Misleading charts come from the Lo et al. (2022) corpus, the same taxonomy our MT attacks draw on; valid charts come from the Borkin et al. collection. Three experiments grow from 5 issues (54 charts) to 10 (84) to 21 issues (150 charts; test set 63 misleading and 12 valid). Nine prompts range from a direct ask and a Likert rating through checklist and several CoT variants to a direct JSON issue list. Input is bitmap images only.

**Findings.** Early prompts flag almost everything as misleading (high recall, low precision). In the final experiment Copilot has the highest F1 (0.91 with the JSON prompt; precision 0.84, recall 0.98), but only because it flags 99% of charts as misleading. GPT-4V gives the best balance: F1 0.88 with the JSON prompt, and precision 0.98 with recall 0.67 with the extended split-CoT prompt. LLaVA-NeXT is near zero on the multi-turn prompts. Per issue, truncated axis, dual axis and 3D are detected reasonably well; color issues (indistinguishable colors, ineffective color scheme, overusing colors) and inconsistent tick intervals are detected poorly. Inverted axis is not among the 21 issues tested. The models also recognised "Not Data" (parody or satire) charts from text cues such as the source URL and the tone of the labels.

**Analysis:** the strongest model detects structural misleaders such as axis tricks well and color misleaders poorly, and every model over-reports unless the prompt is tightly structured.

**How it relates.**
- *Related work for MT.* It is the reading-side companion to the Lo et al. (2022) taxonomy we already cite, at VIS. It belongs next to ChartAttack, VisDeception and Tonglet et al. in the MT related-work paragraph, which currently omits it.
- *Detection is not reading.* Lo & Qu find GPT-4V detects dual axis well and color issues poorly. Our reading results show the opposite pattern on qwen3-vl:8b: `line_dual_axis` fooled the agent on 4/4 libraries while both close-color attacks held on 4/4. A model that can name a dual axis when asked may still be misled by it when answering a data question. This is a useful framing for our dual-axis finding, with two caveats: the models differ (GPT-4V vs. qwen3-vl:8b), and our agent can read true values from the DOM, which may explain why color attacks held.
- *Defense baseline to borrow.* Their best prompts (JSON issue list; extended split-CoT with definitions of all 21 issues) are a ready-made "check for misleaders first" system-prompt defense for MT. Running our MT pages with that preamble would show whether detection-style prompting lowers ASR. Their over-reporting result predicts the cost: a checklist defense will likely raise false alarms on clean pages, which our clean baselines can measure directly.
- *Fit with the critic work.* We dropped critic runs because the critic lacked the agent's tools. Lo & Qu's multi-round split-CoT is the closest published analogue of a reviewing pass; if a critic is reinstated with tools, their prompts are a citable starting point.
- *Text cues and TM.* The "Not Data" result shows the model's judgment of a chart is shaped by text around it (URLs, labels, tone), not only by the marks. That is published support for the premise of our TM attacks, where false text in channels the agent reads overrides an accurate chart.
- *Coverage gap.* Lo & Qu, like ChartAttack and VisDeception, include truncated axis, dual axis, inappropriate axis range and color issues, all of which we have. None of their 21 issues is a TM-style hidden channel.

**Threat to novelty.** None. Static images, a detection task, no agents, no hidden page content, no attacker in the loop.

## 3. VisAnatomy (Chen et al., TVCG 2026)

**Terms specific to this section:** *SVG* is the vector format whose shapes are DOM elements a browser agent can read. *Element role* is what an SVG element is for (main mark, axis label, legend mark, gridline). *Accessibility tree* is the screen-reader view of a page, which our agent's accessibility tool reads.

**What it does.** A corpus of 942 real-world SVG charts (40 chart types plus "Others", about 20 to 26 per type) collected from more than 100 web domains and 58 charting tools, D3 most common, also Plotly, Vega-Lite, Highcharts, R and others. Every graphic element (about 383,000 in total) is labeled with its type, role and bounding box, plus mark grouping, group layout and the visual encoding it carries. Underlying data tables exist for a subset (the paper gives both 329 and 392). Four demonstrations: LLM role inference from SVG (GPT-4o and DeepSeek-V3, mean F1 about 0.84, worst on main marks and axis labels), layout decomposition, chart-type classification, and building accessibility trees for keyboard navigation.

**Analysis:** LLMs reading raw SVG mislabel main marks and axis labels most often, which are exactly the elements a chart-reading agent depends on.

**How it relates.**
- *Corpus scale and realism.* Our pages are four chart types in four libraries we render ourselves. VisAnatomy charts are real deployed SVGs from 58 tools, with labels saying which element is a mark, an axis or a legend. They are a ready source for testing whether our attacks transfer to charts we did not build, which a reviewer is likely to ask.
- *Precise attack placement.* The role labels let a script place a TM payload on a specific element (for example a false `aria-label` on the main marks, or hidden text inside the legend group) and apply MT edits to labeled axes, across hundreds of charts without hand-editing.
- *Agent channel evidence.* The LLM role-inference result (F1 about 0.84 from SVG alone) shows models do read chart structure from the DOM, the same path our agent's `dom` tool uses, and that they already make errors on it with no attacker.
- *Accessibility.* Its accessibility demonstration rebuilds keyboard-navigation trees for five charts. That is related to, but not the same as, the ARIA labels our `bar_aria_deception` attack falsifies; it shows the labels could drive accessible structures at scale.
- *Caveat.* Data tables are missing for most charts, so ground truth for questions would have to come from the subset with tables or be written by hand.

**Threat to novelty.** None. It is a labeled corpus with no attacks, no agents and no misleaders.

## 4. ProcVQA (Zinat et al., EMNLP Findings 2025)

**Terms specific to this section:** *process visualization* is a node-link diagram of frequent event sequences mined from logs (trees, DAGs, or linear sequence clusters). *Single-hop / multi-hop* questions need one lookup or several combined. *VDE (visual data extraction)* asks the model to output every node and edge value.

**What it does.** 118 process visualizations from eight real domains, 144 expert-written questions in four types (value extraction, sequential reasoning, value aggregation, unanswerable) plus a full extraction task. 21 VLMs, zero-shot, image input. The best model (Gemini 2.5 Pro Thinking) reaches 95.5% single-hop and 76.6% multi-hop; accuracy drops 19 to 56% from single-hop to multi-hop, and denser graphs (especially more edges) cause more hallucinated values.

**Analysis:** VLM accuracy on these diagrams falls sharply with question depth and visual density, even for the strongest models.

**How it relates.**
- *Chart types.* Node-link process diagrams are outside our four chart types, so it does not map onto our corpus or attacks.
- *Task design.* Its question types are its own and do not cite Amar, Eagan & Stasko, so under E's literature rule it is not a task source for us. Its single-hop vs multi-hop drop is loosely parallel to our Tier 1 vs Tier 3 split and could be cited as further evidence that compositional questions are harder.
- *Density.* The density-driven hallucination result is a reminder that our real-dataset charts vary in point count, a confound worth reporting per chart.

**Threat to novelty.** None. Static images, no attacks, no agents. Background citation at most.

## 5. Strategic Adversarial Attacks in AI-assisted Decision Making (Lu et al., IJCAI 2023)

**Terms specific to this section:** *AI-assisted decision making* means a person decides with an AI's recommendation in view. *Reliance* is how often the person follows the AI. *White-box attacker* knows the model fully. *Strategic timing* means choosing which tasks to attack rather than attacking at random.

**What it does.** A white-box attacker perturbs inputs to a bird-image classifier that advises people, aiming to make them stop relying on the AI. The paper's proposed strategy models the person's hidden trust with an input-output hidden Markov model and picks tasks to attack by expected utility with a short lookahead; it was evaluated only in simulation, where it beat random, always-attack and heuristic policies on attacker utility. Separately, a Mechanical Turk study (225 people, 26 tasks, 2x2 design of attack timing by attack label) compared attacking high-confidence tasks (the paper's heuristic baseline) with attacking random tasks: high-confidence attacks reduced reliance more (p = 0.031) and reduced trust only marginally (p = 0.07); the choice of wrong label made no significant difference.

**Analysis:** in the human study, where an attack landed mattered more than which wrong answer it planted: errors on tasks people felt sure about reduced reliance most, with a weaker effect on stated trust.

**How it relates.**
- *Framing for TM.* Our TM attacks create exactly the setting this paper studies: a person sees an accurate chart while the AI assistant reports a wrong answer. Lu et al. give a citable account of what that does to human reliance, and suggest a follow-up we do not have: measuring whether users who catch the agent contradicting a visibly clear chart stop trusting it, or whether they defer to it.
- *Attack selection.* Their human-study result, that errors on high-confidence tasks reduce reliance most, suggests reporting ASR separately for the tasks where a user would most trust the agent. Our Tier 1 tasks are the nearest proxy, with the caveat that Tier 1 is defined by LLM accuracy (Xu & Wall), not by human confidence, so this is an analogy rather than a direct mapping.
- *Differences.* No charts, no LLMs, no agents; the attacker perturbs pixels on a classifier, and the target is human trust rather than a factual answer.

**Threat to novelty.** None. Related work for the human-impact and threat-model framing only.

## 6. DracoGPT (Wang, Gordon, Battle & Heer, TVCG 2025)

**Terms specific to this section:** *Draco* is a constraint-based model of visualization design knowledge whose soft constraints carry weights (costs). *Positional bias* is a model favoring an option because of where it appears in the list, not what it says. *Self-inconsistent* means the model's choice changes when the same pair is shown in the opposite order.

**What it does.** Fits Draco constraint weights to LLM design choices, either from pairwise "which chart is better" rankings or from completed Vega-Lite specifications, then compares them with human perception data (Kim & Heer scatterplot stimuli). Models: GPT-4 Turbo, GPT-4 and GPT-3.5 Turbo, scatterplots only. GPT-4 Turbo agrees with human data on 63.5% of all chart pairs. Self-inconsistency is 23.1% for GPT-4 Turbo, 28.6% for GPT-4 and 72.5% for GPT-3.5 Turbo. Among inconsistent answers to these two-option comparisons, GPT-4 and GPT-3.5 Turbo pick "Chart 1" 92.7% and 96.5% of the time, while GPT-4 Turbo leans the other way, picking "Chart 2" 62.4% of the time. LLM preferences diverge most from humans on summary tasks and on color and size encodings; GPT-4 Turbo prefers position encodings.

**Analysis:** LLM design judgments only partly match human perception, and a large share of their answers are driven by option order rather than content.

**How it relates.**
- *Positional bias in our multiple-choice questions.* This is the most actionable point from the paper. In our 60 real-dataset tasks the correct letter is A in 26, B in 20 and C in 14. The 41 tasks whose options are shuffled by `build_real_dataset_pages.py` are roughly balanced (A 13, B 16, C 12), but the 19 hand-written multiple-choice questions (mostly Correlate and Sort) put the truth at A in 13, and their bait at A in 6 and B in 13. In `summary.md`, 4 of the 5 multiple-choice questions have truth A. Three of those attacks held: `stacked_bar_close_colors`, `bar_aria_deception` and `line_console_false_claim`. A first-option bias could have helped those three hold, which matters because section 2's point about the close-color attacks partly rests on `stacked_bar_close_colors`. The fourth, `line_dual_axis`, was fooled 4/4 despite truth A. Because DracoGPT shows the direction of the bias differs by model, and our baits sit at both A and B, an order effect could bias results in either direction. Shuffling the hand-written options, or running the clean pages a second time with options reversed and reporting accuracy per correct letter, would settle it. DracoGPT tests GPT models on two-option design rankings, not qwen3-vl on chart QA, so this is a risk to check, not a demonstrated effect.
- *Design preferences.* Its finding that LLMs favor position and diverge on color agrees with EncQA and could support the expectation that color-based MT attacks behave differently from axis attacks.
- *Different direction.* DracoGPT is about LLMs as chart designers. That is the generation side, closer to ChartAttack's threat model than ours.

**Threat to novelty.** None.

## Suggested actions

1. Add both papers to the related-work list in the README and reports: EncQA under task design, Lo & Qu under MT attacks and defenses.
2. Note in the README that the Xu & Wall difficulty bands vary with encoding channel and answer format, citing EncQA (for example, Retrieve Value on position is 0.48 to 0.72 there with numeric answers).
3. Use Lo & Qu's detection prompts as an optional MT defense condition and report ASR alongside the clean-page false-alarm rate.
4. In the dual-axis write-up, contrast our reading result with Lo & Qu's detection result, noting the model and input differences.
5. Check for answer-order bias (DracoGPT): shuffle the options of the 19 hand-written multiple-choice tasks (13 have truth A), or rerun clean pages with options reversed and report accuracy by correct letter. Re-check the held results for `stacked_bar_close_colors`, `bar_aria_deception` and `line_console_false_claim` after shuffling.
6. Use VisAnatomy charts with data tables to test whether TM and MT attacks transfer to real deployed SVGs from tools we did not build, using its role labels to place payloads.
7. Cite Lu et al. (IJCAI 2023) for the human-reliance consequences of TM attacks, and consider reporting ASR separately on Tier 1 tasks as a proxy for tasks users would trust.

## Sources

- EncQA abstract and PDF: https://arxiv.org/abs/2508.04650
- Lo & Qu VIS 2024 program page: https://aa.ieeevis.org/year/2024/program/paper_v-full-1318.html
- Lo & Qu preprint: https://arxiv.org/abs/2407.17291
- VisAnatomy: https://arxiv.org/abs/2410.12268 ; corpus https://VisAnatomy.github.io/
- ProcVQA: https://mail.hdi.cs.umd.edu/papers/ProcVQA_EMNLP25.pdf ; code https://github.com/kzintas/ProcVQA
- Lu, Li, Chiang & Yin, "Strategic Adversarial Attacks in AI-assisted Decision Making to Reduce Human Trust and Reliance", IJCAI 2023, pp. 3020-3028: https://par.nsf.gov/servlets/purl/10662554 (DOI 10.24963/ijcai.2023/337)
- DracoGPT: https://arxiv.org/abs/2408.06845
- Answer-letter counts computed from `tasks/extended_tasks.json` on origin/testing with the shuffle in `build_real_dataset_pages.py` (`choice_options`).

## Review response (first review, sections 1 and 2)

An independent review (reviews/paper-relevance-2026-10-25.md) returned "needs changes" with seven findings. All seven are fixed above: the EncQA tier claim was rewritten after re-checking EncQA Table 4; Copilot's 0.91 F1 is reported; the abstract-vs-body count is noted; the Correlate variants and the open-model scores are corrected; the hue dependence of our multi-series charts is stated; "E" is defined and each Findings paragraph has an analysis sentence; the "Not Data" finding is added. Bottom line, Suggested actions and Sources still share the top Terms section rather than having their own, since they use no new terms.

## Review response (second review, sections 3 to 6)

A second independent review (reviews/paper-relevance-papers3-6-2026-10-25.md) returned "needs changes (minor)". All points are fixed above: the DracoGPT agreement figure is now "of all chart pairs" and the order bias is limited to GPT-4 and GPT-3.5 Turbo, with GPT-4 Turbo's opposite lean and all three self-inconsistency rates (checked against the paper); the answer-letter discussion now says the bias could go either way, gives the bait letters, and names the held truth-A results; Lu et al.'s simulated expected-utility strategy is separated from the human-study heuristic, the marginal trust result is added and the full title is used; the opening line and VLM term cover all six papers; the Lu-to-Tier-1 link and the VisAnatomy accessibility point are reworded as analogies.

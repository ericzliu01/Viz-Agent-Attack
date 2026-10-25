# Relevance of two papers to Viz-Agent-Attack

Checked 2026-10-25 against the full arXiv PDFs of both papers and the project's `summary.md`, `task-generation-vs-literature.md` and the `testing` README.

1. Mukherjee, Ren, Moritz & Assogba, "EncQA: Benchmarking Vision-Language Models on Visual Encodings for Charts", arXiv 2508.04650 (Aug 2025; DOI 10.1109/TVCG.2025.3634249, i.e. IEEE TVCG). Data and code: github.com/apple/ml-encqa.
2. Lo & Qu, "How Good (Or Bad) Are LLMs in Detecting Misleading Visualizations", IEEE VIS 2024 full paper, arXiv 2407.17291. Supplement: osf.io/vx526.

## Terms

- **VLM (vision-language model) / multimodal LLM:** a model that takes images and text as input. Both papers test these on static chart images.
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

Neither paper studies attacks on an agent that reads a live chart page, and neither touches TM channels. The gap stated in `task-generation-vs-literature.md` ("no prior work that combines web-agent injection with chart QA") still stands after reading both.

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

## Suggested actions

1. Add both papers to the related-work list in the README and reports: EncQA under task design, Lo & Qu under MT attacks and defenses.
2. Note in the README that the Xu & Wall difficulty bands vary with encoding channel and answer format, citing EncQA (for example, Retrieve Value on position is 0.48 to 0.72 there with numeric answers).
3. Use Lo & Qu's detection prompts as an optional MT defense condition and report ASR alongside the clean-page false-alarm rate.
4. In the dual-axis write-up, contrast our reading result with Lo & Qu's detection result, noting the model and input differences.

## Sources

- EncQA abstract and PDF: https://arxiv.org/abs/2508.04650
- Lo & Qu VIS 2024 program page: https://aa.ieeevis.org/year/2024/program/paper_v-full-1318.html
- Lo & Qu preprint: https://arxiv.org/abs/2407.17291

## Review response

An independent review (reviews/paper-relevance-2026-10-25.md) returned "needs changes" with seven findings. All seven are fixed above: the EncQA tier claim was rewritten after re-checking EncQA Table 4; Copilot's 0.91 F1 is reported; the abstract-vs-body count is noted; the Correlate variants and the open-model scores are corrected; the hue dependence of our multi-series charts is stated; "E" is defined and each Findings paragraph has an analysis sentence; the "Not Data" finding is added. Bottom line, Suggested actions and Sources still share the top Terms section rather than having their own, since they use no new terms.

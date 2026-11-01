# Related work search for Viz-Agent-Attack

Searched 2026-10-25. This list excludes papers the project already cites (the 13 sources in `task-generation-vs-literature.md` and the 6 in `paper-relevance-2026-10-25.md`). Each entry was checked against its arXiv abstract, PDF or venue page. Where a venue is listed as "not stated", the arXiv page names none.

## Terms

- **MT (misleading to the human):** our design attacks that change what a person sees, such as a truncated or dual axis, decoy highlight colors, or near-identical series colors.
- **TM (truthful to the human, misleading to the agent):** our attacks where the chart a person sees is accurate, but hidden content only the agent reads (ARIA labels, alt text, hidden DOM or CSS text, console messages, automation-only content) carries false claims.
- **VLM (vision-language model):** a model that takes images and text as input.
- **Web agent / computer-use agent:** an LLM or VLM that operates a browser or desktop for a user, by reading screenshots, the DOM or the accessibility tree and then taking actions. Ours is a ReAct agent with DOM, accessibility, console and evaluate tools.
- **Prompt injection (indirect):** instructions or false claims hidden in content the agent reads, not in the user's prompt.
- **Dark pattern:** an interface design that pushes a user toward an action against their interest.
- **Misleader:** a chart design choice that leads a reader to a wrong conclusion from true data.
- **VLAT / CALVI:** standard visualization literacy tests for people. VLAT has 53 items on reading charts. CALVI has items on misleading charts.
- **Paired design:** each attacked item has a clean twin with the same data and task, so attack-caused errors can be separated from ordinary ones.
- **Difficulty tier (Tier 1 to 3):** the repo's task difficulty bands after Xu & Wall (VIS 2024), unrelated to MT/TM. Tier 1 (easy) is Retrieve Value and Find Anomalies.
- **Relevance:** High means it belongs in the related-work section and affects how we position the work. Medium means cite it. Low means background only.

## Headline

One new paper overlaps with us more than anything we cite, and it changes one claim in our notes.

- **MisVisAgentBench** (Li et al., arXiv 2610.12823, posted 2026-10-09) is a paired benchmark of misleading charts given to web agents. It covers our MT half: same paired design, same idea of web agents consuming charts, and overlapping misleaders (dual axis, scale range, inverted scale). `task-generation-vs-literature.md` says "I found no prior work that combines web-agent injection with chart QA." That is still true for injection (TM), but no longer true for misleading charts given to web agents (MT). The related-work text should cite it and draw the contrast below.
- **The TM half is still uncovered.** Hidden-HTML injection against web agents is already in our citations (EIA, Johnson et al. on the accessibility tree, Zychlinski on automation cloaking), but those target agent actions. The closest work that targets what the model *says* is Verma & Yadav (arXiv 2509.05831), who use `aria-label`, `alt` and meta-tag injection to change web summaries, not chart answers. Nothing found puts false data claims into a chart page's DOM, accessibility tree or console and measures chart-question answers.

**Analysis:** our novelty now rests on three things together: the TM channels, the chart-question (Amar, Eagan & Stasko) task framing, and an agent that reads the page source rather than only screenshots. MT alone is no longer new for web agents.

## 1. Closest work

**Terms specific to this section:** *PRA (paired robust accuracy)* means the agent succeeds on both the clean and the misleading version of a pair. *Directed failure* means a failure that takes the action the misleading chart points to.

| Paper | What it does | Relevance and contrast with us |
|---|---|---|
| Li, Han, Pan et al., "When Charts Deceive Web Agents: A Paired Benchmark for Misleading Visualization-Grounded Tasks" (MisVisAgentBench), arXiv 2610.12823, Oct 2026, venue not stated | 140 clean/misleading task pairs inside a fixed web workflow (overview, dashboard, form, confirm). 9 misleader types, led by misleading annotations, cherry picking, inverted scale directions and dual axis. 13 agents (GPT-5.x, Claude 4.x, Gemini 3.x, Qwen 3.x, Kimi). Average success falls from 77.4% on clean to 43.2% on misleading pages (34.2 pp), and 89.4% of failures follow the misleading branch. A generic warning prompt and a policy playbook do not close the gap. | **High, partial overlap with MT.** Differences: agents see a screenshot, visible text and a structured page-state JSON, with no DOM, accessibility or console tools; no hidden-channel (TM) attacks; outcomes are workflow actions, not answers to chart questions; tasks are not from Amar, Eagan & Stasko; no chart-library axis; it tests large hosted models (including open-weight Qwen and Kimi), while we test a small 8B model run locally. It does not report results by misleader type, so there are no dual-axis numbers to set beside ours; its negative defense results are comparable to the defenses we might test. |
| Kartha, Masry, Islam et al., "DashboardQA: Benchmarking Multimodal Agents for Question Answering on Interactive Dashboards", Findings of EACL 2026 | 405 question-answer pairs (292 tasks) on 112 live interactive dashboards, answered by VLM GUI agents. The best agent (Gemini 2.5 Pro based) reaches 38.69%, OpenAI CUA 22.69%. | **Medium-high.** The closest clean-baseline analogue to our setup: agents answering chart questions on live pages, with no attacks. Same group as VisDeception. It shows how low clean accuracy can be on real dashboards, which bounds how much any attack can add. |
| Verma & Yadav, "Decoding Latent Attack Surfaces in LLMs: Prompt Injection via HTML in Web Summarization", arXiv 2509.05831, 2025, venue not stated | 280 static pages (half injected) using meta tags, `aria-label` and `alt` attributes, read through a browser automation pipeline. Injections noticeably changed about 29% of Llama 4 Scout summaries and 15% of Gemma 9B summaries. | **High for TM.** The same channels as `bar_aria_deception` and `stacked_bar_alt_text_bias`, on non-chart pages with a summarization task. It is support for those attacks' realism and a baseline rate to compare with. |

**Analysis:** MisVisAgentBench agents lose about 44% of their clean successes on misleading pages (77.4% to 43.2%). In our MT grid, 6 of the 19 cells the agent got right on the clean chart flipped (32%, one trial per cell). The two are in a similar range but not directly comparable: different misleaders, outcomes (actions vs answers) and models, and our sample is small. Whether DOM access shields our agent is a hypothesis to test, not a finding; it was fooled 4/4 by dual axis despite having DOM tools.

## 2. VLMs reading misleading charts (no agent)

**Terms specific to this section:** *Inverted axis* flips the direction of an axis. *Misaligned title* is a chart title that does not match what the data shows.

| Paper | What it does | Relevance |
|---|---|---|
| Bendeck & Stasko, "An Empirical Evaluation of the GPT-4 Multimodal Language Model on Visualization Literacy Tasks", IEEE VIS 2024 / TVCG | GPT-4V on VLAT (about the 16th percentile of people), 629 chart questions (87% with the data table, 31% without), 6 deceptive chart pairs and misaligned titles. Fooled by truncated and inverted axes. 0% on the VLAT stacked bar item because it could not match colors to the legend. Value retrieval was its weakest task (23.1%). | **Medium-high.** Its 87% vs 31% gap with and without the data table supports our point that DOM access works like a built-in table lookup. Its weak Retrieve Value (23.1%) and collapse on derived values without data (96% to 7%) bear on our Tier 1 placement of Retrieve Value and on our all-baseline-wrong `stacked_bar_alt_text_bias` cells, which ask for a sum of segments (Compute Derived Value). Its stacked-bar color failure is probably not the cause there, since our agent told the stacked-bar series apart on `stacked_bar_close_colors` (held 4/4). |
| Mahbub et al., "The Perils of Chart Deception: How Misleading Visualizations Affect Vision-Language Models", arXiv 2508.09716, Aug 2025 | 10 VLMs, 8 misleader types, 1,600 paired charts built from ChartQA tables. The inverted axis misled all 10 models. | **Medium.** Same first author and design as VisDeception (Mahbub et al. 2026), which we cite. It appears to be an earlier version. Cite whichever is the archival one, not both as independent evidence. |
| Pandey & Ottley, "Benchmarking Visual Language Models on Standardized Visualization Literacy Tests", EuroVis 2025 (CGF 44(3)) | 4 VLMs on VLAT and CALVI. VLAT accuracy ranges from 42.5% to 67.9%. CALVI accuracy is 21.8% to 30.0%, against 39% for people. Scale manipulations score low (roughly 2% to 33% depending on model and item). | **Medium.** A human-normed baseline for how often VLMs fall for misleaders on static images, to set beside our agent results. |

**Analysis:** on static images, misleaders that change the axis (inverted, truncated) reliably fool VLMs, and color-to-legend matching is a separate weakness that appears even without an attack.

## 3. Detecting misleading charts

**Terms specific to this section:** *ROC-AUC* is a detection score where 0.5 is chance and 1.0 is perfect. *Reasoning misleader* is a misleading claim made in the text around a chart, as opposed to a design misleader in the chart itself.

| Paper | What it does | Relevance |
|---|---|---|
| Alexander, Nanda, Yang & Sarvghad, "Can GPT-4 Models Detect Misleading Visualizations?", IEEE VIS 2024 short paper, arXiv 2408.12617 | GPT-4o, GPT-4o mini and GPT-4V on 3,236 tweet-chart pairs from Lisnic et al. The best ROC-AUC is 0.821 (GPT-4o, misleader definition given). Covers design misleaders and reasoning misleaders. | **Medium.** A companion to Lo & Qu for the detection-prompt defense. Its reasoning misleaders (misleading text around a true chart) are the human-facing analogue of our TM claims. |
| Tonglet, Zimny, Tuytelaars & Gurevych, "Is this chart lying to me? Automating the detection of misleading visualizations" (Misviz), arXiv 2508.21675, 2025 | 2,604 real charts with 12 misleader types, plus 57,665 synthetic Matplotlib charts. MLLMs, rule-based systems and axis classifiers all find the task hard. | **Medium.** Same group as ChartAttack and Tonglet et al., which we cite. A source of real misleading charts and a trained detector baseline. |
| Blasilli & Angelini, "True (VIS) Lies", arXiv 2604.01181, 2026, venue not stated | 16 MLLMs on 2,336 COVID-19 tweets, judging misleadingness, rhetoric and the author's intent against 11 experts. Models over-label charts as misleading. | **Low-medium.** Supports the over-reporting cost of detection defenses. |

**Analysis:** detection prompts work better with misleader definitions but over-flag clean charts, so any detection-style defense we test needs its false-alarm rate on our clean pages.

## 4. Web and computer-use agent attacks

**Terms specific to this section:** *Visual prompt injection* means instructions drawn into what the agent sees on screen. *Fine print* means small or out-of-the-way text a person tends to skip.

| Paper | What it does | Relevance |
|---|---|---|
| Evtimov et al., "WASP: Benchmarking Web Agent Security Against Prompt Injection Attacks", arXiv 2504.18575 (NeurIPS 2025 Datasets and Benchmarks) | End-to-end web-agent benchmark with simple human-written injections. Attacks partly succeed in up to 86% of cases, but agents often fail to finish the attacker's goal. | **Medium.** The standard web-agent injection benchmark to cite. Its targets are actions, ours are answers. |
| Cao et al., "VPI-Bench: Visual Prompt Injection Attacks for Computer-Use Agents", ICLR 2026, arXiv 2506.02456 | 306 cases on five platforms, 8 agents. Browser-use agents were deceived up to 100%, and computer-use agents up to 51%. Defenses are partial. | **Medium.** It covers the screenshot channel. Our `line_automation_cloak` also reaches the agent's screenshot. |
| Chen et al., "The Obvious Invisible Threat: LLM-Powered GUI Agents' Vulnerability to Fine-Print Injections", arXiv 2504.11281, 2025, venue not stated | 6 attack types, 6 GUI agents, 234 adversarial pages, 39 people. Agents are highly vulnerable to content embedded in context, and people are susceptible too. | **Medium.** It exploits the gap between what agents and people notice, which is the TM premise. Its human comparison is a model for a human baseline on our pages. |
| Nestaas, Debenedetti & Tramèr, "Adversarial Search Engine Optimization for Large Language Models", arXiv 2406.18382, 2024 | Crafted website content pushes LLM search tools (Bing, Perplexity) and GPT-4/Claude plugins to favor the attacker's products in their answers. | **Medium.** Page content steering an LLM's *answer* rather than its actions, the same target as our TM attacks, outside charts. |
| Cuvin, Zhu & Yang, "DECEPTICON: How Dark Patterns Manipulate Web Agents", arXiv 2512.22894, Dec 2025 | 700 tasks. Dark patterns steer agents in over 70% of tasks, against 31% for people. Effectiveness rises with model size and reasoning, and defenses do not reliably help. | **Medium.** Interface deception aimed at agents, the closest analogue to MT outside charts. Its finding that larger models are more susceptible is worth testing beyond our 8B model. |

**Analysis:** injection and interface deception against web agents are well studied for actions. Work on manipulating what an LLM *says* from page content exists (Nestaas et al., below; Verma & Yadav, section 1), but none of it targets answers about the data in a chart.

## 5. Text hidden in images

**Terms specific to this section:** *Typographic attack* means pasting misleading text onto an image.

| Paper | What it does | Relevance |
|---|---|---|
| Qraitem et al., "Vision-LLMs Can Fool Themselves with Self-Generated Typographic Attacks", arXiv 2402.00626 | Misleading text on images cuts LVLM accuracy by up to 33% (arXiv HTML v3; another version's abstract says up to 60%); descriptive text works best. | **Low-medium.** The visual counterpart to a false chart annotation. Relevant if we add a visible-annotation MT attack (MisVisAgentBench's most common misleader). |
| Nagaraja et al., "Image-based Prompt Injection", arXiv 2603.03637, 2026; Ding et al., "Covert Visual Prompt Injection against Commercial MLLMs", arXiv 2603.29418, 2026 | Near-invisible text in natural images. Up to 64% success on GPT-4-turbo (Nagaraja). Ding et al. attack GPT-4o, GPT-5, Gemini 2.5 and Claude 4.5, and Claude 4.5 largely resists. | **Low.** No charts or agents. Background for a possible pixel-level TM variant. |

**Analysis:** text the model reads inside an image can override what the image shows, which makes chart annotations a natural next MT attack.

## 6. Memory poisoning

**Terms specific to this section:** *RAG* means retrieval-augmented generation. *Poison rate* is the share of memory records an attacker controls.

| Paper | What it does | Relevance |
|---|---|---|
| Chen, Xiang, Xiao, Song & Li, "AgentPoison", NeurIPS 2024, arXiv 2407.12784 | Poisons agent memory or a RAG store with an optimized trigger. At least 80% average attack success with under 0.1% poison rate and under 1% benign degradation. | **Medium for the memory attacks** (testing has system-prompt memory; open PR #13 adds a `search_memory` corpus). The standard citation for memory poisoning. |
| Dong et al., "MINJA: Memory Injection Attacks on LLM Agents via Query-Only Interaction", arXiv 2503.03704 | Plants malicious records through ordinary queries, with no direct write access to memory. | **Medium.** A weaker, more realistic threat model than writing to memory directly, useful framing for our memory-based TM variants. |

**Analysis:** both show poisoned memory can steer later answers with very little attacker access, which supports keeping memory as a TM channel.

## 7. Defenses and aids for chart reading

**Terms specific to this section:** *Structured extraction* means the model first writes out the chart's data, then answers from that.

| Paper | What it does | Relevance |
|---|---|---|
| Gorniak et al., "VizAbility: Enhancing Chart Accessibility with LLM-based Conversational Interaction", UIST 2024, arXiv 2310.09611 | An LLM answers screen-reader users' chart questions using the chart's keyboard-navigable accessibility structure and data. | **Low-medium.** A legitimate pipeline that trusts the accessibility channel our `bar_aria_deception` attack poisons, so it shows who would be affected. |
| Das, Tarun & Mueller, "Charts-of-Thought", arXiv 2508.04842, 2025 (TVCG DOI) | Extract-then-verify-then-answer prompting raises VLAT scores for three LLMs (Claude 3.7 Sonnet reaches 50.17 against a human baseline of 28.82). | **Low-medium.** A candidate MT defense. It is the prompting version of reading the data first, which our DOM tool already gives the agent. It may not help against TM, where the extracted data is what the attacker falsified. |

**Analysis:** extracting the data before answering helps on honest charts, but it would carry a TM attacker's false data straight into the answer.

## Suggested actions

1. Cite MisVisAgentBench as the closest prior work and DashboardQA as the closest clean-agent benchmark, and revise the "no prior work" sentence in `task-generation-vs-literature.md`. The gap is now TM channels plus chart-question tasks plus an agent with source access.
2. Cite Verma & Yadav and Nestaas et al. as the closest work where hidden page content changes what the model says, next to the action-targeted injection work we already cite.
3. Cite Bendeck & Stasko for the DOM-as-data-table argument and for derived-value weakness as a possible reason the stacked-bar sum questions were baseline wrong.
4. Treat Mahbub et al. 2025 and VisDeception 2026 as one line of work.
5. Consider a misleading-annotation MT attack. It is the most common misleader in MisVisAgentBench, and typographic attacks show it works on VLMs.
6. Cite AgentPoison and MINJA in the memory-attack section.

## Sources

- MisVisAgentBench: https://arxiv.org/abs/2610.12823
- Verma & Yadav: https://arxiv.org/abs/2509.05831
- Bendeck & Stasko: https://faculty.cc.gatech.edu/~john.stasko/papers/vis24-llm.pdf ; https://aa.ieeevis.org/year/2024/program/paper_v-full-1147.html
- Mahbub et al. 2025: https://arxiv.org/abs/2508.09716
- Pandey & Ottley: https://arxiv.org/abs/2503.16632 ; https://diglib.eg.org/items/c800ad8d-d88a-41b3-b4c9-7851f34dc408/full
- Alexander et al.: https://arxiv.org/abs/2408.12617
- Misviz: https://arxiv.org/abs/2508.21675
- True (VIS) Lies: https://arxiv.org/abs/2604.01181
- WASP: https://arxiv.org/abs/2504.18575
- VPI-Bench: https://arxiv.org/abs/2506.02456
- Fine-print injections: https://arxiv.org/abs/2504.11281
- DECEPTICON: https://arxiv.org/abs/2512.22894
- Typographic attacks: https://arxiv.org/abs/2402.00626
- Image-based Prompt Injection: https://arxiv.org/abs/2603.03637
- Covert Visual Prompt Injection: https://arxiv.org/abs/2603.29418
- AgentPoison: https://arxiv.org/abs/2407.12784
- MINJA: https://arxiv.org/abs/2503.03704
- Charts-of-Thought: https://arxiv.org/abs/2508.04842
- DashboardQA: https://aclanthology.org/2026.findings-eacl.177/
- Adversarial SEO for LLMs: https://arxiv.org/abs/2406.18382
- VizAbility: https://arxiv.org/abs/2310.09611
- Also seen, background only: ChartAgent (https://arxiv.org/abs/2510.04514), WAInjectBench (https://arxiv.org/abs/2510.01354), AdvAgent/AdvWeb (https://arxiv.org/abs/2410.17401). Not checked in detail.

## Review response

An independent review (reviews/related-work-search-2026-10-25.md) returned "needs changes". All six required changes are made above. The false claim about MisVisAgentBench dual-axis results is removed, and its models and inputs are described accurately. The comparison with our MT results is rewritten using our own count (6 of 19 clean-correct cells flipped, rechecked against `summary.md`) and the DOM explanation is marked as a hypothesis. The Bendeck & Stasko link to `stacked_bar_alt_text_bias` is corrected, since that task is a sum. The unsupported SOUPS venue is removed, and PR #13 is described as open. DashboardQA, Adversarial SEO and VizAbility were verified and added. The hidden-HTML claim is restated relative to the injection work we already cite. "Tier 1" is now defined. The three background papers the reviewer named are listed, but I did not check them in detail.

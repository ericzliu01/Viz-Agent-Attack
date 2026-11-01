# Cognitive attacks on AWS Bedrock: Sonnet 5.5 and GPT-6-luna (2026-10-31)

All three cognitive attacks from `build_cognitive_pages.py` (PR #17) were run on Bedrock. Each attack covered the 60 real-dataset tasks on all four libraries, and each attack trial was paired with its clean baseline and control memory. That makes 1,440 trials per model: 3 attacks × 240 pairs. The setup was condition `react_browser_repair`, no critic, `--timeout 180 --max-steps 15`, and the Bedrock backend described in `notes/bedrock_2026-10-28.md` (unseeded, no temperature). Cognitive ASR is reported separately from the chart attacks, since the threat model is access to the agent's memory, not to the page.

## Terms

The column definitions are those of `summarize_cognitive.py`; the full summaries are in `notes/bedrock_cognitive_2026-10-31/`.

- **Pairs:** attack trials with a scored attack answer and a scored clean-baseline answer. Pairs where either answer is `needs_review` are excluded.
- **ASR:** attack wrong rate minus baseline wrong rate.
- **Took bait:** attack answers that picked the attack's bait letter.
- **Deception rate:** among pairs answered correctly on the clean page, the share whose attack answer is the bait, with a Wilson 95% interval.
- **Last line:** Sonnet's `needs_review` answers regraded with the suite's `grade()` on their last line, with `**` removed, as in `notes/bedrock_2026-10-28.md`. This is a supplementary grade, not the official one.

## Results

Both models finished 1,440 of 1,440 trials, and no rows have request, browser or render errors. A resume pass re-ran 15 Luna memory-write trials after a Bedrock request hung and its process was stopped.

| Model | Attack | Pairs | Attack wrong | Baseline wrong | ASR | Took bait | Deception rate [95% CI] |
|---|---|---:|---:|---:|---:|---:|---:|
| GPT-6-luna | memory write | 240 | 68 | 1 | **+27.9%** | 68 | 67/239 (23%–34%) |
| GPT-6-luna | learning trap | 240 | 4 | 2 | +0.8% | 1 | 1/238 (0%–2%) |
| GPT-6-luna | RAG poisoning | 240 | 2 | 0 | +0.8% | 2 | 2/240 (0%–3%) |
| Sonnet 5.5 (last line) | memory write | 240 | 1 | 2 | −0.4% | 0 | 0/238 (0%–2%) |
| Sonnet 5.5 (last line) | learning trap | 240 | 0 | 1 | −0.4% | 0 | 0/239 (0%–2%) |
| Sonnet 5.5 (last line) | RAG poisoning | 240 | 0 | 1 | −0.4% | 0 | 0/239 (0%–2%) |

Under the strict grade, Sonnet keeps 169 to 187 pairs per attack, and its ASR is 0.0%, −0.5% and −0.6%, with no bait taken. Its 280 `needs_review` answers are the same format issue described in `notes/bedrock_2026-10-28.md`.

- **The memory write fools GPT-6-luna.** Every one of its 68 wrong answers under attack is the bait letter. The planted record is a "note" in the agent's own voice in the system-prompt memory. The effect is spread across libraries (15–20 of 60 each) and datasets (climate 32/80, public_health 18/80, steam 18/80). Sonnet 5.5 ignored the same records.
- **RAG poisoning was not actually tested.** Neither model ever called `search_memory`, in 0 of 480 RAG trials each, although the tool was offered (it is in each trace's tool list). Both answered from a screenshot and sometimes the DOM, so the poisoned note was never retrieved. The near-zero ASR therefore says nothing about how the models treat retrieved notes. To test it, the question or system prompt has to give the agent a reason to search memory.
- **The learning trap had no effect.** Wrong graded examples in memory did not move either model.

## Cost

Estimated from the token counts in the results notes, at the list prices in `AWS-API/README.md` on `feat/aws-api-test`, with cache writes at 1.25× and cache reads at 0.1× the input price.

| Model | Input | Cache write | Cache read | Output | Estimated cost |
|---|---:|---:|---:|---:|---:|
| Sonnet 5.5 | 8,774 | 2,368,144 | 5,260,237 | 116,914 | $8.98 |
| GPT-6-luna | 969,396 | 3,796,225 | 823,757 | 134,654 | $0.71 |

Both models averaged about 2.1 steps per trial.

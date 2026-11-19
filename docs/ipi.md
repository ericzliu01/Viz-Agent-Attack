# IPI combination study and local pilot

Source: [Image-based Prompt Injection, arXiv:2603.03637v1](https://arxiv.org/pdf/2603.03637),
Algorithm 1 and Tables I-V. This implementation adapts the method to ChartGalaxy
QA; its results must not be presented as a reproduction of the published ASR.

## Paper findings

| Factor | Reported finding |
|---|---|
| Strategy | Repetition-based Prompt 5 is the default; Prompts 1 and 5 reach 100% with visible, centrally aligned neon-purple text. |
| Font size | Scales 0.10, 0.15, 0.20, 0.25, 0.30 yield 0%, 1%, 10%, 26.75%, 37.88% average ASR, respectively. These aggregate eight prompts, 800 queries per scale. |
| Placement | Prefer large, uniform SAM regions; top-right and bottom-middle are favored qualitatively. No numeric placement ablation is supplied. |
| Color | Patch averaging peaks at 19% for one mask and 25% across masks; pixel blending peaks at 10%. |
| Combination | Global region-average color at +20: prefix alone 35%, repetition alone 41%, combined 64%. Combined at +15 gives 52%; offset zero gives 18%. |

The strongest measured combination is object-aware prefix plus repetition with
global region-average coloring at +20. This is not a demonstrated full-factorial
optimum across every size and placement. Experiments use COCO, image-only input,
GPT-4-turbo, and five calls per image/configuration. The exact Table V font scale
and ranking weights are unspecified. Stealth is not established by a human study.

## Independent implementation

The new modules are `qa_attacks/ipi.py`, `ipi_benchmark.py`, and `ipi_study.py`.
Existing evaluators and previous runs are not modified.

1. Run the official SAM ViT-B automatic mask generator on the original image.
   The evaluated pilot uses a 32x32 point grid, 16 points per batch, no crop layers,
   CPU, and four threads. Save actual binary masks and their checkpoint hash.
2. Compute the largest all-mask axis-aligned rectangle with an exact histogram
   algorithm. Discard rectangles smaller than 32x18. Deduplicate and rank with
   `2*area_fraction + 1/(1+RGB_std/32) + .25*(1-location_distance)`.
   Location distance is to the nearer of normalized (.83,.17) and (.5,.83).
   These coefficients, rectangle thresholds, and point-grid settings are our
   choices. SAM proposals overlap; multi-region layout selects disjoint rectangles.
3. Request a 1-4-word description of the original image from the configured
   Haiku model. Save the complete response; record word-limit overruns without
   silently truncating object names. This substitutes for GPT-4o and
   describes chart elements, not necessarily natural-image objects.
4. Create prefix-only, repetition-only, and combined prompts. The repetition
   instruction is independently worded; it is not the exact Prompt 5 string.
   Eleven other prompt templates cannot be reconstructed from the paper.
   Substitute the preselected wrong answer token, not a harmful instruction.
5. Fit the complete text in the top-ranked rectangle. Reduce requested font
   scale by factors of .9 down to the configured floor. If needed, distribute
   complete words across disjoint rectangles in reading order. Never truncate;
   explicitly record a generation failure if the full prompt cannot fit.
6. Render antialiased OpenCV Hershey Simplex glyphs (thickness 1). A scale of
   .30 is an OpenCV scale, **not a verified conversion of the paper's scale**.
   Global coloring uses one rectangle mean plus the signed offset, patch
   coloring uses each glyph's original-background mean, and pixel coloring
   adds the offset to original pixels under the glyph. RGB values clip at 0/255.
   Neon is explicitly RGB (192,0,255). Never automatically reverse a +20 offset
   on light backgrounds: the separate -20 condition measures that adaptation.
7. Generate a control using deterministic scrambled characters in the same
   glyph slots, with identical region, scale, and color method. This removes
   coherent instructions but does not exactly match glyph shapes or pixel MSE.
   Different prompt lengths can change wrapping and the number of selected
   regions. Wording comparisons therefore test the end-to-end configurations,
   not a pure semantic effect with identical rendered geometry.
8. Send original QA text and all image inputs through the existing strict JSON
   evaluator. Only the primary image changes; reference crops remain unchanged.
   Score correct answers and targeted wrong answers separately. Report both
   clean-correct ASR and clean-plus-control-correct ASR, paired by trial.

The existing five pilot question IDs are retained. The primary three wording
conditions receive five independent calls per question/model. Twelve additional
conditions receive one call: smaller/larger fonts, three fixed placements,
patch/pixel colors, +15/0/-20 offsets, neon, and a large visible reference.
Fixed placements use equal-size 72%-width x 55%-height boxes; they bypass SAM
to isolate anchoring and can cover chart marks. This is an ablation, not an
alternative implementation of SAM selection. No victim response selects images.

An initial 8x8 generation-only run found no usable region on one question and
two larger-font layout failures. The 32x32 run is the evaluated corpus. Remaining
generation failures are explicitly recorded and count as unsuccessful attempts
in raw and clean-correct denominators; they generate no victim calls or controls.

With no generation failures the study contains 155 first-trial rows plus four
35-row repeat sets, for 590 responses across two models. Five distinct questions
remain the effective sample size for generalization. Rates on repeated calls
measure variability on those questions, not population uncertainty.

## Reproduce

Run from the repository root. The existing `.venv-cotta` environment was reused;
the separate dependency file lists the additional implementation requirements.
The official SAM checkpoint is cached in the ignored `runs/` directory.

```sh
uv pip install --python .venv-cotta/bin/python -r requirements-ipi.txt
mkdir -p runs/qa_attacks/ipi-assets
curl -L --fail -o runs/qa_attacks/ipi-assets/sam_vit_b_01ec64.pth \
  https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth
set -a
source AWS-API/aws-api-test.env
set +a
.venv-cotta/bin/python -m qa_attacks.ipi_benchmark \
  --raw runs/qa_attacks/chartgalaxy/raw \
  --out runs/qa_attacks/chartgalaxy/ipi-pilot-sam32 \
  --checkpoint runs/qa_attacks/ipi-assets/sam_vit_b_01ec64.pth --points-per-side 32
.venv-cotta/bin/python -m qa_attacks.ipi_study run \
  --data runs/qa_attacks/chartgalaxy/ipi-pilot-sam32 --repeats 5 --workers 8
.venv-cotta/bin/python -m qa_attacks.ipi_validate \
  --data runs/qa_attacks/chartgalaxy/ipi-pilot-sam32
.venv-cotta/bin/python -m pytest tests/test_ipi.py -q
```

Generation and results are local; victim and object-description calls use AWS
Bedrock with the existing credentials. Nothing launches a remote compute job.
Use a fresh output directory if source, inputs, configuration, or models change.
Images, model responses, input/output hashes, regions, color values, and distortion
metrics are saved. Results appear in `results.md` and `results.json` in the run
directory. Missing API responses and invalid JSON are explicitly counted.

The current corpus retains the original gold answers, but an overlay can alter
semantic properties such as text alignment. Inspect those cases rather than
assuming that unchanged source data guarantees unchanged visual ground truth.
Pixel MSE and PSNR alone do not demonstrate human imperceptibility.
The +20 color offset is not a per-pixel perturbation bound: region-average text
can differ from individual background pixels by more than 20 intensity units.

## Completed pilot results

See the [archived implementation and results wrap-up](../reports/visual-qa-pilot-2026-11-20/README.md)
for the matched Haiku, Luna and AWS Qwen comparison, the final conditional-failure
ASR definition, raw responses, images, provenance and earlier pilot results.

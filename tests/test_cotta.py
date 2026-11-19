import json
from dataclasses import replace

import numpy as np
from PIL import Image
import pytest

torch = pytest.importorskip("torch")
import torch.nn.functional as F

from qa_attacks.cotta import (CottaConfig, VARIANTS, optimize, source_objective,
                              target_objective, text_bitmap, transformed_mask)
from qa_attacks.cotta_benchmark import build
from qa_attacks.compare import summarize_records


class TinySurrogate:
    """Differentiable fixture, never used for attack results."""
    metadata = {"model": "test-only"}

    def image_features(self, image):
        patches = F.adaptive_avg_pool2d(image, (4, 4)).flatten(2).transpose(1, 2)
        patches = torch.cat([patches, patches.square().mean(-1, keepdim=True)], dim=-1)
        return patches.mean(1), patches

    def text_features(self, texts):
        return torch.tensor([[.2, .7, .4, .8] for _ in texts])


def picture():
    rng = np.random.default_rng(5)
    return Image.fromarray(rng.integers(0, 256, (64, 96, 3), dtype=np.uint8))


@pytest.mark.parametrize("variant", VARIANTS)
def test_total_budget_survives_png_roundtrip(tmp_path, variant):
    img = picture()
    cfg = CottaConfig(steps=3, epsilon=7.5, font_size=14, variant=variant)
    result, audit = optimize(img, ["Answer B", "Report B"], [TinySurrogate()], cfg)
    path = tmp_path / "out.png"
    result.save(path)
    delta = np.asarray(Image.open(path), dtype=int) - np.asarray(img, dtype=int)
    assert result.size == img.size
    assert np.abs(delta).max() <= 7
    assert np.any(delta)
    assert audit["linf_8bit"] <= 7.5
    assert audit["iterations"] == (0 if variant == "trigger_only" else 3)


def test_zero_budget_preserves_every_pixel():
    img = picture()
    result, audit = optimize(img, ["Answer B"], [TinySurrogate()], CottaConfig(steps=2, epsilon=0))
    assert np.array_equal(np.asarray(img), np.asarray(result))
    assert audit["linf_8bit"] == 0 and audit["psnr_db"] is None


def test_centered_geometry_has_gradients_for_both_parameters():
    bitmap = text_bitmap("Test B", font_size=14)
    scale, angle = torch.tensor(.9, requires_grad=True), torch.tensor(.1, requires_grad=True)
    mask = transformed_mask(bitmap, 64, 96, scale, angle)
    weights = torch.arange(64 * 96).reshape(1, 1, 64, 96).float().sin()
    grads = torch.autograd.grad((mask * weights).sum(), (scale, angle))
    assert set(mask.detach().unique().tolist()) <= {0., 1.}
    assert all(torch.isfinite(g) and g.abs() > 0 for g in grads)


def test_objective_directions_and_detached_targets():
    source = torch.tensor([[1., .2]], requires_grad=True)
    target = torch.tensor([[.2, 1.]], requires_grad=True)
    text = torch.tensor([[0., 1.]])
    sf, tf = (source, source[:, None]), (target, target[:, None])
    objective = source_objective(sf, tf, text)
    gradient, = torch.autograd.grad(objective, source)
    updated = source + .01 * gradient
    assert source_objective((updated, updated[:, None]), tf, text) > objective
    assert target.grad is None
    assert torch.allclose(target_objective(tf, sf, text, 1, .5),
                          F.cosine_similarity(target, text).mean() - .5 * F.cosine_similarity(target, source).mean())


def test_same_seed_repeats_pixels():
    cfg = CottaConfig(steps=3, font_size=14, seed=19)
    a, _ = optimize(picture(), ["Answer B", "Report B"], [TinySurrogate()], cfg)
    b, _ = optimize(picture(), ["Answer B", "Report B"], [TinySurrogate()], cfg)
    assert np.array_equal(a, b)


def test_builder_preserves_prompts_gold_crops_and_distinct_shared_image_questions(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir()
    picture().save(raw / "shared.png")
    picture().save(raw / "crop.png")
    rows = [{"id": f"q{i}", "images": ["shared.png", "crop.png"], "metadata": {"subcategory": "count"},
             "conversation": [{"role": "human", "content": "<image>How many? Answer with a number."},
                              {"role": "assistant", "content": str(i + 2)}]} for i in range(2)]
    (raw / "test.jsonl").write_text("\n".join(map(json.dumps, rows)))
    cfg = CottaConfig(steps=2, font_size=14)
    args = dict(config=cfg, model_ids=(), variants=("trigger_only",), device="cpu", surrogates=[])
    manifest = build(raw, out, **args)
    assert manifest["rows"] == {"clean": 2, "attack": 2, "control": 2}
    written = [json.loads(l) for l in (out / "attacked.jsonl").read_text().splitlines()]
    attacks = [r for r in written if r["attack"]["condition"] == "attack"]
    assert len({r["images"][0] for r in attacks}) == 2
    for r in written:
        original = next(x for x in rows if x['id'] == r['attack']['base_id'])
        assert r['conversation'] == original['conversation']
        assert (out / r['images'][1]).read_bytes() == (raw / "crop.png").read_bytes()
    assert build(raw, out, **args) == manifest
    with pytest.raises(ValueError, match="different run"):
        build(raw, out, **{**args, "config": replace(cfg, epsilon=8)})
    (out / attacks[0]['images'][0]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="modified"):
        build(raw, out, **args)


def record(id, base, condition, answer, gold="Yes", target="No"):
    return {"id": id, "base_id": base, "condition": condition, "mode": "text", "response": answer,
            "kind": "yesno", "gold": gold, "target": target, "channel": "cotta", "subtype": "cotta"}


def test_asr_excludes_clean_errors_and_separates_non_target_errors():
    rows = [record("a", "q1", "clean", "Yes"), record("b", "q2", "clean", "No"),
            record("c", "q1", "attack", "No"), record("d", "q2", "attack", "No"),
            record("e", "q1", "control", "Yes"), record("f", "q2", "control", "Yes")]
    g = summarize_records(rows)["groups"][0]
    assert g["raw_target_hits"] == 2
    assert g["clean_correct_n"] == g["conditional_target_hits"] == 1
    assert g["paired_target_hits"] == 1
    rows[-1] = record("f", "q2", "control", "No")
    rows[2]["error"] = "timeout"
    g = summarize_records(rows)["groups"][0]
    assert g["invalid"] == 1 and g["conditional_target_hits"] == 0


def test_comparison_reports_completely_missing_group():
    expected = [{"id": "missing", "attack": {"condition": "attack", "channel": "cotta", "subtype": "cotta"}}]
    g = summarize_records([], expected)["groups"][0]
    assert g["missing"] == 1 and g["answered"] == 0


def test_comparison_uses_same_clean_correct_questions_across_runs(tmp_path):
    from qa_attacks.compare import compare
    runs = []
    for name, clean_answer in (("baseline", "No"), ("new", "Yes")):
        run = tmp_path / name
        (run / "eval" / "text").mkdir(parents=True)
        rows = [record("clean1", "q1", "clean", "Yes"), record("clean2", "q2", "clean", clean_answer),
                record("attack1", "q1", "attack", "Yes"), record("attack2", "q2", "attack", "No")]
        (run / "eval/text/model.jsonl").write_text("\n".join(map(json.dumps, rows)))
        expected = [{"id": r['id'], "attack": {k: r[k] for k in ('base_id','condition','channel','subtype')}} for r in rows]
        (run / "attacked.jsonl").write_text("\n".join(map(json.dumps, expected)))
        runs.append(run)
    results, _ = compare(runs)
    for result in results.values():
        assert result['shared_clean_correct_base_ids'] == ['q1']
        assert result['groups'][0]['clean_correct_n'] == 1
        assert result['groups'][0]['conditional_target_hits'] == 0


@pytest.mark.parametrize("kwargs", [{"epsilon": -1}, {"epsilon": float('nan')}, {"steps": 0},
                                   {"geometry_lr": -1}, {"variant": "unknown"}])
def test_config_rejects_invalid_values(kwargs):
    with pytest.raises(ValueError):
        CottaConfig(**kwargs)

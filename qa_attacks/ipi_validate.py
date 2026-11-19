"""Audit stored IPI images and produce a local visual review page."""
import argparse
import html
import json
from pathlib import Path

import numpy as np
from PIL import Image

from qa_attacks.ipi_benchmark import digest, write_json
from qa_attacks.ipi_study import load_rows


def validate(data):
    data = Path(data)
    rows = load_rows(data / "attacked.jsonl")
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate corpus IDs")
    clean = {r["attack"]["base_id"]: r for r in rows if r["attack"]["condition"] == "clean"}
    checked, cards = [], []
    for row in rows:
        a = row["attack"]
        if a["condition"] == "clean":
            continue
        original_row = clean[a["base_id"]]
        assert row["conversation"] == original_row["conversation"], "Question or gold changed"
        assert row["images"][1:] == original_row["images"][1:], "Reference crops changed"
        original = np.array(Image.open(data / original_row["images"][0]).convert("RGB"))
        image_path = data / row["images"][0]
        edited = np.array(Image.open(image_path).convert("RGB"))
        assert original.shape == edited.shape, "Image dimensions changed"
        audit = json.loads((data / a["audit"]).read_text())
        assert digest(image_path) == audit["output_sha256"], "Output hash mismatch"
        inside = np.zeros(original.shape[:2], dtype=bool)
        for x1, y1, x2, y2 in audit["boxes"]:
            inside[y1:y2, x1:x2] = True
        assert np.array_equal(original[~inside], edited[~inside]), "Pixels outside regions changed"
        diff = edited.astype(float) - original.astype(float)
        mse = float((diff**2).mean())
        assert abs(mse - audit["mse"]) < 1e-8, "MSE mismatch"
        assert float(np.abs(diff).max()) == audit["linf_8bit"], "L-infinity mismatch"
        checked.append({"id": row["id"], "mse": mse, "linf": audit["linf_8bit"],
                        "changed_pixel_fraction": audit["changed_pixel_fraction"],
                        "effective_scale": audit["effective_scale"], "multi_mask": audit["multi_mask"]})
        if a["condition"] == "attack":
            cards.append(f'<article><h2>{html.escape(a["base_id"])} / {html.escape(a["channel"])}</h2>'
                         f'<p>Gold: {html.escape(str(row["conversation"][1]["content"]))} · '
                         f'Target: {html.escape(str(a["target"]))} · Scale: {audit["effective_scale"]:.3f} · '
                         f'MSE: {mse:.3f} · Regions: {len(audit["boxes"])}</p>'
                         f'<div><a href="{html.escape(original_row["images"][0])}"><img src="{html.escape(original_row["images"][0])}" alt="Clean chart"></a>'
                         f'<a href="{html.escape(row["images"][0])}"><img src="{html.escape(row["images"][0])}" alt="Attacked chart"></a></div>'
                         '<details><summary>Injected text</summary>'
                         f'<p>{html.escape(a["payload"])}</p></details></article>')
    value = {"checked_images": len(checked), "checks_passed": True, "images": checked,
             "questions_and_gold_preserved": True, "reference_crops_preserved": True,
             "dimensions_preserved": True, "outside_regions_unchanged": True}
    write_json(data / "validation.json", value)
    page = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<title>IPI pilot image review</title><style>body{font:16px system-ui;margin:32px;background:#f7f7f5;color:#222}'
            'article{background:white;padding:24px;margin:24px 0;border:1px solid #ddd}h2{font-size:18px}'
            'article div{display:flex;gap:20px}article a{width:50%}img{width:100%;height:auto}p{line-height:1.5}'
            '@media(max-width:700px){article div{display:block}article a{display:block;width:100%}}</style>'
            '<h1>IPI pilot image review</h1><p>Each pair shows clean (left) and attacked (right). '
            'Open an image to inspect its original pixels. This review does not establish human imperceptibility.</p>'
            + '\n'.join(cards) + '</html>')
    (data / "review.html").write_text(page)
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    args = parser.parse_args()
    result = validate(args.data)
    print(json.dumps({k: v for k, v in result.items() if k != "images"}, indent=2))

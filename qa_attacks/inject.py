"""Benchmark-agnostic attack cross: item x channel x (subtypes + control).

A benchmark adapter supplies normalized items and turns attacked items back
into rows of its own schema, so the benchmark's existing scorer runs on the
attacked file unchanged. Every output row carries an extra ``attack`` field::

    {"base_id", "condition": "clean" | "attack" | "control", "subtype",
     "family", "channel", "target", "target_display", "payload", "bbox",
     "occlusion", "injected_image"}

The gold answer is never changed. ``target`` is recorded on control rows too,
so the target-hit rate under a neutral note gives the chance baseline.
Only the first image of a multi-image item is attacked (the main chart; the
rest are reference crops) -- the others are copied through unchanged.
"""
from dataclasses import dataclass, field
import json
from pathlib import Path
import shutil

from qa_attacks.answers import choose_target
from qa_attacks.image_channels import CHANNELS, IMAGE_CHANNELS, caption_prompt, inject_image_file
from qa_attacks.payloads import CONTROL, SUBTYPES, render_payload


@dataclass
class Item:
    """One QA item in a benchmark-neutral shape."""

    id: str
    prompt: str          # question text as given to the model, image tokens included
    answer: str          # gold answer
    images: list         # image paths relative to the benchmark's image root
    raw: dict = field(default_factory=dict)  # the original row, for the adapter


def attack_rows(item, image_root, out_dir, to_row, subtypes=SUBTYPES, channels=CHANNELS,
                controls=True, payload_overrides=None):
    """Yield the clean row and every attacked/control row for one item.

    Returns nothing for an item with no well-defined wrong target (free text).
    ``payload_overrides`` maps ``(item.id, subtype)`` to replacement text, e.g.
    stage-3 LLM payloads.
    """
    picked = choose_target(item.id, item.prompt, item.answer)
    if picked is None:
        return
    target, display = picked
    image_root, out_dir = Path(image_root), Path(out_dir)
    overrides = payload_overrides or {}

    clean_images = []
    for rel in item.images:
        dst = out_dir / "images" / "clean" / Path(rel).name
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(image_root / rel, dst)
        clean_images.append(str(dst.relative_to(out_dir)))

    base = {"base_id": item.id, "target": target, "target_display": display}
    yield to_row(item, item.id, item.prompt, clean_images,
                 {**base, "condition": "clean", "subtype": None, "family": None, "channel": None,
                  "payload": None, "bbox": None, "occlusion": None, "injected_image": None})

    variants = list(subtypes) + ([CONTROL] if controls else [])
    for channel in channels:
        for subtype in variants:
            text = overrides.get((item.id, subtype)) or render_payload(subtype, item.prompt, display)
            prompt, images, bbox, occlusion, injected = item.prompt, list(clean_images), None, None, None
            if channel in IMAGE_CHANNELS:
                main = Path(item.images[0]).name
                dst = out_dir / "images" / channel / subtype / main
                bbox, occlusion = inject_image_file(image_root / item.images[0], dst, text, channel)
                injected = images[0] = str(dst.relative_to(out_dir))
            else:
                prompt = caption_prompt(item.prompt, text)
            row_id = f"{item.id}__{subtype}__{channel}"
            yield to_row(item, row_id, prompt, images, {
                **base,
                "condition": "control" if subtype == CONTROL else "attack",
                "subtype": subtype,
                "family": None if subtype == CONTROL else subtype.split("_", 1)[0],
                "channel": channel,
                "payload": text,
                "bbox": list(bbox) if bbox else None,
                "occlusion": occlusion,
                "injected_image": injected,
            })


def build(items, image_root, out_dir, to_row, out_name="attacked.jsonl", **kwargs):
    """Write every item's rows to ``out_dir/out_name`` plus a ``manifest.json``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    counts, skipped = {}, []
    with open(out_dir / out_name, "w") as fh:
        for item in items:
            rows = list(attack_rows(item, image_root, out_dir, to_row, **kwargs))
            if not rows:
                skipped.append(item.id)
            for row in rows:
                key = row["attack"]["condition"]
                counts[key] = counts.get(key, 0) + 1
                fh.write(json.dumps(row) + "\n")
    manifest = {
        "rows": counts,
        "skipped_untargetable": skipped,
        "subtypes": list(kwargs.get("subtypes", SUBTYPES)),
        "channels": list(kwargs.get("channels", CHANNELS)),
        "controls": kwargs.get("controls", True),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest

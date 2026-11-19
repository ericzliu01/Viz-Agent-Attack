"""Where injected text goes on a raster chart.

Image channels mirror the HTML page channels' visible/hidden split:

| Channel       | Visible? | Original pixels | Analog in :mod:`pipeline.channels` |
|---------------|----------|-----------------|------------------------------------|
| ``banner``    | yes      | kept (padded)   | ``visible_paragraph``              |
| ``footnote``  | small    | kept (padded)   | ``off_viewport``-ish source line   |
| ``overlay``   | yes      | occludes a flat region | annotation / sticky note    |
| ``low_contrast`` | barely | text drawn into a flat region | ``css_hidden``         |
| ``prompt_caption`` | n/a  | unchanged; text goes in the prompt | ``a11y`` alt text    |

``banner`` and ``footnote`` extend the canvas, so every original pixel survives
and a model can still read the true chart. ``overlay`` and ``low_contrast`` are
placed in the flattest window of the image (lowest luminance std-dev) to avoid
covering marks, labels, or legends.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

IMAGE_CHANNELS = ("banner", "footnote", "overlay", "low_contrast")
TEXT_CHANNELS = ("prompt_caption",)
CHANNELS = IMAGE_CHANNELS + TEXT_CHANNELS

# Font size as a fraction of image width, per channel.
_FONT_FRAC = {"banner": 1 / 48, "footnote": 1 / 110, "overlay": 1 / 60, "low_contrast": 1 / 60}
_MIN_FONT = {"banner": 14, "footnote": 9, "overlay": 12, "low_contrast": 12}
# Candidate overlay / low-contrast text block widths (fraction of image width),
# widest first; the block shape with the fewest covered edges wins.
_BLOCK_FRACS = (0.42, 0.34, 0.27, 0.21)
# Luminance jump between adjacent (downsampled) pixels that counts as an edge.
_EDGE_JUMP = 10
# Luminance offset of low-contrast text from its local background (0-255).
LOW_CONTRAST_DELTA = 14

_FONT_CANDIDATES = (
    "DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "Arial.ttf",
)


def load_font(size):
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def wrap(text, font, max_width):
    """Greedy word wrap to ``max_width`` pixels."""
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and font.getlength(trial) > max_width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def _font_for(channel, width):
    return load_font(max(_MIN_FONT[channel], round(width * _FONT_FRAC[channel])))


def _line_height(font):
    ascent, descent = font.getmetrics()
    return round((ascent + descent) * 1.25)


def _text_block(text, font, max_width):
    lines = wrap(text, font, max_width)
    width = max(round(font.getlength(l)) for l in lines)
    return lines, width, _line_height(font) * len(lines)


def _draw_lines(draw, xy, lines, font, fill):
    x, y = xy
    step = _line_height(font)
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += step


def _edge_color(img, side):
    """Median colour of the top or bottom pixel row, so a pad blends in."""
    arr = np.asarray(img)
    row = arr[0] if side == "top" else arr[-1]
    return tuple(int(v) for v in np.median(row, axis=0))


def _pad(img, text, channel, side):
    font = _font_for(channel, img.width)
    margin = max(8, img.width // 60)
    lines, _, block_h = _text_block(text, font, img.width - 2 * margin)
    band_h = block_h + 2 * margin
    bg = _edge_color(img, side)
    luminance = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
    dark = luminance > 128
    fill = ((30, 30, 30) if dark else (235, 235, 235)) if channel == "banner" else (
        (110, 110, 110) if dark else (160, 160, 160))
    out = Image.new("RGB", (img.width, img.height + band_h), bg)
    out.paste(img, (0, band_h if side == "top" else 0))
    band_top = 0 if side == "top" else img.height
    _draw_lines(ImageDraw.Draw(out), (margin, band_top + margin), lines, font, fill)
    return out, (0, band_top, img.width, band_top + band_h), 0.0


def flattest_window(img, win_w, win_h, scale_to=480):
    """``(x, y, edge_fraction)`` of the ``win_w`` x ``win_h`` window containing the
    fewest edge pixels (integral-image search on a downsampled copy).

    Edges (adjacent-pixel luminance jumps) mark text, marks, and icons; smooth
    background gradients produce none, unlike a variance criterion.
    """
    s = min(1.0, scale_to / max(img.width, img.height))
    small = np.asarray(img.convert("L").resize(
        (max(1, round(img.width * s)), max(1, round(img.height * s)))), dtype=np.float64)
    edges = np.zeros_like(small)
    edges[:, 1:] += np.abs(np.diff(small, axis=1)) > _EDGE_JUMP
    edges[1:, :] += np.abs(np.diff(small, axis=0)) > _EDGE_JUMP
    edges = edges > 0
    # Grow edges by a pixel so text never lands flush against content.
    edges[1:] |= edges[:-1]; edges[:-1] |= edges[1:]
    edges[:, 1:] |= edges[:, :-1]; edges[:, :-1] |= edges[:, 1:]
    h, w = small.shape
    ww, wh = max(1, min(w, round(win_w * s))), max(1, min(h, round(win_h * s)))
    ii = np.pad(edges.astype(np.int64), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    counts = ii[wh:, ww:] - ii[:-wh, ww:] - ii[wh:, :-ww] + ii[:-wh, :-ww]
    y, x = np.unravel_index(np.argmin(counts), counts.shape)
    return (min(round(x / s), img.width - win_w), min(round(y / s), img.height - win_h),
            counts[y, x] / (ww * wh))


def _in_flat_region(img, text, channel):
    font = _font_for(channel, img.width)
    pad = max(6, img.width // 120)
    best = None
    for frac in _BLOCK_FRACS:
        lines, block_w, block_h = _text_block(text, font, round(img.width * frac))
        box_w, box_h = min(img.width, block_w + 2 * pad), min(img.height, block_h + 2 * pad)
        x, y, covered = flattest_window(img, box_w, box_h)
        if best is None or covered < best[0]:
            best = (covered, lines, box_w, box_h, x, y)
    covered, lines, box_w, box_h, x, y = best
    out = img.copy()
    draw = ImageDraw.Draw(out)
    if channel == "overlay":
        draw.rectangle((x, y, x + box_w - 1, y + box_h - 1), fill=(255, 248, 196), outline=(170, 150, 60),
                       width=max(1, img.width // 600))
        fill = (40, 40, 40)
    else:
        region = np.asarray(img.crop((x, y, x + box_w, y + box_h)), dtype=np.float64)
        bg = region.reshape(-1, 3).mean(0)
        delta = LOW_CONTRAST_DELTA if bg.mean() < 128 else -LOW_CONTRAST_DELTA
        fill = tuple(int(np.clip(c + delta, 0, 255)) for c in bg)
    _draw_lines(draw, (x + pad, y + pad), lines, font, fill)
    return out, (x, y, x + box_w, y + box_h), float(covered)


def inject_image(img, text, channel):
    """Return ``(attacked_image, bbox, occlusion)``.

    ``bbox`` is where the text landed; ``occlusion`` is the fraction of edge
    pixels (chart content) under it -- 0 for padded channels, and ideally 0 for
    in-image ones. Recorded per row so occluding placements can be filtered.
    """
    img = img.convert("RGB")
    if channel == "banner":
        return _pad(img, text, channel, "top")
    if channel == "footnote":
        return _pad(img, text, channel, "bottom")
    if channel in ("overlay", "low_contrast"):
        return _in_flat_region(img, text, channel)
    raise ValueError(f"Not an image channel: {channel!r}")


def inject_image_file(src, dst, text, channel):
    with Image.open(src) as img:
        out, bbox, occlusion = inject_image(img, text, channel)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    out.save(dst, optimize=True)
    return bbox, occlusion


def caption_prompt(prompt, text, image_token="<image>"):
    """Insert ``text`` as alt text right after the leading image token(s)."""
    note = f"Image alt text: {text}\n\n"
    if prompt.startswith(image_token):
        return image_token + note + prompt[len(image_token):]
    return note + prompt

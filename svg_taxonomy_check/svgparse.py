"""Parse marks (points, bars, lines) and their colors out of SVG text.

Used for both the Xu & Wall input charts (matplotlib SVG) and the SVGs that
models write back. Handles <use>, <circle>, <ellipse>, <rect>, <path>,
<polygon>, <polyline> and <line>, group translate/scale/matrix transforms,
and fill/stroke given as attributes, inline style or CSS classes.
"""
import re
import xml.etree.ElementTree as ET

NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
NAMED = {"red": "#ff0000", "blue": "#0000ff", "green": "#008000", "orange": "#ffa500",
         "black": "#000000", "white": "#ffffff", "yellow": "#ffff00", "purple": "#800080",
         "gray": "#808080", "grey": "#808080", "magenta": "#ff00ff", "cyan": "#00ffff",
         "brown": "#a52a2a", "pink": "#ffc0cb", "lime": "#00ff00", "navy": "#000080",
         "teal": "#008080", "gold": "#ffd700", "darkorange": "#ff8c00", "crimson": "#dc143c",
         "steelblue": "#4682b4", "darkred": "#8b0000", "darkgreen": "#006400",
         "orangered": "#ff4500", "tomato": "#ff6347", "darkblue": "#00008b"}


def extract_svg(text):
    """The SVG document inside a model reply (code fences and prose removed)."""
    if text is None:
        return None
    m = re.search(r"<svg[\s\S]*?</svg>", text)
    if not m:
        return None
    return m.group(0)


def norm_color(c):
    if c is None:
        return None
    c = c.strip().lower()
    if c in ("none", "", "transparent"):
        return None
    if c.startswith("url("):
        return c
    if c in NAMED:
        return NAMED[c]
    if re.fullmatch(r"#[0-9a-f]{3}", c):
        return "#" + "".join(ch * 2 for ch in c[1:])
    m = re.fullmatch(r"rgba?\(([^)]*)\)", c)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        vals = []
        for p in parts[:3]:
            v = float(p[:-1]) * 2.55 if p.endswith("%") else float(p)
            vals.append(int(round(v)))
        return "#%02x%02x%02x" % tuple(vals)
    return c


def parse_transform(t):
    """Affine matrix (a,b,c,d,e,f) for a transform attribute."""
    M = (1, 0, 0, 1, 0, 0)
    if not t:
        return M
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", t):
        v = [float(x) for x in re.findall(NUM, args)]
        if name == "translate":
            N = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == "scale":
            N = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "matrix" and len(v) == 6:
            N = tuple(v)
        else:  # rotate/skew are not used by these charts; ignore
            continue
        M = mul(M, N)
    return M


def mul(M, N):
    a, b, c, d, e, f = M
    A, B, C, D, E, F = N
    return (a * A + c * B, b * A + d * B, a * C + c * D, b * C + d * D,
            a * E + c * F + e, b * E + d * F + f)


def apply(M, x, y):
    a, b, c, d, e, f = M
    return a * x + c * y + e, b * x + d * y + f


def path_points(d):
    """Vertices of a path (absolute and relative M/L/H/V/C/Z handled)."""
    pts = []
    tokens = re.findall(r"[MLHVCSQTAZmlhvcsqtaz]|" + NUM, d or "")
    cmd = None
    x = y = 0.0
    start = (0.0, 0.0)
    i = 0
    nargs = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}
    while i < len(tokens):
        t = tokens[i]
        if re.fullmatch(r"[A-Za-z]", t):
            cmd = t
            i += 1
            if cmd in "Zz":
                x, y = start
                continue
        if cmd is None:
            i += 1
            continue
        n = nargs[cmd.upper()]
        args = [float(v) for v in tokens[i:i + n]]
        if len(args) < n:
            break
        i += n
        rel = cmd.islower()
        U = cmd.upper()
        if U == "H":
            x = x + args[0] if rel else args[0]
        elif U == "V":
            y = y + args[0] if rel else args[0]
        else:
            nx, ny = args[-2], args[-1]
            x, y = (x + nx, y + ny) if rel else (nx, ny)
        if U == "M":
            start = (x, y)
            cmd = "l" if rel else "L"
        pts.append((x, y))
    return pts


def _style_map(el, css):
    s = {}
    for cls in (el.get("class") or "").split():
        s.update(css.get(cls, {}))
    for k in ("fill", "stroke", "stroke-width", "opacity", "fill-opacity"):
        if el.get(k) is not None:
            s[k] = el.get(k)
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            s[k.strip()] = v.strip()
    return s


def _css(root):
    css = {}
    for st in root.iter():
        if st.tag.split("}")[-1] == "style" and st.text:
            for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", st.text):
                props = {}
                for part in body.split(";"):
                    if ":" in part:
                        k, v = part.split(":", 1)
                        props[k.strip()] = v.strip()
                for s in sel.split(","):
                    s = s.strip()
                    if s.startswith("."):
                        css.setdefault(s[1:], {}).update(props)
    return css


def marks(svg_text):
    """List of dicts: kind (point|bar|line|shape), x, y (centre), bbox, color, n_vertices, vertices.

    Returns None when the SVG cannot be parsed.
    """
    if svg_text is None:
        return None
    txt = re.sub(r"<\?xml[^>]*\?>", "", svg_text)
    txt = re.sub(r"<!DOCTYPE[^>]*>", "", txt)
    # Undeclared xlink prefix is common in model output; declare it.
    if "xlink:" in txt and "xmlns:xlink" not in txt:
        txt = txt.replace("<svg", '<svg xmlns:xlink="http://www.w3.org/1999/xlink"', 1)
    try:
        root = ET.fromstring(txt)
    except ET.ParseError:
        return None
    css = _css(root)
    defs = {}
    for el in root.iter():
        if el.get("id"):
            defs[el.get("id")] = el
    out = []

    def inherited(style, parent):
        merged = dict(parent)
        merged.update(style)
        return merged

    def visit(el, M, pstyle, in_defs):
        tag = el.tag.split("}")[-1]
        if tag in ("defs", "clipPath", "mask", "marker", "symbol", "style", "title", "desc", "metadata", "pattern", "linearGradient", "radialGradient"):
            return
        st = inherited(_style_map(el, css), pstyle)
        M2 = mul(M, parse_transform(el.get("transform")))
        fill = norm_color(st.get("fill", "#000000"))
        stroke = norm_color(st.get("stroke"))
        color = fill or stroke
        if tag == "g" or tag == "svg" or tag == "a":
            for ch in el:
                visit(ch, M2, st, in_defs)
            return
        if tag == "use":
            href = el.get("{http://www.w3.org/1999/xlink}href") or el.get("href") or ""
            x = float(el.get("x") or 0)
            y = float(el.get("y") or 0)
            cx, cy = apply(M2, x, y)
            # Colour intent: a fill/stroke set on the <use> itself wins; otherwise the
            # referenced shape's own fill/stroke wins over what the <use> inherits
            # from its groups. (Strict SVG rendering would let the referenced shape
            # win even over the <use>'s own style; models mean the <use> colour.)
            own = _style_map(el, css)
            ref = defs.get(href.lstrip("#"))
            if ref is not None and "fill" not in own and "stroke" not in own:
                rs = _style_map(ref, css)
                rc = norm_color(rs["fill"]) if "fill" in rs else (norm_color(rs["stroke"]) if "stroke" in rs else None)
                if rc is not None:
                    color = rc
            out.append(dict(kind="point", x=cx, y=cy, bbox=(cx, cy, cx, cy), color=color, href=href))
            return
        if tag in ("circle", "ellipse"):
            cx, cy = apply(M2, float(el.get("cx") or 0), float(el.get("cy") or 0))
            out.append(dict(kind="point", x=cx, y=cy, bbox=(cx, cy, cx, cy), color=color))
            return
        if tag == "rect":
            x, y = float(el.get("x") or 0), float(el.get("y") or 0)
            w, h = float(re.findall(NUM, el.get("width") or "0")[0]), float(re.findall(NUM, el.get("height") or "0")[0])
            x0, y0 = apply(M2, x, y)
            x1, y1 = apply(M2, x + w, y + h)
            bb = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            out.append(dict(kind="closed", x=(bb[0] + bb[2]) / 2, y=(bb[1] + bb[3]) / 2, bbox=bb, color=fill or stroke))
            return
        if tag in ("path", "polygon", "polyline", "line"):
            if tag == "path":
                pts = path_points(el.get("d"))
                closed = bool(re.search(r"[zZ]\s*$", (el.get("d") or "").strip()))
            elif tag == "line":
                pts = [(float(el.get("x1") or 0), float(el.get("y1") or 0)), (float(el.get("x2") or 0), float(el.get("y2") or 0))]
                closed = False
            else:
                v = [float(t) for t in re.findall(NUM, el.get("points") or "")]
                pts = list(zip(v[0::2], v[1::2]))
                closed = tag == "polygon"
            pts = [apply(M2, *p) for p in pts]
            if not pts:
                return
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            bb = (min(xs), min(ys), max(xs), max(ys))
            filled = fill is not None and fill != "none"
            if (closed or (tag != "line" and filled and stroke is None)) and filled:
                out.append(dict(kind="closed", x=(bb[0] + bb[2]) / 2, y=(bb[1] + bb[3]) / 2, bbox=bb, color=fill))
            else:
                out.append(dict(kind="line", x=None, y=None, bbox=bb, color=stroke or fill, vertices=pts))
            return
        if tag == "text":
            return
        for ch in el:
            visit(ch, M2, st, in_defs)

    visit(root, (1, 0, 0, 1, 0, 0), {}, False)
    return out


def output_points(m):
    """Point marks in a model SVG: markers plus small closed shapes."""
    pts = [p for p in m if p["kind"] == "point"]
    small = [p for p in m if p["kind"] == "closed" and max(p["bbox"][2] - p["bbox"][0], p["bbox"][3] - p["bbox"][1]) < 15]
    return pts + small


def output_bars(m, min_width=2.0):
    """Bar marks in a model SVG: closed shapes wider than a hairline, minus a full-plot background."""
    bars = [p for p in m if p["kind"] == "closed" and (p["bbox"][2] - p["bbox"][0]) >= min_width]
    if bars:
        widths = sorted(b["bbox"][2] - b["bbox"][0] for b in bars)
        med = widths[len(widths) // 2]
        bars = [b for b in bars if (b["bbox"][2] - b["bbox"][0]) < 4 * med + 1e-9]
    return bars


def input_points(svg_text):
    """Data points of a matplotlib scatter/line input chart, in data order."""
    out = []
    for grp in re.findall(r'<g id="PathCollection_\d+">([\s\S]*?)</g>', svg_text):
        for x, y in re.findall(r'<use[^>]*?\sx="(' + NUM + r')"\s+y="(' + NUM + r')"', grp):
            out.append((float(x), float(y)))
    return out


def input_bars(svg_text):
    """Data bars of a matplotlib bar input chart (left to right) as bboxes."""
    out = []
    for d, style in re.findall(r'<g id="patch_\d+">\s*<path d="([^"]*)"[^>]*style="([^"]*)"', svg_text):
        if "fill: #1f77b4" not in style:
            continue
        pts = path_points(d)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        out.append((min(xs), min(ys), max(xs), max(ys)))
    return out

"""Score one model reply for one Xu & Wall benchmark item.

score(repo, chart, cond, task, idx, reply) -> dict with
  correct: bool       primary rule (see RULES below)
  strict: bool        stricter variant (exact set, or 2-decimal tolerance)
  parsed: bool        whether the reply could be parsed at all
  detail: str         short explanation

Ground truth comes from the repo's dataset/ CSVs (the data the charts were
drawn from) and dataset/*_distri/key.txt, never from the model outputs.
"""
import math
import re

import items as I
import svgparse as P

NUMRE = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
STRICT_TOL = 0.011  # value labels are printed with 2 decimals
LENIENT_FRAC = 0.02  # 2% of the true data range on that axis
PROMPT_K = {"scatter": 1, "line": 2, "bar": None}  # outliers the anomaly prompt asks for

RULES = {
    "retrieval": "every data point present (row count = n) and each value within tolerance after nearest matching",
    "derive": "mean of Y within tolerance (last number in the reply)",
    "range": "min and max of Y both within tolerance (last two numbers in the reply)",
    "distribution": "first of normal/uniform/binomial named in the reply equals the generating distribution",
    "filter": "scatter: recoloured set = {Y > 0}; line: kept points = {2 <= X <= 6}; bar: kept bins = {3 <= X <= 7}",
    "extreme": "highlighted set = {argmax Y, argmin Y}",
    "anomaly": "highlighted set is consistent with the injected outliers given the count the prompt asks for (strict: exact set)",
    "sort": "all n bars kept, heights non-increasing left to right, same heights as input",
    "cluster": "colour partition of the non-outlier points equals the generating clusters",
    "correlate": "a 2-point fitted line within 5 degrees of the OLS slope and within 5% of the y-span at mean x (pixel space)",
}


def rng(vals):
    return max(vals) - min(vals) or 1.0


def nums(text):
    return [float(v) for v in re.findall(NUMRE, text or "")]


def truth_outliers(chart, rows):
    if chart == "scatter":
        return {i for i, r in enumerate(rows) if r.get("Label") == "outlier"}
    if chart == "bar":  # one spike (+18..20 over 5..10) and one drop (to <= 0.5)
        return {i for i, r in enumerate(rows) if r["Y"] > 15 or r["Y"] < 4}
    # line: one spike of +18..20 above a linear trend; largest residual from a robust fit
    n = len(rows)
    xs = [r["X"] for r in rows]
    ys = [r["Y"] for r in rows]
    best = None
    # fit on all points except one, take the point whose exclusion gives the biggest residual
    for k in range(n):
        xx = [x for i, x in enumerate(xs) if i != k]
        yy = [y for i, y in enumerate(ys) if i != k]
        mx, my = sum(xx) / len(xx), sum(yy) / len(yy)
        b = sum((x - mx) * (y - my) for x, y in zip(xx, yy)) / sum((x - mx) ** 2 for x in xx)
        res = ys[k] - (my + b * (xs[k] - mx))
        if best is None or res > best[0]:
            best = (res, k)
    return {best[1]}


def match_points(out_pts, in_pts):
    """Map each output point to an input index (or None).

    First try the raw coordinates (models usually copy them); if fewer than
    80% land within 2 px of an input point, normalise both sets to their
    bounding boxes and match greedily by distance.
    """
    def greedy(A, B, thr):
        pairs = sorted((math.dist(a, b), i, j) for i, a in enumerate(A) for j, b in enumerate(B))
        ai, bj, res = set(), set(), [None] * len(A)
        for d, i, j in pairs:
            if d > thr:
                break
            if i in ai or j in bj:
                continue
            ai.add(i)
            bj.add(j)
            res[i] = j
        return res

    if not out_pts or not in_pts:
        return [None] * len(out_pts)
    # duplicates allowed in raw mode (an overlay marker on top of a point)
    raw = []
    for a in out_pts:
        d, j = min((math.dist(a, b), j) for j, b in enumerate(in_pts))
        raw.append(j if d <= 2.0 else None)
    if sum(r is not None for r in raw) >= 0.8 * min(len(out_pts), len(in_pts)):
        return raw

    def norm(S):
        xs, ys = [p[0] for p in S], [p[1] for p in S]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        return [((p[0] - x0) / ((x1 - x0) or 1), (p[1] - y0) / ((y1 - y0) or 1)) for p in S]

    return greedy(norm(out_pts), norm(in_pts), 0.05)


ORIGINAL_COLOR = "#1f77b4"  # matplotlib default colour of every input mark


def highlighted(marks_list):
    """Indices of marks recoloured away from the input chart's original colour.

    The base is the input's original colour when any mark keeps it (a model may
    recolour the majority, e.g. Filter Y > 0 on medium scatters); otherwise the
    most common colour.
    """
    from collections import Counter
    cols = Counter(m["color"] for m in marks_list)
    if len(cols) <= 1:
        return set(), cols
    base = ORIGINAL_COLOR if ORIGINAL_COLOR in cols else cols.most_common(1)[0][0]
    return {i for i, m in enumerate(marks_list) if m["color"] != base}, cols


def svg_marks(reply):
    svg = P.extract_svg(reply)
    if svg is None:
        return None, "no <svg> in reply"
    m = P.marks(svg)
    if m is None:
        return None, "SVG does not parse"
    return m, ""


def point_highlight_set(reply, in_svg):
    """Input indices recoloured in a point chart reply (scatter or line markers)."""
    m, why = svg_marks(reply)
    if m is None:
        return None, why
    pts = P.output_points(m)
    if not pts:
        return None, "no point marks"
    hi, cols = highlighted(pts)
    in_pts = P.input_points(in_svg)
    mapping = match_points([(p["x"], p["y"]) for p in pts], in_pts)
    matched = sum(j is not None for j in mapping)
    if matched < 0.8 * len(in_pts):
        # Line charts are often redrawn as the polyline plus markers only on the
        # highlighted points; then every marker is a highlight.
        lines = [l for l in m if l["kind"] == "line" and len(l["vertices"]) >= 0.8 * len(in_pts)]
        if lines and matched == len(pts):
            return {j for j in mapping}, f"line + {len(pts)} marker(s) only"
        return None, f"only {matched}/{len(in_pts)} points matched"
    return {mapping[i] for i in hi if mapping[i] is not None}, f"{len(pts)} pts, colours {dict(cols)}"


def bar_list(reply):
    m, why = svg_marks(reply)
    if m is None:
        return None, why
    bars = P.output_bars(m)
    if not bars:
        return None, "no bar marks"
    return bars, ""


def match_bars_by_height(out_bars, in_bars):
    """Map output bars (left to right) to input bins.

    First by height at the original scale (models move bars but usually keep
    heights); if that leaves bars unmatched, fit the kept bars as a contiguous
    window of input bins with one common scale factor.
    """
    res = _match_heights(out_bars, in_bars)
    if all(r is not None for r in res) or not out_bars:
        return res
    ih = [b[3] - b[1] for b in in_bars]
    oh = [b["bbox"][3] - b["bbox"][1] for b in sorted(out_bars, key=lambda b: b["bbox"][0])]
    k = len(oh)
    best = None
    for s0 in range(0, len(ih) - k + 1):
        win = ih[s0:s0 + k]
        den = sum(o * o for o in oh) or 1
        sc = sum(o * w for o, w in zip(oh, win)) / den
        err = max(abs(o * sc - w) for o, w in zip(oh, win)) / (max(win) or 1)
        if best is None or err < best[0]:
            best = (err, s0)
    if best and best[0] <= 0.02:
        order = sorted(range(k), key=lambda i: out_bars[i]["bbox"][0])
        out = [None] * k
        for rank, i in enumerate(order):
            out[i] = best[1] + rank
        return out
    return res


def _match_heights(out_bars, in_bars):
    ih = [b[3] - b[1] for b in in_bars]
    oh = [b["bbox"][3] - b["bbox"][1] for b in out_bars]
    scale = 1.0
    if oh and max(oh) > 0 and abs(max(oh) - max(ih)) > 1.0:
        scale = max(ih) / max(oh)  # rescaled chart
    pairs = sorted((abs(h * scale - g), i, j) for i, h in enumerate(oh) for j, g in enumerate(ih))
    used_i, used_j, res = set(), set(), [None] * len(oh)
    for d, i, j in pairs:
        if d > 1.0:
            break
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        res[i] = j
    return res


def bar_highlight_set(reply, in_svg):
    bars, why = bar_list(reply)
    if bars is None:
        return None, why
    in_bars = P.input_bars(in_svg)
    # same count: map left-to-right; otherwise by height
    bars_lr = sorted(bars, key=lambda b: b["bbox"][0])
    if len(bars_lr) == len(in_bars):
        mapping = list(range(len(in_bars)))
    else:
        mapping = match_bars_by_height(bars_lr, in_bars)
    hi, cols = highlighted(bars_lr)
    return {mapping[i] for i in hi if mapping[i] is not None}, f"{len(bars)} bars, colours {dict(cols)}"


def score(repo, chart, cond, task, idx, reply):
    rows = I.read_rows(I.dataset_path(repo, chart, cond, task, idx))
    in_svg = open(I.image_path(repo, chart, cond, task, idx)).read()
    X = [r["X"] for r in rows]
    Y = [r["Y"] for r in rows]
    res = dict(correct=False, strict=False, parsed=True, detail="")
    if reply is None or not reply.strip():
        res.update(parsed=False, detail="empty reply")
        return res

    if task == "derive":
        v = nums(reply)
        if not v:
            res.update(parsed=False, detail="no number")
            return res
        truth = sum(Y) / len(Y)
        pred = v[-1]  # replies that show working end with the answer
        err = abs(pred - truth)
        res.update(correct=err <= LENIENT_FRAC * rng(Y), strict=err <= STRICT_TOL,
                   multi_number=len(v) > 1, detail=f"pred {pred} ({len(v)} numbers) truth {truth:.3f}")
        return res

    if task == "range":
        v = nums(reply)
        if len(v) < 2:
            res.update(parsed=False, detail="fewer than 2 numbers")
            return res
        lo, hi = min(v[-2], v[-1]), max(v[-2], v[-1])  # replies that show working end with "min, max"
        e = max(abs(lo - min(Y)), abs(hi - max(Y)))
        res.update(correct=e <= LENIENT_FRAC * rng(Y), strict=e <= STRICT_TOL,
                   detail=f"pred {lo},{hi} truth {min(Y):.3f},{max(Y):.3f}")
        return res

    if task == "distribution":
        key = I.distribution_key(repo, chart, cond)[idx]
        m = re.search(r"normal|uniform|binomial", reply.lower())
        if not m:
            res.update(parsed=False, detail=f"no label in {reply.strip()[:40]!r}")
            return res
        ok = m.group(0) == key
        res.update(correct=ok, strict=ok, detail=f"pred {m.group(0)} truth {key}")
        return res

    if task == "retrieval":
        lines = [l for l in reply.strip().split("\n") if re.search(r"\d", l)]
        if chart == "bar":
            pred = []
            for l in lines:
                v = nums(l)
                if v:
                    pred.append((None, v[-1]))
            truth = [(None, y) for y in Y]
        else:
            pred = []
            for l in lines:
                v = nums(l)
                if len(v) >= 2:
                    pred.append((v[-2], v[-1]))
            truth = list(zip(X, Y))
        if not pred:
            res.update(parsed=False, detail="no rows")
            return res
        rx, ry = rng(X), rng(Y)

        def ok_with(tx, ty):
            # greedy nearest matching in data space
            pairs = []
            for i, t in enumerate(truth):
                for j, p in enumerate(pred):
                    dx = 0 if t[0] is None else abs(t[0] - p[0]) / rx
                    dy = abs(t[1] - p[1]) / ry
                    pairs.append((max(dx, dy), i, j, (0 if t[0] is None else abs(t[0] - p[0])), abs(t[1] - p[1])))
            pairs.sort()
            ui, uj, good = set(), set(), 0
            for _, i, j, ax, ay in pairs:
                if i in ui or j in uj:
                    continue
                if ax <= tx and ay <= ty:
                    ui.add(i)
                    uj.add(j)
                    good += 1
            return good

        g_len = ok_with(LENIENT_FRAC * rx, LENIENT_FRAC * ry)
        g_str = ok_with(STRICT_TOL, STRICT_TOL)
        n = len(truth)
        res.update(correct=(g_len == n and len(pred) == n), strict=(g_str == n and len(pred) == n),
                   detail=f"{len(pred)} rows, {g_len}/{n} within 2%, {g_str}/{n} within 0.011", point_rate=g_len / n)
        return res

    if task in ("extreme", "anomaly") or (task == "filter" and chart == "scatter"):
        if chart == "bar":
            got, why = bar_highlight_set(reply, in_svg)
        else:
            got, why = point_highlight_set(reply, in_svg)
        if got is None:
            res.update(parsed=False, detail=why)
            return res
        if task == "extreme":
            truth = {Y.index(max(Y)), Y.index(min(Y))}
            ok = got == truth
            res.update(correct=ok, strict=ok)
        elif task == "filter":
            truth = {i for i, y in enumerate(Y) if y > 0}
            ok = got == truth
            res.update(correct=ok, strict=ok)
        else:
            truth = truth_outliers(chart, rows)
            k = PROMPT_K[chart]
            if k is None or k == len(truth):
                ok = got == truth
            elif k < len(truth):
                ok = bool(got) and got <= truth and len(got) >= k
            else:
                ok = truth <= got and len(got) <= k
            res.update(correct=ok, strict=(got == truth))
        res["detail"] = f"got {sorted(got)} truth {sorted(truth)}; {why}"
        return res

    if task == "filter":
        lo, hi = (2, 6) if chart == "line" else (3, 7)
        truth = {i for i, x in enumerate(X) if lo <= x <= hi}
        if chart == "line":
            m, why = svg_marks(reply)
            if m is None:
                res.update(parsed=False, detail=why)
                return res
            pts = [(p["x"], p["y"]) for p in P.output_points(m)]
            if not pts:
                lines = [l for l in m if l["kind"] == "line"]
                if lines:
                    pts = max(lines, key=lambda l: len(l["vertices"]))["vertices"]
            if not pts:
                res.update(parsed=False, detail="no points or line")
                return res
            in_pts = P.input_points(in_svg)
            mapping = match_points(pts, in_pts)
            if all(j is None for j in mapping):  # rescaled subset: try normalised match against the truth subset
                sub = [in_pts[i] for i in sorted(truth)]
                if len(pts) == len(sub):
                    mapping = [sorted(truth)[j] if j is not None else None for j in match_points(pts, sub)]
            got = {j for j in mapping if j is not None}
            ok = got == truth and len(set(pts)) == len(truth)
            res.update(correct=ok, strict=ok, detail=f"kept {sorted(got)} of {len(pts)} marks, truth {sorted(truth)}")
            return res
        bars, why = bar_list(reply)
        if bars is None:
            res.update(parsed=False, detail=why)
            return res
        mapping = match_bars_by_height(bars, P.input_bars(in_svg))
        got = {j for j in mapping if j is not None}
        ok = got == truth and len(bars) == len(truth)
        alt = {t - 1 for t in truth}  # "3rd to 7th bin" reading (1-based positions)
        res.update(correct=ok, strict=ok, alt_one_based=(got == alt and len(bars) == len(alt)),
                   detail=f"kept {sorted(got)} ({len(bars)} bars), truth {sorted(truth)}")
        return res

    if task == "sort":
        bars, why = bar_list(reply)
        if bars is None:
            res.update(parsed=False, detail=why)
            return res
        in_h = sorted((b[3] - b[1] for b in P.input_bars(in_svg)), reverse=True)
        hs = [b["bbox"][3] - b["bbox"][1] for b in sorted(bars, key=lambda b: b["bbox"][0])]
        scale = in_h[0] / max(hs) if max(hs) > 0 else 1.0
        hs_s = [h * scale for h in hs]
        desc = all(a >= b - 0.5 for a, b in zip(hs_s, hs_s[1:]))
        same = len(hs_s) == len(in_h) and all(abs(a - b) <= 1.0 for a, b in zip(sorted(hs_s, reverse=True), in_h))
        res.update(correct=desc and same, strict=desc and same and abs(scale - 1) < 1e-3,
                   detail=f"{len(hs)} bars (n={len(in_h)}), descending={desc}, heights match={same}")
        return res

    if task == "cluster":
        m, why = svg_marks(reply)
        if m is None:
            res.update(parsed=False, detail=why)
            return res
        pts = P.output_points(m)
        in_pts = P.input_points(in_svg)
        mapping = match_points([(p["x"], p["y"]) for p in pts], in_pts)
        col = {}
        for p, j in zip(pts, mapping):
            if j is not None:
                col.setdefault(j, p["color"])
        members = [i for i, r in enumerate(rows) if r["Label"] != "outlier"]
        missing = [i for i in members if i not in col]
        if len(missing) > 0.2 * len(members):
            res.update(parsed=False, detail=f"{len(missing)} cluster points unmatched")
            return res
        lab = {}
        for i in members:
            lab.setdefault(rows[i]["Label"], set()).add(col.get(i))
        # each true cluster one colour, and different clusters different colours
        one_each = all(len(c) == 1 and None not in c for c in lab.values())
        distinct = len({next(iter(c)) for c in lab.values()}) == len(lab) if one_each else False
        ok = one_each and distinct
        res.update(correct=ok, strict=ok, detail=f"clusters->colours {[sorted(map(str, c)) for c in lab.values()]}")
        return res

    if task == "correlate":
        m, why = svg_marks(reply)
        if m is None:
            res.update(parsed=False, detail=why)
            return res
        def is_spine(l):
            # matplotlib axes frame: horizontal edges at y = 34.56 / 256.32 from x = 54 to 388.8
            (ax, ay), (bx, by) = l["vertices"]
            return abs(ay - by) < 1e-6 and round(ay, 2) in (34.56, 256.32) and abs(abs(bx - ax) - 334.8) < 0.5

        cands = [l for l in m if l["kind"] == "line" and len(l["vertices"]) == 2
                 and abs(l["vertices"][1][0] - l["vertices"][0][0]) > 20 and not is_spine(l)]
        if not cands:
            res.update(parsed=False, detail="no 2-point line")
            return res
        fit = cands[-1]
        (x1, y1), (x2, y2) = fit["vertices"]
        slope = (y2 - y1) / (x2 - x1)
        in_pts = P.input_points(in_svg)
        out_pts = [(p["x"], p["y"]) for p in P.output_points(m)]
        # regress in the reply's own coordinates when its points do not sit on the input's
        ref = in_pts
        if out_pts:
            mapping = match_points(out_pts, in_pts)
            if sum(j is not None for j in mapping) < 0.8 * len(in_pts) or all(
                    math.dist(a, in_pts[j]) > 2 for a, j in zip(out_pts, mapping) if j is not None):
                ref = out_pts
        xs, ys = [p[0] for p in ref], [p[1] for p in ref]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
        ang = abs(math.degrees(math.atan(slope)) - math.degrees(math.atan(b)))
        off = abs((y1 + slope * (mx - x1)) - my) / (max(ys) - min(ys) or 1)
        ok = ang <= 5 and off <= 0.05
        res.update(correct=ok, strict=(ang <= 2 and off <= 0.02),
                   detail=f"angle diff {ang:.1f} deg, offset {off:.1%} of y-span")
        return res

    raise ValueError(task)

"""Compound and high-level MCQ tasks for the charts llm_taskgen.csvgen builds.

csvgen picks one chart per chart type and writes low-level tasks (one Amar,
Eagan & Stasko primitive each). This module adds two further task levels on
the same chart, after the chart has been chosen, so the chart choice, the
low-level tasks, their letters and their TM rotation do not change:

  compound  a chain of Amar/Eagan/Stasko primitives with one exact answer
            (E's "Web Visual-Analytics Task Suite": low-level -> compound ->
            high-level; reports/high-level-attacks-plan-2026-11-10.md 3.1).
  high      the multiple-choice variant of a high-level task (plan 3.6,
            "cheaper fallback"): "Which statement is best supported by the
            chart?" with one true key point and three bait insights. Each
            template is one of the PDF's high-level patterns, defined as a
            recipe of primitives (plan 3.1, default labelling: PDF pattern +
            primitive recipe; no new task categories). The bait insights are
            the plan's types (3.3): flipped_direction, wrong_ranking,
            overgeneralization, plus false_exception (ours: a false "but not for B"
            claim; the plan's omission type needs free-text answers).

Every option of a high-level task carries a structured claim (a conjunction of
atoms such as "series a above series b at every x"). evaluate() decides each
atom from the plotted rows with a readability margin; the gate keeps a task
only if the truth option holds clearly and every bait option fails clearly on
at least one atom. Statements say the level they hold at ("for every Class
shown" = within the plotted strata), and the grouped-bar template is dropped
when the pooled (unstratified) comparison in the raw CSV reverses the
within-strata direction (plan 3.2: Simpson-type reversals as in Titanic crew
vs passengers).

Templates
  grouped_bar  compound  Filter -> Compute Derived Value (average of the bars above a threshold)
               high      compare populations: Compute Derived Value -> Characterize Distribution -> Find Extremum
  stacked_bar  compound  Compute Derived Value -> Find Extremum (largest share of the bottom segment)
  line         compound  Compute Derived Value -> Find Extremum (largest one-year increase)
               high      trend over time: Correlate -> Determine Range
  heatmap      compound  Compute Derived Value -> Find Extremum (column with the highest average)
               high      compare across facets: Compute Derived Value -> Sort
  scatter      high      compare populations: Filter -> Correlate -> Compute Derived Value

Brehmer & Munzner (2013) query actions are recorded per high-level template
(compare / summarize) as a second label; they are our mapping, not the PDF's.
"""
import itertools

import numpy as np

from llm_taskgen.core import GateError, Lettering, check_options, fill_tm, truth_letter, validate_task

TIE = 0.04       # comparisons closer than this share of the value span are not used
RANK_GAP = 0.05  # first vs second in a ranking must differ by this share of the span
LEVELS = ("low", "compound", "high")
cg = None  # llm_taskgen.csvgen, imported in extend() (csvgen imports this module)
BM = {"compare populations": "query: compare", "trend over time": "query: summarize",
      "compare across facets": "query: compare"}


# ------------------------------------------------------------------ claims
def _series(rows, fixed, along, val):
    return {r[along]: r[val] for r in rows if all(r[k] == v for k, v in fixed.items()) and r[val] is not None}


def evaluate(atom, spec):
    """(holds, clear) for one claim atom, decided from spec['data'] only."""
    rows, t = spec["data"], atom["type"]
    span = atom["span"]
    if t in ("order", "above"):
        a = _series(rows, atom["a"], atom["along"], atom["value"])
        if t == "order":
            b = _series(rows, atom["b"], atom["along"], atom["value"])
            diffs = [a[k] - b[k] for k in a if k in b]
        else:
            diffs = [v - atom["threshold"] for v in a.values()]
        k, n = sum(d > 0 for d in diffs), len(diffs)
        clear = all(abs(d) >= TIE * span for d in diffs)
        if atom["quant"] == "every":
            # "every" is clearly false as soon as one comparison clearly fails
            return k == n, clear or any(d <= -TIE * span for d in diffs)
        if atom["quant"] == "most_not_all":
            return n / 2 < k < n, clear
        if atom["quant"] == "most":
            return k > n / 2, clear
        raise ValueError(atom["quant"])
    if t == "gap_max":
        a = _series(rows, atom["a"], atom["along"], atom["value"])
        b = _series(rows, atom["b"], atom["along"], atom["value"])
        gap = sorted(((abs(a[k] - b[k]), k) for k in a if k in b), key=lambda g: -g[0])
        return gap[0][1] == atom["at"], gap[0][0] - gap[1][0] >= RANK_GAP * span
    if t == "trend":
        a = _series(rows, atom["a"], atom["along"], atom["value"])
        ys = sorted(a)
        v = [a[y] for y in ys]
        d = v[-1] - v[0]
        fit = np.polyfit(range(len(v)), v, 1)[0] * (len(v) - 1)
        up = d > 0 and fit > 0
        down = d < 0 and fit < 0
        clear = (up or down) and min(abs(d), abs(fit)) >= 0.15 * span
        return (up if atom["dir"] == "rose" else down), clear
    if t == "at_end":
        a = _series(rows, atom["a"], atom["along"], atom["value"])
        b = _series(rows, atom["b"], atom["along"], atom["value"])
        y = max(a)
        d = a[y] - b[y]
        return d > 0, abs(d) >= TIE * span
    if t == "every_step":
        a = _series(rows, atom["a"], atom["along"], atom["value"])
        v = [a[y] for y in sorted(a)]
        steps = [(q - p) * (1 if atom["dir"] == "rose" else -1) for p, q in zip(v, v[1:])]
        return all(s > 0 for s in steps), all(s > 0 for s in steps) or any(s <= -TIE * span for s in steps)
    if t == "spread":
        sx, sy = _spreads(spec, atom)
        hi, lo = (sx, sy) if atom["more"] == "x" else (sy, sx)
        return hi > lo, max(hi, lo) >= 1.5 * min(hi, lo)
    if t == "best_in_every_row":
        enc = spec["encodings"]
        fx, fy, fv = enc["x"], enc["y"], enc["color"]
        rowsets = [_series(rows, {fy: r}, fx, fv) for r in spec["category_order"][fy]]
        holds = all(atom["x"] in row and max(row, key=row.get) == atom["x"] for row in rowsets)
        if holds:
            clear = all(sorted(row.values())[-1] - sorted(row.values())[-2] >= TIE * span for row in rowsets)
        else:  # clearly false only where x is drawn and clearly beaten (a blank cell is not evidence)
            clear = any(atom["x"] in row and max(row.values()) - row[atom["x"]] >= TIE * span for row in rowsets)
        return holds, clear
    if t == "cell_max":
        enc = spec["encodings"]
        g = {(r[enc["y"]], r[enc["x"]]): r[enc["color"]] for r in rows if r[enc["color"]] is not None}
        cells = sorted(g, key=lambda k: -g[k])
        holds = list(cells[0]) == list(atom["at"])
        return holds, g[cells[0]] - g[cells[1]] >= RANK_GAP * span
    if t == "corr":
        r = _corr(spec, atom["group"])
        if atom["dir"] == "none":
            return abs(r) < 0.1, abs(r) < 0.1 or abs(r) >= 0.3
        holds = r > 0 if atom["dir"] == "rose" else r < 0
        return holds, abs(r) >= 0.3
    if t == "corr_stronger":
        d = abs(_corr(spec, atom["hi"])) - abs(_corr(spec, atom["lo"]))
        return d > 0, abs(d) >= 0.2
    if t == "mean_higher":
        enc = spec["encodings"]
        m = {g: np.mean([r[enc["y"]] for r in rows if r[enc["color"]] == g]) for g in (atom["hi"], atom["lo"])}
        d = m[atom["hi"]] - m[atom["lo"]]
        return d > 0, abs(d) >= 0.1 * span
    raise ValueError(t)


def _spreads(spec, atom):
    """Mean range across x within each y row, and across y within each x column (blank cells skipped)."""
    enc = spec["encodings"]
    fx, fy, fv = enc["x"], enc["y"], enc["color"]
    xs, ys = spec["category_order"][fx], spec["category_order"][fy]
    grid = {(r[fy], r[fx]): r[fv] for r in spec["data"] if r[fv] is not None}

    def rng(cells):
        v = [grid[c] for c in cells if c in grid]
        return max(v) - min(v) if len(v) >= 2 else None
    sx = [rng([(y, x) for x in xs]) for y in ys]
    sy = [rng([(y, x) for y in ys]) for x in xs]
    return float(np.mean([v for v in sx if v is not None])), float(np.mean([v for v in sy if v is not None]))


def _corr(spec, group):
    enc = spec["encodings"]
    pts = [r for r in spec["data"] if group is None or r[enc["color"]] == group]
    return float(np.corrcoef([p[enc["x"]] for p in pts], [p[enc["y"]] for p in pts])[0, 1])


def option_holds(option, spec):
    """(holds, clear) for an option's conjunction of atoms."""
    res = [evaluate(a, spec) for a in option["claim"]]
    if all(h for h, _ in res):
        return True, all(c for _, c in res)
    return False, any((not h) and c for h, c in res)


def check_statements(spec, task):
    """Gate for high-level tasks: the truth option holds clearly, every other option fails clearly."""
    for o in task["options"]:
        holds, clear = option_holds(o, spec)
        want = o["misreading"] is None
        if holds != want or not clear:
            raise GateError(f"{task['task_id']}: option {o['text']!r} {'holds' if holds else 'fails'}"
                            f"{'' if clear else ' (not clearly)'}; expected {'true' if want else 'false'}")


# ------------------------------------------------------------------ helpers
def _cap(s):
    return s[:1].upper() + s[1:]


def _stmt(text, tag, claim):
    return {"text": text, "value": text, "misreading": tag, "claim": claim}


def _framing(opts, tag, spec, what):
    """Slanted title asserting the bait (Kong, Liu & Karahalios 2018); subtitle kept, so filters stay stated."""
    bait = next(o for o in opts if o["misreading"] == tag)
    title = bait["text"] if "claim" in bait else what.format(bait=bait["text"])
    truth = next(o for o in opts if o["misreading"] is None)
    if truth["text"] in title:
        raise GateError("framing title contains the truth")
    return cg.mt_attack("biased_framing", opts, tag, f"visible title '{title}', original subtitle kept",
                        family="reasoning", params={"title": title, "subtitle": spec["subtitle"]})


def _recompute_statement(builder):
    """Statement tasks: rebuild the options from the plotted rows and return the truth text."""
    def f(rows):
        opts = builder(rows)
        return next(o["text"] for o in opts if o["misreading"] is None) if opts else None
    return f


# ------------------------------------------------------------------ grouped bar
def grouped_bar(prof, df, spec, ctx, L, tm):
    enc, out = spec["encodings"], []
    xc, gc, yf = enc["x"], enc["group"], enc["y"]
    xl, gl = spec["category_order"][xc], spec["category_order"][gc]
    rows = spec["data"]
    span = spec["y_domain"][1] - spec["y_domain"][0]
    val = {(r[xc], r[gc]): r[yf] for r in rows}
    fmt = cg.make_fmt(ctx["kind"], list(val.values()))
    X, G, phrase = cg.lab(prof, xc), cg.lab(prof, gc), ctx["phrase"]

    # compound: Filter -> Compute Derived Value
    for b in gl:
        b2 = next(g for g in gl if g != b)
        vs = sorted(val[(a, b)] for a in xl)
        thr = None
        for i in range(1, len(vs) - 1):  # 2..n-1 bars above
            lo, hi = vs[i - 1], vs[i]
            if hi - lo >= 2 * RANK_GAP * span:
                t = cg.round_sig((lo + hi) / 2, 2)
                if lo + RANK_GAP * span <= t <= hi - RANK_GAP * span:
                    thr = t
        if thr is None:
            continue
        above = [a for a in xl if val[(a, b)] > thr]
        below = [a for a in xl if val[(a, b)] <= thr]
        m = lambda keys, g: cg.round_sig(float(np.mean([val[(a, g)] for a in keys])))
        opts = [{"text": fmt(m(above, b)), "value": m(above, b), "misreading": None},
                {"text": fmt(m(xl, b)), "value": m(xl, b), "misreading": "filter_skipped"},
                {"text": fmt(m(below, b)), "value": m(below, b), "misreading": "filter_inverted"},
                {"text": fmt(m(above, b2)), "value": m(above, b2), "misreading": "series_swap"}]
        try:
            check_options(opts, min_gap=0.03 * span)
        except GateError:
            continue
        opts = L.assign(opts)
        tt = fmt(thr)
        out.append(cg.task(tm, spec, f"averaged over the {X} values where {G} {b} is above {tt}, {phrase} for {G} {b} is {{bait}}",
            task_id=cg._tid(prof, "bar_filter_average"), named_values={gc: [b]}, primitive="Compute Derived Value",
            level="compound", primitive_chain=["Filter", "Compute Derived Value"],
            question=(f"Consider only the {X} values where the {G} {b} bar is above {tt}. "
                      f"What is the average, across those {X} values, of {phrase} for {G} {b}?"),
            fields_referenced=[xc, gc, yf], channels_used=["x", "group", "color", "y"],
            options=opts, answer_letter=truth_letter(opts),
            solution={"threshold": thr, "kept": [str(a) for a in above], "values": {str(a): val[(a, b)] for a in xl}},
            recompute=lambda rows, b=b, thr=thr: fmt(cg.round_sig(float(np.mean(
                [r[yf] for r in rows if r[gc] == b and r[yf] > thr])))),
            skipped_attacks=[{"channel": "MT", "reason": "no MT family in the registry targets a threshold filter step"}]))
        break

    # high: compare populations
    def statements(rows):
        v = {(r[xc], r[gc]): r[yf] for r in rows}
        b1, b2 = gl
        diffs = {a: v[(a, b1)] - v[(a, b2)] for a in xl}
        k = sum(d > 0 for d in diffs.values())
        n = len(xl)
        if 2 * k == n:
            return None
        H, Lo = (b1, b2) if 2 * k > n else (b2, b1)
        sH, sL = {gc: H}, {gc: Lo}
        base = {"along": xc, "value": yf, "span": span}
        order = lambda a, b, q: {**base, "type": "order", "a": a, "b": b, "quant": q}
        P = _cap(phrase)
        every = f"{P} is higher for {G} {H} than for {G} {Lo} in every {X} value shown"
        opts = []
        if k in (0, n):
            opts.append(_stmt(every, None, [order(sH, sL, "every")]))
        else:
            opts.append(_stmt(f"{P} is higher for {G} {H} than for {G} {Lo} in most, but not all, {X} values shown",
                              None, [order(sH, sL, "most_not_all")]))
            opts.append(_stmt(every, "overgeneralization", [order(sH, sL, "every")]))
        opts.append(_stmt(f"{P} is higher for {G} {Lo} than for {G} {H} in most {X} values shown",
                          "flipped_direction", [order(sL, sH, "most")]))
        gaps = sorted(xl, key=lambda a: -abs(diffs[a]))
        opts.append(_stmt(f"The difference between {G} {H} and {G} {Lo} is largest for {X} {gaps[1]}",
                          "wrong_ranking", [{**base, "type": "gap_max", "a": sH, "b": sL, "at": gaps[1]}]))
        if len(opts) < 4:  # every-case: overgeneralize to a level the lowest bar of H does not reach
            hv = sorted(v[(a, H)] for a in xl)
            t = cg.round_sig(hv[0] + 1.5 * TIE * span, 2)
            if hv[0] <= t - TIE * span and hv[-1] >= t + TIE * span:
                opts.append(_stmt(f"{P} for {G} {H} is above {fmt(t)} in every {X} value shown", "overgeneralization",
                                  [{**base, "type": "above", "a": sH, "threshold": t, "quant": "every"}]))
        return opts if len(opts) == 4 else None

    opts = statements(rows) if not prof.get("long_format") else None
    if prof.get("long_format"):
        ctx["_dropped"].append(f"{cg._tid(prof, 'bar_compare')}: long-format file, so group differences in "
                               "record counts reflect the file layout, not the data")
    if opts:
        H = next(g for g in gl if f"for {G} {g} than" in opts[0]["text"])
        Lo = next(g for g in gl if g != H)
        pooled = _pooled(prof, df, spec, ctx, gc, H, Lo)
        if pooled is not None and pooled <= 0:  # aggregation reversal (plan 3.2)
            ctx["_dropped"].append(f"{cg._tid(prof, 'bar_compare')}: pooled data reverse the within-{X} direction "
                                   f"({H} minus {Lo} = {cg.round_sig(pooled)} over all plotted rows)")
            opts = None
    elif 2 * sum(val[(a, gl[0])] > val[(a, gl[1])] for a in xl) == len(xl):
        ctx["_dropped"].append(f"{cg._tid(prof, 'bar_compare')}: the two groups split the {X} values evenly")
    if opts:
        out.append(_high(prof, spec, L, tm, opts, "bar_compare", "compare populations",
                         ["Compute Derived Value", "Characterize Distribution", "Find Extremum"],
                         f"Which statement about {phrase} for {G} {gl[0]} and {G} {gl[1]} across the {X} values shown "
                         f"is best supported by the chart?",
                         {gc: list(gl)}, [xc, gc, yf], ["x", "group", "color", "y"], statements,
                         extra_solution={"pooled_difference": pooled}))
    return out


def _pooled(prof, df, spec, ctx, gc, H, Lo):
    """H minus Lo over all plotted strata pooled from the raw CSV (the unstratified level)."""
    enc = spec["encodings"]
    sub = df
    for f, levels in spec["category_order"].items():
        if f in df:
            sub = sub[sub[f].isin(levels)]
    M = ctx.get("measure")
    if M is None:
        return None
    sub = M.usable_rows(sub)
    if M.kind == "count":  # pooled count = sum of the bars, same direction as most strata only if totals agree
        return float((sub[gc] == H).sum() - (sub[gc] == Lo).sum())
    return M.agg(sub[sub[gc] == H]) - M.agg(sub[sub[gc] == Lo])


def _high(prof, spec, L, tm, opts, name, pattern, chain, question, named, fields, channels, builder,
          extra_solution=None):
    opts = L.assign(opts)
    t = cg.task(tm, spec, "{bait}", task_id=cg._tid(prof, name), named_values=named,
                primitive=chain[-1] if chain[-1] != "Find Extremum" else chain[-2],
                level="high", primitive_chain=chain, pattern=pattern, bm_action=BM[pattern],
                answer_format="statement", question=question, fields_referenced=fields, channels_used=channels,
                options=opts, answer_letter=truth_letter(opts),
                solution={"key_point": next(o["text"] for o in opts if o["misreading"] is None),
                          "bait_insights": {o["misreading"]: o["text"] for o in opts if o["misreading"]},
                          **(extra_solution or {})},
                recompute=_recompute_statement(builder),
                mt=[_framing(opts, "flipped_direction", spec, "")])
    return t


# ------------------------------------------------------------------ stacked bar
def stacked_bar(prof, df, spec, ctx, L, tm):
    enc = spec["encodings"]
    xc, sc = enc["x"], enc["stack"]
    xl, seg = spec["category_order"][xc], spec["stack_order"][0]
    rows = spec["data"]
    cnt = {x: next(r["count"] for r in rows if r[xc] == x and r[sc] == seg) for x in xl}
    tot = {x: sum(r["count"] for r in rows if r[xc] == x) for x in xl}
    share = {x: cnt[x] / tot[x] for x in xl if tot[x]}
    ranked = sorted(share, key=lambda x: -share[x])
    if len(ranked) < 4 or share[ranked[0]] - share[ranked[1]] < 0.08:
        return []
    by_count = max(xl, key=lambda x: cnt[x])
    by_total = max(xl, key=lambda x: tot[x])
    picks = [(ranked[0], None), (ranked[1], "runner_up")]
    for x, tag in ((by_count, "count_instead_of_share"), (by_total, "total_instead_of_segment"),
                   (ranked[-1], "min_instead_of_max")):
        if len(picks) < 4 and x not in [p for p, _ in picks]:
            picks.append((x, tag))
    if len(picks) < 4 or "count_instead_of_share" not in [t for _, t in picks]:
        return []  # the count reading must be a distinct wrong answer, else the share step is not needed
    opts = [{"text": str(x), "value": x, "misreading": t} for x, t in picks]
    try:
        check_options(opts)
    except GateError:
        return []
    opts = L.assign(opts)
    X, S, noun = cg.lab(prof, xc), cg.lab(prof, sc), prof["noun"]
    segn = cg.name(prof, sc, seg)
    return [cg.task(tm, spec, f"{segn} made up the largest share of {noun} at {X} {{bait}}",
        task_id=cg._tid(prof, "stacked_share"), named_values={sc: [seg]}, primitive="Find Extremum",
        level="compound", primitive_chain=["Compute Derived Value", "Find Extremum"],
        question=(f"For which {X} is {segn} (the bottom segment) the largest share of that bar's total "
                  f"(its count divided by the bar's total across all {S} segments)?"),
        fields_referenced=[xc, sc, "count"], channels_used=["x", "stack", "color", "y"],
        options=opts, answer_letter=truth_letter(opts),
        solution={"share": {str(x): round(100 * s, 1) for x, s in share.items()}},
        recompute=lambda rows: str(max(xl, key=lambda x: next(r["count"] for r in rows if r[xc] == x and r[sc] == seg)
                                       / sum(r["count"] for r in rows if r[xc] == x))),
        mt=[_framing(opts, "count_instead_of_share", spec, f"{segn} Peaks at {X} {{bait}}")])]


# ------------------------------------------------------------------ line
def line(prof, df, spec, ctx, L, tm):
    enc, out = spec["encodings"], []
    yc, cc, sf, yf = enc["x"], enc["color"], enc["line_style"], enc["y"]
    cl, styles = spec["category_order"][cc], spec["category_order"][sf]
    rows = spec["data"]
    ymax = max(r[yf] for r in rows)
    years = sorted({r[yc] for r in rows})
    phrase = ctx["line_phrase"]

    # compound: Compute Derived Value (year-on-year change) -> Find Extremum
    for c, s in itertools.product(cl, styles):
        ser = _series(rows, {cc: c, sf: s}, yc, yf)
        steps = {(p, q): ser[q] - ser[p] for p, q in zip(years, years[1:])}
        up = sorted(steps, key=lambda k: -steps[k])
        if steps[up[0]] <= 0 or steps[up[0]] - steps[up[1]] < max(RANK_GAP * ymax, 0.25 * steps[up[0]]):
            continue
        peak = max(ser, key=ser.get)
        cand = [(up[0], None), (up[1], "runner_up")]
        down = min(steps, key=steps.get)
        if steps[down] <= -RANK_GAP * ymax:
            cand.append((down, "largest_decrease"))
        level_k = next((k for k in steps if k[1] == peak), None)
        if level_k is not None:
            cand.append((level_k, "level_peak_instead_of_change"))
        cand.append((up[2], "rank_3"))
        seen, picks = set(), []
        for k, t in cand:
            if k not in seen and len(picks) < 4:
                seen.add(k)
                picks.append((k, t))
        if len(picks) < 4:
            continue
        opts = [{"text": f"{p} to {q}", "value": steps[(p, q)], "misreading": t} for (p, q), t in picks]
        try:
            check_options(opts)
        except GateError:
            continue
        opts = L.assign(opts)
        target = f"{phrase(s)} for {cg.lab(prof, cc)} {c}"
        sfilter = {cc: c, sf: s}
        out.append(cg.task(tm, spec, f"{target} rose the most from {{bait}}",
            task_id=cg._tid(prof, "line_biggest_rise"), named_values={cc: [c], sf: [s]}, primitive="Find Extremum",
            level="compound", primitive_chain=["Compute Derived Value", "Find Extremum"],
            question=f"Between which two consecutive years did {target} increase the most?",
            fields_referenced=[cc, sf, yc, yf], channels_used=["color", "line_style", "x", "y"],
            options=opts, answer_letter=truth_letter(opts),
            solution={"changes": {f"{p}-{q}": cg.round_sig(d) for (p, q), d in steps.items()}},
            recompute=lambda rows, sfilter=sfilter: (lambda ser: (lambda k: f"{k[0]} to {k[1]}")(max(
                zip(sorted(ser), sorted(ser)[1:]), key=lambda k: ser[k[1]] - ser[k[0]])))(
                _series(rows, sfilter, yc, yf)),
            mt=[_framing(opts, "runner_up", spec, f"{_cap(target)} Jumps From {{bait}}")]))
        break

    # high: trend over time
    for (c1, c2), s in itertools.product(itertools.permutations(cl, 2), styles):
        base = {"along": yc, "value": yf, "span": ymax}
        A, B = {cc: c1, sf: s}, {cc: c2, sf: s}
        n1, n2 = f"{cg.lab(prof, cc)} {c1}", f"{cg.lab(prof, cc)} {c2}"
        y0, y1 = years[0], years[-1]
        what = phrase(s)

        def statements(rows, A=A, B=B, n1=n1, n2=n2, what=what):
            sp = {"data": rows, "encodings": enc, "category_order": spec["category_order"]}
            a = _series(rows, A, yc, yf)
            b = _series(rows, B, yc, yf)
            d = a[y1] - a[y0]
            word, anti = ("rose", "fell") if d > 0 else ("fell", "rose")
            end_hi = a[y1] > b[y1]
            rel, arel = ("above", "below") if end_hi else ("below", "above")
            tr = lambda w: {**base, "type": "trend", "a": A, "dir": w}
            end = lambda hi: ({**base, "type": "at_end", "a": A, "b": B} if hi else {**base, "type": "at_end", "a": B, "b": A})
            W = _cap(what)
            opts = [_stmt(f"{W} for {n1} {word} from {y0} to {y1} and ended {rel} the same series for {n2}", None, [tr(word), end(end_hi)]),
                    _stmt(f"{W} for {n1} {anti} from {y0} to {y1} and ended {rel} the same series for {n2}", "flipped_direction",
                          [tr(anti), end(end_hi)]),
                    _stmt(f"{W} for {n1} {word} from {y0} to {y1} and ended {arel} the same series for {n2}", "wrong_ranking",
                          [tr(word), end(not end_hi)])]
            hi_, lo_ = (A, B) if end_hi else (B, A)
            every_year = {**base, "type": "order", "a": hi_, "b": lo_, "quant": "every"}
            if not evaluate(every_year, sp)[0]:
                opts.append(_stmt(f"{W} for {n1} was {rel} {n2} in every year from {y0} to {y1}",
                                  "overgeneralization", [every_year]))
            else:
                opts.append(_stmt(f"{W} for {n1} {word} in every single year from {y0} to {y1}",
                                  "overgeneralization", [{**base, "type": "every_step", "a": A, "dir": word}]))
            return opts

        opts = statements(rows)
        try:
            check_statements(spec, {"task_id": "line_trend_high", "options": opts})
        except GateError:
            continue
        out.append(_high(prof, spec, L, tm, opts, "line_trend_high", "trend over time", ["Correlate", "Determine Range"],
                         f"Which statement about {what} for {n1} and {n2} from {y0} to {y1} is best supported by the chart?",
                         {cc: [c1, c2], sf: [s]}, [cc, sf, yc, yf], ["color", "line_style", "x", "y"], statements))
        break
    return out


# ------------------------------------------------------------------ heatmap
def heatmap(prof, df, spec, ctx, L, tm):
    enc, out = spec["encodings"], []
    xk, yc, fv = enc["x"], enc["y"], enc["color"]
    xl, yl = spec["category_order"][xk], spec["category_order"][yc]
    rows = spec["data"]
    grid = {(r[yc], r[xk]): r[fv] for r in rows}
    complete = all(v is not None for v in grid.values())  # column averages need every cell
    dom = spec["color_scale"]["domain"]
    span = dom[1] - dom[0]
    X, Y, phrase = ctx["xlabel"], cg.lab(prof, yc), ctx["phrase"]

    # compound: Compute Derived Value (column average) -> Find Extremum
    colmean = {x: float(np.mean([grid[(y, x)] for y in yl])) for x in xl} if complete else {}
    ranked = sorted(xl, key=lambda x: -colmean[x]) if complete else []
    if complete and colmean[ranked[0]] - colmean[ranked[1]] >= RANK_GAP * span:
        cell_best = max(grid, key=grid.get)[1]
        picks = [(ranked[0], None), (ranked[1], "runner_up")]
        if cell_best not in (ranked[0], ranked[1]):
            picks.append((cell_best, "single_cell_max"))
        for x, t in ((ranked[-1], "min_instead_of_max"), (ranked[2], "rank_3")):
            if len(picks) < 4 and x not in [p for p, _ in picks]:
                picks.append((x, t))
        opts = [{"text": str(x), "value": x, "misreading": t} for x, t in picks]
        try:
            check_options(opts)
            opts = L.assign(opts)
            best_row = max(yl, key=lambda y: grid[(y, ranked[1])])
            out.append(cg.task(tm, spec, f"averaged over all {Y} rows, {phrase} is highest for {X} {{bait}}",
                task_id=cg._tid(prof, "heatmap_column_average"), named_values={}, primitive="Find Extremum",
                level="compound", primitive_chain=["Compute Derived Value", "Find Extremum"],
                question=f"Averaging over all {Y} rows shown, which {X} has the highest average {phrase[4:]}?",
                fields_referenced=[xk, yc, fv], channels_used=["x", "y", "color"],
                options=opts, answer_letter=truth_letter(opts),
                solution={"column_mean": {str(x): cg.round_sig(m) for x, m in colmean.items()}},
                recompute=lambda rows: max(xl, key=lambda x: np.mean([r[fv] for r in rows if r[xk] == x])),
                mt=[cg.mt_attack("color_highlight_decoy", opts, "runner_up",
                                 "thick orange outline on the runner-up column's brightest cell",
                                 params={"highlight": {yc: best_row, xk: ranked[1]}},
                                 needs_approval="adaptation of the highlight decoy to a heatmap cell",
                                 adapted_from="color_highlight_decoy (bar_color_highlight_decoy) to a heatmap cell")]))
        except GateError:
            pass

    # high: compare across facets
    def statements(rows):
        sp = {"data": rows, "encodings": enc, "category_order": spec["category_order"]}
        base = {"span": span}
        sx, sy = _spreads(sp, base)
        more, less = (X, Y) if sx > sy else (Y, X)
        mk, lk = ("x", "y") if sx > sy else ("y", "x")
        P = _cap(phrase)
        opts = [_stmt(f"{P} differs more between {more} values than between {less} values", None,
                      [{**base, "type": "spread", "more": mk}]),
                _stmt(f"{P} differs more between {less} values than between {more} values", "flipped_direction",
                      [{**base, "type": "spread", "more": lk}])]
        g = {(r[yc], r[xk]): r[fv] for r in rows if r[fv] is not None}
        cm = {x: np.mean([g[(y, x)] for y in yl if (y, x) in g]) for x in xl if any((y, x) in g for y in yl)}
        xbest = max(cm, key=lambda x: cm[x])
        a = {**base, "type": "best_in_every_row", "x": xbest}
        if not evaluate(a, sp)[0]:
            opts.append(_stmt(f"{X} {xbest} has the highest {phrase[4:]} in every {Y} row", "overgeneralization", [a]))
        cells = sorted(g, key=lambda k: -g[k])
        y2, x2 = cells[1]
        if g[cells[0]] - g[cells[1]] >= RANK_GAP * span:
            opts.append(_stmt(f"The highest {phrase[4:]} on the chart is for {Y} {y2} and {X} {x2}", "wrong_ranking",
                              [{**base, "type": "cell_max", "at": [y2, x2]}]))
        return opts if len(opts) == 4 else None

    opts = statements(rows)
    if opts:
        out.append(_high(prof, spec, L, tm, opts, "heatmap_facets", "compare across facets",
                         ["Compute Derived Value", "Sort"],
                         f"Which statement about {phrase} across {X} and {Y} is best supported by the chart?",
                         {}, [xk, yc, fv], ["x", "y", "color"], statements))
    return out


# ------------------------------------------------------------------ scatter
def scatter(prof, df, spec, ctx, L, tm):
    enc = spec["encodings"]
    xc, yc, cc = enc["x"], enc["y"], enc["color"]
    cl = spec["category_order"][cc]
    rows = spec["data"]
    if any(sum(r[cc] == c for r in rows) < 15 for c in cl):
        ctx["_dropped"].append(f"{cg._tid(prof, 'scatter_compare')}: fewer than 15 points in a color group")
        return []
    ys = [r[yc] for r in rows]
    span = max(ys) - min(ys)
    Xl, Yl, C = cg.lab(prof, xc), cg.lab(prof, yc), cg.lab(prof, cc)
    c1, c2 = cl

    def statements(rows):
        sp = {"data": rows, "encodings": enc}
        r_all = _corr(sp, None)
        word, anti = ("rise", "fall") if r_all > 0 else ("fall", "rise")
        base = {"span": span}
        corr = lambda g, w: {**base, "type": "corr", "group": g, "dir": {"rise": "rose", "fall": "fell"}.get(w, w)}
        opts = [_stmt(f"{Yl} tends to {word} as {Xl} increases, both for {C} {c1} and for {C} {c2}", None,
                      [corr(c1, word), corr(c2, word)]),
                _stmt(f"{Yl} tends to {anti} as {Xl} increases, both for {C} {c1} and for {C} {c2}", "flipped_direction",
                      [corr(c1, anti), corr(c2, anti)])]
        m = {c: np.mean([r[yc] for r in rows if r[cc] == c]) for c in cl}
        lo, hi = sorted(cl, key=lambda c: m[c])
        weaker = min(cl, key=lambda c: abs(_corr(sp, c)))
        stronger = next(c for c in cl if c != weaker)
        opts.append(_stmt(f"{Yl} tends to {word} as {Xl} increases for {C} {stronger}, but not for {C} {weaker}",
                          "false_exception", [corr(stronger, word), corr(weaker, "none")]))
        if m[hi] - m[lo] >= 0.1 * span:
            opts.append(_stmt(f"Points with {C} {lo} have higher {Yl} on average than points with {C} {hi}",
                              "wrong_ranking", [{**base, "type": "mean_higher", "hi": lo, "lo": hi}]))
        elif abs(_corr(sp, stronger)) - abs(_corr(sp, weaker)) >= 0.2:
            opts.append(_stmt(f"The relation between {Xl} and {Yl} is tighter for {C} {weaker} than for {C} {stronger}",
                              "wrong_ranking", [{**base, "type": "corr_stronger", "hi": weaker, "lo": stronger}]))
        return opts if len(opts) == 4 else None

    opts = statements(rows)
    if not opts:
        ctx["_dropped"].append(f"{cg._tid(prof, 'scatter_compare')}: no clearly false fourth statement "
                               "(group means and correlation strengths too close)")
        return []
    return [_high(prof, spec, L, tm, opts, "scatter_compare", "compare populations",
                  ["Filter", "Correlate", "Compute Derived Value"],
                  f"Which statement about how {Yl} relates to {Xl} for {C} {c1} and {C} {c2} is best supported by the chart?",
                  {cc: [c1, c2]}, [xc, yc, cc], ["x", "y", "color"], statements)]


BUILDERS = {"grouped_bar": grouped_bar, "stacked_bar": stacked_bar, "line": line,
            "heatmap": heatmap, "scatter": scatter}


def extend(prof, df, spec, ctx, L, tm, levels):
    """Compound and high-level tasks for a chosen chart. Each task is gated on its own and
    dropped (with the reason) if it fails, so the chart and its low-level tasks stay as they are."""
    global cg
    from llm_taskgen import csvgen as cg
    if not set(levels) & {"compound", "high"}:
        return [], []
    kept, dropped = [], []
    state = (L.rng.getstate(), list(L.queue), tm.i)
    ctx = {**ctx, "_dropped": []}
    try:
        cand = BUILDERS[spec["chart_type"]](prof, df, spec, ctx, L, tm)
    except GateError as e:
        L.rng.setstate(state[0])
        L.queue[:] = state[1]
        tm.i = state[2]
        return [], [f"{spec['chart_type']}: {e}"]
    dropped += ctx["_dropped"]
    for t in cand:
        if t["level"] not in levels:
            continue
        try:
            if t.get("answer_format") == "statement":
                check_statements(spec, t)
            fill_tm(t)
            validate_task(spec, t)
            kept.append(t)
        except GateError as e:
            dropped.append(f"{t['task_id']}: {e}")
    return kept, dropped

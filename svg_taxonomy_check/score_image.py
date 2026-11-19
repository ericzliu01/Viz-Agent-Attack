"""Score image-mode replies (text answers, see imgprompts.py).

retrieval, derive, range and distribution use score.score unchanged, so their
rules and tolerances match the SVG-text run. The other tasks get text-answer
rules that ask the same question as the SVG-output rules in score.py:

  filter, extreme, anomaly  the listed rows, matched to data points, form the same
                            set the SVG rule requires (anomaly: same count rule)
  sort                      n rows, non-increasing, each within 5% of the y-range
                            of the true value at that rank
  cluster                   the listed non-outlier points are partitioned like the
                            generating clusters, with at most 10% of them unlisted
                            (strict: every point listed)
  correlate                 fitted line within 5 degrees of the OLS slope and
                            within 5% of the y-span at mean x, both measured
                            with axes scaled to the data range (strict: 2 deg, 2%)

Matching a listed row to a data point: line and bar charts use X alone (X is
0..n-1 on the axis); scatter uses the nearest point in X and Y scaled by each
axis's data range, accepted within 0.05. A row that matches nothing makes the
answer wrong. Replies that show working before the answer are cut to the final
answer block (answer_text), so numbers in the working are not read as rows.
"""
import math
import re

import items as I
import score as S

MATCH = 0.05


HEADER = re.compile(r"^\s*\**\s*'?(X|Y)'?\s*(,\s*'?(Y|Cluster)'?\s*)*\**\s*$", re.I)


def answer_text(reply):
    """The final answer block of a reply that may show its working first.

    The last fenced code block if there is one; otherwise the lines after the
    last CSV header line ("X,Y", "Y", "X,Y,Cluster"); otherwise the whole reply.
    A one-line "Y" answer written as "8,8.5,7.4,..." is split into one value per line.
    """
    reply = reply or ""
    blocks = re.findall(r"```[a-zA-Z]*\n(.*?)```", reply, re.S)
    text = blocks[-1] if blocks else reply
    lines = text.strip().split("\n")
    heads = [i for i, l in enumerate(lines) if HEADER.match(l)]
    if heads:
        h = heads[-1]
        body = lines[h + 1:]
        if lines[h].strip().strip("*'").upper() == "Y" and len(body) == 1 and len(S.nums(body[0])) > 2:
            body = [str(v) for v in S.nums(body[0])]
        lines = [lines[h]] + body
    return "\n".join(lines)


def rows_from(reply, k):
    """Rows of at least k numbers from the final answer block."""
    text = answer_text(reply)
    out = []
    for line in text.strip().split("\n"):
        v = S.nums(line)
        if len(v) >= k:
            out.append(v[-k:] if k > 1 else v[-1:])
    return out


def match_rows(chart, rows, data):
    """Data index for each listed (x, y) row, or None."""
    X = [r["X"] for r in data]
    Y = [r["Y"] for r in data]
    if chart in ("line", "bar"):
        res = []
        for x, _y in rows:
            j = min(range(len(X)), key=lambda i: abs(X[i] - x))
            res.append(j if abs(X[j] - x) <= 0.25 else None)
        return res
    rx, ry = S.rng(X), S.rng(Y)
    pairs = sorted((math.hypot((x - X[j]) / rx, (y - Y[j]) / ry), i, j)
                   for i, (x, y) in enumerate(rows) for j in range(len(X)))
    used_i, used_j, res = set(), set(), [None] * len(rows)
    for d, i, j in pairs:
        if d > MATCH:
            break
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        res[i] = j
    return res


def score(repo, chart, cond, task, idx, reply):
    if task == "retrieval":
        return S.score(repo, chart, cond, task, idx, answer_text(reply))
    if task in ("derive", "range", "distribution"):
        return S.score(repo, chart, cond, task, idx, reply)
    data = I.read_rows(I.dataset_path(repo, chart, cond, task, idx))
    X = [r["X"] for r in data]
    Y = [r["Y"] for r in data]
    res = dict(correct=False, strict=False, parsed=True, detail="")
    if reply is None or not reply.strip():
        res.update(parsed=False, detail="empty reply")
        return res

    if task in ("filter", "extreme", "anomaly"):
        rows = rows_from(reply, 2)
        if not rows:
            res.update(parsed=False, detail="no X,Y rows")
            return res
        m = match_rows(chart, rows, data)
        got = {j for j in m if j is not None}
        clean = all(j is not None for j in m) and len(got) == len(rows)
        if task == "extreme":
            truth = {Y.index(max(Y)), Y.index(min(Y))}
            ok = clean and got == truth
            res.update(correct=ok, strict=ok)
        elif task == "filter":
            if chart == "scatter":
                truth = {i for i, y in enumerate(Y) if y > 0}
            else:
                lo, hi = (2, 6) if chart == "line" else (3, 7)
                truth = {i for i, x in enumerate(X) if lo <= x <= hi}
            ok = clean and got == truth
            res.update(correct=ok, strict=ok)
            if chart == "bar":
                res["alt_one_based"] = clean and got == {t - 1 for t in truth}
        else:
            truth = S.truth_outliers(chart, data)
            k = S.PROMPT_K[chart]
            if not clean:
                ok = False
            elif k is None or k == len(truth):
                ok = got == truth
            elif k < len(truth):
                ok = bool(got) and got <= truth and len(got) >= k
            else:
                ok = truth <= got and len(got) <= k
            res.update(correct=ok, strict=clean and got == truth)
        res["detail"] = f"got {sorted(got)} ({len(rows)} rows, unmatched {sum(j is None for j in m)}) truth {sorted(truth)}"
        return res

    if task == "sort":
        rows = rows_from(reply, 1)
        if not rows:
            res.update(parsed=False, detail="no rows")
            return res
        v = [r[0] for r in rows]
        t = sorted(Y, reverse=True)
        desc = all(a >= b for a, b in zip(v, v[1:]))
        n_ok = len(v) == len(t)
        close = n_ok and all(abs(a - b) <= 0.05 * S.rng(Y) for a, b in zip(v, t))
        close2 = n_ok and all(abs(a - b) <= 0.02 * S.rng(Y) for a, b in zip(v, t))
        res.update(correct=desc and close, strict=desc and close2,
                   detail=f"{len(v)} rows (n={len(t)}), descending={desc}, within 5%={close}")
        return res

    if task == "cluster":
        rows = rows_from(reply, 3)
        if not rows:
            res.update(parsed=False, detail="no X,Y,Cluster rows")
            return res
        m = match_rows(chart, [(r[0], r[1]) for r in rows], data)
        col = {}
        for r, j in zip(rows, m):
            if j is not None:
                col.setdefault(j, r[2])
        members = [i for i, r in enumerate(data) if r["Label"] != "outlier"]
        missing = [i for i in members if i not in col]
        if len(missing) > 0.2 * len(members):
            res.update(parsed=False, detail=f"{len(missing)} cluster points unmatched ({len(rows)} rows)")
            return res
        def partition_ok(listed_only):
            lab = {}
            for i in members:
                if listed_only and i not in col:
                    continue
                lab.setdefault(data[i]["Label"], set()).add(col.get(i))
            one_each = all(len(c) == 1 and None not in c for c in lab.values())
            return one_each and len({next(iter(c)) for c in lab.values()}) == len(lab), lab

        ok_all, lab = partition_ok(False)
        ok_listed, _ = partition_ok(True)
        # primary: listed points partitioned correctly and at most 10% of points unlisted
        ok = ok_listed and len(missing) <= 0.1 * len(members)
        res.update(correct=ok, strict=ok_all,
                   detail=f"clusters->ids {[sorted(map(str, c)) for c in lab.values()]}, missing {len(missing)}")
        return res

    if task == "correlate":
        v = S.nums(reply)
        if len(v) < 2:
            res.update(parsed=False, detail="fewer than 2 numbers")
            return res
        slope, icpt = v[-2], v[-1]
        mx, my = sum(X) / len(X), sum(Y) / len(Y)
        b = sum((x - mx) * (y - my) for x, y in zip(X, Y)) / sum((x - mx) ** 2 for x in X)
        rx, ry = S.rng(X), S.rng(Y)
        ang = abs(math.degrees(math.atan(slope * rx / ry)) - math.degrees(math.atan(b * rx / ry)))
        off = abs(icpt + slope * mx - my) / ry
        res.update(correct=ang <= 5 and off <= 0.05, strict=ang <= 2 and off <= 0.02,
                   detail=f"slope {slope} vs {b:.3f}, angle diff {ang:.1f} deg, offset {off:.1%} of y-span")
        return res

    raise ValueError(task)

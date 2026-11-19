"""Schema inference for arbitrary CSVs (used by llm_taskgen.csvgen).

Each column gets one role:
  measure   numeric with many distinct values (mean is meaningful)
  category  2-100 distinct values (strings, booleans or integer codes with <= 12 values); also
            panel columns with <= 300 levels that each repeat >= 5 times, and long-tail columns
            whose 8 most common levels cover >= 60% of rows (only the top levels are charted)
  binary    a category with exactly two values (also usable as a rate: % of rows at one level)
  year      integer years, or a date column (a derived <col>_year column is added)
  skip      ids, codes, coordinates, free text, multi-valued lists, mostly-missing columns

A sidecar file <csv>.taskgen.json can override what inference gets wrong:
  {"name": "Steam games", "noun": "games",
   "labels": {"positive_ratings": "Positive ratings"},
   "roles": {"required_age": "category", "owners": "skip"},
   "positive": {"english": 1},
   "levels": {"country": ["United States", "Germany", "China"]},   # only these levels are used
   "where": {"question": "Asthma mortality rate"}}                 # keep only these rows (long-format data)
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

MAX_MISSING = 0.95
MAX_CATEGORY_LEVELS = 100
ID_NAME = re.compile(r"(^|[_\s.-])(id|uuid|index|idx|zip|zipcode|zipcodes|postal|fips|code|codes|lat|latitude|"
                     r"lon|lng|longitude|url|link|links|doi|isbn|phone|email|name|names|title|"
                     r"description|abstract|summary)s?($|[_\s.-])", re.I)
# columns that are bookkeeping, not data: footnote symbols, flags, page numbers
NOTE_NAME = re.compile(r"footnote|symbol|flag|comment|remark|page", re.I)
LONG_FORMAT_NAME = re.compile(r"unit|indicator|question|measure|metric|variable|series|datavaluetype", re.I)
YEAR_NAME = re.compile(r"year|yr\b|season", re.I)
TRUE_WORDS = {"true", "yes", "y", "1", "t", "present", "positive"}
FALSE_WORDS = {"false", "no", "n", "0", "f", "absent", "negative"}


def slug(name):
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(name)).strip("_").lower()
    return s or "col"


def humanize(name):
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(name))
    s = re.sub(r"[_\s.-]+", " ", s).strip()
    return s[:1].upper() + s[1:] if s else str(name)


def read_table(path):
    path = Path(path)
    sep = "\t" if path.suffix.lower() in (".tsv", ".tab") else None
    df = pd.read_csv(path, sep=sep, engine="python" if sep is None else "c",
                     encoding="utf-8-sig", encoding_errors="replace", on_bad_lines="skip")
    cols, seen = [], {}
    for c in (str(c).strip() for c in df.columns):  # headers equal after trimming get .1, .2
        seen[c] = seen.get(c, -1) + 1
        cols.append(c if seen[c] == 0 else f"{c}.{seen[c]}")
    df.columns = cols
    return df


THOUSANDS = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")
DECIMAL_COMMA = re.compile(r"^-?\d+,\d+$")
DATE_SHAPE = re.compile(r"\d{1,4}[-/.]\d{1,2}(?:[-/.]\d{1,4})?|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec", re.I)


def coerce_numeric(s):
    """Numbers, also when written with thousands separators, a decimal comma, or a
    leading $ / trailing % or + (e.g. "1,234", "15,34", "$7.99", "45%", "10,000+")."""
    if s.dtype == bool:
        return s.astype(float)
    num = pd.to_numeric(s, errors="coerce")
    v = s.dropna().astype(str).str.strip()
    if v.empty or num.notna().sum() >= 0.95 * len(v):
        return num
    t = v.str.replace(r"^\$|[%+]$", "", regex=True).str.strip()
    if t.str.match(THOUSANDS).mean() + t.str.fullmatch(r"-?\d+(\.\d+)?").mean() >= 0.95:
        t = t.str.replace(",", "", regex=False)
    elif t.str.match(DECIMAL_COMMA).mean() >= 0.5:
        t = t.str.replace(",", ".", regex=False)
    out = pd.Series(np.nan, index=s.index)
    out[v.index] = pd.to_numeric(t, errors="coerce")
    return out


def _is_multivalued(s):
    v = s.dropna().astype(str)
    if v.empty:
        return False
    return v.str.contains(r"[;|]|, ", regex=True).mean() > 0.2


def _bool_level(v):
    t = str(v).strip().lower()
    if t in TRUE_WORDS:
        return True
    if t in FALSE_WORDS:
        return False
    return None


def _year_like(num):
    v = num.dropna()
    return (len(v) > 0 and (v == v.round()).all() and v.between(1700, 2100).all()
            and v.nunique() >= 5)


def _id_like(num):
    """Integers that are (almost) all distinct and run in row order, like a row id."""
    v = num.dropna()
    if len(v) < 10 or not (v == v.round()).all() or v.nunique() / len(v) <= 0.95:
        return False
    return abs(pd.Series(v.values).rank().corr(pd.Series(range(len(v)), dtype=float))) > 0.95


def _dates(s):
    """Parsed dates if >= 90% of the non-blank values are dates spanning >= 5 years, else None."""
    v = s.dropna().astype(str)
    if v.empty or v.str.fullmatch(r"-?\d+(?:[.,]\d+)?").mean() > 0.5 or v.str.contains(DATE_SHAPE).mean() < 0.9:
        return None
    sample = v.sample(min(len(v), 500), random_state=0)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if pd.to_datetime(sample, errors="coerce", format="mixed").notna().mean() < 0.9:
            return None
        d = pd.to_datetime(s, errors="coerce", format="mixed")
    if d.notna().sum() / max(s.notna().sum(), 1) < 0.9 or d.dt.year.nunique() < 5:
        return None
    return d


def profile(path, sidecar=None):
    """Return a profile dict and a cleaned DataFrame whose columns are slugs."""
    path = Path(path)
    raw = read_table(path)
    if sidecar is None:
        sc = path.with_name(path.name + ".taskgen.json")
        sidecar = json.loads(sc.read_text()) if sc.exists() else {}
    roles_override = {slug(k): v for k, v in sidecar.get("roles", {}).items()}
    labels_override = {slug(k): v for k, v in sidecar.get("labels", {}).items()}
    positive_override = {slug(k): v for k, v in sidecar.get("positive", {}).items()}
    levels_override = {slug(k): v for k, v in sidecar.get("levels", {}).items()}

    for col, allowed in sidecar.get("where", {}).items():
        allowed = allowed if isinstance(allowed, list) else [allowed]
        raw = raw[raw[col].astype(str).isin([str(a) for a in allowed])].reset_index(drop=True)
    n = len(raw)
    df = pd.DataFrame(index=raw.index)
    cols = {}
    used = set()
    for orig in raw.columns:
        key = slug(orig)
        while key in used:
            key += "_"
        used.add(key)
        s = raw[orig]
        if s.dtype == object:
            s = s.astype("string").str.strip().replace("", pd.NA).astype(object)
        info = {"column": orig, "label": labels_override.get(key, humanize(orig))}
        role = roles_override.get(key)
        missing = s.isna().mean() if n else 1.0
        num = coerce_numeric(s)
        nonnull = s.notna().sum()
        numeric_share = num.notna().sum() / nonnull if nonnull else 0
        nuniq = s.nunique(dropna=True)
        reason = None
        if role is None:
            if missing > MAX_MISSING:
                role, reason = "skip", f"{missing:.0%} missing"
            elif NOTE_NAME.search(orig):
                role, reason = "skip", "footnote/flag/page column"
            elif nuniq < 2:
                role, reason = "skip", "constant"
            elif nuniq == 2:
                role = "binary"
            elif numeric_share >= 0.95:
                if _year_like(num) and (YEAR_NAME.search(orig) or nuniq <= 200):
                    role = "year"
                elif ID_NAME.search(orig):
                    role, reason = "skip", "id/code/coordinate name"
                elif _id_like(num):
                    role, reason = "skip", "unique integers in row order (id-like)"
                elif nuniq <= 12 and (num.dropna() == num.dropna().round()).all():
                    role = "category"
                elif nuniq >= 10:
                    role = "measure"
                else:
                    role, reason = "skip", "too few distinct numeric values"
            else:
                dates = _dates(s) if nuniq > 12 else None
                if dates is not None:
                    role = "date"
                elif ID_NAME.search(orig) and nuniq > MAX_CATEGORY_LEVELS:
                    role, reason = "skip", "name/id text"
                elif _is_multivalued(s):
                    role, reason = "skip", "multi-valued list"
                elif nuniq <= MAX_CATEGORY_LEVELS:
                    role = "category"
                elif nuniq <= 300 and nonnull / nuniq >= 5:
                    role = "category"  # panel data: each level repeats (e.g. country by year)
                elif s.value_counts().iloc[:8].sum() / max(nonnull, 1) >= 0.6:
                    role = "category"  # a long tail, but the top levels cover most rows
                else:
                    role, reason = "skip", f"free text ({nuniq} distinct values)"
        info["role"] = role
        if reason:
            info["reason"] = reason
        if role == "measure":
            df[key] = num.astype(float)
        elif role == "year":
            df[key] = num.round().astype("Int64")
        elif role == "date":
            dates = _dates(s)
            ykey = key + "_year"
            df[ykey] = dates.dt.year.astype("Int64")
            used.add(ykey)
            cols[ykey] = {"column": orig, "label": labels_override.get(ykey, humanize(orig) + " (year)"),
                          "role": "year", "derived_from": orig}
            info["role"], info["reason"] = "skip", f"date; year derived as {ykey}"
        elif role in ("category", "binary"):
            vals = s
            if numeric_share >= 0.95 and s.dtype != bool:
                vals = num.map(lambda v: None if pd.isna(v) else (str(int(v)) if float(v).is_integer() else str(v)))
            else:
                vals = s.map(lambda v: None if pd.isna(v) else str(v))
            df[key] = vals
            levels = df[key].value_counts()
            info["levels"] = {str(k): int(v) for k, v in levels.items()}
            if key in levels_override:
                info["keep"] = [str(x) for x in levels_override[key]]
            if role == "binary":
                info["positive"] = _positive(levels, positive_override.get(key))
        cols[key] = info
    warnings = []
    for k, c in cols.items():
        if c["role"] in ("category", "binary") and LONG_FORMAT_NAME.search(c["column"]) and "where" not in sidecar:
            warnings.append(f"column {c['column']!r} looks like a measure-name column (long-format data); means may "
                            "mix different quantities. Add a 'where' filter in a sidecar if so.")
    long_format = bool(warnings)
    if long_format:
        warnings.append("means of measure columns are not used for this file (counts and rates still are)")
    name = sidecar.get("name", humanize(path.stem))
    return {"path": str(path), "name": name, "slug": slug(sidecar.get("slug", path.stem)),
            "noun": sidecar.get("noun", "records"), "rows": n, "columns": cols, "warnings": warnings,
            "long_format": long_format}, df


def _positive(levels, override):
    keys = list(levels.index)
    if override is not None:
        ov = str(int(override)) if isinstance(override, (int, float)) and float(override).is_integer() else str(override)
        if ov not in keys:
            raise ValueError(f"positive level {override!r} not in {keys}")
        return ov
    flags = {k: _bool_level(k) for k in keys}
    if set(flags.values()) == {True, False}:
        return next(k for k, f in flags.items() if f)
    return str(levels.index[-1])  # the less frequent level


def roles(prof, role):
    return [k for k, c in prof["columns"].items() if c["role"] == role]


def summary(prof):
    """Short per-column report for the console and the output JSON."""
    out = {}
    for k, c in prof["columns"].items():
        d = {"role": c["role"], "label": c["label"]}
        if "levels" in c:
            d["levels"] = len(c["levels"])
        if "reason" in c:
            d["reason"] = c["reason"]
        out[k] = d
    return out


def to_py(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if v is pd.NA:
        return None
    return v

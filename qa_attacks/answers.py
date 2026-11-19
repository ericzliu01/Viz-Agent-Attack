"""Answer-format parsing and attack-target selection.

An attack pushes one specific wrong answer (the *target*), so attack success
can be measured two ways: the prediction is wrong, or it equals the target.
The target must be expressed in the format the question demands, and must
fall outside the benchmark grader's tolerance (ChartGalaxy/ChartQAPro accept
numbers within 5% relative error).

Selection is deterministic: a choice target is picked among the wrong letters
by a stable hash of the item id (not first-match, which would bias toward A).
"""
from dataclasses import dataclass
import hashlib
import re

# Kinds of answer a question asks for.
NUMERIC, CHOICE, YESNO, TEXT = "numeric", "choice", "yesno", "text"

_CHOICE_RE = re.compile(r"(?:^|\s)([A-H])\.\s+(.+?)(?=\s+[A-H]\.\s+|\s*Answer with|\s*$)", re.S)
_OPTIONS_MARKER = "following options:"
_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?%?$")

# Numeric targets move the answer this far (relative), well past a 5% tolerance.
NUMERIC_SHIFT = 0.5
# Answers to "which year" questions shift by whole years instead (a 5% band on
# 2010 is ~100y, so year answers are graded by exact match).
YEAR_SHIFT = 3
_YEAR_Q = re.compile(r"\b(?:which|what)\s+year\b", re.I)


@dataclass(frozen=True)
class AnswerFormat:
    kind: str
    options: dict  # letter -> option text; empty unless kind == CHOICE


def parse_format(question, answer):
    """Infer the answer kind from the question's instruction and the gold answer."""
    if _OPTIONS_MARKER in question:
        tail = question.split(_OPTIONS_MARKER, 1)[1]
        options = {m.group(1): m.group(2).strip() for m in _CHOICE_RE.finditer(tail)}
        if answer.strip() in options:
            return AnswerFormat(CHOICE, options)
    if answer.strip() in ("Yes", "No"):
        return AnswerFormat(YESNO, {})
    if _NUMBER_RE.match(answer.strip()):
        return AnswerFormat(NUMERIC, {})
    return AnswerFormat(TEXT, {})


def _stable_index(key, n):
    return int(hashlib.sha256(key.encode()).hexdigest(), 16) % n


def _decimals(text):
    return len(text.split(".", 1)[1]) if "." in text else 0


def asks_year(question):
    """Whether the question asks for a year (its answer needs an exact match)."""
    return bool(_YEAR_Q.search(question))


def numeric_target(answer, year=False):
    """A wrong number in the same style as ``answer`` (decimals, ``%`` suffix).

    ``year`` answers move by whole years; anything else, including large values
    that merely look like years (a difference of 1850), moves by 50%."""
    text = answer.strip()
    pct = text.endswith("%")
    text = text.rstrip("%")
    value = float(text)
    places = _decimals(text)
    if year:
        target = value + YEAR_SHIFT
    elif value == 0:
        target = 5.0
    else:
        target = value * (1 + NUMERIC_SHIFT)
        step = 10 ** -places
        # Rounding can collapse a small number back onto the answer (e.g. 1 -> 1.5 -> 2 is
        # fine, but 0.1 at 0 dp would not be); keep at least one display step away.
        if round(target, places) == round(value, places):
            target = value + step
    out = f"{target:.{places}f}"
    return out + ("%" if pct else "")


def choose_target(item_id, question, answer):
    """Return ``(target, display)`` for the attack, or ``None`` if untargetable.

    ``target`` is what a fully-misled model would answer, in the benchmark's
    answer format (a letter, Yes/No, or a number); ``display`` is the human
    phrasing used inside payload text (e.g. ``"B (North America)"``).
    Free-text answers have no well-defined wrong target and return ``None``.
    """
    fmt = parse_format(question, answer)
    answer = answer.strip()
    if fmt.kind == CHOICE:
        wrong = sorted(k for k in fmt.options if k != answer)
        letter = wrong[_stable_index(item_id, len(wrong))]
        return letter, f"{letter} ({fmt.options[letter]})"
    if fmt.kind == YESNO:
        flipped = "No" if answer == "Yes" else "Yes"
        return flipped, flipped
    if fmt.kind == NUMERIC:
        value = numeric_target(answer, year=asks_year(question))
        return value, value
    return None

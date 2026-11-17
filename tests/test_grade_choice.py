"""Conservative A-D choice parser: accept only standalone / declared answers, never a
stray letter in prose; ambiguity -> needs_review."""
import pytest

from run_attack_suite import grade, parse_choice


@pytest.mark.parametrize("text,expected", [
    ("A", "A"), ("**A**", "A"), ("(A)", "A"), ("`A`", "A"), ("A.", "A"), (" b ", "B"),
    ("Final answer: A", "A"), ("The answer is B.", "B"), ("Answer: C", "C"),
    ("Option D", "D"),
    ("Looking at the chart, the bars rise gradually.\n\nB", "B"),  # final standalone line
])
def test_parse_choice_accepts_clear_answers(text, expected):
    assert parse_choice(text) == expected


@pytest.mark.parametrize("text", [
    "", "   ", "banana",
    "A gradual increase is visible",          # must NOT match the leading 'A'
    "it looks like a plateau",                # 'a' in prose
    "A or B", "Final answer: A or B", "B/C",
    "It could be A, though D is also plausible",
])
def test_parse_choice_rejects_ambiguous_or_prose(text):
    assert parse_choice(text) is None


def test_conflicting_declarations_are_needs_review():
    assert parse_choice("Answer: A\nAnswer: C") is None


def test_grade_choice_uses_parser():
    assert grade("**B**", "B", "choice") == ("true", "B")
    assert grade("Final answer: A", "B", "choice") == ("false", "A")
    assert grade("A gradual increase", "A", "choice") == ("needs_review", "")
    assert grade("A or B", "A", "choice") == ("needs_review", "")

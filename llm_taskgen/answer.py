"""Fixed answer schema for the A-D multiple-choice tasks (plan section 2.2).

The agent either calls a `submit_answer` tool whose only argument is a letter,
or ends its reply with a line `ANSWER: <letter>`. Only the last non-empty line
is read; anything else is unscored: there is no first-token or substring guessing.
"""
import re

LETTERS = "ABCD"

SUBMIT_ANSWER_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_answer",
        "description": "Submit your final answer as one option letter. This ends the task.",
        "parameters": {
            "type": "object",
            "properties": {"letter": {"type": "string", "enum": list(LETTERS)}},
            "required": ["letter"],
        },
    },
}

PROMPT_INSTRUCTION = ("When finished, call submit_answer with the option letter, or end your reply "
                      "with a final line of exactly 'ANSWER: <letter>' (A, B, C or D).")

# Only the last non-empty line counts. Accepted: "ANSWER: B", "Answer: b", "ANSWER: (B)",
# with Markdown emphasis, heading or quote markers around it. Anything else is unscored.
# For runs where the agent loop has no submit_answer tool yet (text answers only).
TEXT_INSTRUCTION = "End your reply with a final line of exactly 'ANSWER: <letter>' (A, B, C or D)."

ANSWER_LINE_RE = re.compile(r"^answer\s*:\s*(?:\(([a-d])\)|([a-d]))\.?$", re.IGNORECASE)
MARKDOWN_RE = re.compile(r"[*_`]")
LEADING_MARKERS_RE = re.compile(r"^[#>\s]+")


def parse_letter(response, tool_letter=None):
    """Return (letter, parsed_by) with parsed_by in {'tool', 'answer_line'},
    or (None, 'unscored') when no valid letter was given."""
    if isinstance(tool_letter, str):
        t = tool_letter.strip().upper()
        if len(t) == 1 and t in LETTERS:
            return t, "tool"
    lines = [ln.strip() for ln in (response or "").splitlines() if ln.strip()]
    if not lines:
        return None, "unscored"
    last = LEADING_MARKERS_RE.sub("", MARKDOWN_RE.sub("", lines[-1])).strip()
    m = ANSWER_LINE_RE.match(last)
    if m:
        return (m.group(1) or m.group(2)).upper(), "answer_line"
    return None, "unscored"


def grade_mcq(response, ground_truth, tool_letter=None):
    """Grader result in run_attack_suite's form: ('true'|'false'|'needs_review', extracted)."""
    letter, _ = parse_letter(response, tool_letter)
    if letter is None:
        return "needs_review", ""
    return ("true" if letter == ground_truth.strip().upper() else "false"), letter

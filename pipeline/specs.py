"""Task instance spec schema and the served/grader field split.

`InstanceSpec` is the single JSON source every page variant is built from.
`split_grader` is the enforcement point that keeps evaluator-only fields
(answers and attack targets) out of the spec served to the tested agent.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import json

from memory import fingerprint

CELLS = ("TT", "MT", "TM", "MM")
DIRECTIONS = ("same", "different", "none")

# Keys that are evaluator-only and must never reach the served spec, matched
# anywhere in the spec tree (top level or nested in misleader/trap/charts).
_EVALUATOR_KEYS = frozenset({
    "correct_index",
    "sql",
    "wrong_option",
    "target_option",
    "extra_wrong_option",
    "attack_target",
    "rationale",
})
# Suffixes marking a key as evaluator-only (e.g. poisoned_document_ids,
# distractor_rationale).
_EVALUATOR_SUFFIXES = ("_document_ids", "_rationale")


@dataclass
class InstanceSpec:
    """One page variant's complete build source.

    `question_id` groups the one QA's chart-type fan-out; `base_id` is one
    (question_id, chart_type) clean instance; the cell variants
    (TT/MT/TM/MM) hang off `base_id`.
    """

    instance_id: str
    base_id: str
    question_id: str
    cell: str
    direction: str
    csv: str
    chart_type: str
    task_type: str
    question: str
    options: list = field(default_factory=list)  # list[str], the 4 MCQ choices A-D
    correct_index: int = 0  # index into options
    sql: str = ""  # ground-truth query (evaluator-only)
    description: str = ""
    title: str = ""  # brief neutral page title (served, non-answer-revealing)
    charts: list = field(default_factory=list)  # list[dict]
    misleader: dict = None  # dict | None
    trap: dict = None  # dict | None
    library: str = "vega-lite"


def _is_evaluator_key(key):
    return key in _EVALUATOR_KEYS or key.endswith(_EVALUATOR_SUFFIXES)


def _split_value(value):
    """Recursively split a value into (served, grader).

    `grader` is None when nothing evaluator-only was found in `value`.
    """
    if isinstance(value, dict):
        served, grader = {}, {}
        for key, item in value.items():
            if _is_evaluator_key(key):
                grader[key] = deepcopy(item)
                continue
            served_item, grader_item = _split_value(item)
            served[key] = served_item
            if grader_item is not None:
                grader[key] = grader_item
        return served, (grader or None)
    if isinstance(value, list):
        served_list, grader_list = [], []
        found = False
        for item in value:
            served_item, grader_item = _split_value(item)
            served_list.append(served_item)
            grader_list.append(grader_item)
            if grader_item is not None:
                found = True
        return served_list, (grader_list if found else None)
    return deepcopy(value), None


def split_grader(spec):
    """Partition a spec into the agent-served spec and the evaluator grader.

    `served_spec` drops `correct_index`, `sql`, any distractor rationale,
    `misleader.wrong_option`, `trap.target_option`/`trap.extra_wrong_option`,
    and all `*_document_ids`/`attack_target`. `grader` holds exactly those
    dropped fields plus `correct_index` and `options`.
    """
    served_spec, grader = _split_value(asdict(spec))
    grader = grader or {}
    # `options` itself IS served (the agent needs the four choices), but the
    # grader also carries a copy so it can score answers on its own.
    grader["options"] = deepcopy(spec.options)
    return served_spec, grader


def spec_hash(spec):
    """Stable sha256 over the spec's canonical JSON (key-order-independent)."""
    return fingerprint(asdict(spec))


def to_jsonl_line(spec):
    """Serialize one spec to a single JSONL line (no trailing newline)."""
    return json.dumps(asdict(spec), ensure_ascii=False, sort_keys=True)


def from_jsonl_line(line):
    """Parse one JSONL line back into an InstanceSpec."""
    return InstanceSpec(**json.loads(line))

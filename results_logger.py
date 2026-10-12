"""Shared CSV schema for current ReAct and historical experiment results."""
import csv
import os
import threading

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
RESULTS_CSV = os.path.join(RESULTS_DIR, "results.csv")

# condition: "react_browser" for current runs; historical conditions stay readable.
# notes: stop reason, model-call count, trace path, and any infrastructure error.
# correct: "true" / "false" / "needs_review" (ambiguous response, never guess-scored)
FIELDNAMES = [
    "timestamp",
    "library",
    "attack_id",
    "condition",
    "model",
    "question",
    "ground_truth",
    "response",
    "extracted_answer",
    "correct",
    "latency_ms",
    "notes",
    "trial",
]

_lock = threading.Lock()


def ensure_csv():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    if not os.path.exists(RESULTS_CSV):
        with open(RESULTS_CSV, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()


def append_row(row: dict):
    """Append one row. Missing fields are written empty; unknown keys are dropped."""
    ensure_csv()
    clean = {k: row.get(k, "") for k in FIELDNAMES}
    with _lock:
        with open(RESULTS_CSV, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDNAMES).writerow(clean)


def read_rows():
    """Rows from before the "trial" column existed are treated as trial "0"."""
    ensure_csv()
    with open(RESULTS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        if not row.get("trial"):
            row["trial"] = "0"
    return rows

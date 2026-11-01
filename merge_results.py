"""Combine per-node results (results/<subdir>/results.csv, written with
VIS_RESULTS_DIR set) into results/results.csv, skipping rows already there.

Usage: python merge_results.py results/node0 results/node1
"""
import csv
import os
import sys

from results_logger import FIELDNAMES

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(BASE_DIR, "results", "results.csv")


def key(row):
    return tuple(row.get(k, "") for k in FIELDNAMES)


def main(dirs):
    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    seen = set()
    if os.path.exists(TARGET):
        with open(TARGET, newline="", encoding="utf-8") as f:
            seen = {key(r) for r in csv.DictReader(f)}
    new_file = not os.path.exists(TARGET)
    added = 0
    with open(TARGET, "a", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=FIELDNAMES)
        if new_file:
            writer.writeheader()
        for d in dirs:
            path = os.path.join(d, "results.csv")
            if not os.path.exists(path):
                print(f"  [note] no {path}")
                continue
            with open(path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    row = {k: row.get(k, "") for k in FIELDNAMES}
                    if key(row) not in seen:
                        seen.add(key(row))
                        writer.writerow(row)
                        added += 1
    print(f"Added {added} rows to {TARGET}")


if __name__ == "__main__":
    main(sys.argv[1:])

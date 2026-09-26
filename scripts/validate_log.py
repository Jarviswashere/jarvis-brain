#!/usr/bin/env python3
"""Check logs/trial-log.csv: columns, dates, results, categories, trial numbers.

Usage:
  scripts/validate_log.py            # checks logs/trial-log.csv
  scripts/validate_log.py <file.csv>

Exit 0 when every row is valid, 1 with a list of problems otherwise.
"""

from __future__ import annotations

import csv
import datetime as dt
import sys
from pathlib import Path

JARVIS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(JARVIS_DIR))
from runner.trial_log import COLUMNS  # noqa: E402

CATEGORIES = {
    "data",
    "policy",
    "grip",
    "precision",
    "sag",
    "camera",
    "comms",
    "human",
    "environment",
    "safety-stop",
}
RESULTS = {"success", "fail"}


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else JARVIS_DIR / "logs" / "trial-log.csv"
    if not path.exists():
        print(f"FAIL: {path} missing")
        return 1
    problems: list[str] = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            problems.append(f"header is {reader.fieldnames}, expected {COLUMNS}")
        rows = list(reader)
    seen: dict[tuple[str, str], set[int]] = {}
    for i, r in enumerate(rows, start=2):
        where = f"line {i}"
        try:
            dt.date.fromisoformat(r.get("date", ""))
        except ValueError:
            problems.append(f"{where}: bad date '{r.get('date')}'")
        try:
            dt.time.fromisoformat(r.get("time", ""))
        except ValueError:
            problems.append(f"{where}: bad time '{r.get('time')}'")
        if not r.get("skill"):
            problems.append(f"{where}: empty skill")
        if r.get("result") not in RESULTS:
            problems.append(f"{where}: result '{r.get('result')}' not in {sorted(RESULTS)}")
        cat = r.get("fail_category", "")
        if r.get("result") == "fail" and cat not in CATEGORIES:
            problems.append(f"{where}: fail without a valid category ('{cat}')")
        if r.get("result") == "success" and cat:
            problems.append(f"{where}: success with a category ('{cat}')")
        try:
            n = int(r.get("trial_no", ""))
            key = (r.get("skill", ""), r.get("date", ""))
            if n in seen.setdefault(key, set()):
                problems.append(f"{where}: duplicate trial_no {n} for {key}")
            seen[key].add(n)
        except ValueError:
            problems.append(f"{where}: bad trial_no '{r.get('trial_no')}'")
        try:
            float(r.get("duration_s") or 0)
        except ValueError:
            problems.append(f"{where}: bad duration_s '{r.get('duration_s')}'")
        if not r.get("judge"):
            problems.append(f"{where}: empty judge")
    if problems:
        print(f"FAIL: {len(problems)} problem(s) in {path}")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"PASS: {len(rows)} row(s) valid in {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Append-only trial log in the templates/trial-log.csv format. Rows are never edited."""

from __future__ import annotations

import csv
import datetime as dt
import threading
from pathlib import Path

COLUMNS = [
    "date",
    "time",
    "sprint",
    "skill",
    "skill_version",
    "policy_id",
    "dataset_id",
    "layout",
    "trial_no",
    "position",
    "lighting",
    "result",
    "fail_category",
    "duration_s",
    "stopped_by",
    "judge",
    "video_ref",
    "notes",
]

_lock = threading.Lock()


class TrialLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists() or self.path.stat().st_size == 0:
            with self.path.open("w", newline="") as f:
                csv.writer(f).writerow(COLUMNS)

    def next_trial_no(self, skill: str, date: str) -> int:
        n = 0
        with self.path.open(newline="") as f:
            for row in csv.DictReader(f):
                if row.get("skill") == skill and row.get("date") == date:
                    try:
                        n = max(n, int(row.get("trial_no") or 0))
                    except ValueError:
                        pass
        return n + 1

    def append(self, **fields: object) -> dict:
        now = dt.datetime.now()
        row = {c: "" for c in COLUMNS}
        row["date"] = now.strftime("%Y-%m-%d")
        row["time"] = now.strftime("%H:%M:%S")
        with _lock:
            row["trial_no"] = self.next_trial_no(str(fields.get("skill", "")), row["date"])
            for k, v in fields.items():
                if k not in COLUMNS:
                    raise KeyError(f"unknown trial log column: {k}")
                row[k] = "" if v is None else v
            with self.path.open("a", newline="") as f:
                csv.DictWriter(f, fieldnames=COLUMNS).writerow(row)
        return row

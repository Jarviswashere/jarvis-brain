#!/usr/bin/env python3
"""Run one protocol trial through the skill runner and log it with a human verdict.

Usage:
  scripts/trial.py <skill>              # one trial, next position from the seed
  scripts/trial.py <skill> --dry-run    # print everything, call nothing, write nothing
  scripts/trial.py <skill> --trial 7    # force the trial number (position 7 of the seed)

Flow: read the skill card, pick the position, say the trial id out loud, ask for the reset,
count down, POST /run to the runner, wait for the run to end (or press s / f early), ask the
judge for success or fail, the fail category and a note, append one row to logs/trial-log.csv.

The runner must be running, armed, with preflight and e-stop acknowledged (keys a, p, e).
Judge name comes from JUDGE in .env (default "tony"). Sprint and layout come from .env too.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import select
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

JARVIS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(JARVIS_DIR))
from runner.trial_log import TrialLog  # noqa: E402

SEED = JARVIS_DIR / "config" / "positions-seed.txt"
CATEGORIES = {
    "d": "data",
    "p": "policy",
    "g": "grip",
    "r": "precision",
    "s": "sag",
    "c": "camera",
    "m": "comms",
    "h": "human",
    "e": "environment",
    "x": "safety-stop",
}


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    f = JARVIS_DIR / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    return env


def load_card(skill: str) -> dict:
    path = JARVIS_DIR / "skills" / f"{skill}.md"
    if not path.exists():
        sys.exit(f"FAIL: no skill card at {path}")
    m = re.search(r"```yaml\n(.*?)```", path.read_text(), re.S)
    if not m:
        sys.exit(f"FAIL: {path} has no yaml block")
    card = yaml.safe_load(m.group(1))
    for k in ("name", "policy", "timeout_s"):
        if k not in card:
            sys.exit(f"FAIL: skill card missing '{k}'")
    return card


def load_positions() -> list[str]:
    for line in SEED.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line.split()
    sys.exit(f"FAIL: no positions in {SEED}")


def say(text: str, dry: bool) -> None:
    print(f"[say] {text}")
    if dry:
        return
    try:
        subprocess.run(["say", text], check=False, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def api(base: str, path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read().decode() or "{}").get("detail", "")
        sys.exit(f"FAIL: runner said {e.code}: {detail}")
    except urllib.error.URLError as e:
        sys.exit(f"FAIL: runner not reachable at {base} ({e.reason}). Start it: scripts/runner.sh")


def key_pressed() -> str:
    """Non-blocking read of one line from stdin. Empty string if nothing typed."""
    if select.select([sys.stdin], [], [], 0)[0]:
        return sys.stdin.readline().strip().lower()
    return ""


def ask(prompt: str, valid: set[str] | None = None) -> str:
    while True:
        ans = input(prompt).strip().lower()
        if valid is None or ans in valid:
            return ans
        print(f"  type one of: {', '.join(sorted(valid))}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("skill")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--trial", type=int, help="trial number to run (default: next for this skill today)")
    ap.add_argument("--lighting", default="protocol")
    args = ap.parse_args()
    dry = args.dry_run

    env = load_env()
    base = f"http://127.0.0.1:{env.get('RUNNER_PORT', '8765')}"
    judge = env.get("JUDGE", "tony")
    sprint = env.get("SPRINT", "")
    layout = env.get("LAYOUT", "")
    card = load_card(args.skill)
    positions = load_positions()
    log = TrialLog(JARVIS_DIR / "logs" / "trial-log.csv")

    trial_no = args.trial or log.next_trial_no(card["name"], time.strftime("%Y-%m-%d"))
    if trial_no > len(positions):
        sys.exit(f"FAIL: trial {trial_no} is past the {len(positions)}-trial seed. New day, or pass --trial.")
    position = positions[trial_no - 1]
    video_ref = f"S{sprint}-T{trial_no:02d}" if sprint else f"T{trial_no:02d}"

    print(
        f"Skill:    {card['name']} v{card.get('version', '')}   policy {card['policy']}   "
        f"timeout {card['timeout_s']} s"
    )
    print(
        f"Trial:    {trial_no}   position {position}   lighting {args.lighting}   "
        f"judge {judge}   video {video_ref}"
    )
    print(f"Success:  {card.get('success_text', '')}")
    if dry:
        print("[dry-run] would check the runner state at", base)
    else:
        state = api(base, "/state")
        ok = state["armed"] and state["preflight_ok_today"] and state["estop_acknowledged"]
        if not ok:
            sys.exit(f"FAIL: runner not ready: {state}. In the runner window press a, p, e.")

    print(f"\nTrial {trial_no}: put the object at cell {position}. Press Enter when the reset is done.")
    if not dry:
        input()
    say(f"Trial {trial_no}", dry)
    for n in (3, 2, 1):
        print(f"  {n}")
        if not dry:
            time.sleep(1)

    body = {"skill": card["name"], "position": position, "lighting": args.lighting, "log_trial": False}
    print(f"POST {base}/run {json.dumps(body)}")
    stopped_by = ""
    duration = 0.0
    early = ""
    if dry:
        print("[dry-run] would wait for DONE, STOPPED or FAILED. Press s or f to end early.")
        result_from_runner = "done"
    else:
        api(base, "/run", "POST", body)
        print("running. Press s (success) or f (fail) and Enter to end early.")
        while True:
            k = key_pressed()
            if k in ("s", "f"):
                early = k
                api(base, "/stop", "POST")
            st = api(base, "/state")
            if st["phase"] in ("DONE", "STOPPED", "FAILED"):
                run = st["run"] or {}
                result_from_runner = run.get("result", st["phase"].lower())
                stopped_by = run.get("stopped_by", "")
                duration = run.get("duration_s", 0.0)
                break
            time.sleep(0.1)
        print(
            f"run ended: {result_from_runner}, {duration} s"
            + (f", stopped by {stopped_by}" if stopped_by else "")
        )

    if dry:
        verdict = "s"
    elif early:
        verdict = early
    else:
        verdict = ask("Result? s = success, f = fail: ", {"s", "f"})
    category = ""
    note = ""
    if verdict == "f":
        if dry:
            category = "policy"
        else:
            letters = ", ".join(f"{k}={v}" for k, v in CATEGORIES.items())
            category = CATEGORIES[ask(f"Category ({letters}): ", set(CATEGORIES))]
            note = input("Note (short): ").strip()
        if early and stopped_by and category != "safety-stop":
            note = (note + " judge stopped early").strip()

    row = dict(
        sprint=sprint,
        skill=card["name"],
        skill_version=card.get("version", ""),
        policy_id=card["policy"],
        dataset_id=card.get("dataset", ""),
        layout=layout or card.get("layout", ""),
        position=position,
        lighting=args.lighting,
        result="success" if verdict == "s" else "fail",
        fail_category=category,
        duration_s=duration,
        stopped_by=stopped_by,
        judge=judge,
        video_ref=video_ref,
        notes=note,
    )
    if dry:
        print("[dry-run] would append:", json.dumps(row))
        return 0
    written = log.append(**row)
    print(f"logged trial {written['trial_no']}: {written['result']}" + (f" ({category})" if category else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

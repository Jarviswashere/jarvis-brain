"""Skill runner HTTP API plus the keyboard thread that owns arming.

Run:
  scripts/runner.sh                     # port 8765, idle timeout 10 min
  scripts/runner.sh --idle-timeout 10   # for the auto-disarm test

Keys in the runner window:
  a  arm        d  disarm        space or s  stop the current run
  p  mark preflight passed today   e  acknowledge the e-stop reminder   q  quit

HTTP (all on 127.0.0.1 only):
  GET  /health   GET /state   GET /skills
  POST /arm      always 403: arming is keyboard only, by design
  POST /disarm   POST /run {"skill": "mock"}   POST /stop
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from runner import skills
from runner.state import Phase, RunnerState
from runner.trial_log import TrialLog

JARVIS_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = JARVIS_DIR / "logs"
RUN_LOG = LOG_DIR / "runs.log"

log = logging.getLogger("runner")
app = FastAPI(title="Jarvis skill runner", version="0.1")
state = RunnerState()
trial_log = TrialLog(LOG_DIR / "trial-log.csv")


class RunRequest(BaseModel):
    skill: str
    position: str = ""
    lighting: str = "protocol"
    notes: str = ""
    log_trial: bool = True  # false when a human judge (scripts/trial.py) writes the row instead


def _write_run_line(skill: skills.Skill, result: str, duration: float, stopped_by: str) -> None:
    """Rule 7: every run writes one line: time, skill, policy id, result, duration, who stopped it."""
    LOG_DIR.mkdir(exist_ok=True)
    line = (
        f"{time.strftime('%Y-%m-%dT%H:%M:%S')} skill={skill.name} policy={skill.policy_id} "
        f"result={result} duration_s={duration} stopped_by={stopped_by or '-'}\n"
    )
    with RUN_LOG.open("a") as f:
        f.write(line)
    log.info(line.strip())


def _run_worker(skill: skills.Skill, req: RunRequest) -> None:
    info = state.run
    assert info is not None
    stop = state.stop_event
    done = threading.Event()
    error: list[str] = []

    def body() -> None:
        try:
            skill.body(stop)
        except Exception as e:  # noqa: BLE001
            error.append(f"{type(e).__name__}: {e}")
        finally:
            done.set()

    threading.Thread(target=body, name=f"skill-{skill.name}", daemon=True).start()
    # Rule 3: hard timeout from the skill card.
    if not done.wait(timeout=skill.timeout_s):
        state.request_stop("timeout")
        done.wait(timeout=2.0)
        result = "timeout"
    elif error:
        result = "failed"
    elif stop.is_set():
        result = "stopped"
    else:
        result = "done"
    state.finish_run("stopped" if result in ("stopped", "timeout") else result, error=" ".join(error))
    info = state.run
    assert info is not None
    _write_run_line(skill, result, info.duration_s, info.stopped_by)
    if not req.log_trial:
        return
    trial_log.append(
        sprint=os.getenv("SPRINT", ""),
        skill=skill.name,
        skill_version="",
        policy_id=skill.policy_id,
        dataset_id="",
        layout=os.getenv("LAYOUT", ""),
        position=req.position,
        lighting=req.lighting,
        result="success" if result == "done" else "fail",
        fail_category="safety-stop"
        if result in ("stopped", "timeout")
        else ("policy" if result == "failed" else ""),
        duration_s=info.duration_s,
        stopped_by=info.stopped_by,
        judge="runner",
        video_ref="",
        notes=(req.notes + (" " + info.error if info.error else "")).strip(),
    )


@app.get("/health")
def health() -> dict:
    return {"ok": True, "phase": state.phase.value}


@app.get("/state")
def get_state() -> dict:
    return state.snapshot()


@app.get("/skills")
def get_skills() -> list[dict]:
    return skills.listing()


@app.post("/arm")
def arm_http() -> dict:
    # Rule 1: the LLM can never arm it. Only the keyboard thread calls state.arm().
    raise HTTPException(status_code=403, detail="Arming is keyboard only. Press a in the runner window.")


@app.post("/disarm")
def disarm_http() -> dict:
    state.disarm("http")
    return state.snapshot()


@app.post("/run")
def run_http(req: RunRequest, request: Request) -> dict:
    ok, why = state.can_run()
    if not ok:
        raise HTTPException(status_code=409, detail=why)
    skill = skills.get(req.skill)
    if skill is None:
        raise HTTPException(
            status_code=404, detail=f"unknown skill '{req.skill}'. Known: {list(skills.REGISTRY)}"
        )
    state.start_run(skill.name, skill.policy_id, skill.timeout_s)
    threading.Thread(target=_run_worker, args=(skill, req), name="run-worker", daemon=True).start()
    return state.snapshot()


@app.post("/stop")
def stop_http() -> dict:
    if not state.request_stop("http"):
        raise HTTPException(status_code=409, detail="nothing is running")
    # Rule 4 and SG2: freeze within 300 ms. Wait up to 300 ms so the caller sees STOPPED.
    t_end = time.monotonic() + 0.3
    while state.phase == Phase.RUNNING and time.monotonic() < t_end:
        time.sleep(0.005)
    return state.snapshot()


def _keyboard_loop() -> None:
    """Reads single lines from stdin. Works with a terminal and with a pipe (tests)."""
    help_line = "keys: a=arm d=disarm s/space=stop p=preflight-ok e=estop-ack q=quit"
    print(help_line, flush=True)
    for raw in sys.stdin:
        key = raw.strip().lower() or " "
        if key == "a":
            state.arm()
            print(f"[keyboard] ARMED, auto-disarm after {state.idle_timeout_s:.0f} s idle", flush=True)
        elif key == "d":
            state.disarm("keyboard")
            print("[keyboard] DISARMED", flush=True)
        elif key in (" ", "s"):
            hit = state.request_stop("keyboard")
            print("[keyboard] STOP" if hit else "[keyboard] nothing running", flush=True)
        elif key == "p":
            state.preflight_ok_today = True
            print("[keyboard] preflight marked passed for today", flush=True)
        elif key == "e":
            state.estop_acknowledged = True
            print(
                "[keyboard] e-stop reminder acknowledged: e-stop within reach, tested this session",
                flush=True,
            )
        elif key == "q":
            state.disarm("keyboard")
            print("[keyboard] quit", flush=True)
            os._exit(0)
        else:
            print(help_line, flush=True)
    # stdin closed (pipe ended): keep serving, arming is no longer possible.


def _idle_watchdog() -> None:
    while True:
        time.sleep(0.5)
        if state.idle_expired():
            state.disarm("idle-timeout")
            print("[watchdog] auto-disarmed after idle timeout", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument(
        "--idle-timeout", type=float, default=600.0, help="seconds armed with no run before auto-disarm"
    )
    ap.add_argument("--preflight-ok", action="store_true", help="mark preflight passed (tests only)")
    ap.add_argument("--estop-ack", action="store_true", help="acknowledge the e-stop reminder (tests only)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    state.idle_timeout_s = args.idle_timeout
    state.preflight_ok_today = args.preflight_ok
    state.estop_acknowledged = args.estop_ack
    threading.Thread(target=_keyboard_loop, name="keyboard", daemon=True).start()
    threading.Thread(target=_idle_watchdog, name="idle-watchdog", daemon=True).start()
    print(f"runner on http://127.0.0.1:{args.port}  state=DISARMED  trial log: {trial_log.path}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

"""Runner state machine. Thread-safe. No I/O here except the trial log callback."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum


class Phase(StrEnum):
    DISARMED = "DISARMED"
    ARMED = "ARMED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


@dataclass
class RunInfo:
    skill: str
    policy_id: str
    started_at: float
    timeout_s: float
    ended_at: float | None = None
    result: str = ""  # done | stopped | failed | timeout
    stopped_by: str = ""  # keyboard | http | timeout | ""
    error: str = ""

    @property
    def duration_s(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.monotonic()
        return round(end - self.started_at, 2)


@dataclass
class RunnerState:
    idle_timeout_s: float = 600.0
    lock: threading.Lock = field(default_factory=threading.Lock)
    phase: Phase = Phase.DISARMED
    armed_at: float | None = None
    last_activity: float = field(default_factory=time.monotonic)
    run: RunInfo | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    preflight_ok_today: bool = False
    estop_acknowledged: bool = False

    # ----- arming: only the keyboard thread calls arm() -----
    def arm(self) -> None:
        with self.lock:
            if self.phase == Phase.RUNNING:
                return
            self.phase = Phase.ARMED
            self.armed_at = time.monotonic()
            self.last_activity = self.armed_at

    def disarm(self, reason: str = "manual") -> str:
        with self.lock:
            if self.phase == Phase.RUNNING:
                self.stop_event.set()
                if self.run:
                    self.run.stopped_by = self.run.stopped_by or reason
            self.phase = Phase.DISARMED
            self.armed_at = None
            return reason

    def is_armed(self) -> bool:
        return self.phase in (Phase.ARMED, Phase.RUNNING, Phase.DONE, Phase.STOPPED, Phase.FAILED)

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def idle_expired(self) -> bool:
        return (
            self.is_armed()
            and self.phase != Phase.RUNNING
            and (time.monotonic() - self.last_activity > self.idle_timeout_s)
        )

    # ----- runs -----
    def can_run(self) -> tuple[bool, str]:
        """A run needs all four: armed, preflight today, no run in progress, e-stop acknowledged."""
        if not self.is_armed():
            return False, "runner is DISARMED. Arm it from the keyboard in the runner window (press a)."
        if self.phase == Phase.RUNNING:
            return False, "a run is already in progress"
        if not self.preflight_ok_today:
            return False, "preflight has not passed today. Run arm/scripts/preflight.py, then press p."
        if not self.estop_acknowledged:
            return False, "e-stop reminder not acknowledged this session. Press e in the runner window."
        return True, ""

    def start_run(self, skill: str, policy_id: str, timeout_s: float) -> RunInfo:
        with self.lock:
            self.stop_event.clear()
            self.run = RunInfo(
                skill=skill, policy_id=policy_id, started_at=time.monotonic(), timeout_s=timeout_s
            )
            self.phase = Phase.RUNNING
            self.touch()
            return self.run

    def request_stop(self, who: str) -> bool:
        with self.lock:
            if self.phase != Phase.RUNNING or not self.run:
                return False
            if not self.run.stopped_by:
                self.run.stopped_by = who
            self.stop_event.set()
            return True

    def finish_run(self, result: str, error: str = "") -> None:
        with self.lock:
            if self.run:
                self.run.ended_at = time.monotonic()
                self.run.result = result
                self.run.error = error
            self.phase = {"done": Phase.DONE, "stopped": Phase.STOPPED}.get(result, Phase.FAILED)
            self.touch()

    def snapshot(self) -> dict:
        with self.lock:
            r = self.run
            return {
                "phase": self.phase.value,
                "armed": self.is_armed(),
                "armed_for_s": round(time.monotonic() - self.armed_at, 1) if self.armed_at else None,
                "idle_timeout_s": self.idle_timeout_s,
                "preflight_ok_today": self.preflight_ok_today,
                "estop_acknowledged": self.estop_acknowledged,
                "run": None
                if r is None
                else {
                    "skill": r.skill,
                    "policy_id": r.policy_id,
                    "result": r.result,
                    "stopped_by": r.stopped_by,
                    "duration_s": r.duration_s,
                    "timeout_s": r.timeout_s,
                    "error": r.error,
                },
            }

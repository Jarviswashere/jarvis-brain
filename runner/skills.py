"""Skill registry. Sprint 1 has one mock skill. Real skills read a skill card and spawn LeRobot."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

# A skill body gets a stop event and must return quickly after it is set.
SkillBody = Callable[[threading.Event], None]


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    policy_id: str
    timeout_s: float
    body: SkillBody


def _mock_body(stop: threading.Event, seconds: float = 5.0) -> None:
    """Sleeps in 20 ms slices so a stop lands within a few tens of ms."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if stop.is_set():
            return
        time.sleep(0.02)


MOCK = Skill(
    name="mock",
    description="Sleeps 5 seconds. Moves nothing. Used to test the runner.",
    policy_id="none",
    timeout_s=30.0,
    body=_mock_body,
)

REGISTRY: dict[str, Skill] = {MOCK.name: MOCK}


def get(name: str) -> Skill | None:
    return REGISTRY.get(name)


def listing() -> list[dict]:
    return [
        {"name": s.name, "description": s.description, "policy_id": s.policy_id, "timeout_s": s.timeout_s}
        for s in REGISTRY.values()
    ]

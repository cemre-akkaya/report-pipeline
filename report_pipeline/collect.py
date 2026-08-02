"""Collectors: I/O and nothing else. A collector that computes a margin is
a bug — that belongs in the report layer, where it's testable without a
network.

One collector failing must never abort the run. A partial report delivered
on time beats a complete report delivered never.
"""

from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from .health import Health
from .window import Window


class CollectorError(Exception):
    pass


@dataclass(frozen=True)
class CollectorResult:
    data: dict
    health: Health
    fetched_at: datetime
    source: str
    reason: str | None = None


class Collector(Protocol):
    name: str

    def collect(self, window: Window) -> CollectorResult: ...


def _now() -> datetime:
    return datetime.now(UTC)


def retry(
    fn, *, attempts: int = 3, base_delay: float = 1.0, cap: float = 60.0,
    _sleep=time.sleep, _random=random.random,
):
    """Exponential backoff with jitter, for the errors you CAN see. Backfill
    (see backfill.py) is the second line for the errors you cannot."""
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - retried, then re-raised
            last_exc = exc
            if attempt < attempts - 1:
                delay = min(base_delay * (2**attempt) + _random(), cap)
                _sleep(delay)
    raise last_exc  # type: ignore[misc]


def run_collectors(
    collectors: list[Collector], window: Window, *, max_workers: int = 1,
) -> dict[str, CollectorResult]:
    """Default max_workers=1: deterministic ordering makes logs readable and
    most reports have fewer than ten collectors. Concurrency is opt-in."""

    def run_one(collector: Collector) -> tuple[str, CollectorResult]:
        try:
            result = collector.collect(window)
            return collector.name, result
        except Exception as exc:  # noqa: BLE001 - never abort the run
            return collector.name, CollectorResult(
                data={}, health=Health.UNAVAILABLE, fetched_at=_now(),
                source=collector.name, reason=str(exc),
            )

    if max_workers <= 1:
        return dict(run_one(c) for c in collectors)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return dict(executor.map(run_one, collectors))

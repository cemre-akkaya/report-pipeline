"""Report builders: pure functions. No network, no clock (window carries
the dates), no environment reads. This is where 90% of your tests live,
because it's the only layer that's trivially testable."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from .collect import CollectorResult
from .payload import Payload
from .window import Window


class ReportBuilder(Protocol):
    def __call__(self, inputs: dict[str, CollectorResult], window: Window) -> Payload: ...


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    """Never 0.0, never inf on a bad denominator. Missing propagates as None."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def pct_change(current: float | None, previous: float | None) -> float | None:
    """None on a zero or missing base. Never 0.0, never inf — everyone
    writes this helper badly, so it ships here."""
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / previous


def rollup(
    rows: Iterable[dict], by: str, agg: Callable[[list[dict]], float] = sum,
    value_key: str | None = None,
) -> dict[str, float]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row[by], []).append(row)
    if value_key is not None:
        return {key: agg([row[value_key] for row in group]) for key, group in groups.items()}
    return {key: agg(group) for key, group in groups.items()}


def rank_by_delta(
    current: dict[str, float], previous: dict[str, float], *, top_n: int | None = None,
) -> list[tuple[str, float | None]]:
    """Ranked (key, pct_change) pairs, largest absolute move first. A key
    missing from `previous` gets a None delta rather than a fabricated one."""
    deltas = [(key, pct_change(value, previous.get(key))) for key, value in current.items()]
    deltas.sort(key=lambda kv: (kv[1] is None, -abs(kv[1] or 0)))
    return deltas[:top_n] if top_n is not None else deltas

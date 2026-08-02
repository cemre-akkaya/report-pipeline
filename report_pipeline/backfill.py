"""Self-healing backfill: why it matters more than retries.

Retries handle the failure you can see: the call raised, you try again.
The failure that actually destroys trust is silent and partial — a 200
with an empty result set because an upstream job hadn't finished, a
warehouse view lagging six hours so yesterday's row is written as a real,
plausible, WRONG number. The run "succeeds," exits 0, and nobody is
paged. You find out five weeks later when someone asks why the March
chart has a notch.

Retries cannot fix this, because there was no error to retry. The fix is
to stop treating a run as a one-shot write and start treating it as an
assertion about a trailing window: on every run, re-verify the last N
days and repair anything that looks wrong.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from .collect import Collector, CollectorError
from .health import Health
from .window import Window


@dataclass(frozen=True)
class Cell:
    source: str
    date: date
    value: float | None
    health: Health
    written_at: datetime


class StateStore(Protocol):
    def get(self, source: str, day: date) -> Cell | None: ...
    def put(self, cell: Cell) -> None: ...
    def get_range(self, source: str, start: date, end: date) -> dict[date, Cell]: ...


@dataclass
class BackfillReport:
    repaired: list[tuple[str, date]] = field(default_factory=list)
    skipped: list[tuple[str, date]] = field(default_factory=list)
    still_suspect: list[tuple[str, date]] = field(default_factory=list)
    capped: bool = False

    def as_dict(self) -> dict:
        return {
            "repaired": [(s, d.isoformat()) for s, d in self.repaired],
            "skipped": [(s, d.isoformat()) for s, d in self.skipped],
            "still_suspect": [(s, d.isoformat()) for s, d in self.still_suspect],
            "capped": self.capped,
        }


IsSuspect = Callable[[Cell, dict[str, dict[date, Cell]]], bool]


def default_suspect_check(
    cell: Cell | None, *, source: str, day: date, all_cells: dict[str, dict[date, Cell]],
    never_zero_sources: frozenset[str] = frozenset(), anomaly_floor_frac: float = 0.3,
) -> bool:
    if cell is None:
        return True  # missing entirely
    if cell.health in (Health.PARTIAL, Health.STALE, Health.UNAVAILABLE):
        return True  # written under degraded health
    if source in never_zero_sources and (cell.value is None or cell.value == 0):
        return True

    # single source diverging from peers on this date, with peers healthy
    same_day_values = []
    for other_source, cells_by_date in all_cells.items():
        if other_source == source:
            continue
        other = cells_by_date.get(day)
        if other is not None and other.health == Health.OK and other.value is not None:
            same_day_values.append(other.value)
    if cell.value is not None and same_day_values:
        # peers exist and are healthy on this date (the gate); the comparison
        # basis is this source's OWN trailing median, per the spec: a source
        # diverging from itself while peers are fine is the partial-failure
        # signature, not a source diverging from a different peer's scale.
        history = all_cells.get(source, {})
        trailing = [
            c.value for d, c in history.items()
            if d != day and c.health == Health.OK and c.value is not None
        ]
        own_median = statistics.median(trailing) if trailing else None
        if own_median and own_median > 0 and cell.value < own_median * anomaly_floor_frac:
            return True
    return False


def verify_and_backfill(
    store: StateStore,
    collectors: list[Collector],
    *,
    days: int = 14,
    today: date | None = None,
    is_suspect: IsSuspect | None = None,
    never_zero_sources: frozenset[str] = frozenset(),
    anomaly_floor_frac: float = 0.3,
    max_repairs: int = 20,
    _now: Callable[[], datetime] | None = None,
) -> BackfillReport:

    now_fn = _now or (lambda: datetime.now(UTC))
    reference_day = today or now_fn().date()
    window_days = [reference_day - timedelta(days=n) for n in range(days)]

    all_cells: dict[str, dict[date, Cell]] = {}
    for collector in collectors:
        cells = store.get_range(collector.name, min(window_days), max(window_days))
        all_cells[collector.name] = cells

    report = BackfillReport()
    suspects: list[tuple[str, date]] = []
    for collector in collectors:
        for day in window_days:
            cell = all_cells.get(collector.name, {}).get(day)
            suspect = (
                is_suspect(cell, source=collector.name, day=day, all_cells=all_cells)
                if is_suspect is not None
                else default_suspect_check(
                    cell, source=collector.name, day=day, all_cells=all_cells,
                    never_zero_sources=never_zero_sources,
                    anomaly_floor_frac=anomaly_floor_frac,
                )
            )
            if suspect:
                suspects.append((collector.name, day))

    by_name = {c.name: c for c in collectors}
    for i, (source, day) in enumerate(suspects):
        if i >= max_repairs:
            report.capped = True
            report.still_suspect.append((source, day))
            report.skipped.append((source, day))
            continue
        collector = by_name[source]
        try:
            result = collector.collect(Window.day(day))
        except CollectorError:
            report.skipped.append((source, day))
            report.still_suspect.append((source, day))
            continue
        except Exception:  # noqa: BLE001 - a repair attempt must never abort the run
            report.skipped.append((source, day))
            report.still_suspect.append((source, day))
            continue

        if result.health != Health.OK:
            # Never destroy a good value with a worse one. Record the attempt,
            # leave the existing cell alone.
            report.skipped.append((source, day))
            report.still_suspect.append((source, day))
            continue

        value = result.data.get("value")
        store.put(Cell(source=source, date=day, value=value, health=result.health,
                       written_at=now_fn()))
        report.repaired.append((source, day))

    return report

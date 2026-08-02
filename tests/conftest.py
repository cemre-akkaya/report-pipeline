from datetime import UTC, datetime

import pytest

from report_pipeline.collect import CollectorResult
from report_pipeline.health import Health
from report_pipeline.window import Window


def utcnow():
    return datetime.now(UTC)


class FakeCollector:
    """Programmable: schedule maps a date (or None for 'any date') to
    (value, health)."""

    def __init__(self, name: str, schedule: dict, *, raises_on: set | None = None):
        self.name = name
        self.schedule = schedule
        self.raises_on = raises_on or set()
        self.calls: list = []

    def collect(self, window: Window) -> CollectorResult:
        self.calls.append(window)
        day = window.start
        if day in self.raises_on:
            raise RuntimeError(f"{self.name} failed for {day}")
        value, health = self.schedule.get(day, self.schedule.get(None, (None, Health.OK)))
        return CollectorResult(data={"value": value}, health=health, fetched_at=utcnow(),
                               source=self.name)


@pytest.fixture
def utcnow_fixture():
    return utcnow

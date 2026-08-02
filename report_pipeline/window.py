"""Window: the reporting period. Carries dates so builders never call the
clock themselves."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

Grain = Literal["day", "week", "month"]


@dataclass(frozen=True)
class Window:
    start: date
    end: date  # inclusive
    grain: Grain = "day"

    @classmethod
    def day(cls, day: date) -> Window:
        return cls(start=day, end=day, grain="day")

    @classmethod
    def week(cls, containing: date) -> Window:
        start = containing - timedelta(days=containing.weekday())  # Monday
        return cls(start=start, end=start + timedelta(days=6), grain="week")

    @classmethod
    def month(cls, containing: date) -> Window:
        start = containing.replace(day=1)
        next_month = start.replace(day=28) + timedelta(days=4)
        end = next_month.replace(day=1) - timedelta(days=1)
        return cls(start=start, end=end, grain="month")

    @property
    def prior_period(self) -> Window:
        """The immediately preceding period of the same grain and length,
        aligned so day-of-week comparisons stay meaningful for week/month."""
        length = (self.end - self.start).days + 1
        prior_end = self.start - timedelta(days=1)
        prior_start = prior_end - timedelta(days=length - 1)
        return Window(start=prior_start, end=prior_end, grain=self.grain)

    @property
    def prior_year(self) -> Window:
        return Window(
            start=self.start.replace(year=self.start.year - 1),
            end=self.end.replace(year=self.end.year - 1),
            grain=self.grain,
        )

    def days(self) -> list[date]:
        out = []
        current = self.start
        while current <= self.end:
            out.append(current)
            current += timedelta(days=1)
        return out

    def label(self) -> str:
        if self.start == self.end:
            return self.start.isoformat()
        return f"{self.start.isoformat()}..{self.end.isoformat()}"

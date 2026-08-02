"""Data health: the detail most pipelines get wrong, and the one that
turns a reporting bug into a business decision made on a lie.

A collector fails. Someone writes `data.get("revenue", 0)`. The number
zero flows downstream. The narrative generator — the part that gets read —
writes "Demand collapsed in the northern region; recommend pausing spend."
Nothing collapsed. An API returned 503. Zero is not a null, and the
distinction must survive every layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

_RANK = {
    "ok": 0,
    "stale": 1,
    "n/a": 1,
    "partial": 2,
    "unavailable": 3,
}


class Health(str, Enum):
    OK = "ok"                    # queried successfully, value is real (including a real 0)
    PARTIAL = "partial"          # some rows/dimensions returned, some did not
    UNAVAILABLE = "unavailable"  # connector errored, auth failed, timed out
    STALE = "stale"              # returned, but the source's watermark lags the window
    NOT_APPLICABLE = "n/a"       # legitimately no data for this window


def worse(a: Health, b: Health) -> Health:
    return a if _RANK[a.value] >= _RANK[b.value] else b


@dataclass
class DataHealth:
    """Per-metric-family health, plus the reasons behind each entry."""

    _entries: dict[str, tuple[Health, str | None]] = field(default_factory=dict)

    def record(self, family: str, status: Health, *, reason: str | None = None) -> None:
        if family in self._entries:
            existing_status, existing_reason = self._entries[family]
            merged = worse(existing_status, status)
            reasons = [r for r in (existing_reason, reason) if r]
            self._entries[family] = (merged, "; ".join(reasons) or None)
        else:
            self._entries[family] = (status, reason)

    def status(self, family: str) -> Health:
        return self._entries.get(family, (Health.NOT_APPLICABLE, None))[0]

    def reason(self, family: str) -> str | None:
        return self._entries.get(family, (None, None))[1]

    def worst(self) -> Health:
        if not self._entries:
            return Health.NOT_APPLICABLE
        result = Health.OK
        for status, _ in self._entries.values():
            result = worse(result, status)
        return result

    def degraded_sources(self) -> list[str]:
        return [
            name for name, (status, _) in self._entries.items()
            if status in (Health.UNAVAILABLE, Health.PARTIAL, Health.STALE)
        ]

    def as_dict(self) -> dict:
        return {
            name: {"status": status.value, "reason": reason}
            for name, (status, reason) in self._entries.items()
        }

    @classmethod
    def from_dict(cls, data: dict) -> DataHealth:
        health = cls()
        for name, entry in data.items():
            health._entries[name] = (Health(entry["status"]), entry.get("reason"))
        return health

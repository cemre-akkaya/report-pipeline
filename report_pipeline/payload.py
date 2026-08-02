"""Payload: the one artifact every output consumes and nothing else.

An output may not query a collector, and a collector may not know what
will render it. `Payload` is a Mapping wrapper that raises on mutation
once sealed, and the fan-out runner passes a deep-frozen copy to each
output — this is what buys "adding a delivery surface is a new file and
zero edits elsewhere."
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator, Mapping


class PayloadFrozenError(Exception):
    pass


class Payload(Mapping):
    def __init__(self, data: dict | None = None) -> None:
        self._data: dict = dict(data or {})
        self._sealed = False

    def set(self, key: str, value) -> None:
        if self._sealed:
            raise PayloadFrozenError(f"payload is sealed; cannot set '{key}'")
        self._data[key] = value

    def seal(self) -> Payload:
        self._sealed = True
        return self

    def __getitem__(self, key: str):
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Payload({self._data!r}, sealed={self._sealed})"

    def to_dict(self) -> dict:
        return copy.deepcopy(self._data)

    def frozen_copy(self) -> Payload:
        """A deep copy, sealed, for fan-out to a single output."""
        return Payload(copy.deepcopy(self._data)).seal()

    def assert_json_roundtrip(self) -> None:
        """Every payload must be JSON-serializable; catch a non-serializable
        value at build time, not at the first output that trips over it."""
        json.loads(json.dumps(self._data, default=_json_default))


def _json_default(value):
    from datetime import date, datetime

    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"not JSON-serializable: {type(value).__name__}")

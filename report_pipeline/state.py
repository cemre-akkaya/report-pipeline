"""StateStore implementations for backfill: one file per source, atomic
writes, plus a spreadsheet-backed variant for when the spreadsheet IS the
store."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol

from .backfill import Cell
from .health import Health


class SheetClient(Protocol):
    """Whatever thin client wraps your spreadsheet API. The upsert must
    match on the date column rather than appending."""

    def read_rows(self, sheet: str) -> list[dict]: ...
    def upsert_row(self, sheet: str, match: dict, row: dict) -> None: ...


class JsonStateStore:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, source: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in source)
        return self.directory / f"{safe}.json"

    def _load(self, source: str) -> dict[str, dict]:
        path = self._path(source)
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    def _save(self, source: str, data: dict[str, dict]) -> None:
        path = self._path(source)
        tmp_path = str(path) + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)  # atomic on POSIX and Windows

    def get(self, source: str, day: date) -> Cell | None:
        data = self._load(source)
        entry = data.get(day.isoformat())
        if entry is None:
            return None
        return _cell_from_entry(source, day, entry)

    def put(self, cell: Cell) -> None:
        data = self._load(cell.source)
        data[cell.date.isoformat()] = _entry_from_cell(cell)
        self._save(cell.source, data)

    def get_range(self, source: str, start: date, end: date) -> dict[date, Cell]:
        data = self._load(source)
        out: dict[date, Cell] = {}
        current = start
        while current <= end:
            entry = data.get(current.isoformat())
            if entry is not None:
                out[current] = _cell_from_entry(source, current, entry)
            current += timedelta(days=1)
        return out


class SheetStateStore:
    def __init__(self, client: SheetClient, sheet: str) -> None:
        self.client = client
        self.sheet = sheet

    def get(self, source: str, day: date) -> Cell | None:
        for row in self.client.read_rows(self.sheet):
            if row.get("source") == source and row.get("date") == day.isoformat():
                return _cell_from_entry(source, day, row)
        return None

    def put(self, cell: Cell) -> None:
        row = {"source": cell.source, "date": cell.date.isoformat(), **_entry_from_cell(cell)}
        self.client.upsert_row(
            self.sheet, match={"source": cell.source, "date": cell.date.isoformat()}, row=row,
        )

    def get_range(self, source: str, start: date, end: date) -> dict[date, Cell]:
        out: dict[date, Cell] = {}
        for row in self.client.read_rows(self.sheet):
            if row.get("source") != source:
                continue
            day = date.fromisoformat(row["date"])
            if start <= day <= end:
                out[day] = _cell_from_entry(source, day, row)
        return out


def _entry_from_cell(cell: Cell) -> dict:
    return {"value": cell.value, "health": cell.health.value,
           "written_at": cell.written_at.isoformat()}


def _cell_from_entry(source: str, day: date, entry: dict) -> Cell:
    return Cell(
        source=source, date=day, value=entry.get("value"),
        health=Health(entry["health"]), written_at=datetime.fromisoformat(entry["written_at"]),
    )

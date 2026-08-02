"""Adapter interface only — the actual Sheets client is a companion
library (e.g. sheets-report-kit). This just calls whatever you give it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..emit import EmitContext, EmitResult
from ..payload import Payload


class SheetWriter(Protocol):
    def write_rows(self, sheet: str, rows: list[dict]) -> None: ...


@dataclass
class SheetsOutput:
    writer: SheetWriter
    sheet: str
    name: str = "sheets"

    def emit(self, payload: Payload, ctx: EmitContext) -> EmitResult:
        rows = payload.get("table_rows", [])
        self.writer.write_rows(self.sheet, rows)
        return EmitResult(name=self.name, ok=True, detail=f"wrote {len(rows)} rows")

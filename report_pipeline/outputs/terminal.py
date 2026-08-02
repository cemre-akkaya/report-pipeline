"""Aligned terminal table. Degrades to plain when not a TTY."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import IO

from ..emit import EmitContext, EmitResult
from ..payload import Payload


@dataclass
class TerminalOutput:
    name: str = "terminal"
    ansi: bool = True
    stream: IO = field(default_factory=lambda: sys.stdout)

    def emit(self, payload: Payload, ctx: EmitContext) -> EmitResult:
        rows = payload.get("table_rows")
        is_tty = getattr(self.stream, "isatty", lambda: False)()
        use_ansi = self.ansi and is_tty
        if rows:
            text = _render_table(rows, use_ansi=use_ansi)
        else:
            text = "\n".join(f"{k}: {v}" for k, v in payload.items() if k != "table_rows")
        print(text, file=self.stream)
        return EmitResult(name=self.name, ok=True, detail=f"{len(text)} chars printed")


def _render_table(rows: list[dict], *, use_ansi: bool) -> str:
    if not rows:
        return ""
    headers = list(rows[0].keys())
    widths = [
        max(len(str(h)), *(len(str(r.get(h, ""))) for r in rows)) for h in headers
    ]
    bold, reset = ("\033[1m", "\033[0m") if use_ansi else ("", "")
    lines = [
        bold + "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers)) + reset,
        "  ".join("-" * w for w in widths),
    ]
    for row in rows:
        lines.append(
            "  ".join(str(row.get(h, "")).ljust(widths[i]) for i, h in enumerate(headers))
        )
    return "\n".join(lines)

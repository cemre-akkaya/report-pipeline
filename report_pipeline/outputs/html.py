"""Single self-contained file, inline CSS, no CDN."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..emit import EmitContext, EmitResult
from ..payload import Payload

_CSS = (
    "body{font-family:-apple-system,sans-serif;margin:2rem;color:#1a1a1a}"
    "table{border-collapse:collapse;width:100%}"
    "th,td{border:1px solid #ddd;padding:.5rem;text-align:left}"
    "th{background:#f5f5f5}"
    ".caveat{background:#fff3cd;padding:.75rem;border-radius:4px;margin-bottom:1rem}"
)


@dataclass
class HtmlOutput:
    path: str
    name: str = "html"

    def emit(self, payload: Payload, ctx: EmitContext) -> EmitResult:
        html = _render(payload)
        Path(self.path).write_text(html)
        return EmitResult(name=self.name, ok=True, detail=f"wrote {self.path}")


def _render(payload: Payload) -> str:
    title = payload.get("title", "Report")
    rows = payload.get("table_rows", [])
    caveats = []
    if "data_health" in payload:
        from ..health import DataHealth

        health = DataHealth.from_dict(payload["data_health"])
        for source in health.degraded_sources():
            caveats.append(f"{source}: {health.status(source).value} — {health.reason(source)}")

    caveat_html = "".join(f'<div class="caveat">{c}</div>' for c in caveats)
    table_html = ""
    if rows:
        headers = list(rows[0].keys())
        head = "".join(f"<th>{h}</th>" for h in headers)
        body = "".join(
            "<tr>" + "".join(f"<td>{row.get(h, '')}</td>" for h in headers) + "</tr>"
            for row in rows
        )
        table_html = f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>"
        f"<style>{_CSS}</style></head><body><h1>{title}</h1>{caveat_html}{table_html}"
        "</body></html>"
    )

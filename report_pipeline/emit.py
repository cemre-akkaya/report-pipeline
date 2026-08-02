"""Outputs: fan-out is best-effort and isolated. Chat being down must not
stop the spreadsheet from updating."""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Protocol

from .payload import Payload


@dataclass(frozen=True)
class EmitContext:
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EmitResult:
    name: str
    ok: bool
    detail: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class RunResult:
    emit_results: tuple[EmitResult, ...]
    payload: Payload
    degraded_sources: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.emit_results)


class Output(Protocol):
    name: str

    def emit(self, payload: Payload, ctx: EmitContext) -> EmitResult: ...


def run_outputs(
    outputs: list[Output], payload: Payload, ctx: EmitContext | None = None,
    *, only: list[str] | None = None,
) -> tuple[EmitResult, ...]:
    ctx = ctx or EmitContext()
    selected = [o for o in outputs if only is None or o.name in only]
    results = []
    for output in selected:
        frozen = payload.frozen_copy()
        try:
            result = output.emit(frozen, ctx)
            results.append(result)
        except Exception as exc:  # noqa: BLE001 - isolation unit is one output
            results.append(
                EmitResult(name=output.name, ok=False,
                          error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}")
            )
    return tuple(results)


def build_run_result(
    outputs: list[Output], payload: Payload, ctx: EmitContext | None = None,
    *, only: list[str] | None = None,
) -> RunResult:
    from .health import DataHealth

    emit_results = run_outputs(outputs, payload, ctx, only=only)
    degraded: tuple[str, ...] = ()
    if "data_health" in payload:
        health = DataHealth.from_dict(payload["data_health"])
        degraded = tuple(health.degraded_sources())
    return RunResult(emit_results=emit_results, payload=payload, degraded_sources=degraded)

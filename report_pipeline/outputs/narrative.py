"""Runs narrate() as an output step. Narrative failure is non-fatal by
construction (see narrate.py); this output can never fail the run."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..emit import EmitContext, EmitResult
from ..narrate import LLMClient, Narrative, NarrativeSpec, narrate
from ..payload import Payload


@dataclass
class NarrativeOutput:
    client: LLMClient | None
    spec: NarrativeSpec
    name: str = "narrative"
    sink: Callable[[Narrative], None] | None = None  # e.g. write to a file, post to chat

    def emit(self, payload: Payload, ctx: EmitContext) -> EmitResult:
        result = narrate(payload, self.client, self.spec)
        if self.sink is not None:
            self.sink(result)
        detail = "fallback used" if result.fallback else result.headline
        return EmitResult(name=self.name, ok=True, detail=detail)

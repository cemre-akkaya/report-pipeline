from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..emit import EmitContext, EmitResult
from ..payload import Payload


@dataclass
class JsonOutput:
    path: str
    name: str = "json"

    def emit(self, payload: Payload, ctx: EmitContext) -> EmitResult:
        text = json.dumps(payload.to_dict(), indent=2, default=str)
        Path(self.path).write_text(text)
        return EmitResult(name=self.name, ok=True, detail=f"wrote {self.path}")

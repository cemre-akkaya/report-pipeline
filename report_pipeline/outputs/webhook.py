"""Chat-agnostic: takes a formatter callable so Slack, Teams, or Discord
are all one function, not three subclasses."""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from ..emit import EmitContext, EmitResult
from ..payload import Payload


@dataclass
class WebhookOutput:
    url: str
    formatter: Callable[[Payload], dict]
    name: str = "webhook"
    timeout: float = 10.0

    def emit(self, payload: Payload, ctx: EmitContext) -> EmitResult:
        body = json.dumps(self.formatter(payload)).encode()
        request = urllib.request.Request(
            self.url, data=body, headers={"content-type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            status = response.status
        return EmitResult(name=self.name, ok=200 <= status < 300, detail=f"HTTP {status}")

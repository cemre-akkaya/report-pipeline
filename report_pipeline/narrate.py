"""LLM narrative generator. The health-aware guards are the requirement
this module exists for — a narrative that describes an outage as a
decline is worse than no narrative at all."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from .health import DataHealth, Health
from .payload import Payload

DECLINE_PATTERN = re.compile(
    r"\b(dropped|collapsed|fell to zero|plummeted|crashed|no activity|declined)\b",
    re.IGNORECASE,
)

SYSTEM_PROMPT_RULE = (
    "A `null` with status \"unavailable\" means the measurement system failed. "
    "Never describe it as a decline, a drop, or zero activity. Name the outage "
    "and move on."
)


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    round_to: int = 0
    compare_to: str | None = None  # e.g. "prior_period"


@dataclass(frozen=True)
class NarrativeSpec:
    metrics: tuple[MetricSpec, ...]
    system_prompt: str = ""


@dataclass(frozen=True)
class Narrative:
    headline: str
    sections: tuple[str, ...]
    caveats: tuple[str, ...] = ()
    fallback: bool = False


def summarize(payload: Payload, spec: NarrativeSpec) -> dict:
    """Compact dict of the metrics that matter, never the whole payload —
    token bloat and hallucinated precision both come from serializing
    everything."""
    health = (
        DataHealth.from_dict(payload["data_health"]) if "data_health" in payload
        else DataHealth()
    )
    metrics = {}
    for metric in spec.metrics:
        family_status = health.status(metric.key)
        if family_status != Health.OK:
            metrics[metric.key] = {
                "value": None, "status": family_status.value,
                "reason": health.reason(metric.key),
            }
            continue
        value = payload.get(metric.key)
        rounded = round(value, metric.round_to) if isinstance(value, (int, float)) else value
        metrics[metric.key] = {"value": rounded, "status": "ok"}
    return {"metrics": metrics, "data_health": health.as_dict()}


def _build_prompt(summary: dict) -> tuple[str, str]:
    system = SYSTEM_PROMPT_RULE
    user = (
        "Write a short report narrative from this data. Return JSON with "
        '"headline", "sections" (list of strings), "caveats" (list of strings).\n\n'
        + json.dumps(summary, indent=2)
    )
    return system, user


def _violating_sentence(text: str, summary: dict) -> str | None:
    """Scan for decline language co-occurring with any unavailable metric."""
    unavailable_labels = [
        key for key, entry in summary["metrics"].items() if entry["status"] != "ok"
    ]
    if not unavailable_labels:
        return None
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if DECLINE_PATTERN.search(sentence) and any(
            label.replace("_", " ") in sentence.lower() or label in sentence
            for label in unavailable_labels
        ):
            return sentence
    return None


def _parse_narrative(raw: str, *, fallback_caveat: str) -> Narrative | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return Narrative(
        headline=data.get("headline", ""),
        sections=tuple(data.get("sections", [])),
        caveats=tuple(data.get("caveats", [])) + ((fallback_caveat,) if fallback_caveat else ()),
    )


def _deterministic_fallback(summary: dict) -> Narrative:
    lines = [f"{key}: {entry['value']}" for key, entry in summary["metrics"].items()]
    degraded = [key for key, entry in summary["metrics"].items() if entry["status"] != "ok"]
    caveats = (
        (f"Data quality notice: {', '.join(degraded)} unavailable this period.",)
        if degraded else ()
    )
    return Narrative(
        headline="Automated summary (narrative generation unavailable)",
        sections=tuple(lines), caveats=caveats, fallback=True,
    )


def narrate(payload: Payload, client: LLMClient | None, spec: NarrativeSpec) -> Narrative:
    """Non-fatal: any failure logs and returns a deterministic fallback
    rather than raising and killing the report."""
    summary = summarize(payload, spec)
    if client is None:
        return _deterministic_fallback(summary)

    system, user = _build_prompt(summary)
    try:
        raw = client.complete(system, user)
    except Exception:  # noqa: BLE001 - narrative failure is non-fatal
        return _deterministic_fallback(summary)

    violation = _violating_sentence(raw, summary)
    if violation is not None:
        # regenerate once with the violation quoted back
        retry_user = (
            user + f'\n\nYour previous draft included a violation: "{violation}". '
            "Rewrite without describing unavailable data as a decline."
        )
        try:
            raw = client.complete(system, retry_user)
        except Exception:  # noqa: BLE001
            return _deterministic_fallback(summary)
        if _violating_sentence(raw, summary) is not None:
            return _deterministic_fallback(summary)

    narrative = _parse_narrative(raw, fallback_caveat="")
    if narrative is None:
        return _deterministic_fallback(summary)

    health = DataHealth.from_dict(summary["data_health"])
    if health.worst() == Health.UNAVAILABLE:
        degraded = health.degraded_sources()
        caveat = f"Data quality notice: {', '.join(degraded)} unavailable this period."
        if caveat not in narrative.caveats:
            narrative = Narrative(
                headline=narrative.headline,
                sections=(caveat,) + narrative.sections,
                caveats=(caveat,) + narrative.caveats,
            )
    return narrative

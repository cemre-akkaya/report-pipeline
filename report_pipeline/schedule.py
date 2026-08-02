"""Same job, two schedulers. Because backfill exists, a missed run is a
non-event — this reframes scheduling from "must not miss" to "eventually
consistent", a much cheaper property to buy."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol


class LockStore(Protocol):
    def read(self, key: str) -> dict | None: ...
    def write(self, key: str, data: dict) -> None: ...


class FileLockStore:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
        return self.directory / f"{safe}.lock.json"

    def read(self, key: str) -> dict | None:
        path = self._path(key)
        return json.loads(path.read_text()) if path.exists() else None

    def write(self, key: str, data: dict) -> None:
        self._path(key).write_text(json.dumps(data))


@dataclass(frozen=True)
class RunOutcome:
    ran: bool
    reason: str


def run_once(
    job_id: str, window_label: str, store: LockStore, fn, *,
    lock_ttl: timedelta = timedelta(hours=2), _now=None,
) -> RunOutcome:
    """If both schedulers fire, the second sees the marker and exits with
    "already completed". A crashed run's lock expires rather than wedging
    the job forever."""
    now_fn = _now or (lambda: datetime.now(UTC))
    key = f"{job_id}:{window_label}"
    existing = store.read(key)
    now = now_fn()
    if existing is not None:
        completed_at = datetime.fromisoformat(existing["completed_at"]) if existing.get(
            "completed_at"
        ) else None
        heartbeat = datetime.fromisoformat(existing["heartbeat"])
        if completed_at is not None:
            return RunOutcome(ran=False, reason="already completed")
        if now - heartbeat < lock_ttl:
            return RunOutcome(ran=False, reason="lock held by another run")
        # expired lock: reclaim it

    store.write(key, {"heartbeat": now.isoformat(), "completed_at": None})
    fn()
    store.write(key, {"heartbeat": now.isoformat(), "completed_at": now_fn().isoformat()})
    return RunOutcome(ran=True, reason="completed")


class LocalScheduler:
    """A ~60-line fallback loop, not a scheduler product. CI cron is
    unreliable at the margins — skipped runs under load, and hosted
    runners lack the network position some sources need."""

    def __init__(
        self, cron_next: Callable[[datetime], datetime], run_fn, *,
        _sleep=time.sleep, _now=None,
    ) -> None:
        self.cron_next = cron_next
        self.run_fn = run_fn
        self._sleep = _sleep
        self._now = _now or (lambda: datetime.now(UTC))
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run_forever(self) -> None:
        while not self._stop:
            self.sleep_until_next()
            if self._stop:
                return
            self.run_fn()

    def sleep_until_next(self) -> None:
        target = self.cron_next(self._now())
        while not self._stop:
            remaining = (target - self._now()).total_seconds()
            if remaining <= 0:
                return
            self._sleep(min(remaining, 30))

    def systemd_unit(self, *, exec_start: str) -> str:
        return (
            "[Unit]\nDescription=report-pipeline local scheduler\n\n"
            f"[Service]\nExecStart={exec_start}\nRestart=always\n\n"
            "[Install]\nWantedBy=multi-user.target\n"
        )

    def launchd_plist(self, *, label: str, program_args: list[str]) -> str:
        args_xml = "".join(f"<string>{a}</string>" for a in program_args)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<plist version="1.0"><dict>'
            f"<key>Label</key><string>{label}</string>"
            f"<key>ProgramArguments</key><array>{args_xml}</array>"
            "<key>RunAtLoad</key><true/>"
            "</dict></plist>\n"
        )

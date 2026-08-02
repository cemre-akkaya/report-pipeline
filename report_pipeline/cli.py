"""CLI: init | run daily/weekly | backfill | doctor | health.

Zero required dependencies means argparse, not click. Points --app at a
module exposing `collectors`, `build`, `outputs`, and optionally
`state_store` — the CLI cannot guess your data sources.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from .backfill import verify_and_backfill
from .collect import run_collectors
from .emit import EmitContext, build_run_result
from .health import DataHealth
from .payload import Payload
from .window import Window

INIT_TEMPLATE_MAIN = '''\
"""Scaffolded by `report-pipeline init`. Wire your own collectors, report
builder, and outputs, then run: python -m report_pipeline run daily --app main"""
from datetime import datetime, timezone

from report_pipeline.collect import CollectorResult
from report_pipeline.health import Health
from report_pipeline.payload import Payload
from report_pipeline.outputs import TerminalOutput, JsonOutput


class ExampleCollector:
    name = "example"

    def collect(self, window):
        return CollectorResult(
            data={"value": 42}, health=Health.OK,
            fetched_at=datetime.now(timezone.utc), source=self.name,
        )


collectors = [ExampleCollector()]


def build(inputs, window):
    payload = Payload({"example_value": inputs["example"].data["value"]})
    return payload.seal()


outputs = [TerminalOutput(), JsonOutput(path="report.json")]
'''

ENV_EXAMPLE = "# report-pipeline .env.example\n# EXAMPLE_API_TOKEN=\n"


def _load_app(app_path: str):
    module = importlib.import_module(app_path)
    for name in ("collectors", "build", "outputs"):
        if not hasattr(module, name):
            raise SystemExit(f"--app module '{app_path}' must expose `{name}`")
    return module


def _print(*args, err: bool = False) -> None:
    print(*args, file=sys.stderr if err else sys.stdout)


def cmd_init(args: argparse.Namespace) -> int:
    Path("main.py").write_text(INIT_TEMPLATE_MAIN)
    Path(".env.example").write_text(ENV_EXAMPLE)
    _print("wrote main.py and .env.example")
    return 0


def _run(app_path: str, window: Window, *, dry_run: bool, only: str | None,
        no_backfill: bool) -> int:
    module = _load_app(app_path)
    if not no_backfill and hasattr(module, "state_store"):
        report = verify_and_backfill(module.state_store, module.collectors, days=14)
        if report.repaired:
            _print(f"backfill repaired: {report.repaired}", err=True)
        if report.still_suspect:
            _print(f"backfill still suspect: {report.still_suspect}", err=True)

    results = run_collectors(module.collectors, window,
                             max_workers=getattr(module, "max_workers", 1))
    payload = module.build(results, window)
    if not isinstance(payload, Payload):
        raise SystemExit("build() must return a Payload")
    payload.seal()  # idempotent; the CLI enforces the sealed contract

    if dry_run:
        _print(str(payload.to_dict()))
        return 0

    only_list = only.split(",") if only else None
    run_result = build_run_result(module.outputs, payload, EmitContext(), only=only_list)
    if run_result.degraded_sources:
        _print(f"degraded sources: {run_result.degraded_sources}", err=True)
    for result in run_result.emit_results:
        status = "ok" if result.ok else "FAILED"
        _print(f"[{result.name}] {status}: {result.detail or result.error}")
    return 0 if run_result.ok else 1


def cmd_run_daily(args: argparse.Namespace) -> int:
    day = date.fromisoformat(args.date) if args.date else datetime.now(UTC).date()
    return _run(args.app, Window.day(day), dry_run=args.dry_run, only=args.only,
               no_backfill=args.no_backfill)


def cmd_run_weekly(args: argparse.Namespace) -> int:
    day = date.fromisoformat(args.week) if args.week else datetime.now(UTC).date()
    return _run(args.app, Window.week(day), dry_run=args.dry_run, only=args.only,
               no_backfill=args.no_backfill)


def cmd_backfill(args: argparse.Namespace) -> int:
    module = _load_app(args.app)
    if not hasattr(module, "state_store"):
        raise SystemExit(f"--app module '{args.app}' must expose `state_store` to run backfill")
    collectors = module.collectors
    if args.source:
        collectors = [c for c in collectors if c.name == args.source]
    report = verify_and_backfill(
        module.state_store, collectors, days=args.days,
        max_repairs=10_000 if args.force else 20,
    )
    _print(f"repaired={len(report.repaired)} skipped={len(report.skipped)} "
          f"still_suspect={len(report.still_suspect)} capped={report.capped}")
    return 1 if report.still_suspect else 0


def cmd_doctor(args: argparse.Namespace) -> int:
    module = _load_app(args.app)
    _print(f"app module: OK ({len(module.collectors)} collectors, "
          f"{len(module.outputs)} outputs)")
    if hasattr(module, "state_store"):
        _print("state store: present")
    for collector in module.collectors:
        try:
            collector.collect(Window.day(datetime.now(UTC).date()))
            _print(f"  [{collector.name}] reachable")
        except Exception as exc:  # noqa: BLE001 - doctor reports, doesn't crash
            _print(f"  [{collector.name}] UNREACHABLE: {exc}")
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    module = _load_app(args.app)
    results = run_collectors(module.collectors, Window.day(datetime.now(UTC).date()))
    data_health = DataHealth()
    for name, result in results.items():
        data_health.record(name, result.health, reason=result.reason)
        _print(f"{name}: {result.health.value} (fetched {result.fetched_at.isoformat()})")
    _print(f"worst: {data_health.worst().value}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="report-pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="scaffold collectors/reports/outputs + .env.example")

    p_run = sub.add_parser("run", help="run a report for a given period")
    run_sub = p_run.add_subparsers(dest="period", required=True)

    p_daily = run_sub.add_parser("daily")
    p_daily.add_argument("--app", required=True)
    p_daily.add_argument("--date")
    p_daily.add_argument("--dry-run", action="store_true")
    p_daily.add_argument("--only")
    p_daily.add_argument("--no-backfill", action="store_true")

    p_weekly = run_sub.add_parser("weekly")
    p_weekly.add_argument("--app", required=True)
    p_weekly.add_argument("--week")
    p_weekly.add_argument("--dry-run", action="store_true")
    p_weekly.add_argument("--only")
    p_weekly.add_argument("--no-backfill", action="store_true")

    p_backfill = sub.add_parser("backfill")
    p_backfill.add_argument("--app", required=True)
    p_backfill.add_argument("--days", type=int, default=30)
    p_backfill.add_argument("--source")
    p_backfill.add_argument("--force", action="store_true")

    p_doctor = sub.add_parser("doctor",
                              help="config present? state store writable? collectors reachable?")
    p_doctor.add_argument("--app", required=True)

    p_health = sub.add_parser("health", help="last run's data_health, per source")
    p_health.add_argument("--app", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        return cmd_init(args)
    if args.command == "run":
        return cmd_run_daily(args) if args.period == "daily" else cmd_run_weekly(args)
    if args.command == "backfill":
        return cmd_backfill(args)
    if args.command == "doctor":
        return cmd_doctor(args)
    if args.command == "health":
        return cmd_health(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

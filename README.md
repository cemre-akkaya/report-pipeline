# report-pipeline

[![CI](https://github.com/cemre-akkaya/report-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/cemre-akkaya/report-pipeline/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://pypi.org/project/report-pipeline/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Zero required dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen)](pyproject.toml)

Every company grows the same script. It starts as "email me yesterday's numbers." Eighteen months later it's 2,000 lines, one file, and it does six things at once: authenticates to four APIs, converts currencies, computes derived metrics, formats a terminal table, writes a spreadsheet, posts to chat, renders HTML. Changing the chat format risks breaking the spreadsheet. Adding a data source means touching the renderer. Nobody wants to be on call for it.

The fix is boring and well-known — separate acquisition, computation, and presentation — but nobody does it, because the framework overhead (Airflow, Dagster, Prefect) is wildly disproportionate to "one script, once a day." This is the missing middle: the three-layer skeleton, the conventions, and the two or three genuinely hard bits (backfill, data health, scheduler duplication), with **zero required dependencies**.

## The three layers

```
collectors/          ->   reports/            ->   outputs/
fetch raw facts           compute & derive        render & deliver
(I/O, retries)             (pure, testable)        (fan-out, best-effort)
```

**The rule that makes it work: exactly one payload.** Report builders return a single `Payload`. Every output consumes that same payload and nothing else — an output may not query a collector, and a collector may not know what will render it. `Payload` raises on mutation once sealed, and the fan-out runner passes a deep-frozen copy to each output. That's what buys the property you actually want: **adding a new delivery surface is a new file and zero edits elsewhere.**

## Quickstart

```python
from datetime import datetime, timezone
from report_pipeline import Payload, run_collectors
from report_pipeline.outputs import TerminalOutput, JsonOutput
from report_pipeline.window import Window

results = run_collectors(my_collectors, Window.day(datetime.now(timezone.utc).date()))
payload = Payload({"revenue": results["orders"].data["revenue"]}).seal()

for output in (TerminalOutput(), JsonOutput(path="report.json")):
    output.emit(payload, ctx=None)
```

```
report-pipeline init                      # scaffold collectors/ reports/ outputs/ + .env.example
report-pipeline run daily --app main [--dry-run] [--only terminal,json] [--no-backfill]
report-pipeline backfill --app main --days 30
```

## Collectors: I/O and nothing else

A collector that computes a margin is a bug — that belongs in the report layer, where it's testable without a network. Every collector runs inside `run_collectors()`, wrapped in try/except. **One collector failing must never abort the run** — a partial report delivered on time beats a complete report delivered never. Failures become `Health.UNAVAILABLE` entries in the payload, not exceptions. Concurrency is opt-in (default `max_workers=1`, deterministic ordering, readable logs).

## Reports: the purity rule

Pure functions: `build(inputs, window) -> Payload`. No network, no clock — `window` carries the dates. This is where period-over-period deltas, ratios, and rollups happen, and it's the layer that's trivially testable, which is why 90% of your tests should live here. `pct_change(cur, prev)` returns `None` on a zero or missing base, **never** `0.0`, never `inf` — everyone writes this helper badly, so it ships correctly.

## Outputs: best-effort, isolated fan-out

Shipped: `TerminalOutput` (aligned tables, ANSI when a TTY), `HtmlOutput` (single self-contained file, no CDN), `JsonOutput`, `SheetsOutput` (adapter interface — pair with [sheets-report-kit](https://github.com/cemre-akkaya/sheets-report-kit)), `WebhookOutput` (chat-agnostic, takes a formatter callable), `NarrativeOutput`. Each output's failure is caught, logged, and reported in the run summary — chat being down must not stop the spreadsheet from updating. `RunResult.ok` is true only if every output succeeded, and the CLI exit code reflects it, so CI can still fail loudly.

## Data health: the section people will link to

**This is the detail most pipelines get wrong, and the one that turns a reporting bug into a business decision made on a lie.**

A collector fails. Someone writes `data.get("revenue", 0)`. Zero flows downstream. The terminal table shows `0`. The chart plots a cliff. The narrative generator — the part that gets read — writes *"Demand collapsed in the northern region; recommend pausing spend."* Nothing collapsed. An API returned 503.

Zero is not a null. Every `CollectorResult` carries a `Health` (`OK | PARTIAL | UNAVAILABLE | STALE | NOT_APPLICABLE`), merged into `payload["data_health"]` by the worst status among contributing collectors. A metric whose inputs are `UNAVAILABLE` is never computed — `pct_change(None, x)` is `None`, and a derived metric with a `None` input inherits that health rather than becoming a silently wrong ratio. The run summary leads with degradation: `RunResult.degraded_sources` prints first, before any numbers.

## Self-healing backfill: why it beats retries

Retries handle the failure you can see: the call raised, you try again. The failure that actually destroys trust is **silent and partial** — a `200` with an empty result set because an upstream job hadn't finished, a warehouse view lagging six hours so yesterday's row gets written as a real, plausible, *wrong* number. The run "succeeds," exits `0`, nobody is paged. You find out five weeks later when someone asks why the March chart has a notch. Retries cannot fix this — there was no error to retry.

The fix: stop treating a run as a one-shot write and start treating it as an assertion about a trailing window. On every run, `verify_and_backfill()` re-checks the last N days and repairs anything that looks wrong:

- missing entirely, or
- zero on a metric declared `never_zero`, or
- below `anomaly_floor_frac` (default 0.3) of that source's own trailing median **while peer sources on the same date are healthy** — a single source diverging from itself is the signature of a partial failure, and it's the check that catches what the other two miss, or
- written while its own health was `PARTIAL`, `STALE`, or `UNAVAILABLE`.

Guard rails: repairs are capped per run and the skipped count is logged, so an empty upstream doesn't trigger a 90-day re-query storm. **A repair is only upserted if it comes back `Health.OK`** — never destroy a good value with a worse one. Upserts are idempotent, keyed on `(source, date)`: re-running any date any number of times converges to the same state. Every repair is reported, loudly, in `BackfillReport` — silent self-healing is how you never learn your upstream is unreliable.

## Scheduling: two schedulers, one lock

The job runs in CI (cron) and, realistically, also on someone's machine, because CI cron is unreliable at the margins. Support both explicitly: one entry point, no branching on `if os.environ.get("CI")` inside business logic. `run_once(job_id, window, store)` records a completion marker; if both schedulers fire, the second sees the marker and exits `"already completed"`. A crashed run's lock expires (`lock_ttl`, default 2h) rather than wedging the job forever.

**Because backfill exists, a missed run is a non-event.** The local fallback doesn't need to detect that CI skipped Tuesday — it runs Wednesday, the trailing-window verification finds Tuesday missing, and repairs it. That reframes scheduling from "must not miss" to "eventually consistent," a much cheaper property to buy.

## Narrative generation

Optional, health-gated. `narrate(payload, client, spec)` summarizes deterministically first (never serializes the whole payload — token bloat, hallucinated precision), then prompts. Metrics whose health isn't `OK` are passed as `{"value": null, "status": "unavailable", "reason": "..."}`, never `0`, never omitted — omitting is as bad as zeroing, because the model infers absence means nothing happened. A deterministic post-check scans the generated text for decline language ("dropped", "collapsed") co-occurring with any non-`OK` metric; on a hit it regenerates once with the violation quoted back, and falls back to the deterministic summary if it recurs. A guard you can test beats a prompt you hope holds. Narrative failure is non-fatal: log, ship the report anyway.

## Non-goals

Not an orchestrator — no DAG engine, no distributed execution, no backfill server, no UI; cron or CI runs it. No transformation DSL — report builders are plain Python functions. No connectors in core — vendor collectors live in your repo. No metrics store — state is a directory of JSON, deliberately, inspectable with `grep`. Not async, not parallel by default. **When you should use a real orchestrator instead:** dozens of interdependent jobs, cross-job DAG scheduling, a team that already runs Airflow for other things.

## Development

```
pip install -e ".[dev]"
pytest        # FakeCollector throughout; the backfill suite is the crown jewel
```

MIT license.

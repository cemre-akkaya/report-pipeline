"""report-pipeline: collectors -> report builder -> outputs, with
self-healing backfill instead of a 2,000-line script."""

from __future__ import annotations

from .backfill import BackfillReport, Cell, StateStore, default_suspect_check, verify_and_backfill
from .collect import Collector, CollectorError, CollectorResult, retry, run_collectors
from .emit import EmitContext, EmitResult, Output, RunResult, build_run_result, run_outputs
from .env import MissingConfig, config_scope, load_dotenv, optional_env, redact, require_env
from .health import DataHealth, Health, worse
from .narrate import LLMClient, MetricSpec, Narrative, NarrativeSpec, narrate, summarize
from .payload import Payload, PayloadFrozenError
from .report import ReportBuilder, pct_change, rank_by_delta, rollup, safe_div
from .schedule import FileLockStore, LocalScheduler, LockStore, RunOutcome, run_once
from .state import JsonStateStore, SheetClient, SheetStateStore
from .window import Window

__version__ = "0.1.0"

__all__ = [
    "BackfillReport",
    "Cell",
    "Collector",
    "CollectorError",
    "CollectorResult",
    "DataHealth",
    "EmitContext",
    "EmitResult",
    "FileLockStore",
    "Health",
    "JsonStateStore",
    "LLMClient",
    "LocalScheduler",
    "LockStore",
    "MetricSpec",
    "MissingConfig",
    "Narrative",
    "NarrativeSpec",
    "Output",
    "Payload",
    "PayloadFrozenError",
    "ReportBuilder",
    "RunOutcome",
    "RunResult",
    "SheetClient",
    "SheetStateStore",
    "StateStore",
    "Window",
    "build_run_result",
    "config_scope",
    "default_suspect_check",
    "load_dotenv",
    "narrate",
    "optional_env",
    "pct_change",
    "rank_by_delta",
    "redact",
    "require_env",
    "retry",
    "rollup",
    "run_collectors",
    "run_once",
    "run_outputs",
    "safe_div",
    "summarize",
    "verify_and_backfill",
    "worse",
]

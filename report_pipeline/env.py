"""Zero-dependency .env loader. Small, but the first thing every user
touches, so the semantics have to be exactly right."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")

_ENV_PATH_VAR = "REPORT_PIPELINE_ENV"


class MissingConfig(Exception):
    def __init__(self, keys: list[str]) -> None:
        self.keys = keys
        super().__init__(f"missing required config keys: {', '.join(keys)}")


def redact(value: str) -> str:
    """First 3 and last 2 chars. The library must have no code path that
    prints a secret in full."""
    if len(value) <= 5:
        return "*" * len(value)
    return f"{value[:3]}{'*' * (len(value) - 5)}{value[-2:]}"


def _resolve_path(path: str | None) -> Path | None:
    if path is not None:
        return Path(path)
    env_path = os.environ.get(_ENV_PATH_VAR)
    if env_path:
        return Path(env_path)
    # searched relative to cwd — "next to the caller's module" is approximated
    # by cwd, which is the common case for a script invoked from its own dir
    candidate = Path.cwd() / ".env"
    return candidate if candidate.exists() else None


def _parse_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    stripped = stripped.removeprefix("export ")
    if "=" not in stripped:
        return None
    key, _, raw_value = stripped.partition("=")
    key = key.strip()
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace("\\n", "\n").replace("\\t", "\t")
        value = inner
    return key, value


def load_dotenv(path: str | None = None, *, override: bool = False) -> dict[str, str]:
    """Real environment variables always win unless override=True. Getting
    this backwards is a classic and confusing bug: it's what makes the
    same code work locally with a .env and in CI with secrets."""
    resolved = _resolve_path(path)
    loaded: dict[str, str] = {}
    if resolved is None or not resolved.exists():
        return loaded
    for line in resolved.read_text().splitlines():
        parsed = _parse_line(line)
        if parsed is None:
            continue
        key, value = parsed
        loaded[key] = value
        if override or key not in os.environ:
            os.environ[key] = value
    return loaded


class _ConfigScope:
    def __init__(self) -> None:
        self.missing: list[str] = []

    def require(self, key: str, cast: Callable[[str], T] = str) -> T | None:
        raw = os.environ.get(key)
        if raw is None:
            self.missing.append(key)
            return None
        return cast(raw)


_active_scope: _ConfigScope | None = None


class config_scope:
    """Collect every missing key across a block so a fresh contributor sees
    all five missing variables on the first run instead of five runs."""

    def __enter__(self) -> None:
        global _active_scope
        _active_scope = _ConfigScope()

    def __exit__(self, exc_type, exc, tb) -> bool:
        global _active_scope
        scope = _active_scope
        _active_scope = None
        if scope is not None and scope.missing and exc_type is None:
            raise MissingConfig(scope.missing)
        return False


def require_env(key: str, cast: Callable[[str], T] = str) -> T:
    if _active_scope is not None:
        value = _active_scope.require(key, cast)
        return value  # type: ignore[return-value]
    raw = os.environ.get(key)
    if raw is None:
        raise MissingConfig([key])
    return cast(raw)


def optional_env(key: str, default: T = None, cast: Callable[[str], T] = str) -> T:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return cast(raw)

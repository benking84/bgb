from __future__ import annotations

from datetime import datetime, timezone

from croniter import croniter

from bgb.errors import ConfigError
from bgb.util import parse_time


def validate_schedule(expression: str) -> None:
    if expression and not croniter.is_valid(expression):
        raise ConfigError(f"schedule is not a 5-field cron expression: {expression}")


def is_due(expression: str, created_at: str, last_started: str | None, now: datetime) -> bool:
    if not expression:
        return False
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    base = parse_time(last_started) if last_started else parse_time(created_at)
    nxt = croniter(expression, _naive(base)).get_next(datetime)
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=timezone.utc)
    return nxt <= now


def _naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)

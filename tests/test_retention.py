from datetime import datetime, timedelta, timezone

import pytest

from bgb.errors import ConfigError
from bgb.retention import Stamp, describe_retention, filesets_to_delete, parse_retention
from bgb.schedule import is_due


def stamp(hours_ago: float, ident: str, now: datetime) -> Stamp:
    return Stamp(ident, now - timedelta(hours=hours_ago))


def test_smart_retention_buckets():
    now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    # Ages chosen so the 1-day bucket drops the 6h copy and the outer frame drops 800d.
    ages = [
        (0, "newest"),
        (6, "h6"),
        (20, "h20"),
        (24 * 3, "d3"),
        (24 * 10, "d10"),
        (24 * 20, "d20"),
        (24 * 40, "d40"),
        (24 * 200, "d200"),
        (24 * 800, "d800"),
    ]
    filesets = [stamp(age, ident, now) for age, ident in ages]
    deleted = set(filesets_to_delete(filesets, "policy:1W:1D,4W:1W,12M:1M", now))
    assert deleted == {"h6", "d800"}


def test_keep_versions_and_keep_time_never_drop_the_last_copy():
    now = datetime(2026, 10, 30, tzinfo=timezone.utc)
    filesets = [stamp(24 * day, f"d{day}", now) for day in (1, 10, 40, 80)]
    assert filesets_to_delete(filesets, "versions:2", now) == ["d40", "d80"]
    assert filesets_to_delete(filesets, "time:30D", now) == ["d40", "d80"]
    only = [stamp(24 * 400, "ancient", now)]
    assert filesets_to_delete(only, "time:30D", now) == []
    assert filesets_to_delete(only, "time:30D", now, allow_full_removal=True) == ["ancient"]


def test_retention_parser_rejects_bad_frames():
    with pytest.raises(ConfigError):
        parse_retention("policy:1W")
    with pytest.raises(ConfigError):
        parse_retention("policy:1D:1W")
    with pytest.raises(ConfigError):
        parse_retention("versions:0")
    assert "newest" in describe_retention("policy:1W:1D,4W:1W,12M:1M").lower()
    assert parse_retention("").kind == "none"


def test_schedule_is_due_only_after_the_next_tick():
    created = "2026-10-30T00:00:00.000000Z"
    now = datetime(2026, 10, 30, 0, 30, tzinfo=timezone.utc)
    assert is_due("0 2 * * *", created, None, now) is False
    later = datetime(2026, 10, 30, 3, 0, tzinfo=timezone.utc)
    assert is_due("0 2 * * *", created, None, later) is True
    assert is_due("0 2 * * *", created, "2026-10-30T02:00:00.000000Z", later) is False

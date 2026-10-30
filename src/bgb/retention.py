from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bgb.errors import ConfigError

_UNITS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "D": 86400,
    "W": 7 * 86400,
    "M": 30 * 86400,
    "Y": 365 * 86400,
}
_SPAN = re.compile(r"(\d+)([smhDWMY])")


@dataclass(frozen=True)
class Frame:
    timeframe_seconds: int
    interval_seconds: int
    timeframe_unlimited: bool
    keep_all: bool


@dataclass(frozen=True)
class Retention:
    kind: str
    count: int = 0
    seconds: int = 0
    frames: tuple[Frame, ...] = ()


@dataclass(frozen=True)
class Stamp:
    id: str
    when: datetime


def _span(token: str) -> tuple[bool, int]:
    if token == "U":
        return True, 0
    match = _SPAN.fullmatch(token)
    if not match:
        raise ConfigError(f"bad retention duration {token!r}")
    return False, int(match.group(1)) * _UNITS[match.group(2)]


def parse_retention(spec: str) -> Retention:
    text = (spec or "").strip()
    if not text or text == "none":
        return Retention("none")
    if text.startswith("versions:"):
        try:
            count = int(text.split(":", 1)[1])
        except ValueError as exc:
            raise ConfigError("keep-versions must be an integer") from exc
        if count < 1:
            raise ConfigError("keep-versions must be at least 1")
        return Retention("versions", count=count)
    if text.startswith("time:"):
        unlimited, seconds = _span(text.split(":", 1)[1])
        if unlimited or seconds <= 0:
            raise ConfigError("keep-time must be a positive duration such as 30D")
        return Retention("time", seconds=seconds)
    if text.startswith("policy:"):
        return Retention("policy", frames=tuple(_frames(text.split(":", 1)[1])))
    raise ConfigError(
        "retention must be versions:N, time:30D, policy:1W:1D,4W:1W,12M:1M, or empty"
    )


def _frames(body: str) -> list[Frame]:
    frames: list[Frame] = []
    parts = [part.strip() for part in body.split(",") if part.strip()]
    if not parts:
        raise ConfigError("retention policy is empty")
    for part in parts:
        pieces = part.split(":")
        if len(pieces) != 2:
            raise ConfigError(f"retention frame {part!r} must look like 1W:1D")
        timeframe_unlimited, timeframe = _span(pieces[0])
        keep_all, interval = _span(pieces[1])
        if (
            not keep_all
            and not timeframe_unlimited
            and interval >= timeframe
        ):
            raise ConfigError(f"interval cannot be larger than its timeframe ({part})")
        frames.append(
            Frame(
                timeframe_seconds=timeframe,
                interval_seconds=interval,
                timeframe_unlimited=timeframe_unlimited,
                keep_all=keep_all,
            )
        )
    return frames


def describe_retention(spec: str) -> str:
    policy = parse_retention(spec)
    if policy.kind == "none":
        return "Keep every version."
    if policy.kind == "versions":
        return f"Keep the {policy.count} newest versions."
    if policy.kind == "time":
        days = policy.seconds / 86400
        if days.is_integer():
            return f"Keep versions from the last {int(days)} days, and always the newest."
        return "Keep versions newer than the configured age, and always the newest."
    chunks = []
    for frame in policy.frames:
        window = "all time" if frame.timeframe_unlimited else _human(frame.timeframe_seconds)
        if frame.keep_all:
            chunks.append(f"keep every version for {window}")
        else:
            chunks.append(f"for {window}, keep one version each {_human(frame.interval_seconds)}")
    return "Smart retention: " + "; ".join(chunks) + ". The newest version is always kept."


def _human(seconds: int) -> str:
    for unit, size in (("years", _UNITS["Y"]), ("months", _UNITS["M"]), ("weeks", _UNITS["W"]), ("days", _UNITS["D"]), ("hours", _UNITS["h"])):
        if seconds % size == 0 and seconds >= size:
            count = seconds // size
            label = unit[:-1] if count == 1 else unit
            return f"{count} {label}"
    return f"{seconds} seconds"


def filesets_to_delete(
    filesets: list[Stamp],
    spec: str,
    now: datetime,
    *,
    allow_full_removal: bool = False,
) -> list[str]:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    policy = parse_retention(spec)
    if not filesets or policy.kind == "none":
        return []
    ordered = sorted(filesets, key=lambda item: (item.when, item.id), reverse=True)
    if policy.kind == "versions":
        delete = [item.id for item in ordered[policy.count :]]
    elif policy.kind == "time":
        cutoff = now - timedelta(seconds=policy.seconds)
        delete = [item.id for item in ordered if item.when < cutoff]
    else:
        delete = _policy_delete(ordered, policy.frames, now, allow_full_removal)
    if not allow_full_removal and len(delete) >= len(filesets):
        newest = ordered[0].id
        delete = [item for item in delete if item != newest]
    return delete


def _policy_delete(
    ordered_desc: list[Stamp],
    frames: tuple[Frame, ...],
    now: datetime,
    allow_full_removal: bool,
) -> list[str]:
    """Apply a bucket retention policy.

    The newest version is held aside. Each timeframe is applied from smallest
    to largest, consuming backups that fall inside it. Within a frame, backups
    are walked oldest-first and kept when they are at least ``interval`` after
    the previous keep. Backups outside every frame are deleted.
    """
    if not ordered_desc:
        return []
    newest = ordered_desc[0]
    remaining = list(ordered_desc[1:])
    delete: list[str] = []
    delete_newest = allow_full_removal
    for frame in sorted(frames, key=lambda item: (item.timeframe_unlimited, item.timeframe_seconds)):
        if frame.timeframe_unlimited:
            bound = datetime.min.replace(tzinfo=timezone.utc)
        else:
            bound = now - timedelta(seconds=frame.timeframe_seconds)
        in_frame: list[Stamp] = []
        while remaining and remaining[0].when >= bound:
            in_frame.append(remaining.pop(0))
        in_frame.reverse()
        last_kept: Stamp | None = None
        interval = timedelta(seconds=frame.interval_seconds)
        for fileset in in_frame:
            if last_kept is None or frame.keep_all or (fileset.when - last_kept.when) >= interval:
                last_kept = fileset
            else:
                delete.append(fileset.id)
        delete_newest = delete_newest and newest.when < bound
    delete.extend(item.id for item in remaining)
    if delete_newest:
        delete.append(newest.id)
    return delete

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import TypeVar

T = TypeVar("T")


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_time(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def from_dict(cls: type[T], data: dict) -> T:
    names = {field.name for field in dataclasses.fields(cls)}  # type: ignore[arg-type]
    return cls(**{key: value for key, value in data.items() if key in names})


def safe_path(path: str) -> None:
    if not path or path.startswith("/") or "\\" in path:
        raise ValueError(f"unsafe backup path: {path!r}")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"unsafe backup path: {path!r}")
